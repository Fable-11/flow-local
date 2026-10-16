"""Key/value settings persisted as JSON in SQLite."""

from __future__ import annotations

import json
from typing import Any

from flow.store.db import Database


class SettingsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        rows = self.db.query("SELECT value FROM settings WHERE key = ?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except ValueError:
            return default

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    def all(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self.db.query("SELECT * FROM settings")}
