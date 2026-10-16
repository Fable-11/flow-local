"""'Fix last word': learn a dictionary entry from a correction the user just made."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_EDGE = " \t\r\n.,!?;:\"'()[]{}؟،؛"
MIN_RATIO = 0.3
MAX_WORDS = 3


@dataclass(frozen=True)
class FixSuggestion:
    heard: str  # what the speech model wrote
    correct: str  # what the user fixed it to

    @property
    def spoken(self) -> str | None:
        """Spoken form to store; None for a pure capitalisation fix."""
        return None if self.heard.casefold() == self.correct.casefold() else self.heard


def suggest_fix(last_text: str, corrected: str) -> FixSuggestion | None:
    """Match the corrected word(s) to the most similar span of the last dictation."""
    corrected = corrected.strip(_EDGE)
    if not corrected or len(corrected.split()) > MAX_WORDS or len(corrected) > 60:
        return None
    words = [w for w in (t.strip(_EDGE) for t in re.findall(r"\S+", last_text)) if w]
    n = len(corrected.split())
    if not words or any(" ".join(words[i : i + n]) == corrected for i in range(len(words))):
        return None  # the dictation already said exactly this
    target = corrected.casefold().replace(" ", "")
    best: tuple[float, str] | None = None
    for span in {max(1, n - 1), n, n + 1}:
        for i in range(0, len(words) - span + 1):
            cand = " ".join(words[i : i + span])
            ratio = SequenceMatcher(None, cand.casefold().replace(" ", ""), target).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, cand)
    if best is None or best[0] < MIN_RATIO:
        return None
    return FixSuggestion(best[1], corrected)
