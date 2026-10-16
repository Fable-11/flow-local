"""Insert text into the focused app: clipboard paste, with a direct-typing fallback."""

from __future__ import annotations

import logging
import time

from flow.insert import clipboard, winapi

log = logging.getLogger(__name__)

# Per-process paste method overrides. Default is Ctrl+V.
#   "shift": Ctrl+Shift+V (terminals that reserve Ctrl+V)
#   "type":  type characters directly (apps that ignore synthetic paste)
PASTE_OVERRIDES: dict[str, str] = {
    "mintty.exe": "shift",
    "alacritty.exe": "shift",
}

PASTE_SETTLE_S = 0.12  # apps read the clipboard asynchronously; wait before restoring


def method_for(process: str, default: str = "clipboard") -> str:
    return PASTE_OVERRIDES.get(process.lower(), default)


def paste_text(text: str, method: str = "clipboard", restore_clipboard: bool = True) -> str:
    """Insert ``text`` at the cursor. Returns the method actually used.

    Falls back to direct typing if the clipboard is unavailable.
    """
    if not text:
        return method
    winapi.wait_modifiers_released()
    if method == "type":
        winapi.type_unicode(text)
        return "type"
    try:
        ctx = clipboard.preserved_clipboard() if restore_clipboard else None
        if ctx is None:
            _paste_via_clipboard(text, method, None)
        else:
            with ctx as holder:
                _paste_via_clipboard(text, method, holder)
        return method
    except OSError:
        log.warning("clipboard paste failed, typing instead", exc_info=True)
        winapi.type_unicode(text)
        return "type"


def _paste_via_clipboard(text: str, method: str, holder) -> None:  # noqa: ANN001
    seq = clipboard.set_text(text)
    if holder is not None:
        holder.seq = seq
    keys = [winapi.VK_CONTROL, winapi.VK_SHIFT, winapi.VK_V] if method == "shift" else [
        winapi.VK_CONTROL,
        winapi.VK_V,
    ]
    winapi.chord(keys)
    time.sleep(PASTE_SETTLE_S)
