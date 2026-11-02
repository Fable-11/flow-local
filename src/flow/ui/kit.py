"""Painted building blocks for the redesigned interface: the voice trace, stat tiles, the week
chart and the one motion helper. All colours come from ``flow.ui.theme``.

The voice trace is the app's signature: rounded bars that show how loudly you spoke. It is live in
the Flow Bar and frozen on Home (the last dictation), and nowhere else. Nothing here runs a timer:
widgets repaint only when their data changes, so an idle app uses no CPU for drawing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRectF, QSize, Qt, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from flow.ui.theme import MOTION_ENTER_MS, current_palette, notifier

TRACE_BARS = 48
_LIVE_STATES = ("recording", "handsfree", "command")


# -- the voice trace ------------------------------------------------------------------------------
def level_from_rms(rms: float) -> float:
    """Microphone loudness (RMS) to a bar height 0..1 that reads well for normal speech."""
    return min(1.0, (max(rms, 0.0) * 9.0) ** 0.7)


def envelope(levels: Sequence[float], bars: int = TRACE_BARS) -> list[float]:
    """Squeeze a recording's levels into ``bars`` bars (loudest moment of each slice)."""
    if not levels:
        return []
    if len(levels) <= bars:
        return [float(v) for v in levels]
    step = len(levels) / bars
    return [
        max(levels[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)])
        for i in range(bars)
    ]


def paint_trace(
    p: QPainter, rect: QRectF, levels: Iterable[float], color: QColor, bar_w: float, gap: float
) -> None:
    """Rounded bars centred on the rect's middle line; quiet moments keep a small stub."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    cy = rect.center().y()
    x = rect.left()
    for lv in levels:
        if x + bar_w > rect.right() + 0.5:
            break
        h = max(bar_w, min(1.0, max(0.0, lv)) * rect.height())
        p.drawRoundedRect(QRectF(x, cy - h / 2, bar_w, h), bar_w / 2, bar_w / 2)
        x += bar_w + gap


class VoiceTrace(QWidget):
    """A frozen trace of one dictation. Ember while it is the newest thing on screen."""

    BAR_W = 3.0
    GAP = 3.0

    def __init__(self, height: int = 40) -> None:
        super().__init__()
        self.levels: list[float] = []
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        notifier.changed.connect(self.update)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(int(TRACE_BARS * (self.BAR_W + self.GAP)), self.minimumHeight())

    def set_levels(self, levels: Sequence[float]) -> None:
        self.levels = [float(v) for v in levels]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        if not self.levels:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # the trace spans the width it is given: bars and gaps share it equally
        n = len(self.levels)
        bar = max(2.0, min(6.0, self.width() / (2 * n - 1)))
        paint_trace(p, QRectF(self.rect()), self.levels, QColor(current_palette().accent), bar, bar)
        p.end()


class TraceRecorder(QObject):
    """Keeps the loudness of the dictation in progress and hands its trace on when it ends.

    Fed by the worker's state and level signals; the trace lives in memory only.
    """

    def __init__(self, on_trace) -> None:  # noqa: ANN001 - any callable taking list[float]
        super().__init__()
        self._on_trace = on_trace
        self._levels: list[float] = []
        self._live = False

    @Slot(str, str)
    def on_state(self, state: str, _text: str = "") -> None:
        if state in _LIVE_STATES:
            if not self._live:
                self._levels = []
            self._live = True
            return
        if self._live and state in ("processing", "done") and self._levels:
            self._on_trace(envelope(self._levels))
        self._live = False

    @Slot(float)
    def on_level(self, rms: float) -> None:
        if self._live:
            self._levels.append(level_from_rms(rms))


# -- numbers --------------------------------------------------------------------------------------
class StatTile(QWidget):
    """A label, one large figure, and a quiet line that says what the figure compares to."""

    def __init__(self, label: str, note: str = "") -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.label = QLabel(label)
        self.label.setProperty("role", "caption")
        self.value = QLabel("-")
        self.value.setProperty("role", "figure")
        self.note = QLabel(note)
        self.note.setProperty("role", "caption")
        self.note.setWordWrap(True)
        for w in (self.label, self.value, self.note):
            lay.addWidget(w)
        self.note.setVisible(bool(note))

    def set(self, value: str, note: str | None = None) -> None:
        self.value.setText(value)
        if note is not None:
            self.note.setText(note)
            self.note.setVisible(bool(note))


# -- the week chart -------------------------------------------------------------------------------
class WeekChart(QWidget):
    """Words per day for the last 7 days, split by language, against your daily average.

    Colour means something: ember is English, sage is Arabic, and today is drawn at full strength
    while earlier days step back. A dashed line marks your usual day, so a bar reads as "more or
    less than usual" at a glance. A day without dictation keeps a small dot, so gaps stay visible.
    """

    def __init__(self, height: int = 280) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.days: list[tuple[date, int, int]] = []  # (day, english, arabic)
        self.average = 0.0
        notifier.changed.connect(self.update)

    def set_days(self, days: Sequence[tuple], average: float = 0.0) -> None:
        """``days`` holds (day, words) or (day, english, arabic) tuples, oldest first."""
        self.days = [(d[0], d[1], 0) if len(d) == 2 else (d[0], d[1], d[2]) for d in days]
        self.average = average
        self.update()

    def has_arabic(self) -> bool:
        return any(ar for _, _, ar in self.days)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        if not self.days:
            return
        pal = current_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        font = QFont(self.font())
        font.setPixelSize(12)
        p.setFont(font)
        legend_h = 28
        base = h - 28  # room for the day labels
        chart_top = legend_h + 24  # room for the value above the tallest bar
        top = max([en + ar for _, en, ar in self.days] + [self.average, 1.0])
        span = base - chart_top

        def y_of(value: float) -> float:
            return base - span * value / top

        # legend: what each colour means
        x = 0.0
        series = [("English", pal.accent)] + (
            [("Arabic", pal.series_2)] if self.has_arabic() else []
        )
        for name, color in series:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x, 8, 10, 10), 3, 3)
            p.setPen(QColor(pal.secondary))
            p.drawText(QRectF(x + 16, 4, 80, 18), int(Qt.AlignmentFlag.AlignVCenter), name)
            x += 16 + QFontMetrics(font).horizontalAdvance(name) + 20
        # baseline
        p.setPen(QColor(pal.border))
        p.drawLine(0, int(base), w, int(base))
        # the usual day
        if self.average > 0:
            pen = QPen(QColor(pal.muted), 1, Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 4])
            p.setPen(pen)
            ya = y_of(self.average)
            p.drawLine(0, int(ya), w, int(ya))
            label = f"Your average {self.average:,.0f}"
            lw = QFontMetrics(font).horizontalAdvance(label) + 8
            p.setPen(QColor(pal.muted))
            p.drawText(QRectF(w - lw, ya - 20, lw, 18), int(Qt.AlignmentFlag.AlignRight), label)

        slot = w / len(self.days)
        for i, (d, en, ar) in enumerate(self.days):
            today = i == len(self.days) - 1
            total = en + ar
            bw = min(slot * 0.46, 40.0)
            left = i * slot + (slot - bw) / 2
            if total:
                bar = QRectF(left, y_of(total), bw, base - y_of(total))
                clip = QPainterPath()
                clip.addRoundedRect(bar, 6, 6)
                p.save()
                p.setClipPath(clip)
                p.setPen(Qt.PenStyle.NoPen)
                for value, color, bottom in ((en, pal.accent, 0), (ar, pal.series_2, en)):
                    if value:
                        c = QColor(color)
                        c.setAlphaF(1.0 if today else 0.62)
                        p.setBrush(c)
                        p.drawRect(
                            QRectF(
                                left, y_of(bottom + value), bw, y_of(bottom) - y_of(bottom + value)
                            )
                        )
                p.restore()
                above = self.average and total >= self.average
                p.setPen(QColor(pal.text if today or above else pal.muted))
                p.drawText(
                    QRectF(i * slot, bar.top() - 22, slot, 18),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    f"{total:,}",
                )
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal.border_strong))
                p.drawEllipse(QRectF(left + bw / 2 - 2, base - 6, 4, 4))
            p.setPen(QColor(pal.text if today else pal.muted))
            p.drawText(
                QRectF(i * slot, h - 22, slot, 20),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                "Today" if today else d.strftime("%a"),
            )
        p.end()


class RankedList(QWidget):
    """A short ranked list with thin bars: where your words went. The leader is ember."""

    ROW = 32

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, int]] = []
        notifier.changed.connect(self.update)

    def set_rows(self, rows: Sequence[tuple[str, int]]) -> None:
        self.rows = list(rows)
        self.setFixedHeight(max(1, len(self.rows)) * self.ROW)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        if not self.rows:
            return
        pal = current_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(13)
        p.setFont(font)
        w = self.width()
        name_w = 140.0
        value_w = 72.0
        top = max(n for _, n in self.rows) or 1
        for i, (name, n) in enumerate(self.rows):
            y = i * self.ROW
            p.setPen(QColor(pal.text))
            p.drawText(QRectF(0, y, name_w, self.ROW), int(Qt.AlignmentFlag.AlignVCenter), name)
            track = QRectF(name_w, y + self.ROW / 2 - 3, w - name_w - value_w - 12, 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal.surface_hover))
            p.drawRoundedRect(track, 3, 3)
            p.setBrush(QColor(pal.accent if i == 0 else pal.border_strong))
            p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * n / top, 6), 3, 3)
            p.setPen(QColor(pal.secondary))
            p.drawText(
                QRectF(w - value_w, y, value_w, self.ROW),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                f"{n:,} words",
            )
        p.end()


class CountBarDelegate(QStyledItemDelegate):
    """A count with a thin bar under it, scaled to the largest count in the column.

    The bar makes a long list scannable: the words you use most stand out without reading numbers.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.top = 1

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: ANN001
        super().paint(painter, option, index)
        try:
            n = int(index.data() or 0)
        except ValueError:
            return
        if n <= 0:
            return
        pal = current_palette()
        r = option.rect
        width = max(4.0, (r.width() - 24) * n / max(self.top, 1))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.accent))
        painter.drawRoundedRect(QRectF(r.left() + 12, r.bottom() - 9, width, 3), 1.5, 1.5)
        painter.restore()


# -- motion ---------------------------------------------------------------------------------------
def fade_in(widget: QWidget, duration: int = MOTION_ENTER_MS) -> QPropertyAnimation:
    """The one entrance: a short fade. The effect is removed afterwards so text stays crisp."""
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


# -- the recent dictations list -------------------------------------------------------------------
LANGUAGE_ROLE = Qt.ItemDataRole.UserRole + 1


class RecentRowDelegate(QStyledItemDelegate):
    """Draws one cell of the recent dictations list.

    Column 0 gets a short mark in the language's chart colour (ember English, sage Arabic) so the
    list and the Insights chart speak the same language; column 1 shows the app as a quiet badge.
    """

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: ANN001
        pal = current_palette()
        if index.column() == 1:
            # the row's background, then the badge instead of plain text
            text = index.data() or ""
            self._paint_background(painter, option)
            if text:
                font = QFont(option.font)
                font.setPixelSize(12)
                fm = QFontMetrics(font)
                r = option.rect
                w = fm.horizontalAdvance(text) + 16
                badge = QRectF(r.left() + 8, r.center().y() - 11, w, 22)
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(pal.raised))
                painter.drawRoundedRect(badge, 6, 6)
                painter.setFont(font)
                painter.setPen(QColor(pal.secondary))
                painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), text)
                painter.restore()
            return
        if index.column() != 0:
            super().paint(painter, option, index)
            return
        # time column: the background spans the cell, the text moves right of the language mark
        self._paint_background(painter, option)
        shifted = QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(10, 0, 0, 0)
        super().paint(painter, shifted, index)
        lang = index.data(LANGUAGE_ROLE) or "en"
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.series_2 if lang == "ar" else pal.accent))
        painter.drawRoundedRect(QRectF(r.left() + 2, r.center().y() - 8, 3, 16), 1.5, 1.5)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: ANN001, ANN201, N802
        size = super().sizeHint(option, index)
        if index.column() == 0:
            size.setWidth(size.width() + 12)  # room for the language mark
        elif index.column() == 1:
            size.setWidth(size.width() + 24)  # room for the badge padding
        return size

    @staticmethod
    def _paint_background(painter: QPainter, option) -> None:  # noqa: ANN001
        from PySide6.QtWidgets import QStyle

        pal = current_palette()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(pal.raised))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(pal.surface_hover))
        painter.save()
        painter.setPen(QColor(pal.border))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()
