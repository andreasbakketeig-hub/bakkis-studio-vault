"""
Settings repository — lightweight key/value store backed by SQLite.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.database import Database


class SettingsRepository:
    """Persist and retrieve application preferences."""

    def __init__(self, db: "Database") -> None:
        self._db = db

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, key: str, default: str = "") -> str:
        rows = self._db.query(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        return rows[0]["value"] if rows else default

    def get_all(self) -> dict[str, str]:
        rows = self._db.query("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}

    # ── Write ─────────────────────────────────────────────────────────────────

    def set(self, key: str, value: str) -> None:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        self._db.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, value, now),
        )

    def set_many(self, pairs: dict[str, str]) -> None:
        now = datetime.datetime.now().isoformat(timespec="seconds")

        def _txn(conn) -> None:
            for key, value in pairs.items():
                conn.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                                   updated_at = excluded.updated_at
                    """,
                    (key, value, now),
                )

        self._db.execute_transaction(_txn)

    def delete(self, key: str) -> None:
        self._db.execute("DELETE FROM settings WHERE key = ?", (key,))
