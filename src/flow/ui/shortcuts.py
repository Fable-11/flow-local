"""Desktop shortcuts to open and stop Flow Local (created with the Windows shell COM object)."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path

from flow.ui.autostart import launch_parts

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OPEN_NAME = "Flow Local.lnk"
STOP_NAME = "Stop Flow Local.lnk"

_CREATE = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:FL_LNK)
$s.TargetPath = $env:FL_TARGET
$s.Arguments = $env:FL_ARGS
$s.WorkingDirectory = $env:FL_WORKDIR
$s.Description = $env:FL_DESC
$s.WindowStyle = [int]$env:FL_STYLE
if ($env:FL_ICON) { $s.IconLocation = $env:FL_ICON }
$s.Save()
"""
_READ = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:FL_LNK)
$s.TargetPath; $s.Arguments
"""


def _powershell(script: str, **env: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "powershell failed")
    return result.stdout


def desktop_dir() -> Path:
    out = _powershell("[Environment]::GetFolderPath('Desktop')").strip()
    return Path(out) if out else Path.home() / "Desktop"


def create_shortcut(
    lnk: Path, target: str, args: str = "", workdir: str = "", icon: str = "", desc: str = "",
    minimized: bool = False,
) -> Path:  # fmt: skip
    lnk.parent.mkdir(parents=True, exist_ok=True)
    _powershell(
        _CREATE,
        FL_LNK=str(lnk), FL_TARGET=target, FL_ARGS=args, FL_WORKDIR=workdir, FL_ICON=icon,
        FL_DESC=desc, FL_STYLE="7" if minimized else "1",
    )  # fmt: skip
    return lnk


def read_shortcut(lnk: Path) -> tuple[str, str]:
    lines = _powershell(_READ, FL_LNK=str(lnk)).splitlines()
    return (lines[0] if lines else ""), (lines[1] if len(lines) > 1 else "")


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
# Explorer caches icons by file path (including failures). Bump this when the icon files change
# so shortcuts point at a new path and show the new icon instead of a stale blank one.
ICON_VERSION = 2


def build_ico(images: dict[int, bytes]) -> bytes:
    """Assemble an .ico from PNG images keyed by pixel size (PNG entries are valid since Vista)."""
    sizes = sorted(images)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, payload = b"", b""
    for size in sizes:
        data = images[size]
        dim = 0 if size >= 256 else size  # 0 means 256 in the directory entry
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(payload))
        payload += data
    return header + entries + payload


def _png_bytes(icon, size: int) -> bytes:  # noqa: ANN001
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    icon.pixmap(size, size).save(buf, "PNG")
    buf.close()
    return bytes(data)


def _dib_bytes(icon, size: int) -> bytes:  # noqa: ANN001
    """Classic icon image data: a 32-bit BGRA bitmap (bottom-up) plus an empty AND mask.

    Explorer only reliably reads PNG-compressed entries at 256 px; smaller sizes need this form.
    """
    from PySide6.QtGui import QImage

    img = icon.pixmap(size, size).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    raw = bytes(img.constBits())[: size * size * 4]
    rows = [raw[y * size * 4 : (y + 1) * size * 4] for y in range(size)]
    pixels = b"".join(reversed(rows))  # bottom-up
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    mask_row = ((size + 31) // 32) * 4
    return header + pixels + bytes(mask_row * size)  # AND mask all zero: the alpha channel rules


def ensure_icon(kind: str = "app") -> str:
    """Write a crisp multi-size icon ("app" = blue, "stop" = red) to %LOCALAPPDATA%\\FlowLocal.

    Needs Qt. Returns the path, or an empty string if it could not be written.
    """
    from PySide6.QtGui import QGuiApplication

    from flow.store.db import default_db_path
    from flow.ui.tray import make_icon, make_stop_icon

    folder = default_db_path().parent
    stem = "flow-stop" if kind == "stop" else "flow"
    path = folder / f"{stem}-v{ICON_VERSION}.ico"
    for old in folder.glob(f"{stem}*.ico"):  # leftovers from earlier versions
        if old != path:
            old.unlink(missing_ok=True)
    try:
        if QGuiApplication.instance() is None:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            _app = QGuiApplication(sys.argv)  # noqa: F841
        icon = make_stop_icon(256) if kind == "stop" else make_icon(256)
        path.write_bytes(
            build_ico({s: _png_bytes(icon, s) if s >= 256 else _dib_bytes(icon, s) for s in ICON_SIZES})
        )
        return str(path)
    except Exception:  # noqa: BLE001 - a missing icon must not block the shortcut
        return ""


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def stop_command() -> tuple[str, str]:
    """Target and arguments of the shortcut that stops the app."""
    if getattr(sys, "frozen", False):
        return "taskkill.exe", "/IM FlowLocal.exe /F"
    script = PROJECT_ROOT / "scripts" / "stop_flow.ps1"
    return "powershell.exe", f'-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{script}"'


def refresh_shell_icons() -> bool:
    """Tell Explorer that icons changed, so shortcuts do not keep showing a stale generic icon."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32")
        shell32.SHChangeNotify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        shell32.SHChangeNotify(0x08000000, 0x1000, None, None)  # SHCNE_ASSOCCHANGED, SHCNF_FLUSH
        return True
    except (OSError, AttributeError):
        return False


def install_shortcuts(folder: Path | None = None, start_menu: Path | None = None) -> list[Path]:
    """Create 'Flow Local' (open) and 'Stop Flow Local' on the desktop, plus a Start-menu entry.

    Returns the paths. Pass folders to put them elsewhere (tests do).
    """
    folder = folder or desktop_dir()
    start_menu = start_menu or start_menu_dir()
    app_icon, stop_icon = ensure_icon("app"), ensure_icon("stop")
    exe, args = launch_parts(background=False)
    workdir = str(Path(exe).parent if getattr(sys, "frozen", False) else PROJECT_ROOT)
    desc = "Open Flow Local (starts it if it is not running)"
    open_lnk = create_shortcut(folder / OPEN_NAME, exe, args, workdir, app_icon, desc)
    stop_target, stop_args = stop_command()
    stop_lnk = create_shortcut(
        folder / STOP_NAME, stop_target, stop_args, workdir, stop_icon, "Stop Flow Local",
        minimized=True,
    )  # fmt: skip
    # a Start-menu entry makes the app findable with Windows search and pinnable to the taskbar
    menu_lnk = create_shortcut(start_menu / OPEN_NAME, exe, args, workdir, app_icon, desc)
    refresh_shell_icons()
    return [open_lnk, stop_lnk, menu_lnk]
