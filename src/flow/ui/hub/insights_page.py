"""Insights: words dictated, speaking speed, time saved, streak, and the week in one chart."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QVBoxLayout, QWidget

from flow.store.history import Insights, compute_insights
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import page_header, scrollable, section_title
from flow.ui.kit import StatTile, WeekChart


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


# the week chart lives in the shared kit; the old name stays for anything that imports it
WeekBars = WeekChart


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
        lay.setSpacing(16)
        lay.addWidget(page_header("Insights", "Your dictation habits. Calculated on this computer."))

        tiles_card = QFrame()
        tiles_card.setObjectName("Card")
        tiles = QGridLayout(tiles_card)
        tiles.setContentsMargins(24, 20, 24, 20)
        tiles.setHorizontalSpacing(32)
        tiles.setVerticalSpacing(20)
        self.cards = {
            "words": StatTile("Words dictated", "Since you started"),
            "saved": StatTile("Time saved", "Compared with typing at 40 words a minute"),
            "wpm": StatTile("Speaking speed", "Words per minute while talking"),
            "dictations": StatTile("Dictations", "Commands not counted"),
            "streak": StatTile("Day streak", "Days in a row with a dictation"),
        }
        for i, tile in enumerate(self.cards.values()):
            tiles.addWidget(tile, i // 3, i % 3, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(tiles_card)

        lay.addSpacing(8)
        lay.addWidget(section_title("Words per day"))
        chart_card = QFrame()
        chart_card.setObjectName("Card")
        chart_lay = QVBoxLayout(chart_card)
        chart_lay.setContentsMargins(24, 20, 24, 16)
        self.chart = WeekChart(280)
        chart_lay.addWidget(self.chart)
        lay.addWidget(chart_card, 1)
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
