"""Low-level Windows keyboard + mouse hook feeding a HotkeyMachine (Windows only)."""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

from flow.hotkeys.bindings import HotkeyMachine, format_chord
from flow.insert import winapi

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_MBUTTONDOWN, WM_MBUTTONUP, WM_XBUTTONDOWN, WM_XBUTTONUP = 0x207, 0x208, 0x20B, 0x20C
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def _build_vk_names() -> dict[int, str]:
    names = {
        0xA0: "shift", 0xA1: "shift", 0x10: "shift",
        0xA2: "ctrl", 0xA3: "ctrl", 0x11: "ctrl",
        0xA4: "alt", 0xA5: "alt", 0x12: "alt",
        0x5B: "win", 0x5C: "win",
        0x20: "space", 0x1B: "esc", 0x0D: "enter", 0x09: "tab", 0x08: "backspace",
        0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
        0x2D: "insert", 0x2E: "delete", 0x24: "home", 0x23: "end",
        0x21: "pageup", 0x22: "pagedown", 0x14: "capslock",
    }  # fmt: skip
    for i in range(26):
        names[0x41 + i] = chr(ord("a") + i)
    for i in range(10):
        names[0x30 + i] = str(i)
    for i in range(24):
        names[0x70 + i] = f"f{i + 1}"
    return names


VK_NAMES = _build_vk_names()


class HotkeyListener:
    """Runs the hook on its own thread. ``on_action`` is called on that thread: keep it fast."""

    def __init__(
        self,
        machine: HotkeyMachine,
        on_action: Callable[[str], None],
        ignore_injected: bool = True,
    ) -> None:
        self.machine = machine
        self.on_action = on_action
        self.ignore_injected = ignore_injected
        self._thread: threading.Thread | None = None
        self._capture: Callable[[str], None] | None = None
        self._cap_pressed: set[str] = set()
        self._cap_all: set[str] = set()
        self._tid = 0
        self._ready = threading.Event()
        self._error: Exception | None = None
        # keep references so the callbacks are not garbage collected
        self._kb_proc = HOOKPROC(self._kb)
        self._ms_proc = HOOKPROC(self._ms)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="flow-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise self._error

    def begin_capture(self, callback: Callable[[str], None]) -> None:
        """Swallow all keys until a chord is pressed and fully released; report it as text."""
        self._cap_pressed, self._cap_all = set(), set()
        self._capture = callback

    def cancel_capture(self) -> None:
        self._capture = None

    def stop(self) -> None:
        if self._thread and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = None

    # -- hook thread -----------------------------------------------------------------------
    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        hmod = kernel32.GetModuleHandleW(None)
        kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, hmod, 0)
        ms = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, hmod, 0)
        if not kb:
            self._error = OSError(f"keyboard hook failed ({ctypes.get_last_error()})")
        self._ready.set()
        if not kb:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(kb)
        if ms:
            user32.UnhookWindowsHookEx(ms)

    def _handle(self, key: str, down: bool) -> bool:
        """Feed the machine; return True if the event must be swallowed."""
        try:
            if self._capture is not None:
                return self._capture_event(key, down)
            res = self.machine.feed(key, down)
            if res.inject_dummy:
                winapi.inject_dummy_key()
            for action in res.actions:
                self.on_action(action)
            return res.swallow
        except Exception:  # noqa: BLE001 - a hook callback must never raise
            log.exception("hotkey handler error")
            return False

    def _capture_event(self, key: str, down: bool) -> bool:
        if down:
            self._cap_pressed.add(key)
            self._cap_all.add(key)
        else:
            self._cap_pressed.discard(key)
            if not self._cap_pressed and self._cap_all:
                chord = format_chord(frozenset(self._cap_all))
                callback, self._capture = self._capture, None
                self._cap_all = set()
                if callback:
                    callback(chord)
        return True

    def _kb(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0:
            info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            name = VK_NAMES.get(info.vkCode)
            injected = bool(info.flags & LLKHF_INJECTED)
            if name and not (injected and self.ignore_injected):
                down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if self._handle(name, down):
                    return 1
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _ms(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0 and wparam in (WM_MBUTTONDOWN, WM_MBUTTONUP, WM_XBUTTONDOWN, WM_XBUTTONUP):
            info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (info.flags & LLMHF_INJECTED and self.ignore_injected):
                if wparam in (WM_MBUTTONDOWN, WM_MBUTTONUP):
                    name = "mouse_middle"
                else:
                    name = "mouse_x1" if (info.mouseData >> 16) == 1 else "mouse_x2"
                down = wparam in (WM_MBUTTONDOWN, WM_XBUTTONDOWN)
                if self._handle(name, down):
                    return 1
        return user32.CallNextHookEx(None, code, wparam, lparam)
