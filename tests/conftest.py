import os
from pathlib import Path

# Qt tests must never open real windows on the user's desktop.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform finds no fonts by itself on Windows, which skews text widths.
if Path("C:/Windows/Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_mixer(monkeypatch):
    """Tests must never mute the real programs on the desktop they run on."""
    from flow.audio import ducking

    monkeypatch.setattr(ducking.SystemSessions, "sessions", lambda self: [])
