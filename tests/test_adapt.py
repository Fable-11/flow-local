"""Defaults for different computers. A typical 8 GB desktop card keeps its setup."""

from __future__ import annotations

import pytest

from flow.cleanup.llm import DEFAULT_MODEL, FALLBACK_MODEL, OllamaClient, local_host
from flow.hardware import Hardware, recommend
from flow.stt import engine as engine_mod


# -- the Ollama port: only the port can change, never the address --------------------------------
@pytest.mark.parametrize(
    ("port", "expected"),
    [
        (11434, "http://127.0.0.1:11434"),
        (11500, "http://127.0.0.1:11500"),
        (80, "http://127.0.0.1:11434"),  # reserved port: back to the default
        (70000, "http://127.0.0.1:11434"),
        (None, "http://127.0.0.1:11434"),
        (True, "http://127.0.0.1:11434"),  # a boolean is not a port
        ("11500", "http://127.0.0.1:11434"),
    ],
)
def test_local_host_only_ever_gives_a_local_address(port, expected):
    assert local_host(port) == expected


def test_a_remote_ollama_address_is_still_refused():
    with pytest.raises(ValueError):
        OllamaClient(host="http://example.com:11434")
    assert OllamaClient(host=local_host(11500)).host == "http://127.0.0.1:11500"


# -- speech model by graphics memory ---------------------------------------------------------
@pytest.fixture
def cuda(monkeypatch):
    monkeypatch.setattr(engine_mod, "cuda_available", lambda: True)

    def set_vram(mb):
        monkeypatch.setattr(engine_mod, "gpu_memory_mb", lambda: mb)

    return set_vram


@pytest.mark.parametrize(
    ("vram", "name", "compute"),
    [
        (8192, "large-v3-turbo", "int8_float16"),  # a common 8 GB card: unchanged
        (12288, "large-v3-turbo", "float16"),
        (6144, "large-v3-turbo", "int8_float16"),
        (3072, "small", "int8_float16"),  # a confirmed tiny card gets the smaller model
        (None, "large-v3-turbo", "float16"),  # an unreadable card changes nothing
    ],
)
def test_speech_model_follows_a_confirmed_card_only(cuda, vram, name, compute):
    cuda(vram)
    choice = engine_mod.choose_model()
    assert (choice.name, choice.compute_type) == (name, compute)


def test_an_explicit_model_choice_is_never_overridden(cuda):
    cuda(3072)
    assert engine_mod.choose_model("medium").name == "medium"


# -- first-run cleanup model -------------------------------------------------------------
@pytest.mark.parametrize(
    ("hw", "model"),
    [
        (Hardware(True, 16.0, 8192), DEFAULT_MODEL),  # a typical gaming PC: still the 7B model
        (Hardware(True, 32.0, 24576), DEFAULT_MODEL),
        (Hardware(True, 16.0, 0), DEFAULT_MODEL),  # card size unknown: no guessing
        (Hardware(True, 16.0, 4096), FALLBACK_MODEL),  # 7B + speech model would not fit
        (Hardware(False, 16.0, 0), FALLBACK_MODEL),
        (Hardware(True, 8.0, 8192), FALLBACK_MODEL),  # little memory
    ],
)
def test_recommended_cleanup_model(hw, model):
    assert recommend(hw).llm_model == model


def test_the_lighter_model_comes_with_a_licence_note():
    notes = " ".join(recommend(Hardware(False, 16.0, 0)).notes)
    assert "non-commercial" in notes
    assert "non-commercial" not in " ".join(recommend(Hardware(True, 16.0, 8192)).notes)
