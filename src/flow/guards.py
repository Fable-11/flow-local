"""Small decisions about when something went wrong, kept pure so they can be tested."""

from __future__ import annotations

import re

_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")


def describe_failure(exc: BaseException) -> str:
    """A message that tells the user what to do, instead of 'Something went wrong'."""
    text = str(exc).lower()
    if isinstance(exc, MemoryError) or "out of memory" in text:
        return "Out of memory, try again"
    busy = "clipboard" in text or getattr(exc, "winerror", 0) in (5, 1418)
    if isinstance(exc, OSError) and busy:
        return "Clipboard busy, try again"
    if isinstance(exc, TimeoutError):
        return "Took too long, try again"
    if isinstance(exc, OSError):
        return "Could not insert the text, see log"
    return "Something went wrong, see log"


def label_language(text: str, detected: str) -> str:
    """The language label of a dictation, taken from what was actually written.

    The speech model can decode English words under an Arabic language tag (an accent confuses
    the language check), so a label of "ar" on text with no Arabic letters says nothing useful.
    """
    arabic, latin = len(_ARABIC.findall(text)), len(_LATIN.findall(text))
    if arabic + latin == 0:
        return detected
    return "ar" if arabic >= latin else "en"
