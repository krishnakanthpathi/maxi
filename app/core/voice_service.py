"""
Maxi Integrated Voice Push-to-Talk Service
Runs as an embedded background listener inside the Maxi daemon.
Trigger: Hold [Control + Space], speak, release.
Audio STT: Transcribes audio via Voice endpoint (Groq Whisper-Turbo), then hands
the transcript directly to the Main Agent.
Web HUD: Broadcasts real-time voice events to connected clients over WebSockets.
"""

import io
import os
import sys
import time
import wave
import asyncio
import logging
import threading
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List

try:
    import numpy as np
except ImportError:
    np = None

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    from pynput import keyboard
except Exception:
    keyboard = None

import httpx

from app.config import settings

logger = logging.getLogger("maxi.voice")

SAMPLE_RATE = 16000
CHANNELS = 1


def resolve_sound_path(sound_name: str) -> Optional[Path]:
    """Resolves sound name from app/sounds directory, absolute path, or system fallback."""
    if not sound_name or sound_name.lower() in ("none", "off", "disabled"):
        return None
    # Direct path
    p = Path(sound_name)
    if p.exists() and p.is_file():
        return p

    # app/sounds/ directory
    sounds_dir = Path(__file__).resolve().parent.parent / "sounds"
    for ext in ("", ".mp3", ".wav", ".aiff", ".m4a", ".ogg"):
        cand = sounds_dir / f"{sound_name}{ext}"
        if cand.exists() and cand.is_file():
            return cand

    # macOS system sounds fallback
    if sys.platform == "darwin":
        cand = Path(f"/System/Library/Sounds/{sound_name}.aiff")
        if cand.exists():
            return cand
    return None


def play_sound(sound_name: str):
    """Play audio chime (macOS native afplay, Linux paplay/aplay, Windows winsound)."""
    resolved = resolve_sound_path(sound_name)
    if not resolved:
        return
    if sys.platform == "darwin":
        subprocess.Popen(["afplay", str(resolved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform.startswith("linux"):
        for player in ("paplay", "pw-play", "aplay", "canberra-gtk-play", "ffplay"):
            if shutil.which(player):
                if player == "ffplay":
                    subprocess.Popen([player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(resolved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen([player, str(resolved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
    elif sys.platform == "win32":
        try:
            if resolved.suffix.lower() == ".wav":
                import winsound
                winsound.PlaySound(str(resolved), winsound.SND_ASYNC | winsound.SND_FILENAME)
            else:
                import ctypes
                alias = f"maxi_{abs(hash(str(resolved))) % 100000}"
                winmm = ctypes.windll.winmm
                winmm.mciSendStringW(f'open "{resolved}" type mpegvideo alias {alias}', None, 0, None)
                winmm.mciSendStringW(f'play {alias} from 0', None, 0, None)
        except Exception:
            pass


def show_notification(title: str, message: str, subtitle: str = ""):
    """Display native notification banner."""
    if sys.platform == "darwin":
        clean_msg = message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
        clean_title = title.replace('"', '\\"')
        clean_sub = subtitle.replace('"', '\\"') if subtitle else ""
        sub_clause = f'subtitle "{clean_sub}"' if clean_sub else ""
        script = f'display notification "{clean_msg}" with title "{clean_title}" {sub_clause}'
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.Popen(["notify-send", title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        logger.info(f"[{title}] {message} ({subtitle})")


class VoiceHotkeyService:
    """Embedded global hotkey listener and audio capture pipeline with tap-to-lock support."""

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listener: Optional[keyboard.Listener] = None
        self._stream: Optional[sd.InputStream] = None

        # Platform & hotkey state
        self.is_mac = sys.platform == "darwin"
        self.ctrl_pressed = False
        self.space_pressed = False
        self.is_recording = False
        self.is_locked = False
        self.press_time = 0.0

        self.audio_buffer: List[np.ndarray] = []
        self.last_interim_transcript: str = ""
        self.speech_detected = False
        self.last_speech_time = 0.0
        self.last_key_press_time = 0.0
        self.last_key_release_time = 0.0
        self.lock = threading.RLock()

    def _broadcast(self, msg: dict):
        """Broadcasts voice state event to active WebSocket connections."""
        try:
            from app.api.websocket import ws_manager
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(ws_manager.broadcast(msg), self._loop)
        except Exception as e:
            logger.debug(f"Could not broadcast voice event: {e}")

    def _is_mac_right_option(self, key) -> bool:
        """Identifies Mac Right Option key via Key.alt_r, alt_gr, virtual keycode, or string representation."""
        if key in (keyboard.Key.alt_r, getattr(keyboard.Key, "alt_gr", None)):
            return True
        if hasattr(key, "name") and key.name in ("alt_r", "option_r", "alt_gr"):
            return True
        if hasattr(key, "vk") and key.vk in (61, 54):
            return True
        if str(key) in ("Key.alt_r", "Key.alt_gr"):
            return True
        if "<61>" in repr(key):
            return True
        return False

    def _is_ctrl(self, key) -> bool:
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return True
        if hasattr(key, "vk") and key.vk in (59, 62, 17, 162, 163):
            return True
        return False

    def _is_space(self, key) -> bool:
        if key == keyboard.Key.space:
            return True
        if hasattr(key, "vk") and key.vk in (49, 32):
            return True
        if hasattr(key, "char") and key.char == " ":
            return True
        return False

    def _audio_callback(self, indata, frames, time_info, status):
        if self.is_recording and np is not None:
            self.audio_buffer.append(indata.copy())
            rms = float(np.sqrt(np.mean(indata**2)))
            if rms >= settings.voice_silence_threshold:
                self.speech_detected = True
                self.last_speech_time = time.time()

    def start_recording(self):
        with self.lock:
            if self.is_recording:
                return
            if sd is None:
                logger.warning("Microphone recording unavailable (sounddevice not installed or no audio backend).")
                return
            self.is_recording = True
            self.audio_buffer = []
            self.speech_detected = False
            self.last_speech_time = time.time()
            self.press_time = time.time()

            play_sound(settings.voice_start_sound)
            self._broadcast({"event": "voice_start"})
            logger.info("🎙️ Voice recording started...")

            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    callback=self._audio_callback
                )
                self._stream.start()
                # Launch live speech streaming & silence detection worker
                threading.Thread(target=self._stream_transcription_worker, daemon=True).start()
            except Exception as e:
                logger.error(f"Failed to open microphone audio stream: {e}")
                self.is_recording = False
                self.is_locked = False
                self._broadcast({"event": "voice_stop"})

    def _stream_transcription_worker(self):
        """Continuously streams interim transcripts while user speaks and handles silence VAD endpointing."""
        last_text = ""
        last_transcript_time = time.time()
        time.sleep(0.3)
        while self.is_recording:
            now = time.time()

            # 1. Transcript stability endpointing (user finished speaking a sentence and paused for 1.0s)
            if last_text and settings.voice_auto_endpoint:
                if (now - self.press_time) > 1.2 and (now - last_transcript_time) >= 1.0:
                    logger.info(f"⏱️ Spoken command finalized (\"{last_text}\"). Auto-endpointing...")
                    self.stop_recording()
                    break

            # 2. Silence VAD Endpointing (auto-stop when silence detected after speaking)
            if self.speech_detected and settings.voice_auto_endpoint:
                silence_elapsed = now - self.last_speech_time
                if (now - self.press_time) > 0.8 and silence_elapsed >= settings.voice_silence_duration:
                    logger.info(f"⏱️ Voice silence detected ({silence_elapsed:.2f}s). Auto-endpointing...")
                    self.stop_recording()
                    break

            # 3. Idle timeout (no speech for 6s)
            if not self.speech_detected and (now - self.press_time) > 6.0:
                logger.info("⏱️ No speech detected within 6s timeout. Auto-canceling...")
                self.stop_recording()
                break

            # 4. Maximum utterance safety timeout (12s)
            if (now - self.press_time) > 12.0:
                logger.info("⏱️ Max recording duration (12s) reached. Auto-endpointing...")
                self.stop_recording()
                break

            # 5. Interim transcription
            chunks = []
            with self.lock:
                if not self.is_recording:
                    break
                if len(self.audio_buffer) >= 4:
                    chunks = list(self.audio_buffer)

            if chunks:
                audio_data = np.concatenate(chunks, axis=0)
                if len(audio_data) >= SAMPLE_RATE * 0.4:
                    interim = self._transcribe(audio_data)
                    clean = interim.strip()
                    if clean and clean != last_text and clean not in (".", "...", "!", "?"):
                        last_text = clean
                        last_transcript_time = time.time()
                        self.speech_detected = True
                        self.last_interim_transcript = clean
                        logger.info(f"🗣️ Live Voice Stream: \"{clean}\"")
                        self._broadcast({
                            "event": "voice_interim_transcript",
                            "transcript": clean
                        })

            time.sleep(0.3)

    def stop_recording(self):
        stream_to_stop = None
        chunks = []
        with self.lock:
            if not self.is_recording:
                return
            self.is_recording = False
            self.is_locked = False
            play_sound(settings.voice_release_sound)
            self._broadcast({"event": "voice_stop"})

            stream_to_stop = self._stream
            self._stream = None
            chunks = list(self.audio_buffer)
            self.audio_buffer = []

        # Stop audio stream outside the lock so no PortAudio deadlocks occur
        if stream_to_stop:
            try:
                stream_to_stop.stop()
                stream_to_stop.close()
            except Exception as e:
                logger.debug(f"Audio stream close error: {e}")

        if not chunks:
            return

        threading.Thread(target=self._process_recording, args=(chunks,), daemon=True).start()

    def _transcribe(self, audio_data: np.ndarray) -> str:
        """Sends captured audio to Voice/Groq Whisper endpoint."""
        api_key = settings.get_voice_api_key()
        if not api_key:
            logger.error("No VOICE_API_KEY or GROQ_API_KEY configured for speech transcription.")
            return ""

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            int16_data = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)
            wf.writeframes(int16_data.tobytes())
        wav_bytes = buf.getvalue()

        url = f"{settings.voice_base_url.rstrip('/')}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": ("command.wav", wav_bytes, "audio/wav")}
        data = {"model": settings.voice_model, "response_format": "json"}

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, files=files, data=data)
                if resp.status_code == 200:
                    return resp.json().get("text", "").strip()
                logger.error(f"Voice transcription returned error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error calling voice transcription endpoint: {e}")
        return ""

    def _process_recording(self, chunks: List[np.ndarray]):
        audio_data = np.concatenate(chunks, axis=0)
        # Filter out short taps (< 300 ms)
        if len(audio_data) < SAMPLE_RATE * 0.3:
            logger.debug("Audio input too brief (<300ms). Ignored.")
            return

        t0 = time.perf_counter()
        transcript = self._transcribe(audio_data)
        if not transcript or transcript in (".", "...", "!", "?"):
            transcript = self.last_interim_transcript
        if not transcript or transcript in (".", "...", "!", "?"):
            logger.info("No recognizable speech detected.")
            return

        stt_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(f"🗣️ Voice Transcript ({stt_ms}ms): \"{transcript}\"")

        # Hand directly to Main Agent
        from app.core.agent import agent
        agent_output = ""
        tools_used = []

        try:
            if self._loop and self._loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    agent.run(prompt=transcript, source="voice:hotkey"),
                    self._loop
                )
                result = future.result(timeout=30)
                agent_output = result.get("output", "")
                tools_used = result.get("tools_used", [])
            else:
                # Fallback if loop reference not active
                result = asyncio.run(agent.run(prompt=transcript, source="voice:hotkey"))
                agent_output = result.get("output", "")
                tools_used = result.get("tools_used", [])
        except Exception as e:
            logger.error(f"Error dispatching voice command to main agent: {e}")
            agent_output = f"Execution error: {str(e)}"

        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(f"⚡ Maxi Voice Result ({total_ms}ms): {agent_output}")
        if tools_used:
            logger.info(f"🛠️  Tools executed: {', '.join(tools_used)}")

        # Broadcast result to frontend HUD
        self._broadcast({
            "event": "voice_result",
            "transcript": transcript,
            "output": agent_output,
            "tools": tools_used
        })

        # Play completion chime AFTER result is ready
        play_sound(settings.voice_finish_sound)

        # Native macOS notification banner (full text)
        show_notification(
            title="Maxi Voice 🎙️",
            message=agent_output or "Command executed.",
            subtitle=transcript
        )

    def _on_press(self, key):
        now = time.time()
        if now - self.last_key_press_time < 0.08:
            return
        self.last_key_press_time = now

        # 1. Mac Right Option check
        if self.is_mac and self._is_mac_right_option(key):
            logger.info("🔑 Right Option key detected.")
            with self.lock:
                if self.is_recording and self.is_locked:
                    self.is_locked = False
                    self.stop_recording()
                    return
                if not self.is_recording:
                    self.press_time = time.time()
                    self.is_locked = False
                    self.start_recording()
            return

        # 2. Universal Control + Space check (works on Mac, Windows, Linux)
        if self._is_ctrl(key):
            self.ctrl_pressed = True
        elif self._is_space(key):
            self.space_pressed = True

        if self.ctrl_pressed and self.space_pressed:
            logger.info("🔑 Control + Space hotkey detected.")
            with self.lock:
                if self.is_recording and self.is_locked:
                    self.is_locked = False
                    self.stop_recording()
                    return
                if not self.is_recording:
                    self.press_time = time.time()
                    self.is_locked = False
                    self.start_recording()

    def _on_release(self, key):
        now = time.time()
        if now - self.last_key_release_time < 0.08:
            return
        self.last_key_release_time = now

        # 1. Mac Right Option release
        if self.is_mac and self._is_mac_right_option(key):
            with self.lock:
                if self.is_recording and not self.is_locked:
                    elapsed = time.time() - self.press_time
                    if elapsed < 0.4:
                        # Quick tap (<400ms) -> LOCK IN recording!
                        self.is_locked = True
                        logger.info("🔒 Voice recording locked in (tap hotkey again to send).")
                        self._broadcast({"event": "voice_locked", "locked": True})
                    else:
                        # Held down (>400ms) -> Push-to-Talk release!
                        self.stop_recording()
            return

        # 2. Universal Control + Space release
        was_recording = self.is_recording
        if self._is_ctrl(key):
            self.ctrl_pressed = False
        elif self._is_space(key):
            self.space_pressed = False

        if was_recording and not (self.ctrl_pressed and self.space_pressed):
            with self.lock:
                if self.is_recording and not self.is_locked:
                    elapsed = time.time() - self.press_time
                    if elapsed < 0.4:
                        self.is_locked = True
                        logger.info("🔒 Voice recording locked in (press hotkey again to send).")
                        self._broadcast({"event": "voice_locked", "locked": True})
                    else:
                        self.stop_recording()

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Starts the global Push-to-Talk / Lock-in voice listener thread."""
        if not settings.enable_voice_hotkey:
            logger.info("Voice push-to-talk hotkey is disabled (ENABLE_VOICE_HOTKEY=False).")
            return

        if keyboard is None:
            logger.info("ℹ️ pynput keyboard listener is unavailable. Text/chat mode is fully active.")
            return

        self._loop = loop
        hotkey_name = "Right Option" if self.is_mac else "Control + Space"
        logger.info(f"Initializing global {hotkey_name} voice listener (with tap-to-lock support)...")

        try:
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener.daemon = True
            self._listener.start()
            logger.info(f"✅ Voice hotkey active: Tap {hotkey_name} to lock-in recording (or hold to speak).")
        except Exception as e:
            logger.warning(f"Voice hotkey listener could not start ({e}). Text/chat mode is fully active.")

    def stop(self):
        """Stops the hotkey listener and audio capture."""
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        logger.info("Voice Push-to-Talk listener stopped.")


voice_service = VoiceHotkeyService()
