"""Replays real key sequences through the hotkey machine AND the worker together.

The machine and the worker were each tested alone and each looked right; the hands-free stop
bug lived in how they talk to each other (a cancel from the worker reset the machine).
"""

import queue
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("PySide6")

import flow.app as app_mod  # noqa: E402
from flow import sounds  # noqa: E402
from flow.config import Settings  # noqa: E402
from flow.hotkeys.bindings import HotkeyMachine  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class FakeRecorder:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self, mute_s=0.0):
        self.starts += 1

    def stop(self):
        self.stops += 1
        return np.zeros(16000, np.float32)


class Rig:
    """A worker wired to a real HotkeyMachine; keys go in, finished dictations come out."""

    def __init__(self, monkeypatch):
        monkeypatch.setattr(app_mod, "TAIL_S", 0.0)
        sounds.configure(False, 40)
        self.clock = Clock()
        self.states = []
        bridge = SimpleNamespace(
            state=SimpleNamespace(emit=lambda s, t="": self.states.append(s)),
            level=SimpleNamespace(emit=lambda v: None),
        )
        w = app_mod.Worker(bridge, queue.Queue(), lambda: Settings(), None, None, None)
        w.engine = SimpleNamespace(loaded=True)
        w.recorder = FakeRecorder()
        w.pipeline = SimpleNamespace(use_llm=False)
        w.llm = SimpleNamespace(last_used=0.0, warm_up=lambda: None)
        w.machine = HotkeyMachine(now=self.clock)
        self.finished = []
        self.commands = []
        w._finish = lambda audio: self.finished.append(audio)
        w._finish_command = lambda audio: self.commands.append(audio)
        self.w = w

    def key(self, name, down=True):
        for action in self.w.machine.feed(name, down).actions:
            self.w._dispatch(action)

    def press(self, *names):
        for n in names:
            self.key(n, True)

    def release(self, *names):
        for n in names:
            self.key(n, False)


@pytest.fixture
def rig(monkeypatch):
    return Rig(monkeypatch)


def test_push_to_talk_hold_and_release_inserts_once(rig):
    rig.press("ctrl", "win")
    assert rig.w.recording
    rig.clock.advance(1.0)
    rig.release("win", "ctrl")
    assert len(rig.finished) == 1 and not rig.w.recording and not rig.w.machine.active


def test_hands_free_start_keeps_recording_after_keys_are_released(rig):
    rig.press("ctrl", "win", "space")
    rig.release("space", "win", "ctrl")
    assert rig.w.recording and rig.w.handsfree
    assert rig.w.machine.active  # the machine must still know hands-free is on
    assert rig.finished == []


def test_hands_free_second_press_stops_and_INSERTS(rig):
    """The reported bug: stopping hands-free threw the audio away and started a new recording."""
    rig.press("ctrl", "win", "space")
    rig.release("space", "win", "ctrl")
    rig.clock.advance(5.0)
    rig.press("ctrl", "win", "space")  # press the same shortcut again to stop
    rig.release("space", "win", "ctrl")
    assert len(rig.finished) == 1  # the speech is processed and inserted
    assert not rig.w.recording and not rig.w.machine.active


def test_hands_free_can_be_repeated(rig):
    for _ in range(3):
        rig.press("ctrl", "win", "space")
        rig.release("space", "win", "ctrl")
        rig.clock.advance(2.0)
        rig.press("ctrl", "win", "space")
        rig.release("space", "win", "ctrl")
        rig.clock.advance(2.0)
    assert len(rig.finished) == 3 and not rig.w.recording


def test_double_tap_hands_free_then_double_tap_stops(rig):
    def tap():
        rig.press("ctrl", "win")
        rig.clock.advance(0.1)
        rig.release("win", "ctrl")
        rig.clock.advance(0.2)

    tap()
    tap()  # double tap: hands-free starts
    assert rig.w.recording and rig.w.handsfree and rig.w.machine.active
    rig.clock.advance(4.0)
    rig.press("ctrl", "win", "space")  # stop with the toggle shortcut
    rig.release("space", "win", "ctrl")
    assert len(rig.finished) == 1 and not rig.w.recording


def test_escape_cancels_hands_free_and_discards_audio(rig):
    rig.press("ctrl", "win", "space")
    rig.release("space", "win", "ctrl")
    rig.press("esc")
    rig.release("esc")
    assert rig.finished == [] and not rig.w.recording and not rig.w.machine.active
    # and the next hands-free session works normally
    rig.clock.advance(1.0)
    rig.press("ctrl", "win", "space")
    rig.release("space", "win", "ctrl")
    assert rig.w.recording


def test_escape_cancels_push_to_talk(rig):
    rig.press("ctrl", "win")
    rig.press("esc")
    rig.release("esc", "win", "ctrl")
    assert rig.finished == [] and not rig.w.recording


def test_bar_click_stops_hands_free_and_resets_the_machine(rig):
    rig.press("ctrl", "win", "space")
    rig.release("space", "win", "ctrl")
    rig.w._dispatch(app_mod.BAR_CLICK)
    assert len(rig.finished) == 1 and not rig.w.machine.active
    # the shortcut starts a fresh hands-free session afterwards
    rig.clock.advance(1.0)
    rig.press("ctrl", "win", "space")
    assert rig.w.recording


def test_command_mode_hold_release_runs_a_command(rig):
    rig.press("ctrl", "win", "alt")
    assert rig.w.recording and rig.w.command_mode
    rig.clock.advance(2.0)
    rig.release("alt", "win", "ctrl")
    assert len(rig.commands) == 1 and rig.finished == []


def test_pause_cancels_an_active_hands_free_session(rig):
    rig.press("ctrl", "win", "space")
    rig.release("space", "win", "ctrl")
    rig.w._dispatch(app_mod.PAUSE)
    assert not rig.w.recording and not rig.w.machine.active
    rig.w._dispatch(app_mod.RESUME)
    rig.clock.advance(1.0)
    rig.press("ctrl", "win", "space")
    assert rig.w.recording


def test_quick_tap_does_not_insert_anything(rig):
    rig.press("ctrl", "win")
    rig.clock.advance(0.1)
    rig.release("win", "ctrl")
    assert rig.finished == [] and not rig.w.recording


# -- the same scenario through the REAL keyboard hook (harmless F20/F21 keys, injected) --------
@pytest.mark.slow
def test_hands_free_through_the_real_hook(monkeypatch):
    import sys
    import time

    if sys.platform != "win32":
        pytest.skip("Windows only")
    from flow.hotkeys.winhook import HotkeyListener
    from flow.insert import winapi

    rig = Rig(monkeypatch)
    rig.w.machine = HotkeyMachine({"push_to_talk": "f20", "hands_free": "f20+f21"})
    actions: queue.Queue[str] = queue.Queue()
    listener = HotkeyListener(rig.w.machine, actions.put, ignore_injected=False)
    listener.start()

    def tap(*vks, hold=0.06):
        winapi.send([winapi._key(v) for v in vks])
        time.sleep(hold)
        winapi.send([winapi._key(v, up=True) for v in reversed(vks)])
        deadline = time.monotonic() + 2.0  # wait for the hook thread, however busy the machine is
        while actions.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)  # let any second action from the same key press arrive
        while not actions.empty():
            rig.w._dispatch(actions.get())

    try:
        tap(0x83, 0x84)  # F20+F21: start hands-free
        assert rig.w.recording and rig.w.handsfree and rig.w.machine.active
        for _ in range(3):  # pressing it again must STOP and insert, every time, never restart
            tap(0x83, 0x84)
            assert not rig.w.recording and not rig.w.machine.active
            tap(0x83, 0x84)
            assert rig.w.recording
        assert len(rig.finished) == 3
    finally:
        listener.stop()


# -- other programs are quietened while recording and ALWAYS put back ---------------------------
class FakeDucker:
    def __init__(self):
        self.events = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")

    def recover(self):
        self.events.append("recover")


def settle(ducker, expected, timeout=2.0):
    import time

    end = time.time() + timeout
    while len(ducker.events) < expected and time.time() < end:
        time.sleep(0.01)
    time.sleep(0.05)  # let any extra, unexpected call show up
    return ducker.events


@pytest.fixture
def ducked(rig):
    from flow.audio.ducking import DuckRunner

    rig.w.ducker = FakeDucker()
    rig.w.duck_runner = DuckRunner(rig.w.ducker, delay=0.03)
    return rig


def hold(seconds=0.12):
    import time

    time.sleep(seconds)  # a real recording lasts longer than the moment a tap does


def test_a_tap_never_quietens_anything(ducked):
    ducked.press("ctrl", "win")
    ducked.release("win", "ctrl")  # released at once: no recording worth quietening for
    assert settle(ducked.w.ducker, 1, timeout=0.3) == []


def test_push_to_talk_quietens_then_restores(ducked):
    ducked.press("ctrl", "win")
    hold()
    ducked.clock.advance(1.0)
    ducked.release("win", "ctrl")
    assert settle(ducked.w.ducker, 2) == ["start", "stop"]


def test_escape_restores_the_sound_too(ducked):
    ducked.press("ctrl", "win")
    hold()
    ducked.press("esc")
    ducked.release("esc", "win", "ctrl")
    assert settle(ducked.w.ducker, 2) == ["start", "stop"]


def test_hands_free_stays_quiet_until_you_stop(ducked):
    ducked.press("ctrl", "win", "space")
    ducked.release("space", "win", "ctrl")
    # Ctrl+Win starts a recording and Space turns it into hands-free: stop and start within
    # milliseconds. The other programs must be quietened once, with no flicker.
    assert settle(ducked.w.ducker, 1) == ["start"]
    ducked.clock.advance(5.0)
    ducked.press("ctrl", "win", "space")
    ducked.release("space", "win", "ctrl")
    assert settle(ducked.w.ducker, 2) == ["start", "stop"]


def test_a_recording_that_cannot_start_never_quietens_anything(ducked):
    def broken(mute_s=0.0):
        raise OSError("no microphone")

    ducked.w.recorder.start = broken
    ducked.w.recorder.close = lambda: None
    ducked.press("ctrl", "win")
    ducked.release("win", "ctrl")
    assert settle(ducked.w.ducker, 1, timeout=0.3) == []


def test_every_cancel_path_ends_with_the_sound_back(ducked):
    for _ in range(3):  # repeated sessions must not leave an unmatched start behind
        ducked.press("ctrl", "win", "space")
        ducked.release("space", "win", "ctrl")
        hold()
        ducked.press("esc")
        ducked.release("esc")
        hold(0.06)
        ducked.clock.advance(1.0)
    events = settle(ducked.w.ducker, 6)
    assert events.count("start") == events.count("stop") == 3
