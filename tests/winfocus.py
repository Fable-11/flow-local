"""Helper for live tests that need a real window to hold keyboard focus."""

import ctypes
import time

import pytest


def require_focus(root, widget=None, timeout=2.0):
    """Give a Tk window the foreground and keyboard focus, or skip the test.

    Windows refuses to hand focus to a background process while the user is working in another
    window, which is an environment problem, not a bug in the code under test. The caller's
    ``finally`` destroys the window as usual.
    """
    user32 = ctypes.windll.user32
    root.attributes("-topmost", True)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        mine = int(root.wm_frame(), 16)  # the real top-level window handle
        user32.SetForegroundWindow(mine)
        root.focus_force()
        (widget or root).focus_force()
        if user32.GetForegroundWindow() == mine:
            return
        time.sleep(0.05)
    pytest.skip("could not take keyboard focus (the desktop is in active use)")


def new_tk():
    """tkinter.Tk() with retries: creating and destroying Tk repeatedly in one process can
    intermittently fail with 'Tcl wasn't installed properly' on Windows."""
    import tkinter as tk

    last = None
    for _ in range(4):
        try:
            return tk.Tk()
        except tk.TclError as e:  # noqa: PERF203
            last = e
            time.sleep(0.3)
    pytest.skip(f"tkinter is unreliable in this session: {last}")
