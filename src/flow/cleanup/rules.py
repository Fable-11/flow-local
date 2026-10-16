"""Deterministic, rule-based transcript cleanup (English + Arabic).

Used on its own when the LLM is off or unavailable, and as pre/post processing around the LLM.
Conservative by design: when a rule could change meaning, it is left to the LLM or skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Sentinels survive the LLM untouched and become whitespace in ``apply_post``.
NL = "⟦NL⟧"
PARA = "⟦P⟧"
ENTER = "⟦ENTER⟧"
SENTINELS = (NL, PARA, ENTER)

_F = re.IGNORECASE | re.UNICODE
_AR = "؀-ۿ"
_ARL = "ء-ي"  # Arabic letters only (excludes Arabic punctuation)


@dataclass
class RuleOptions:
    spoken_commands: bool = True
    press_enter: bool = False  # experimental: "press enter" -> real Enter key
    remove_fillers: bool = True
    self_corrections: bool = True
    lists: bool = True
    capitalize: bool = True
    final_period: bool = True


# -- spoken commands ------------------------------------------------------------------------
_COMMANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r",?\s*(?<!\w)new\s*paragraph(?!\w)[.,]?\s*", _F), f" {PARA} "),
    (re.compile(r",?\s*(?<!\w)new\s*line(?!\w)[.,]?\s*", _F), f" {NL} "),
    (re.compile(r",?\s*(?<![\w])فقرة\s+جديدة(?![\w])[.,،]?\s*", _F), f" {PARA} "),
    (re.compile(r",?\s*(?<![\w])سطر\s+جديد(?![\w])[.,،]?\s*", _F), f" {NL} "),
    (re.compile(r"\s*(?<!\w)question\s+mark(?!\w)[.,]?", _F), "?"),
    (re.compile(r"\s*(?<!\w)exclamation\s+(?:mark|point)(?!\w)[.,]?", _F), "!"),
    (re.compile(r"\s*(?<!\w)comma(?!\w)[.,]?", _F), ","),
    (re.compile(r"\s*(?<![\w])علامة\s+استفهام(?![\w])[.,]?", _F), "؟"),
    (re.compile(r"\s*(?<![\w])علامة\s+تعجب(?![\w])[.,]?", _F), "!"),
    (re.compile(r"\s*(?<![\w])فاصلة(?![\w])[.,]?", _F), "،"),
]
# "period"/"full stop"/"نقطة" are ordinary nouns, so they only count at the end or before a break.
_END_WORDS = re.compile(
    rf"\s*(?<![\w])(?:period|full\s+stop|نقطة)(?![\w])[.,]?(?=\s*(?:$|{NL}|{PARA}))", _F
)
_PRESS_ENTER = re.compile(r",?\s*(?<!\w)(?:press|hit)\s+enter(?!\w)[.,]?\s*", _F)


def _spoken_commands(text: str, opts: RuleOptions) -> str:
    for pat, repl in _COMMANDS:
        text = pat.sub(repl, text)
    text = _END_WORDS.sub(".", text)
    if opts.press_enter:
        text = _PRESS_ENTER.sub(f" {ENTER} ", text)
    return text


# -- fillers ----------------------------------------------------------------------------------
_EN_FILLER = r"(?:um+|uh+|uhm+|erm+|er|hmm+)"
_FILLER_SIMPLE = re.compile(rf",?\s*(?<!\w){_EN_FILLER}(?!\w)[,.]?(?=\s|$)", _F)
_FILLER_PHRASE = re.compile(
    r"(?:(?<=,)|(?<=^)|(?<=[.!?]))\s*(?:you\s+know|like|i\s+mean)\s*,\s*", _F
)
_FILLER_BRACKETED = re.compile(r",\s*(?:you\s+know|like)\s*,", _F)
_AR_HESITATION = re.compile(rf"(?<![{_ARL}\w])[اإأآ]?م{{2,}}(?![{_ARL}\w])[,،]?", _F)
_AR_YAANI_EDGE = re.compile(rf"(?:^|(?<=[.!?؟\n]))\s*يعني(?![{_ARL}])\s*[,،]?\s*", _F)
_AR_YAANI_COMMAS = re.compile(rf"[,،]\s*يعني(?![{_ARL}])\s*[,،]", _F)
_STUTTER = re.compile(r"(?<!\w)(\w+)(?:\s+\1(?!\w))+", _F)
_STUTTER_KEEP = {"had", "that", "is", "very", "no", "bye", "so", "well", "knock", "ha"}


def _fillers(text: str) -> str:
    text = _FILLER_SIMPLE.sub(" ", text)
    text = _FILLER_BRACKETED.sub(" ", text)
    text = _FILLER_PHRASE.sub(" ", text)
    text = _AR_HESITATION.sub(" ", text)
    text = _AR_YAANI_COMMAS.sub(" ", text)
    text = _AR_YAANI_EDGE.sub(" ", text)

    def _dedupe(m: re.Match[str]) -> str:
        return m.group(0) if m.group(1).lower() in _STUTTER_KEEP else m.group(1)

    return _STUTTER.sub(_dedupe, text)


# -- self corrections ------------------------------------------------------------------------
_EN_NUMS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy "
    "eighty ninety hundred thousand monday tuesday wednesday thursday friday saturday "
    "sunday january february march april may june july august september october november "
    "december noon midnight"
).split()
_AR_NUMS = (
    "واحد اثنين اثنان ثلاثة ثلاثه اربعة أربعة اربعه خمسة خمسه ستة سته سبعة سبعه ثمانية "
    "ثمانيه تسعة تسعه عشرة عشره السبت الأحد الاحد الاثنين الثلاثاء الأربعاء الاربعاء "
    "الخميس الجمعة"
).split()
_NUM = r"(?:[\d٠-٩]+(?:[.:][\d٠-٩]+)?|" + "|".join(_EN_NUMS + _AR_NUMS) + ")"
_UNIT = (
    r"(?:a\.?m\.?|p\.?m\.?|o'clock|dollars?|riyals?|minutes?|hours?|days?|people|percent|%"
    r"|ريال|دقيقة|دقائق|ساعة|ساعات|يوم|أيام|اشخاص|أشخاص)(?![A-Za-z])"
)
_MARK = (
    r"(?:no[,.]?\s+wait|wait[,.]?\s+no|no[,.]?\s+sorry|sorry[,.]?\s+(?:i\s+meant|i\s+mean|make\s+that)"
    r"|sorry|i\s+mean|i\s+meant|make\s+that|actually[,.]?\s+no|or\s+rather"
    r"|لا\s+لحظة|لا\s+لا|لا\s+قصدي|لا\s+[اأ]قصد|لا\s+بل|قصدي|[اأ]قصد|لا\s+انتظر)"
)
_CORRECTION = re.compile(
    rf"(?<![\w])(?P<old>{_NUM}(?:\s*(?P<ou>{_UNIT}))?)\s*[,.،]?\s*{_MARK}\s*[,.،]?\s*"
    rf"(?P<new>{_NUM}(?:\s*(?P<nu>{_UNIT}))?)(?![\w])",
    _F,
)
_SCRATCH = re.compile(
    r"\s*(?<![\w])(?:scratch\s+that|delete\s+that|ignore\s+that|امسح\s+(?:هذا|هذه|الجملة)"
    r"|تجاهل\s+(?:هذا|ذلك))(?![\w])[.,،]?\s*",
    _F,
)


def _correct_match(m: re.Match[str]) -> str:
    new = m.group("new")
    if m.group("ou") and not m.group("nu"):
        new = f"{new} {m.group('ou')}"
    return new


def _self_corrections(text: str) -> str:
    for _ in range(4):
        new = _CORRECTION.sub(_correct_match, text)
        if new == text:
            break
        text = new
    while True:
        m = _SCRATCH.search(text)
        if not m:
            break
        before = text[: m.start()]
        cut = max(before.rfind(c) for c in ".!?؟\n")
        text = (before[: cut + 1] if cut >= 0 else "") + " " + text[m.end() :]
    return text


def apply_pre(text: str, opts: RuleOptions | None = None) -> str:
    """Spoken commands -> sentinels, fillers, self-corrections. Safe to run before the LLM."""
    opts = opts or RuleOptions()
    if opts.spoken_commands:
        text = _spoken_commands(text, opts)
    if opts.remove_fillers:
        text = _fillers(text)
    if opts.self_corrections:
        text = _self_corrections(text)
    return text


# -- lists ------------------------------------------------------------------------------------
_ORDINALS = [
    (r"first(?:ly)?", r"[اأ]ولا[ًا]?"),
    (r"second(?:ly)?", r"ثاني[اً]?[ًا]?"),
    (r"third(?:ly)?", r"ثالث[اً]?[ًا]?"),
    (r"fourth(?:ly)?", r"رابع[اً]?[ًا]?"),
    (r"fifth(?:ly)?", r"خامس[اً]?[ًا]?"),
    (r"sixth(?:ly)?", r"سادس[اً]?[ًا]?"),
]
_ORD_RE = [re.compile(rf"(?<![\w])(?:{en}|{ar})(?![\w])", _F) for en, ar in _ORDINALS]


def _lists(text: str) -> str:
    if re.search(r"(?m)^\s*(?:\d+\.|[-*•])\s", text):
        return text  # already formatted
    # two or more consecutive ordinals starting at "first" are strong evidence of a list
    marks: list[tuple[int, int]] = []
    pos = 0
    for rx in _ORD_RE:
        found = rx.search(text, pos)
        if not found:
            break
        marks.append((found.start(), found.end()))
        pos = found.end()
    if len(marks) < 2:
        return text
    pre = text[: marks[0][0]].rstrip()
    items = []
    for i, (_, end) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        item = text[end:stop].strip(" \t,:;.،")
        item = re.sub(r"\s+(?:and|then|و)$", "", item, flags=re.I).strip(" ,.;")
        if item:
            items.append(item)
    if len(items) < 2:
        return text
    body = "\n".join(f"{i}. {it}" for i, it in enumerate(items, 1))
    return f"{pre}\n{body}" if pre else body


# -- post processing ------------------------------------------------------------------------
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?،؛؟…])")
_SPACE_AFTER_PUNCT = re.compile(r"([,;!?،؛؟])(?=[^\s\d\"')\]}.,;:!?،؛؟])")
_SENT_START = re.compile(r"(^|[.!?؟]\s+|\n\s*)([a-z])")
_LOWER_I = re.compile(r"(?<![\w'])i(?=(?:'(?:m|ll|ve|d))?(?![\w']))")
_AR_CHAR = re.compile(rf"[{_AR}]")


def _arabic_punct(text: str) -> str:
    out = list(text)
    for i, ch in enumerate(out):
        if ch in ",?;":
            j = i - 1
            while j >= 0 and out[j].isspace():
                j -= 1
            if j >= 0 and _AR_CHAR.match(out[j]):
                out[i] = {",": "،", "?": "؟", ";": "؛"}[ch]
    return "".join(out)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _SPACE_AFTER_PUNCT.sub(r"\1 ", text)
    text = re.sub(r",\s*([.!?،؟])", r"\1", text)
    text = re.sub(r"([.!?])\1+", r"\1", text)
    return text.strip()


def _sentinels_to_text(text: str) -> str:
    for token, repl in ((PARA, "\n\n"), (NL, "\n"), (ENTER, "\n")):
        text = re.sub(rf"[ \t]*{re.escape(token)}[ \t]*", repl, text)
    return re.sub(r"\n{3,}", "\n\n", text).strip(" \t")


def apply_post(text: str, opts: RuleOptions | None = None) -> str:
    """Spacing, Arabic punctuation, lists, capitalization, final period, sentinels -> text."""
    opts = opts or RuleOptions()
    text = _tidy(text)
    text = _arabic_punct(text)
    if opts.lists:
        text = _lists(text)
    text = _sentinels_to_text(text)
    text = _tidy_lines(text)
    if opts.capitalize:
        text = _SENT_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)
        text = _LOWER_I.sub("I", text)
    if opts.final_period:
        text = _final_period(text)
    return text.strip()


def _tidy_lines(text: str) -> str:
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines)


def _final_period(text: str) -> str:
    body = text.rstrip()
    tail = text[len(body) :]
    if not body or len(body.split()) < 3:
        return text
    last_line = body.rsplit("\n", 1)[-1]
    if re.match(r"\d+\.\s", last_line) and len(body.rsplit("\n", 1)) > 1:
        return text  # list items stay without trailing periods
    if body[-1].isalnum() or body[-1] in ")\"'":
        return body + "." + tail
    return text


def clean_rules(text: str, opts: RuleOptions | None = None) -> str:
    """Full rule-based cleanup (no LLM)."""
    return apply_post(apply_pre(text, opts), opts)
