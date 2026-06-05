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

from pathlib import Path

from app.core.scanner import SCAN_PATHS as DEFAULT_PLUGIN_PATHS
from app.core.music_software_scanner import SCAN_PATHS as DEFAULT_APP_PATHS

DEFAULT_QUARANTINE_FOLDER = str(
    Path.home() / "Music" / "Studio Vault Quarantine"
)

# ── Setting keys ──────────────────────────────────────────────────────────────

# Studio Preferences
KEY_USER_FULL_NAME       = "user_full_name"
KEY_PREFERRED_DAW        = "preferred_daw"
KEY_PREFERRED_FORMATS    = "preferred_formats"
KEY_MACHINE_ROLE         = "machine_role"

# Scan Settings
KEY_PLUGIN_SCAN_PATHS    = "plugin_scan_paths"
KEY_APP_SCAN_PATHS       = "app_scan_paths"
KEY_DEEP_SCAN_ENABLED    = "deep_scan_enabled"
KEY_AUTO_RESCAN_LAUNCH   = "auto_rescan_on_launch"
KEY_BACKGROUND_SCANNING  = "background_scanning"
KEY_AUTO_LOAD_CACHE      = "auto_load_cache"
KEY_CACHE_MAX_SESSIONS   = "cache_max_sessions"

# Cleanup Rules
KEY_NEVER_REMOVE_ONLY    = "never_remove_only_format"
KEY_LEGACY_VST2_SENS     = "legacy_vst2_sensitivity"
KEY_IGNORED_VENDORS      = "ignored_vendors"
KEY_SAFE_MODE_CLEANUP    = "safe_mode_cleanup"
KEY_QUARANTINE_FOLDER    = "quarantine_folder"

# Migration / Machine Settings
KEY_MACHINE_DISPLAY_NAME = "machine_display_name"
KEY_SNAPSHOT_FOLDER      = "snapshot_export_folder"
KEY_COMPARISON_BEHAVIOR  = "comparison_behavior"
KEY_READINESS_THRESHOLD  = "migration_readiness_threshold"

# UI Preferences
KEY_COMPACT_SIDEBAR      = "compact_sidebar"
KEY_REDUCED_MOTION       = "reduced_motion"
KEY_DASHBOARD_DENSITY    = "dashboard_density"
KEY_ACCENT_COLOR         = "accent_color"
KEY_THEME_PRESET         = "theme_preset"

# ── Option lists ──────────────────────────────────────────────────────────────

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

MACHINE_ROLES = [
    "Main Studio",
    "Travel Laptop",
    "Live Rig",
    "Backup Machine",
    "Custom",
]

VST2_SENSITIVITIES = ["Low", "Medium", "High"]

COMPARISON_BEHAVIORS = [
    "Match by name",
    "Match by name + version",
    "Strict path match",
]

DASHBOARD_DENSITIES = ["Comfortable", "Compact", "Spacious"]

THEME_PRESETS = ["Midnight Blue", "Deep Space", "Graphite", "Obsidian"]


# ── AppSettings dataclass ─────────────────────────────────────────────────────

@dataclass
class AppSettings:
    """Typed application preferences."""

    # Studio Preferences
    user_full_name: str = ""          # empty = fall back to OS username
    preferred_daw: str = ""
    preferred_formats: list[str] = field(default_factory=lambda: ["VST3", "AU"])
    machine_role: str = "Main Studio"

    # Scan Settings
    plugin_scan_paths: list[str] = field(
        default_factory=lambda: list(DEFAULT_PLUGIN_PATHS)
    )
    app_scan_paths: list[str] = field(
        default_factory=lambda: list(DEFAULT_APP_PATHS)
    )
    deep_scan_enabled: bool = False
    auto_rescan_on_launch: bool = False
    background_scanning: bool = False
    auto_load_cache: bool = True
    cache_max_sessions: int = 10

    # Cleanup Rules
    never_remove_only_format: bool = True
    legacy_vst2_sensitivity: str = "Medium"
    ignored_vendors: list[str] = field(default_factory=list)
    safe_mode_cleanup: bool = True
    quarantine_folder: str = ""

    # Migration / Machine Settings
    machine_display_name: str = ""
    snapshot_export_folder: str = ""
    comparison_behavior: str = "Match by name"
    migration_readiness_threshold: int = 80

    # UI Preferences
    compact_sidebar: bool = False
    reduced_motion: bool = False
    dashboard_density: str = "Comfortable"
    accent_color: str = "#6C8EF5"
    theme_preset: str = "Midnight Blue"

    # ── Persistence ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, repo: "SettingsRepository") -> "AppSettings":
        """Hydrate an :class:`AppSettings` from the settings repository."""
        raw = repo.get_all()

        return cls(
            # Studio
            user_full_name=raw.get(KEY_USER_FULL_NAME, ""),
            preferred_daw=raw.get(KEY_PREFERRED_DAW, ""),
            preferred_formats=_load_json_list(
                raw.get(KEY_PREFERRED_FORMATS, ""), default=["VST3", "AU"]
            ),
            machine_role=raw.get(KEY_MACHINE_ROLE, "Main Studio"),

            # Scan
            plugin_scan_paths=_load_json_list(
                raw.get(KEY_PLUGIN_SCAN_PATHS, ""),
                default=list(DEFAULT_PLUGIN_PATHS),
            ),
            app_scan_paths=_load_json_list(
                raw.get(KEY_APP_SCAN_PATHS, ""),
                default=list(DEFAULT_APP_PATHS),
            ),
            deep_scan_enabled=raw.get(KEY_DEEP_SCAN_ENABLED, "false").lower() == "true",
            auto_rescan_on_launch=raw.get(KEY_AUTO_RESCAN_LAUNCH, "false").lower() == "true",
            background_scanning=raw.get(KEY_BACKGROUND_SCANNING, "false").lower() == "true",
            auto_load_cache=raw.get(KEY_AUTO_LOAD_CACHE, "true").lower() == "true",
            cache_max_sessions=_load_int(raw.get(KEY_CACHE_MAX_SESSIONS, "10"), 10),

            # Cleanup
            never_remove_only_format=raw.get(KEY_NEVER_REMOVE_ONLY, "true").lower() == "true",
            legacy_vst2_sensitivity=raw.get(KEY_LEGACY_VST2_SENS, "Medium"),
            ignored_vendors=_load_json_list(raw.get(KEY_IGNORED_VENDORS, ""), default=[]),
            safe_mode_cleanup=raw.get(KEY_SAFE_MODE_CLEANUP, "true").lower() == "true",
            quarantine_folder=raw.get(KEY_QUARANTINE_FOLDER, "").strip(),

            # Migration
            machine_display_name=raw.get(KEY_MACHINE_DISPLAY_NAME, ""),
            snapshot_export_folder=raw.get(KEY_SNAPSHOT_FOLDER, ""),
            comparison_behavior=raw.get(KEY_COMPARISON_BEHAVIOR, "Match by name"),
            migration_readiness_threshold=_load_int(
                raw.get(KEY_READINESS_THRESHOLD, "80"), 80
            ),

            # UI
            compact_sidebar=raw.get(KEY_COMPACT_SIDEBAR, "false").lower() == "true",
            reduced_motion=raw.get(KEY_REDUCED_MOTION, "false").lower() == "true",
            dashboard_density=raw.get(KEY_DASHBOARD_DENSITY, "Comfortable"),
            accent_color=raw.get(KEY_ACCENT_COLOR, "#6C8EF5"),
            theme_preset=raw.get(KEY_THEME_PRESET, "Midnight Blue"),
        )

    def save(self, repo: "SettingsRepository") -> None:
        """Persist all preferences to the settings repository."""
        repo.set_many(
            {
                # Studio
                KEY_USER_FULL_NAME:       self.user_full_name,
                KEY_PREFERRED_DAW:        self.preferred_daw,
                KEY_PREFERRED_FORMATS:    json.dumps(self.preferred_formats),
                KEY_MACHINE_ROLE:         self.machine_role,

                # Scan
                KEY_PLUGIN_SCAN_PATHS:    json.dumps(self.plugin_scan_paths),
                KEY_APP_SCAN_PATHS:       json.dumps(self.app_scan_paths),
                KEY_DEEP_SCAN_ENABLED:    _bool_str(self.deep_scan_enabled),
                KEY_AUTO_RESCAN_LAUNCH:   _bool_str(self.auto_rescan_on_launch),
                KEY_BACKGROUND_SCANNING:  _bool_str(self.background_scanning),
                KEY_AUTO_LOAD_CACHE:      _bool_str(self.auto_load_cache),
                KEY_CACHE_MAX_SESSIONS:   str(self.cache_max_sessions),

                # Cleanup
                KEY_NEVER_REMOVE_ONLY:    _bool_str(self.never_remove_only_format),
                KEY_LEGACY_VST2_SENS:     self.legacy_vst2_sensitivity,
                KEY_IGNORED_VENDORS:      json.dumps(self.ignored_vendors),
                KEY_SAFE_MODE_CLEANUP:    _bool_str(self.safe_mode_cleanup),
                KEY_QUARANTINE_FOLDER:    self.quarantine_folder,

                # Migration
                KEY_MACHINE_DISPLAY_NAME: self.machine_display_name,
                KEY_SNAPSHOT_FOLDER:      self.snapshot_export_folder,
                KEY_COMPARISON_BEHAVIOR:  self.comparison_behavior,
                KEY_READINESS_THRESHOLD:  str(self.migration_readiness_threshold),

                # UI
                KEY_COMPACT_SIDEBAR:      _bool_str(self.compact_sidebar),
                KEY_REDUCED_MOTION:       _bool_str(self.reduced_motion),
                KEY_DASHBOARD_DENSITY:    self.dashboard_density,
                KEY_ACCENT_COLOR:         self.accent_color,
                KEY_THEME_PRESET:         self.theme_preset,
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


def _load_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _bool_str(value: bool) -> str:
    return "true" if value else "false"
