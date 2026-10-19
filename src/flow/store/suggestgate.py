"""Decides when the "add this word to your dictionary?" prompt may appear.

The goal is to stay out of the way: at most a few prompts a day, a pause between prompts, and a
longer pause every time the user ignores or dismisses one. Saying yes resets the pause.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from flow.store.settings_repo import SettingsRepo

KEY = "suggest_gate"
BASE_COOLDOWN_S = 10 * 60
MAX_COOLDOWN_S = 24 * 3600
MAX_PER_DAY = 3


class SuggestionGate:
    def __init__(self, repo: SettingsRepo, clock: Callable[[], float] = time.time) -> None:
        self.repo = repo
        self.clock = clock

    def _state(self) -> dict:
        s = self.repo.get(KEY, {})
        return s if isinstance(s, dict) else {}

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d")

    def allow(self) -> bool:
        s = self._state()
        shown_today = s.get("count", 0) if s.get("day") == self._today() else 0
        if shown_today >= MAX_PER_DAY:
            return False
        cooldown = min(BASE_COOLDOWN_S * 2 ** int(s.get("ignored", 0)), MAX_COOLDOWN_S)
        return self.clock() - float(s.get("last", 0)) >= cooldown

    def shown(self) -> None:
        s = self._state()
        today = self._today()
        count = s.get("count", 0) + 1 if s.get("day") == today else 1
        self.repo.set(KEY, {**s, "last": self.clock(), "day": today, "count": count})

    def answered(self, accepted: bool) -> None:
        """Yes resets the back-off; a dismissal or a prompt that timed out lengthens it."""
        s = self._state()
        ignored = 0 if accepted else int(s.get("ignored", 0)) + 1
        self.repo.set(KEY, {**s, "ignored": min(ignored, 8)})
