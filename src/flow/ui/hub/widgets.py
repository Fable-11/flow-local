"""Shared building blocks for the Hub pages. All colour and type come from ``flow.ui.theme``."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from flow.ui import icons
from flow.ui.theme import current_palette, notifier


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_role(label: QLabel, role: str) -> QLabel:
    """Typographic role: title, section, strong, muted, caption, error, stat."""
    label.setProperty("role", role)
    repolish(label)
    return label


def soften(label: QLabel) -> QLabel:
    return set_role(label, "muted")


def scrollable(inner: QWidget) -> QScrollArea:
    """Wrap a page in a vertical scroll area so rows never get squashed on a short window."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(inner)
    return scroll


def style_table(table: QTableWidget, row_height: int = 40) -> QTableWidget:
    """One look for every table: no grid, left-aligned headers, comfortable rows."""
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.setShowGrid(False)
    table.setFrameShape(QFrame.Shape.NoFrame)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setStretchLastSection(False)
    return table


def button(text: str, variant: str = "secondary") -> QPushButton:
    """A button in the app's vocabulary: secondary (default), primary, ghost or danger."""
    b = QPushButton(text)
    b.setProperty("variant", variant)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def page_header(title: str, subtitle: str = "") -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(set_role(QLabel(title), "title"))
    if subtitle:
        s = QLabel(subtitle)
        s.setWordWrap(True)
        s.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(set_role(s, "muted"))
    return box


def section_title(text: str) -> QLabel:
    return set_role(QLabel(text), "section")


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    # wrapped text shrinks with the window instead of forcing a horizontal scrollbar
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return set_role(label, "muted")


def caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return set_role(label, "caption")


def hbox(*widgets: QWidget, stretch_last: bool = False, spacing: int = 8) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    if stretch_last:
        lay.addStretch(1)
    return lay


# -- panel with rows --------------------------------------------------------------------------------
class Panel(QFrame):
    """One bordered surface. Rows inside are separated by hairlines, never nested panels."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._rows = 0

    def add(self, widget: QWidget, padded: bool = True) -> QWidget:
        if self._rows:
            divider = QFrame()
            divider.setObjectName("Divider")
            self._lay.addWidget(divider)
        if padded:
            holder = QWidget()
            inner = QVBoxLayout(holder)
            inner.setContentsMargins(16, 12, 16, 12)
            inner.addWidget(widget)
            self._lay.addWidget(holder)
        else:
            self._lay.addWidget(widget)
        self._rows += 1
        return widget

    def add_row(self, title: str, description: str = "", control: QWidget | None = None) -> SettingRow:
        row = SettingRow(title, description, control)
        self.add(row)
        return row


class SettingRow(QWidget):
    """Title and optional description on the left, the control on the right."""

    def __init__(self, title: str, description: str = "", control: QWidget | QHBoxLayout | None = None):
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = set_role(QLabel(title), "strong")
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        text.addWidget(self.title)
        self.description = None
        if description:
            self.description = caption(description)
            text.addWidget(self.description)
        outer.addLayout(text, 1)
        self.control = control
        if isinstance(control, QHBoxLayout):
            outer.addLayout(control)
        elif control is not None:
            outer.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


# -- toggle switch ----------------------------------------------------------------------------------
class Toggle(QCheckBox):
    """A switch. Keeps the QCheckBox API (isChecked, setChecked, toggled), so it is a drop-in."""

    W, H = 40, 22

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)
        notifier.changed.connect(self.update)

    def _set_pos(self, v) -> None:  # noqa: ANN001
        self._pos = float(v)
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt naming
        super().setChecked(checked)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0  # programmatic changes (loading settings) do not animate

    def sizeHint(self) -> QSize:  # noqa: N802
        text_w = QFontMetrics(self.font()).horizontalAdvance(self.text()) + 12 if self.text() else 0
        return QSize(text_w + self.W + 4, max(self.H + 6, 28))

    def hitButton(self, pos) -> bool:  # noqa: ANN001, N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        p = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = self.width() - self.W - 2
        y = (self.height() - self.H) / 2
        track = QRectF(x, y, self.W, self.H)
        if self.text():
            painter.setPen(QColor(p.text if self.isEnabled() else p.muted))
            painter.drawText(
                QRectF(0, 0, x - 8, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self.text(),
            )
        off, on = QColor(p.border_strong), QColor(p.accent)
        t = self._pos
        color = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        if not self.isEnabled():
            color.setAlphaF(0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, self.H / 2, self.H / 2)
        knob_d = self.H - 6
        knob_x = x + 3 + (self.W - knob_d - 6) * t
        painter.setBrush(QColor(p.knob))
        painter.drawEllipse(QRectF(knob_x, y + 3, knob_d, knob_d))
        if self.hasFocus():  # visible keyboard focus
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(p.accent), 2))
            painter.drawRoundedRect(track.adjusted(-3, -3, 3, 3), self.H / 2 + 3, self.H / 2 + 3)


# -- key caps for shortcuts --------------------------------------------------------------------------
_KEY_LABELS = {"ctrl": "Ctrl", "win": "Win", "alt": "Alt", "shift": "Shift", "space": "Space", "esc": "Esc"}


def key_label(key: str) -> str:
    if key.startswith("mouse_"):
        return "Mouse " + key[6:].upper()
    return _KEY_LABELS.get(key, key.upper() if len(key) == 1 else key.capitalize())


class KeyCaps(QWidget):
    """A shortcut drawn as little keyboard keys: Ctrl  Win  Space."""

    def __init__(self, chord: str = "") -> None:
        super().__init__()
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self.set_chord(chord)

    def set_chord(self, chord: str) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for key in [k for k in chord.split("+") if k]:
            cap = QFrame()
            cap.setObjectName("KeyCap")
            cap.setMinimumHeight(26)
            inner = QHBoxLayout(cap)
            inner.setContentsMargins(9, 0, 9, 0)
            text = QLabel(key_label(key))
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inner.addWidget(text)
            self._lay.addWidget(cap)
        self._lay.addStretch(1)


# -- status dot and empty state --------------------------------------------------------------------
class StatusDot(QWidget):
    """A small filled circle whose colour reflects a state (ok, busy, error, idle)."""

    COLORS = {"ok": "success", "busy": "accent", "error": "danger", "idle": "muted"}

    def __init__(self, size: int = 10) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._state = "idle"
        notifier.changed.connect(self.update)

    def set_state(self, state: str) -> None:
        self._state = state if state in self.COLORS else "idle"
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(getattr(current_palette(), self.COLORS[self._state])))
        painter.drawEllipse(self.rect())


class IconLabel(QLabel):
    """A theme-coloured outline icon."""

    def __init__(self, name: str, size: int = 20, color_role: str = "muted") -> None:
        super().__init__()
        self._name, self._size, self._role = name, size, color_role
        self.setFixedSize(size, size)
        notifier.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        color = getattr(current_palette(), self._role)
        self.setPixmap(icons.pixmap(self._name, color, self._size))


class EmptyState(QWidget):
    """Teaches what the page is for and what to do next, instead of saying 'nothing here'."""

    def __init__(self, icon_name: str, title: str, text: str, action: QPushButton | None = None) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 36, 24, 36)
        lay.setSpacing(8)
        lay.addStretch(1)
        lay.addWidget(IconLabel(icon_name, 28), 0, Qt.AlignmentFlag.AlignHCenter)
        t = set_role(QLabel(title), "strong")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        body = muted(text)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setMaximumWidth(420)
        lay.addWidget(body, 0, Qt.AlignmentFlag.AlignHCenter)
        if action is not None:
            lay.addSpacing(6)
            lay.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self.action = action


def centered_note(text: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return set_role(label, "muted")
