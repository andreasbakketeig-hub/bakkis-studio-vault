"""
Safe quarantine and restore for plugin bundles.

Moves files into a user quarantine folder with a JSON manifest.
Never deletes plugin files.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.scanner import PLUGIN_FORMATS, SCAN_PATHS

# ── Paths ─────────────────────────────────────────────────────────────────────

DEFAULT_QUARANTINE_ROOT = Path.home() / "Music" / "Studio Vault Quarantine"
MANIFEST_FILENAME = "manifest.json"
ITEMS_DIRNAME = "items"

STATUS_PENDING = "pending"
STATUS_QUARANTINED = "quarantined"
STATUS_RESTORED = "restored"
STATUS_FAILED = "failed"

SYSTEM_PLUGIN_PREFIXES = (
    "/Library/Audio/Plug-Ins/",
    "/Library/Application Support/Avid/Audio/Plug-Ins/",
)

CRITICAL_PREFIXES = (
    "/",
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/var",
    "/private/etc",
    "/private/var",
)

ATTENTION_STATUSES = frozenset({STATUS_PENDING, STATUS_FAILED, STATUS_QUARANTINED})

PERMISSION_DENIED_MESSAGE = (
    "This plug-in is in a system location and cannot be moved without "
    "administrator permission. Studio Vault does not use sudo. "
    "Reveal in Finder and move manually if needed."
)

QUARANTINE_FOLDER_CHANGE_WARNING = (
    "Changing the quarantine folder affects future quarantines only. "
    "Existing quarantined items remain in their original quarantine folder."
)

_configured_quarantine_root: str | None = None


class QuarantineError(Exception):
    """Raised when quarantine or restore cannot proceed safely."""


class QuarantineDestinationMismatchError(QuarantineError):
    """Raised when the move destination differs from the user-confirmed path."""


@dataclass
class ValidationResult:
    ok: bool
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    is_system_path: bool = False
    requires_system_ack: bool = False
    not_writable: bool = False

    @property
    def can_offer_in_ui(self) -> bool:
        """True when Quarantine may be offered before final confirmation."""
        if self.not_writable:
            return False
        if self.ok:
            return True
        return self.requires_system_ack


@dataclass
class QuarantineOperation:
    operation_id: str
    status: str
    original_path: str
    quarantine_path: str
    timestamp: str
    reason: str
    plugin_name: str = ""
    developer: str = ""
    fmt: str = ""
    file_size: int = 0
    file_hash: str = ""
    app_version: str = ""
    restored_at: str = ""
    issue_kind: str = ""
    error_message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QuarantineOperation":
        return cls(
            operation_id=data.get("operation_id", ""),
            status=data.get("status", STATUS_QUARANTINED),
            original_path=data.get("original_path", ""),
            quarantine_path=data.get("quarantine_path", ""),
            timestamp=data.get("timestamp", ""),
            reason=data.get("reason", ""),
            plugin_name=data.get("plugin_name", ""),
            developer=data.get("developer", ""),
            fmt=data.get("fmt", ""),
            file_size=int(data.get("file_size", 0) or 0),
            file_hash=data.get("file_hash", ""),
            app_version=data.get("app_version", ""),
            restored_at=data.get("restored_at", ""),
            issue_kind=data.get("issue_kind", ""),
            error_message=data.get("error_message", ""),
        )


@dataclass
class MoveResult:
    operation: QuarantineOperation
    warnings: list[str] = field(default_factory=list)


@dataclass
class RestoreResult:
    operation: QuarantineOperation
    message: str = ""


# ── Allowed scan roots ────────────────────────────────────────────────────────

def get_allowed_scan_paths(custom_paths: list[str] | None = None) -> list[Path]:
    """
    Return resolved plug-in scan roots.

    Uses *custom_paths* from settings when provided and non-empty;
    otherwise falls back to default :data:`SCAN_PATHS`.
    """
    raw = custom_paths if custom_paths else list(SCAN_PATHS)
    roots: list[Path] = []
    for p in raw:
        if not str(p).strip():
            continue
        try:
            roots.append(Path(os.path.expanduser(p)).resolve())
        except OSError:
            pass
    return roots


def _allowed_roots(scan_paths: list[str] | None = None) -> list[Path]:
    return get_allowed_scan_paths(scan_paths)


# ── Configured root (from AppSettings) ────────────────────────────────────────

def set_configured_quarantine_root(path: str | None) -> None:
    """Set the active quarantine folder from application settings."""
    global _configured_quarantine_root
    _configured_quarantine_root = path.strip() if path and path.strip() else None


def get_configured_quarantine_folder_setting() -> str:
    """Return the raw configured folder string (empty means default)."""
    return _configured_quarantine_root or ""


def default_quarantine_folder() -> str:
    return str(DEFAULT_QUARANTINE_ROOT.expanduser())


def apply_quarantine_settings(settings) -> None:
    """Apply quarantine folder from :class:`app.core.settings.AppSettings`."""
    folder = getattr(settings, "quarantine_folder", "") or ""
    set_configured_quarantine_root(folder.strip() or None)


# ── Manifest I/O ──────────────────────────────────────────────────────────────

def get_quarantine_root(
    custom_root: str | Path | None = None,
    *,
    settings=None,
) -> Path:
    """Resolve the active quarantine folder (settings → configured → default)."""
    if custom_root:
        return Path(custom_root).expanduser().resolve()
    if settings is not None:
        folder = (getattr(settings, "quarantine_folder", "") or "").strip()
        if folder:
            return Path(folder).expanduser().resolve()
    if _configured_quarantine_root:
        return Path(_configured_quarantine_root).expanduser().resolve()
    return DEFAULT_QUARANTINE_ROOT.expanduser().resolve()


def sync_quarantine_root_from_settings(settings) -> Path:
    """Apply settings and return the effective quarantine folder."""
    if settings is not None:
        apply_quarantine_settings(settings)
    return get_quarantine_root(settings=settings)


def get_quarantine_display_root(settings=None) -> str:
    """Return the user-facing display string for the configured quarantine folder.

    Unlike :func:`get_quarantine_root`, this does *not* call ``Path.resolve()``,
    so symlinks are preserved and the result matches what the Settings UI shows.
    """
    # Import here to avoid a circular dependency at module level.
    from app.core.settings import DEFAULT_QUARANTINE_FOLDER  # noqa: PLC0415
    if settings is not None:
        folder = (getattr(settings, "quarantine_folder", "") or "").strip()
        if folder:
            return str(Path(folder).expanduser())
    if _configured_quarantine_root:
        return str(Path(_configured_quarantine_root).expanduser())
    return DEFAULT_QUARANTINE_FOLDER


def _manifest_path(root: Path) -> Path:
    return root / MANIFEST_FILENAME


def _items_dir(root: Path) -> Path:
    return root / ITEMS_DIRNAME


def _ensure_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _items_dir(root).mkdir(parents=True, exist_ok=True)


def load_manifest(root: Path | None = None) -> dict:
    root = root or get_quarantine_root()
    path = _manifest_path(root)
    if not path.exists():
        return {"version": 1, "operations": []}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise QuarantineError(f"Could not read manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise QuarantineError("Manifest format is invalid.")
    data.setdefault("version", 1)
    data.setdefault("operations", [])
    return data


def save_manifest(data: dict, root: Path | None = None) -> None:
    root = root or get_quarantine_root()
    _ensure_layout(root)
    path = _manifest_path(root)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def safe_load_manifest(root: Path | None = None) -> tuple[dict | None, str | None]:
    """Return ``(data, error_message)`` without raising."""
    try:
        return load_manifest(root), None
    except QuarantineError as exc:
        return None, str(exc)


def list_quarantine_operations(
    *,
    root: Path | None = None,
    active_only: bool = False,
    include_attention: bool = False,
) -> list[QuarantineOperation]:
    """Return operations newest first."""
    data, err = safe_load_manifest(root)
    if err or data is None:
        raise QuarantineError(err or "Manifest unavailable.")
    ops = [QuarantineOperation.from_dict(o) for o in data.get("operations", [])]
    if active_only:
        ops = [o for o in ops if o.status == STATUS_QUARANTINED]
    elif include_attention:
        ops = [o for o in ops if o.status in ATTENTION_STATUSES]
    ops.sort(key=lambda o: o.timestamp, reverse=True)
    return ops


def _path_key(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def _find_operation_by_original(
    path: str,
    root: Path,
    statuses: frozenset[str],
) -> QuarantineOperation | None:
    key = _path_key(path)
    for op in list_quarantine_operations(root=root, include_attention=True):
        if op.status in statuses and _path_key(op.original_path) == key:
            return op
    return None


def is_path_quarantined(path: str, root: Path | None = None) -> bool:
    root = root or get_quarantine_root()
    return _find_operation_by_original(
        path, root, frozenset({STATUS_PENDING, STATUS_QUARANTINED})
    ) is not None


def _find_operation_index(data: dict, operation_id: str) -> int | None:
    for i, o in enumerate(data.get("operations", [])):
        if o.get("operation_id") == operation_id:
            return i
    return None


# ── Validation ────────────────────────────────────────────────────────────────

def _resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.exists() and p.is_symlink():
        raise QuarantineError("Broken symlink — cannot quarantine.")
    if p.is_symlink():
        target = p.resolve()
        if not target.exists():
            raise QuarantineError("Symlink target does not exist.")
        return target
    return p.resolve()


def _is_plugin_bundle_or_file(path: Path) -> bool:
    return path.suffix.lower() in PLUGIN_FORMATS


def _under_allowed_root(resolved: Path, scan_paths: list[str] | None) -> bool:
    for root in _allowed_roots(scan_paths):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _is_critical_path(resolved: Path) -> bool:
    s = str(resolved)
    if s == "/":
        return True
    if "/var/folders/" in s or s.startswith("/tmp/") or s.startswith("/private/tmp/"):
        return False
    for prefix in CRITICAL_PREFIXES:
        if prefix == "/":
            continue
        if prefix in ("/var", "/private/var"):
            if s == prefix or s.startswith(prefix + "/root"):
                return True
            continue
        if s.startswith(prefix):
            return True
    return False


def is_quarantine_path_movable(path: str) -> bool:
    """Return True when the current user can move *path* without elevated privileges."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    if not resolved.exists():
        return False
    return os.access(resolved, os.W_OK) and os.access(resolved.parent, os.W_OK)


def _folder_conflicts_with_scan_paths(folder: Path, scan_paths: list[str] | None) -> str | None:
    folder = folder.resolve()
    for root in _allowed_roots(scan_paths):
        try:
            folder.relative_to(root)
            return "Quarantine folder cannot be inside a plug-in scan location."
        except ValueError:
            pass
        try:
            root.relative_to(folder)
            return "Quarantine folder cannot contain a plug-in scan location."
        except ValueError:
            pass
    return None


def validate_quarantine_folder(
    folder: str,
    *,
    scan_paths: list[str] | None = None,
) -> ValidationResult:
    """Validate a user-selected quarantine folder path."""
    if not folder or not str(folder).strip():
        return ValidationResult(False, "Choose a quarantine folder path.")

    try:
        resolved = Path(folder).expanduser().resolve()
    except OSError as exc:
        return ValidationResult(False, f"Invalid folder path: {exc}")

    if _is_critical_path(resolved):
        return ValidationResult(False, "Quarantine folder cannot be a system location.")

    conflict = _folder_conflicts_with_scan_paths(resolved, scan_paths)
    if conflict:
        return ValidationResult(False, conflict)

    target = resolved
    if not target.exists():
        target = resolved.parent
        if _is_critical_path(target):
            return ValidationResult(False, "Parent folder is not writable or is protected.")
    if not os.access(target, os.W_OK):
        return ValidationResult(False, "Quarantine folder is not writable.")

    return ValidationResult(True)


def ensure_quarantine_folder(
    folder: str,
    *,
    scan_paths: list[str] | None = None,
) -> Path:
    """Create the quarantine folder layout after validation."""
    v = validate_quarantine_folder(folder, scan_paths=scan_paths)
    if not v.ok:
        raise QuarantineError(v.message)
    root = Path(folder).expanduser().resolve()
    _ensure_layout(root)
    return root


def preflight_quarantine_target(
    path: str,
    root: Path | None = None,
    *,
    scan_paths: list[str] | None = None,
    system_path_acknowledged: bool = False,
) -> ValidationResult:
    """
    Pre-move check for UI enable logic.

    Does not require system-path acknowledgement to offer Quarantine, but
    reports ``requires_system_ack`` for the confirmation dialog.
    """
    v = validate_quarantine_target(
        path,
        root,
        scan_paths=scan_paths,
        system_path_acknowledged=system_path_acknowledged,
    )
    if not v.can_offer_in_ui and not v.requires_system_ack:
        return v
    if not is_quarantine_path_movable(path):
        return ValidationResult(
            False,
            PERMISSION_DENIED_MESSAGE,
            is_system_path=v.is_system_path,
            requires_system_ack=v.requires_system_ack,
            not_writable=True,
        )
    if v.ok:
        return v
    return ValidationResult(
        True,
        warnings=v.warnings,
        is_system_path=v.is_system_path,
        requires_system_ack=v.requires_system_ack,
    )


def is_system_plugin_location(path: Path) -> bool:
    s = str(path.resolve())
    home_lib = os.path.expanduser("~/Library/Audio/Plug-Ins/")
    if s.startswith(home_lib):
        return False
    return any(s.startswith(prefix) for prefix in SYSTEM_PLUGIN_PREFIXES)


def validate_quarantine_target(
    path: str,
    root: Path | None = None,
    *,
    scan_paths: list[str] | None = None,
    system_path_acknowledged: bool = False,
) -> ValidationResult:
    """Validate *path* before moving to quarantine."""
    root = root or get_quarantine_root()
    warnings: list[str] = []

    if not path or not str(path).strip():
        return ValidationResult(False, "No path specified.")

    try:
        resolved = _resolve_path(path)
    except QuarantineError as exc:
        return ValidationResult(False, str(exc))

    if not resolved.exists():
        return ValidationResult(False, "Path does not exist.")

    if _is_critical_path(resolved):
        return ValidationResult(False, "Path is in a protected system location.")

    if not _under_allowed_root(resolved, scan_paths):
        return ValidationResult(
            False,
            "Path is outside known plug-in folders. Quarantine is blocked.",
        )

    if not _is_plugin_bundle_or_file(resolved):
        return ValidationResult(
            False,
            "Path does not look like a recognised plug-in bundle.",
        )

    if is_path_quarantined(str(resolved), root):
        return ValidationResult(False, "This plug-in is already in quarantine.")

    src = Path(path).expanduser()
    if src.is_symlink():
        warnings.append(
            "Source is a symlink; the resolved target will be moved."
        )

    is_system = is_system_plugin_location(resolved)
    if is_system:
        if not system_path_acknowledged:
            return ValidationResult(
                False,
                "System plug-in location requires additional confirmation.",
                is_system_path=True,
                requires_system_ack=True,
            )
        warnings.append(
            "System plug-in location (/Library/…). Moving may affect all users "
            "and can require administrator permission."
        )

    if not is_quarantine_path_movable(str(resolved)):
        return ValidationResult(
            False,
            PERMISSION_DENIED_MESSAGE,
            is_system_path=is_system,
            requires_system_ack=is_system,
            not_writable=True,
        )

    return ValidationResult(
        True,
        warnings=warnings,
        is_system_path=is_system,
        requires_system_ack=is_system,
    )


def validate_restore_target(
    operation: QuarantineOperation,
    root: Path | None = None,
) -> ValidationResult:
    """Validate whether *operation* can be restored."""
    root = root or get_quarantine_root()

    if operation.status != STATUS_QUARANTINED:
        return ValidationResult(
            False,
            f"Cannot restore — status is '{operation.status}', not quarantined.",
        )

    qpath = Path(operation.quarantine_path)
    if not qpath.exists():
        return ValidationResult(False, "Quarantined file is missing from disk.")

    original = Path(operation.original_path)
    if original.exists():
        return ValidationResult(
            False,
            f"Original path already exists:\n{original}",
        )

    parent = original.parent
    if not parent.exists():
        return ValidationResult(
            True,
            warnings=[f"Parent folder does not exist and will be created:\n{parent}"],
        )

    return ValidationResult(True)


# ── Destination planning ──────────────────────────────────────────────────────

def _planned_dest_path(items_dir: Path, op_id: str, src: Path) -> Path:
    """Compute destination path without creating the bundle at *dest*."""
    base = items_dir / op_id
    dest = base / src.name
    if not dest.exists():
        return dest
    raise QuarantineError(
        "Quarantine destination is already occupied. Close other operations "
        "and try again."
    )


def plan_quarantine_destination(
    path: str,
    root: Path | None = None,
    *,
    scan_paths: list[str] | None = None,
    system_path_acknowledged: bool = False,
) -> tuple[str, Path]:
    """Return ``(operation_id, destination_path)`` for display before confirmation."""
    validation = validate_quarantine_target(
        path,
        root,
        scan_paths=scan_paths,
        system_path_acknowledged=system_path_acknowledged,
    )
    if not validation.ok:
        raise QuarantineError(validation.message)

    root = root or get_quarantine_root()
    resolved = _resolve_path(path)
    op_id = _new_operation_id()
    dest = _planned_dest_path(_items_dir(root), op_id, resolved)
    return op_id, dest


def _assert_destination_matches(
    expected: str,
    actual: Path,
) -> None:
    exp = Path(expected).expanduser().resolve()
    act = actual.resolve()
    if exp != act:
        raise QuarantineDestinationMismatchError(
            "The quarantine destination changed since confirmation. "
            "Please open Quarantine again and confirm the new destination.\n"
            f"Confirmed: {exp}\nCurrent:   {act}"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cheap_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        if path.is_file():
            with path.open("rb") as fh:
                h.update(fh.read(65536))
        elif path.is_dir():
            plist = path / "Contents" / "Info.plist"
            if plist.is_file():
                with plist.open("rb") as fh:
                    h.update(fh.read(65536))
            else:
                h.update(str(path.stat().st_mtime).encode())
    except OSError:
        return ""
    return h.hexdigest()[:32]


def _bundle_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _read_bundle_version(path: Path) -> str:
    plist = path / "Contents" / "Info.plist"
    if not plist.is_file():
        return ""
    try:
        import plistlib
        with plist.open("rb") as fh:
            data = plistlib.load(fh)
        return (
            str(data.get("CFBundleShortVersionString") or data.get("CFBundleVersion") or "")
        ).strip()
    except Exception:
        return ""


def _new_operation_id() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"op_{ts}_{uuid.uuid4().hex[:8]}"


def _update_operation(root: Path, op: QuarantineOperation) -> None:
    data = load_manifest(root)
    idx = _find_operation_index(data, op.operation_id)
    if idx is None:
        raise QuarantineError(f"Unknown operation: {op.operation_id}")
    data["operations"][idx] = op.to_dict()
    save_manifest(data, root)


# ── Two-phase move ────────────────────────────────────────────────────────────

def register_pending_quarantine(
    path: str,
    reason: str,
    operation_id: str,
    quarantine_path: str,
    *,
    metadata: dict | None = None,
    root: Path | None = None,
    scan_paths: list[str] | None = None,
    system_path_acknowledged: bool = False,
) -> QuarantineOperation:
    """
    Phase 1 — write a *pending* manifest row before any file move.
    """
    root = root or get_quarantine_root()
    _ensure_layout(root)

    validation = validate_quarantine_target(
        path,
        root,
        scan_paths=scan_paths,
        system_path_acknowledged=system_path_acknowledged,
    )
    if not validation.ok:
        raise QuarantineError(validation.message)

    resolved = _resolve_path(path)
    dest = Path(quarantine_path).expanduser().resolve()
    _assert_destination_matches(quarantine_path, dest)

    if dest.exists():
        raise QuarantineError(
            "Quarantine destination is already occupied. Reopen Quarantine to refresh."
        )

    data = load_manifest(root)
    if _find_operation_index(data, operation_id) is not None:
        raise QuarantineError("Operation already registered.")

    meta = metadata or {}
    op = QuarantineOperation(
        operation_id=operation_id,
        status=STATUS_PENDING,
        original_path=str(resolved),
        quarantine_path=str(dest),
        timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        reason=reason.strip() or "Quarantined from Plugin Health",
        plugin_name=meta.get("plugin_name", resolved.stem),
        developer=meta.get("developer", ""),
        fmt=meta.get("fmt", PLUGIN_FORMATS.get(resolved.suffix.lower(), "")),
        issue_kind=meta.get("issue_kind", ""),
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("operations", []).append(op.to_dict())
    save_manifest(data, root)
    return op


def complete_quarantine_move(
    operation_id: str,
    expected_quarantine_path: str,
    *,
    root: Path | None = None,
    scan_paths: list[str] | None = None,
) -> MoveResult:
    """
    Phase 2 — move file into the reserved destination and finalize manifest.
    """
    root = root or get_quarantine_root()
    data = load_manifest(root)
    idx = _find_operation_index(data, operation_id)
    if idx is None:
        raise QuarantineError(f"Unknown operation: {operation_id}")

    op = QuarantineOperation.from_dict(data["operations"][idx])
    if op.status != STATUS_PENDING:
        raise QuarantineError(f"Operation is not pending (status={op.status}).")

    dest = Path(expected_quarantine_path).expanduser()
    _assert_destination_matches(expected_quarantine_path, dest)
    _assert_destination_matches(op.quarantine_path, dest)

    if dest.exists():
        raise QuarantineDestinationMismatchError(
            "Quarantine destination is occupied. Reopen Quarantine and confirm again."
        )

    resolved = Path(op.original_path)
    if not resolved.exists():
        op.status = STATUS_FAILED
        op.error_message = "Source path no longer exists before move."
        data["operations"][idx] = op.to_dict()
        save_manifest(data, root)
        raise QuarantineError(op.error_message)

    validation = validate_quarantine_target(
        str(resolved),
        root,
        scan_paths=scan_paths,
        system_path_acknowledged=True,
    )
    warnings = list(validation.warnings) if validation.ok else []

    try:
        shutil.move(str(resolved), str(dest))
    except (PermissionError, OSError) as exc:
        op.status = STATUS_FAILED
        op.error_message = str(exc)
        data["operations"][idx] = op.to_dict()
        save_manifest(data, root)
        raise QuarantineError(f"Move failed: {exc}") from exc

    if not dest.exists():
        op.status = STATUS_FAILED
        op.error_message = "Move failed — quarantine destination not found."
        data["operations"][idx] = op.to_dict()
        save_manifest(data, root)
        raise QuarantineError(op.error_message)

    op.status = STATUS_QUARANTINED
    op.quarantine_path = str(dest.resolve())
    op.error_message = ""
    op.file_size = _bundle_size(dest)
    op.file_hash = _cheap_file_hash(dest)
    op.app_version = op.app_version or _read_bundle_version(dest)
    data["operations"][idx] = op.to_dict()
    save_manifest(data, root)

    return MoveResult(operation=op, warnings=warnings)


def move_to_quarantine(
    path: str,
    reason: str,
    *,
    metadata: dict | None = None,
    root: Path | None = None,
    operation_id: str | None = None,
    expected_quarantine_path: str | None = None,
    scan_paths: list[str] | None = None,
    system_path_acknowledged: bool = False,
) -> MoveResult:
    """
    Register pending + complete in one call (used by tests and internal flows).
    """
    op_id, dest = plan_quarantine_destination(
        path,
        root,
        scan_paths=scan_paths,
        system_path_acknowledged=system_path_acknowledged,
    )
    if operation_id:
        op_id = operation_id
    if expected_quarantine_path:
        dest = Path(expected_quarantine_path).expanduser().resolve()
        _assert_destination_matches(expected_quarantine_path, dest)

    register_pending_quarantine(
        path,
        reason,
        op_id,
        str(dest),
        metadata=metadata,
        root=root,
        scan_paths=scan_paths,
        system_path_acknowledged=system_path_acknowledged,
    )
    return complete_quarantine_move(
        op_id,
        str(dest),
        root=root,
        scan_paths=scan_paths,
    )


def restore_from_quarantine(
    operation_id: str,
    *,
    root: Path | None = None,
) -> RestoreResult:
    """Move a quarantined item back to its original path."""
    root = root or get_quarantine_root()
    data = load_manifest(root)
    idx = _find_operation_index(data, operation_id)
    if idx is None:
        raise QuarantineError(f"Unknown operation: {operation_id}")

    op = QuarantineOperation.from_dict(data["operations"][idx])
    validation = validate_restore_target(op, root)
    if not validation.ok:
        raise QuarantineError(validation.message)

    qpath = Path(op.quarantine_path)
    original = Path(op.original_path)
    original.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(qpath), str(original))
    except PermissionError as exc:
        raise QuarantineError(f"Permission denied while restoring: {exc}") from exc
    except OSError as exc:
        raise QuarantineError(f"Restore failed: {exc}") from exc

    if not original.exists():
        raise QuarantineError("Restore failed — original path not found after move.")

    op.status = STATUS_RESTORED
    op.restored_at = datetime.datetime.now().isoformat(timespec="seconds")
    data["operations"][idx] = op.to_dict()
    save_manifest(data, root)

    return RestoreResult(
        operation=op,
        message=f"Restored to {original}",
    )
