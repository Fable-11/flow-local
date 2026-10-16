import os
from pathlib import Path

# Qt tests must never open real windows on the user's desktop.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform finds no fonts by itself on Windows, which skews text widths.
if Path("C:/Windows/Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
