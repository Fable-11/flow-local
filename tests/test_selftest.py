from __future__ import annotations

from flow import selftest
from flow.selftest import Check, redact, report, run


def test_the_user_name_and_home_folder_never_appear_in_a_report(tmp_path):
    home = tmp_path / "Alexandra"
    text = f"data in {home / 'AppData'} and user Alexandra logged in"
    out = redact(text, home=home, user="Alexandra")
    assert "Alexandra" not in out and "~" in out and "<user>" in out


def test_very_short_user_names_are_not_replaced_everywhere():
    nowhere = selftest.Path("Z:/nowhere")
    assert redact("no names here: ab", home=nowhere, user="ab") == "no names here: ab"


def test_a_crashing_check_is_reported_and_the_others_still_run():
    def boom():
        raise RuntimeError("driver exploded")

    def fine():
        return Check("Fine", "ok", "works")

    results = run([boom, fine])
    assert results[0].status == "fail" and "driver exploded" in results[0].detail
    assert results[1].status == "ok"
    assert selftest.exit_code(results) == 1
    assert selftest.exit_code([results[1]]) == 0


def test_warnings_and_skips_do_not_fail_the_run():
    results = [Check("A", "warn", "x"), Check("B", "skip", "y"), Check("C", "ok", "z")]
    assert selftest.exit_code(results) == 0
    text = report(results, "9.9.9")
    assert "self-check" in text and "1 warning" in text and "1 skipped" in text


def test_the_cleanup_check_expects_what_the_rules_really_do():
    assert selftest.check_cleanup().status == "ok"


def test_clipboard_check_leaves_the_clipboard_as_it_was(monkeypatch):
    from flow.insert import clipboard

    state = {"text": "before"}
    monkeypatch.setattr(clipboard, "snapshot", lambda: [("fake", b"before")])
    monkeypatch.setattr(clipboard, "write_journal", lambda snap: None)
    monkeypatch.setattr(clipboard, "clear_journal", lambda: None)
    monkeypatch.setattr(clipboard, "sequence_number", lambda: 1)
    monkeypatch.setattr(clipboard, "set_text", lambda t, **k: state.update(text=t) or 1)
    monkeypatch.setattr(clipboard, "get_text", lambda: state["text"])
    monkeypatch.setattr(clipboard, "restore", lambda snap: state.update(text="before"))
    assert selftest.check_clipboard().status == "ok"
    assert state["text"] == "before"
