from __future__ import annotations

from pathlib import PureWindowsPath

from flow.__main__ import shorten_home


def test_home_folder_is_hidden_in_pasted_reports():
    from pathlib import Path

    home = str(Path.home())
    assert shorten_home(home + "\\AppData\\Local\\FlowLocal\\flow.db") == (
        "~\\AppData\\Local\\FlowLocal\\flow.db"
    )
    assert shorten_home(home.upper() + "\\x") == "~\\x"  # case does not matter on Windows
    assert shorten_home("Z:\\elsewhere\\flow.db") == "Z:\\elsewhere\\flow.db"  # other places stay
    assert PureWindowsPath(shorten_home(Path.home() / "a.db")).parts[0] == "~"
