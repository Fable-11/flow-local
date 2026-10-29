"""Quietening other programs while dictating: never leave one muted, never touch the wrong one."""

from __future__ import annotations

import json
import os

import pytest

from flow.audio.ducking import LOWERED_TO, AudioDucker


class FakeSession:
    def __init__(self, pid, name, muted=False, volume=0.8):
        self.pid, self.name, self._muted, self._volume = pid, name, muted, volume

    def muted(self):
        return self._muted

    def volume(self):
        return self._volume

    def set_muted(self, value):
        self._muted = value

    def set_volume(self, value):
        self._volume = value


class FakeMixer:
    def __init__(self, sessions):
        self.items = sessions

    def sessions(self):
        return list(self.items)


@pytest.fixture
def mixer():
    return FakeMixer(
        [
            FakeSession(10, "music.exe"),
            FakeSession(11, "browser.exe"),
            FakeSession(12, "already_quiet.exe", muted=True),
            FakeSession(99, "flow.exe"),  # Flow Local's own sounds
        ]
    )


def ducker(mixer, tmp_path, mode="mute"):
    return AudioDucker(mode, tmp_path / "ducking.json", mixer, own_pids={99})


def test_other_programs_are_muted_and_restored(mixer, tmp_path):
    d = ducker(mixer, tmp_path)
    d.start()
    state = {s.name: s.muted() for s in mixer.items}
    assert state == {
        "music.exe": True, "browser.exe": True, "already_quiet.exe": True, "flow.exe": False
    }
    d.stop()
    state = {s.name: s.muted() for s in mixer.items}
    # restored, except the one that was already muted before: that is how the user had it
    assert state == {
        "music.exe": False, "browser.exe": False, "already_quiet.exe": True, "flow.exe": False
    }


def test_a_program_the_user_unmuted_meanwhile_is_left_alone(mixer, tmp_path):
    d = ducker(mixer, tmp_path)
    d.start()
    mixer.items[0]._muted = False  # the user unmuted the music in the Windows mixer
    mixer.items[1]._muted = True
    d.stop()
    assert mixer.items[0].muted() is False and mixer.items[1].muted() is False


def test_lower_mode_dips_the_volume_and_puts_it_back(mixer, tmp_path):
    d = ducker(mixer, tmp_path, "lower")
    d.start()
    assert mixer.items[0].volume() == pytest.approx(0.8 * LOWERED_TO)
    assert not mixer.items[0].muted()
    d.stop()
    assert mixer.items[0].volume() == pytest.approx(0.8)


def test_a_volume_the_user_moved_meanwhile_is_not_overwritten(mixer, tmp_path):
    d = ducker(mixer, tmp_path, "lower")
    d.start()
    mixer.items[0]._volume = 0.5  # the user turned it up
    d.stop()
    assert mixer.items[0].volume() == 0.5


def test_off_mode_touches_nothing(mixer, tmp_path):
    d = ducker(mixer, tmp_path, "off")
    d.start()
    assert not any(s.muted() for s in mixer.items if s.name != "already_quiet.exe")
    d.stop()


def test_start_twice_and_stop_twice_are_harmless(mixer, tmp_path):
    d = ducker(mixer, tmp_path)
    d.start()
    d.start()
    d.stop()
    d.stop()
    assert [s.muted() for s in mixer.items] == [False, False, True, False]


def test_a_crash_is_undone_by_the_next_start(mixer, tmp_path):
    first = ducker(mixer, tmp_path)
    first.start()
    assert (tmp_path / "ducking.json").exists()  # written before anything was muted
    # the app dies here: nobody calls stop(). A new run finds the record and restores.
    second = ducker(mixer, tmp_path)
    assert second.recover() == 2
    assert [s.muted() for s in mixer.items] == [False, False, True, False]
    assert not (tmp_path / "ducking.json").exists()


def test_a_record_about_another_program_with_the_same_number_is_ignored(mixer, tmp_path):
    (tmp_path / "ducking.json").write_text(
        json.dumps([{"pid": 10, "name": "something_else.exe", "mode": "mute", "was_volume": 0.8}])
    )
    mixer.items[0]._muted = True  # muted by the user, and it is a different program now
    assert ducker(mixer, tmp_path).recover() == 1
    assert mixer.items[0].muted() is True  # untouched


def test_a_damaged_record_is_discarded_quietly(mixer, tmp_path):
    (tmp_path / "ducking.json").write_text("not json")
    assert ducker(mixer, tmp_path).recover() == 0
    assert not (tmp_path / "ducking.json").exists()


def test_a_broken_mixer_never_raises(tmp_path):
    class Broken:
        def sessions(self):
            return []

    d = AudioDucker("mute", tmp_path / "d.json", Broken(), own_pids=set())
    d.start()
    d.stop()
    assert not d.active


def test_the_record_is_written_before_muting(mixer, tmp_path):
    seen = {}

    class Spy(FakeSession):
        def set_muted(self, value):
            seen["record_existed"] = (tmp_path / "ducking.json").exists()
            super().set_muted(value)

    mixer.items = [Spy(10, "music.exe")]
    ducker(mixer, tmp_path).start()
    assert seen["record_existed"] is True


def test_own_process_numbers_default_to_this_process():
    assert os.getpid() in AudioDucker("mute", None, FakeMixer([])).own_pids
