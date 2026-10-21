"""English and Arabic in one dictation: the language is chosen from the audio, chunk by chunk.

A fixed language (the setting, or one guess for the whole recording) makes the model invent text
when the speech is in the other language: forced Arabic turns "use skill superpowers" into
"subscribe to the channel", forced English turns Arabic into Latin gibberish. The audio itself
says which language it is, so that is used, and the setting only breaks ties.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("faster_whisper")

from flow.stt import engine as engine_mod  # noqa: E402
from flow.stt.engine import ModelChoice, SttEngine  # noqa: E402

SR = 16_000
EN, AR = 0.1, 0.9  # a chunk of audio is a constant: 0.1 is English speech, 0.9 is Arabic speech
TEXT = {"en": "use skill superpowers", "ar": "السلام عليكم كيف حالك"}
# what the model makes up when it is forced into the wrong language
INVENTED = {"en": "subscribe to the channel", "ar": "اشتركوا في القناة"}


class FakeModel:
    def __init__(self, shares: dict[float, float] | None = None):
        self.shares = shares or {}  # English share of the language-ID probability per chunk kind
        self.decoded: list[tuple[float, str | None]] = []
        self.detections = 0

    def _truth(self, audio) -> str:
        return "en" if float(audio[0]) < 0.5 else "ar"

    def detect_language(self, audio, **kwargs):
        self.detections += 1
        kind = round(float(audio[0]), 1)
        share = self.shares.get(kind, 0.99 if self._truth(audio) == "en" else 0.01)
        top = "en" if share >= 0.5 else "ar"
        return top, max(share, 1 - share), [("en", share), ("ar", 1 - share)]

    def transcribe(self, audio, **kwargs):
        lang = kwargs.get("language")
        self.decoded.append((round(float(audio[0]), 1), lang))
        right = lang == self._truth(audio)
        text = TEXT[lang] if right else INVENTED[lang]
        seg = SimpleNamespace(text=f" {text} ", avg_logprob=-0.2 if right else -0.9,
                              no_speech_prob=0.01, compression_ratio=1.1)
        return iter([seg]), SimpleNamespace(
            language=lang, language_probability=1.0, all_language_probs=None
        )


def speech(*kinds: float, seconds: float = 2.0):
    """Audio made of chunks (kind per chunk) separated by short silences, plus the chunk ranges."""
    parts, chunks, pos = [], [], 0
    for kind in kinds:
        n = int(seconds * SR)
        parts += [np.full(n, kind, np.float32), np.zeros(SR // 2, np.float32)]
        chunks.append((pos, pos + n))
        pos += n + SR // 2
    return np.concatenate(parts), chunks


def engine(model, monkeypatch, chunks):
    eng = SttEngine(ModelChoice("small", "cpu", "int8"))
    eng._model = model
    monkeypatch.setattr(engine_mod, "split_by_pauses", lambda audio: chunks)
    return eng


@pytest.mark.parametrize("preferred", [None, "ar", "en"])
def test_english_speech_is_english_whatever_the_setting(monkeypatch, preferred):
    audio, chunks = speech(EN)
    text, lang, _p = engine(FakeModel(), monkeypatch, chunks).transcribe(audio, language=preferred)
    assert text == TEXT["en"] and lang == "en"  # never "subscribe to the channel"


@pytest.mark.parametrize("preferred", [None, "ar", "en"])
def test_arabic_speech_is_arabic_whatever_the_setting(monkeypatch, preferred):
    audio, chunks = speech(AR)
    text, lang, _p = engine(FakeModel(), monkeypatch, chunks).transcribe(audio, language=preferred)
    assert text == TEXT["ar"] and lang == "ar"


def test_each_part_of_a_mixed_dictation_gets_its_own_language(monkeypatch):
    audio, chunks = speech(EN, AR, EN)
    model = FakeModel()
    text, lang, _p = engine(model, monkeypatch, chunks).transcribe(audio, language="ar")
    assert text == f"{TEXT['en']} {TEXT['ar']} {TEXT['en']}"
    assert lang == "en"  # the language of most of the speech
    assert [lang for _k, lang in model.decoded] == ["en", "ar", "en"]  # one decode per part


def test_one_language_throughout_is_decoded_in_one_go_to_keep_its_context(monkeypatch):
    audio, chunks = speech(EN, EN)
    model = FakeModel()
    text, lang, _p = engine(model, monkeypatch, chunks).transcribe(audio)
    assert text == TEXT["en"] and lang == "en"
    assert len(model.decoded) == 1  # two parts, one language: a single pass over the recording


def test_when_detection_is_unsure_both_languages_are_tried_and_the_better_one_wins(monkeypatch):
    audio, chunks = speech(EN)
    model = FakeModel(shares={EN: 0.55})  # accented English: detection cannot decide
    text, lang, _p = engine(model, monkeypatch, chunks).transcribe(audio, language="ar")
    assert text == TEXT["en"] and lang == "en"
    assert {lang for _k, lang in model.decoded} == {"en", "ar"}


def test_the_setting_wins_a_close_call_but_not_a_clear_one(monkeypatch):
    audio, chunks = speech(AR)
    # detection leans English a little (0.7) but the speech really is Arabic: preferred "ar" holds
    model = FakeModel(shares={AR: 0.7})
    text, _l, _p = engine(model, monkeypatch, chunks).transcribe(audio, language="ar")
    assert text == TEXT["ar"]
    # detection is certain it is English: the Arabic setting no longer forces Arabic
    audio, chunks = speech(EN)
    text, _l, _p = engine(FakeModel(), monkeypatch, chunks).transcribe(audio, language="ar")
    assert text == TEXT["en"]


def test_a_failing_language_check_falls_back_to_the_setting(monkeypatch):
    audio, chunks = speech(EN)
    model = FakeModel()

    def boom(*a, **k):
        raise RuntimeError("detection failed")

    model.detect_language = boom
    text, lang, _p = engine(model, monkeypatch, chunks).transcribe(audio, language="en")
    assert text == TEXT["en"] and lang == "en"  # the dictation is never lost


def test_known_invented_phrases_are_dropped_when_nothing_better_exists(monkeypatch):
    audio, chunks = speech(EN)
    model = FakeModel(shares={EN: 0.01})  # detection is wrong and certain, the decode is invented
    model.transcribe_original = model.transcribe

    def only_arabic_decode(audio, **kw):
        seg = SimpleNamespace(text=" اشتركوا في القناة ", avg_logprob=-0.4,
                              no_speech_prob=0.01, compression_ratio=1.1)
        return iter([seg]), SimpleNamespace(language="ar", language_probability=1.0,
                                            all_language_probs=None)

    model.transcribe = only_arabic_decode
    text, _l, _p = engine(model, monkeypatch, chunks).transcribe(audio)
    assert text == ""  # a made-up "subscribe to the channel" is worse than nothing
