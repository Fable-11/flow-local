"""A dictation never waits for an AI model that is not loaded yet."""

from __future__ import annotations

import time

import pytest

from fake_ollama import FakeServer
from flow.cleanup.llm import LlmError, OllamaClient
from flow.cleanup.pipeline import CleanupPipeline
from flow.cleanup.prompts import PromptContext

TEXT = "so I was thinking we could meet on tuesday to go over the report together"
CLEAN = "So I was thinking we could meet on Tuesday to go over the report together."


@pytest.fixture
def server():
    s = FakeServer(reply=CLEAN)
    yield s
    s.close()


def pipeline(server):
    return CleanupPipeline(OllamaClient(host=server.url), use_llm=True)


def test_a_loaded_model_is_used(server):
    result = pipeline(server).clean(TEXT, PromptContext())
    assert result.used_llm and result.note == ""


def test_a_cold_model_is_skipped_at_once_and_warmed_in_the_background(server):
    server.loaded = []  # Ollama is up, but the model is not in memory
    server.delay = 3.0  # loading would take this long
    start = time.perf_counter()
    result = pipeline(server).clean(TEXT, PromptContext())
    assert time.perf_counter() - start < 1.0  # no waiting for the load
    assert not result.used_llm and result.note == "llm cold"
    assert result.text.startswith("So I was thinking")  # the rules still clean it
    deadline = time.time() + 6
    while server.last_payload is None and time.time() < deadline:
        time.sleep(0.05)
    assert server.last_payload is not None  # the model was asked to load meanwhile


def test_warming_never_runs_twice_at_once(server):
    server.loaded = []
    server.delay = 1.0
    client = OllamaClient(host=server.url)
    client.warm_in_background()
    client.warm_in_background()
    assert client._warming
    deadline = time.time() + 6
    while client._warming and time.time() < deadline:
        time.sleep(0.05)
    assert not client._warming


def test_an_ollama_that_cannot_say_what_is_loaded_is_assumed_ready(server, monkeypatch):
    """Older Ollama versions have no /api/ps: keep the old behaviour instead of skipping the AI."""
    client = OllamaClient(host=server.url)
    real = client._request

    def request(path, payload, timeout):
        if path == "/api/ps":
            raise LlmError("not found")
        return real(path, payload, timeout)

    monkeypatch.setattr(client, "_request", request)
    assert client.is_loaded() is True
