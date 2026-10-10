"""
Maxi Integrated Voice Push-to-Talk Service
Runs as an embedded voice engine inside the Maxi service.

Capabilities:
1. Hardware Push-to-Talk:
   Hold Right Option (macOS) or Control + Space (Windows/Linux) to speak, release to execute.
2. Tactile 3-chime audio pipeline, Siri TTS output, and real-time WebSocket HUD broadcasting.
"""

import io
import os
import sys
import time
import wave
import asyncio
import concurrent.futures
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
from app.core.tts import tts_service

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
                    subprocess.Popen(
                        [player, "-nodisp", "-autoexit", "-loglevel", "quiet", str(resolved)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
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
                winmm.mciSendStringW(f"play {alias} from 0", None, 0, None)
        except Exception:
            pass


def show_notification(title: str, message: str, subtitle: str = ""):
    """Display native notification banner."""
    if sys.platform == "darwin":
        clean_msg = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        clean_title = title.replace('"', '\\"')
        clean_sub = subtitle.replace('"', '\\"') if subtitle else ""
        sub_clause = f'subtitle "{clean_sub}"' if clean_sub else ""
        script = f'display notification "{clean_msg}" with title "{clean_title}" {sub_clause}'
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.Popen(["notify-send", title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        logger.info(f"[{title}] {message} ({subtitle})")


class MaxiVoiceService:
    """
    Push-to-Talk Voice Service (Right Option on macOS / Control + Space on Windows/Linux).
    Only captures microphone audio while the Push-to-Talk hotkey is held down.
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listener: Optional[keyboard.Listener] = None
        self._stream: Optional[sd.InputStream] = None
        self._running = False

        # Platform detection
        self.is_mac = sys.platform == "darwin"

        # Hotkey state
        self.ctrl_pressed = False
        self.space_pressed = False
        self.right_option_pressed = False
        self.last_key_press_time = 0.0
        self.last_key_release_time = 0.0

        # Push-to-Talk recording state
        self.is_ptt_recording = False
        self.ptt_press_time = 0.0
        self.ptt_audio_buffer: List[np.ndarray] = []
        self.last_interim_transcript: str = ""

        # Concurrency & dispatch state
        self._is_dispatching: bool = False
        self.lock = threading.RLock()

    @property
    def is_recording(self) -> bool:
        """Compatibility property for legacy HUD queries."""
        return self.is_ptt_recording

    def _broadcast(self, msg: dict):
        """Broadcasts voice state event to active WebSocket connections."""
        try:
            from app.api.websocket import ws_manager
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(ws_manager.broadcast(msg), self._loop)
        except Exception as e:
            logger.debug(f"Could not broadcast voice event: {e}")

    # =========================================================================
    # Keyboard Hotkey Identification
    # =========================================================================

    def _is_mac_right_option(self, key) -> bool:
        """Identifies Mac Right Option key via Key.alt_r, alt_gr, virtual keycode, or string."""
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

    def _is_hotkey_pref_right_option(self) -> bool:
        pref = (getattr(settings, "voice_hotkey", "auto") or "auto").lower()
        if pref == "auto":
            return self.is_mac
        return pref in ("right_option", "option_r", "alt_r", "option")

    def _is_hotkey_pref_ctrl_space(self) -> bool:
        pref = (getattr(settings, "voice_hotkey", "auto") or "auto").lower()
        if pref == "auto":
            return not self.is_mac
        return pref in ("ctrl_space", "control_space")

    def _is_hotkey_active(self) -> bool:
        if self._is_hotkey_pref_right_option() and self.right_option_pressed:
            return True
        if self._is_hotkey_pref_ctrl_space() and (self.ctrl_pressed and self.space_pressed):
            return True
        return False

    # =========================================================================
    # Audio Capture & Callback
    # =========================================================================

    def _audio_callback(self, indata, frames, time_info, status):
        """Audio capture callback active only during Push-to-Talk."""
        if status:
            logger.debug(f"Audio stream status: {status}")
        if np is None or not self.is_ptt_recording:
            return

        with self.lock:
            self.ptt_audio_buffer.append(indata.copy())

    def _open_mic_stream(self):
        """Opens microphone input stream on demand when Push-to-Talk starts."""
        if sd is None or self._stream is not None:
            return
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as e:
            logger.warning(f"Could not open microphone stream: {e}")
            self._stream = None

    def _close_mic_stream(self):
        """Closes microphone input stream immediately when Push-to-Talk ends."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    # =========================================================================
    # Push-to-Talk Recording Controls
    # =========================================================================

    def start_recording(self):
        """Starts Push-to-Talk audio gathering."""
        with self.lock:
            if self.is_ptt_recording:
                return
            self.is_ptt_recording = True
            self.ptt_audio_buffer = []
            self.ptt_press_time = time.time()

            # Interrupt any ongoing TTS speech if hotkey pressed
            tts_service.stop()
            self._open_mic_stream()

            play_sound(settings.voice_start_sound)
            self._broadcast({"event": "voice_start"})
            logger.info("🎙️ Push-to-Talk recording started (Hold key to speak)...")

    def cancel_recording(self):
        """Silently cancels Push-to-Talk without processing or playing finish chimes."""
        with self.lock:
            if not self.is_ptt_recording:
                return
            self.is_ptt_recording = False
            self.ptt_audio_buffer = []
            self._close_mic_stream()

        self._broadcast({"event": "voice_stop"})
        logger.debug("Voice recording cancelled (brief tap or abort).")

    def stop_recording(self):
        """Stops Push-to-Talk gathering and initiates execution."""
        chunks = []
        with self.lock:
            if not self.is_ptt_recording:
                return
            self.is_ptt_recording = False
            chunks = list(self.ptt_audio_buffer)
            self.ptt_audio_buffer = []
            self._close_mic_stream()

        play_sound(settings.voice_release_sound)
        self._broadcast({"event": "voice_stop"})

        if not chunks:
            return

        threading.Thread(target=self._process_ptt_recording, args=(chunks,), daemon=True).start()

    def _process_ptt_recording(self, chunks: List[np.ndarray]):
        if not chunks or np is None:
            return

        audio_data = np.concatenate(chunks, axis=0)
        if len(audio_data) < SAMPLE_RATE * 0.28:
            logger.debug("Audio input too brief (<280ms). Ignored.")
            return

        t0 = time.perf_counter()
        transcript = self._transcribe(audio_data)
        if not transcript or transcript in (".", "...", "!", "?"):
            logger.info("No recognizable speech detected.")
            return

        stt_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(f"🗣️ Push-to-Talk Transcript ({stt_ms}ms): \"{transcript}\"")

        self._dispatch_command(transcript, source="voice:hotkey", trigger_transcript=transcript)

    # =========================================================================
    # STT Transcription & Agent Execution
    # =========================================================================

    def _transcribe(self, audio_data: np.ndarray) -> str:
        """Sends captured audio to Voice STT (Groq Whisper-Turbo / OpenAI STT endpoint)."""
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
        data = {
            "model": settings.voice_model,
            "response_format": "json",
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, files=files, data=data)
                if resp.status_code == 200:
                    return resp.json().get("text", "").strip()
                logger.error(f"Voice transcription returned error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error calling voice transcription endpoint: {e}")
        return ""

    def _dispatch_command(self, prompt: str, source: str = "voice:hotkey", trigger_transcript: str = ""):
        """Dispatches formatted voice prompt to the main Maxi agent."""
        from app.core.agent import agent

        self._is_dispatching = True
        t0 = time.perf_counter()
        agent_output = ""
        tools_used = []

        logger.info(f"⚡ Activating Maxi Agent Function with prompt: \"{prompt}\" (source: {source})")

        timeout_s = getattr(settings, "agent_timeout_seconds", 90.0)
        try:
            if self._loop and self._loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    agent.run(prompt=prompt, source=source),
                    self._loop,
                )
                result = future.result(timeout=timeout_s)
                agent_output = result.get("output", "")
                tools_used = result.get("tools_used", [])
            else:
                result = asyncio.run(agent.run(prompt=prompt, source=source))
                agent_output = result.get("output", "")
                tools_used = result.get("tools_used", [])
        except (TimeoutError, concurrent.futures.TimeoutError, asyncio.TimeoutError):
            logger.error(f"Voice command timed out after {timeout_s}s: \"{prompt}\"")
            agent_output = f"Command timed out after {int(timeout_s)} seconds. Please try again."
        except Exception as e:
            err_desc = str(e).strip() or type(e).__name__
            logger.error(f"Error dispatching voice command to main agent: {err_desc}", exc_info=True)
            agent_output = f"Execution error: {err_desc}"
        finally:
            self._is_dispatching = False

        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(f"⚡ Maxi Voice Result ({total_ms}ms): {agent_output}")
        if tools_used:
            logger.info(f"🛠️ Tools executed: {', '.join(tools_used)}")

        # Broadcast result to frontend HUD
        self._broadcast({
            "event": "voice_result",
            "transcript": prompt,
            "output": agent_output,
            "tools": tools_used,
        })

        # Play completion chime
        play_sound(settings.voice_finish_sound)

        # Native desktop notification banner
        show_notification(
            title="Maxi Voice 🎙️",
            message=agent_output or "Command executed.",
            subtitle=prompt,
        )

        # Speak response aloud using Siri TTS
        if getattr(settings, "enable_tts", True) and agent_output:
            tts_service.speak(agent_output)

    # =========================================================================
    # Keyboard Event Handlers
    # =========================================================================

    def _on_press(self, key):
        if self._is_hotkey_pref_right_option() and self._is_mac_right_option(key):
            self.right_option_pressed = True

        if self._is_hotkey_pref_ctrl_space():
            if self._is_ctrl(key):
                self.ctrl_pressed = True
            elif self._is_space(key):
                self.space_pressed = True

        if self._is_hotkey_active():
            now = time.time()
            if now - self.last_key_press_time < 0.12:
                return
            self.last_key_press_time = now

            with self.lock:
                if not self.is_ptt_recording:
                    self.ptt_press_time = now
                    self.start_recording()

    def _on_release(self, key):
        was_recording = self.is_ptt_recording

        if self._is_hotkey_pref_right_option() and self._is_mac_right_option(key):
            self.right_option_pressed = False

        if self._is_hotkey_pref_ctrl_space():
            if self._is_ctrl(key):
                self.ctrl_pressed = False
            elif self._is_space(key):
                self.space_pressed = False

        if was_recording and not self._is_hotkey_active():
            now = time.time()
            if now - self.last_key_release_time < 0.10:
                return
            self.last_key_release_time = now

            with self.lock:
                if not self.is_ptt_recording:
                    return
                elapsed = time.time() - self.ptt_press_time
                if elapsed < 0.25:
                    logger.debug(f"⏱️ Hotkey released too quickly ({elapsed:.2f}s). Cancelling.")
                    self.cancel_recording()
                else:
                    logger.info(f"🎙️ Hotkey released ({elapsed:.2f}s). Processing speech...")
                    self.stop_recording()

    # =========================================================================
    # Service Lifecycle Management
    # =========================================================================

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Starts the global Push-to-Talk hotkey listener (mic opens only while hotkey is held)."""
        self._loop = loop
        self._running = True
        tts_service.set_broadcast_callback(self._broadcast)

        if getattr(settings, "enable_tts", True):
            logger.info(f"🔊 Siri TTS active: Voice '{settings.tts_voice}' @ {settings.tts_rate}wpm")

        if settings.enable_voice_hotkey and keyboard is not None:
            hotkey_name = "Right Option (⌥)" if self._is_hotkey_pref_right_option() else "Control + Space"
            try:
                self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
                self._listener.daemon = True
                self._listener.start()
                logger.info(f"✅ Push-to-Talk hotkey active: Hold {hotkey_name} to speak, release to execute.")
            except Exception as e:
                logger.warning(f"Voice hotkey listener could not start ({e}).")

    def stop(self):
        """Gracefully stops all audio streams and hotkey listeners."""
        self._running = False
        tts_service.stop()

        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

        self._close_mic_stream()
        logger.info("Maxi Voice service stopped.")


voice_service = MaxiVoiceService()

