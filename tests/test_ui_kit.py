"""The redesign's building blocks: the voice trace, today's numbers and the one-accent rule."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from flow.store.db import Database  # noqa: E402
from flow.store.history import HistoryStore, compute_today  # noqa: E402
from flow.ui import theme  # noqa: E402
from flow.ui.kit import (  # noqa: E402
    TRACE_BARS,
    StatTile,
    TraceRecorder,
    VoiceTrace,
    WeekChart,
    envelope,
    level_from_rms,
)

UI = Path(__file__).resolve().parents[1] / "src" / "flow" / "ui"


def test_envelope_keeps_the_loudest_moment_of_each_slice():
    levels = [0.0] * 480
    levels[100] = 0.9  # one loud word
    out = envelope(levels)
    assert len(out) == TRACE_BARS and max(out) == 0.9 and out.count(0.9) == 1
    assert envelope([0.2, 0.4]) == [0.2, 0.4] and envelope([]) == []


def test_levels_stay_between_zero_and_one():
    assert level_from_rms(-1) == 0.0 and level_from_rms(5) == 1.0 and 0 < level_from_rms(0.05) < 1


def test_the_trace_of_a_dictation_is_handed_on_when_it_ends():
    got: list[list[float]] = []
    rec = TraceRecorder(got.append)
    rec.on_level(0.3)  # before recording: ignored
    rec.on_state("recording")
    for v in (0.01, 0.08, 0.02):
        rec.on_level(v)
    rec.on_state("handsfree")  # switching mode mid-dictation keeps what was said
    rec.on_level(0.05)
    rec.on_state("processing")
    assert len(got) == 1 and len(got[0]) == 4 and max(got[0]) == level_from_rms(0.08)
    rec.on_state("done")  # the same dictation is not reported twice
    assert len(got) == 1
    rec.on_state("recording")
    rec.on_state("idle")  # cancelled: nothing to show
    assert len(got) == 1


def test_painted_widgets_never_run_a_timer(qtbot):
    from PySide6.QtCore import QTimer

    trace, chart = VoiceTrace(), WeekChart()
    for w in (trace, chart):
        qtbot.addWidget(w)
        w.show()
    trace.set_levels([0.2, 0.8, 0.5])
    chart.set_days([(date(2026, 3, d), d * 10) for d in range(1, 8)])
    for p in (theme.LIGHT, theme.DARK):
        theme.force_palette(p)
        assert not trace.grab().isNull() and not chart.grab().isNull()
    theme.force_palette(None)
    assert not trace.findChildren(QTimer) and not chart.findChildren(QTimer)


def test_stat_tile_shows_a_figure_and_an_optional_note(qtbot):
    tile = StatTile("Words today")
    qtbot.addWidget(tile)
    tile.set("1,240", "about 9 minutes of typing")
    assert tile.value.text() == "1,240" and tile.note.isVisibleTo(tile)
    tile.set("0", "")
    assert not tile.note.isVisibleTo(tile)


def test_today_counts_only_today_and_skips_commands():
    db = Database()
    h = HistoryStore(db)
    h.add("r", "one two three", audio_s=1, now=datetime(2026, 3, 9, 10, 0))
    h.add("r", "four five", audio_s=1, now=datetime(2026, 3, 9, 11, 0))
    h.add("r", "make it formal", kind="command", now=datetime(2026, 3, 9, 12, 0))
    h.add("r", "yesterday words here", audio_s=1, now=datetime(2026, 3, 8, 9, 0))
    today = compute_today(db, date(2026, 3, 9))
    assert (today.words, today.dictations) == (5, 2) and today.time_saved_s > 0
    assert compute_today(db, date(2026, 3, 1)).words == 0


def test_the_interface_uses_one_accent_only():
    """Colours live in the theme. Painted code may use only theme tokens, white and black."""
    allowed = {"#ffffff", "#000000"}
    offenders = []
    for path in UI.rglob("*.py"):
        if path.name == "theme.py":
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.name}: {h}" for h in re.findall(r"#[0-9a-fA-F]{6}\b", text)
                      if h.lower() not in allowed]  # fmt: skip
        for r, g, b in re.findall(r"QColor\((\d+),\s*(\d+),\s*(\d+)", text):
            if len({r, g, b}) > 1:  # a grey is fine, a hue is not
                offenders.append(f"{path.name}: QColor({r}, {g}, {b})")
    assert not offenders, offenders
