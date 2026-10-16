"""Clipboard snapshot/restore with a crash-safe on-disk journal (Windows only)."""

from __future__ import annotations

import base64
import contextlib
import ctypes
import json
import logging
import os
import time
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
# Handle-based formats (GDI objects, owner-display) cannot be copied as raw bytes.
_SKIP_FORMATS = {2, 3, 9, 14, 0x80, 0x81, 0x82, 0x83, 0x8E}
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

Snapshot = list[tuple[int, bytes]]
_HISTORY_OPT_OUT = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
)


def journal_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FlowLocal"
    base.mkdir(parents=True, exist_ok=True)
    return base / "clipboard_journal.json"


@contextlib.contextmanager
def open_clipboard(retries: int = 20, delay: float = 0.02):
    for _ in range(retries):
        if user32.OpenClipboard(None):
            break
        time.sleep(delay)
    else:
        raise OSError("could not open clipboard (held by another app)")
    try:
        yield
    finally:
        user32.CloseClipboard()


def sequence_number() -> int:
    return int(user32.GetClipboardSequenceNumber())


def snapshot() -> Snapshot:
    out: Snapshot = []
    total = 0
    with open_clipboard():
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if fmt in _SKIP_FORMATS:
                continue
            handle = user32.GetClipboardData(fmt)
            if not handle:
                continue
            size = kernel32.GlobalSize(handle)
            if not size or total + size > MAX_SNAPSHOT_BYTES:
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                continue
            try:
                out.append((fmt, ctypes.string_at(ptr, size)))
                total += size
            finally:
                kernel32.GlobalUnlock(handle)
    return out


def _set_bytes(fmt: int, data: bytes) -> None:
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(len(data), 1))
    if not h:
        raise MemoryError("GlobalAlloc failed")
    ptr = kernel32.GlobalLock(h)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(h)
    if not user32.SetClipboardData(fmt, h):
        kernel32.GlobalFree(h)
        raise OSError(f"SetClipboardData({fmt}) failed")


def restore(snap: Snapshot) -> None:
    with open_clipboard():
        user32.EmptyClipboard()
        for fmt, data in snap:
            try:
                _set_bytes(fmt, data)
            except OSError:
                log.warning("could not restore clipboard format %s", fmt)


def set_text(text: str, hide_from_history: bool = True) -> int:
    """Replace clipboard with text; returns the sequence number after our write."""
    with open_clipboard():
        user32.EmptyClipboard()
        _set_bytes(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
        if hide_from_history:
            for name in _HISTORY_OPT_OUT:
                fmt = user32.RegisterClipboardFormatW(name)
                with contextlib.suppress(OSError):
                    _set_bytes(fmt, (0).to_bytes(4, "little"))
    return sequence_number()


def get_text() -> str | None:
    with open_clipboard():
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(h)


# -- crash-safe journal ---------------------------------------------------------------------
def write_journal(snap: Snapshot, path: Path | None = None) -> None:
    payload = [[f, base64.b64encode(d).decode("ascii")] for f, d in snap]
    (path or journal_path()).write_text(json.dumps(payload), encoding="utf-8")


def clear_journal(path: Path | None = None) -> None:
    with contextlib.suppress(FileNotFoundError):
        (path or journal_path()).unlink()


def recover_journal(path: Path | None = None) -> bool:
    """If a previous run died mid-paste, put the user's clipboard back. True if recovered."""
    p = path or journal_path()
    if not p.exists():
        return False
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        restore([(int(f), base64.b64decode(d)) for f, d in payload])
    except (OSError, ValueError):
        log.exception("clipboard journal recovery failed")
        return False
    finally:
        clear_journal(p)
    return True


@contextlib.contextmanager
def preserved_clipboard():
    """Snapshot the clipboard, journal it, and restore afterwards.

    Restore is skipped if something else wrote to the clipboard after us (sequence changed).
    Yields a holder whose ``seq`` the caller sets to the sequence number after its own write.
    """

    class Holder:
        seq: int | None = None

    snap: Snapshot = []
    try:
        snap = snapshot()
    except OSError:
        log.warning("clipboard snapshot failed; clipboard will not be restored")
    if snap:
        write_journal(snap)
    holder = Holder()
    try:
        yield holder
    finally:
        try:
            if snap and (holder.seq is None or sequence_number() == holder.seq):
                restore(snap)
        except OSError:
            log.exception("clipboard restore failed")
        finally:
            clear_journal()
