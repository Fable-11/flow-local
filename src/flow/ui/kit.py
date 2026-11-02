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
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QSizePolicy, QVBoxLayout, QWidget

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
    return [max(levels[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)]) for i in range(bars)]


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
    """Words per day for the last 7 days. Today is ember; other days are neutral steps."""

    def __init__(self, height: int = 280) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.days: list[tuple[date, int]] = []
        notifier.changed.connect(self.update)

    def set_days(self, days: list[tuple[date, int]]) -> None:
        self.days = days
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        if not self.days:
            return
        pal = current_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        top = max((n for _, n in self.days), default=0) or 1
        slot = w / len(self.days)
        base = h - 28  # room for the day labels
        chart_top = 28  # room for the value above the tallest bar
        font = QFont(self.font())
        font.setPixelSize(12)
        p.setFont(font)
        grid = QColor(pal.border)
        for i in range(4):  # a muted grid: baseline plus three quiet lines
            y = base - (base - chart_top) * i / 3
            p.setPen(grid)
            p.drawLine(0, int(y), w, int(y))
        for i, (d, n) in enumerate(self.days):
            today = i == len(self.days) - 1
            bar_h = (base - chart_top) * n / top
            bw = min(slot * 0.5, 44.0)
            rect = QRectF(i * slot + (slot - bw) / 2, base - bar_h, bw, bar_h)
            if n:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal.accent if today else pal.border_strong))
                p.drawRoundedRect(rect, 6, 6)
                p.setPen(QColor(pal.text if today else pal.muted))
                p.drawText(
                    QRectF(i * slot, rect.top() - 22, slot, 18),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    f"{n:,}",
                )
            p.setPen(QColor(pal.text if today else pal.muted))
            p.drawText(
                QRectF(i * slot, h - 22, slot, 20),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                "Today" if today else d.strftime("%a"),
            )
        p.end()


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
