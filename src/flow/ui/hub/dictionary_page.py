"""Dictionary: names and jargon, optional spoken->written replacements, priority stars."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flow.store.history import suggest_words
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import (
    EmptyState,
    Panel,
    button,
    caption,
    page_header,
    section_title,
    style_table,
)
from flow.ui.theme import current_palette, notifier

STAR_ON, STAR_OFF = "★", "☆"


class EntryDialog(QDialog):
    def __init__(self, parent=None, written="", spoken="", starred=False) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setWindowTitle("Dictionary word")
        self.setMinimumWidth(420)
        self.written = QLineEdit(written)
        self.written.setPlaceholderText("e.g. Kubernetes, faster-whisper")
        self.spoken = QLineEdit(spoken or "")
        self.spoken.setPlaceholderText("Optional: how it sounds, e.g. cuber nettys")
        self.star = QCheckBox("Priority word (sent to the speech model first)")
        self.star.setChecked(starred)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.setVerticalSpacing(12)
        form.addRow("Word", self.written)
        form.addRow("Replace spoken form", self.spoken)
        form.addRow(self.star)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, str | None, bool]:
        return self.written.text(), self.spoken.text() or None, self.star.isChecked()


class DictionaryPage(QWidget):
    def __init__(self, ctx: HubContext) -> None:
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 12, 0)  # same right edge as the scrolling pages
        lay.setSpacing(16)
        lay.addWidget(
            page_header(
                "Dictionary",
                "Words the speech model should know. Starred words get priority. A spoken form is "
                "swapped for the written word, e.g. “cuber nettys” becomes “Kubernetes”.",
            )
        )
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search words")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.import_btn = button("Import", "ghost")
        self.import_btn.clicked.connect(self.import_file)
        self.export_btn = button("Export", "ghost")
        self.export_btn.clicked.connect(self.export_file)
        self.add_btn = button("Add word", "primary")
        self.add_btn.clicked.connect(self.add_dialog)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.import_btn)
        bar.addWidget(self.export_btn)
        bar.addWidget(self.add_btn)
        lay.addLayout(bar)

        panel = Panel()
        self.table = style_table(QTableWidget(0, 4))
        self.table.setHorizontalHeaderLabels(["", "Word", "Replaces spoken form", "Uses"])
        self.table.setMinimumHeight(220)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.edit_row(r))
        panel.add(self.table, padded=False)
        self.empty_add = button("Add your first word", "primary")
        self.empty_add.clicked.connect(self.add_dialog)
        self.empty_state = EmptyState(
            "dictionary",
            "Teach it your words",
            "Add names, places and technical terms so they are recognised and spelled the way "
            "you want.",
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

        self.suggest_label = section_title("Suggested words")
        lay.addWidget(self.suggest_label)
        self.suggest_help = caption("Terms you say often that are not in your dictionary yet.")
        lay.addWidget(self.suggest_help)
        self.suggestions = QListWidget()
        self.suggestions.setMaximumHeight(96)
        lay.addWidget(self.suggestions)
        self.add_suggestion_btn = button("Add selected suggestion")
        self.add_suggestion_btn.clicked.connect(self.add_selected_suggestion)
        lay.addWidget(self.add_suggestion_btn, 0, Qt.AlignmentFlag.AlignLeft)
        ctx.historyChanged.connect(self.refresh_suggestions)
        notifier.changed.connect(self.refresh)  # star colours follow the theme
        self.refresh()

    # -- data -----------------------------------------------------------------------------------
    def refresh(self) -> None:
        entries = self.ctx.dictionary.list(self.search.text())
        self.refresh_suggestions()
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            star = QTableWidgetItem(STAR_ON if e.starred else STAR_OFF)
            star.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pal = current_palette()
            star.setForeground(QBrush(QColor(pal.accent if e.starred else pal.muted)))
            star.setToolTip("Click to toggle priority")
            self.table.setItem(r, 0, star)
            word = QTableWidgetItem(e.written)
            if e.auto:
                word.setToolTip("Learned automatically. Delete it if it is wrong; it will not come back.")
                word.setForeground(QBrush(QColor(pal.muted)))
            self.table.setItem(r, 1, word)
            self.table.setItem(r, 2, QTableWidgetItem(e.spoken or ""))
            uses = QTableWidgetItem(str(e.uses))
            uses.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, uses)
        nothing = not self.ctx.dictionary.list()
        self.empty_state.setVisible(nothing)
        self.table.setVisible(not nothing)
        self.delete_btn.setEnabled(not nothing)

    def add_entry(self, written: str, spoken: str | None = None, starred: bool = False) -> None:
        self.ctx.dictionary.add(written, spoken, starred)
        self.refresh()

    def words(self) -> list[str]:
        return [self.table.item(r, 1).text() for r in range(self.table.rowCount())]

    def _word_at(self, row: int) -> str:
        return self.table.item(row, 1).text()

    def _cell_clicked(self, row: int, col: int) -> None:
        if col == 0:
            word = self._word_at(row)
            entry = self.ctx.dictionary.get(word)
            if entry:
                self.ctx.dictionary.set_starred(word, not entry.starred)
                self.refresh()

    def toggle_star(self, row: int) -> None:
        self._cell_clicked(row, 0)

    def delete_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.ctx.dictionary.delete(self._word_at(r))
        self.refresh()

    # -- dialogs --------------------------------------------------------------------------------
    def add_dialog(self) -> None:
        dlg = EntryDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.add_entry(*dlg.values())
            except ValueError:
                QMessageBox.warning(self, "Dictionary", "Please enter a word.")

    def edit_row(self, row: int) -> None:
        old = self.ctx.dictionary.get(self._word_at(row))
        if old is None:
            return
        dlg = EntryDialog(self, old.written, old.spoken or "", old.starred)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            written, spoken, starred = dlg.values()
            if written.casefold() != old.written.casefold():
                self.ctx.dictionary.delete(old.written)
            self.add_entry(written, spoken, starred)

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import dictionary", "", "Dictionary files (*.json *.csv)"
        )
        if not path:
            return
        try:
            ok, bad = self.ctx.dictionary.import_text(Path(path).read_text("utf-8"))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import failed", str(e))
            return
        self.refresh()
        QMessageBox.information(self, "Import", f"Imported {ok} word(s), skipped {bad}.")

    def export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export dictionary", "dictionary.json", "JSON (*.json);;CSV (*.csv)"
        )
        if not path:
            return
        d = self.ctx.dictionary
        text = d.export_csv() if path.lower().endswith(".csv") else d.export_json()
        Path(path).write_text(text, encoding="utf-8-sig")

    # -- suggestions ----------------------------------------------------------------------------
    def refresh_suggestions(self) -> None:
        known = {e.written.casefold() for e in self.ctx.dictionary.list()}
        found = suggest_words(self.ctx.history.all_finals(), known)
        self.suggestions.clear()
        for word, n in found:
            self.suggestions.addItem(f"{word}  ({n}x)")
            self.suggestions.item(self.suggestions.count() - 1).setData(Qt.ItemDataRole.UserRole, word)
        visible = bool(found)
        for w in (self.suggest_label, self.suggest_help, self.suggestions, self.add_suggestion_btn):
            w.setVisible(visible)

    def add_selected_suggestion(self) -> None:
        item = self.suggestions.currentItem()
        if item is not None:
            self.add_entry(item.data(Qt.ItemDataRole.UserRole))
