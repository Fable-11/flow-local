"""Style: tone presets, the user's own instructions, and per-app rules."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flow.cleanup.prompts import STYLES
from flow.config import STYLE_NAMES
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import (
    Panel,
    button,
    caption,
    muted,
    page_header,
    section_title,
    style_table,
)

EXAMPLES = {
    "default": "I think we should meet at 4 tomorrow.",
    "formal": "I believe we should schedule our meeting for 4 p.m. tomorrow.",
    "casual": "think we should meet at 4 tomorrow",
    "excited": "We should totally meet at 4 tomorrow!",
    "very_casual": "we should meet at 4 tmrw",
}


class StylePage(QWidget):
    def __init__(self, ctx: HubContext) -> None:
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(16)
        lay.addWidget(
            page_header("Style", "How your dictation should sound. Casual styles also skip the final period.")
        )

        # -- tone ----------------------------------------------------------------------------
        lay.addWidget(section_title("Tone"))
        tone = Panel()
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for key, label in STYLE_NAMES.items():
            row = QWidget()
            col = QVBoxLayout(row)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            radio = QRadioButton(label)
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self.radios[key] = radio
            self.group.addButton(radio)
            col.addWidget(radio)
            hint = caption(f"{STYLES[key]}  Example: “{EXAMPLES[key]}”")
            hint.setContentsMargins(24, 0, 0, 0)
            col.addWidget(hint)
            tone.add(row)
            radio.toggled.connect(lambda on, k=key: on and self._style_chosen(k))
        lay.addWidget(tone)

        # -- custom instructions -------------------------------------------------------------
        lay.addWidget(section_title("Your own instructions"))
        lay.addWidget(muted("Added to every cleanup request."))
        self.custom = QPlainTextEdit(ctx.settings.custom_instructions)
        self.custom.setPlaceholderText(
            "e.g. Use British spelling. Keep my sentences short. Never use exclamation marks."
        )
        self.custom.setFixedHeight(96)
        lay.addWidget(self.custom)
        self.save_btn = button("Save instructions", "primary")
        self.save_btn.clicked.connect(self.save_instructions)
        lay.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # -- per-app rules -------------------------------------------------------------------
        lay.addWidget(section_title("Per-app styles"))
        lay.addWidget(
            muted(
                "Chat apps use Casual and email apps use Formal unless you pick a tone above. Add a "
                "rule to force a tone in one app, using its process name (shown on the Home page)."
            )
        )
        add = QHBoxLayout()
        add.setSpacing(8)
        self.app_name = QLineEdit()
        self.app_name.setPlaceholderText("Process name, e.g. code.exe")
        self.app_style = QComboBox()
        for key, label in STYLE_NAMES.items():
            self.app_style.addItem(label, key)
        self.add_rule_btn = button("Add rule")
        self.add_rule_btn.clicked.connect(
            lambda: self.add_app_rule(self.app_name.text(), self.app_style.currentData())
        )
        add.addWidget(self.app_name, 1)
        add.addWidget(self.app_style)
        add.addWidget(self.add_rule_btn)
        lay.addLayout(add)
        rules_panel = Panel()
        self.rules = style_table(QTableWidget(0, 2), 38)
        self.rules.setHorizontalHeaderLabels(["App", "Style"])
        self.rules.setFixedHeight(150)
        self.rules.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        rules_panel.add(self.rules, padded=False)
        lay.addWidget(rules_panel)
        self.remove_rule_btn = button("Remove selected rule", "danger")
        self.remove_rule_btn.clicked.connect(self.remove_selected_rule)
        lay.addWidget(self.remove_rule_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        self.refresh_rules()
        self.select_style(ctx.settings.style, notify=False)

    def select_style(self, key: str, notify: bool = True) -> None:
        radio = self.radios.get(key, self.radios["default"])
        if not notify:
            radio.blockSignals(True)
        radio.setChecked(True)
        radio.blockSignals(False)

    def _style_chosen(self, key: str) -> None:
        if key != self.ctx.settings.style:
            self.ctx.update(style=key)

    def save_instructions(self) -> None:
        self.ctx.update(custom_instructions=self.custom.toPlainText().strip())

    # -- per-app rules --------------------------------------------------------------------------
    def refresh_rules(self) -> None:
        rules = sorted(self.ctx.settings.app_styles.items())
        self.rules.setRowCount(len(rules))
        for r, (proc, style) in enumerate(rules):
            self.rules.setItem(r, 0, QTableWidgetItem(proc))
            self.rules.setItem(r, 1, QTableWidgetItem(STYLE_NAMES.get(style, style)))

    def add_app_rule(self, process: str, style: str) -> bool:
        proc = process.strip().lower()
        if not proc or style not in STYLE_NAMES:
            return False
        if not proc.endswith(".exe"):
            proc += ".exe"
        self.ctx.update(app_styles={**self.ctx.settings.app_styles, proc: style})
        self.app_name.clear()
        self.refresh_rules()
        return True

    def remove_selected_rule(self) -> None:
        rows = sorted({i.row() for i in self.rules.selectedIndexes()})
        rules = dict(self.ctx.settings.app_styles)
        for r in rows:
            rules.pop(self.rules.item(r, 0).text(), None)
        self.ctx.update(app_styles=rules)
        self.refresh_rules()

