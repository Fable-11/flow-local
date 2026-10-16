"""Personal dictionary: names/jargon, optional spoken->written replacements, priority stars."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass

from flow.store.db import Database

MAX_LEN = 80
_TRUE = {"1", "true", "yes", "y", "*", "star", "starred"}


@dataclass(frozen=True)
class DictEntry:
    id: int
    written: str
    spoken: str | None
    starred: bool
    uses: int


def _clean(value: str | None) -> str | None:
    value = " ".join((value or "").split())
    return value[:MAX_LEN] or None


class DictionaryStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._regex: re.Pattern[str] | None = None
        self._map: dict[str, str] = {}

    # -- CRUD ---------------------------------------------------------------------------
    def add(self, written: str, spoken: str | None = None, starred: bool = False) -> DictEntry:
        """Insert or update (matching ``written`` case-insensitively)."""
        w = _clean(written)
        if not w:
            raise ValueError("word must not be empty")
        s = _clean(spoken)
        self.db.execute(
            "INSERT INTO dictionary (written, spoken, starred) VALUES (?, ?, ?) "
            "ON CONFLICT(written) DO UPDATE SET written = excluded.written, "
            "spoken = excluded.spoken, starred = excluded.starred",
            (w, s, int(starred)),
        )
        self._regex = None
        return self.get(w)  # type: ignore[return-value]

    def get(self, written: str) -> DictEntry | None:
        rows = self.db.query("SELECT * FROM dictionary WHERE written = ?", (written,))
        return self._entry(rows[0]) if rows else None

    def delete(self, written: str) -> bool:
        cur = self.db.execute("DELETE FROM dictionary WHERE written = ?", (written,))
        self._regex = None
        return cur.rowcount > 0

    def set_starred(self, written: str, starred: bool) -> None:
        self.db.execute(
            "UPDATE dictionary SET starred = ? WHERE written = ?", (int(starred), written)
        )

    def list(self, search: str = "") -> list[DictEntry]:
        like = f"%{search.strip()}%"
        rows = self.db.query(
            "SELECT * FROM dictionary WHERE written LIKE ? OR IFNULL(spoken, '') LIKE ? "
            "ORDER BY starred DESC, written COLLATE NOCASE",
            (like, like),
        )
        return [self._entry(r) for r in rows]

    @staticmethod
    def _entry(r) -> DictEntry:  # noqa: ANN001
        return DictEntry(r["id"], r["written"], r["spoken"], bool(r["starred"]), r["uses"])

    # -- feeding the models -------------------------------------------------------------
    def words_for_prompt(self, limit: int = 60) -> list[str]:
        """Written forms, starred first, then most used. Used for Whisper and the LLM."""
        rows = self.db.query(
            "SELECT written FROM dictionary "
            "ORDER BY starred DESC, uses DESC, written COLLATE NOCASE LIMIT ?",
            (limit,),
        )
        return [r["written"] for r in rows]

    # -- replacements -------------------------------------------------------------------
    def _build(self) -> None:
        mapping: dict[str, str] = {}
        for e in self.list():
            mapping[e.written.casefold()] = e.written  # fixes casing of the word itself
            if "-" in e.written:  # Whisper often hears "faster-whisper" as "faster whisper"
                mapping.setdefault(e.written.replace("-", " ").casefold(), e.written)
        for e in self.list():
            if e.spoken:
                mapping[e.spoken.casefold()] = e.written
        self._map = mapping
        keys = sorted(mapping, key=len, reverse=True)
        self._regex = (
            re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, keys)) + r")(?!\w)", re.IGNORECASE)
            if keys
            else None
        )

    def apply_replacements(self, text: str) -> tuple[str, list[str]]:
        """Replace spoken forms / fix casing. Returns (new_text, written words that matched)."""
        if self._regex is None:
            self._build()
        if self._regex is None or not text:
            return text, []
        hits: list[str] = []

        def sub(m: re.Match[str]) -> str:
            written = self._map[m.group(0).casefold()]
            hits.append(written)
            return written

        return self._regex.sub(sub, text), hits

    def record_use(self, words: list[str]) -> None:
        for w in set(words):
            self.db.execute("UPDATE dictionary SET uses = uses + 1 WHERE written = ?", (w,))

    # -- import / export ----------------------------------------------------------------
    def export_json(self) -> str:
        data = [
            {"written": e.written, "spoken": e.spoken, "starred": e.starred} for e in self.list()
        ]
        return json.dumps(data, ensure_ascii=False, indent=2)

    def export_csv(self) -> str:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["written", "spoken", "starred"])
        for e in self.list():
            w.writerow([e.written, e.spoken or "", int(e.starred)])
        return out.getvalue()

    def import_text(self, text: str, fmt: str | None = None) -> tuple[int, int]:
        """Import JSON or CSV text. Returns (imported, skipped)."""
        text = text.lstrip("﻿")
        fmt = fmt or ("json" if text.lstrip().startswith(("[", "{")) else "csv")
        if fmt == "json":
            rows = json.loads(text)
        else:
            rows = list(csv.DictReader(io.StringIO(text)))
        if isinstance(rows, dict):
            rows = [rows]
        ok = bad = 0
        for row in rows:
            row = {str(k).strip().lower(): v for k, v in dict(row).items()}
            written = row.get("written") or row.get("word")
            spoken = row.get("spoken") or row.get("replacement")
            star = row.get("starred", False)
            starred = star if isinstance(star, bool) else str(star).strip().lower() in _TRUE
            try:
                self.add(str(written or ""), str(spoken) if spoken else None, starred)
                ok += 1
            except ValueError:
                bad += 1
        return ok, bad
