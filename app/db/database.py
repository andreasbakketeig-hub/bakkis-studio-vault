"""
Database — SQLite connection manager with schema init and versioning.

The database file lives at:
    ~/Library/Application Support/BakkisStudioManager/studio.db

All access goes through a single sqlite3 connection kept open for the
lifetime of the application.  WAL mode is enabled for better concurrency
between the main thread and background scan threads.
"""

from __future__ import annotations

import datetime
import sqlite3
import threading
from pathlib import Path

from app.db.schema import (
    SCHEMA_VERSION,
    create_initial_schema,
    run_migrations,
)

DEFAULT_DB_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "BakkisStudioManager"
    / "studio.db"
)


class Database:
    """
    Lightweight wrapper around a sqlite3 connection.

    Thread safety: a ``threading.Lock`` serialises every write operation so
    that background scan threads can save results without racing.
    """

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection = self._open()
        self._lock = threading.Lock()
        self._init_schema()

    # ── Connection ────────────────────────────────────────────────────────────

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── Schema bootstrap ──────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._lock:
            current = self._read_schema_version()

            if current == 0:
                # Brand-new database
                create_initial_schema(self._conn)
                self._conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.datetime.now().isoformat()),
                )
                self._conn.commit()
            elif current < SCHEMA_VERSION:
                new_version = run_migrations(self._conn, current)
                self._conn.commit()
                current = new_version

    def _read_schema_version(self) -> int:
        try:
            row = self._conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return int(row["version"]) if row else 0
        except sqlite3.OperationalError:
            # schema_version table doesn't exist yet
            return 0

    # ── Low-level helpers (used by repositories) ──────────────────────────────

    def execute(
        self,
        sql: str,
        params: tuple | list = (),
    ) -> sqlite3.Cursor:
        """Execute a single statement (auto-commits inside a write lock)."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def executemany(
        self,
        sql: str,
        params_seq: list[tuple | list],
    ) -> None:
        """Execute a statement for each row in *params_seq*."""
        with self._lock:
            self._conn.executemany(sql, params_seq)
            self._conn.commit()

    def query(
        self,
        sql: str,
        params: tuple | list = (),
    ) -> list[sqlite3.Row]:
        """Read-only query; no locking needed for SELECT."""
        return self._conn.execute(sql, params).fetchall()

    def execute_transaction(self, fn) -> None:
        """
        Execute *fn(conn)* inside an explicit transaction under the write lock.
        Rolls back automatically on any exception.
        """
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                fn(self._conn)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
