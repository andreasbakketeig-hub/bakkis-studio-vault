"""
Studio snapshots — schema v2, save/load/list, import of both v1 formats.

A snapshot is one JSON file (``*.studiovault``) holding everything found in a
scan. Snapshots are private by construction so they can be shared as-is:

- paths under a home folder are stored as ``~/…`` (no macOS user names)
- the machine id is a one-way hash of the IOPlatformUUID, never the raw value
- no serials, license notes or Keychain data are ever written here

File layout (schema_version 2):

    {
      "format": "bakkis-studio-vault-snapshot",
      "schema_version": 2,
      "id": "3f2a…",                       # random, unique per snapshot
      "name": "Studio Mac — before upgrade",
      "machine_name": "Studio Mac",
      "machine_id": "9c1e…",               # sha256 hash, 16 hex chars
      "created_at": "2026-10-23T14:05:00",
      "app_version": "2.0.0",
      "macos_version": "27.0",
      "source": "scan" | "import-v1",
      "plugins":  [{"name", "fmt", "developer", "version", "bundle_id", "size", "modified", "path", "kind"}],
      "apps":     [{"name", "category", "developer", "version", "path"}],
      "hardware": [{"name", "vendor", "device_type", "connection_type"}]
    }
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
import re
import subprocess
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from studio_vault import __version__, config

FORMAT_ID = "bakkis-studio-vault-snapshot"
SCHEMA_VERSION = 2
FILE_SUFFIX = ".studiovault"

SOURCE_SCAN = "scan"
SOURCE_IMPORT_V1 = "import-v1"

_MACHINE_ID_SALT = "bakkis-studio-vault:"


class SnapshotError(Exception):
    """Raised for files that are not readable snapshots."""


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SnapPlugin:
    name: str
    fmt: str
    developer: str = ""
    version: str = ""
    bundle_id: str = ""
    size: int = 0
    modified: str = ""
    path: str = ""
    kind: str = ""          # Instrument | Effect | MIDI | ""


@dataclass(frozen=True)
class SnapApp:
    name: str
    category: str = ""
    developer: str = ""
    version: str = ""
    path: str = ""


@dataclass(frozen=True)
class SnapHardware:
    name: str
    vendor: str = ""
    device_type: str = ""
    connection_type: str = ""


@dataclass
class Snapshot:
    id: str
    name: str
    machine_name: str
    machine_id: str
    created_at: str
    app_version: str = __version__
    macos_version: str = ""
    source: str = SOURCE_SCAN
    plugins: list[SnapPlugin] = field(default_factory=list)
    apps: list[SnapApp] = field(default_factory=list)
    hardware: list[SnapHardware] = field(default_factory=list)

    @property
    def plugin_formats(self) -> dict[str, int]:
        return dict(Counter(p.fmt for p in self.plugins))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {"format": FORMAT_ID, "schema_version": SCHEMA_VERSION, **data}


@dataclass(frozen=True)
class SnapshotInfo:
    """Lightweight listing entry (what the Snapshots screen shows)."""

    path: Path
    id: str
    name: str
    machine_name: str
    created_at: str
    plugin_count: int
    app_count: int
    hardware_count: int
    is_this_mac: bool


# ── Privacy helpers ───────────────────────────────────────────────────────────

_HOME_PREFIX = re.compile(r"^/Users/[^/]+(?=/|$)")


def scrub_path(path: str) -> str:
    """Replace any home folder prefix (``/Users/<name>``) with ``~``."""
    return _HOME_PREFIX.sub("~", path or "")


def hash_machine_id(raw: str) -> str:
    return hashlib.sha256((_MACHINE_ID_SALT + raw).encode("utf-8")).hexdigest()[:16]


_this_machine_id: str | None = None


def this_machine_id() -> str:
    """Hashed IOPlatformUUID of this Mac ("" when it cannot be read)."""
    global _this_machine_id
    if _this_machine_id is None:
        raw = ""
        try:
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5, check=False,
            ).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            raw = m.group(1) if m else ""
        except (OSError, subprocess.TimeoutExpired):
            pass
        _this_machine_id = hash_machine_id(raw) if raw else ""
    return _this_machine_id


def this_machine_name() -> str:
    """The Mac's user-visible name (System Settings → General → Sharing)."""
    try:
        name = subprocess.run(
            ["scutil", "--get", "ComputerName"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        if name:
            return name
    except (OSError, subprocess.TimeoutExpired):
        pass
    return platform.node().removesuffix(".local") or "Mac"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ── Creating snapshots ────────────────────────────────────────────────────────

def from_scan(
    plugins: Iterable[Any],
    apps: Iterable[Any],
    hardware: Iterable[Any],
    name: str = "",
) -> Snapshot:
    """Build a snapshot from scanner results (scanners.plugins/apps/hardware objects)."""
    machine = this_machine_name()
    return Snapshot(
        id=uuid.uuid4().hex,
        name=name.strip() or machine,
        machine_name=machine,
        machine_id=this_machine_id(),
        created_at=_now(),
        macos_version=platform.mac_ver()[0],
        source=SOURCE_SCAN,
        plugins=sorted(
            (SnapPlugin(
                name=p.name, fmt=p.fmt, developer=p.developer, version=p.version,
                bundle_id=getattr(p, "bundle_id", ""), size=p.file_size,
                modified=p.modified, path=scrub_path(p.path), kind=getattr(p, "kind", ""),
            ) for p in plugins),
            key=lambda p: (p.name.lower(), p.fmt),
        ),
        apps=sorted(
            (SnapApp(
                name=a.name, category=a.category, developer=a.developer,
                version=a.version, path=scrub_path(a.path),
            ) for a in apps),
            key=lambda a: a.name.lower(),
        ),
        hardware=sorted(
            (SnapHardware(
                name=h.name, vendor=h.vendor, device_type=h.device_type,
                connection_type=h.connection_type,
            ) for h in hardware),
            key=lambda h: h.name.lower(),
        ),
    )


# ── Parsing (v2 + both v1 formats) ────────────────────────────────────────────

def _s(d: dict, key: str, default: str = "") -> str:
    value = d.get(key, default)
    return value.strip() if isinstance(value, str) else default


def _i(d: dict, key: str) -> int:
    value = d.get(key, 0)
    return value if isinstance(value, int) and value >= 0 else 0


def _dicts(value: Any) -> list[dict]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _plugin(d: dict) -> SnapPlugin:
    return SnapPlugin(
        name=_s(d, "name"), fmt=_s(d, "fmt"), developer=_s(d, "developer"),
        version=_s(d, "version"), bundle_id=_s(d, "bundle_id"),
        size=_i(d, "size") or _i(d, "file_size"), modified=_s(d, "modified"),
        path=scrub_path(_s(d, "path")), kind=_s(d, "kind"),
    )


def _app(d: dict) -> SnapApp:
    return SnapApp(
        name=_s(d, "name"), category=_s(d, "category"), developer=_s(d, "developer"),
        version=_s(d, "version"), path=scrub_path(_s(d, "path")),
    )


def _hardware(d: dict) -> SnapHardware:
    return SnapHardware(
        name=_s(d, "name"), vendor=_s(d, "vendor"),
        device_type=_s(d, "device_type"), connection_type=_s(d, "connection_type"),
    )


def _clean_machine_id(raw: str) -> str:
    """v2 ids are already hashed (16 hex); anything else (v1 raw UUID) gets hashed."""
    if re.fullmatch(r"[0-9a-f]{16}", raw):
        return raw
    return hash_machine_id(raw) if raw else ""


def parse(data: Any) -> Snapshot:
    """Turn decoded JSON (v2, v1 Studio Snapshots, or v1 Migration Assistant) into a Snapshot."""
    if not isinstance(data, dict):
        raise SnapshotError("Not a snapshot file.")

    if data.get("format") == FORMAT_ID:
        version = data.get("schema_version")
        if not isinstance(version, int) or version > SCHEMA_VERSION:
            raise SnapshotError("This snapshot was made by a newer version of the app.")
        return Snapshot(
            id=_s(data, "id") or uuid.uuid4().hex,
            name=_s(data, "name") or _s(data, "machine_name") or "Snapshot",
            machine_name=_s(data, "machine_name"),
            machine_id=_clean_machine_id(_s(data, "machine_id")),
            created_at=_s(data, "created_at"),
            app_version=_s(data, "app_version"),
            macos_version=_s(data, "macos_version"),
            source=_s(data, "source") or SOURCE_SCAN,
            plugins=[_plugin(p) for p in _dicts(data.get("plugins"))],
            apps=[_app(a) for a in _dicts(data.get("apps"))],
            hardware=[_hardware(h) for h in _dicts(data.get("hardware"))],
        )

    # v1 "Studio Snapshots" (app/core/studio_snapshots.py, schema_version 1)
    if data.get("schema_version") == 1 and "machine_name" in data:
        machine = _s(data, "machine_name") or "Mac"
        return Snapshot(
            id=_content_id(data),
            name=machine,
            machine_name=machine,
            machine_id=_clean_machine_id(_s(data, "machine_id")),
            created_at=_s(data, "scan_date"),
            app_version=_s(data, "app_version"),
            source=SOURCE_IMPORT_V1,
            plugins=[_plugin(p) for p in _dicts(data.get("plugins"))],
            apps=[_app(a) for a in _dicts(data.get("music_software"))],
            hardware=[_hardware(h) for h in _dicts(data.get("hardware"))],
        )

    # v1 "Migration Assistant" (app/core/migration_assistant.py, no schema_version)
    if "created_at" in data and "hostname" in data and "schema_version" not in data:
        # v1 appended a role as "Name  [Role]"; keep it in the label only.
        label = _s(data, "hostname") or "Mac"
        machine = re.sub(r"\s+\[[^\]]*\]$", "", label) or label
        return Snapshot(
            id=_content_id(data),
            name=label,
            machine_name=machine,
            machine_id="",
            created_at=_s(data, "created_at"),
            app_version="",
            source=SOURCE_IMPORT_V1,
            plugins=[_plugin(p) for p in _dicts(data.get("plugins"))],
            apps=[_app(a) for a in _dicts(data.get("apps"))],
            hardware=[],
        )

    raise SnapshotError("Not a snapshot file.")


def _content_id(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def load(path: Path | str) -> Snapshot:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SnapshotError(f"Could not read {Path(path).name}: {exc}") from exc
    return parse(data)


# ── Storage ───────────────────────────────────────────────────────────────────

def _file_name(snapshot: Snapshot) -> str:
    stamp = re.sub(r"[^0-9]", "", snapshot.created_at)[:14] or "00000000000000"
    label = re.sub(r"[^A-Za-z0-9]+", "-", snapshot.name).strip("-")[:40] or "snapshot"
    return f"{stamp}_{label}_{snapshot.id[:6]}{FILE_SUFFIX}"


def write(snapshot: Snapshot, dest: Path) -> Path:
    """Write *snapshot* to *dest* atomically and return the path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(snapshot.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return dest


def save(snapshot: Snapshot) -> Path:
    """Store *snapshot* in the app's snapshots folder."""
    return write(snapshot, config.snapshots_dir() / _file_name(snapshot))


def export(snapshot: Snapshot, dest: Path) -> Path:
    """Write a copy for sharing (AirDrop, iCloud, USB). Adds the file suffix if missing."""
    if dest.suffix != FILE_SUFFIX:
        dest = dest.with_name(dest.name + FILE_SUFFIX)
    return write(snapshot, dest)


def find_path(snapshot_id: str) -> Path | None:
    for info in list_snapshots():
        if info.id == snapshot_id:
            return info.path
    return None


def import_file(src: Path | str) -> Snapshot:
    """
    Copy a snapshot file (v2 or v1) into the snapshots folder.
    Importing the same snapshot twice keeps one copy (v1 files get an id
    derived from their content, so this holds for them too).
    """
    snapshot = load(src)
    existing = find_path(snapshot.id)
    if existing is not None:
        return load(existing)
    save(snapshot)
    return snapshot


def list_snapshots() -> list[SnapshotInfo]:
    """All stored snapshots, newest first. Unreadable files are skipped."""
    folder = config.snapshots_dir()
    if not folder.is_dir():
        return []
    mine = this_machine_id()
    infos: list[SnapshotInfo] = []
    for path in folder.glob(f"*{FILE_SUFFIX}"):
        try:
            snap = load(path)
        except SnapshotError:
            continue
        infos.append(SnapshotInfo(
            path=path,
            id=snap.id,
            name=snap.name,
            machine_name=snap.machine_name,
            created_at=snap.created_at,
            plugin_count=len(snap.plugins),
            app_count=len(snap.apps),
            hardware_count=len(snap.hardware),
            is_this_mac=bool(mine) and snap.machine_id == mine,
        ))
    infos.sort(key=lambda i: i.created_at, reverse=True)
    return infos


def latest_for_this_mac() -> Snapshot | None:
    for info in list_snapshots():
        if info.is_this_mac:
            return load(info.path)
    return None


def import_legacy(legacy_dir: Path | None = None) -> int:
    """Import v1 snapshots from the old data folder once. Returns how many were imported."""
    folder = (legacy_dir or config.LEGACY_DATA_DIR) / "snapshots"
    if not folder.is_dir():
        return 0
    count = 0
    for path in sorted(folder.glob("*.json")):
        try:
            import_file(path)
            count += 1
        except SnapshotError:
            continue
    return count
