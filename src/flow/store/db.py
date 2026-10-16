"""SQLite storage with simple versioned migrations (settings, dictionary, snippets)."""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE dictionary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        written TEXT NOT NULL UNIQUE COLLATE NOCASE,
        spoken TEXT,
        starred INTEGER NOT NULL DEFAULT 0,
        uses INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE snippets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger TEXT NOT NULL UNIQUE COLLATE NOCASE,
        content TEXT NOT NULL,
        anywhere INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # v2
    """
    CREATE TABLE history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        app TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'text',
        language TEXT NOT NULL DEFAULT '',
        raw TEXT NOT NULL,
        final TEXT NOT NULL,
        words INTEGER NOT NULL DEFAULT 0,
        audio_s REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX history_created ON history (created_at);
    CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    """,
]


def default_db_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FlowLocal"
    base.mkdir(parents=True, exist_ok=True)
    return base / "flow.db"


class Database:
    """Thread-safe wrapper around one sqlite3 connection."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for i in range(version, len(MIGRATIONS)):
                self._conn.executescript(MIGRATIONS[i])
                self._conn.execute(f"PRAGMA user_version = {i + 1}")
            self._conn.commit()

    @property
    def version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def execute(self, sql: str, params: Sequence = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: Sequence = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()
