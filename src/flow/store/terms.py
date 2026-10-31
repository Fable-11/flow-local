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
# Everyday words that only get a capital at the start of a sentence. A dictionary entry for one of
# these would capitalise it everywhere.
COMMON_WORDS = frozenset(
    "a about after all also an and any are as at be because been before but by can could did do "
    "does for from had has have he her him his how i if in into is it its just like me more my "
    "no not now of on one only or other our out she so some than that the their them then there "
    "these they this to too up us very was we were what when where which who why will with would "
    "yes you your".split()
)


def candidate_terms(text: str, unique: bool = True) -> list[str]:
    """Rare-looking terms in ``text``: mid-sentence capitals, hyphenated, digit or camelCase words.

    With ``unique`` each term is returned once per call, so counting calls counts dictations,
    not repeats.
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in WORD.finditer(text):
        w = m.group(0).strip("'-")
        if len(w) < 3 or w.casefold() in _COMMON_CAPITALISED or w.casefold() in COMMON_WORDS:
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
