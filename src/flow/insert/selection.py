"""Read the currently selected text of the focused app via a clipboard-safe Ctrl+C."""

from __future__ import annotations

import time
import uuid

from flow.insert import clipboard, winapi

# Ctrl+C interrupts the running program in a terminal, so never send it there.
TERMINALS = {
    "windowsterminal.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "conhost.exe",
    "mintty.exe",
    "alacritty.exe",
    "wezterm-gui.exe",
}
# Editors that copy the whole current line when nothing is selected.
LINE_COPY_APPS = {"code.exe", "cursor.exe", "devenv.exe", "sublime_text.exe", "notepad++.exe"}
MAX_SELECTION_CHARS = 20_000


class SelectionError(Exception):
    """Human-readable reason why selected text could not be used."""


def check_app(process: str) -> None:
    if process.lower() in TERMINALS:
        raise SelectionError("Command Mode is not available in terminals")


def interpret_copy(process: str, text: str | None) -> str:
    """Turn the clipboard text captured after Ctrl+C into the selection, or raise."""
    if not text or not text.strip():
        raise SelectionError("Select some text first")
    if process.lower() in LINE_COPY_APPS and text.endswith(("\n", "\r")):
        raise SelectionError("Select some text first")  # editor copied the empty-selection line
    if len(text) > MAX_SELECTION_CHARS:
        raise SelectionError("The selection is too long")
    return text


def capture_selection(process: str = "", timeout: float = 0.7) -> str:
    """Copy the selection with Ctrl+C and return it. The user's clipboard is restored."""
    check_app(process)
    winapi.wait_modifiers_released()
    marker = f"​__flow_{uuid.uuid4().hex}__"
    with clipboard.preserved_clipboard() as holder:
        holder.seq = clipboard.set_text(marker)
        winapi.chord([winapi.VK_CONTROL, winapi.VK_C])
        deadline = time.monotonic() + timeout
        changed = False
        while time.monotonic() < deadline:
            if clipboard.sequence_number() != holder.seq:
                changed = True
                break
            time.sleep(0.01)
        text = None
        if changed:
            time.sleep(0.03)  # let the app finish writing all formats
            holder.seq = clipboard.sequence_number()  # our own copy: allow the restore
            text = clipboard.get_text()
    if text == marker:
        text = None
    return interpret_copy(process, text)
