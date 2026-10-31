"""Two dictations in the same text must not run together ("friendHello").

When the cursor's surroundings cannot be read (the app answered too slowly, or the page does not
copy selections) the first dictation still tells us what is before the cursor: it was just put
there. That memory has to be used, whatever the probe says.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from test_enhance import _worker, speechlike

pytest.importorskip("PySide6")

import flow.app as app_mod  # noqa: E402
from flow.insert.caret import Around  # noqa: E402
from flow.insert.spacing import SpacingTracker  # noqa: E402


class Rig:
    def __init__(self, monkeypatch, around):
        self.w, self.states, _ = _worker(monkeypatch)
        self.clock = [1000.0]
        self.w.spacing = SpacingTracker(now=lambda: self.clock[0])
        self.pasted: list[str] = []
        monkeypatch.setattr(
            app_mod,
            "get_active_app",
            lambda: SimpleNamespace(hwnd=5, process="chrome.exe", title=""),
        )
        monkeypatch.setattr(app_mod, "paste_text", lambda text, *a, **k: self.pasted.append(text))
        monkeypatch.setattr(app_mod, "read_around", around)

    def dictate(self, wait: float = 20.0):
        self.clock[0] += wait
        self.w._finish(speechlike(peak=0.4, noise_rms=0.0005))


def unreadable(process):
    return Around("", "")  # the probe found nothing before the cursor


def readable(process):
    return Around("friend", "")  # the first dictation is right before the cursor


def not_allowed(process):
    return None  # an app where the cursor is never read


@pytest.mark.parametrize("around", [unreadable, readable, not_allowed])
def test_the_second_dictation_never_sticks_to_the_first(monkeypatch, around):
    rig = Rig(monkeypatch, around)
    rig.dictate()
    rig.dictate()
    first, second = rig.pasted
    assert second.startswith(" ")  # a space separates it from "friend"
    assert first.strip() == second.strip()


def test_a_long_pause_between_dictations_still_keeps_them_apart(monkeypatch):
    rig = Rig(monkeypatch, unreadable)
    rig.dictate()
    rig.dictate(wait=240.0)  # four minutes later, same window
    assert rig.pasted[1].startswith(" ")


def test_a_different_window_starts_clean(monkeypatch):
    rig = Rig(monkeypatch, unreadable)
    rig.dictate()
    monkeypatch.setattr(
        app_mod, "get_active_app", lambda: SimpleNamespace(hwnd=9, process="slack.exe", title="")
    )
    rig.dictate()
    assert not rig.pasted[1].startswith(" ")
