"""
Willow-inspired FocusedInputCapture & Per-App Context Explorer (`app/core/context_capture.py`).
Captures the frontmost application, bundle ID, window title, active browser URL, and
currently highlighted text (`AXSelectedText`) in parallel on hotkey press (0ms added latency).
"""

import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List

logger = logging.getLogger("maxi.context")


@dataclass
class CapturedContext:
    app_name: str = ""
    bundle_id: str = ""
    window_title: str = ""
    url: str = ""
    selected_text: str = ""
    captured_at: float = 0.0

    def is_empty(self) -> bool:
        return not (self.app_name or self.window_title or self.url or self.selected_text)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def format_for_prompt(self) -> str:
        """Formats captured active context as a concise XML block for the LLM agent."""
        if self.is_empty():
            return ""
        lines = ["<active_context>"]
        if self.app_name:
            app_str = f"{self.app_name} ({self.bundle_id})" if self.bundle_id else self.app_name
            lines.append(f"  Frontmost App: {app_str}")
        if self.window_title:
            lines.append(f"  Window Title: {self.window_title}")
        if self.url:
            lines.append(f"  Active URL: {self.url}")
        if self.selected_text:
            clipped = self.selected_text.strip()
            if len(clipped) > 1500:
                clipped = clipped[:1500] + "... [truncated]"
            lines.append(f"  Highlighted/Selected Text:\n  \"\"\"\n  {clipped}\n  \"\"\"")
        lines.append("</active_context>")
        return "\n".join(lines)

    def to_prompt_block(self) -> str:
        return self.format_for_prompt()

    def extract_proper_nouns(self) -> List[str]:
        """Extracts proper nouns and domain tokens from window title & app name to condition Whisper STT."""
        raw = f"{self.app_name} {self.window_title}"
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,24}", raw)
        stop = {"the", "and", "for", "with", "from", "google", "chrome", "apple", "window", "untitled"}
        seen = []
        for t in tokens:
            if t.lower() not in stop and t not in seen:
                seen.append(t)
        return seen[:15]


class FocusedContextCapturer:
    """
    Captures active window metadata and highlighted text on macOS when Push-to-Talk starts.
    Uses a fast single-pass AppleScript + Accessibility query with strict timeouts.
    """

    def __init__(self, timeout_seconds: float = 0.45):
        self.timeout_seconds = timeout_seconds
        self._last_context: Optional[CapturedContext] = None

    @property
    def last_context(self) -> Optional[CapturedContext]:
        return self._last_context

    def capture(self) -> CapturedContext:
        return self.capture_snapshot()

    def capture_snapshot(self) -> CapturedContext:
        """Captures frontmost app, window title, active browser URL, and AXSelectedText."""
        ctx = CapturedContext(captured_at=time.time())
        if sys.platform != "darwin":
            self._last_context = ctx
            return ctx

        script = r'''
        set appName to ""
        set bundleId to ""
        set winTitle to ""
        set selText to ""
        set activeUrl to ""

        tell application "System Events"
            try
                set frontProc to first application process whose frontmost is true
                set appName to name of frontProc
                set bundleId to bundle identifier of frontProc
                try
                    set winTitle to name of front window of frontProc
                end try
                try
                    set focusedElem to value of attribute "AXFocusedUIElement" of frontProc
                    set selVal to value of attribute "AXSelectedText" of focusedElem
                    if selVal is not missing value then
                        set selText to selVal as text
                    end if
                end try
            end try
        end tell

        if bundleId is "com.google.Chrome" then
            try
                tell application "Google Chrome" to set activeUrl to URL of active tab of front window
            end try
        else if bundleId is "com.apple.Safari" then
            try
                tell application "Safari" to set activeUrl to URL of current tab of front window
            end try
        end if

        return appName & "\n<<SEP>>\n" & bundleId & "\n<<SEP>>\n" & winTitle & "\n<<SEP>>\n" & activeUrl & "\n<<SEP>>\n" & selText
        '''
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if res.returncode == 0 and res.stdout:
                parts = res.stdout.strip("\r\n").split("\n<<SEP>>\n")
                if len(parts) >= 5:
                    ctx.app_name = parts[0].strip()
                    ctx.bundle_id = parts[1].strip()
                    ctx.window_title = parts[2].strip()
                    ctx.url = parts[3].strip()
                    ctx.selected_text = parts[4].strip()
        except Exception as e:
            logger.debug(f"Context capture timed out or skipped: {e}")

        self._last_context = ctx
        return ctx


context_capturer = FocusedContextCapturer()
