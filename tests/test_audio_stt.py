import wave

import numpy as np
import pytest

from flow.audio.capture import SAMPLE_RATE, load_wav
from flow.audio.vad import is_silent
from flow.stt.engine import build_initial_prompt


def _write_wav(path, data, rate=SAMPLE_RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((data * 32767).astype(np.int16).tobytes())


def test_load_wav_resamples(tmp_path):
    t = np.linspace(0, 1, 8000, endpoint=False)
    _write_wav(tmp_path / "a.wav", 0.5 * np.sin(2 * np.pi * 440 * t), rate=8000)
    out = load_wav(str(tmp_path / "a.wav"))
    assert out.dtype == np.float32
    assert abs(len(out) - SAMPLE_RATE) <= 1


def test_is_silent():
    assert is_silent(np.zeros(1000, np.float32))
    assert is_silent(np.zeros(0, np.float32))
    assert not is_silent(0.3 * np.ones(1000, np.float32))


def test_initial_prompt_limit_and_order():
    assert build_initial_prompt([]) is None
    assert build_initial_prompt(["Pygame", "Kubernetes", "NASA"]) == "Pygame, Kubernetes, NASA"
    assert len(build_initial_prompt(["x" * 100] * 20, limit_chars=250)) <= 250


def test_trim_silence_on_silence():
    pytest.importorskip("faster_whisper")
    from flow.audio.vad import trim_silence

    assert trim_silence(np.zeros(SAMPLE_RATE * 2, np.float32)).size == 0
