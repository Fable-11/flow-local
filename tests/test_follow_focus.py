"""The text goes where the keyboard focus is when the dictation is ready, not where it started."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from test_enhance import _worker, speechlike

pytest.importorskip("PySide6")

import flow.app as app_mod  # noqa: E402


def window(process, hwnd):
    return SimpleNamespace(hwnd=hwnd, process=process, title="")


def test_the_paste_follows_the_speaker_to_the_window_they_moved_to(monkeypatch):
    w, states, _heard = _worker(monkeypatch)
    seen = {"paste": [], "probe": [], "spacing": []}
    windows = iter([window("chrome.exe", 1), window("mintty.exe", 2)])  # at start, then when ready
    monkeypatch.setattr(app_mod, "get_active_app", lambda: next(windows))
    monkeypatch.setattr(
        app_mod, "paste_text", lambda text, method="clipboard", **k: seen["paste"].append(method)
    )
    monkeypatch.setattr(app_mod, "read_around", lambda process: seen["probe"].append(process))
    w.spacing = SimpleNamespace(
        prefix_for=lambda hwnd, text: seen["spacing"].append(hwnd) or "", record=lambda *a: None
    )
    w._finish(speechlike(peak=0.4, noise_rms=0.0005))
    # the terminal the speaker moved to, not the browser it started in, decided all three
    assert seen["probe"] == ["mintty.exe"]
    assert seen["paste"] == ["shift"]  # mintty needs Ctrl+Shift+V
    assert seen["spacing"] == [2]
    assert states[-1][0] == "done"  # and it is never reported as a failure


def test_text_is_never_withheld_because_the_window_changed(monkeypatch):
    w, states, _heard = _worker(monkeypatch)
    pasted = []
    windows = iter([window("chrome.exe", 1), window("slack.exe", 9)])
    monkeypatch.setattr(app_mod, "get_active_app", lambda: next(windows))
    monkeypatch.setattr(app_mod, "paste_text", lambda text, *a, **k: pasted.append(text))
    monkeypatch.setattr(app_mod, "read_around", lambda process: None)
    w._finish(speechlike(peak=0.4, noise_rms=0.0005))
    assert pasted == ["hello there my friend"]
    assert not any(s == "error" for s, _t in states)
