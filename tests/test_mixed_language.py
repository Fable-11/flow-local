from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from flow.arabicphrases import arabic_phrases


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("Assalamu alaikum, how are you?", "السلام عليكم, how are you?"),
        ("Assalamu Alaikum", "السلام عليكم"),
        ("assalam alaykum my friend", "السلام عليكم my friend"),
        ("As-salamu alaykum wa rahmatullahi wa barakatuh", "السلام عليكم ورحمة الله وبركاته"),
        ("Wa alaikum assalam", "وعليكم السلام"),
        ("see you tomorrow inshallah", "see you tomorrow إن شاء الله"),
        ("Alhamdulillah it went well", "الحمد لله it went well"),
        ("Mashallah, nice work", "ما شاء الله, nice work"),
        ("Jazakallah khair", "جزاك الله خيرا"),
    ],
)
def test_latin_arabic_phrases_become_arabic(heard, expected):
    assert arabic_phrases(heard) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Hello there, how are you?",
        "The salami sandwich is good",
        "السلام عليكم",
        "I will call Salam",
    ],
)
def test_other_text_is_untouched(text):
    assert arabic_phrases(text) == text


# -- per-chunk language in the engine -----------------------------------------------------------
faster_whisper = pytest.importorskip("faster_whisper")

from flow.stt import engine as engine_mod  # noqa: E402
from flow.stt.engine import ModelChoice, SttEngine, merge_short_chunks  # noqa: E402

SR = 16_000


def test_short_speech_spans_are_merged_into_classifiable_chunks():
    stamps = [{"start": 0, "end": SR * 2}, {"start": SR * 3, "end": SR * 3 + 4000}]
    # a trailing blip joins the part before it
    assert merge_short_chunks(stamps, SR) == [(0, SR * 3 + 4000)]
    stamps = [{"start": 0, "end": 3000}, {"start": SR, "end": SR * 3}]
    assert merge_short_chunks(stamps, SR) == [(0, SR * 3)]  # leading blip joins the next part
    two = [{"start": 0, "end": SR * 2}, {"start": SR * 3, "end": SR * 5}]
    assert merge_short_chunks(two, SR) == [(0, SR * 2), (SR * 3, SR * 5)]


class MixedModel:
    """English for the first chunk, Arabic for the second; records what each call was given."""

    def __init__(self):
        self.calls: list[tuple[str | None, int]] = []

    def detect_language(self, audio, **kwargs):
        lang = "ar" if float(audio[0]) > 0.5 else "en"
        return lang, 0.95, [(lang, 0.95)]

    def transcribe(self, audio, **kwargs):
        lang = kwargs.get("language")
        self.calls.append((lang, len(audio)))
        text = {"en": "Hello my friend", "ar": "السلام عليكم"}.get(lang, "?")
        return iter([SimpleNamespace(text=f" {text} ")]), SimpleNamespace(
            language=lang or "en", language_probability=0.9, all_language_probs=[("en", 0.9)]
        )


def _engine(model):
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    eng._model = model
    return eng


def _audio():
    english = np.full(SR * 2, 0.1, np.float32)
    arabic = np.full(SR * 2, 0.9, np.float32)
    return np.concatenate([english, np.zeros(SR // 2, np.float32), arabic]), [
        (0, SR * 2),
        (int(SR * 2.5), SR * 4 + SR // 2),
    ]


def test_mixed_dictation_is_written_part_by_part_in_each_language(monkeypatch):
    audio, chunks = _audio()
    monkeypatch.setattr(engine_mod, "split_by_pauses", lambda a: chunks)
    model = MixedModel()
    text, lang, _p = _engine(model).transcribe(audio)
    assert text == "Hello my friend السلام عليكم"
    assert [c[0] for c in model.calls] == ["en", "ar"]  # each part decoded in its own language
    assert lang in ("en", "ar")


def test_single_language_dictation_uses_one_pass(monkeypatch):
    audio, chunks = _audio()
    monkeypatch.setattr(engine_mod, "split_by_pauses", lambda a: chunks)
    model = MixedModel()
    model.detect_language = lambda a, **k: ("en", 0.95, [("en", 0.95)])
    _engine(model).transcribe(audio)
    assert len(model.calls) == 1  # whole recording at once, with its full context


def test_a_failure_in_the_mixed_step_falls_back_to_the_normal_pass(monkeypatch):
    audio, _ = _audio()

    def boom(a):
        raise RuntimeError("vad failed")

    monkeypatch.setattr(engine_mod, "split_by_pauses", boom)
    model = MixedModel()
    text, _lang, _p = _engine(model).transcribe(audio)
    assert text and len(model.calls) == 1


def test_short_audio_is_never_split(monkeypatch):
    audio, chunks = _audio()
    monkeypatch.setattr(engine_mod, "split_by_pauses", lambda a: chunks)
    model = MixedModel()
    _engine(model).transcribe(audio[: SR * 2])  # under 3 s
    assert len(model.calls) == 1
