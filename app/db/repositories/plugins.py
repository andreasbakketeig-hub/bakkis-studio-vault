"""
Plugin repository — persist and load plugin scan sessions.
"""

from __future__ import annotations

import datetime
import json
import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.database import Database

from app.core.scanner import Plugin


class PluginRepository:
    """Read/write plugin scan sessions and their results."""

    def __init__(self, db: "Database") -> None:
        self._db = db

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_scan(
        self,
        plugins: list[Plugin],
        scan_paths: list[str] | None = None,
    ) -> int:
        """
        Persist a complete scan result as a new session.
        Returns the new session id.
        """
        now = datetime.datetime.now().isoformat(timespec="seconds")
        hostname = _hostname()
        paths_json = json.dumps(scan_paths or [])

        session_id_box: list[int] = []

        def _txn(conn) -> None:
            cur = conn.execute(
                """
                INSERT INTO plugin_scan_sessions
                    (scanned_at, plugin_count, hostname, scan_paths)
                VALUES (?, ?, ?, ?)
                """,
                (now, len(plugins), hostname, paths_json),
            )
            sid = cur.lastrowid
            session_id_box.append(sid)

            conn.executemany(
                """
                INSERT INTO plugins
                    (session_id, name, fmt, path, version, developer,
                     file_size, modified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sid,
                        p.name,
                        p.fmt,
                        p.path,
                        p.version,
                        p.developer,
                        p.file_size,
                        p.modified,
                    )
                    for p in plugins
                ],
            )

        self._db.execute_transaction(_txn)
        return session_id_box[0] if session_id_box else -1

    # ── Read ──────────────────────────────────────────────────────────────────

    def load_latest(self) -> tuple[list[Plugin], str | None]:
        """
        Return ``(plugins, scanned_at)`` for the most recent session,
        or ``([], None)`` when no sessions exist.
        """
        row = self._db.query(
            "SELECT id, scanned_at FROM plugin_scan_sessions ORDER BY id DESC LIMIT 1"
        )
        if not row:
            return [], None

        session_id = row[0]["id"]
        scanned_at = row[0]["scanned_at"]

        plugin_rows = self._db.query(
            "SELECT name, fmt, path, version, developer, file_size, modified "
            "FROM plugins WHERE session_id = ? ORDER BY name",
            (session_id,),
        )

        plugins = [
            Plugin(
                name=r["name"],
                fmt=r["fmt"],
                path=r["path"],
                version=r["version"],
                developer=r["developer"],
                file_size=r["file_size"],
                modified=r["modified"],
            )
            for r in plugin_rows
        ]
        return plugins, scanned_at

    def get_session_count(self) -> int:
        row = self._db.query("SELECT COUNT(*) AS n FROM plugin_scan_sessions")
        return row[0]["n"] if row else 0

    def list_sessions(self) -> list[dict]:
        """Return all sessions (newest first) as plain dicts."""
        rows = self._db.query(
            "SELECT id, scanned_at, plugin_count, hostname "
            "FROM plugin_scan_sessions ORDER BY id DESC"
        )
        return [dict(r) for r in rows]

    def delete_session(self, session_id: int) -> None:
        self._db.execute(
            "DELETE FROM plugin_scan_sessions WHERE id = ?", (session_id,)
        )

    def clear_all(self) -> None:
        self._db.execute("DELETE FROM plugin_scan_sessions")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""
