from flow.cleanup.appstyles import builtin_style, resolve_style
from flow.cleanup.pipeline import CleanupPipeline
from flow.processing import TextProcessor
from flow.store.db import Database
from flow.store.dictionary import DictionaryStore
from flow.store.snippets import SnippetStore


def test_builtin_styles():
    assert builtin_style("WhatsApp.exe") == "casual"
    assert builtin_style("OUTLOOK.EXE") == "formal"
    assert builtin_style("notepad.exe") is None


def test_resolution_order():
    overrides = {"outlook.exe": "casual"}
    assert resolve_style("OUTLOOK.EXE", "formal", overrides) == "casual"  # explicit rule wins
    assert resolve_style("whatsapp.exe", "formal", {}) == "formal"  # global choice beats default
    assert resolve_style("whatsapp.exe", "default", {}) == "casual"  # built-in app default
    assert resolve_style("notepad.exe", "default", {}) == "default"


def test_processor_uses_per_app_style_for_final_period():
    db = Database()
    p = TextProcessor(CleanupPipeline(None, use_llm=False), DictionaryStore(db), SnippetStore(db))
    assert p.process("we should meet tomorrow at noon", "notepad.exe").text.endswith(".")
    # casual (chat app default) drops the final period
    chat = p.process("we should meet tomorrow at noon", "WhatsApp.exe").text
    assert chat == "We should meet tomorrow at noon"
    p.app_styles = {"notepad.exe": "casual"}
    assert not p.process("we should meet tomorrow at noon", "notepad.exe").text.endswith(".")
