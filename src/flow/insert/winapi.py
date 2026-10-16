"""Thin ctypes wrappers around SendInput and key state (Windows only)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_DUMMY = 0xE8  # unassigned; used to cancel the Start-menu trigger on Win release
VK_V = 0x56
VK_C = 0x43

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = wintypes.SHORT


def _key(vk: int = 0, up: bool = False, char: int | None = None) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    scan = 0
    if char is not None:
        flags |= KEYEVENTF_UNICODE
        scan = char
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))


def send(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def chord(vks: list[int]) -> None:
    """Press all keys in order, then release in reverse order."""
    send([_key(v) for v in vks] + [_key(v, up=True) for v in reversed(vks)])


def type_unicode(text: str) -> None:
    """Type text as Unicode key events; newlines become Enter. Works without the clipboard."""
    events: list[INPUT] = []
    utf16 = text.replace("\r\n", "\n").encode("utf-16-le")
    units = [int.from_bytes(utf16[i : i + 2], "little") for i in range(0, len(utf16), 2)]
    for u in units:
        if u == 0x0A:
            events += [_key(VK_RETURN), _key(VK_RETURN, up=True)]
        else:
            events += [_key(0, char=u), _key(0, up=True, char=u)]
    for i in range(0, len(events), 400):  # keep each SendInput call modest
        send(events[i : i + 400])


def inject_dummy_key() -> None:
    chord([VK_DUMMY])


def is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def modifiers_down() -> bool:
    return any(is_down(v) for v in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))


def wait_modifiers_released(timeout: float = 3.0) -> bool:
    """Wait until the user lets go of Ctrl/Shift/Alt/Win so our synthetic keys stay clean."""
    end = time.monotonic() + timeout
    while modifiers_down():
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    return True
