"""
Willow-inspired PrivateDucker (`app/core/audio_ducker.py`).
Automatically ducks (lowers) system audio volume when Push-to-Talk recording starts
so background music/video never bleeds into the microphone, and restores the exact
previous volume when recording finishes or cancels.
"""

import logging
import subprocess
import sys
import threading
from typing import Optional
from app.config import settings

logger = logging.getLogger("maxi.ducker")


class AudioDucker:
    """Snapshots and ducks macOS output volume during active microphone capture."""

    def __init__(self, duck_level: int = 12):
        self.duck_level = duck_level
        self._lock = threading.Lock()
        self._previous_volume: Optional[int] = None
        self._is_ducked: bool = False

    @property
    def is_ducked(self) -> bool:
        return self._is_ducked

    def _get_macos_output_volume(self) -> Optional[int]:
        if sys.platform != "darwin":
            return None
        try:
            res = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True,
                text=True,
                timeout=0.35,
            )
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return int(res.stdout.strip())
        except Exception as e:
            logger.debug(f"Could not read macOS volume for ducking: {e}")
        return None

    def _set_macos_output_volume(self, volume: int):
        if sys.platform != "darwin":
            return
        vol = max(0, min(100, int(volume)))
        try:
            subprocess.Popen(
                ["osascript", "-e", f"set volume output volume {vol}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.debug(f"Could not set macOS volume to {vol}: {e}")

    def duck(self):
        """Lowers system volume while recording if auto_duck_audio is enabled."""
        if not getattr(settings, "auto_duck_audio", True):
            return
        with self._lock:
            if self._is_ducked:
                return
            current = self._get_macos_output_volume()
            if current is not None and current > self.duck_level:
                self._previous_volume = current
                self._is_ducked = True
                self._set_macos_output_volume(self.duck_level)
                logger.debug(f"🔉 Ducked system volume from {current}% -> {self.duck_level}%")

    def unduck(self):
        """Restores system volume to its pre-recording level."""
        with self._lock:
            if not self._is_ducked:
                return
            prev = self._previous_volume
            self._previous_volume = None
            self._is_ducked = False
        if prev is not None:
            self._set_macos_output_volume(prev)
            logger.debug(f"🔊 Restored system volume to {prev}%")


audio_ducker = AudioDucker()
