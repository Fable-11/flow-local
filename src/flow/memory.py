"""Keep the process's memory footprint small while idle (Windows)."""

from __future__ import annotations

import ctypes
import gc
import sys


def trim_working_set() -> bool:
    """Ask Windows to page out memory this process is not actively using.

    Task Manager then shows a much smaller number; pages are loaded back on demand, so the next
    dictation may be a few milliseconds slower. Returns True if the call succeeded.
    """
    gc.collect()
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.K32EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        return bool(kernel32.K32EmptyWorkingSet(kernel32.GetCurrentProcess()))
    except (OSError, AttributeError):
        return False
