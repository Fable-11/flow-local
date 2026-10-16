"""Live hook test: uses harmless F20 key events injected with SendInput."""

import sys
import time

import pytest

pytestmark = [pytest.mark.skipif(sys.platform != "win32", reason="Windows only"), pytest.mark.slow]


def test_hook_receives_f20_hold():
    from flow.hotkeys.bindings import PTT_START, PTT_STOP, HotkeyMachine
    from flow.hotkeys.winhook import HotkeyListener
    from flow.insert import winapi

    got: list[str] = []
    machine = HotkeyMachine({"push_to_talk": "f20"})
    listener = HotkeyListener(machine, got.append, ignore_injected=False)
    listener.start()
    try:
        winapi.send([winapi._key(0x83)])  # F20 down
        time.sleep(0.4)
        winapi.send([winapi._key(0x83, up=True)])
        time.sleep(0.3)
    finally:
        listener.stop()
    assert got == [PTT_START, PTT_STOP]


def test_hook_ignores_injected_by_default():
    from flow.hotkeys.bindings import HotkeyMachine
    from flow.hotkeys.winhook import HotkeyListener
    from flow.insert import winapi

    got: list[str] = []
    listener = HotkeyListener(HotkeyMachine({"push_to_talk": "f20"}), got.append)
    listener.start()
    try:
        winapi.send([winapi._key(0x83)])
        time.sleep(0.1)
        winapi.send([winapi._key(0x83, up=True)])
        time.sleep(0.2)
    finally:
        listener.stop()
    assert got == []


def test_hook_capture_reports_chord_and_swallows():
    from flow.hotkeys.bindings import HotkeyMachine
    from flow.hotkeys.winhook import HotkeyListener
    from flow.insert import winapi

    actions: list[str] = []
    chords: list[str] = []
    listener = HotkeyListener(HotkeyMachine(), actions.append, ignore_injected=False)
    listener.start()
    try:
        listener.begin_capture(chords.append)
        winapi.send([winapi._key(0x83)])  # F20 down
        winapi.send([winapi._key(0x83, up=True)])
        time.sleep(0.3)
    finally:
        listener.stop()
    assert chords == ["f20"]
    assert actions == []  # capture mode must not trigger dictation
