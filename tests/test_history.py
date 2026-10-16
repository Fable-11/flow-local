from datetime import date, datetime, timedelta

import pytest

from flow.store.db import MIGRATIONS, Database
from flow.store.history import (
    HistoryStore,
    NotesStore,
    compute_insights,
    count_words,
    derive_title,
    suggest_words,
)

NOW = datetime(2026, 10, 15, 12, 0, 0)


@pytest.fixture
def db():
    d = Database()
    yield d
    d.close()


def test_migrated_to_latest(db):
    assert db.version == len(MIGRATIONS) >= 2


def test_count_words_english_arabic_mixed():
    assert count_words("Hello, world!") == 2
    assert count_words("انا رايح السوق") == 3
    assert count_words("send it to أحمد now") == 5
    assert count_words("faster-whisper isn't slow") == 3
    assert count_words("") == 0


def test_history_add_recent_search_delete(db):
    h = HistoryStore(db)
    a = h.add("um hello there", "Hello there.", "chrome.exe", "text", "en", 2.0, NOW)
    b = h.add("raw2", "مرحبا بك", "whatsapp.exe", "text", "ar", 1.5, NOW)
    assert [i.id for i in h.recent()] == [b, a]  # newest first
    assert h.get(a).final == "Hello there." and h.get(a).words == 2
    assert [i.id for i in h.recent(search="whatsapp")] == [b]
    assert [i.id for i in h.recent(search="hello")] == [a]
    h.update_final(a, "Hello there, friend.")
    assert h.get(a).words == 3
    assert h.delete(a) and not h.delete(a)
    assert h.count() == 1
    assert h.clear() == 1 and h.count() == 0


def test_purge_older_than(db):
    h = HistoryStore(db)
    h.add("old", "old text", now=NOW - timedelta(days=40))
    h.add("mid", "mid text", now=NOW - timedelta(days=10))
    h.add("new", "new text", now=NOW)
    assert h.purge_older_than(0, NOW) == 0  # 0 = keep forever
    assert h.purge_older_than(30, NOW) == 1
    assert [i.raw for i in h.recent()] == ["new", "mid"]


def test_insights_basic_numbers(db):
    h = HistoryStore(db)
    # 120 words in 60 s of speech = 120 wpm; typing it at 40 wpm would take 180 s
    h.add("r", " ".join(["word"] * 120), audio_s=60.0, now=NOW)
    ins = compute_insights(db, NOW.date())
    assert ins.total_words == 120 and ins.dictations == 1
    assert round(ins.wpm) == 120
    assert round(ins.time_saved_s) == 120
    assert ins.streak_days == 1
    assert ins.words_by_day[-1] == (NOW.date(), 120) and len(ins.words_by_day) == 7


def test_insights_empty_and_commands_excluded(db):
    ins = compute_insights(db, NOW.date())
    assert (ins.total_words, ins.dictations, ins.streak_days) == (0, 0, 0)
    assert (ins.wpm, ins.time_saved_s) == (0.0, 0.0)
    HistoryStore(db).add("r", "edited text here", kind="command", audio_s=3, now=NOW)
    assert compute_insights(db, NOW.date()).dictations == 0


def test_streak_rules(db):
    h = HistoryStore(db)
    today = date(2026, 10, 15)
    for back in (0, 1, 2, 4):  # gap at 3 days ago
        h.add("r", "some words here", now=datetime(2026, 10, 15 - back, 9, 0))
    assert compute_insights(db, today).streak_days == 3
    # nothing today yet: the streak still counts through yesterday
    assert compute_insights(db, today + timedelta(days=1)).streak_days == 3
    assert compute_insights(db, today + timedelta(days=3)).streak_days == 0


def test_notes_crud_and_titles(db):
    n = NotesStore(db)
    note = n.create("Shopping list\nmilk\neggs", NOW)
    assert note.title == "Shopping list"
    n.update(note.id, "Updated first line\nmore", NOW + timedelta(minutes=1))
    assert n.get(note.id).title == "Updated first line"
    second = n.create("", NOW + timedelta(minutes=2))
    assert second.title == "Untitled note"
    assert [x.id for x in n.list()] == [second.id, note.id]  # most recently updated first
    assert n.delete(note.id) and not n.delete(note.id)
    assert derive_title("\n\n  hi there \n") == "hi there"


def test_suggest_words():
    finals = [
        "I talked to Kubernetes today.",
        "We met at Kubernetes again.",
        "Then the Kubernetes team replied.",
        "Use faster-whisper for it.",
        "faster-whisper is fast and faster-whisper is local.",
        "Hello there. Today is fine.",
        "Maybe Rarely once.",
    ]
    got = dict(suggest_words(finals, known={"hello"}))
    assert got["Kubernetes"] == 3 and got["faster-whisper"] == 3
    assert "Today" not in got and "Hello" not in got and "Rarely" not in got
    assert "Kubernetes" not in dict(suggest_words(finals, known={"kubernetes"}))
