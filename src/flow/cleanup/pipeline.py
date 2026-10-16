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
    r"no[,.]?\s+wait|wait[,.]?\s+no|i\s+mean|i\s+meant|scratch\s+that|actually[,.]?\s+no|"
    r"make\s+that|or\s+rather|لا\s+لحظة|قصدي|[اأ]قصد|امسح|تجاهل",
    re.IGNORECASE,
)
_WORD = re.compile(r"[\w؀-ۿ]+", re.UNICODE)
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
    return None


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
