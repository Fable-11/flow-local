import queue
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from flow.audio import enhance
from flow.audio.capture import SAMPLE_RATE

RNG = np.random.default_rng(7)


def speechlike(seconds=2.0, peak=0.5, lead=0.5, tail=0.3, noise_rms=0.0010):
    """Bursts of amplitude-modulated tones (voice-like energy) between quiet room noise."""
    n_speech = int(seconds * SAMPLE_RATE)
    t = np.arange(n_speech) / SAMPLE_RATE
    voice = sum(np.sin(2 * np.pi * f * t) for f in (180, 360, 540, 900, 1800))
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 3.5 * t)) ** 0.7  # syllable rhythm
    voice = voice * envelope
    voice = voice / np.abs(voice).max() * peak
    total = int((lead + seconds + tail) * SAMPLE_RATE)
    audio = noise_rms * RNG.standard_normal(total)
    start = int(lead * SAMPLE_RATE)
    audio[start : start + n_speech] += voice
    return audio.astype(np.float32)


# -- analysis -----------------------------------------------------------------------------------------
def test_stats_separate_speech_from_noise():
    st = enhance.analyze(speechlike(peak=0.4, noise_rms=0.001))
    assert st.speech_rms > 20 * st.noise_rms
    assert 20 < st.snr_db < 60
    assert 0.3 < st.peak <= 0.45


def test_stats_of_empty_and_silent_audio():
    assert enhance.analyze(np.zeros(0, np.float32)).too_quiet
    assert enhance.analyze(np.zeros(16000, np.float32)).too_quiet
    muted = (0.0001 * RNG.standard_normal(32000)).astype(np.float32)
    assert enhance.analyze(muted).too_quiet  # a muted or disconnected microphone


def test_pure_noise_is_not_mistaken_for_speech():
    noise = (0.01 * RNG.standard_normal(SAMPLE_RATE * 3)).astype(np.float32)  # loud room, no talking
    st = enhance.analyze(noise)
    assert st.snr_db < enhance.MIN_SNR_DB + 1 and st.too_quiet
    assert enhance.prepare(noise).silent  # must not be boosted into a hallucination


# -- the reported problem: speaking far from the microphone ---------------------------------------------------
def out_peak(prepared) -> float:
    return float(np.percentile(np.abs(prepared.audio), 99.8))


@pytest.mark.parametrize("peak", [0.02, 0.008, 0.004])  # about -34, -42 and -48 dBFS
def test_far_field_speech_is_not_discarded_and_is_boosted(peak):
    audio = speechlike(peak=peak, noise_rms=0.0001)
    p = enhance.prepare(audio)
    assert not p.silent
    assert 0.35 < out_peak(p) < 0.75  # brought to a normal level
    assert p.gain_db > 10 and p.audio.dtype == np.float32
    assert np.abs(p.audio).max() <= 1.0 and np.isfinite(p.audio).all()


def test_the_old_fixed_cutoff_would_have_discarded_this_recording():
    audio = speechlike(peak=0.006, noise_rms=0.0001)
    assert float(np.sqrt(np.mean(audio**2))) < 0.003  # the previous is_silent() rule
    assert not enhance.prepare(audio).silent


def test_boost_is_capped_so_noise_is_not_blown_up():
    audio = speechlike(peak=0.001, noise_rms=0.00003)
    p = enhance.prepare(audio)
    assert p.gain_db <= enhance.MAX_GAIN_DB + 0.01


def test_normal_and_loud_speech_are_left_alone():
    for peak in (0.3, 0.4, 0.9):
        audio = speechlike(peak=peak, noise_rms=0.001)
        p = enhance.prepare(audio)
        assert p.gain_db == 0.0 and not p.denoised
        core = slice(int(0.6 * SAMPLE_RATE), int(2.4 * SAMPLE_RATE))
        corr = np.corrcoef(audio[core], p.audio[core])[0, 1]
        assert corr > 0.99  # only the sub-70 Hz rumble filter touched it


def test_auto_gain_can_be_switched_off():
    audio = speechlike(peak=0.01, noise_rms=0.0001)
    p = enhance.prepare(audio, auto=False)
    assert p.gain_db == 0.0 and np.array_equal(p.audio, audio) and not p.silent


def test_noise_reduction_improves_signal_to_noise():
    audio = speechlike(peak=0.05, noise_rms=0.004)  # noisy room, moderate speech
    before = enhance.analyze(audio).snr_db
    after = enhance.analyze(enhance.reduce_noise(audio)).snr_db
    assert after > before + 3


def test_noise_reduction_keeps_length_and_is_safe_on_tiny_input():
    audio = speechlike(seconds=1.0)
    assert len(enhance.reduce_noise(audio)) == len(audio)
    tiny = np.ones(100, np.float32)
    assert enhance.reduce_noise(tiny) is tiny  # too short to analyse: untouched


def test_highpass_removes_dc_and_rumble_but_keeps_speech_band():
    t = np.arange(SAMPLE_RATE * 2) / SAMPLE_RATE
    rumble = 0.3 * np.sin(2 * np.pi * 25 * t) + 0.2  # 25 Hz thump plus DC offset
    voice = 0.1 * np.sin(2 * np.pi * 500 * t)
    out = enhance.highpass((rumble + voice).astype(np.float32))
    core = out[4000:-4000]
    assert abs(float(np.mean(core))) < 0.005  # DC gone
    assert float(np.std(core - voice[4000:-4000])) < 0.05  # rumble gone, 500 Hz tone intact


def test_prepare_is_fast_enough_for_live_use():
    import time

    audio = speechlike(seconds=30, peak=0.01, noise_rms=0.0002)
    t0 = time.perf_counter()
    enhance.prepare(audio)
    assert time.perf_counter() - t0 < 1.0  # 30 s of audio, well under the latency budget


# -- messages -----------------------------------------------------------------------------------------------
def test_hints_tell_the_user_what_to_do():
    muted = enhance.analyze(np.zeros(16000, np.float32))
    assert "muted" in enhance.quiet_hint(muted)
    quiet_noise = enhance.analyze((0.003 * RNG.standard_normal(32000)).astype(np.float32))
    assert "closer" in enhance.quiet_hint(quiet_noise)
    loud_noise = enhance.analyze((0.05 * RNG.standard_normal(32000)).astype(np.float32))
    assert enhance.quiet_hint(loud_noise) == "No speech heard"
    good = enhance.analyze(speechlike(peak=0.4))
    assert enhance.describe(good) == "Good level."
    assert "boost" in enhance.describe(enhance.analyze(speechlike(peak=0.05)))
    assert "No signal" in enhance.describe(muted)


# -- worker integration: the engine receives the boosted audio ---------------------------------------------------
def _worker(monkeypatch, auto_gain=True):
    pytest.importorskip("PySide6")
    import flow.app as app_mod
    from flow.config import Settings

    states = []
    bridge = SimpleNamespace(
        state=SimpleNamespace(emit=lambda s, t="": states.append((s, t))),
        level=SimpleNamespace(emit=lambda v: None),
        historyChanged=SimpleNamespace(emit=lambda: None),
    )
    w = app_mod.Worker(bridge, queue.Queue(), lambda: Settings(auto_gain=auto_gain), None, None, None)
    heard = {}

    class Engine:
        loaded = True

        def transcribe(self, audio, **kw):
            heard["peak"] = float(np.abs(audio).max())
            return "hello there my friend", "en", 0.99

    w.engine = Engine()
    w.processor = SimpleNamespace(
        whisper_prompt=lambda: None,
        process=lambda text, *a: SimpleNamespace(text=text, kind="text", press_enter=False),
    )
    w.spacing = SimpleNamespace(prefix_for=lambda *a: "", record=lambda *a: None)
    w.history = SimpleNamespace(add=lambda *a: None)
    monkeypatch.setattr(app_mod, "paste_text", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "get_active_app", lambda: SimpleNamespace(hwnd=1, process="x.exe", title=""))
    return w, states, heard


def test_worker_boosts_quiet_audio_before_transcribing(monkeypatch):
    w, states, heard = _worker(monkeypatch)
    w._finish(speechlike(peak=0.01, noise_rms=0.0001))
    assert 0.35 < heard["peak"] < 0.75
    assert states[-1][0] == "done"


def test_worker_respects_the_setting(monkeypatch):
    w, states, heard = _worker(monkeypatch, auto_gain=False)
    w._finish(speechlike(peak=0.01, noise_rms=0.0001))
    assert heard["peak"] < 0.05  # untouched


def test_worker_gives_a_useful_message_for_a_muted_mic_and_for_noise_only(monkeypatch):
    w, states, heard = _worker(monkeypatch)
    w._finish(np.zeros(32000, np.float32))
    assert states[-1] == ("error", "Microphone silent: is it muted?") and not heard
    w._finish((0.03 * RNG.standard_normal(48000)).astype(np.float32))
    assert states[-1] == ("error", "No speech heard") and not heard


# -- end to end with a real voice and the real model (needs Windows speech + the model) -------------------------
@pytest.mark.slow
def test_real_voice_at_a_distance_is_transcribed(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows only")
    from flow.audio.capture import load_wav
    from flow.stt.engine import SttEngine, choose_model
    from flow.stt.models import is_model_cached

    choice = choose_model()
    if not is_model_cached(choice.name):
        pytest.skip("speech model not downloaded")
    wav = tmp_path / "voice.wav"
    script = Path(__file__).parent / "fixtures" / "speak.ps1"
    done = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Text", "Hello. Can you hear me from over here?", "-Out", str(wav)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    if done.returncode != 0 or not wav.exists():
        pytest.skip("Windows speech synthesis not available")
    voice = load_wav(str(wav))
    voice = voice / np.abs(voice).max() * 0.5
    audio = (0.0012 * RNG.standard_normal(len(voice) + 32000)).astype(np.float32)
    audio[16000 : 16000 + len(voice)] += voice * 10 ** (-36 / 20)  # a far-away talker
    old_would_reject = float(np.sqrt(np.mean(audio**2))) < 0.003
    assert old_would_reject  # the previous fixed cut-off discarded this recording
    prepared = enhance.prepare(audio)
    assert not prepared.silent
    engine = SttEngine(choice)
    engine.load()
    text = engine.transcribe(prepared.audio)[0].lower()
    assert "hear me" in text
