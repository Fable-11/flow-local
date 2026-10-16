"""Launch-at-login via the per-user Run registry key (no admin rights needed)."""

from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FlowLocal"


def launch_parts(background: bool = True) -> tuple[str, str]:
    """(executable, arguments) that start the app; ``background`` = tray only, no window."""
    exe = Path(sys.executable)
    flag = "--background" if background else ""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return str(exe), flag
    pythonw = exe.with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else exe), f"-m flow {flag}".strip()


def launch_command() -> str:
    """Command line that starts the app windowless at login."""
    exe, args = launch_parts(background=True)
    return f'"{exe}" {args}'.strip()


def is_enabled(key_path: str = RUN_KEY) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY, command: str | None = None) -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command or launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
