from types import SimpleNamespace

import numpy as np
import pytest

faster_whisper = pytest.importorskip("faster_whisper")

from flow.stt import engine as engine_mod  # noqa: E402
from flow.stt.engine import ModelChoice, ModelNotDownloaded, SttEngine  # noqa: E402


class FakeModel:
    """Stands in for WhisperModel and records how it was opened."""

    opened: list[dict] = []
    fail_cuda = False
    cached = True

    def __init__(self, name, **kwargs):
        FakeModel.opened.append({"name": name, **kwargs})
        if FakeModel.fail_cuda and kwargs.get("device") == "cuda":
            raise RuntimeError("CUDA out of memory")

    detected = "en"
    probs = [("en", 0.99)]
    calls: list = []

    def transcribe(self, audio, **kwargs):
        FakeModel.calls.append(kwargs.get("language"))
        lang = kwargs.get("language") or FakeModel.detected
        return iter([SimpleNamespace(text=" hello ")]), SimpleNamespace(
            language=lang, language_probability=0.99, all_language_probs=FakeModel.probs
        )


@pytest.fixture(autouse=True)
def fake_whisper(monkeypatch):
    FakeModel.opened, FakeModel.fail_cuda, FakeModel.cached = [], False, True
    FakeModel.detected, FakeModel.probs, FakeModel.calls = "en", [("en", 0.99)], []
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    monkeypatch.setattr(engine_mod, "add_cuda_dll_dirs", lambda: None)
    monkeypatch.setattr(engine_mod, "is_model_cached", lambda name, cache=None: FakeModel.cached)


def test_cached_model_loads_offline():
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    eng.load()
    assert eng.loaded
    assert [o.get("local_files_only") for o in FakeModel.opened] == [True]  # no download attempt


def test_missing_model_is_not_downloaded_silently():
    FakeModel.cached = False
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    with pytest.raises(ModelNotDownloaded) as exc:
        eng.load()
    assert exc.value.model_name == "small" and not eng.loaded
    assert FakeModel.opened == []  # never constructed a model, so never went online


def test_explicit_download_allowed():
    FakeModel.cached = False
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    eng.load(allow_download=True)
    assert eng.loaded
    assert len(FakeModel.opened) == 1 and "local_files_only" not in FakeModel.opened[0]


def test_cuda_failure_falls_back_to_cpu_small():
    FakeModel.fail_cuda = True
    eng = SttEngine(ModelChoice("large-v3-turbo", "cuda", "float16"))
    eng.load()
    assert eng.loaded and eng.choice == ModelChoice("small", "cpu", "int8")


def test_transcribe_returns_text_and_requires_load():
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    with pytest.raises(RuntimeError, match="not loaded"):
        eng.transcribe(np.zeros(16000, np.float32))
    eng.load()
    assert eng.transcribe(np.zeros(16000, np.float32)) == ("hello", "en", 0.99)


def test_real_load_failures_are_not_reported_as_missing_model():
    FakeModel.fail_cuda = True
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))

    class Boom(FakeModel):
        def __init__(self, name, **kwargs):
            raise RuntimeError("corrupt weights")

    import faster_whisper as fw

    fw.WhisperModel = Boom
    with pytest.raises(RuntimeError, match="corrupt weights"):
        eng.load()


def test_unsupported_detected_language_is_redone_in_english_or_arabic():
    """'Hello' was once detected as Russian; the app only supports Arabic and English."""
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    eng.load()
    FakeModel.calls.clear()
    FakeModel.detected = "ru"
    FakeModel.probs = [("ru", 0.45), ("en", 0.30), ("ar", 0.05)]
    text, lang, _ = eng.transcribe(np.zeros(16000, np.float32))
    assert FakeModel.calls == [None, "en"]  # auto first, then forced to the better of en/ar
    assert (text, lang) == ("hello", "en")
    FakeModel.calls.clear()
    FakeModel.detected = "fa"  # Persian is often what Arabic gets mistaken for
    FakeModel.probs = [("fa", 0.5), ("en", 0.05), ("ar", 0.3)]
    assert eng.transcribe(np.zeros(16000, np.float32))[1] == "ar"


def test_supported_or_forced_languages_are_not_redone():
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    eng.load()
    FakeModel.calls.clear()
    FakeModel.detected = "ar"
    eng.transcribe(np.zeros(16000, np.float32))
    assert FakeModel.calls == [None]  # one pass: no extra cost in the normal case
    FakeModel.calls.clear()
    eng.transcribe(np.zeros(16000, np.float32), language="en")
    assert FakeModel.calls == ["en"]  # the user's own language setting is always respected


def test_pick_allowed_language_helper():
    from flow.stt.engine import pick_allowed_language

    assert pick_allowed_language("en", [("en", 1.0)]) is None
    assert pick_allowed_language("ru", None) is None
    assert pick_allowed_language("de", [("de", 0.5), ("ar", 0.2), ("en", 0.1)]) == "ar"
