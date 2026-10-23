"""
Studio Snapshots — export, import, and compare studio setups across machines.

Read-only: no files are moved, no plugins are modified, no cloud sync.

Snapshots are stored as JSON in:
    ~/Library/Application Support/BakkisStudioManager/snapshots/

JSON Schema (schema_version = 1)
---------------------------------
{
  "schema_version": 1,
  "machine_name": "My Mac Studio",
  "machine_id": "<UUID or IOPlatformUUID>",
  "scan_date": "2026-06-05T10:00:00",
  "app_version": "1.0.0",
  "plugins": [
    {
      "name": "Serum",
      "developer": "Xfer Records",
      "version": "1.35",
      "fmt": "VST3",
      "path": "/Library/Audio/Plug-Ins/VST3/Serum.vst3",
      "size": 12345678,
      "modified": "2025-11-01"
    }
  ],
  "music_software": [
    { "name": "Logic Pro", "version": "11.0", "category": "DAW", "path": "/Applications/Logic Pro.app" }
  ],
  "hardware": [
    { "name": "Focusrite Scarlett 2i2", "vendor": "Focusrite", "device_type": "Audio Interface", "connection_type": "USB" }
  ],
  "summary": {
    "total_plugins": 142,
    "total_software": 12,
    "total_hardware": 3,
    "plugin_formats": { "VST3": 90, "AU": 45, "VST": 7 }
  }
}
"""

from __future__ import annotations

import datetime
import json
import re
import socket
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.scanner import Plugin
    from app.core.music_software_scanner import MusicApp
    from app.core.hardware_scanner import HardwareDevice

# ── Storage ───────────────────────────────────────────────────────────────────

SNAPSHOTS_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "BakkisStudioManager"
    / "snapshots"
)
SCHEMA_VERSION = 1


# ── Helper: app version ───────────────────────────────────────────────────────

def _app_version() -> str:
    try:
        from importlib.metadata import version
        return version("bakkis-studio-manager")
    except Exception:
        return ""


# ── Helper: stable machine UUID ───────────────────────────────────────────────

def _machine_id() -> str:
    """Return the macOS IOPlatformUUID, falling back to a random UUID."""
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                parts = line.split('"')
                if len(parts) >= 4:
                    return parts[-2]
    except Exception:
        pass
    return str(uuid.uuid4())


# ── Helper: normalise plugin name for comparison ──────────────────────────────

def _plugin_key(name: str) -> str:
    """Strip trailing format suffixes and lowercase for stable comparison keys."""
    key = re.sub(
        r"[\s_\-]*(vst3?|au|aax)\s*$", "", name, flags=re.IGNORECASE
    ).strip().lower()
    return key or name.lower()


# ── Snapshot data models ──────────────────────────────────────────────────────

@dataclass
class SnapshotPlugin:
    name: str
    developer: str
    version: str
    fmt: str
    path: str
    size: int
    modified: str

    def to_dict(self) -> dict:
        return {
            "name":      self.name,
            "developer": self.developer,
            "version":   self.version,
            "fmt":       self.fmt,
            "path":      self.path,
            "size":      self.size,
            "modified":  self.modified,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SnapshotPlugin":
        return cls(
            name=d.get("name", ""),
            developer=d.get("developer", ""),
            version=d.get("version", ""),
            fmt=d.get("fmt", ""),
            path=d.get("path", ""),
            size=d.get("size", 0),
            modified=d.get("modified", ""),
        )


@dataclass
class SnapshotSoftware:
    name: str
    version: str
    category: str
    path: str

    def to_dict(self) -> dict:
        return {
            "name":     self.name,
            "version":  self.version,
            "category": self.category,
            "path":     self.path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SnapshotSoftware":
        return cls(
            name=d.get("name", ""),
            version=d.get("version", ""),
            category=d.get("category", ""),
            path=d.get("path", ""),
        )


@dataclass
class SnapshotHardware:
    name: str
    vendor: str
    device_type: str
    connection_type: str

    def to_dict(self) -> dict:
        return {
            "name":            self.name,
            "vendor":          self.vendor,
            "device_type":     self.device_type,
            "connection_type": self.connection_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SnapshotHardware":
        return cls(
            name=d.get("name", ""),
            vendor=d.get("vendor", ""),
            device_type=d.get("device_type", ""),
            connection_type=d.get("connection_type", ""),
        )


@dataclass
class SnapshotSummary:
    total_plugins: int
    total_software: int
    total_hardware: int
    plugin_formats: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "total_plugins":  self.total_plugins,
            "total_software": self.total_software,
            "total_hardware": self.total_hardware,
            "plugin_formats": self.plugin_formats,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SnapshotSummary":
        return cls(
            total_plugins=d.get("total_plugins", 0),
            total_software=d.get("total_software", 0),
            total_hardware=d.get("total_hardware", 0),
            plugin_formats=d.get("plugin_formats", {}),
        )


@dataclass
class StudioSnapshot:
    schema_version: int
    machine_name: str
    machine_id: str
    scan_date: str
    app_version: str
    plugins: list[SnapshotPlugin]
    music_software: list[SnapshotSoftware]
    hardware: list[SnapshotHardware]
    summary: SnapshotSummary

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "machine_name":   self.machine_name,
            "machine_id":     self.machine_id,
            "scan_date":      self.scan_date,
            "app_version":    self.app_version,
            "plugins":        [p.to_dict() for p in self.plugins],
            "music_software": [s.to_dict() for s in self.music_software],
            "hardware":       [h.to_dict() for h in self.hardware],
            "summary":        self.summary.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StudioSnapshot":
        return cls(
            schema_version=d.get("schema_version", 1),
            machine_name=d.get("machine_name", ""),
            machine_id=d.get("machine_id", ""),
            scan_date=d.get("scan_date", ""),
            app_version=d.get("app_version", ""),
            plugins=[SnapshotPlugin.from_dict(p) for p in d.get("plugins", [])],
            music_software=[SnapshotSoftware.from_dict(s) for s in d.get("music_software", [])],
            hardware=[SnapshotHardware.from_dict(h) for h in d.get("hardware", [])],
            summary=SnapshotSummary.from_dict(d.get("summary", {})),
        )

    @property
    def display_date(self) -> str:
        try:
            dt = datetime.datetime.fromisoformat(self.scan_date)
            return dt.strftime("%b %d, %Y  %H:%M")
        except Exception:
            return self.scan_date


# ── Comparison models ─────────────────────────────────────────────────────────

@dataclass
class PluginDiff:
    name: str
    developer: str
    fmt: str
    local_version: str = ""
    other_version: str = ""
    local_path: str = ""
    other_path: str = ""
    diff_type: str = ""
    # diff_type values: "missing_locally" | "missing_on_other" | "version_diff" | "format_diff"


@dataclass
class SoftwareDiff:
    name: str
    category: str
    local_version: str = ""
    other_version: str = ""
    diff_type: str = ""
    # diff_type values: "missing_locally" | "missing_on_other" | "version_diff"


@dataclass
class HardwareDiff:
    name: str
    vendor: str
    device_type: str
    diff_type: str = ""
    # diff_type values: "missing_locally" | "missing_on_other"


@dataclass
class SnapshotComparison:
    local_snapshot: StudioSnapshot
    other_snapshot: StudioSnapshot
    plugins_missing_locally: list[PluginDiff]  = field(default_factory=list)
    plugins_missing_on_other: list[PluginDiff] = field(default_factory=list)
    plugin_version_diffs: list[PluginDiff]     = field(default_factory=list)
    plugin_format_diffs: list[PluginDiff]      = field(default_factory=list)
    software_diffs: list[SoftwareDiff]         = field(default_factory=list)
    hardware_diffs: list[HardwareDiff]         = field(default_factory=list)

    @property
    def has_differences(self) -> bool:
        return bool(
            self.plugins_missing_locally
            or self.plugins_missing_on_other
            or self.plugin_version_diffs
            or self.plugin_format_diffs
            or self.software_diffs
            or self.hardware_diffs
        )

    @property
    def total_differences(self) -> int:
        return (
            len(self.plugins_missing_locally)
            + len(self.plugins_missing_on_other)
            + len(self.plugin_version_diffs)
            + len(self.plugin_format_diffs)
            + len(self.software_diffs)
            + len(self.hardware_diffs)
        )


# ── Snapshot creation ─────────────────────────────────────────────────────────

def export_snapshot(
    plugins: "list[Plugin]",
    music_apps: "list[MusicApp]",
    hardware_devices: "list[HardwareDevice] | None" = None,
    machine_name: str = "",
) -> StudioSnapshot:
    """Build a StudioSnapshot from current scan data. Pure function — no I/O."""
    snap_plugins = [
        SnapshotPlugin(
            name=p.name,
            developer=p.developer,
            version=p.version,
            fmt=p.fmt,
            path=p.path,
            size=p.file_size,
            modified=p.modified,
        )
        for p in plugins
    ]

    snap_software = [
        SnapshotSoftware(
            name=a.name,
            version=getattr(a, "version", ""),
            category=getattr(a, "category", ""),
            path=getattr(a, "path", ""),
        )
        for a in music_apps
    ]

    snap_hardware: list[SnapshotHardware] = []
    if hardware_devices:
        snap_hardware = [
            SnapshotHardware(
                name=d.name,
                vendor=d.vendor,
                device_type=d.device_type,
                connection_type=d.connection_type,
            )
            for d in hardware_devices
        ]

    fmt_counts: dict[str, int] = {}
    for p in snap_plugins:
        fmt_counts[p.fmt] = fmt_counts.get(p.fmt, 0) + 1

    summary = SnapshotSummary(
        total_plugins=len(snap_plugins),
        total_software=len(snap_software),
        total_hardware=len(snap_hardware),
        plugin_formats=fmt_counts,
    )

    return StudioSnapshot(
        schema_version=SCHEMA_VERSION,
        machine_name=machine_name or socket.gethostname(),
        machine_id=_machine_id(),
        scan_date=datetime.datetime.now().isoformat(timespec="seconds"),
        app_version=_app_version(),
        plugins=snap_plugins,
        music_software=snap_software,
        hardware=snap_hardware,
        summary=summary,
    )


def save_snapshot(snapshot: StudioSnapshot, dest: Path | None = None) -> Path:
    """
    Persist snapshot JSON. If *dest* is a full file path, saves there.
    Otherwise saves to the default SNAPSHOTS_DIR with an auto-generated name.
    Returns the path of the saved file.
    """
    if dest and dest.suffix.lower() == ".json":
        folder = dest.parent
        path = dest
    else:
        folder = dest or SNAPSHOTS_DIR
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", snapshot.machine_name)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = folder / f"snapshot_{safe_name}_{ts}.json"

    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_snapshot(path: Path) -> StudioSnapshot:
    """Load and deserialise a snapshot JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return StudioSnapshot.from_dict(data)


def list_saved_snapshots() -> list[Path]:
    """Return snapshot JSON paths in SNAPSHOTS_DIR, newest first."""
    if not SNAPSHOTS_DIR.exists():
        return []
    return sorted(
        SNAPSHOTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


# ── Comparison ────────────────────────────────────────────────────────────────

def compare_snapshots(
    local: StudioSnapshot,
    other: StudioSnapshot,
) -> SnapshotComparison:
    """
    Compare *local* snapshot against *other* (imported machine).

    Plugin matching uses (normalised_name, fmt) as the primary key so that
    'Serum.vst3' and 'Serum VST3' both resolve to the same product.
    """
    result = SnapshotComparison(local_snapshot=local, other_snapshot=other)

    # ── Plugin lookups ────────────────────────────────────────────────────────

    local_by_key: dict[tuple[str, str], SnapshotPlugin] = {
        (_plugin_key(p.name), p.fmt): p for p in local.plugins
    }
    other_by_key: dict[tuple[str, str], SnapshotPlugin] = {
        (_plugin_key(p.name), p.fmt): p for p in other.plugins
    }

    local_by_name: dict[str, list[SnapshotPlugin]] = {}
    for p in local.plugins:
        local_by_name.setdefault(_plugin_key(p.name), []).append(p)

    other_by_name: dict[str, list[SnapshotPlugin]] = {}
    for p in other.plugins:
        other_by_name.setdefault(_plugin_key(p.name), []).append(p)

    # Missing locally: exists on other but not locally (exact name+fmt)
    for key, op in other_by_key.items():
        if key not in local_by_key:
            result.plugins_missing_locally.append(PluginDiff(
                name=op.name,
                developer=op.developer,
                fmt=op.fmt,
                other_version=op.version,
                other_path=op.path,
                diff_type="missing_locally",
            ))

    # Missing on other: exists locally but not on other (exact name+fmt)
    for key, lp in local_by_key.items():
        if key not in other_by_key:
            result.plugins_missing_on_other.append(PluginDiff(
                name=lp.name,
                developer=lp.developer,
                fmt=lp.fmt,
                local_version=lp.version,
                local_path=lp.path,
                diff_type="missing_on_other",
            ))

    # Version differences: same name+fmt, different non-empty version strings
    for key in set(local_by_key) & set(other_by_key):
        lp = local_by_key[key]
        op = other_by_key[key]
        if lp.version and op.version and lp.version != op.version:
            result.plugin_version_diffs.append(PluginDiff(
                name=lp.name,
                developer=lp.developer,
                fmt=lp.fmt,
                local_version=lp.version,
                other_version=op.version,
                local_path=lp.path,
                other_path=op.path,
                diff_type="version_diff",
            ))

    # Format differences: same product name, different set of formats
    for name_key in set(local_by_name) & set(other_by_name):
        local_fmts = {p.fmt for p in local_by_name[name_key]}
        other_fmts = {p.fmt for p in other_by_name[name_key]}
        if local_fmts != other_fmts:
            rep_l = local_by_name[name_key][0]
            rep_o = other_by_name[name_key][0]
            result.plugin_format_diffs.append(PluginDiff(
                name=rep_l.name,
                developer=rep_l.developer,
                fmt=f"{', '.join(sorted(local_fmts))}  →  {', '.join(sorted(other_fmts))}",
                local_version=rep_l.version,
                other_version=rep_o.version,
                diff_type="format_diff",
            ))

    # ── Software diffs ────────────────────────────────────────────────────────

    local_sw: dict[str, SnapshotSoftware] = {
        s.name.lower(): s for s in local.music_software
    }
    other_sw: dict[str, SnapshotSoftware] = {
        s.name.lower(): s for s in other.music_software
    }

    for name, o_sw in other_sw.items():
        if name not in local_sw:
            result.software_diffs.append(SoftwareDiff(
                name=o_sw.name,
                category=o_sw.category,
                other_version=o_sw.version,
                diff_type="missing_locally",
            ))
        elif local_sw[name].version != o_sw.version:
            l_sw = local_sw[name]
            result.software_diffs.append(SoftwareDiff(
                name=l_sw.name,
                category=l_sw.category,
                local_version=l_sw.version,
                other_version=o_sw.version,
                diff_type="version_diff",
            ))

    for name, l_sw in local_sw.items():
        if name not in other_sw:
            result.software_diffs.append(SoftwareDiff(
                name=l_sw.name,
                category=l_sw.category,
                local_version=l_sw.version,
                diff_type="missing_on_other",
            ))

    # ── Hardware diffs ────────────────────────────────────────────────────────

    local_hw: dict[str, SnapshotHardware] = {
        d.name.lower(): d for d in local.hardware
    }
    other_hw: dict[str, SnapshotHardware] = {
        d.name.lower(): d for d in other.hardware
    }

    for name, o_hw in other_hw.items():
        if name not in local_hw:
            result.hardware_diffs.append(HardwareDiff(
                name=o_hw.name,
                vendor=o_hw.vendor,
                device_type=o_hw.device_type,
                diff_type="missing_locally",
            ))

    for name, l_hw in local_hw.items():
        if name not in other_hw:
            result.hardware_diffs.append(HardwareDiff(
                name=l_hw.name,
                vendor=l_hw.vendor,
                device_type=l_hw.device_type,
                diff_type="missing_on_other",
            ))

    return result
