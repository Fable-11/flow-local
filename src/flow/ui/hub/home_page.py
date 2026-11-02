"""Home: what the app is doing right now, the shortcuts, and recent dictations."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flow.cleanup.rules import clean_rules
from flow.config import BINDING_LABELS
from flow.insert.fit import has_arabic
from flow.store.history import compute_today
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import (
    EmptyState,
    KeyCaps,
    Panel,
    StatusDot,
    button,
    caption,
    page_header,
    scrollable,
    section_title,
    set_role,
    style_table,
)
from flow.ui.kit import StatTile, VoiceTrace

ID_ROLE = Qt.ItemDataRole.UserRole


def format_time(ts: datetime, today: date | None = None) -> str:
    today = today or date.today()
    if ts.date() == today:
        return ts.strftime("%H:%M")
    return ts.strftime("%b %d, %H:%M")


class HomePage(QWidget):
    def __init__(self, ctx: HubContext) -> None:
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setObjectName("Page")
        outer.addWidget(scrollable(inner))
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(16)
        lay.addWidget(page_header("Home", "Dictate in any app: hold your shortcut, speak, let go."))

        # -- hero: what is happening now, today in numbers, and the last thing you said ----------
        hero = QFrame()
        hero.setObjectName("Hero")
        hero_lay = QVBoxLayout(hero)
        hero_lay.setContentsMargins(24, 24, 24, 24)
        hero_lay.setSpacing(20)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.dot = StatusDot(12)
        self.status = set_role(QLabel(ctx.status or "Starting..."), "hero")
        self.status.setWordWrap(True)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.status, 1)
        hero_lay.addLayout(row)
        self.ai_row = QWidget()
        ai_lay = QHBoxLayout(self.ai_row)
        ai_lay.setContentsMargins(24, 0, 0, 0)
        ai_lay.setSpacing(12)
        self.ai_label = caption("")
        self.ai_label.setWordWrap(True)
        self.ai_button = button("Start Ollama")
        self.ai_button.clicked.connect(self._start_ollama)
        ai_lay.addWidget(self.ai_label, 1)
        ai_lay.addWidget(self.ai_button, 0, Qt.AlignmentFlag.AlignVCenter)
        hero_lay.addWidget(self.ai_row)
        # the row only exists while there is something to say or a button to show
        self._ai_parts = [self.ai_row]

        tiles = QHBoxLayout()
        tiles.setSpacing(32)
        self.today = {
            "words": StatTile("Words today"),
            "dictations": StatTile("Dictations today"),
            "saved": StatTile("Typing time saved today"),
        }
        for tile in self.today.values():
            tiles.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)
        tiles.addStretch(1)
        hero_lay.addLayout(tiles)

        self.last_box = QWidget()
        last = QVBoxLayout(self.last_box)
        last.setContentsMargins(0, 0, 0, 0)
        last.setSpacing(8)
        last.addWidget(caption("Last dictation"))
        self.trace = VoiceTrace(36)
        last.addWidget(self.trace)
        self.last_text = set_role(QLabel(""), "muted")
        self.last_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        last.addWidget(self.last_text)
        hero_lay.addWidget(self.last_box)
        lay.addWidget(hero)

        # -- shortcuts: two quiet columns of keys -------------------------------------------
        lay.addSpacing(8)
        lay.addWidget(section_title("Shortcuts"))
        self.shortcut_panel = QFrame()
        self.shortcut_panel.setObjectName("Card")
        grid = QGridLayout(self.shortcut_panel)
        grid.setContentsMargins(20, 16, 20, 16)
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(12)
        self._caps: dict[str, KeyCaps] = {}
        entries = [(name, label) for name, label in BINDING_LABELS.items()] + [("cancel", "Cancel")]
        for i, (name, label) in enumerate(entries):
            caps = KeyCaps("esc" if name == "cancel" else "")
            if name != "cancel":
                self._caps[name] = caps
            cell = QHBoxLayout()
            cell.setSpacing(12)
            cell.addWidget(QLabel(label), 1)
            cell.addWidget(caps)
            grid.addLayout(cell, i // 2, i % 2)
        lay.addWidget(self.shortcut_panel)

        # -- recent dictations ---------------------------------------------------------------
        lay.addSpacing(8)
        head = QHBoxLayout()
        head.addWidget(section_title("Recent dictations"), 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search dictations")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.refresh)
        head.addWidget(self.search)
        lay.addLayout(head)

        self.history_panel = Panel()
        self.table = style_table(QTableWidget(0, 3), 42)
        self.table.setHorizontalHeaderLabels(["Time", "App", "Text"])
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(260)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_panel.add(self.table, padded=False)
        self.empty_note = EmptyState(
            "mic",
            "No dictations yet",
            "Click into any text box, hold your shortcut and start talking. Each dictation "
            "appears here so you can copy it or run the cleanup again.",
        )
        self.history_panel.add(self.empty_note, padded=False)
        lay.addWidget(self.history_panel, 1)

        self.copy_btn = button("Copy")
        self.copy_btn.clicked.connect(self.copy_selected)
        self.rerun_btn = button("Re-run cleanup")
        self.rerun_btn.clicked.connect(self.rerun_selected)
        self.delete_btn = button("Delete", "danger")
        self.delete_btn.clicked.connect(self.delete_selected)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for b in (self.copy_btn, self.rerun_btn, self.delete_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)

        ctx.statusChanged.connect(self._set_status)
        ctx.aiStatusChanged.connect(self._set_ai_status)
        self._set_ai_status(*ctx.ai_status)
        ctx.settingsChanged.connect(self._settings_changed)
        ctx.historyChanged.connect(self.refresh)
        ctx.lastTraceChanged.connect(self._set_trace)
        self._set_status(ctx.status)
        self._set_trace(ctx.last_trace)
        self.refresh_shortcuts()
        self.refresh()

    # -- status ---------------------------------------------------------------------------------
    def _set_status(self, text: str) -> None:
        from flow.ui.hub.window import status_state

        if text:
            self.status.setText(text)
            self.dot.set_state(status_state(text))

    def _set_ai_status(self, _code: str, text: str, can_start: bool) -> None:
        self.ai_label.setText(text)
        self.ai_label.setVisible(bool(text))
        self.ai_button.setVisible(can_start)
        self.ai_button.setEnabled(True)
        for part in self._ai_parts:
            part.setVisible(bool(text) or can_start)

    def _set_trace(self, levels: list[float]) -> None:
        self.trace.set_levels(levels)
        self.trace.setVisible(bool(levels))

    def _refresh_today(self) -> None:
        from flow.ui.hub.insights_page import format_duration

        today = compute_today(self.ctx.dictionary.db)
        self.today["words"].set(f"{today.words:,}")
        self.today["dictations"].set(f"{today.dictations:,}")
        self.today["saved"].set(format_duration(today.time_saved_s))
        newest = self.ctx.history.recent(1)
        text = " ".join(newest[0].final.split()) if newest else ""
        self.last_text.setText(text)
        self.last_text.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if has_arabic(text[:40]) else Qt.LayoutDirection.LeftToRight
        )
        self.last_box.setVisible(bool(text))

    def _start_ollama(self) -> None:
        self.ai_button.setEnabled(False)  # one press; the status line updates by itself
        self.ctx.startOllamaRequested.emit()

    def _settings_changed(self, _settings) -> None:  # noqa: ANN001
        self.refresh_shortcuts()

    def refresh_shortcuts(self) -> None:
        for name, caps in self._caps.items():
            caps.set_chord(self.ctx.settings.bindings[name])

    # -- history --------------------------------------------------------------------------------
    def refresh(self) -> None:
        self._refresh_today()
        items = self.ctx.history.recent(100, self.search.text())
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            app = it.app.removesuffix(".exe") if it.app else ""
            label = {"command": "Command: ", "snippet": "Snippet: "}.get(it.kind, "")
            cells = (format_time(it.created_at), app, label + " ".join(it.final.splitlines()))
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setData(ID_ROLE, it.id)
                cell.setToolTip(it.final)
                if c == 2 and has_arabic(text[:40]):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, cell)
        empty = not items
        searching = bool(self.search.text())
        self.empty_note.setVisible(empty and not searching)
        self.table.setVisible(not empty or searching)
        for b in (self.copy_btn, self.rerun_btn, self.delete_btn):
            b.setEnabled(not empty)

    def selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return int(self.table.item(rows[0].row(), 0).data(ID_ROLE))

    def copy_selected(self) -> None:
        item = self.ctx.history.get(self.selected_id() or -1)
        if item:
            QApplication.clipboard().setText(item.final)

    def rerun_selected(self) -> str | None:
        item = self.ctx.history.get(self.selected_id() or -1)
        if not item:
            return None
        fn = self.ctx.rerun_cleanup or clean_rules
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            new = fn(item.raw)
        finally:
            QApplication.restoreOverrideCursor()
        if new:
            self.ctx.history.update_final(item.id, new)
            self.refresh()
        return new

    def delete_selected(self) -> None:
        item_id = self.selected_id()
        if item_id is not None:
            self.ctx.history.delete(item_id)
            self.ctx.historyChanged.emit()

    def confirm_clear(self) -> None:
        reply = QMessageBox.question(
            self, "Delete history", "Delete all saved dictations? This cannot be undone."
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.ctx.history.clear()
            self.ctx.historyChanged.emit()

