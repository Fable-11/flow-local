"""Write packaging/flow.ico from the same artwork the tray icon uses."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

from flow.ui.tray import make_icon  # noqa: E402

app = QGuiApplication(sys.argv)
out = Path(__file__).with_name("flow.ico")
pixmap = make_icon(256).pixmap(256, 256)
if not pixmap.save(str(out), "ICO"):
    raise SystemExit("could not write the icon (Qt ICO plugin missing?)")
print("wrote", out)
