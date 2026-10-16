"""Decide whether a new dictation needs a leading space after the previous one."""

from __future__ import annotations

import time
from collections.abc import Callable

# Characters that attach to the previous word (no space before them).
_NO_SPACE_BEFORE = set(".,!?;:)]}%،؛؟…'\"")


class SpacingTracker:
    """Remembers the last insertion so back-to-back dictations in one window stay separated.

    Heuristic (we cannot read the caret position in arbitrary apps): if the previous
    dictation went into the same window recently and did not end in whitespace, the new
    text gets a leading space.
    """

    def __init__(self, window_s: float = 120.0, now: Callable[[], float] = time.monotonic) -> None:
        self.window_s = window_s
        self._now = now
        self._hwnd = 0
        self._time = 0.0
        self._last = ""

    def prefix_for(self, hwnd: int, text: str) -> str:
        if not text or not self._last or hwnd != self._hwnd or not hwnd:
            return ""
        if self._now() - self._time > self.window_s:
            return ""
        if self._last[-1].isspace() or text[0].isspace() or text[0] in _NO_SPACE_BEFORE:
            return ""
        return " "

    def record(self, hwnd: int, text: str) -> None:
        self._hwnd, self._time, self._last = hwnd, self._now(), text

    def forget(self) -> None:
        self._last = ""
