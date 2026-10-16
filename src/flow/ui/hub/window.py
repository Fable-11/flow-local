"""The Hub: main window with a sidebar (brand, navigation, live status) and one page per area."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flow import __version__
from flow.ui import icons
from flow.ui.hub.context import HubContext
from flow.ui.hub.dictionary_page import DictionaryPage
from flow.ui.hub.home_page import HomePage
from flow.ui.hub.insights_page import InsightsPage
from flow.ui.hub.notes_page import NotesPage
from flow.ui.hub.settings_page import SettingsPage
from flow.ui.hub.snippets_page import SnippetsPage
from flow.ui.hub.style_page import StylePage
from flow.ui.hub.widgets import StatusDot, caption, set_role
from flow.ui.theme import current_palette, notifier
from flow.ui.tray import make_icon

PAGES = ["Home", "Insights", "Dictionary", "Snippets", "Style", "Notes", "Settings"]
NAV_ICONS = {
    "Home": "home",
    "Insights": "insights",
    "Dictionary": "dictionary",
    "Snippets": "snippets",
    "Style": "style",
    "Notes": "notes",
    "Settings": "settings",
}
SIDEBAR_WIDTH = 228
CONTENT_MAX_WIDTH = 900
_BUSY = ("listening", "working", "loading", "downloading")
_BAD = ("not downloaded", "could not", "unavailable", "stopped", "no microphone", "error", "broke")


def status_state(text: str) -> str:
    """Map a status sentence to a dot colour: ok, busy or error."""
    t = text.lower()
    if any(w in t for w in _BAD):
        return "error"
    if any(w in t for w in _BUSY):
        return "busy"
    return "ok"


class HubWindow(QMainWindow):
    closed = Signal()  # emitted when the window is destroyed on close (delete_on_close)

    def __init__(self, ctx: HubContext, delete_on_close: bool = False) -> None:
        super().__init__()
        self.ctx = ctx
        self._delete_on_close = delete_on_close
        self.setWindowTitle("Flow Local")
        self.setWindowIcon(make_icon())
        self.setMinimumSize(900, 600)
        self.resize(1060, 720)

        root = QWidget()
        root.setObjectName("Content")
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        self.pages: dict[str, QWidget] = {
            "Home": HomePage(ctx),
            "Insights": InsightsPage(ctx),
            "Dictionary": DictionaryPage(ctx),
            "Snippets": SnippetsPage(ctx),
            "Style": StylePage(ctx),
            "Notes": NotesPage(ctx),
            "Settings": SettingsPage(ctx),
        }
        for name in PAGES:
            self.stack.addWidget(self._center(self.pages[name]))
        row.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self._on_status(ctx.status or "Starting...")
        ctx.statusChanged.connect(self._on_status)
        notifier.changed.connect(self._refresh_icons)
        self._refresh_icons()

    # -- layout ---------------------------------------------------------------------------------
    @staticmethod
    def _center(page: QWidget) -> QWidget:
        """Content is a centred column: readable on wide monitors, full width on narrow ones."""
        holder = QWidget()
        holder.setObjectName("Page")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(36, 32, 36, 24)
        page.setMaximumWidth(CONTENT_MAX_WIDTH)
        lay.addStretch(1)
        lay.addWidget(page, 100)
        lay.addStretch(1)
        return holder

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(SIDEBAR_WIDTH)
        col = QVBoxLayout(side)
        col.setContentsMargins(14, 18, 14, 14)
        col.setSpacing(14)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(make_icon(64).pixmap(30, 30))
        logo.setFixedSize(30, 30)
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(set_role(QLabel("Flow Local"), "section"))
        names.addWidget(caption(f"Version {__version__}"))
        brand.addLayout(names)
        brand.addStretch(1)
        col.addLayout(brand)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.nav.setSpacing(1)
        for name in PAGES:
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(0, 38))
            self.nav.addItem(item)
        col.addWidget(self.nav, 1)

        status = QHBoxLayout()
        status.setContentsMargins(8, 0, 0, 0)
        status.setSpacing(8)
        self.dot = StatusDot()
        self.status_text = caption("Starting...")
        self.status_text.setWordWrap(True)
        status.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        status.addWidget(self.status_text, 1)
        col.addLayout(status)
        return side

    def _refresh_icons(self) -> None:
        p = current_palette()
        for i, name in enumerate(PAGES):
            self.nav.item(i).setIcon(icons.nav_icon(NAV_ICONS[name], p.muted, p.accent))

    def _on_status(self, text: str) -> None:
        if text:
            self.status_text.setText(text)
            self.dot.set_state(status_state(text))

    # -- API ------------------------------------------------------------------------------------
    def show_page(self, name: str) -> None:
        self.nav.setCurrentRow(PAGES.index(name))
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Closing the window hides it; the app keeps running in the tray."""
        self.pages["Notes"].flush()
        if self._delete_on_close:  # free the page widgets while the app idles in the tray
            event.accept()
            self.closed.emit()
            self.deleteLater()
            return
        event.ignore()
        self.hide()
