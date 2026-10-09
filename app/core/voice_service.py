"""
Maxi Integrated Voice Push-to-Talk & Wake Word Auto-Catch Service
Runs as an embedded background voice engine inside the Maxi daemon.

Capabilities:
1. Hands-Free Wake Word Auto-Catch:
   Continuously listens for "Hey Maxi" or "Hey Siri".
   When detected, prefixes the command with "Hey Maxi," and activates the agent function.
2. Hardware Push-to-Talk:
   Hold Right Option (macOS) or Control + Space (Windows/Linux) to speak, release to execute.
3. Tactile 3-chime audio pipeline and real-time WebSocket HUD broadcasting.
"""

import io
import os
import sys
import time
import wave
import queue
import asyncio
import logging
import threading
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List, Deque
from collections import deque

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
from app.core.wake_word import parse_wake_word, format_prefixed_prompt

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
    Unified Voice Service combining:
    1. Background Hands-Free Wake Word Auto-Catch ("Hey Maxi" / "Hey Siri")
    2. Global Push-to-Talk Hotkey (Right Option / Control + Space)
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

        # Wake Word audio queue and state
        self._wake_audio_queue: queue.Queue = queue.Queue(maxsize=200)
        self._wake_worker_thread: Optional[threading.Thread] = None
        self._wake_pending_command: bool = False
        self._wake_pending_time: float = 0.0

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
        """Unified audio capture callback feeding both PTT and Wake Word queues."""
        if status:
            logger.debug(f"Audio stream status: {status}")
        if np is None:
            return

        chunk = indata.copy()

        # 1. Active Push-to-Talk takes priority
        if self.is_ptt_recording:
            with self.lock:
                self.ptt_audio_buffer.append(chunk)
            return

        # 2. Feed Wake Word Auto-Catch queue if enabled and not currently dispatching
        if settings.enable_wake_word and not self._is_dispatching:
            try:
                self._wake_audio_queue.put_nowait(chunk)
            except queue.Full:
                try:
                    # Drop oldest frame to keep live buffer fresh
                    self._wake_audio_queue.get_nowait()
                    self._wake_audio_queue.put_nowait(chunk)
                except Exception:
                    pass

    # =========================================================================
    # Hands-Free Wake Word Auto-Catch Worker
    # =========================================================================

    def _wake_word_worker(self):
        """
        Background worker that continuously monitors microphone audio energy (RMS).
        Detects voice utterances, transcribes speech, and auto-catches "Hey Maxi" / "Hey Siri".
        """
        pre_roll: Deque[np.ndarray] = deque(maxlen=6)  # ~0.4s pre-speech buffer
        speech_chunks: List[np.ndarray] = []
        in_speech = False
        last_speech_time = 0.0
        speech_start_time = 0.0

        silence_threshold = getattr(settings, "wake_word_energy_threshold", 0.015)
        silence_duration = getattr(settings, "wake_word_silence_duration", 1.0)

        while self._running:
            try:
                chunk = self._wake_audio_queue.get(timeout=0.2)
            except queue.Empty:
                # Check for two-stage wake command timeout (e.g. User said "Hey Maxi" then stayed silent for >6s)
                if self._wake_pending_command and (time.time() - self._wake_pending_time > 6.0):
                    logger.debug("⏱️ Two-stage wake timeout expired without follow-up command.")
                    self._wake_pending_command = False
                    self._broadcast({"event": "voice_stop"})
                continue

            if self.is_ptt_recording or self._is_dispatching:
                pre_roll.clear()
                speech_chunks.clear()
                in_speech = False
                continue

            rms = float(np.sqrt(np.mean(chunk**2))) if np is not None else 0.0
            now = time.time()

            # State A: Listening for speech onset
            if not in_speech:
                pre_roll.append(chunk)
                if rms >= silence_threshold:
                    in_speech = True
                    speech_start_time = now
                    last_speech_time = now
                    speech_chunks = list(pre_roll)
                    pre_roll.clear()
            # State B: Gathering utterance
            else:
                speech_chunks.append(chunk)
                if rms >= silence_threshold:
                    last_speech_time = now

                silence_gap = now - last_speech_time
                total_duration = now - speech_start_time

                # Utterance complete when silence gap met or safety max cap (12s) reached
                if silence_gap >= silence_duration or total_duration >= 12.0:
                    in_speech = False
                    chunks_to_process = list(speech_chunks)
                    speech_chunks.clear()
                    pre_roll.clear()

                    if chunks_to_process:
                        threading.Thread(
                            target=self._process_wake_utterance,
                            args=(chunks_to_process,),
                            daemon=True,
                        ).start()

    def _process_wake_utterance(self, chunks: List[np.ndarray]):
        """Transcribes captured utterance and triggers agent execution if wake word matches."""
        if not chunks or np is None:
            return

        audio_data = np.concatenate(chunks, axis=0)
        # Filter out transient clicks / bumps (< 350ms)
        if len(audio_data) < SAMPLE_RATE * 0.35:
            return

        transcript = self._transcribe(audio_data)
        if not transcript or transcript.strip() in (".", "...", "!", "?"):
            return

        logger.debug(f"🎙️ Ambient Speech Utterance: \"{transcript}\"")

        # Case 1: Waiting for command after previous "Hey Maxi" wake trigger
        if self._wake_pending_command:
            self._wake_pending_command = False
            logger.info(f"🗣️ Follow-Up Voice Command: \"{transcript}\"")

            prefixed_prompt = (
                format_prefixed_prompt(transcript)
                if settings.wake_word_auto_prefix
                else transcript
            )
            self._dispatch_command(prefixed_prompt, source="voice:wake_word", trigger_transcript=transcript)
            return

        # Case 2: Standard wake word detection in utterance
        parsed = parse_wake_word(transcript, settings.get_wake_words_list())
        if not parsed:
            # Utterance did not contain authorized wake word; silently discard
            logger.debug(f"Non-wake speech discarded: \"{transcript}\"")
            return

        matched_wake_word, command = parsed
        logger.info(f"⚡ Wake Word Auto-Catch: '{matched_wake_word}' detected in \"{transcript}\"")

        # Audible tactile feedback immediately upon catching wake word
        play_sound(settings.voice_start_sound)
        self._broadcast({
            "event": "wake_word_detected",
            "wake_word": matched_wake_word,
            "transcript": transcript,
        })
        self._broadcast({"event": "voice_start"})

        # Subcase 2A: Utterance already contained the command (e.g. "Hey Maxi, open Safari")
        if command and len(command.strip()) > 1:
            prefixed_prompt = (
                format_prefixed_prompt(command)
                if settings.wake_word_auto_prefix
                else f"Hey Maxi, {command.strip()}"
            )
            self._dispatch_command(prefixed_prompt, source="voice:wake_word", trigger_transcript=transcript)
        # Subcase 2B: User spoke only the wake word (e.g. "Hey Maxi") -> wait for command
        else:
            logger.info("🎙️ Wake word detected without immediate command. Listening for command...")
            self._wake_pending_command = True
            self._wake_pending_time = time.time()
            show_notification(
                title="Maxi Voice 🎙️",
                message="Listening for your command...",
                subtitle="Say your command now"
            )

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

            # Suspend two-stage wake if hotkey pressed
            self._wake_pending_command = False

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

        # Format prompt with 'Hey Maxi,' prefix if enabled
        prefixed_prompt = (
            format_prefixed_prompt(transcript)
            if settings.wake_word_auto_prefix
            else transcript
        )

        self._dispatch_command(prefixed_prompt, source="voice:hotkey", trigger_transcript=transcript)

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
            "prompt": "Computer assistant voice command: Hey Maxi, Hey Siri.",
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

    def _dispatch_command(self, prompt: str, source: str = "voice:wake_word", trigger_transcript: str = ""):
        """Dispatches formatted voice prompt to the main Maxi agent."""
        from app.core.agent import agent

        self._is_dispatching = True
        t0 = time.perf_counter()
        agent_output = ""
        tools_used = []

        logger.info(f"⚡ Activating Maxi Agent Function with prompt: \"{prompt}\" (source: {source})")

        try:
            if self._loop and self._loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    agent.run(prompt=prompt, source=source),
                    self._loop,
                )
                result = future.result(timeout=35)
                agent_output = result.get("output", "")
                tools_used = result.get("tools_used", [])
            else:
                result = asyncio.run(agent.run(prompt=prompt, source=source))
                agent_output = result.get("output", "")
                tools_used = result.get("tools_used", [])
        except Exception as e:
            logger.error(f"Error dispatching voice command to main agent: {e}")
            agent_output = f"Execution error: {str(e)}"
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
        """Starts the unified Push-to-Talk hotkey listener and Wake Word auto-catch stream."""
        self._loop = loop
        self._running = True

        # 1. Start continuous audio stream if sounddevice is available
        if sd is not None:
            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self._stream.start()

                # Start Wake Word Auto-Catch background worker
                if settings.enable_wake_word:
                    self._wake_worker_thread = threading.Thread(
                        target=self._wake_word_worker,
                        daemon=True,
                    )
                    self._wake_worker_thread.start()
                    logger.info(
                        f"✅ Hands-Free Wake Word Auto-Catch active: "
                        f"Say {', '.join(settings.get_wake_words_list())} to trigger."
                    )
                    if settings.wake_word_auto_prefix:
                        logger.info("   Commands are automatically prefixed with 'Hey Maxi,' upon activation.")
            except Exception as e:
                logger.warning(f"Could not open microphone audio stream: {e}. Voice capture disabled.")
        else:
            logger.info("ℹ️ sounddevice audio backend unavailable. Voice capture disabled.")

        # 2. Start global Push-to-Talk hotkey listener
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
        """Gracefully stops all audio streams, listeners, and worker threads."""
        self._running = False
        self._wake_pending_command = False

        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        logger.info("Maxi Voice & Wake Word service stopped.")


voice_service = MaxiVoiceService()
