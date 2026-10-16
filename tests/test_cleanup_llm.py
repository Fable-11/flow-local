import difflib
import json
from pathlib import Path

import pytest

from fake_ollama import FakeServer
from flow.cleanup.llm import LlmError, OllamaClient
from flow.cleanup.pipeline import CleanupPipeline, validate_llm_output
from flow.cleanup.prompts import PromptContext, app_hint, cleanup_messages, system_prompt
from flow.cleanup.rules import NL


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


def test_client_rejects_non_local_host():
    with pytest.raises(ValueError):
        OllamaClient(host="http://example.com:11434")


def test_client_available_and_chat(server):
    c = OllamaClient(host=server.url)
    assert c.available()
    assert c.chat([{"role": "user", "content": "hi"}]) == "Hello world."
    assert server.last_payload["options"]["temperature"] == 0
    assert server.last_payload["keep_alive"] == "30m"


def test_client_falls_back_to_small_model():
    s = FakeServer(models=("qwen2.5:3b",))
    try:
        c = OllamaClient(host=s.url)
        c.chat([{"role": "user", "content": "hi"}])
        assert s.last_payload["model"] == "qwen2.5:3b"
    finally:
        s.close()


def test_client_down_is_graceful():
    c = OllamaClient(host="http://127.0.0.1:1")
    assert not c.available()
    with pytest.raises(LlmError):
        c.chat([{"role": "user", "content": "hi"}])


def test_pipeline_uses_llm_output(server):
    server.reply = "I want to ask about the budget."
    p = CleanupPipeline(OllamaClient(host=server.url))
    r = p.clean("um I want to I want to ask about the budget")
    assert r.used_llm
    assert r.text == "I want to ask about the budget."


def test_pipeline_rejects_answers(server):
    server.reply = "The capital of France is Paris, a city known for the Eiffel Tower."
    p = CleanupPipeline(OllamaClient(host=server.url))
    r = p.clean("what is the capital of france please tell me")
    assert not r.used_llm
    assert "rejected" in r.note
    assert r.text == "What is the capital of france please tell me."


def test_pipeline_rejects_translation(server):
    server.reply = "I am going to the market tomorrow morning."
    p = CleanupPipeline(OllamaClient(host=server.url))
    r = p.clean("انا رايح السوق بكرة الصبح ان شاء الله")
    assert not r.used_llm


def test_pipeline_timeout_falls_back_to_rules():
    s = FakeServer(delay=1.0)
    try:
        p = CleanupPipeline(OllamaClient(host=s.url, timeout_s=0.2))
        r = p.clean("um so we should meet tomorrow at noon")
        assert not r.used_llm
        assert r.text == "So we should meet tomorrow at noon."
    finally:
        s.close()


def test_pipeline_llm_down_and_off():
    down = CleanupPipeline(OllamaClient(host="http://127.0.0.1:1"))
    assert down.clean("um so we should meet tomorrow").text == "So we should meet tomorrow."
    off = CleanupPipeline(None, use_llm=False)
    assert off.clean("uh hello there my friend").note == "llm off"


def test_pipeline_skips_llm_for_short_text(server):
    p = CleanupPipeline(OllamaClient(host=server.url))
    r = p.clean("hello there")
    assert not r.used_llm and server.last_payload is None


def test_pipeline_preserves_sentinels(server):
    p = CleanupPipeline(OllamaClient(host=server.url))
    server.reply = f"Dear John {NL} I hope you are well today."
    r = p.clean("dear John new line I hope you are well today")
    assert r.used_llm and r.text == "Dear John\nI hope you are well today."
    server.reply = "Dear John, I hope you are well today."  # dropped the marker
    r = p.clean("dear John new line I hope you are well today")
    assert not r.used_llm and r.text == "Dear John\nI hope you are well today."


def test_llm_output_that_drops_a_greeting_is_rejected():
    """Reported bug: 'Hello? Can you hear me?' came out as 'Can you hear me?'."""
    assert validate_llm_output("Hello? Can you hear me?", "Can you hear me?") == "dropped 'hello'"
    assert validate_llm_output("hello can you hear me", "Hello, can you hear me?") is None
    assert validate_llm_output("thanks so much see you", "See you.") == "dropped 'thanks'"
    assert validate_llm_output("مرحبا كيف حالك", "كيف حالك؟") is not None  # Arabic greeting too


def test_greeting_may_go_when_the_speaker_corrected_themselves():
    source = "hi no wait hello there my friend"
    assert validate_llm_output(source, "Hello there, my friend.") is None


def test_pipeline_falls_back_to_rules_when_the_model_drops_hello(server):
    server.reply = "Can you hear me?"
    p = CleanupPipeline(OllamaClient(host=server.url))
    r = p.clean("hello can you hear me right now")
    assert not r.used_llm and "dropped" in r.note
    assert r.text == "Hello can you hear me right now."  # nothing lost; rules only


def test_validate_llm_output_cases():
    assert validate_llm_output("hello there my friend", "Hello there, my friend.") is None
    assert validate_llm_output("hello there", "Sure! Here is the text: hello there") == "preamble"
    assert validate_llm_output("hello there", "") == "empty output"


def test_prompt_contains_glossary_style_and_context():
    ctx = PromptContext(
        style="formal",
        app_process="WhatsApp.exe",
        glossary=["Kubernetes", "NASA"],
        custom_instructions="Use British spelling.",
    )
    sp = system_prompt(ctx)
    for needle in ("Kubernetes", "formal", "chat app", "British spelling", "NEVER answer"):
        assert needle in sp
    msgs = cleanup_messages("hello", ctx)
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"] == "<transcript>hello</transcript>"


def test_app_hints():
    assert "email" in app_hint("OUTLOOK.EXE")
    assert "code editor" in app_hint("Code.exe")
    assert app_hint("notepad.exe") == ""


# -- real Ollama (run with: pytest -m llm) ---------------------------------------------------
LLM_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "cleanup" / "llm_cases.json").read_text("utf-8")
)


@pytest.fixture(scope="module")
def real_pipeline():
    client = OllamaClient()
    if not client.available() or client.resolve_model() is None:
        pytest.skip("Ollama not running or no model installed")
    client.warm_up()
    return CleanupPipeline(client)


@pytest.mark.llm
@pytest.mark.parametrize("case", LLM_CASES, ids=[c["id"] for c in LLM_CASES])
def test_real_llm_cleanup(real_pipeline, case):
    ctx = PromptContext(glossary=["faster-whisper", "Pygame"])
    result = real_pipeline.clean(case["input"], ctx)
    ratio = difflib.SequenceMatcher(None, result.text, case["expected"]).ratio()
    detail = f"{result.text!r} (llm={result.used_llm}, {result.note}) vs {case['expected']!r}"
    assert ratio >= 0.8, detail
