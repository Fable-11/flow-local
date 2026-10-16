"""Windows integration tests. Clipboard tests touch the real clipboard but restore it."""

import sys
import time

import pytest

from winfocus import new_tk, require_focus

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_clipboard_text_roundtrip_and_restore():
    from flow.insert import clipboard

    original = clipboard.snapshot()
    try:
        clipboard.set_text("héllo مرحبا")
        assert clipboard.get_text() == "héllo مرحبا"
        snap = clipboard.snapshot()
        clipboard.set_text("other")
        clipboard.restore(snap)
        assert clipboard.get_text() == "héllo مرحبا"
    finally:
        clipboard.restore(original)


def test_journal_recovery(tmp_path):
    from flow.insert import clipboard

    original = clipboard.snapshot()
    try:
        clipboard.set_text("keep me")
        snap = clipboard.snapshot()
        jp = tmp_path / "journal.json"
        clipboard.write_journal(snap, jp)
        clipboard.set_text("clobbered by crashed paste")
        assert clipboard.recover_journal(jp) is True
        assert clipboard.get_text() == "keep me"
        assert not jp.exists()
        assert clipboard.recover_journal(jp) is False
    finally:
        clipboard.restore(original)


def test_preserved_clipboard_skips_restore_if_user_copied():
    from flow.insert import clipboard

    original = clipboard.snapshot()
    try:
        clipboard.set_text("before")
        with clipboard.preserved_clipboard() as holder:
            holder.seq = clipboard.set_text("ours")
            clipboard.set_text("user copied this meanwhile")
        assert clipboard.get_text() == "user copied this meanwhile"
    finally:
        clipboard.restore(original)


def test_active_app_returns_something():
    from flow.insert.context import get_active_app

    ctx = get_active_app()
    assert isinstance(ctx.process, str)


def test_paste_method_override():
    from flow.insert.paste import method_for

    assert method_for("MinTTY.exe") == "shift"
    assert method_for("chrome.exe") == "clipboard"


@pytest.mark.slow
@pytest.mark.parametrize("method", ["clipboard", "type"])
def test_paste_into_real_window(method):
    """Needs an interactive desktop: opens a Tk window, focuses it, inserts text."""
    tk = pytest.importorskip("tkinter")
    from flow.insert import clipboard
    from flow.insert.paste import paste_text

    text = "Hello مرحبا world\nsecond line"
    original = clipboard.snapshot()
    root = new_tk()
    try:
        box = tk.Text(root)
        box.pack()
        require_focus(root, box)
        for _ in range(20):
            root.update()
            time.sleep(0.02)
        import threading

        t = threading.Thread(target=paste_text, args=(text, method))
        t.start()
        while t.is_alive():
            root.update()
            time.sleep(0.01)
        for _ in range(10):
            root.update()
            time.sleep(0.02)
        assert box.get("1.0", "end-1c") == text
    finally:
        root.destroy()
        clipboard.restore(original)
