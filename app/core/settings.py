"""
AppSettings — application preference model.

Preferences are stored as string key/value pairs in the settings table.
This module provides a typed wrapper that serialises/deserialises them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.repositories.settings import SettingsRepository

from app.core.scanner import SCAN_PATHS as DEFAULT_PLUGIN_PATHS
from app.core.music_software_scanner import SCAN_PATHS as DEFAULT_APP_PATHS

# ── Setting keys ─────────────────────────────────────────────────────────────

KEY_PREFERRED_DAW        = "preferred_daw"
KEY_PREFERRED_FORMATS    = "preferred_formats"
KEY_PLUGIN_SCAN_PATHS    = "plugin_scan_paths"
KEY_APP_SCAN_PATHS       = "app_scan_paths"
KEY_AUTO_LOAD_CACHE      = "auto_load_cache"
KEY_CACHE_MAX_SESSIONS   = "cache_max_sessions"

ALL_FORMATS = ["VST3", "AU", "VST", "AAX"]

DAW_OPTIONS = [
    "Logic Pro",
    "Ableton Live",
    "FL Studio",
    "Cubase",
    "Studio One",
    "Pro Tools",
    "Bitwig Studio",
    "Reaper",
    "Reason",
    "GarageBand",
    "Other",
]


@dataclass
class AppSettings:
    """Typed application preferences."""

    preferred_daw: str = ""
    preferred_formats: list[str] = field(
        default_factory=lambda: ["VST3", "AU"]
    )
    plugin_scan_paths: list[str] = field(
        default_factory=lambda: list(DEFAULT_PLUGIN_PATHS)
    )
    app_scan_paths: list[str] = field(
        default_factory=lambda: list(DEFAULT_APP_PATHS)
    )
    auto_load_cache: bool = True
    cache_max_sessions: int = 10

    # ── Persistence ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, repo: "SettingsRepository") -> "AppSettings":
        """Hydrate an :class:`AppSettings` from the settings repository."""
        raw = repo.get_all()

        preferred_daw = raw.get(KEY_PREFERRED_DAW, "")

        preferred_formats = _load_json_list(
            raw.get(KEY_PREFERRED_FORMATS, ""),
            default=["VST3", "AU"],
        )

        plugin_scan_paths = _load_json_list(
            raw.get(KEY_PLUGIN_SCAN_PATHS, ""),
            default=list(DEFAULT_PLUGIN_PATHS),
        )

        app_scan_paths = _load_json_list(
            raw.get(KEY_APP_SCAN_PATHS, ""),
            default=list(DEFAULT_APP_PATHS),
        )

        auto_load_cache = raw.get(KEY_AUTO_LOAD_CACHE, "true").lower() == "true"

        try:
            cache_max = int(raw.get(KEY_CACHE_MAX_SESSIONS, "10"))
        except ValueError:
            cache_max = 10

        return cls(
            preferred_daw=preferred_daw,
            preferred_formats=preferred_formats,
            plugin_scan_paths=plugin_scan_paths,
            app_scan_paths=app_scan_paths,
            auto_load_cache=auto_load_cache,
            cache_max_sessions=cache_max,
        )

    def save(self, repo: "SettingsRepository") -> None:
        """Persist all preferences to the settings repository."""
        repo.set_many(
            {
                KEY_PREFERRED_DAW:      self.preferred_daw,
                KEY_PREFERRED_FORMATS:  json.dumps(self.preferred_formats),
                KEY_PLUGIN_SCAN_PATHS:  json.dumps(self.plugin_scan_paths),
                KEY_APP_SCAN_PATHS:     json.dumps(self.app_scan_paths),
                KEY_AUTO_LOAD_CACHE:    str(self.auto_load_cache).lower(),
                KEY_CACHE_MAX_SESSIONS: str(self.cache_max_sessions),
            }
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_json_list(raw: str, default: list) -> list:
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else default
    except (json.JSONDecodeError, ValueError):
        return default
