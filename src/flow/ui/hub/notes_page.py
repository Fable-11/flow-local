"""Notes: a scratch pad you can dictate straight into (click in a note, then use the shortcut)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import Panel, button, page_header, section_title

ID_ROLE = Qt.ItemDataRole.UserRole
AUTOSAVE_MS = 600


class NotesPage(QWidget):
    def __init__(self, ctx: HubContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._current: int | None = None
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 12, 0)  # same right edge as the scrolling pages
        lay.setSpacing(16)
        lay.addWidget(
            page_header("Notes", "Click into a note and dictate with your shortcut. Notes save automatically.")
        )

        panel = Panel()
        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(250)
        col = QVBoxLayout(left)
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(section_title("Your notes"), 1)
        self.new_btn = button("New", "primary")
        self.new_btn.clicked.connect(self.new_note)
        head.addWidget(self.new_btn)
        col.addLayout(head)
        self.listing = QListWidget()
        self.listing.currentItemChanged.connect(self._selected)
        col.addWidget(self.listing, 1)
        self.delete_btn = button("Delete note", "danger")
        self.delete_btn.clicked.connect(self.delete_note)
        col.addWidget(self.delete_btn)
        row.addWidget(left)

        divider = QFrame()
        divider.setObjectName("VDivider")
        row.addWidget(divider)

        self.editor = QPlainTextEdit()
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setObjectName("NoteEditor")
        self.editor.setPlaceholderText("Start typing, or hold your dictation shortcut and speak...")
        opt = self.editor.document().defaultTextOption()
        opt.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)  # Arabic lines flow right to left
        self.editor.document().setDefaultTextOption(opt)
        self.editor.textChanged.connect(self._changed)
        row.addWidget(self.editor, 1)
        panel.add(body, padded=False)
        panel.setMinimumHeight(380)
        lay.addWidget(panel, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self.flush)
        self.reload()

    # -- list -----------------------------------------------------------------------------------
    def reload(self, select_id: int | None = None) -> None:
        notes = self.ctx.notes.list()
        self._loading = True
        self.listing.clear()
        for n in notes:
            item = QListWidgetItem(n.title)
            item.setData(ID_ROLE, n.id)
            self.listing.addItem(item)
        self._loading = False
        target = select_id or (notes[0].id if notes else None)
        for i in range(self.listing.count()):
            if self.listing.item(i).data(ID_ROLE) == target:
                self.listing.setCurrentRow(i)
                return
        self._current = None
        self._set_text("")
        self.editor.setEnabled(bool(notes))
        self.delete_btn.setEnabled(bool(notes))

    def _selected(self, item: QListWidgetItem | None, _prev=None) -> None:  # noqa: ANN001
        if self._loading:
            return
        self.flush()
        if item is None:
            return
        self._current = int(item.data(ID_ROLE))
        note = self.ctx.notes.get(self._current)
        self.editor.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self._set_text(note.body if note else "")

    def _set_text(self, text: str) -> None:
        self._loading = True
        self.editor.setPlainText(text)
        self._loading = False

    # -- editing --------------------------------------------------------------------------------
    def _changed(self) -> None:
        if not self._loading and self._current is not None:
            self._timer.start()

    def flush(self) -> None:
        """Save the open note now (also called before switching notes and on close)."""
        self._timer.stop()
        if self._current is None:
            return
        body = self.editor.toPlainText()
        note = self.ctx.notes.get(self._current)
        if note is not None and note.body != body:
            self.ctx.notes.update(self._current, body)
            item = self.listing.currentItem()
            if item is not None:
                item.setText(self.ctx.notes.get(self._current).title)

    def new_note(self) -> None:
        self.flush()
        note = self.ctx.notes.create("")
        self.reload(note.id)
        self.editor.setFocus()

    def delete_note(self) -> None:
        if self._current is not None:
            self._timer.stop()
            self.ctx.notes.delete(self._current)
            self._current = None
            self.reload()
