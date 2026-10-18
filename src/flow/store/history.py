"""Dictation history, notes and usage insights (all local)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from flow.store.db import Database
from flow.store.terms import WORD as _WORD
from flow.store.terms import candidate_terms

TYPING_WPM = 40  # baseline used for "time saved"


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def _stamp(now: datetime | None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


@dataclass(frozen=True)
class HistoryItem:
    id: int
    created_at: datetime
    app: str
    kind: str
    language: str
    raw: str
    final: str
    words: int
    audio_s: float


class HistoryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        raw: str,
        final: str,
        app: str = "",
        kind: str = "text",
        language: str = "",
        audio_s: float = 0.0,
        now: datetime | None = None,
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO history (created_at, app, kind, language, raw, final, words, audio_s) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_stamp(now), app, kind, language, raw, final, count_words(final), audio_s),
        )
        return int(cur.lastrowid)

    @staticmethod
    def _item(r) -> HistoryItem:  # noqa: ANN001
        return HistoryItem(
            r["id"], datetime.fromisoformat(r["created_at"]), r["app"], r["kind"], r["language"],
            r["raw"], r["final"], r["words"], r["audio_s"],
        )  # fmt: skip

    def get(self, item_id: int) -> HistoryItem | None:
        rows = self.db.query("SELECT * FROM history WHERE id = ?", (item_id,))
        return self._item(rows[0]) if rows else None

    def recent(self, limit: int = 50, search: str = "") -> list[HistoryItem]:
        like = f"%{search.strip()}%"
        rows = self.db.query(
            "SELECT * FROM history WHERE final LIKE ? OR raw LIKE ? OR app LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (like, like, like, limit),
        )
        return [self._item(r) for r in rows]

    def count(self) -> int:
        return int(self.db.query("SELECT COUNT(*) AS n FROM history")[0]["n"])

    def update_final(self, item_id: int, final: str) -> None:
        self.db.execute(
            "UPDATE history SET final = ?, words = ? WHERE id = ?",
            (final, count_words(final), item_id),
        )

    def delete(self, item_id: int) -> bool:
        return self.db.execute("DELETE FROM history WHERE id = ?", (item_id,)).rowcount > 0

    def clear(self) -> int:
        return self.db.execute("DELETE FROM history").rowcount

    def purge_older_than(self, days: int, now: datetime | None = None) -> int:
        if days <= 0:
            return 0
        cutoff = _stamp((now or datetime.now()) - timedelta(days=days))
        return self.db.execute("DELETE FROM history WHERE created_at < ?", (cutoff,)).rowcount

    def all_finals(self) -> list[str]:
        return [r["final"] for r in self.db.query("SELECT final FROM history ORDER BY id")]


# -- insights ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Insights:
    total_words: int
    dictations: int
    wpm: float  # speaking speed
    time_saved_s: float  # versus typing at TYPING_WPM
    streak_days: int
    words_by_day: list[tuple[date, int]]  # last 7 days, oldest first


def compute_insights(db: Database, today: date | None = None) -> Insights:
    today = today or date.today()
    rows = db.query("SELECT created_at, words, audio_s FROM history WHERE kind != 'command'")
    total_words = sum(r["words"] for r in rows)
    spoken_s = sum(r["audio_s"] for r in rows if r["audio_s"] > 0)
    spoken_words = sum(r["words"] for r in rows if r["audio_s"] > 0)
    wpm = spoken_words / (spoken_s / 60) if spoken_s > 0 else 0.0
    saved = max(0.0, total_words / TYPING_WPM * 60 - spoken_s) if rows else 0.0
    per_day: Counter[date] = Counter()
    for r in rows:
        per_day[datetime.fromisoformat(r["created_at"]).date()] += r["words"]
    # the streak may continue from yesterday if the user has not dictated yet today
    day = today if per_day.get(today) else today - timedelta(days=1)
    streak = 0
    while per_day.get(day):
        streak += 1
        day -= timedelta(days=1)
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    week = [(d, per_day.get(d, 0)) for d in days]
    return Insights(total_words, len(rows), wpm, saved, streak, week)


# -- notes ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Note:
    id: int
    title: str
    body: str
    updated_at: datetime


def derive_title(body: str) -> str:
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    return first[:60] or "Untitled note"


class NotesStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _note(r) -> Note:  # noqa: ANN001
        return Note(r["id"], r["title"], r["body"], datetime.fromisoformat(r["updated_at"]))

    def create(self, body: str = "", now: datetime | None = None) -> Note:
        cur = self.db.execute(
            "INSERT INTO notes (title, body, updated_at) VALUES (?, ?, ?)",
            (derive_title(body), body, _stamp(now)),
        )
        return self.get(int(cur.lastrowid))  # type: ignore[return-value]

    def get(self, note_id: int) -> Note | None:
        rows = self.db.query("SELECT * FROM notes WHERE id = ?", (note_id,))
        return self._note(rows[0]) if rows else None

    def update(self, note_id: int, body: str, now: datetime | None = None) -> None:
        self.db.execute(
            "UPDATE notes SET body = ?, title = ?, updated_at = ? WHERE id = ?",
            (body, derive_title(body), _stamp(now), note_id),
        )

    def delete(self, note_id: int) -> bool:
        return self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount > 0

    def list(self) -> list[Note]:
        rows = self.db.query("SELECT * FROM notes ORDER BY updated_at DESC, id DESC")
        return [self._note(r) for r in rows]


# -- suggested dictionary words ----------------------------------------------------------------
def suggest_words(
    finals: list[str], known: set[str], min_count: int = 3, limit: int = 12
) -> list[tuple[str, int]]:
    """Rare-looking terms (mid-sentence capitals, hyphen/digit/camelCase words) said repeatedly."""
    counts: Counter[str] = Counter()
    for text in finals:
        for w in candidate_terms(text, unique=False):
            if w.casefold() not in known:
                counts[w] += 1
    return [(w, n) for w, n in counts.most_common(limit) if n >= min_count]
