"""
Music-app repository — persist and load music software scan sessions.
"""

from __future__ import annotations

import datetime
import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.database import Database

from app.core.music_software_scanner import MusicApp


class MusicAppRepository:
    """Read/write music-app scan sessions and their results."""

    def __init__(self, db: "Database") -> None:
        self._db = db

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_scan(self, apps: list[MusicApp]) -> int:
        """
        Persist a complete scan result as a new session.
        Returns the new session id.
        """
        now = datetime.datetime.now().isoformat(timespec="seconds")
        hostname = _hostname()

        session_id_box: list[int] = []

        def _txn(conn) -> None:
            cur = conn.execute(
                """
                INSERT INTO music_app_scan_sessions
                    (scanned_at, app_count, hostname)
                VALUES (?, ?, ?)
                """,
                (now, len(apps), hostname),
            )
            sid = cur.lastrowid
            session_id_box.append(sid)

            conn.executemany(
                """
                INSERT INTO music_apps
                    (session_id, name, category, developer,
                     version, path, modified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sid,
                        a.name,
                        a.category,
                        a.developer,
                        a.version,
                        a.path,
                        a.modified,
                    )
                    for a in apps
                ],
            )

        self._db.execute_transaction(_txn)
        return session_id_box[0] if session_id_box else -1

    # ── Read ──────────────────────────────────────────────────────────────────

    def load_latest(self) -> tuple[list[MusicApp], str | None]:
        """
        Return ``(apps, scanned_at)`` for the most recent session,
        or ``([], None)`` when no sessions exist.
        """
        row = self._db.query(
            "SELECT id, scanned_at FROM music_app_scan_sessions ORDER BY id DESC LIMIT 1"
        )
        if not row:
            return [], None

        session_id = row[0]["id"]
        scanned_at = row[0]["scanned_at"]

        app_rows = self._db.query(
            "SELECT name, category, developer, version, path, modified "
            "FROM music_apps WHERE session_id = ? ORDER BY category, name",
            (session_id,),
        )

        apps = [
            MusicApp(
                name=r["name"],
                category=r["category"],
                developer=r["developer"],
                version=r["version"],
                path=r["path"],
                modified=r["modified"],
            )
            for r in app_rows
        ]
        return apps, scanned_at

    def get_session_count(self) -> int:
        row = self._db.query("SELECT COUNT(*) AS n FROM music_app_scan_sessions")
        return row[0]["n"] if row else 0

    def list_sessions(self) -> list[dict]:
        rows = self._db.query(
            "SELECT id, scanned_at, app_count, hostname "
            "FROM music_app_scan_sessions ORDER BY id DESC"
        )
        return [dict(r) for r in rows]

    def clear_all(self) -> None:
        self._db.execute("DELETE FROM music_app_scan_sessions")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""
