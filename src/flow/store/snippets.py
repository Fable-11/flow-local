"""Snippets: say a trigger phrase, get a saved block of text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from flow.store.db import Database

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    """Case-fold, drop punctuation (incl. Arabic), collapse spaces."""
    return " ".join(_PUNCT.sub(" ", text.casefold()).split())


@dataclass(frozen=True)
class Snippet:
    id: int
    trigger: str
    content: str
    anywhere: bool  # also expand when the trigger appears inside a longer sentence


class SnippetStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, trigger: str, content: str, anywhere: bool = False) -> Snippet:
        t = " ".join(trigger.split())
        if not normalize(t) or not content:
            raise ValueError("trigger and content must not be empty")
        self.db.execute(
            "INSERT INTO snippets (trigger, content, anywhere) VALUES (?, ?, ?) "
            "ON CONFLICT(trigger) DO UPDATE SET content = excluded.content, "
            "anywhere = excluded.anywhere",
            (t, content, int(anywhere)),
        )
        return self.get(t)  # type: ignore[return-value]

    def get(self, trigger: str) -> Snippet | None:
        rows = self.db.query("SELECT * FROM snippets WHERE trigger = ?", (trigger,))
        return self._row(rows[0]) if rows else None

    def delete(self, trigger: str) -> bool:
        return self.db.execute("DELETE FROM snippets WHERE trigger = ?", (trigger,)).rowcount > 0

    def list(self, search: str = "") -> list[Snippet]:
        like = f"%{search.strip()}%"
        rows = self.db.query(
            "SELECT * FROM snippets WHERE trigger LIKE ? OR content LIKE ? "
            "ORDER BY trigger COLLATE NOCASE",
            (like, like),
        )
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> Snippet:  # noqa: ANN001
        return Snippet(r["id"], r["trigger"], r["content"], bool(r["anywhere"]))

    # -- matching -----------------------------------------------------------------------
    def match_exact(self, utterance: str) -> Snippet | None:
        """The whole utterance is a trigger phrase (ignoring case and punctuation)."""
        key = normalize(utterance)
        if not key:
            return None
        for s in self.list():
            if normalize(s.trigger) == key:
                return s
        return None

    def expand_embedded(self, text: str) -> tuple[str, list[str]]:
        """Replace triggers of 'anywhere' snippets found inside ``text``."""
        used: list[str] = []
        for s in sorted((s for s in self.list() if s.anywhere), key=lambda s: -len(s.trigger)):
            words = [re.escape(w) for w in s.trigger.split()]
            pat = re.compile(r"(?<!\w)" + r"[\s,]+".join(words) + r"(?!\w)[.,;!?،؟]?", re.I)
            new = pat.sub(lambda _m, c=s.content: c, text)
            if new != text:
                used.append(s.trigger)
                text = new
        return text, used
