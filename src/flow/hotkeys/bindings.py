"""Chord parsing, conflict detection and the hotkey state machine (no OS calls)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

MODIFIERS = frozenset({"ctrl", "shift", "alt", "win"})

# Action strings emitted by the machine.
PTT_START = "ptt_start"
PTT_STOP = "ptt_stop"
COMMAND_START = "command_start"
COMMAND_STOP = "command_stop"
HANDSFREE_TOGGLE = "handsfree_toggle"
CANCEL = "cancel"  # the user pressed Esc: stop, discard the audio, play the stop cue
# A recording that is dropped silently because the shortcut turned into something else (a longer
# chord completed, an unrelated key joined, or it was only a quick tap). It must NOT touch the
# hands-free state: the worker used to reset it on every cancel, which broke stopping hands-free.
ABORT = "abort"
FIX_LAST = "fix_last"

DEFAULT_BINDINGS: dict[str, str] = {
    "push_to_talk": "ctrl+win",
    "hands_free": "ctrl+win+space",
    "command": "ctrl+win+alt",
    "fix_last": "ctrl+win+f",
}
CANCEL_KEY = "esc"

HOLD_ACTIONS = {"push_to_talk": (PTT_START, PTT_STOP), "command": (COMMAND_START, COMMAND_STOP)}
PRESS_ACTIONS = {"hands_free": HANDSFREE_TOGGLE, "fix_last": FIX_LAST}

_ALIASES = {"control": "ctrl", "windows": "win", "meta": "win", "super": "win", "escape": "esc"}


def parse_chord(text: str) -> frozenset[str]:
    keys = {_ALIASES.get(k.strip().lower(), k.strip().lower()) for k in text.split("+")}
    keys.discard("")
    if not keys:
        raise ValueError("empty chord")
    return frozenset(keys)


def format_chord(chord: frozenset[str]) -> str:
    mods = [m for m in ("ctrl", "shift", "alt", "win") if m in chord]
    rest = sorted(chord - MODIFIERS)
    return "+".join(mods + rest)


def find_conflicts(bindings: dict[str, str]) -> list[tuple[str, str]]:
    """Pairs of binding names that use the identical chord (subsets are allowed by design)."""
    parsed = {name: parse_chord(text) for name, text in bindings.items()}
    names = sorted(parsed)
    return [
        (a, b) for i, a in enumerate(names) for b in names[i + 1 :] if parsed[a] == parsed[b]
    ] + [(n, "cancel") for n, c in parsed.items() if c == frozenset({CANCEL_KEY})]


@dataclass
class Result:
    actions: list[str] = field(default_factory=list)
    swallow: bool = False  # do not pass this event on to the focused app
    inject_dummy: bool = False  # inject a dummy key so releasing Win does not open Start


class HotkeyMachine:
    """Turns raw key up/down events into dictation actions.

    Hold bindings (push_to_talk, command) start on chord completion and stop when any chord key
    is released. If a larger chord is completed while one is held, the held one is cancelled and
    the larger one fires. Press bindings fire once on chord completion.
    """

    def __init__(
        self,
        bindings: dict[str, str] | None = None,
        now: Callable[[], float] = time.monotonic,
        tap_s: float = 0.25,
        double_tap_s: float = 0.5,
        double_tap: bool = True,
    ) -> None:
        b = {**DEFAULT_BINDINGS, **(bindings or {})}
        self._chords = {name: parse_chord(text) for name, text in b.items()}
        self._now = now
        self._tap_s = tap_s
        self._double_s = double_tap_s
        self._double_tap = double_tap
        self._lock = threading.Lock()
        self._pressed: set[str] = set()
        self._swallowed: set[str] = set()
        self._hold: str | None = None
        self._hold_t = 0.0
        self._last_tap: float | None = None
        self._handsfree = False
        self._blocked = False
        self._used = False

    @property
    def active(self) -> bool:
        return self._hold is not None or self._handsfree

    def end_handsfree(self) -> None:
        """Call when hands-free ended on its own (silence auto-stop, error)."""
        with self._lock:
            self._handsfree = False

    def feed(self, key: str, down: bool) -> Result:
        with self._lock:
            return self._down(key) if down else self._up(key)

    # -- internals -----------------------------------------------------------------------
    def _match(self) -> str | None:
        for name, chord in self._chords.items():
            if chord == self._pressed:
                return name
        return None

    def _down(self, key: str) -> Result:
        res = Result()
        if key in self._pressed:  # auto-repeat
            res.swallow = key in self._swallowed
            return res
        self._pressed.add(key)
        if key == CANCEL_KEY and self.active:
            self._hold = None
            self._handsfree = False
            self._blocked = True
            self._swallowed.add(key)
            res.actions.append(CANCEL)
            res.swallow = True
            return res
        if self._blocked:
            return res
        name = self._match()
        if self._hold is not None:
            if name is None or name != self._hold:
                self._hold = None
                self._blocked = True
                res.actions.append(ABORT)
                if name is not None:
                    self._blocked = False
                    self._fire(name, key, res)
            return res
        if name is not None:
            self._fire(name, key, res)
        return res

    def _fire(self, name: str, key: str, res: Result) -> None:
        if name in HOLD_ACTIONS:
            if self._handsfree:  # hands-free owns the mic; ignore hold chords (don't block,
                return  # so a larger chord such as the hands-free toggle can still complete)
            res.actions.append(HOLD_ACTIONS[name][0])
            self._hold = name
            self._hold_t = self._now()
        else:
            if name == "hands_free":
                self._handsfree = not self._handsfree
            res.actions.append(PRESS_ACTIONS[name])
            self._blocked = True
        self._used = True
        if key not in MODIFIERS:
            res.swallow = True
            self._swallowed.add(key)

    def _up(self, key: str) -> Result:
        res = Result()
        self._pressed.discard(key)
        if key in self._swallowed:
            self._swallowed.discard(key)
            res.swallow = True
        if self._hold is not None and key in self._chords[self._hold]:
            stop = HOLD_ACTIONS[self._hold][1]
            held = self._now() - self._hold_t
            if held < self._tap_s:
                res.actions.append(ABORT)
                if self._double_tap and self._hold == "push_to_talk":
                    t = self._now()
                    if self._last_tap is not None and t - self._last_tap < self._double_s:
                        self._last_tap = None
                        self._handsfree = True
                        res.actions.append(HANDSFREE_TOGGLE)
                    else:
                        self._last_tap = t
            else:
                res.actions.append(stop)
            self._hold = None
            self._blocked = True
        if key == "win" and self._used:
            res.inject_dummy = True
            self._used = False
        if not self._pressed:
            self._blocked = False
            self._used = False
        return res
