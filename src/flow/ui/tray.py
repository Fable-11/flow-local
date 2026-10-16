"""System tray icon (original artwork drawn in code, no external assets)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon(size: int = 64) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(37, 99, 235))
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.24, size * 0.24)
    p.setBrush(QColor(255, 255, 255))
    heights = (0.22, 0.42, 0.6, 0.38, 0.2)
    bw, gap = size * 0.1, size * 0.065
    x = (size - (5 * bw + 4 * gap)) / 2
    for h in heights:
        bh = size * h
        p.drawRoundedRect(QRectF(x, (size - bh) / 2, bw, bh), bw / 2, bw / 2)
        x += bw + gap
    p.end()
    return QIcon(pm)


class Tray(QObject):
    pause_toggled = Signal(bool)  # True = paused

    def __init__(self, on_quit: Callable[[], None], show_page: Callable[[str], None]) -> None:
        super().__init__()
        self.icon = QSystemTrayIcon(make_icon())
        self.icon.setToolTip("Flow Local: hold Ctrl+Win to dictate")
        self.menu = QMenu()
        self.open_action = QAction("Open Flow Local")
        self.open_action.triggered.connect(lambda: show_page("Home"))
        self.settings_action = QAction("Settings")
        self.settings_action.triggered.connect(lambda: show_page("Settings"))
        self.pause_action = QAction("Pause dictation")
        self.pause_action.setCheckable(True)
        self.pause_action.toggled.connect(self._paused)
        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(on_quit)
        for a in (self.open_action, self.settings_action, self.pause_action):
            self.menu.addAction(a)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(
            lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and show_page("Home")
        )
        self.icon.show()

    def _paused(self, paused: bool) -> None:
        self.pause_action.setText("Resume dictation" if paused else "Pause dictation")
        self.icon.setToolTip("Flow Local (paused)" if paused else "Flow Local: hold Ctrl+Win to dictate")
        self.pause_toggled.emit(paused)


def make_stop_icon(size: int = 64) -> QIcon:
    """Red rounded square with a white 'stop' square: used for the Stop shortcut."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(220, 38, 38))
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.24, size * 0.24)
    p.setBrush(QColor(255, 255, 255))
    s = size * 0.34
    p.drawRoundedRect(QRectF((size - s) / 2, (size - s) / 2, s, s), size * 0.06, size * 0.06)
    p.end()
    return QIcon(pm)
