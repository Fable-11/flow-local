"""Turns a raw transcript into final text: snippets, dictionary, cleanup."""

from __future__ import annotations

from dataclasses import dataclass

from flow.arabicphrases import arabic_phrases
from flow.cleanup.appstyles import resolve_style
from flow.cleanup.pipeline import CleanResult, CleanupPipeline
from flow.cleanup.prompts import PromptContext
from flow.smartterms import fix_terms
from flow.store.dictionary import DictionaryStore
from flow.store.snippets import SnippetStore
from flow.store.suggestgate import SuggestionGate
from flow.stt.engine import build_initial_prompt


@dataclass
class ProcessResult:
    text: str
    kind: str  # "snippet" | "text" | "empty"
    clean: CleanResult | None = None
    press_enter: bool = False
    suggestion: str | None = None  # a learned term to ask the user about


class TextProcessor:
    def __init__(
        self,
        pipeline: CleanupPipeline,
        dictionary: DictionaryStore,
        snippets: SnippetStore,
        style: str = "default",
        custom_instructions: str = "",
    ) -> None:
        self.pipeline = pipeline
        self.dictionary = dictionary
        self.snippets = snippets
        self.style = style
        self.custom_instructions = custom_instructions
        self.cleanup_enabled = True
        self.app_styles: dict[str, str] = {}
        self.smart_terms = True
        self.arabic_phrases = True
        # auto: add silently, ask: prompt on the bar, suggest: Dictionary page only, off
        self.learn_mode = "auto"
        self.gate: SuggestionGate | None = None

    def whisper_prompt(self) -> str | None:
        """Dictionary words as Whisper ``initial_prompt`` (starred words first)."""
        return build_initial_prompt(self.dictionary.words_for_prompt())

    def process(self, raw: str, app_process: str = "", app_title: str = "") -> ProcessResult:
        snippet = self.snippets.match_exact(raw)
        if snippet:  # inserted verbatim: no cleanup, no replacements
            return ProcessResult(snippet.content, "snippet")
        text, hits = self.dictionary.apply_replacements(raw)
        if self.smart_terms:
            text = fix_terms(text)
        if self.arabic_phrases:
            text = arabic_phrases(text)
        if not self.cleanup_enabled:  # insert the transcript as Whisper wrote it
            text, _ = self.snippets.expand_embedded(text.strip())
            self.dictionary.record_use(hits)
            return ProcessResult(
                text, "text" if text else "empty", suggestion=self._learn(text)
            )
        ctx = PromptContext(
            style=resolve_style(app_process, self.style, self.app_styles),
            app_process=app_process,
            app_title=app_title,
            glossary=self.dictionary.words_for_prompt(),
            custom_instructions=self.custom_instructions,
        )
        cleaned = self.pipeline.clean(text, ctx)
        if not cleaned.text:
            return ProcessResult("", "empty", cleaned)
        out, hits2 = self.dictionary.apply_replacements(cleaned.text)  # LLM may alter casing
        if self.smart_terms:
            out = fix_terms(out)
        if self.arabic_phrases:
            out = arabic_phrases(out)
        out, _ = self.snippets.expand_embedded(out)
        self.dictionary.record_use(hits + hits2)
        suggestion = self._learn(out)
        press = cleaned.press_enter
        if press:
            out = out.rstrip("\n")
        return ProcessResult(out, "text", cleaned, press, suggestion)

    def _learn(self, text: str) -> str | None:
        """Let the dictionary pick up names and terms that keep coming back.

        "auto" adds them silently. "ask" returns at most one term to offer, and only when the
        gate says it is a good moment (not too often, backing off if the user ignores prompts).
        """
        if not text or self.learn_mode not in ("auto", "ask"):
            return None
        if self.learn_mode == "auto":
            self.dictionary.learn(text)
            return None
        ready = self.gate is None or self.gate.allow()
        found = self.dictionary.learn(text, add=False, report=ready)
        if not (ready and found):
            return None
        if self.gate:
            self.gate.shown()
        return found[0]
