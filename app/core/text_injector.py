"""
Willow-inspired SmartInsertions & PasteboardReadReceipt (`app/core/text_injector.py`).
Injects dictated or AI-generated text directly into the currently focused cursor position
while preserving and restoring the user's original clipboard content.
"""

import logging
import subprocess
import sys
import time
from typing import List
from langchain_core.tools import StructuredTool, BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger("maxi.injector")


class TextInjector:
    """
    Clipboard-preserving cursor text injector (`SmartInsertions` + `PasteboardReadReceipt`).
    1. Snapshots current clipboard (`pbpaste`).
    2. Copies target text (`pbcopy`).
    3. Synthesizes Cmd+V (`keystroke "v" using command down`) into the focused app.
    4. Waits for the target app to read the pasteboard, then restores the original clipboard.
    """

    def _get_clipboard(self) -> str:
        if sys.platform != "darwin":
            return ""
        try:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=0.5)
            if res.returncode == 0:
                return res.stdout
        except Exception:
            pass
        return ""

    def _set_clipboard(self, text: str):
        if sys.platform != "darwin":
            return
        try:
            subprocess.run(["pbcopy"], input=text, text=True, timeout=0.5)
        except Exception as e:
            logger.warning(f"Failed setting clipboard: {e}")

    def inject_text(
        self,
        text: str,
        restore_clipboard: bool = True,
        preserve_clipboard: bool | None = None,
    ) -> bool:
        """Injects `text` at the active cursor and restores the previous clipboard."""
        if not text:
            return False
        if sys.platform != "darwin":
            logger.warning("Cursor text injection is currently only supported on macOS.")
            return False

        should_restore = preserve_clipboard if preserve_clipboard is not None else restore_clipboard
        prior_clipboard = self._get_clipboard() if should_restore else ""
        try:
            self._set_clipboard(text)
            time.sleep(0.03)
            res = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to keystroke "v" using command down',
                ],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            success = res.returncode == 0
        except Exception as e:
            logger.error(f"Failed injecting text at cursor: {e}")
            success = False
        finally:
            if should_restore:
                # Allow 120ms PasteboardReadReceipt window before restoring prior clipboard
                time.sleep(0.12)
                self._set_clipboard(prior_clipboard)

        return success


text_injector = TextInjector()


class InjectTextArgs(BaseModel):
    text: str = Field(..., description="The exact text, code snippet, or rewritten prose to type/paste directly at the user's active cursor position.")


def _inject_text_tool_fn(text: str) -> str:
    ok = text_injector.inject_text(text, restore_clipboard=True)
    if ok:
        return f"Successfully inserted {len(text)} characters at the active cursor (clipboard preserved)."
    return "Failed to insert text at the active cursor."


inject_text_at_cursor = StructuredTool.from_function(
    func=_inject_text_tool_fn,
    name="inject_text_at_cursor",
    description=(
        "Pastes or types text directly into the user's currently focused text field or editor cursor "
        "while preserving their original clipboard. Use this whenever the user asks to 'type this', "
        "'insert this', 'paste this', 'dictate this', or 'write a reply here'."
    ),
    args_schema=InjectTextArgs,
)


def get_text_injector_tools() -> List[BaseTool]:
    """Returns the LangChain tool for injecting text directly into the focused cursor."""
    return [inject_text_at_cursor]

