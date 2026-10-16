"""Snippets: say a trigger phrase, get a saved block of text."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import EmptyState, Panel, button, page_header, style_table


class SnippetDialog(QDialog):
    def __init__(self, parent=None, trigger="", content="", anywhere=False) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setWindowTitle("Snippet")
        self.setMinimumSize(460, 360)
        self.trigger = QLineEdit(trigger)
        self.trigger.setPlaceholderText("What you say, e.g. my email")
        self.content = QPlainTextEdit(content)
        self.content.setPlaceholderText("The text that is inserted")
        self.anywhere = QCheckBox("Also expand inside longer sentences")
        self.anywhere.setChecked(anywhere)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.setVerticalSpacing(12)
        form.addRow("Trigger phrase", self.trigger)
        form.addRow("Inserted text", self.content)
        form.addRow(self.anywhere)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, str, bool]:
        return self.trigger.text(), self.content.toPlainText(), self.anywhere.isChecked()


class SnippetsPage(QWidget):
    def __init__(self, ctx: HubContext) -> None:
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 12, 0)  # same right edge as the scrolling pages
        lay.setSpacing(16)
        lay.addWidget(
            page_header(
                "Snippets",
                "Say a trigger phrase on its own and the saved text is inserted exactly as written, "
                "with no cleanup. Turn on expansion inside sentences only for phrases you never "
                "say by accident.",
            )
        )
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search snippets")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.add_btn = button("Add snippet", "primary")
        self.add_btn.clicked.connect(self.add_dialog)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.add_btn)
        lay.addLayout(bar)

        panel = Panel()
        self.table = style_table(QTableWidget(0, 3))
        self.table.setHorizontalHeaderLabels(["Trigger", "Text", "In sentences"])
        self.table.setMinimumHeight(220)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.edit_row(r))
        panel.add(self.table, padded=False)
        self.empty_add = button("Add your first snippet", "primary")
        self.empty_add.clicked.connect(self.add_dialog)
        self.empty_state = EmptyState(
            "snippets",
            "Save text you type again and again",
            "Your email, address, a sign-off or a link: say a short phrase and the full text is "
            "inserted exactly as you saved it.",
            self.empty_add,
        )
        panel.add(self.empty_state, padded=False)
        lay.addWidget(panel, 1)

        self.delete_btn = button("Delete selected", "danger")
        self.delete_btn.clicked.connect(self.delete_selected)
        row = QHBoxLayout()
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        items = self.ctx.snippets.list(self.search.text())
        self.table.setRowCount(len(items))
        for r, s in enumerate(items):
            preview = " ↵ ".join(s.content.splitlines())[:120]
            self.table.setItem(r, 0, QTableWidgetItem(s.trigger))
            self.table.setItem(r, 1, QTableWidgetItem(preview))
            self.table.setItem(r, 2, QTableWidgetItem("Yes" if s.anywhere else ""))
        nothing = not self.ctx.snippets.list()
        self.empty_state.setVisible(nothing)
        self.table.setVisible(not nothing)
        self.delete_btn.setEnabled(not nothing)

    def add_snippet(self, trigger: str, content: str, anywhere: bool = False) -> None:
        self.ctx.snippets.add(trigger, content, anywhere)
        self.refresh()

    def triggers(self) -> list[str]:
        return [self.table.item(r, 0).text() for r in range(self.table.rowCount())]

    def delete_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.ctx.snippets.delete(self.table.item(r, 0).text())
        self.refresh()

    def add_dialog(self) -> None:
        dlg = SnippetDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.add_snippet(*dlg.values())
            except ValueError:
                QMessageBox.warning(self, "Snippets", "Enter a trigger phrase and some text.")

    def edit_row(self, row: int) -> None:
        old = self.ctx.snippets.get(self.table.item(row, 0).text())
        if old is None:
            return
        dlg = SnippetDialog(self, old.trigger, old.content, old.anywhere)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            trigger, content, anywhere = dlg.values()
            try:
                if trigger.casefold() != old.trigger.casefold():
                    self.ctx.snippets.delete(old.trigger)
                self.add_snippet(trigger, content, anywhere)
            except ValueError:
                QMessageBox.warning(self, "Snippets", "Enter a trigger phrase and some text.")
