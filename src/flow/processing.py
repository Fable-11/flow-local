"""Turns a raw transcript into final text: snippets, dictionary, cleanup."""

from __future__ import annotations

from dataclasses import dataclass

from flow.cleanup.appstyles import resolve_style
from flow.cleanup.pipeline import CleanResult, CleanupPipeline
from flow.cleanup.prompts import PromptContext
from flow.store.dictionary import DictionaryStore
from flow.store.snippets import SnippetStore
from flow.stt.engine import build_initial_prompt


@dataclass
class ProcessResult:
    text: str
    kind: str  # "snippet" | "text" | "empty"
    clean: CleanResult | None = None
    press_enter: bool = False


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

    def whisper_prompt(self) -> str | None:
        """Dictionary words as Whisper ``initial_prompt`` (starred words first)."""
        return build_initial_prompt(self.dictionary.words_for_prompt())

    def process(self, raw: str, app_process: str = "", app_title: str = "") -> ProcessResult:
        snippet = self.snippets.match_exact(raw)
        if snippet:  # inserted verbatim: no cleanup, no replacements
            return ProcessResult(snippet.content, "snippet")
        text, hits = self.dictionary.apply_replacements(raw)
        if not self.cleanup_enabled:  # insert the transcript as Whisper wrote it
            text, _ = self.snippets.expand_embedded(text.strip())
            self.dictionary.record_use(hits)
            return ProcessResult(text, "text" if text else "empty")
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
        out, _ = self.snippets.expand_embedded(out)
        self.dictionary.record_use(hits + hits2)
        press = cleaned.press_enter
        if press:
            out = out.rstrip("\n")
        return ProcessResult(out, "text", cleaned, press)
