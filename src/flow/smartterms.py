"""Context-aware fixes for product and brand names that speech models often mishear.

The classic case is "Claude" heard as "cloud". A plain replacement would break real sentences
about cloud computing, so "cloud" only becomes "Claude" when the surrounding words point at the
AI assistant (model names, "ask Claude", "Anthropic", "ChatGPT", ...).
"""

from __future__ import annotations

import re

_CLOUD = r"(?:cloud|clod|claud|clawed|clode)"
_CLOUDY_NOUN = (
    r"(?:storage|computing|services?|providers?|servers?|infrastructure|platforms?|native|based|"
    r"migration|bills?|costs?|functions?|deployments?|hosting|backups?|security)"
)

_MODEL_NAME = re.compile(rf"\b{_CLOUD}\b(?=\s+(?:code|sonnet|opus|haiku|fable)\b)", re.I)
_DOT_MD = re.compile(rf"\b{_CLOUD}(?:\.| dot )md\b", re.I)
_ADDRESSED = re.compile(
    rf"\b(ask(?:ed|ing)?|tell|told|telling|prompt(?:ed|ing)?|ping|hey|ask)\s+{_CLOUD}\b"
    rf"(?!\s+{_CLOUDY_NOUN})",
    re.I,
)
_AI_CONTEXT = re.compile(r"\b(anthropic|chat\s?gpt|openai|gemini|copilot|llm|llms)\b", re.I)
_BARE = re.compile(rf"\b{_CLOUD}\b(?!\s+{_CLOUDY_NOUN})", re.I)
_BLOCKING_BEFORE = {
    "the", "a", "an", "in", "on", "into", "to", "our", "your", "public", "private", "hybrid",
    "multi", "from", "of", "this", "that",
}

# (pattern, replacement): spacing and capitalisation of well-known names. Whole words only.
_NAMES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bchat[\s-]?g\.?p\.?t\b", re.I), "ChatGPT"),
    (re.compile(r"\bopen\s?a\.?i\b", re.I), "OpenAI"),
    (re.compile(r"\bgit\s?hub\b", re.I), "GitHub"),
    (re.compile(r"\bv\.?\s?s\.?\s?code\b", re.I), "VS Code"),
    (re.compile(r"\banthropic\b", re.I), "Anthropic"),
    (re.compile(r"\bollama\b", re.I), "Ollama"),
]


def _previous_word(text: str, pos: int) -> str:
    m = re.search(r"([A-Za-z']+)\W*$", text[:pos])
    return m.group(1).casefold() if m else ""


def _fix_bare_cloud(text: str) -> str:
    def sub(m: re.Match[str]) -> str:
        if _previous_word(text, m.start()) in _BLOCKING_BEFORE:
            return m.group(0)
        return "Claude"

    return _BARE.sub(sub, text)


def fix_terms(text: str) -> str:
    """Return ``text`` with misheard product names corrected from context."""
    if not text:
        return text
    text = _DOT_MD.sub("CLAUDE.md", text)
    text = _MODEL_NAME.sub("Claude", text)
    text = _ADDRESSED.sub(lambda m: f"{m.group(1)} Claude", text)
    if _AI_CONTEXT.search(text) or re.search(r"\bclaude\b", text, re.I):
        text = _fix_bare_cloud(text)
    for pattern, replacement in _NAMES:
        text = pattern.sub(replacement, text)
    return text
