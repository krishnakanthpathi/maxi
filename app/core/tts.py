"""
Maxi Siri Text-to-Speech (TTS) Engine
Provides ultra-low-latency native Siri voice synthesis with:
- Automatic Siri neural/premium voice resolution (Tara, Samantha, Daniel, Karen, Moira, Rishi)
- Markdown, URL, code-block, and emoji sanitization for natural spoken cadence
- Non-blocking background playback with instant barge-in interruption
- Acoustic self-echo suppression guard so hands-free wake-word VAD never triggers on Maxi's own voice
"""

import re
import sys
import time
import shutil
import logging
import threading
import subprocess
from typing import Optional, List, Dict, Any, Callable
from app.config import settings

logger = logging.getLogger("maxi.tts")

# Friendly Siri voice aliases mapped to macOS native voice names
SIRI_VOICE_ALIASES: Dict[str, str] = {
    "siri": "Tara",
    "siri-in": "Tara",
    "siri-india": "Tara",
    "tara": "Tara",
    "siri-us": "Samantha",
    "siri-america": "Samantha",
    "samantha": "Samantha",
    "siri-uk": "Daniel",
    "siri-british": "Daniel",
    "daniel": "Daniel",
    "siri-au": "Karen",
    "karen": "Karen",
    "siri-ie": "Moira",
    "moira": "Moira",
    "rishi": "Rishi",
    "aman": "Aman",
}

SIRI_VOICE_PRESETS: Dict[str, Dict[str, str]] = {
    "tara": {
        "name": "Siri Female (Tara - Premium)",
        "voice": "Tara",
        "locale": "en_IN",
        "description": "Apple Siri natural English (India) premium voice"
    },
    "samantha": {
        "name": "Siri Female (Samantha - US)",
        "voice": "Samantha",
        "locale": "en_US",
        "description": "Classic Apple Siri US English voice"
    },
    "daniel": {
        "name": "Siri Male (Daniel - UK)",
        "voice": "Daniel",
        "locale": "en_GB",
        "description": "Apple Siri British English voice"
    },
    "karen": {
        "name": "Siri Female (Karen - AU)",
        "voice": "Karen",
        "locale": "en_AU",
        "description": "Apple Siri Australian English voice"
    },
    "moira": {
        "name": "Siri Female (Moira - IE)",
        "voice": "Moira",
        "locale": "en_IE",
        "description": "Apple Siri Irish English voice"
    },
    "rishi": {
        "name": "Siri Male (Rishi - IN)",
        "voice": "Rishi",
        "locale": "en_IN",
        "description": "Apple Siri Indian English male voice"
    },
}


def clean_text_for_tts(text: str, max_chars: int = 450) -> str:
    """
    Sanitizes raw LLM markdown output into clean, natural conversational prose suitable for Siri TTS.
    - Removes code blocks, inline backticks, markdown links, raw URLs, formatting symbols, and emojis.
    """
    if not text or not text.strip():
        return ""

    s = text.strip()

    # 1. Remove fenced code blocks ```...```
    s = re.sub(r"```[\s\S]*?```", " ", s)

    # 2. Convert markdown links [label](https://...) -> label
    s = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", s)

    # 3. Remove raw HTTP/HTTPS/file URLs and clean trailing colons before URLs
    s = re.sub(r":\s*https?://\S+", ".", s)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"file://\S+", "", s)

    # 4. Strip inline code backticks, bold, italics, headings, blockquotes
    s = s.replace("`", "")
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"^#+\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*[-*•]\s+", "", s, flags=re.MULTILINE)

    # 5. Strip emojis and non-speech dingbats so TTS doesn't read emoji names aloud
    s = re.sub(
        r"[\U00010000-\U0010ffff"
        r"\u2600-\u27bf"
        r"\u2300-\u23ff"
        r"\u2b50\u2705\u274c\u26a1\ufe0f]+",
        " ",
        s,
    )

    # 6. Collapse whitespace and newlines into natural sentence pauses
    s = re.sub(r"[\r\n]+", ". ", s)
    s = re.sub(r"(?:\.\s*)+", ". ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # 7. Cap length at a clean sentence boundary so voice replies remain snappy
    if len(s) > max_chars:
        truncated = s[:max_chars]
        last_period = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
        if last_period > max_chars // 2:
            s = truncated[: last_period + 1].strip()
        else:
            s = truncated.strip() + "."

    return s


def resolve_siri_voice(requested_voice: Optional[str] = None) -> str:
    """Resolves a voice alias or name (e.g. 'siri', 'tara', 'samantha') to the canonical macOS voice."""
    raw = (requested_voice or getattr(settings, "tts_voice", "Tara") or "Tara").strip()
    lookup = raw.lower()
    if lookup in SIRI_VOICE_ALIASES:
        return SIRI_VOICE_ALIASES[lookup]
    return raw


class TTSService:
    """Manages non-blocking Siri TTS playback, barge-in cancellation, and mic echo suppression."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._is_speaking: bool = False
        self._last_speech_end_time: float = 0.0
        self._cooldown_seconds: float = 0.45
        self._broadcast_cb: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_broadcast_callback(self, cb: Callable[[Dict[str, Any]], None]):
        """Registers callback to broadcast TTS state events to WebSocket HUD clients."""
        self._broadcast_cb = cb

    @property
    def is_speaking(self) -> bool:
        """True if TTS audio is currently playing."""
        return self._is_speaking

    def is_active_or_cooldown(self) -> bool:
        """
        True if TTS is currently speaking OR within the post-speech acoustic cooldown window.
        Used by the wake-word microphone listener to prevent self-triggering on Maxi's own voice.
        """
        if self._is_speaking:
            return True
        if (time.time() - self._last_speech_end_time) < self._cooldown_seconds:
            return True
        return False

    def stop(self):
        """Immediately stops any active TTS speech (barge-in support)."""
        with self._lock:
            proc = self._proc
            self._proc = None
            was_speaking = self._is_speaking
            self._is_speaking = False
            if was_speaking:
                self._last_speech_end_time = time.time()

        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if was_speaking and self._broadcast_cb:
            try:
                self._broadcast_cb({"event": "tts_stop"})
            except Exception:
                pass

    def speak(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[int] = None,
        block: bool = False,
    ) -> str:
        """
        Sanitizes and speaks text aloud using Siri/native TTS.
        Returns the sanitized spoken text.
        """
        if not getattr(settings, "enable_tts", True):
            return ""

        clean_text = clean_text_for_tts(text)
        if not clean_text:
            return ""

        # Cancel any ongoing speech first
        self.stop()

        resolved_voice = resolve_siri_voice(voice)
        resolved_rate = rate or getattr(settings, "tts_rate", 190) or 190

        if block:
            self._run_speech_sync(clean_text, resolved_voice, resolved_rate)
        else:
            t = threading.Thread(
                target=self._run_speech_sync,
                args=(clean_text, resolved_voice, resolved_rate),
                daemon=True,
            )
            t.start()

        return clean_text

    def _run_speech_sync(self, clean_text: str, voice: str, rate: int):
        cmd = self._build_tts_command(clean_text, voice, rate)
        if not cmd:
            logger.warning("No native TTS binary found on this system.")
            return

        logger.info(f"🔊 Siri TTS ({voice} @ {rate}wpm): \"{clean_text}\"")

        with self._lock:
            self._is_speaking = True
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                proc = self._proc
            except Exception as e:
                logger.error(f"Failed to launch TTS process: {e}")
                self._is_speaking = False
                self._proc = None
                return

        if self._broadcast_cb:
            try:
                self._broadcast_cb({
                    "event": "tts_start",
                    "text": clean_text,
                    "voice": voice,
                })
            except Exception:
                pass

        try:
            proc.wait()
            # If the specific requested voice wasn't installed (exit code != 0 on macOS `say`),
            # automatically fall back to system default voice.
            if proc.returncode not in (0, -15, -9) and sys.platform == "darwin" and "-v" in cmd:
                logger.warning(f"Voice '{voice}' returned code {proc.returncode}; falling back to default macOS voice.")
                fallback_cmd = ["say", "-r", str(rate), clean_text]
                with self._lock:
                    if self._is_speaking:
                        self._proc = subprocess.Popen(
                            fallback_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        proc = self._proc
                proc.wait()
        except Exception as e:
            logger.debug(f"TTS process interrupted: {e}")
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
                    self._is_speaking = False
                    self._last_speech_end_time = time.time()

            if self._broadcast_cb:
                try:
                    self._broadcast_cb({"event": "tts_stop"})
                except Exception:
                    pass

    def _build_tts_command(self, text: str, voice: str, rate: int) -> Optional[List[str]]:
        if sys.platform == "darwin" and shutil.which("say"):
            return ["say", "-v", voice, "-r", str(rate), text]
        elif sys.platform.startswith("win"):
            safe_text = text.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Speak('{safe_text}');"
            )
            return ["powershell", "-NoProfile", "-Command", ps]
        else:
            for bin_name in ("spd-say", "espeak-ng", "espeak"):
                if shutil.which(bin_name):
                    return [bin_name, text]
        return None

    def list_available_voices(self) -> List[Dict[str, str]]:
        """Lists available English voices on macOS or returns presets."""
        voices: List[Dict[str, str]] = []
        if sys.platform == "darwin" and shutil.which("say"):
            try:
                out = subprocess.check_output(["say", "-v", "?"], text=True, timeout=3.0)
                seen = set()
                for line in out.splitlines():
                    if "#" not in line:
                        continue
                    left, sample = line.split("#", 1)
                    parts = left.strip().rsplit(None, 1)
                    if len(parts) != 2:
                        continue
                    v_name, locale = parts[0].strip(), parts[1].strip()
                    if locale.startswith("en_") and v_name not in seen:
                        seen.add(v_name)
                        voices.append({
                            "name": v_name,
                            "locale": locale,
                            "sample": sample.strip(),
                        })
            except Exception as e:
                logger.debug(f"Failed listing macOS voices: {e}")
        return voices


tts_service = TTSService()
