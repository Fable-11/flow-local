"""Links and email addresses said aloud, written the way they are typed.

Speech models and the cleanup step both mangle these: spaces stay in, the first letter gets a
capital, a sentence period is stuck onto the end, or "dot com" is left as words. The spoken
form is turned into the real link first, and the link is then hidden from the cleanup step
behind a placeholder, so nothing can change it afterwards.
"""

from __future__ import annotations

import re

TLDS = (
    "com|net|org|io|co|app|dev|ai|edu|gov|info|me|sa|ae|uk|us|tv|xyz|cloud|tech|online|site|"
    "store|blog|page|link"
)
_DOT = r"(?:dot|period|point)"
_WORD = r"[A-Za-z0-9]+"
_LABEL = rf"{_WORD}(?:\s+(?:dash|hyphen|underscore)\s+{_WORD})*"
_PATH_PART = rf"\s+slash\s+{_LABEL}(?:\s+{_DOT}\s+{_WORD})?"
_SPOKEN_URL = re.compile(
    rf"(?:\b(?:https?|ftp)\s+colon\s+slash\s+slash\s+)?"
    rf"\b{_LABEL}(?:\s+{_DOT}\s+{_LABEL})*\s+{_DOT}\s+(?:{TLDS})\b(?:\s+{_DOT}\s+(?:{TLDS})\b)?"
    rf"(?:{_PATH_PART})*(?:\s+slash\b)?",
    re.IGNORECASE,
)
_SPOKEN_AT = re.compile(r"\s+at\s+", re.IGNORECASE)
_EMAIL_CONTEXT = re.compile(r"\b(e-?mail|mail|address|contact|send|write)\b", re.IGNORECASE)
# a word before "at" that is never half of an address: "look at google.com", "available at ..."
_NOT_A_NAME = frozenset(
    "me you him her it us them home work look looking meet arrive arrived available here there "
    "stare glance aim laugh stop start live lives sit sitting stay ask asked ".split()
)

# "the dot com era" is not a link: these words never start a link
_NOT_A_LABEL = frozenset("the a an this that my your our its every each of in on for one".split())

_SIGNS = (
    (re.compile(r"\s+(?:dot|period|point)\s+", re.I), "."),
    (re.compile(r"\s+slash\s+", re.I), "/"),
    (re.compile(r"\s+slash$", re.I), "/"),
    (re.compile(r"\s+colon\s+", re.I), ":"),
    (re.compile(r"\s+(?:dash|hyphen)\s+", re.I), "-"),
    (re.compile(r"\s+underscore\s+", re.I), "_"),
)
_SPACED_DOT = re.compile(rf"(?<=[A-Za-z0-9])(?:\s\.|\.\s)(?=(?:{TLDS})\b(?![A-Za-z0-9]))")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_LINK = re.compile(
    rf"(?:\b(?:https?|ftp)://)?(?:[A-Za-z0-9-]+\.)+(?:{TLDS})\b(?:/[^\s]*)?|{_EMAIL.pattern}",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?)\"'"
TOKEN = re.compile(r"⟦U(\d+)⟧")


def _write(spoken: str) -> str:
    out = re.sub(
        r"\b(https?|ftp)\s+colon\s+slash\s+slash\s+", r"\1://", spoken.strip(), flags=re.I
    )
    for pattern, sign in _SIGNS:
        out = pattern.sub(sign, out)
    return re.sub(r"\s+", "", out).lower()


def _spoken_emails(text: str) -> str:
    """Turn "john dot smith at gmail.com" into an address when it is clearly one."""
    pattern = re.compile(
        rf"\b({_LABEL}(?:\s+(?:{_DOT}|dash|hyphen|underscore)\s+{_LABEL}){{0,3}})"
        rf"\s+(?:at|@)\s+((?:[A-Za-z0-9-]+\.)+(?:{TLDS}))\b",
        re.IGNORECASE,
    )

    def sub(m: re.Match[str]) -> str:
        local = m.group(1)
        words = local.lower().split()
        if words[-1] in _NOT_A_NAME or (len(words) == 1 and words[0] in _NOT_A_NAME):
            return m.group(0)
        spoken_form = bool(re.search(r"\b(dot|period|dash|hyphen|underscore)\b", local, re.I))
        has_digit = any(c.isdigit() for c in local)
        before = text[max(0, m.start() - 40) : m.start()]
        if not (spoken_form or has_digit or _EMAIL_CONTEXT.search(before)):
            return m.group(0)
        return f"{_write(local)}@{m.group(2).lower()}"

    return pattern.sub(sub, text)


def speak_to_links(text: str) -> str:
    """Write spoken links and addresses as typed ("github dot com" -> "github.com")."""
    if not text:
        return text
    def spoken(m: re.Match[str]) -> str:
        first = m.group(0).split()[0].lower()
        return m.group(0) if first in _NOT_A_LABEL else _write(m.group(0))

    text = _SPOKEN_URL.sub(spoken, text)
    text = _SPACED_DOT.sub(".", text)
    return _spoken_emails(text)


def protect_links(text: str) -> tuple[str, list[str]]:
    """Swap each link or address for a placeholder like ⟦U0⟧. Returns (text, the links)."""
    links: list[str] = []

    def sub(m: re.Match[str]) -> str:
        link = m.group(0)
        tail = ""
        while link and link[-1] in _TRAILING:
            tail = link[-1] + tail
            link = link[:-1]
        if not link:
            return m.group(0)
        links.append(link)
        return f"⟦U{len(links) - 1}⟧{tail}"

    return _LINK.sub(sub, text), links


def restore_links(text: str, links: list[str]) -> str:
    """Put the links back in place of their placeholders."""
    if not links:
        return text

    def sub(m: re.Match[str]) -> str:
        i = int(m.group(1))
        return links[i] if i < len(links) else m.group(0)

    return TOKEN.sub(sub, text)
