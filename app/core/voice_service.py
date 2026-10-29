"""
Maxi Integrated Voice Push-to-Talk & Willow Architecture Service
Runs as an embedded voice engine inside the Maxi service.

Willow-inspired Capabilities:
1. Hardware Push-to-Talk + Double-Tap Hands-Free Lock + Esc Abort (`RecordingHotkeyController`):
   - Hold Right Option (macOS) / Control + Space (Windows/Linux) to speak, release to execute.
   - Double-tap Right Option to lock hands-free recording; tap again to finish, or press Esc to abort.
2. Pre-Warmed STT Transport (`WarmTranscriptionConnection`):
   - Persistent HTTP keep-alive connection pool to eliminate TLS handshake latency on hotkey release.
3. Parallel Active Context Capture (`FocusedInputCapture` + `AXUIHelpers`):
   - Snapshots frontmost app, window title, URL, and highlighted text (`AXSelectedText`) on key-down (0ms added latency).
4. Whisper Vocabulary & Context Conditioning (`GlossaryManager`):
   - Injects custom glossary and active window proper nouns into Whisper's `prompt` parameter + post-STT replacements.
5. Automatic Audio Ducking (`PrivateDucker`):
   - Lowers system audio volume while recording and restores it upon release/cancel.
6. Real-Time 5-Band Audio Level Monitor (`AudioLevelMonitor`) & Siri TTS output.
"""

from __future__ import annotations

import io
import os
import re
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
    if sys.platform.startswith("linux"):
        if "DISPLAY" not in os.environ:
            os.environ["DISPLAY"] = ":0"
        if "XAUTHORITY" not in os.environ:
            import glob
            uid = os.getuid()
            auths = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth*") or glob.glob(f"/run/user/{uid}/.Xauthority*")
            if auths:
                os.environ["XAUTHORITY"] = auths[0]
            elif (Path.home() / ".Xauthority").exists():
                os.environ["XAUTHORITY"] = str(Path.home() / ".Xauthority")
        if "WAYLAND_DISPLAY" not in os.environ:
            w_disp = Path(f"/run/user/{os.getuid()}/wayland-0")
            if w_disp.exists():
                os.environ["WAYLAND_DISPLAY"] = "wayland-0"
    from pynput import keyboard
except Exception:
    keyboard = None

import httpx

from app.config import settings
from app.core.tts import tts_service
from app.core.context_capture import context_capturer, CapturedContext
from app.core.glossary import glossary_manager
from app.core.audio_ducker import audio_ducker
from app.core.text_injector import text_injector

logger = logging.getLogger("maxi.voice")

SAMPLE_RATE = 16000
CHANNELS = 1

DIRECT_DICTATION_REGEX = re.compile(
    r"^(?:dictate|type\s+this|paste\s+this|insert\s+this)[:,\s]+(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def resolve_sound_path(sound_name: str) -> Optional[Path]:
    """Resolves sound name from app/sounds directory, absolute path, or system fallback."""
    if not sound_name or sound_name.lower() in ("none", "off", "disabled"):
        return None
    p = Path(sound_name)
    if p.exists() and p.is_file():
        return p

    sounds_dir = Path(__file__).resolve().parent.parent / "sounds"
    for ext in ("", ".mp3", ".wav", ".aiff", ".m4a", ".ogg"):
        cand = sounds_dir / f"{sound_name}{ext}"
        if cand.exists() and cand.is_file():
            return cand

    if sys.platform == "darwin":
        cand = Path(f"/System/Library/Sounds/{sound_name}.aiff")
        if cand.exists():
            return cand
    return None


_last_sound_played_time = 0.0


def play_sound(sound_name: str):
    """Play audio chime with debounce to prevent overlapping audio glitches."""
    global _last_sound_played_time
    now = time.time()
    if now - _last_sound_played_time < 0.45:
        return
    _last_sound_played_time = now

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
    """Display native notification banner (disabled on macOS)."""
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.Popen(["notify-send", title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        logger.debug(f"[{title}] {message} ({subtitle})")


def compute_audio_levels(chunk: "np.ndarray", bars: int = 5) -> List[float]:
    """Computes normalized 5-bar waveform levels (0.10..1.0) from a float32 PCM chunk using speech frequency bands."""
    if np is None or chunk is None or len(chunk) == 0:
        return [0.1] * bars
    flat = chunk.flatten().astype(np.float32)
    rms = float(np.sqrt(np.mean(np.square(flat))))
    if rms < 0.003:
        return [0.1] * bars

    n_samples = len(flat)
    window = np.hanning(n_samples).astype(np.float32)
    fft_vals = np.abs(np.fft.rfft(flat * window))
    n_bins = len(fft_vals)

    # 16kHz sample rate: Nyquist = 8000 Hz. Each bin = 8000 / (n_bins - 1)
    # Define 5 speech frequency ranges matching human vocal resonance:
    # Band 0: Fundamental pitch (70 - 250 Hz)
    # Band 1: First vowel formant (250 - 650 Hz)
    # Band 2: Second vowel formant (650 - 1600 Hz)
    # Band 3: Third formant / consonant clarity (1600 - 3500 Hz)
    # Band 4: Sibilants / fricatives / air (3500 - 7000 Hz)
    freq_per_bin = 8000.0 / max(1, n_bins - 1)
    band_freqs = [
        (70.0, 250.0),
        (250.0, 650.0),
        (650.0, 1600.0),
        (1600.0, 3500.0),
        (3500.0, 7000.0),
    ]

    levels: List[float] = []
    overall_boost = min(1.0, max(0.12, (rms * 7.0) ** 0.65))

    for low_f, high_f in band_freqs:
        b_low = max(0, int(low_f / freq_per_bin))
        b_high = min(n_bins, max(b_low + 1, int(high_f / freq_per_bin)))
        sub = fft_vals[b_low:b_high]
        band_mag = float(np.mean(sub)) if len(sub) > 0 else 0.0
        norm = min(1.0, max(0.10, (band_mag * 12.0) ** 0.65))
        blended = 0.55 * norm + 0.45 * overall_boost
        levels.append(round(float(min(1.0, max(0.10, blended))), 3))

    return levels


_MIC_WORKER_CODE = """
import os, sys, time, sounddevice as sd
os.write(2, b"STANDBY\\n")
cmd = os.read(0, 16)
if not cmd or cmd.startswith(b"Q"):
    os._exit(0)
out = sys.stdout.buffer
def cb(indata, frames, ti, status):
    try:
        out.write(indata.tobytes())
        out.flush()
    except Exception:
        os._exit(0)
try:
    with sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=512, callback=cb):
        while True:
            time.sleep(1)
except Exception:
    os._exit(1)
"""


class MaxiVoiceService:
    """
    Willow-enhanced Push-to-Talk & Hands-Free Voice Service.
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listener: Optional[keyboard.Listener] = None
        self._stream: Optional[sd.InputStream] = None
        self._mic_proc: Optional[subprocess.Popen] = None
        self._standby_mic_proc: Optional[subprocess.Popen] = None
        self._http_client: Optional[httpx.Client] = None
        self._running = False

        # Platform detection
        self.is_mac = sys.platform == "darwin"

        # Hotkey & RecordingHotkeyController state
        self.ctrl_pressed = False
        self.space_pressed = False
        self.right_option_pressed = False
        self.last_key_press_time = 0.0
        self.last_key_release_time = 0.0
        self.last_short_tap_time = 0.0
        self.is_hands_free_locked = False

        # Push-to-Talk recording state
        self.is_ptt_recording = False
        self.ptt_press_time = 0.0
        self.ptt_audio_buffer: List[np.ndarray] = []
        self.last_interim_transcript: str = ""
        self.max_recording_seconds: float = 60.0
        self.active_context: Optional[CapturedContext] = None

        # Concurrency & dispatch state
        self._is_dispatching: bool = False
        self._active_future: Optional[concurrent.futures.Future] = None
        self._active_futures: set[concurrent.futures.Future] = set()
        self._active_tasks: set[asyncio.Task] = set()
        # Workers retain their generation across recording, STT, and dispatch.
        # Escape invalidates it permanently, even after another recording starts.
        self._command_generation: int = 0
        self.lock = threading.RLock()
        self._stream_lock = threading.Lock()
        self._standby_lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        """Compatibility property for HUD queries."""
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
    # Pre-Warmed STT Transport (`WarmTranscriptionConnection`)
    # =========================================================================

    def _get_http_client(self) -> httpx.Client:
        """Returns a persistent, keep-alive httpx.Client for zero-handshake STT uploads."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.Client(
                timeout=httpx.Timeout(12.0, connect=4.0),
                limits=httpx.Limits(
                    max_keepalive_connections=5,
                    max_connections=10,
                    keepalive_expiry=120.0,
                ),
            )
        return self._http_client

    def refresh_config(self):
        """Refreshes cached clients and warm connections when configuration changes."""
        client = self._http_client
        self._http_client = None
        if client and not client.is_closed:
            try:
                client.close()
            except Exception:
                pass
        self._prewarm_stt_connection()

    def _is_command_current(self, generation: int) -> bool:
        with self.lock:
            return generation == self._command_generation

    def _broadcast_for_command(self, generation: int, msg: dict):
        with self.lock:
            if self._is_command_current(generation):
                self._broadcast(msg)

    def _cancel_active_commands(self):
        with self.lock:
            self._command_generation += 1
            tasks = list(self._active_tasks)
            futures = set(self._active_futures)
            if self._active_future is not None:
                futures.add(self._active_future)

        for task in tasks:
            try:
                task.get_loop().call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The owning loop has already stopped.
        for future in futures:
            future.cancel()

    def _prewarm_stt_connection(self):
        """Pre-warms the TCP+TLS socket to the configured Voice STT provider on startup."""
        try:
            client = self._get_http_client()
            base = settings.voice_base_url.rstrip("/")
            api_key = settings.get_voice_api_key()
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            client.get(f"{base}/models", headers=headers, timeout=3.0)
            logger.debug(f"🔥 Pre-warmed STT connection to {base}")
        except Exception as e:
            logger.debug(f"STT pre-warm probe skipped: {e}")

    # =========================================================================
    # Keyboard Hotkey Identification
    # =========================================================================

    def _is_mac_right_option(self, key) -> bool:
        """Identifies Mac Right Option key via Key.alt_r, alt_gr, virtual keycode 61 (0x3D), or string."""
        if keyboard is not None and key in (keyboard.Key.alt_r, getattr(keyboard.Key, "alt_gr", None)):
            return True
        if hasattr(key, "name") and key.name in ("alt_r", "option_r", "alt_gr"):
            return True
        if hasattr(key, "vk") and key.vk == 61:
            return True
        if hasattr(key, "value") and hasattr(key.value, "vk") and key.value.vk == 61:
            return True
        if str(key) in ("Key.alt_r", "Key.alt_gr"):
            return True
        if "<61>" in repr(key):
            return True
        return False

    def _is_mac_option(self, key) -> bool:
        """Identifies Mac Option key (Left or Right Option)."""
        pref = (getattr(settings, "voice_hotkey", "auto") or "auto").lower()
        if pref in ("right_option", "option_r", "alt_r"):
            return self._is_mac_right_option(key)

        if self._is_mac_right_option(key):
            return True
        if keyboard is not None and key in (keyboard.Key.alt, getattr(keyboard.Key, "alt_l", None)):
            return True
        if hasattr(key, "name") and key.name in ("alt", "alt_l", "option", "option_l"):
            return True
        if hasattr(key, "vk") and key.vk in (58, 61):
            return True
        if hasattr(key, "value") and hasattr(key.value, "vk") and key.value.vk in (58, 61):
            return True
        if str(key) in ("Key.alt", "Key.alt_l"):
            return True
        if "<58>" in repr(key):
            return True
        return False

    def _is_ctrl(self, key) -> bool:
        if keyboard is not None and key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return True
        if hasattr(key, "vk") and key.vk in (59, 62, 17, 162, 163):
            return True
        if hasattr(key, "name") and key.name in ("ctrl", "ctrl_l", "ctrl_r"):
            return True
        if "ctrl" in str(key).lower():
            return True
        return False

    def _is_space(self, key) -> bool:
        if keyboard is not None and key == keyboard.Key.space:
            return True
        if hasattr(key, "vk") and key.vk in (49, 32):
            return True
        if hasattr(key, "char") and key.char == " ":
            return True
        if hasattr(key, "name") and key.name == "space":
            return True
        if "space" in str(key).lower():
            return True
        return False

    def _is_esc(self, key) -> bool:
        """Identifies Escape key for immediate recording cancellation (`onCancelKeyPress`)."""
        if keyboard is not None and key == keyboard.Key.esc:
            return True
        if hasattr(key, "name") and key.name == "esc":
            return True
        if hasattr(key, "vk") and key.vk in (53, 27):
            return True
        if str(key) == "Key.esc":
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

    def _is_hardware_hotkey_physically_down(self) -> Optional[bool]:
        """
        On macOS, queries Quartz HID & Session modifier flags and key state to detect if the hotkey
        was physically released even when CGEventTap missed the key-up event (e.g. focus switch).
        """
        if not self.is_mac:
            return None
        try:
            import Quartz
            hid_state = Quartz.kCGEventSourceStateHIDSystemState
            sess_state = Quartz.kCGEventSourceStateCombinedSessionState
            if self._is_hotkey_pref_right_option():
                key_down = (
                    bool(Quartz.CGEventSourceKeyState(hid_state, 0x3D))
                    or bool(Quartz.CGEventSourceKeyState(sess_state, 0x3D))
                    or bool(Quartz.CGEventSourceKeyState(hid_state, 0x3A))
                    or bool(Quartz.CGEventSourceKeyState(sess_state, 0x3A))
                )
                alt_mask = getattr(Quartz, "kCGEventFlagMaskAlternate", 0x00080000)
                flags_down = bool(
                    (int(Quartz.CGEventSourceFlagsState(hid_state)) & alt_mask)
                    or (int(Quartz.CGEventSourceFlagsState(sess_state)) & alt_mask)
                )
                return key_down or flags_down
            if self._is_hotkey_pref_ctrl_space():
                ctrl_mask = getattr(Quartz, "kCGEventFlagMaskControl", 0x00040000)
                ctrl_down = bool(
                    Quartz.CGEventSourceKeyState(hid_state, 0x3B)
                    or Quartz.CGEventSourceKeyState(hid_state, 0x3E)
                    or (int(Quartz.CGEventSourceFlagsState(sess_state)) & ctrl_mask)
                )
                space_down = bool(
                    Quartz.CGEventSourceKeyState(hid_state, 0x31)
                    or Quartz.CGEventSourceKeyState(sess_state, 0x31)
                )
                return ctrl_down and space_down
        except Exception:
            return None
        return None

    # =========================================================================
    # Audio Capture & Callback
    # =========================================================================

    def _audio_callback(self, indata, frames, time_info, status):
        """
        Lock-free audio capture callback active only during Push-to-Talk.
        Never acquires self.lock so PortAudio Pa_StopStream can never deadlock.
        """
        if status:
            logger.debug(f"Audio stream status: {status}")
        if np is None or not self.is_ptt_recording:
            return
        try:
            self.ptt_audio_buffer.append(indata.copy())
        except Exception:
            pass

    def _spawn_standby_mic_worker(self):
        """
        Pre-spawns an isolated Python mic worker process on macOS (`_standby_mic_proc`)
        that imports `sounddevice` ahead of time and blocks on `stdin` before opening
        CoreAudio `sd.InputStream` (keeping the macOS menu-bar mic indicator OFF while idle).
        """
        if not self.is_mac or sd is None or not self._running:
            return
        with self._standby_lock:
            existing = self._standby_mic_proc
            if existing is not None and existing.poll() is None:
                return
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-u", "-c", _MIC_WORKER_CODE],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                ready_line = proc.stderr.readline()
                if not ready_line or not self._running:
                    try:
                        proc.kill()
                        proc.wait(timeout=0.3)
                    except Exception:
                        pass
                    return
                self._standby_mic_proc = proc
            except Exception as e:
                logger.debug(f"Could not pre-warm standby mic worker: {e}")

    def _read_mic_proc_stdout(self, proc: subprocess.Popen):
        """Reads 512-sample float32 PCM chunks (2048 bytes = 32ms @ 16kHz) from isolated mic worker."""
        chunk_bytes = 512 * 4
        try:
            out = proc.stdout
            while self.is_ptt_recording and self._mic_proc is proc and out is not None:
                raw = out.read(chunk_bytes)
                if not raw or len(raw) < chunk_bytes:
                    break
                if np is not None and self.is_ptt_recording:
                    arr = np.frombuffer(raw, dtype=np.float32).reshape(-1, 1)
                    self._audio_callback(arr, 512, None, None)
        except Exception:
            pass

    def _open_mic_stream(self):
        """
        Opens microphone input stream on demand outside self.lock.
        On macOS, uses a pre-warmed isolated subprocess (`_mic_proc`) so killing the stream
        takes ~1ms and completely bypasses PortAudio's `FinishStoppingStream` vs `startStopCallback`
        CoreAudio mutex deadlock.
        """
        if sd is None:
            return

        if self.is_mac:
            with self._stream_lock:
                if not self.is_ptt_recording or self._mic_proc is not None or self._stream is not None:
                    return
                with self._standby_lock:
                    proc = self._standby_mic_proc
                    self._standby_mic_proc = None

                if proc is None or proc.poll() is not None:
                    try:
                        proc = subprocess.Popen(
                            [sys.executable, "-u", "-c", _MIC_WORKER_CODE],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        proc.stderr.readline()
                    except Exception as e:
                        logger.warning(f"Could not launch isolated microphone worker: {e}")
                        return

                try:
                    if proc.stdin:
                        proc.stdin.write(b"G")
                        proc.stdin.flush()
                except Exception as e:
                    logger.warning(f"Could not trigger microphone worker: {e}")
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return

                if not self.is_ptt_recording:
                    try:
                        proc.kill()
                        proc.wait(timeout=0.3)
                    except Exception:
                        pass
                    return

                self._mic_proc = proc
                threading.Thread(
                    target=self._read_mic_proc_stdout,
                    args=(proc,),
                    daemon=True,
                ).start()

            # Pre-warm the next standby worker in the background
            threading.Thread(target=self._spawn_standby_mic_worker, daemon=True).start()
            return

        with self._stream_lock:
            if not self.is_ptt_recording or self._stream is not None:
                return
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    blocksize=1024,
                    callback=self._audio_callback,
                )
                stream.start()
                if not self.is_ptt_recording:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
                    return
                self._stream = stream
            except Exception as e:
                logger.warning(f"Could not open microphone stream: {e}")
                self._stream = None

    def _close_mic_stream(self):
        """
        Closes microphone input stream immediately outside self.lock without deadlocking PortAudio.
        On macOS, terminates the isolated `_mic_proc` child process (~1ms) so `Pa_StopStream` is never called.
        """
        with self._stream_lock:
            proc = self._mic_proc
            self._mic_proc = None
            stream = self._stream
            self._stream = None

        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=0.3)
            except Exception:
                pass

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _capture_context_background(self):
        """Captures frontmost app, window title, URL, and selected text on key-down (`FocusedInputCapture`)."""
        if not getattr(settings, "enable_context_capture", True):
            return
        try:
            ctx = context_capturer.capture_snapshot()
            self.active_context = ctx
            if not ctx.is_empty():
                self._broadcast({
                    "event": "voice_context",
                    "context": ctx.to_dict(),
                })
        except Exception as e:
            logger.debug(f"Background context capture failed: {e}")

    def _recording_watchdog(self, session_press_time: float):
        """
        Monitors an active Push-to-Talk recording session:
        1. Broadcasts 5-band audio levels (`AudioLevelMonitor`) to WebSocket HUD at 33Hz.
        2. Polls hardware key state on macOS every 30ms (unless hands-free locked) so missed key-up events never stick the mic.
        3. Enforces max_recording_seconds safety cutoff.
        """
        time.sleep(0.05)
        while self._running and self.is_ptt_recording and self.ptt_press_time == session_press_time:
            elapsed = time.time() - session_press_time
            if elapsed >= self.max_recording_seconds:
                logger.warning(f"⏱️ Push-to-Talk exceeded {self.max_recording_seconds}s max duration; auto-stopping mic.")
                self.stop_recording()
                return

            # Broadcast live 5-bar audio levels for HUD waveform
            buf = self.ptt_audio_buffer
            if buf:
                try:
                    levels = compute_audio_levels(buf[-1])
                    self._broadcast({
                        "event": "audio_level",
                        "levels": levels,
                        "locked": self.is_hands_free_locked,
                        "elapsed": round(elapsed, 1),
                    })
                except Exception:
                    pass

            if not self.is_hands_free_locked and elapsed >= 0.18:
                hw_down = self._is_hardware_hotkey_physically_down()
                if hw_down is False:
                    logger.info(f"🎙️ Hardware hotkey release detected ({elapsed:.2f}s). Closing mic...")
                    self.right_option_pressed = False
                    self.ctrl_pressed = False
                    self.space_pressed = False
                    if elapsed < 0.25:
                        self.cancel_recording()
                    else:
                        self.stop_recording()
                    return

            time.sleep(0.03)

    # =========================================================================
    # Push-to-Talk Recording Controls
    # =========================================================================

    def start_recording(self, locked: bool = False):
        """Starts Push-to-Talk audio gathering, ducks system audio, and snapshots active context."""
        with self.lock:
            if self.is_ptt_recording:
                if locked and not self.is_hands_free_locked:
                    self.is_hands_free_locked = True
                    self._broadcast({"event": "voice_lock", "locked": True})
                return
            self.is_ptt_recording = True
            self.is_hands_free_locked = locked
            self.ptt_audio_buffer = []
            self.active_context = None
            session_press_time = time.time()
            self.ptt_press_time = session_press_time

        # 1. Interrupt ongoing TTS & duck system audio (`PrivateDucker`)
        threading.Thread(target=tts_service.stop, daemon=True).start()
        threading.Thread(target=audio_ducker.duck, daemon=True).start()

        # 2. Capture active app, window title, URL, and highlighted text (`FocusedInputCapture`)
        threading.Thread(target=self._capture_context_background, daemon=True).start()

        # 3. Open mic stream and launch hardware watchdog
        self._open_mic_stream()
        if self._running:
            threading.Thread(
                target=self._recording_watchdog,
                args=(session_press_time,),
                daemon=True,
            ).start()

        play_sound(settings.voice_start_sound)
        self._broadcast({
            "event": "voice_start",
            "locked": self.is_hands_free_locked,
        })
        mode_label = "Hands-Free Locked (Tap key to finish, Esc to cancel)" if locked else "Hold key to speak (Double-tap to lock, Esc to cancel)"
        logger.info(f"🎙️ Push-to-Talk recording started ({mode_label})...")

    def cancel_recording(self, reason: str = "cancel"):
        """Silently cancels Push-to-Talk, unducks system audio, and closes mic."""
        with self.lock:
            if not self.is_ptt_recording:
                return
            self.is_ptt_recording = False
            self.is_hands_free_locked = False
            self.ptt_audio_buffer = []

        self._close_mic_stream()
        threading.Thread(target=audio_ducker.unduck, daemon=True).start()
        self._broadcast({"event": "voice_stop", "cancelled": True, "reason": reason})
        logger.info(f"🚫 Voice recording cancelled ({reason}).")

    def abort_current_command(self, reason: str = "esc"):
        """Immediately abort any active recording, STT transcription, LLM processing, or TTS speech."""
        logger.info(f"🛑 Aborting active voice command (reason: {reason})...")
        self._cancel_active_commands()
        self.right_option_pressed = False
        self.ctrl_pressed = False
        self.space_pressed = False

        # 1. Stop audio recording if in progress
        if self.is_ptt_recording:
            self.cancel_recording(reason=reason)

        # 2. Stop TTS speech
        if tts_service.is_speaking:
            tts_service.stop()

        # 3. Reset HTTP pool if STT was hung
        old_client = self._http_client
        self._http_client = None
        if old_client is not None:
            threading.Thread(target=self._safe_close_http, args=(old_client,), daemon=True).start()

        # 4. Broadcast cancellation to HUD
        self._broadcast({"event": "voice_stop", "cancelled": True, "reason": reason})
        self._broadcast({"event": "voice_idle"})
        self._broadcast({"event": "hud_dismiss"})

    def stop_recording(self):
        """Stops Push-to-Talk gathering, closes mic outside lock, unducks audio, and initiates execution."""
        chunks = []
        captured_ctx = None
        with self.lock:
            if not self.is_ptt_recording:
                return
            if time.time() - self.ptt_press_time < 0.35:
                return
            self.is_ptt_recording = False
            self.is_hands_free_locked = False
            chunks = list(self.ptt_audio_buffer)
            self.ptt_audio_buffer = []
            captured_ctx = self.active_context
            command_generation = self._command_generation

        self._close_mic_stream()
        threading.Thread(target=audio_ducker.unduck, daemon=True).start()
        play_sound(settings.voice_release_sound)
        self._broadcast({"event": "voice_stop", "cancelled": False})

        if not chunks:
            logger.info("No recognizable speech detected (recording too brief).")
            self._broadcast({"event": "voice_idle"})
            return

        threading.Thread(
            target=self._process_ptt_recording,
            args=(chunks, captured_ctx, command_generation),
            daemon=True,
        ).start()

    def _process_ptt_recording(
        self, chunks: List[np.ndarray], captured_ctx: Optional[CapturedContext] = None,
        command_generation: Optional[int] = None,
    ):
        with self.lock:
            if command_generation is None:
                command_generation = self._command_generation
        if not self._is_command_current(command_generation):
            return

        if not chunks or np is None:
            self._broadcast_for_command(command_generation, {"event": "voice_idle"})
            return

        audio_data = np.concatenate(chunks, axis=0)
        if len(audio_data) < SAMPLE_RATE * 0.28:
            logger.info("No recognizable speech detected (recording <280ms).")
            self._broadcast_for_command(command_generation, {"event": "voice_idle"})
            return

        duration_s = len(audio_data) / float(SAMPLE_RATE)
        rms = float(np.sqrt(np.mean(np.square(audio_data))))
        peak = float(np.max(np.abs(audio_data)))
        logger.debug(f"🎙️ Captured {duration_s:.2f}s audio (rms={rms:.4f}, peak={peak:.4f})")

        if peak < 0.004 or rms < 0.0006:
            logger.info(f"No speech energy detected in {duration_s:.2f}s audio (rms={rms:.4f}, peak={peak:.4f}).")
            self._broadcast_for_command(command_generation, {"event": "voice_idle"})
            return

        if not self._is_command_current(command_generation):
            logger.info("Voice processing aborted before transcription.")
            return

        self._broadcast_for_command(command_generation, {"event": "voice_processing"})
        t0 = time.perf_counter()
        extra_terms = captured_ctx.extract_proper_nouns() if captured_ctx else []
        transcript = self._transcribe(
            audio_data, extra_terms=extra_terms, command_generation=command_generation,
        )

        if not self._is_command_current(command_generation):
            logger.info("Voice processing aborted after transcription.")
            return
        cleaned_lower = (transcript or "").strip().lower().rstrip(".!?")
        if (
            not transcript
            or cleaned_lower in ("", "v", "v v", "vv", "you")
            or (rms < 0.0035 and cleaned_lower in ("thank you", "thanks for watching", "bye"))
        ):
            logger.info("No recognizable speech detected.")
            self._broadcast_for_command(command_generation, {"event": "voice_idle"})
            return

        stt_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(f"🗣️ Push-to-Talk Transcript ({stt_ms}ms): \"{transcript}\"")
        self._broadcast_for_command(command_generation, {
            "event": "voice_transcript",
            "transcript": transcript,
            "stt_ms": stt_ms,
        })

        # Fast-path Willow SmartInsertions: "Dictate: <text>" or "Type this: <text>"
        m_dictate = DIRECT_DICTATION_REGEX.match(transcript.strip())
        if m_dictate:
            if not self._is_command_current(command_generation):
                return
            dictated_text = m_dictate.group(1).strip()
            ok = text_injector.inject_text(dictated_text, restore_clipboard=True)
            out_msg = dictated_text
            self._broadcast_for_command(command_generation, {
                "event": "voice_result",
                "transcript": transcript,
                "output": out_msg,
                "tools": ["inject_text_at_cursor"],
            })
            if self._is_command_current(command_generation):
                play_sound(settings.voice_finish_sound)
            return

        if not self._is_command_current(command_generation):
            logger.info("Voice dispatch aborted before agent execution.")
            return

        self._dispatch_command(
            transcript,
            source="voice:hotkey",
            trigger_transcript=transcript,
            captured_ctx=captured_ctx,
            command_generation=command_generation,
        )

    # =========================================================================
    # STT Transcription & Agent Execution
    # =========================================================================

    def _transcribe(
        self, audio_data: np.ndarray, extra_terms: Optional[List[str]] = None,
        command_generation: Optional[int] = None,
    ) -> str:
        """
        Sends captured audio over the pre-warmed HTTP client to Voice STT
        and applies deterministic Glossary phrase replacements on the transcript.
        Automatically reconnects with a fresh HTTP client if a stale sleep/DNS error occurs.
        """
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
        data = {
            "model": settings.voice_model,
            "response_format": "json",
        }

        for attempt in range(2):
            if command_generation is not None and not self._is_command_current(command_generation):
                return ""
            try:
                files = {"file": ("command.wav", wav_bytes, "audio/wav")}
                client = self._get_http_client()
                resp = client.post(url, headers=headers, files=files, data=data)
                if resp.status_code == 200:
                    raw_text = resp.json().get("text", "").strip()
                    return glossary_manager.apply_replacements(raw_text)
                logger.error(f"Voice transcription returned error {resp.status_code}: {resp.text}")
                break
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"STT connection hiccup ({e}); resetting HTTP pool and retrying...")
                    old_client = self._http_client
                    self._http_client = None
                    if old_client is not None:
                        threading.Thread(target=self._safe_close_http, args=(old_client,), daemon=True).start()
                    time.sleep(0.25)
                else:
                    logger.error(f"Error calling voice transcription endpoint: {e}")
        return ""

    def _dispatch_command(
        self,
        prompt: str,
        source: str = "voice:hotkey",
        trigger_transcript: str = "",
        captured_ctx: Optional[CapturedContext] = None,
        command_generation: Optional[int] = None,
    ):
        """Dispatches formatted voice prompt + active window context to the main Maxi agent."""
        from app.core.agent import agent

        with self.lock:
            if command_generation is None:
                command_generation = self._command_generation
            if not self._is_command_current(command_generation):
                return
            self._is_dispatching = True
        t0 = time.perf_counter()
        agent_output = ""
        tools_used = []
        context_block = captured_ctx.format_for_prompt() if captured_ctx else ""

        logger.info(f"⚡ Activating Maxi Agent Function with prompt: \"{prompt}\" (source: {source})")

        def on_tool_start(tool_name: str, args: dict):
            logger.info(f"⚡ [Real-time Tool Start]: {tool_name}")
            self._broadcast_for_command(command_generation, {
                "event": "tool_start",
                "tool": tool_name,
                "args": args if isinstance(args, dict) else {},
            })

        def on_tool_end(tool_name: str, result: str):
            logger.info(f"⚡ [Real-time Tool End]: {tool_name}")
            self._broadcast_for_command(command_generation, {
                "event": "tool_end",
                "tool": tool_name,
                "status": "success" if not str(result).startswith("Error") else "error",
            })

        timeout_s = getattr(settings, "agent_timeout_seconds", 90.0)
        future = None

        async def _run_wrapped():
            task = asyncio.current_task()
            with self.lock:
                if not self._is_command_current(command_generation):
                    raise asyncio.CancelledError
                self._active_tasks.add(task)
            try:
                return await agent.run(
                    prompt=prompt,
                    source=source,
                    context_block=context_block,
                    on_tool_start=on_tool_start,
                    on_tool_end=on_tool_end,
                )
            finally:
                with self.lock:
                    self._active_tasks.discard(task)
                    self._is_dispatching = bool(self._active_tasks or self._active_futures)

        async def _run_with_timeout():
            return await asyncio.wait_for(_run_wrapped(), timeout=timeout_s)

        try:
            if self._loop and self._loop.is_running():
                with self.lock:
                    if not self._is_command_current(command_generation):
                        return
                    future = asyncio.run_coroutine_threadsafe(_run_with_timeout(), self._loop)
                    self._active_futures.add(future)
                    self._active_future = future
                result = future.result(timeout=timeout_s)
            else:
                result = asyncio.run(_run_with_timeout())
            agent_output = result.get("output", "")
            tools_used = result.get("tools_used", [])
        except (concurrent.futures.CancelledError, asyncio.CancelledError):
            logger.info("Voice command cancelled by user (Escape).")
            return
        except (TimeoutError, concurrent.futures.TimeoutError, asyncio.TimeoutError):
            if future is not None:
                future.cancel()
            logger.error(f"Voice command timed out after {timeout_s}s: \"{prompt}\"")
            agent_output = f"Command timed out after {int(timeout_s)} seconds. Please try again."
        except Exception as e:
            err_desc = str(e).strip() or type(e).__name__
            logger.error(f"Error dispatching voice command to main agent: {err_desc}", exc_info=True)
            agent_output = f"Execution error: {err_desc}"
        finally:
            with self.lock:
                self._active_futures.discard(future)
                if self._active_future is future:
                    self._active_future = next(iter(self._active_futures), None)
                self._is_dispatching = bool(self._active_tasks or self._active_futures)

        if not self._is_command_current(command_generation) or (not self._running and self._loop is not None):
            logger.info("Discarding result because voice command was cancelled.")
            return

        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(f"⚡ Maxi Voice Result ({total_ms}ms): {agent_output}")
        if tools_used:
            logger.info(f"🛠️ Tools executed: {', '.join(tools_used)}")

        # Separate speech from display output for notch
        from app.core.tts import extract_speech_and_display_text
        spoken_part, display_part = extract_speech_and_display_text(agent_output)

        # Broadcast result to frontend HUD
        self._broadcast_for_command(command_generation, {
            "event": "voice_result",
            "transcript": prompt,
            "output": display_part or agent_output,
            "tools": tools_used,
            "latency_ms": total_ms,
            "context": captured_ctx.to_dict() if captured_ctx and not captured_ctx.is_empty() else None,
        })

        if not self._is_command_current(command_generation):
            return

        # Play completion chime
        play_sound(settings.voice_finish_sound)

        # Speak response aloud using Siri TTS (concise spoken summary only)
        if getattr(settings, "enable_tts", True) and (spoken_part or agent_output):
            tts_service.speak(spoken_part or agent_output)

    # =========================================================================
    # Keyboard Event Handlers (`RecordingHotkeyController`)
    # =========================================================================

    def _on_press(self, key):
        # 1. Escape key handling (`onCancelKeyPress`):
        #    Immediately abort active recording, in-flight STT, LLM reasoning, tools, and speech
        if self._is_esc(key):
            self.abort_current_command(reason="esc")
            return

        was_already_active = self._is_hotkey_active()

        if self._is_hotkey_pref_right_option() and self._is_mac_option(key):
            self.right_option_pressed = True

        if self._is_hotkey_pref_ctrl_space():
            if self._is_ctrl(key):
                self.ctrl_pressed = True
            elif self._is_space(key):
                self.space_pressed = True

        # Ignore duplicate flagsChanged / key-repeat events while the hotkey is already held down
        if was_already_active:
            return

        if self._is_hotkey_active():
            now = time.time()
            if now - self.last_key_press_time < 0.08:
                return
            self.last_key_press_time = now

            # Case A: Already locked in Hands-Free mode -> pressing hotkey again finishes & executes!
            if self.is_ptt_recording and self.is_hands_free_locked:
                if (now - self.ptt_press_time) < 0.28:
                    return
                logger.info("🎙️ Hands-free lock ended via hotkey tap. Processing speech...")
                self.right_option_pressed = False
                self.ctrl_pressed = False
                self.space_pressed = False
                self.stop_recording()
                return

            # Case B: Double-tap within double_tap_window locks Hands-Free recording
            double_tap_win = getattr(settings, "double_tap_window", 0.38)
            is_double_tap = (now - self.last_short_tap_time) <= double_tap_win
            if not self.is_ptt_recording:
                if is_double_tap:
                    self.last_short_tap_time = 0.0
                    self.start_recording(locked=True)
                else:
                    self.start_recording(locked=False)

    def _on_release(self, key):
        was_recording = self.is_ptt_recording

        if self._is_hotkey_pref_right_option() and self._is_mac_option(key):
            self.right_option_pressed = False

        if self._is_hotkey_pref_ctrl_space():
            if self._is_ctrl(key):
                self.ctrl_pressed = False
            elif self._is_space(key):
                self.space_pressed = False

        if was_recording and not self._is_hotkey_active():
            # If locked in hands-free mode, releasing the key keeps recording active!
            if self.is_hands_free_locked:
                return

            now = time.time()
            self.last_key_release_time = now
            elapsed = now - self.ptt_press_time
            if elapsed < 0.25:
                # Record short tap timestamp so a second tap within 380ms locks hands-free mode
                self.last_short_tap_time = now
                logger.debug(f"⏱️ Short tap ({elapsed:.2f}s) — tap again within 0.38s to lock hands-free.")
                self.cancel_recording(reason="short_tap")
            else:
                self.last_short_tap_time = 0.0
                logger.info(f"🎙️ Hotkey released ({elapsed:.2f}s). Processing speech...")
                self.stop_recording()

    # =========================================================================
    # Service Lifecycle Management
    # =========================================================================

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Starts the global Push-to-Talk hotkey listener and pre-warms the STT connection."""
        self._loop = loop
        self._running = True
        tts_service.set_broadcast_callback(self._broadcast)

        # Pre-warm STT connection & standby mic worker in background
        threading.Thread(target=self._prewarm_stt_connection, daemon=True).start()
        if self.is_mac:
            threading.Thread(target=self._spawn_standby_mic_worker, daemon=True).start()

        if getattr(settings, "enable_tts", True):
            from app.core.tts import is_ollama_voice, is_kokoro_voice
            if is_ollama_voice(settings.tts_voice):
                provider_label = "Ollama Phonon"
            elif is_kokoro_voice(settings.tts_voice):
                provider_label = "Kokoro Neural"
            else:
                provider_label = "Siri"
            logger.info(f"🔊 {provider_label} TTS active: Voice '{settings.tts_voice}' @ {settings.tts_rate}wpm")

        if settings.enable_voice_hotkey and keyboard is not None:
            if self.is_mac:
                try:
                    import ApplicationServices
                    if not ApplicationServices.AXIsProcessTrusted():
                        logger.warning(
                            "⚠️ Accessibility permission not granted. "
                            "Global Push-to-Talk hotkeys require Accessibility access in "
                            "System Settings -> Privacy & Security -> Accessibility."
                        )
                        kPrompt = getattr(ApplicationServices, "kAXTrustedCheckOptionPrompt", "AXTrustedCheckOptionPrompt")
                        ApplicationServices.AXIsProcessTrustedWithOptions({kPrompt: True})
                except Exception as e:
                    logger.debug(f"Could not verify Accessibility trust: {e}")

            hotkey_name = "Right Option (⌥)" if self._is_hotkey_pref_right_option() else "Control + Space"
            try:
                self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
                self._listener.daemon = True
                self._listener.start()
                logger.info(
                    f"✅ Push-to-Talk active: Hold {hotkey_name} to speak, Double-Tap to lock hands-free, Esc to cancel."
                )
            except Exception as e:
                logger.warning(f"Voice hotkey listener could not start ({e}).")

    def stop(self):
        """Gracefully stops all audio streams, active dispatches, and hotkey listeners without hanging."""
        self._running = False
        self._cancel_active_commands()
        self.is_ptt_recording = False
        self.is_hands_free_locked = False
        self.right_option_pressed = False
        self.ctrl_pressed = False
        self.space_pressed = False

        self._active_future = None

        tts_service.stop()
        threading.Thread(target=audio_ducker.unduck, daemon=True).start()

        listener = self._listener
        self._listener = None
        if listener is not None:
            threading.Thread(target=self._safe_stop_listener, args=(listener,), daemon=True).start()

        self._close_mic_stream()
        with self._standby_lock:
            standby = self._standby_mic_proc
            self._standby_mic_proc = None
        if standby is not None:
            try:
                standby.kill()
            except Exception:
                pass

        if self._http_client is not None:
            client = self._http_client
            self._http_client = None
            threading.Thread(target=self._safe_close_http, args=(client,), daemon=True).start()

        logger.info("Maxi Voice service stopped.")

    @staticmethod
    def _safe_stop_listener(listener):
        try:
            listener.stop()
        except Exception:
            pass

    @staticmethod
    def _safe_close_http(client: httpx.Client):
        try:
            client.close()
        except Exception:
            pass


voice_service = MaxiVoiceService()
