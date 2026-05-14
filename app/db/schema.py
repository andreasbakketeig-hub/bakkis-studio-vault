"""
SQLite schema DDL and version metadata.

Bump SCHEMA_VERSION and add a migration step to _MIGRATIONS whenever the
schema changes.  Each migration receives the sqlite3 connection and must
be idempotent.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION: int = 1

# ── Initial schema (v0 → v1) ──────────────────────────────────────────────────

_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT    NOT NULL
);
"""

_CREATE_PLUGIN_SESSIONS = """
CREATE TABLE IF NOT EXISTS plugin_scan_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at  TEXT    NOT NULL,
    plugin_count INTEGER NOT NULL DEFAULT 0,
    hostname    TEXT    NOT NULL DEFAULT '',
    scan_paths  TEXT    NOT NULL DEFAULT '[]'
);
"""

_CREATE_PLUGINS = """
CREATE TABLE IF NOT EXISTS plugins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL
               REFERENCES plugin_scan_sessions(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    fmt        TEXT    NOT NULL,
    path       TEXT    NOT NULL,
    version    TEXT    NOT NULL DEFAULT '',
    developer  TEXT    NOT NULL DEFAULT '',
    file_size  INTEGER NOT NULL DEFAULT 0,
    modified   TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_PLUGINS_IDX = """
CREATE INDEX IF NOT EXISTS idx_plugins_session
    ON plugins (session_id);
"""

_CREATE_MUSIC_APP_SESSIONS = """
CREATE TABLE IF NOT EXISTS music_app_scan_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at TEXT    NOT NULL,
    app_count  INTEGER NOT NULL DEFAULT 0,
    hostname   TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_MUSIC_APPS = """
CREATE TABLE IF NOT EXISTS music_apps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL
               REFERENCES music_app_scan_sessions(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    developer  TEXT    NOT NULL DEFAULT '',
    version    TEXT    NOT NULL DEFAULT '',
    path       TEXT    NOT NULL,
    modified   TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_MUSIC_APPS_IDX = """
CREATE INDEX IF NOT EXISTS idx_music_apps_session
    ON music_apps (session_id);
"""

_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_INITIAL_TABLES: list[str] = [
    _CREATE_SCHEMA_VERSION,
    _CREATE_PLUGIN_SESSIONS,
    _CREATE_PLUGINS,
    _CREATE_PLUGINS_IDX,
    _CREATE_MUSIC_APP_SESSIONS,
    _CREATE_MUSIC_APPS,
    _CREATE_MUSIC_APPS_IDX,
    _CREATE_SETTINGS,
]


def create_initial_schema(conn: sqlite3.Connection) -> None:
    """Create all tables for a brand-new database."""
    for stmt in _INITIAL_TABLES:
        conn.execute(stmt)


# ── Migration registry ────────────────────────────────────────────────────────
# Each entry: (target_version, callable(conn) -> None)
# Add new entries here as the schema evolves.

_MIGRATIONS: list[tuple[int, object]] = [
    # Example for a future migration:
    # (2, _migrate_v1_to_v2),
]


def run_migrations(
    conn: sqlite3.Connection,
    current_version: int,
) -> int:
    """
    Apply all pending migrations in order.
    Returns the new schema version.
    """
    import datetime

    version = current_version
    for target, fn in _MIGRATIONS:
        if version < target:
            fn(conn)  # type: ignore[operator]
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (target, datetime.datetime.now().isoformat()),
            )
            version = target
    return version
