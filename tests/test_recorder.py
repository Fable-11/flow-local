import numpy as np

from flow.audio.capture import SAMPLE_RATE, Recorder


def feed(rec, n_blocks, value=0.1, block=800):
    for _ in range(n_blocks):
        rec._callback(np.full((block, 1), value, np.float32), block, None, None)


def test_preroll_is_bounded_and_prepended_on_start():
    rec = Recorder(preroll_s=0.5)
    feed(rec, 50)  # 2.5 s of idle audio
    assert rec._preroll_len <= int(0.5 * SAMPLE_RATE) + 800  # about half a second kept
    rec._recording = True  # what start() does, minus the real stream
    rec._chunks = list(rec._preroll)
    rec._preroll.clear()
    feed(rec, 5, value=0.5)
    audio = rec.snapshot()
    assert abs(len(audio) - (0.5 * SAMPLE_RATE + 5 * 800)) <= 800
    assert audio[-1] == np.float32(0.5) and audio[0] == np.float32(0.1)


def test_levels_reported_only_while_recording():
    levels = []
    rec = Recorder(on_level=levels.append)
    feed(rec, 10)
    assert levels == []  # idle: the UI must not be woken up
    rec._recording = True
    feed(rec, 3, value=0.2)
    assert len(levels) == 3 and abs(levels[0] - 0.2) < 1e-6


def test_gain_applied_and_clipped():
    rec = Recorder(gain=5.0)
    rec._recording = True
    feed(rec, 1, value=0.4)
    assert rec.snapshot().max() == 1.0  # 0.4 * 5 clipped to 1.0


def test_stop_without_start_returns_empty():
    assert Recorder().stop().size == 0


def test_speech_before_the_key_press_does_not_leak_in():
    from flow.audio.capture import select_preroll

    rng = np.random.default_rng(1)
    quiet = (0.002 * rng.standard_normal(4000)).astype(np.float32)
    voice = (0.2 * rng.standard_normal(4000)).astype(np.float32)
    said_earlier = np.concatenate([quiet, voice, quiet, quiet])
    assert select_preroll(said_earlier).size == 0
    still_speaking = np.concatenate([quiet, quiet, voice])  # speaking at the key press
    kept = select_preroll(still_speaking)
    assert 0 < kept.size <= int(0.3 * SAMPLE_RATE) and float(np.abs(kept[-1000:]).max()) > 0.05
    assert select_preroll(np.zeros(0, np.float32)).size == 0


def test_recorder_start_drops_earlier_speech_but_keeps_ongoing_speech():
    rec = Recorder(preroll_s=0.5)
    rng = np.random.default_rng(2)
    for chunk in np.split((0.2 * rng.standard_normal(4000)).astype(np.float32), 5):
        rec._preroll.append(chunk)
    for _ in range(5):  # then a pause before the key press
        rec._preroll.append((0.002 * rng.standard_normal(800)).astype(np.float32))
    rec._preroll_len = sum(len(c) for c in rec._preroll)
    rec.open = lambda: None
    rec.start()
    assert rec.snapshot().size == 0  # the earlier word is not part of this dictation
