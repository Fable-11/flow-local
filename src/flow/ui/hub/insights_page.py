"""Insights: words dictated, speaking speed, time saved, streak. Plain data, no decoration."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from flow.store.history import Insights, compute_insights
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import (
    Panel,
    SettingRow,
    page_header,
    scrollable,
    section_title,
    set_role,
)
from flow.ui.theme import current_palette, notifier


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


class StatRow(SettingRow):
    """A label with its value on the right. ``value`` is the QLabel holding the number."""

    def __init__(self, title: str, description: str = "") -> None:
        self.value = set_role(QLabel("-"), "section")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        super().__init__(title, description, self.value)


class WeekBars(QWidget):
    """Words per day for the last 7 days. Today is the accent colour; other days are neutral."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
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
        base = h - 26  # leave room for the day labels
        label_font = QFont(self.font())
        label_font.setPixelSize(12)
        p.setFont(label_font)
        for i, (d, n) in enumerate(self.days):
            is_today = i == len(self.days) - 1
            bar_h = max((base - 24) * n / top, 3 if n else 2)
            rect = QRectF(i * slot + slot * 0.22, base - bar_h, slot * 0.56, bar_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal.accent if is_today and n else pal.border_strong))
            p.drawRoundedRect(rect, 5, 5)
            p.setPen(QColor(pal.text if n else pal.muted))
            if n:
                p.drawText(
                    QRectF(i * slot, rect.top() - 20, slot, 18),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                    f"{n:,}",
                )
            p.setPen(QColor(pal.text if is_today else pal.muted))
            p.drawText(
                QRectF(i * slot, h - 22, slot, 20),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                "Today" if is_today else d.strftime("%a"),
            )
        p.end()


class InsightsPage(QWidget):
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
        lay.addWidget(page_header("Insights", "Your dictation habits. Calculated on this computer."))

        lay.addWidget(section_title("Summary"))
        summary = Panel()
        self.cards = {
            "words": StatRow("Words dictated"),
            "dictations": StatRow("Dictations"),
            "wpm": StatRow("Speaking speed", "Words per minute while talking"),
            "saved": StatRow("Time saved", "Compared with typing at 40 words per minute"),
            "streak": StatRow("Day streak", "Consecutive days with a dictation"),
        }
        for row in self.cards.values():
            summary.add(row)
        lay.addWidget(summary)

        lay.addWidget(section_title("Words per day"))
        chart_panel = Panel()
        self.chart = WeekBars()
        chart_panel.add(self.chart)
        lay.addWidget(chart_panel, 1)
        ctx.historyChanged.connect(self.refresh)
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        ins: Insights = compute_insights(self.ctx.dictionary.db)
        self.cards["words"].value.setText(f"{ins.total_words:,}")
        self.cards["dictations"].value.setText(f"{ins.dictations:,}")
        self.cards["wpm"].value.setText(f"{ins.wpm:.0f}" if ins.wpm else "-")
        self.cards["saved"].value.setText(format_duration(ins.time_saved_s))
        self.cards["streak"].value.setText(str(ins.streak_days))
        self.chart.set_days(ins.words_by_day)
