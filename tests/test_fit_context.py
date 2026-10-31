from __future__ import annotations

import pytest

from flow.insert import winapi
from flow.insert.caret import SAFE_APPS, read_around
from flow.insert.fit import fit_to_context

# -- fitting the text ---------------------------------------------------------------------------
CASES = [
    # (text, before, after, expected)
    ("The meeting is tomorrow.", "We said that ", " and then left.", "the meeting is tomorrow"),
    ("The meeting is tomorrow.", "", "", "The meeting is tomorrow."),  # empty field: unchanged
    ("The meeting is tomorrow.", "Hello there.\n", "", "The meeting is tomorrow."),
    ("The meeting is tomorrow.", "Hello there. ", "", "The meeting is tomorrow."),
    ("It works.", "I think", " so.", " it works"),  # mid-sentence: lower case, space, no stop
    ("Hello Sara.", "Dear ", ",", "Hello Sara"),  # a name keeps its capital
    ("I agree.", "and then ", " we go", "I agree"),  # "I" keeps its capital
    ("Really?", "so ", " it was", "Really?"),  # only plain function words are lowered
    ("Thanks.", "Line one.\n", "\nLine three.", "Thanks."),  # on its own line: complete sentence
    ("a new idea", "an ", "", "a new idea"),
    ("and more.", "red, ", " blue", "and more"),
    ("quickly.", "he ran", "", " quickly."),  # end of text: the full stop stays
    ("good", "so ", "bad", "good "),  # a word follows directly: add a space
    ("Hello.", "Hi. ", "World again.", "Hello. "),  # a whole sentence before a capital: kept
]


@pytest.mark.parametrize(("text", "before", "after", "expected"), CASES)
def test_fit_to_context(text, before, after, expected):
    assert fit_to_context(text, before, after) == expected


def test_a_space_separates_arabic_from_neighbouring_english_text():
    assert fit_to_context("مرحبا بكم", "see you", "") == " مرحبا بكم"  # English, then Arabic
    assert fit_to_context("Hello.", "مرحبا", "") == " Hello."  # Arabic, then English
    assert fit_to_context("مرحبا", "", "world") == "مرحبا "  # a word follows directly
    assert fit_to_context("مرحبا", "see you ", "") == "مرحبا"  # already separated


def test_arabic_text_and_arabic_neighbours_are_left_alone():
    assert fit_to_context("مرحبا بكم.", "قال ", " ثم") == "مرحبا بكم."
    assert fit_to_context("Hello.", "قال ", " ثم") == "Hello."


# -- reading the text around the cursor (simulated editor) ----------------------------------------
class FakeEditor:
    """A text box with a caret and an optional selection, driven by the probe's own keys."""

    def __init__(self, text: str, caret: int, selection: tuple[int, int] | None = None):
        self.text = text
        self.anchor = self.caret = caret
        if selection:
            self.anchor, self.caret = selection
        self.clipboard = "user clipboard"
        self.copies = 0

    def session(self):
        editor = self

        class Ctx:
            def __enter__(self):
                self.saved = editor.clipboard

            def __exit__(self, *exc):
                editor.clipboard = self.saved

        return Ctx()

    def press(self, vks):
        shift = winapi.VK_SHIFT in vks
        if winapi.VK_LEFT in vks:
            if shift:
                self.caret = max(0, self.caret - 1)
            else:
                self.caret = self.anchor = min(self.anchor, self.caret)
        elif winapi.VK_RIGHT in vks:
            if shift:
                self.caret = min(len(self.text), self.caret + 1)
            else:
                self.caret = self.anchor = max(self.anchor, self.caret)
        if not shift:
            self.anchor = self.caret

    def window_changed(self):
        return False

    def copy(self, timeout=None):
        self.copies += 1
        lo, hi = sorted((self.anchor, self.caret))
        if lo == hi:
            return None
        self.clipboard = self.text[lo:hi]
        return self.clipboard


def around(text, caret, **kw):
    editor = FakeEditor(text, caret, **kw)
    return read_around("chrome.exe", editor), editor


def test_reads_the_characters_on_both_sides_and_puts_the_cursor_back():
    got, ed = around("We said that and then left", 13)
    assert (got.before, got.after) == ("at ", "an")
    assert ed.anchor == ed.caret == 13 and ed.clipboard == "user clipboard"


def test_cursor_at_the_start_or_end_of_the_text():
    got, ed = around("Hello", 0)
    assert (got.before, got.after) == ("", "He") and ed.caret == 0
    got, ed = around("Hello", 5)
    assert (got.before, got.after) == ("llo", "") and ed.caret == 5
    got, ed = around("", 0)
    assert (got.before, got.after) == ("", "")


def test_an_existing_selection_is_never_touched():
    got, ed = around("replace this word please", 8, selection=(8, 12))
    assert got is None
    assert (ed.anchor, ed.caret) == (8, 12)  # still selected, so the dictation replaces it


def test_arabic_neighbours_mean_no_context():
    got, _ = around("قال مرحبا ثم", 5)
    assert got is None


@pytest.mark.parametrize(
    "process", ["cmd.exe", "windowsterminal.exe", "code.exe", "excel.exe", "unknown.exe", ""]
)
def test_unsafe_or_unknown_apps_are_not_probed(process):
    editor = FakeEditor("some text here", 5)
    assert read_around(process, editor) is None
    assert editor.copies == 0 and editor.caret == 5  # no key was sent at all


def test_a_failure_while_probing_gives_no_context_instead_of_an_error():
    class Broken(FakeEditor):
        def copy(self, timeout=None):
            raise OSError("clipboard busy")

    assert read_around("chrome.exe", Broken("text", 2)) is None


def test_browsers_and_chat_apps_are_in_the_safe_list():
    assert {"chrome.exe", "msedge.exe", "winword.exe", "slack.exe", "notepad.exe"} <= SAFE_APPS


def test_live_probe_in_a_real_text_box(monkeypatch):
    """Real keys and a real clipboard against a Tk text box (skipped without desktop focus)."""
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows only")
    import tkinter as tk

    from tests.winfocus import new_tk, require_focus

    from flow.insert import caret, clipboard

    monkeypatch.setattr(caret, "SAFE_APPS", caret.SAFE_APPS | {"python.exe"})
    root = new_tk()
    try:
        text = tk.Text(root, width=40, height=3)
        text.pack()
        text.insert("1.0", "We said that and then left")
        text.mark_set("insert", "1.13")
        require_focus(root, text)
        sentinel = clipboard.set_text("keep me")
        import threading

        result: list = []
        worker = threading.Thread(target=lambda: result.append(caret.read_around("python.exe")))
        worker.start()
        while worker.is_alive():  # Tk only reacts to the injected keys while its loop is pumped
            root.update()
        worker.join()
        root.update()
        got = result[0]
        assert got is not None and (got.before, got.after) == ("at ", "an")
        assert text.index("insert") == "1.13" and not text.tag_ranges("sel")  # cursor is back
        assert clipboard.get_text() == "keep me" and sentinel is not None
    finally:
        root.destroy()


class SlowEditor(FakeEditor):
    """An app that is slow to fill the clipboard: the first copy after each move shows nothing."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.waited = False

    def copy(self, timeout=None):
        if timeout is None and not self.waited and self.anchor != self.caret:
            self.waited = True
            self.copies += 1
            return None  # a selection exists, but it has not reached the clipboard yet
        self.waited = False
        return super().copy(timeout)


def test_a_slow_app_never_leaves_a_selection_behind():
    editor = SlowEditor("We said that and then left", 13)
    got = read_around("chrome.exe", editor)
    assert got is not None and (got.before, got.after) == ("at ", "an")
    assert editor.anchor == editor.caret == 13  # nothing selected, so the paste replaces nothing


def test_focus_moving_to_another_window_abandons_the_probe():
    class Wanders(FakeEditor):
        def window_changed(self):
            return self.copies >= 2  # the focus moves after the first look

    assert read_around("chrome.exe", Wanders("some text here", 5)) is None


class DroppedKey(FakeEditor):
    """An app that loses one key press (the paste then eats the text left selected)."""

    def __init__(self, lost: int, *a, **kw):
        super().__init__(*a, **kw)
        self.lost, self.count = lost, 0

    def press(self, vks):
        self.count += 1
        if self.count - 1 != self.lost:
            super().press(vks)


@pytest.mark.parametrize("lost", range(12))
def test_a_lost_key_never_leaves_text_selected_for_the_paste_to_replace(lost):
    editor = DroppedKey(lost, "the software. At all", 13)
    read_around("chrome.exe", editor)
    assert editor.anchor == editor.caret  # nothing is selected, so the paste replaces nothing
