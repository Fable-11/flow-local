"""Home: what the app is doing right now, the shortcuts, and recent dictations."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flow.cleanup.rules import clean_rules
from flow.config import BINDING_LABELS
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import (
    EmptyState,
    KeyCaps,
    Panel,
    StatusDot,
    button,
    page_header,
    scrollable,
    section_title,
    set_role,
    style_table,
)

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
        lay.setSpacing(20)
        lay.addWidget(page_header("Home", "Dictate in any app: hold your shortcut, speak, let go."))

        # -- live status -------------------------------------------------------------------
        status_panel = Panel()
        row = QWidget()
        status_row = QHBoxLayout(row)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(12)
        self.dot = StatusDot(12)
        self.status = set_role(QLabel(ctx.status or "Starting..."), "section")
        self.status.setWordWrap(True)
        status_row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        status_row.addWidget(self.status, 1)
        status_panel.add(row)
        lay.addWidget(status_panel)

        # -- shortcuts ---------------------------------------------------------------------
        lay.addWidget(section_title("Shortcuts"))
        self.shortcut_panel = Panel()
        self._caps: dict[str, KeyCaps] = {}
        for name, label in BINDING_LABELS.items():
            caps = KeyCaps("")
            self._caps[name] = caps
            self.shortcut_panel.add_row(label, control=caps)
        esc = KeyCaps("esc")
        self.shortcut_panel.add_row("Cancel", "Discards what you said, nothing is inserted.", esc)
        lay.addWidget(self.shortcut_panel)

        # -- recent dictations ---------------------------------------------------------------
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
        ctx.settingsChanged.connect(self._settings_changed)
        ctx.historyChanged.connect(self.refresh)
        self._set_status(ctx.status)
        self.refresh_shortcuts()
        self.refresh()

    # -- status ---------------------------------------------------------------------------------
    def _set_status(self, text: str) -> None:
        from flow.ui.hub.window import status_state

        if text:
            self.status.setText(text)
            self.dot.set_state(status_state(text))

    def _settings_changed(self, _settings) -> None:  # noqa: ANN001
        self.refresh_shortcuts()

    def refresh_shortcuts(self) -> None:
        for name, caps in self._caps.items():
            caps.set_chord(self.ctx.settings.bindings[name])

    # -- history --------------------------------------------------------------------------------
    def refresh(self) -> None:
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

