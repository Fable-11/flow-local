"""Fit a dictation to the text around the cursor.

Inserting "The meeting is tomorrow." in the middle of a sentence should not leave a capital letter
and a full stop behind. Given the few characters before and after the cursor this adjusts the
first letter, the space before, and the final full stop. When nothing is known the text is returned
unchanged, and every rule only acts when it is clearly right.
"""

from __future__ import annotations

import re

_SENTENCE_END = ".!?؟…\n"
_OPENERS = " \t\n([{\"'“‘/-"
_NO_SPACE_BEFORE = set(".,!?;:)]}%،؛؟…'\"")
_ARABIC = re.compile(r"[؀-ۿ]")
# Words that start a sentence only because of a capital: safe to lower-case mid-sentence. Names
# and "I" are not in this list, so they keep their capital.
_FUNCTION_WORDS = frozenset(
    "the a an and but or so if then than that this these those it its is are was were be been "
    "to of in on at by for with from as into about over under after before because while when "
    "where which who whom what why how we you he she they them us our your his her their my "
    "me him there here also just not no yes can could will would should may might must do does "
    "did have has had get got go going make made need want like some any all each every more "
    "most many much very too only still even again maybe please thanks".split()
)
_FIRST_WORD = re.compile(r"[A-Za-z']+")


def has_arabic(text: str) -> bool:
    return bool(_ARABIC.search(text))


def _sentence_start(before: str) -> bool:
    tail = before.rstrip(" \t")
    return not tail or tail[-1] in _SENTENCE_END


def _text_continues(after: str) -> tuple[bool, bool]:
    """(text continues after the cursor on this line, that text starts with a capital)."""
    rest = after.lstrip(" \t")
    if not rest or rest[0] == "\n":
        return False, False
    first = next((c for c in rest if c.isalpha()), "")
    return True, first.isupper()


def fit_to_context(text: str, before: str, after: str) -> str:
    """Adjust ``text`` for the characters that sit before and after the cursor."""
    if not text:
        return text
    # Capital letters and full stops follow English rules; with Arabic anywhere near the cursor they
    # are left alone. The spaces between the old text and the new text are needed in every language.
    arabic = has_arabic(text) or has_arabic(before) or has_arabic(after)
    before = before.replace("\r\n", "\n").replace("\r", "\n")
    after = after.replace("\r\n", "\n").replace("\r", "\n")
    start = _sentence_start(before)
    continues, next_is_capital = _text_continues(after)

    # first letter: only a plain function word is lowered, mid-sentence
    if not arabic and not start and text[0].isupper():
        m = _FIRST_WORD.match(text)
        if m and m.group(0).lower() in _FUNCTION_WORDS and m.group(0) != "I":
            text = text[0].lower() + text[1:]

    # final full stop: drop it when the sentence carries on after the cursor
    stand_alone = start and next_is_capital
    if not arabic and continues and not stand_alone and text.rstrip().endswith("."):
        text = text.rstrip()[:-1]

    # spaces: one before if we sit right after a word, one after if a word follows directly
    if before and before[-1] not in _OPENERS and text[0] not in _NO_SPACE_BEFORE:
        text = " " + text
    if after and (after[0].isalnum()) and not text[-1].isspace():
        text += " "
    elif continues and after[0] in " \t" and False:
        pass
    return text
