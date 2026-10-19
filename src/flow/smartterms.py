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


# -- look-alike words: the speech model writes the letter or pronoun it hears -------------------
_EYE_BEFORE = (
    r"(?:my|your|his|her|their|our|its|the|an?|left|right|both|one|each|human|naked|black|"
    r"bloodshot|red|dry|good|bad|weak|blind|lazy|pink)"
)
_EYE_AFTER = r"(?:drops|lashes|brows|lids|sockets)"
_QUEUE_BEFORE = (
    r"(?:message|job|task|priority|print|work|event|request|retry|circular|blocking|fifo|lifo|"
    r"double[- ]ended|dead[- ]letter)"
)
_NOT_THE_LETTER = r"(?!\s+(?:key|button|letter|section|sign|symbol|and\s+a\b|&|tier|series|factor))"

# (pattern, replacement template). Each only fires where the letter/pronoun makes no sense.
_LOOKALIKES: list[tuple[re.Pattern[str], str]] = [
    # eye / eyes: "my I", "the left I", "I drops" -- a pronoun never follows these words
    (re.compile(rf"\b({_EYE_BEFORE})\s+I\b(?!\s+in\s+(?:the|team))", re.I), r"\1 eye"),
    (re.compile(rf"\b({_EYE_BEFORE})\s+Is\b", re.I), r"\1 eyes"),
    (re.compile(rf"\bI\s+({_EYE_AFTER})\b"), r"eye \1"),
    # queue / queues: the letter Q where a line or a data structure is meant
    (re.compile(rf"\b({_QUEUE_BEFORE})\s+Q(s?)\b", re.I), r"\1 queue\2"),
    (re.compile(r"\b(stacks?)\s+(and|or)\s+(?:Q|cue)(s?)\b", re.I), r"\1 \2 queue\3"),
    (re.compile(r"\b(?:Q|cue)(s?)\s+(and|or)\s+(stacks?)\b", re.I), r"queue\1 \2 \3"),
    (re.compile(rf"\b({_QUEUE_BEFORE})\s+cue(s?)\b", re.I), r"\1 queue\2"),
    (
        re.compile(
            rf"\b(in|into|to|from|of|empty|the|a|this|that|our|my|your)\s+Q(s?)\b{_NOT_THE_LETTER}"
            r"(?<!\bletter Q)",
        ),
        r"\1 queue\2",
    ),
    (re.compile(r"\b(in|into)\s+(the|a)\s+cue\b", re.I), r"\1 \2 queue"),
    (
        re.compile(r"\bQ\s+(data structure|implementation|size|length|depth|overflow)\b"),
        r"queue \1",
    ),
]


def _fix_lookalikes(text: str) -> str:
    for pattern, replacement in _LOOKALIKES:
        text = pattern.sub(replacement, text)
    # a sentence that now starts with the fixed word keeps its capital
    return re.sub(
        r"(^|[.!?]\s+)(eyes?|queues?)\b", lambda m: m.group(1) + m.group(2).capitalize(), text
    )


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
    return _fix_lookalikes(text)
