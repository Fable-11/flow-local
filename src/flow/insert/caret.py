"""Read the few characters around the cursor so a dictation can be fitted to them.

There is no portable way to ask another app what text is next to the cursor, so this does what a
person would: select one character to the left, copy it, and put the cursor back, then the same
to the right. The clipboard is restored. To keep it safe it only runs in apps known to behave, never
when text is selected (the dictation then replaces the selection as usual), and any doubt means
"no context", which leaves the dictation exactly as it was.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from flow.insert import clipboard, winapi
from flow.insert.context import get_active_app
from flow.insert.fit import has_arabic
from flow.insert.selection import LINE_COPY_APPS, TERMINALS

log = logging.getLogger(__name__)

# Apps where Shift+Arrow then Ctrl+C behaves as expected in a text field.
SAFE_APPS = frozenset(
    {
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
        "notepad.exe", "wordpad.exe", "winword.exe", "onenote.exe", "outlook.exe", "olk.exe",
        "slack.exe", "discord.exe", "teams.exe", "ms-teams.exe", "whatsapp.exe", "telegram.exe",
        "obsidian.exe", "notion.exe", "thunderbird.exe", "claude.exe", "chatgpt.exe",
    }
)
BEFORE_CHARS = 3
AFTER_CHARS = 2
COPY_TIMEOUT_S = 0.15
VERIFY_TIMEOUT_S = 0.08  # a selection copies at once; no selection just waits this long
SLOW_COPY_TIMEOUT_S = 0.5  # second look when the first copy brought nothing


@dataclass(frozen=True)
class Around:
    before: str
    after: str


class ProbeIO(Protocol):
    """The two things probing needs; replaced by a simulated editor in tests."""

    def press(self, vks: list[int]) -> None: ...

    def copy(self, timeout: float | None = None) -> str | None:
        """Ctrl+C and return what was copied, or None when nothing was."""
        ...

    def window_changed(self) -> bool:
        """True when another window has taken the keyboard focus since the session began."""
        ...

    def session(self):  # noqa: ANN201 - context manager that restores the clipboard
        ...


class SystemIO:
    def __init__(self) -> None:
        self._holder = None
        self._hwnd = 0

    @contextmanager
    def session(self) -> Iterator[None]:
        winapi.wait_modifiers_released()  # our synthetic keys must not mix with a held Ctrl
        self._hwnd = get_active_app().hwnd
        with clipboard.preserved_clipboard() as holder:
            self._holder = holder
            yield
        self._holder = None

    def press(self, vks: list[int]) -> None:
        winapi.chord(vks)

    def window_changed(self) -> bool:
        return bool(self._hwnd) and get_active_app().hwnd != self._hwnd

    def copy(self, timeout: float | None = None) -> str | None:
        marker = f"​__flow_{uuid.uuid4().hex}__"
        holder = self._holder
        holder.seq = clipboard.set_text(marker)
        winapi.chord([winapi.VK_CONTROL, winapi.VK_C])
        deadline = time.monotonic() + (COPY_TIMEOUT_S if timeout is None else timeout)
        while time.monotonic() < deadline:
            if clipboard.sequence_number() != holder.seq:
                time.sleep(0.02)  # let the app finish writing all formats
                holder.seq = clipboard.sequence_number()
                text = clipboard.get_text()
                return None if text in (None, marker) else text
            time.sleep(0.008)
        return None


def probe_allowed(process: str) -> bool:
    # code editors copy the whole line when nothing is selected, which would fool the probe
    p = process.lower()
    return p in SAFE_APPS and p not in TERMINALS and p not in LINE_COPY_APPS


def read_around(process: str, io: ProbeIO | None = None) -> Around | None:
    """The characters just before and after the cursor, or None when they cannot be read safely."""
    if not probe_allowed(process):
        return None
    io = io or SystemIO()
    try:
        with io.session():
            if io.copy() is not None:  # something is selected: the dictation replaces it
                return None
            before = _probe(io, winapi.VK_LEFT, winapi.VK_RIGHT, BEFORE_CHARS)
            after = _probe(io, winapi.VK_RIGHT, winapi.VK_LEFT, AFTER_CHARS)
    except Exception:  # noqa: BLE001 - never let a probe break a dictation
        log.exception("could not read the text around the cursor")
        return None
    if has_arabic(before) or has_arabic(after):
        return None
    return Around(before, after)


def _probe(io: ProbeIO, extend: int, retrace: int, count: int) -> str:
    """Select up to ``count`` characters in one direction, copy them, and put the cursor back.

    The cursor is restored by shrinking the selection with the opposite arrow, one step per
    character that was selected. Unlike pressing a plain arrow key this behaves the same in every
    app (some collapse a selection, some move one character).

    A copy that brings nothing is checked a second time, more patiently: a slow app can have a
    selection that simply has not reached the clipboard yet, and leaving it selected would make the
    paste replace the user's own text.
    """
    for _ in range(count):
        io.press([winapi.VK_SHIFT, extend])
    got = io.copy()
    if got is None:
        got = io.copy(SLOW_COPY_TIMEOUT_S)
    if got is None:
        return ""  # at the edge of the text: nothing was selected, nothing to undo
    if io.window_changed():
        raise RuntimeError("focus moved to another window while reading the cursor")
    for _ in range(len(got.replace("\r\n", "\n"))):
        io.press([winapi.VK_SHIFT, retrace])
    _make_sure_nothing_is_selected(io, retrace)
    return got


def _make_sure_nothing_is_selected(io: ProbeIO, retrace: int) -> None:
    """Look again: a lost or late key press can leave characters selected, and the next paste
    would silently replace them ("softwar" instead of "software."). A plain arrow in the retrace
    direction collapses a selection back to where the cursor started."""
    for _ in range(2):
        if io.copy(VERIFY_TIMEOUT_S) is None:
            return
        io.press([retrace])
    if io.copy(VERIFY_TIMEOUT_S) is not None:
        raise RuntimeError("could not put the cursor back after reading it")
