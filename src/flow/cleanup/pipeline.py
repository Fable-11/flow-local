"""Cleanup pipeline: rules -> (optional) LLM -> safety checks -> rules."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace

from flow.cleanup.llm import LlmError, OllamaClient
from flow.cleanup.prompts import PromptContext, cleanup_messages
from flow.cleanup.rules import ENTER, SENTINELS, RuleOptions, apply_post, apply_pre

log = logging.getLogger(__name__)

MIN_WORDS_FOR_LLM = 4  # tiny utterances gain nothing from the LLM; skip for latency
_PREAMBLE = re.compile(
    r"^\s*(?:sure|certainly|here(?:'s| is)|cleaned(?: text)?|output|of course|"
    r"بالتأكيد|حسنا|إليك|اليك)\b",
    re.IGNORECASE,
)
# Words the model must never delete: they are content, not filler. (A correction such as
# "no wait" legitimately removes words, so the check is skipped when the source has one.)
_PROTECTED = frozenset(
    "hello hi hey hiya greetings thanks thank please goodbye bye welcome "
    "مرحبا مرحباً اهلا أهلا السلام شكرا شكراً".split()
)
_CORRECTION_HINT = re.compile(
    r"no[,.]?\s+wait|wait[,.]?\s+no|no[,.]?\s+no|i\s+mean|i\s+meant|scratch\s+that|"
    r"actually[,.]?\s+no|make\s+that|or\s+rather|sorry|لا\s+لا|لا\s+بل|لا\s+لحظة|قصدي|"
    r"[اأ]قصد|امسح|تجاهل",
    re.IGNORECASE,
)
MAX_INVENTED_WORDS = 3  # a rewrite that adds this many new content words is not a cleanup
# Small words a tidy-up may add or change without changing what was said.
_NEUTRAL = frozenset(
    "a an the is are was were be been am to of in on at and or but so it its this that these "
    "those i you we he she they me us them as for with do does did have has had will would can "
    "could should shall may might not also then there their ve re ll d s t m don didn doesn "
    "isn aren wasn weren won wouldn couldn shouldn".split()
)
_WORD = re.compile(r"[\w؀-ۿ]+", re.UNICODE)
_LINK_TOKEN = re.compile(r"⟦U\d+⟧")
_AR_LETTER = re.compile(r"[ء-ي]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


@dataclass
class CleanResult:
    text: str
    raw: str
    used_llm: bool
    note: str = ""  # why the LLM was skipped or rejected, for logs/UI
    press_enter: bool = False  # the speaker said "press enter" (experimental)


def style_options(style: str, base: RuleOptions) -> RuleOptions:
    if style == "very_casual":
        return replace(base, capitalize=False, final_period=False)
    if style in ("casual", "excited"):
        return replace(base, final_period=False)
    return base


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _script_ratio(text: str) -> float:
    ar = len(_AR_LETTER.findall(text))
    lat = len(_LATIN_LETTER.findall(text))
    return ar / (ar + lat) if ar + lat else 0.0


def _strip_wrappers(text: str) -> str:
    text = re.sub(r"</?transcript>", "", text, flags=re.IGNORECASE).strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'`":
        text = text[1:-1].strip()
    return text


def validate_llm_output(source: str, out: str) -> str | None:
    """Return None if ``out`` is a trustworthy cleanup of ``source``, else the reason."""
    if not out.strip():
        return "empty output"
    if _PREAMBLE.match(out):
        return "preamble"
    if any(source.count(s) != out.count(s) for s in SENTINELS):
        return "markers changed"
    if sorted(_LINK_TOKEN.findall(source)) != sorted(_LINK_TOKEN.findall(out)):
        return "link placeholder changed"
    if not _CORRECTION_HINT.search(source):
        out_words = set(_words(out))
        lost = sorted(w for w in set(_words(source)) & _PROTECTED if w not in out_words)
        if lost:
            return f"dropped {lost[0]!r}"
    ratio = len(out) / max(len(source), 1)
    if not 0.4 <= ratio <= 1.6:
        return f"length ratio {ratio:.2f}"
    if abs(_script_ratio(source) - _script_ratio(out)) > 0.25:
        return "language changed"
    src = set(_words(source))
    out_words = _words(out)
    if out_words and sum(w in src for w in out_words) / len(out_words) < 0.5:
        return "content changed (possible answer or hallucination)"
    if _invented_words(source, out) >= MAX_INVENTED_WORDS:
        return "added words that were not said"
    if not _CORRECTION_HINT.search(source) and _completed_ending(source, out):
        return "finished a sentence that was cut off"
    return None


def _stem(word: str) -> str:
    return word[:4]


def _invented_words(source: str, out: str) -> int:
    """Count content words in ``out`` never said (other forms of a said word are fine)."""
    said = set(_words(source))
    stems = {_stem(w) for w in said}
    return sum(
        1
        for w in _words(out)
        if w not in said
        and _stem(w) not in stems
        and w not in _NEUTRAL
        and not w.isdigit()
        and len(w) > 1
    )


def _completed_ending(source: str, out: str) -> bool:
    """True when the model added words after the last thing the speaker said."""
    src, got = _words(source), _words(out)
    if len(src) < 4 or not got:
        return False
    if src[-1].isdigit() or got[-1].isdigit():
        return False  # "one" may become "1"
    return _stem(got[-1]) != _stem(src[-1]) and got[-1] not in set(src)


class CleanupPipeline:
    def __init__(
        self,
        llm: OllamaClient | None = None,
        rules: RuleOptions | None = None,
        use_llm: bool = True,
    ) -> None:
        self.llm = llm
        self.rules = rules or RuleOptions()
        self.use_llm = use_llm

    def clean(self, raw: str, ctx: PromptContext | None = None) -> CleanResult:
        ctx = ctx or PromptContext()
        opts = style_options(ctx.style, self.rules)
        pre = apply_pre(raw, opts).strip()
        if not pre:
            return CleanResult("", raw, False, "empty")
        fallback = apply_post(pre, opts)
        enter = ENTER in pre

        if not (self.use_llm and self.llm):
            return CleanResult(fallback, raw, False, "llm off", enter)
        if len(_words(pre)) < MIN_WORDS_FOR_LLM:
            return CleanResult(fallback, raw, False, "short utterance", enter)
        if not self.llm.available():
            return CleanResult(fallback, raw, False, "llm unavailable", enter)
        if not self.llm.is_loaded():  # a load takes 3-10 s and would end in the rules anyway
            self.llm.warm_in_background()
            return CleanResult(fallback, raw, False, "llm cold", enter)
        try:
            out = _strip_wrappers(self.llm.chat(cleanup_messages(pre, ctx)))
        except LlmError as e:
            log.warning("LLM cleanup failed, using rules: %s", e)
            return CleanResult(fallback, raw, False, f"llm error: {e}", enter)
        reason = validate_llm_output(pre, out)
        if reason:
            log.warning("LLM output rejected (%s); using rules", reason)
            return CleanResult(fallback, raw, False, f"rejected: {reason}", enter)
        return CleanResult(apply_post(out, opts), raw, True, press_enter=enter)
