"""
Paths and settings.

User data lives in ``~/Library/Application Support/BAKKIS STUDIO VAULT/``:
    settings.json      user settings
    snapshots/         saved snapshots (*.studiovault, JSON)
    checklists/        tick state per migration checklist
    cache/             plug-in size cache

Tests point everything at a temp dir with the ``STUDIO_VAULT_DATA_DIR`` env var.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from studio_vault import APP_NAME

DATA_DIR_ENV = "STUDIO_VAULT_DATA_DIR"

# v1 ("Bakkis Studio Manager") data folder; snapshots there are imported on first launch.
LEGACY_DATA_DIR = Path.home() / "Library" / "Application Support" / "BakkisStudioManager"


# ── Paths ─────────────────────────────────────────────────────────────────────

def data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / APP_NAME


def snapshots_dir() -> Path:
    return data_dir() / "snapshots"


def checklists_dir() -> Path:
    return data_dir() / "checklists"


def cache_dir() -> Path:
    return data_dir() / "cache"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def bundle_dir() -> Path:
    """Folder with bundled read-only resources (web UI, images)."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "studio_vault"
    return Path(__file__).resolve().parent


def ensure_data_dirs() -> None:
    for d in (snapshots_dir(), checklists_dir(), cache_dir()):
        d.mkdir(parents=True, exist_ok=True)


# ── Settings ──────────────────────────────────────────────────────────────────

@dataclass
class Settings:
    scan_on_launch: bool = False
    auto_save_snapshot: bool = True
    extra_plugin_folders: list[str] = field(default_factory=list)
    legacy_import_done: bool = False
    welcome_seen: bool = False          # the "Hi, I'm BAKKIS" card, once on first launch


def normalize_settings(raw: dict) -> Settings:
    defaults = Settings()
    values: dict = {}
    for f in fields(Settings):
        value = raw.get(f.name, getattr(defaults, f.name))
        default = getattr(defaults, f.name)
        if isinstance(default, bool):
            value = value if isinstance(value, bool) else default
        elif isinstance(default, list):
            value = [str(v) for v in value if isinstance(v, str) and v.strip()] \
                if isinstance(value, list) else default
        values[f.name] = value
    return Settings(**values)


def load_settings() -> Settings:
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    return normalize_settings(raw if isinstance(raw, dict) else {})


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    tmp.replace(path)
