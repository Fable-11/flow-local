import io
import queue
import sys
import threading
import wave

import numpy as np
import pytest

from flow import memory, sounds
from flow.audio.capture import SAMPLE_RATE, Recorder
from flow.config import MEMORY_MODES, Settings, settings_from_dict


# -- sounds -----------------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(sounds.CUES))
def test_cues_are_valid_wav_of_expected_length(name):
    data = sounds.synth(name, 0.6)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, sounds.RATE)
        assert abs(w.getnframes() / sounds.RATE - sounds.cue_duration(name)) < 0.01
        samples = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    assert samples.max() > 1000  # audible
    assert abs(int(samples[0])) < 50 and abs(int(samples[-1])) < 50  # faded: no click


def test_volume_scales_and_zero_is_silent():
    def peak(vol):
        with wave.open(io.BytesIO(sounds.synth("start", vol))) as w:
            return np.abs(np.frombuffer(w.readframes(w.getnframes()), np.int16)).max()

    assert peak(1.0) > peak(0.3) > 0
    assert peak(0.0) == 0


def test_cues_are_short():
    assert all(sounds.cue_duration(n) < 0.5 for n in sounds.CUES)


def test_play_respects_enabled_flag(monkeypatch, tmp_path):
    calls = []
    import winsound

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    sounds._paths.clear()
    monkeypatch.setattr(winsound, "PlaySound", lambda data, flags: calls.append((data, flags)))
    sounds.configure(False, 60)
    assert sounds.play("start") is False and calls == []
    assert sounds.play("start", force=True) is True and len(calls) == 1  # "Test" button
    sounds.configure(True, 60)
    assert sounds.play("stop") is True and len(calls) == 2
    sounds.configure(True, 60)


def test_play_survives_missing_sound_device(monkeypatch):
    import winsound

    def boom(*_a):
        raise RuntimeError("no device")

    monkeypatch.setattr(winsound, "PlaySound", boom)
    sounds.configure(True, 50)
    assert sounds.play("error") is False  # never raises into the dictation path


def test_configure_clamps():
    sounds.configure(True, 500)
    assert sounds.volume == 1.0
    sounds.configure(True, -5)
    assert sounds.volume == 0.0
    sounds.configure(True, 60)


# -- recorder blanks the start cue so the speakers' beep is not transcribed ----------------------
def feed(rec, n_blocks, value, block=800):
    for _ in range(n_blocks):
        rec._callback(np.full((block, 1), value, np.float32), block, None, None)


def test_recorder_mutes_the_cue_but_keeps_preroll_and_speech():
    rec = Recorder(preroll_s=0.5)
    feed(rec, 20, 0.1)  # idle: before the key press
    preroll = rec._preroll_len
    rec._mute = (preroll, int(0.2 * SAMPLE_RATE))  # what start(mute_s=0.2) records
    rec._chunks = list(rec._preroll)
    rec._preroll.clear()
    rec._recording = True
    feed(rec, 20, 0.9)  # beep + speech
    audio = rec.stop()
    assert audio[: preroll].max() == np.float32(0.1)  # words said just before the key: kept
    assert audio[preroll : preroll + int(0.2 * SAMPLE_RATE)].max() == 0.0  # cue span: silent
    after = preroll + int(0.2 * SAMPLE_RATE) + 10
    assert audio[after] == np.float32(0.9)  # speech after the cue: kept


def test_recorder_without_mute_is_untouched():
    rec = Recorder()
    rec._recording = True
    feed(rec, 3, 0.5)
    assert rec.stop().min() == np.float32(0.5)


# -- config -------------------------------------------------------------------------------------
def test_new_settings_defaults_and_validation():
    s = Settings()
    assert (s.sound_effects, s.sound_volume, s.bar_screens, s.memory_mode) == (
        True, 40, "all", "balanced",
    )  # fmt: skip
    bad = settings_from_dict(
        {"sound_volume": 900, "bar_screens": "moon", "memory_mode": "turbo", "sound_effects": "yes"}
    )
    assert (bad.sound_volume, bad.bar_screens, bad.memory_mode, bad.sound_effects) == (
        100, "all", "balanced", True,
    )  # fmt: skip
    assert set(MEMORY_MODES) == {"fast", "balanced", "low"}


# -- memory ---------------------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_trim_working_set_runs():
    assert memory.trim_working_set() is True


# -- worker idle unloading ----------------------------------------------------------------------
class FakeEngine:
    def __init__(self, loaded=True):
        self.loaded = loaded
        self.loads = 0
        self.unloads = 0

    def unload(self):
        self.loaded = False
        self.unloads += 1

    def load(self, allow_download=False):
        self.loads += 1
        self.loaded = True


def make_worker(mode="balanced", loaded=True):
    pytest.importorskip("PySide6")
    from flow.app import Worker

    w = Worker(None, queue.Queue(), lambda: Settings(memory_mode=mode), None, None, None)
    w.engine = FakeEngine(loaded)
    return w


def test_idle_unload_after_configured_minutes(monkeypatch):
    w = make_worker("balanced")
    w.last_activity -= 9 * 60  # 9 idle minutes: still loaded (limit is 10)
    w._idle_tick()
    assert w.engine.loaded
    w.last_activity -= 2 * 60
    w._idle_tick()
    assert not w.engine.loaded and w.unloaded_for_idle and w.engine.unloads == 1


def test_fast_mode_never_unloads_and_low_mode_unloads_sooner():
    fast = make_worker("fast")
    fast.last_activity -= 5 * 3600
    fast._idle_tick()
    assert fast.engine.loaded
    low = make_worker("low")
    low.last_activity -= 3 * 60
    low._idle_tick()
    assert not low.engine.loaded


def test_no_unload_while_recording_or_paused_or_missing_model_notice():
    for attr in ("recording", "paused"):
        w = make_worker("low")
        w.last_activity -= 3600
        setattr(w, attr, True)
        w._idle_tick()
        assert w.engine.loaded
    w = make_worker("low")
    w.last_activity -= 3600
    w.notice = "model problem"
    w._idle_tick()
    assert w.engine.loaded


def test_reload_starts_in_background_and_is_awaited():
    w = make_worker("low", loaded=False)
    w.unloaded_for_idle = True
    release = threading.Event()
    real_load = w.engine.load

    def slow_load(allow_download=False):
        release.wait(5)
        real_load(allow_download)

    w.engine.load = slow_load
    w._reload_in_background()
    assert w._reload_thread is not None and not w.engine.loaded  # still loading: user speaks
    w._reload_in_background()  # a second hotkey press must not start a second load
    release.set()
    assert w._wait_for_model() is True
    assert w.engine.loads == 1 and not w.unloaded_for_idle


def test_reload_does_nothing_if_model_is_loaded_or_never_unloaded():
    w = make_worker("low", loaded=True)
    w._reload_in_background()
    assert w._reload_thread is None
    w2 = make_worker("low", loaded=False)  # not loaded because it is missing, not idle-unloaded
    w2._reload_in_background()
    assert w2._reload_thread is None and w2._wait_for_model() is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_real_playback_does_not_raise_and_uses_a_file(monkeypatch, tmp_path):
    """Regression: winsound cannot play async from memory, which a mocked test hid."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    sounds._paths.clear()
    sounds.configure(True, 0)  # volume 0: the real call happens, but nothing is audible
    for name in sounds.CUES:
        assert sounds.play(name) is True
    files = sorted(p.name for p in (tmp_path / "FlowLocal" / "sounds").glob("*.wav"))
    v = sounds.DESIGN_VERSION
    assert files == [f"error_soft_v{v}_0.wav", f"start_soft_v{v}_0.wav", f"stop_soft_v{v}_0.wav"]
    sounds.configure(True, 60)
    sounds._paths.clear()


def test_volume_buckets_share_files(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    sounds._paths.clear()
    assert sounds.cue_file("start", 0.61) == sounds.cue_file("start", 0.60)
    assert sounds.cue_file("start", 0.30) != sounds.cue_file("start", 0.60)
    sounds._paths.clear()


# -- the cues must be soft: gentle onset, low pitch, quiet, no harsh edge -------------------
def _centroid_hz(x):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sounds.RATE)
    return float((spectrum * freqs).sum() / spectrum.sum())


@pytest.mark.parametrize("which", list(sounds.STYLES))
@pytest.mark.parametrize("name", list(sounds.CUES))
def test_cues_are_soft_not_sharp(name, which):
    x = sounds.synth_samples(name, 1.0, which)  # at full volume: the worst case
    peak = float(np.abs(x).max())
    assert peak <= 0.45  # well below full scale, never harsh
    assert _centroid_hz(x) < 1000  # dull and round, not bright or piercing
    # gentle onset: the first 5 ms may not exceed 40% of the peak (no tick or click)
    assert np.abs(x[: int(0.005 * sounds.RATE)]).max() < 0.4 * peak
    # smooth waveform: no sample-to-sample jump anywhere (a click would show up here)
    assert np.abs(np.diff(x)).max() < 0.08
    # ends exactly at silence, and quickly
    assert abs(x[-1]) < 1e-3 and abs(x[-200:]).max() < 0.02 * peak + 1e-4
    assert sounds.cue_duration(name, which) <= 0.4


def test_start_glides_up_and_stop_glides_down():
    def dominant(name, part):
        x = sounds.synth_samples(name, 1.0)
        n = len(x) // 4
        seg = x[:n] if part == "first" else x[n : 2 * n]
        spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        return np.fft.rfftfreq(len(seg), 1 / sounds.RATE)[int(np.argmax(spectrum))]

    assert dominant("start", "second") > dominant("start", "first")  # rising
    assert dominant("stop", "second") < dominant("stop", "first")  # falling


def test_error_cue_is_gentle_too_not_a_buzz():
    x = sounds.synth_samples("error", 1.0)
    assert _centroid_hz(x) < 700 and float(np.abs(x).max()) <= 0.45


def test_default_volume_is_modest():
    from flow.config import Settings

    quiet = sounds.synth_samples("start", Settings().sound_volume / 100)
    assert float(np.abs(quiet).max()) < 0.2  # under 20% of full scale by default


def test_old_sharp_files_are_replaced(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    sounds._paths.clear()
    folder = sounds.sounds_dir()
    old = folder / "start_60.wav"
    old.write_bytes(b"old sharp sound")
    sounds.cue_file("start", 0.4)
    assert not old.exists()  # cleaned up when the new design is first written
    sounds._paths.clear()


def test_pop_style_is_shorter_than_soft_and_config_validates_it():
    from flow.config import SOUND_STYLES, settings_from_dict

    assert sounds.cue_duration("start", "pop") < sounds.cue_duration("start", "soft")
    assert set(SOUND_STYLES) == set(sounds.STYLES) | {sounds.WINDOWS}
    assert settings_from_dict({"sound_style": "laser"}).sound_style == "soft"
    sounds.configure(True, 40, "laser")  # unknown style falls back safely
    assert sounds.style == "soft"
    sounds.configure(True, 60)


def test_style_changes_the_played_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    sounds._paths.clear()
    a = sounds.cue_file("start", 0.4, "soft")
    b = sounds.cue_file("start", 0.4, "pop")
    assert a != b and "soft" in a and "pop" in b
    sounds._paths.clear()


# -- "windows" style: the system speech chimes, softened ------------------------------------------
needs_windows_sounds = pytest.mark.skipif(
    not sounds.windows_available(), reason="Windows speech sounds not installed"
)


@needs_windows_sounds
@pytest.mark.parametrize("name", list(sounds.WINDOWS_FILES))
def test_windows_cues_are_short_soft_and_end_in_silence(name):
    x = sounds.synth_samples(name, 1.0, sounds.WINDOWS)
    assert float(np.abs(x).max()) <= 0.45
    assert _centroid_hz(x) < 1800  # the original sparkles up to 6 kHz; softened it must not
    assert sounds.cue_duration(name, sounds.WINDOWS) <= 0.4  # start cue is blanked from the audio
    assert abs(x[-1]) < 1e-3 and abs(x[:8]).max() < 0.05 * float(np.abs(x).max())  # no clicks
    assert np.abs(np.diff(x)).max() < 0.1


@needs_windows_sounds
def test_windows_style_is_selectable_and_playable(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    sounds._paths.clear()
    sounds.configure(True, 0, sounds.WINDOWS)  # volume 0: real playback, nothing audible
    assert sounds.style == sounds.WINDOWS
    assert all(sounds.play(n) for n in sounds.WINDOWS_FILES)
    assert sounds.cue_duration("start") == sounds.cue_duration("start", sounds.WINDOWS)
    sounds.configure(True, 40, "soft")
    sounds._paths.clear()


def test_windows_style_falls_back_to_soft_if_files_are_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SystemRoot", str(tmp_path))  # no Media folder here
    assert sounds.windows_available() is False
    sounds.configure(True, 40, sounds.WINDOWS)
    assert sounds.style == "soft"
    sounds.configure(True, 40, "soft")
