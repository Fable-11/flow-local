"""Finds names and jargon in finished text (the raw material for the self-learning dictionary)."""

from __future__ import annotations

import re

WORD = re.compile(r"[\w؀-ۿ][\w؀-ۿ'\-]*", re.UNICODE)
_SENT_START = re.compile(r"(?:^|[.!?؟]\s+|\n)\s*$")
_COMMON_CAPITALISED = {
    w.casefold()
    for w in (
        "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April "
        "June July August September October November December English Arabic Saudi Ramadan "
        "Eid Google Windows"
    ).split()
}


def candidate_terms(text: str, unique: bool = True) -> list[str]:
    """Rare-looking terms in ``text``: mid-sentence capitals, hyphenated, digit or camelCase words.

    With ``unique`` each term is returned once per call, so counting calls counts dictations,
    not repeats.
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in WORD.finditer(text):
        w = m.group(0).strip("'-")
        if len(w) < 3 or w.casefold() in _COMMON_CAPITALISED:
            continue
        if w.endswith("'s"):
            w = w[:-2]
        mid_capital = w[0].isupper() and not _SENT_START.search(text[: m.start()])
        odd = "-" in w or any(c.isdigit() for c in w) or re.search(r"[a-z][A-Z]", w)
        if len(w) >= 3 and (mid_capital or odd):
            if unique and w.casefold() in seen:
                continue
            seen.add(w.casefold())
            found.append(w)
    return found
