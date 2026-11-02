"""Insights: words dictated, speaking speed, time saved, streak, and the week in one chart."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from flow.store.history import Insights, compute_insights
from flow.ui.hub.context import HubContext
from flow.ui.hub.widgets import caption, page_header, scrollable, section_title, set_role
from flow.ui.kit import RankedList, StatTile, WeekChart


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
        lay.addWidget(
            page_header("Insights", "Your dictation habits. Calculated on this computer.")
        )

        # -- the lead number: what dictating gave back, then four supporting figures ----------
        lead_card = QFrame()
        lead_card.setObjectName("Card")
        lead = QHBoxLayout(lead_card)
        lead.setContentsMargins(24, 24, 24, 24)
        lead.setSpacing(40)
        hero = QVBoxLayout()
        hero.setSpacing(4)
        hero.addWidget(caption("Typing time saved"))
        self.saved_value = set_role(QLabel("-"), "lead")
        hero.addWidget(self.saved_value)
        self.saved_note = caption("")
        hero.addWidget(self.saved_note)
        hero.addStretch(1)
        lead.addLayout(hero, 5)
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(32)
        tiles.setVerticalSpacing(20)
        self.cards = {
            "saved": StatTile("Time saved"),  # mirrors the lead figure for older callers
            "words": StatTile("Words dictated"),
            "wpm": StatTile("Speaking speed", "Words a minute while talking"),
            "dictations": StatTile("Dictations"),
            "streak": StatTile("Day streak", "Days in a row"),
        }
        self.cards["saved"].hide()
        for i, key in enumerate(("words", "wpm", "dictations", "streak")):
            tiles.addWidget(self.cards[key], i // 2, i % 2, Qt.AlignmentFlag.AlignTop)
        lead.addLayout(tiles, 6)
        lay.addWidget(lead_card)

        # -- the week -------------------------------------------------------------------------
        lay.addSpacing(8)
        head = QHBoxLayout()
        head.addWidget(section_title("Words per day"), 1)
        self.week_note = caption("")
        self.week_note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.week_note, 1)
        lay.addLayout(head)
        chart_card = QFrame()
        chart_card.setObjectName("Card")
        chart_lay = QVBoxLayout(chart_card)
        chart_lay.setContentsMargins(24, 20, 24, 16)
        self.chart = WeekChart(300)
        chart_lay.addWidget(self.chart)
        lay.addWidget(chart_card)

        # -- where the words went -------------------------------------------------------------
        lay.addSpacing(8)
        lay.addWidget(section_title("Where you dictate"))
        apps_card = QFrame()
        apps_card.setObjectName("Card")
        apps_lay = QVBoxLayout(apps_card)
        apps_lay.setContentsMargins(24, 16, 24, 16)
        apps_lay.setSpacing(8)
        apps_lay.addWidget(caption("Words in each app, last 30 days"))
        self.apps = RankedList()
        apps_lay.addWidget(self.apps)
        self.apps_card = apps_card
        lay.addWidget(apps_card)
        lay.addStretch(1)
        ctx.historyChanged.connect(self.refresh)
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        ins: Insights = compute_insights(self.ctx.dictionary.db)
        saved = format_duration(ins.time_saved_s)
        self.saved_value.setText(saved)
        self.saved_note.setText(
            f"{ins.total_words:,} words you did not have to type, at 40 words a minute"
            if ins.total_words
            else "Your first dictation starts the count"
        )
        self.cards["saved"].value.setText(saved)
        self.cards["words"].value.setText(f"{ins.total_words:,}")
        self.cards["dictations"].value.setText(f"{ins.dictations:,}")
        self.cards["wpm"].value.setText(f"{ins.wpm:.0f}" if ins.wpm else "-")
        self.cards["streak"].value.setText(str(ins.streak_days))
        self.chart.set_days(ins.language_by_day or ins.words_by_day, ins.daily_average)
        self.week_note.setText(
            week_note(ins.words_by_day[-1][1] if ins.words_by_day else 0, ins.daily_average)
        )
        self.apps.set_rows(ins.top_apps)
        self.apps_card.setVisible(bool(ins.top_apps))


def week_note(today: int, average: float) -> str:
    """One line that says how today compares with a usual day."""
    if not average:
        return ""
    diff = round(today - average)
    if today == 0:
        return f"Nothing yet today, you usually say {average:,.0f} words"
    if abs(diff) < max(10, average * 0.05):
        return f"Today {today:,} words, about your usual"
    more = "more" if diff > 0 else "fewer"
    return f"Today {today:,} words, {abs(diff):,} {more} than usual"
