import subprocess
import sys

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

from flow.ipc import notify_running_instance, start_ipc_server  # noqa: E402
from flow.ui import autostart  # noqa: E402


def test_launch_parts_background_flag():
    exe, with_flag = autostart.launch_parts(background=True)
    _, without = autostart.launch_parts(background=False)
    assert "--background" in with_flag and "--background" not in without
    assert "-m flow" in with_flag and exe.lower().endswith((".exe",))
    assert '--background' in autostart.launch_command()


def test_ipc_second_launch_asks_first_to_show(qtbot):
    shown = []
    name = "FlowLocalIPCTest"
    server = start_ipc_server(lambda: shown.append(1), name)
    assert server is not None
    # the second launch is a separate process, exactly like a desktop-shortcut click
    code = (
        "from PySide6.QtCore import QCoreApplication; import sys; app = QCoreApplication([]);"
        "from flow.ipc import notify_running_instance;"
        f"sys.exit(0 if notify_running_instance(3000, {name!r}) else 1)"
    )
    child = subprocess.Popen([sys.executable, "-c", code])
    qtbot.waitUntil(lambda: shown == [1], timeout=8000)
    assert child.wait(10) == 0  # and it got the acknowledgement
    server.close()


def test_ipc_without_running_instance_returns_false():
    assert notify_running_instance(300, "FlowLocalIPCNobodyHome") is False


def test_stop_command_targets_script_in_source_mode():
    from flow.ui.shortcuts import stop_command

    target, args = stop_command()
    assert target == "powershell.exe" and "stop_flow.ps1" in args


def test_create_and_read_shortcuts(tmp_path):
    from flow.ui.shortcuts import (
        OPEN_NAME,
        STOP_NAME,
        create_shortcut,
        install_shortcuts,
        read_shortcut,
    )

    lnk = create_shortcut(tmp_path / "x.lnk", r"C:\Windows\notepad.exe", "-a b", str(tmp_path))
    target, args = read_shortcut(lnk)
    assert (target.lower(), args) == (r"c:\windows\notepad.exe", "-a b")  # Windows may change case
    made = install_shortcuts(tmp_path / "desktop", tmp_path / "startmenu")
    assert [p.name for p in made] == [OPEN_NAME, STOP_NAME, OPEN_NAME]
    assert made[2].parent.name == "startmenu"  # findable with Windows search
    target, args = read_shortcut(made[0])
    assert target.lower().endswith(("pythonw.exe", "python.exe")) and "-m flow" in args
    assert "--background" not in args  # the desktop shortcut opens the window
    assert "stop_flow.ps1" in read_shortcut(made[1])[1]


def test_ico_is_multi_size_with_valid_png_entries():
    import struct

    pytest.importorskip("PySide6")
    from flow.ui.shortcuts import ICON_SIZES, ensure_icon

    for kind in ("app", "stop"):
        path = ensure_icon(kind)
        assert path
        data = open(path, "rb").read()
        reserved, kind_id, count = struct.unpack("<HHH", data[:6])
        assert (reserved, kind_id, count) == (0, 1, len(ICON_SIZES))
        for i in range(count):
            entry = data[6 + 16 * i : 22 + 16 * i]
            w, _h, _c, _r, _planes, _bits, size, offset = struct.unpack("<BBBBHHII", entry)
            real = w or 256
            assert real == ICON_SIZES[i]
            payload = data[offset : offset + size]
            if real >= 256:  # only the largest image is PNG-compressed
                assert payload[:8] == b"\x89PNG\r\n\x1a\n"
            else:  # smaller sizes are classic bitmaps that Explorer can always read
                hdr_size, bw, bh, planes, bits = struct.unpack("<IiiHH", payload[:16])
                assert (hdr_size, bw, bh, planes, bits) == (40, real, real * 2, 1, 32)
                assert len(payload) == 40 + real * real * 4 + ((real + 31) // 32) * 4 * real


def test_stop_icon_is_visibly_different_from_the_app_icon():
    pytest.importorskip("PySide6")
    from flow.ui.shortcuts import ensure_icon

    app, stop = ensure_icon("app"), ensure_icon("stop")
    assert app != stop and open(app, "rb").read() != open(stop, "rb").read()


def test_icon_colors_blue_for_app_red_for_stop():
    pytest.importorskip("PySide6")
    from flow.ui.tray import make_icon, make_stop_icon

    def corner_pixel(icon):
        img = icon.pixmap(64, 64).toImage()
        return img.pixelColor(10, 10)  # inside the rounded square, outside the white glyph

    blue, red = corner_pixel(make_icon()), corner_pixel(make_stop_icon())
    assert blue.blue() > blue.red() and red.red() > red.blue()


def test_refresh_shell_icons_runs_without_error():
    from flow.ui.shortcuts import refresh_shell_icons

    assert refresh_shell_icons() is True


def test_icon_files_are_versioned_so_explorer_does_not_show_a_stale_cache(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    from flow.ui.shortcuts import ICON_VERSION, ensure_icon

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    folder = tmp_path / "FlowLocal"
    folder.mkdir()
    (folder / "flow.ico").write_bytes(b"old, never displayed by Explorer")
    app, stop = ensure_icon("app"), ensure_icon("stop")
    assert app.endswith(f"flow-v{ICON_VERSION}.ico")
    assert stop.endswith(f"flow-stop-v{ICON_VERSION}.ico")
    assert not (folder / "flow.ico").exists()  # the old, cached path is gone
