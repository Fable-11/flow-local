from __future__ import annotations

import numpy as np
import pytest

from flow.audio.capture import Recorder
from flow.guards import describe_failure, label_language, paste_target_changed


# -- where the text goes -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("before", "now", "own", "changed"),
    [
        ("chrome.exe", "chrome.exe", "pythonw.exe", False),  # same program: tabs are fine
        ("chrome.exe", "slack.exe", "pythonw.exe", True),  # moved to another program
        ("chrome.exe", "pythonw.exe", "pythonw.exe", False),  # Flow Local's own window
        ("CHROME.EXE", "chrome.exe", "pythonw.exe", False),  # case does not matter
        ("", "slack.exe", "pythonw.exe", False),  # unknown before: never block
        ("chrome.exe", "", "pythonw.exe", False),  # unknown now: never block
    ],
)
def test_paste_target_changed(before, now, own, changed):
    assert paste_target_changed(before, now, own) is changed


# -- messages ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (MemoryError(), "Out of memory, try again"),
        (RuntimeError("CUDA out of memory"), "Out of memory, try again"),
        (OSError("clipboard is locked"), "Clipboard busy, try again"),
        (TimeoutError(), "Took too long, try again"),
        (OSError("disk"), "Could not insert the text, see log"),
        (ValueError("x"), "Something went wrong, see log"),
    ],
)
def test_describe_failure(exc, expected):
    assert describe_failure(exc) == expected


# -- language label from what was written ------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "detected", "label"),
    [
        ("Can you show me the code?", "ar", "en"),  # English text under an Arabic tag
        ("السلام عليكم كيف حالك", "en", "ar"),
        ("Send it to عمر", "en", "en"),  # mostly English
        ("افتح ملف README الآن", "ar", "ar"),
        ("12:30 ?!", "ar", "ar"),  # nothing to go on: keep the detector's answer
        ("", "en", "en"),
    ],
)
def test_label_language_follows_the_script(text, detected, label):
    assert label_language(text, detected) == label


# -- the microphone comes back after the device went away -------------------------------------
class DeadStream:
    active = False

    def __init__(self):
        self.closed = False

    def stop(self):
        pass

    def close(self):
        self.closed = True


def test_a_stream_that_died_is_replaced_when_recording_starts(monkeypatch):
    rec = Recorder()
    dead = DeadStream()
    rec._stream = dead
    opened = []
    monkeypatch.setattr(rec, "open", lambda: opened.append(1) or setattr(rec, "_stream", object()))
    rec.start()
    assert dead.closed and opened == [1]  # closed the dead stream, then opened a new one
    assert rec._recording
    rec._callback(np.zeros((800, 1), np.float32), 800, None, None)  # still records normally
