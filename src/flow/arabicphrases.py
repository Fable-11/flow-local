"""Common Arabic phrases that the speech model writes in Latin letters inside English text.

When a dictation is mostly English, Whisper writes "Assalamu alaikum" or "inshallah" in Latin
letters. This turns the well-known phrases back into Arabic script. Only fixed, unambiguous
phrases are covered; everything else is left exactly as heard.
"""

from __future__ import annotations

import re

_A = r"(?:a|aa|e)"  # vowel spellings
_SALAM = rf"(?:as[\s-]?)?sal{_A}m(?:u|o|un)?"  # assalam, assalamu, as-salamu, salam
_ALAYKUM = rf"{_A}?l{_A}?(?:ai|ay|ei|ey)kum"  # alaikum, alaykum, 'alaikum

# (pattern, Arabic). Longer phrases first so they win over their own prefixes.
_PHRASES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            rf"\b{_SALAM}\s*'?{_ALAYKUM}\s+wa\s+rahmat(?:u|ul)?\s?a?l?lah(?:i)?"
            r"(?:\s+wa\s+barakatu(?:h)?)?\b",
            re.I,
        ),
        "السلام عليكم ورحمة الله وبركاته",
    ),
    (re.compile(rf"\bwa\s*'?{_ALAYKUM}\s*(?:us|as|el|al)?[\s-]?sal{_A}m\b", re.I), "وعليكم السلام"),
    (re.compile(rf"\b{_SALAM}\s*'?{_ALAYKUM}\b", re.I), "السلام عليكم"),
    (re.compile(r"\bin\s?shaa?'?\s?a?llah\b", re.I), "إن شاء الله"),
    (re.compile(r"\bma\s?shaa?'?\s?a?llah\b", re.I), "ما شاء الله"),
    (re.compile(r"\bal[\s-]?hamdu?\s?(?:li|l)[\s-]?llah\b", re.I), "الحمد لله"),
    (
        re.compile(r"\bjaz{1,2}ak(?:a|i)?\s?(?:u)?allah(?:u)?\s+khair(?:an)?\b", re.I),
        "جزاك الله خيرا",
    ),
    (re.compile(r"\bsubh[a]?n[a]?\s?allah\b", re.I), "سبحان الله"),
    (re.compile(r"\bastaghfir\s?ullah\b", re.I), "أستغفر الله"),
    (re.compile(r"\ballahu\s+akbar\b", re.I), "الله أكبر"),
    (re.compile(r"\bbismillah(?:i)?(?:\s+ir[\s-]?rahman\s+ir[\s-]?rahim)?\b", re.I), "بسم الله"),
]


def arabic_phrases(text: str) -> str:
    """Return ``text`` with well-known Latin-spelled Arabic phrases written in Arabic script."""
    if not text:
        return text
    for pattern, arabic in _PHRASES:
        text = pattern.sub(arabic, text)
    return text
