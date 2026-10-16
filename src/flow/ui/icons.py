"""Small outline icons drawn from simple geometric SVG paths (original artwork), recoloured to
the current theme at render time."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 24 x 24 grid, stroke only
PATHS: dict[str, str] = {
    "home": "M4 11 12 4l8 7M6 10v9a1 1 0 0 0 1 1h3.5v-5h3v5H17a1 1 0 0 0 1-1v-9",
    "insights": "M5 20V11M12 20V5M19 20v-6",
    "dictionary": "M6 4h10a2 2 0 0 1 2 2v13H8a2 2 0 0 1-2-2zM6 17a2 2 0 0 1 2-2h10M10 8h4",
    "snippets": "M13 3 5 13h6l-1 8 8-10h-6z",
    "style": "M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6zM18.5 16l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z",
    "notes": "M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v4h4M9 12h6M9 16h4",
    "settings": "M5 8h9M18 8h1M5 16h1M10 16h9M14 6v4M6 14v4",
    "mic": "M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3zM6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v3M9 20h6",
    "search": "M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM16 16l4 4",
    "plus": "M12 5v14M5 12h14",
    "check": "M5 12.5 10 17.5 19 7",
}


def _svg(name: str, color: str, stroke: float) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="{PATHS[name]}"/></svg>'
    ).encode()


def pixmap(name: str, color: str, size: int = 20, stroke: float = 1.8, dpr: float = 2.0) -> QPixmap:
    """Render an icon crisp at ``size`` logical pixels (``dpr`` times the pixels underneath)."""
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    QSvgRenderer(QByteArray(_svg(name, color, stroke))).render(painter)
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def nav_icon(name: str, normal: str, selected: str, size: int = 20) -> QIcon:
    """An icon with a different colour when its list item is selected."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, normal, size), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, selected, size), QIcon.Mode.Selected, QIcon.State.Off)
    ic.addPixmap(pixmap(name, selected, size), QIcon.Mode.Selected, QIcon.State.On)
    return ic
