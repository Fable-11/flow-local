"""Symbols said aloud ("underscore", "at sign", "hashtag", "dot js") written as the symbol.

Only words that clearly name a symbol are converted. Ordinary words that can also name a symbol
("dot", "slash") are converted only where the symbol is the obvious meaning, for example
"index dot js", "three dot five" or "yes slash no". A sentence such as "she put a dot on the map"
or "the at sign is on my keyboard" is left alone.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_I = re.IGNORECASE
EXTENSIONS = (
    "txt|doc|docx|xls|xlsx|ppt|pptx|pdf|png|jpg|jpeg|gif|svg|mp3|mp4|wav|zip|rar|json|xml|csv|"
    "html|htm|css|js|ts|tsx|jsx|py|java|cpp|go|rs|rb|php|sh|bat|ps1|exe|md|yml|yaml|ini|log|sql|"
    "env|toml|lock|cfg"
)
_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
_NUM = rf"(?:\d+|{'|'.join(_NUMBERS)})"
_ARTICLES = frozenset("the a an this that my your our its of in on for".split())
_SLASH_PAIRS = frozenset(
    "and/or yes/no he/she his/her on/off true/false read/write input/output pass/fail either/or"
    .split()
)
_SLASH_FIRST = "|".join(sorted({p.split("/")[0] for p in _SLASH_PAIRS}))
_PAREN = r"(?:parenthesis|parentheses|paren|bracket)"


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, _I)


def _previous_word(text: str, pos: int) -> str:
    m = re.search(r"([A-Za-z']+)\W*$", text[:pos])
    return m.group(1).lower() if m else ""


def _glue(symbol: str, left: bool = True, right: bool = True) -> Callable[[re.Match[str]], str]:
    """Replacement that joins the symbol to a neighbouring word, or sets it apart with spaces.

    After an article ("the at sign") the words name the symbol itself and are left as they are.
    """

    def sub(m: re.Match[str]) -> str:
        text = m.string
        if _previous_word(text, m.start()) in _ARTICLES:
            return m.group(0)
        before = text[: m.start()].rstrip(" ")
        after = text[m.end() :].lstrip(" ")
        word_before = bool(before) and (before[-1].isalnum() or before[-1] in "_)]")
        word_after = bool(after) and (after[0].isalnum() or after[0] in "_([")
        lead = "" if (left and word_before) else (" " if before else "")
        trail = "" if (right and word_after) else (" " if after else "")
        return f"{lead}{symbol}{trail}"

    return sub


# Longer phrases first. A phrase is eaten together with the spaces around it.
_RULES: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    # joined to both neighbours: john@gmail, user_name
    (_rx(r"\s*(?<!\w)(?:at\s+sign|add\s+sign|at\s+symbol|at\s+the\s+rate(?:\s+of)?)(?!\w)\s*"),
     _glue("@")),
    (_rx(r"\s*(?<!\w)under\s?score(?!\w)\s*"), _glue("_")),
    (_rx(r"\s*(?<!\w)forward\s+slash(?!\w)\s*"), _glue("/")),
    (_rx(r"\s*(?<!\w)back\s?slash(?!\w)\s*"), _glue("\\", left=False)),
    # glued to the next word: #flow, $50
    (_rx(r"\s*(?<!\w)(?:hash\s?tag|hash\s+sign|pound\s+sign|number\s+sign)(?!\w)\s*"),
     _glue("#", left=False)),
    (_rx(r"\s*(?<!\w)dollar\s+sign(?!\w)\s*"), _glue("$", left=False)),
    (_rx(r"\s*(?<!\w)tilde(?!\w)\s*"), _glue("~", left=False)),
    # glued to the previous word: 50%
    (_rx(r"\s*(?<!\w)percent\s+sign(?!\w)"), "%"),
    # set apart with spaces
    (_rx(r"\s*(?<!\w)(?:ampersand|and\s+sign)(?!\w)\s*"), " & "),
    (_rx(r"\s*(?<!\w)plus\s+sign(?!\w)\s*"), " + "),
    (_rx(r"\s*(?<!\w)equals?\s+sign(?!\w)\s*"), " = "),
    (_rx(r"\s*(?<!\w)asterisk(?!\w)\s*"), " * "),
    # brackets
    (_rx(rf"(?<!\w)(?:open|left)\s+(?:round\s+)?{_PAREN}(?!\w)\s*"), "("),
    (_rx(rf"\s*(?<!\w)(?:close|right)\s+(?:round\s+)?{_PAREN}(?!\w)"), ")"),
    (_rx(r"(?<!\w)open\s+square\s+bracket(?!\w)\s*"), "["),
    (_rx(r"\s*(?<!\w)close\s+square\s+bracket(?!\w)"), "]"),
    (_rx(r"(?<!\w)open\s+curly\s+(?:bracket|brace)(?!\w)\s*"), "{"),
    (_rx(r"\s*(?<!\w)close\s+curly\s+(?:bracket|brace)(?!\w)"), "}"),
]
_PROVIDER_AT = _rx(
    r"(?<=\w)\s+at\s+(?=(?:gmail|yahoo|outlook|hotmail|icloud|proton|protonmail|live|msn|aol)\b)"
)
_NUMBER_DOT = _rx(rf"(?<!\w)({_NUM})\s+(?:dot|point)\s+({_NUM})(?!\w)")
_FILE_DOT = _rx(rf"(?<!\w)([A-Za-z0-9_-]+)\s+dot\s+({EXTENSIONS})(?!\w)")
_SLASH = _rx(rf"(?<!\w)({_SLASH_FIRST})\s+slash\s+(\w+)(?!\w)")


_PRONOUNS = frozenset("me you him her us them it home work here there look meet".split())


def _provider_at(m: re.Match[str]) -> str:
    """"john at gmail" is an address; "email me at gmail" is not ("me@" is no one's name)."""
    if _previous_word(m.string, m.start()) in _PRONOUNS:
        return m.group(0)
    return "@"


def _number(word: str) -> str:
    return _NUMBERS.get(word.lower(), word)


def _file_dot(m: re.Match[str]) -> str:
    if m.group(1).lower() in _ARTICLES:
        return m.group(0)
    return f"{m.group(1)}.{m.group(2).lower()}"


def _slash(m: re.Match[str]) -> str:
    pair = f"{m.group(1).lower()}/{m.group(2).lower()}"
    return f"{m.group(1)}/{m.group(2)}" if pair in _SLASH_PAIRS else m.group(0)


def speak_symbols(text: str) -> str:
    """Write spoken symbols as the symbol itself."""
    if not text:
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    text = _PROVIDER_AT.sub(_provider_at, text)
    text = _NUMBER_DOT.sub(lambda m: f"{_number(m.group(1))}.{_number(m.group(2))}", text)
    text = _FILE_DOT.sub(_file_dot, text)
    return _SLASH.sub(_slash, text)
