"""
Backend exposed to the web UI as ``window.pywebview.api.<method>(…)``.

pywebview calls each method on its own thread with JSON-able arguments and
sends the JSON-able return value back to the page. Long work (scanning) runs
on a worker thread and reports through ``emit(event, data)``, which app.py
turns into ``vault.onEvent(event, data)`` in the page.

Everything that is not an API method starts with an underscore: pywebview
exposes every public attribute of this object to JavaScript.

Window-level actions (file dialogs, Finder, browser, Trash) go through a
``Native`` object so tests can replace them.
"""

from __future__ import annotations

import dataclasses
import datetime
import os
import platform
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Protocol

from studio_vault import APP_NAME, __version__, checklist, config, report
from studio_vault import snapshot as snap
from studio_vault.compare import compare
from studio_vault.scanners.apps import scan_music_apps
from studio_vault.scanners.hardware import scan_hardware
from studio_vault.scanners.plugins import SCAN_PATHS, SizeCache, scan_plugins

SCAN_IDLE = "idle"
SCAN_RUNNING = "running"
SCAN_DONE = "done"
SCAN_CANCELLED = "cancelled"
SCAN_FAILED = "failed"

LINKS = {
    "website": "https://bakkis.com",
    "instagram": "https://www.instagram.com/bakkismusic/",
    "music": "https://songshare.com/artist/z7iy15wo",
    "support": "https://ko-fi.com/bakkis",
    "contact": "mailto:bakkis@bakkis.com",
}


class Native(Protocol):
    def choose_open_file(self, file_types: tuple[str, ...]) -> str | None: ...
    def choose_save_file(self, default_name: str, file_types: tuple[str, ...]) -> str | None: ...
    def reveal_in_finder(self, path: str) -> None: ...
    def open_url(self, url: str) -> None: ...
    def move_to_trash(self, path: str) -> None: ...


class ApiError(Exception):
    """A user-facing error; the message is shown in the UI."""


def _ok(**data: Any) -> dict:
    return {"ok": True, **data}


def _fail(message: str) -> dict:
    return {"ok": False, "error": message}


def _safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in " -_." else "-" for c in text).strip() or "Studio"


class Api:
    def __init__(self, native: Native | None = None, emit: Callable[[str, Any], None] | None = None) -> None:
        self._native = native
        self._emit_fn = emit
        self._lock = threading.RLock()
        self._settings = config.load_settings()
        self._scan_thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._scan: dict[str, Any] = {"status": SCAN_IDLE, "phase": "", "message": "", "error": ""}
        self._current: snap.Snapshot | None = None       # last scan of this Mac (maybe unsaved)
        self._current_saved_id: str = ""
        self._changes: dict | None = None                # current vs previous snapshot of this Mac
        config.ensure_data_dirs()
        if not self._settings.legacy_import_done:
            snap.import_legacy()
            self._settings.legacy_import_done = True
            config.save_settings(self._settings)

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _attach(self, native: Native, emit: Callable[[str, Any], None]) -> None:
        """Connect the window once it exists (the window needs this object first)."""
        self._native = native
        self._emit_fn = emit

    def _emit(self, event: str, data: Any = None) -> None:
        if self._emit_fn is not None:
            try:
                self._emit_fn(event, data)
            except Exception:  # noqa: BLE001 - the window may be closing
                pass

    def _require_native(self) -> Native:
        if self._native is None:
            raise ApiError("Not available.")
        return self._native

    def _load(self, snapshot_id: str) -> snap.Snapshot:
        if snapshot_id == "current":
            if self._current is None:
                raise ApiError("Scan this Mac first.")
            return self._current
        path = snap.find_path(snapshot_id)
        if path is None:
            raise ApiError("That snapshot no longer exists.")
        return snap.load(path)

    def _this_mac_state(self) -> snap.Snapshot:
        """What this Mac has now: the last scan, else its latest snapshot, else nothing."""
        if self._current is not None:
            return self._current
        latest = snap.latest_for_this_mac()
        if latest is not None:
            return latest
        return snap.Snapshot(id="empty", name="", machine_name="", machine_id="", created_at="")

    @staticmethod
    def _guard(fn: Callable[[], dict]) -> dict:
        try:
            return fn()
        except (ApiError, snap.SnapshotError) as exc:
            return _fail(str(exc))
        except OSError as exc:
            return _fail(f"Could not access the file: {exc.strerror or exc}")

    # ── state & settings ──────────────────────────────────────────────────────

    def state(self) -> dict:
        latest = None if self._current is not None else snap.latest_for_this_mac()
        with self._lock:
            return _ok(
                app_name=APP_NAME,
                version=__version__,
                macos=platform.mac_ver()[0],
                this_mac=snap.this_machine_name(),
                settings=asdict(self._settings),
                scan=dict(self._scan),
                current=self._summary(self._current) if self._current else None,
                latest=self._summary(latest) if latest else None,
                current_saved_id=self._current_saved_id,
                has_snapshots=bool(snap.list_snapshots()),
            )

    def set_settings(self, changes: dict) -> dict:
        with self._lock:
            allowed = {"scan_on_launch", "auto_save_snapshot", "extra_plugin_folders"}
            picked = {k: v for k, v in (changes or {}).items() if k in allowed}
            merged = {**asdict(self._settings), **picked}
            self._settings = config.normalize_settings(merged)
            config.save_settings(self._settings)
            return _ok(settings=asdict(self._settings))

    def about(self) -> dict:
        return _ok(app_name=APP_NAME, version=__version__, macos=platform.mac_ver()[0], links=LINKS)

    # ── scanning ──────────────────────────────────────────────────────────────

    def scan_start(self) -> dict:
        with self._lock:
            if self._scan["status"] == SCAN_RUNNING:
                return _ok(scan=dict(self._scan))
            self._cancel.clear()
            self._scan = {"status": SCAN_RUNNING, "phase": "plugins", "message": "Starting…", "error": ""}
            self._scan_thread = threading.Thread(target=self._run_scan, name="scan", daemon=True)
            self._scan_thread.start()
            return _ok(scan=dict(self._scan))

    def scan_cancel(self) -> dict:
        self._cancel.set()
        return _ok()

    def _progress(self, phase: str, message: str) -> None:
        with self._lock:
            self._scan.update(phase=phase, message=message)
            data = dict(self._scan)
        self._emit("scan", data)

    def _run_scan(self) -> None:
        try:
            extra = list(self._settings.extra_plugin_folders)
            plugins = scan_plugins(
                SCAN_PATHS + extra,
                progress_cb=lambda m: self._progress("plugins", m),
                cancel=self._cancel,
                size_cache=SizeCache(config.cache_dir() / "plugin_sizes.json"),
            )
            if self._cancel.is_set():
                return self._finish(SCAN_CANCELLED)
            self._progress("apps", "Looking for music apps…")
            apps = scan_music_apps(progress_cb=lambda m: self._progress("apps", m))
            if self._cancel.is_set():
                return self._finish(SCAN_CANCELLED)
            self._progress("hardware", "Looking for audio and MIDI hardware…")
            hardware = scan_hardware(debug_log=False).devices
            if self._cancel.is_set():
                return self._finish(SCAN_CANCELLED)

            current = snap.from_scan(plugins.plugins, apps, hardware)
            previous = snap.latest_for_this_mac()
            changes = self._changes_dict(previous, current) if previous else None
            saved_id = ""
            if self._settings.auto_save_snapshot and (previous is None or not changes["empty"]):
                snap.save(current)
                saved_id = current.id
            with self._lock:
                self._current, self._changes, self._current_saved_id = current, changes, saved_id
            self._finish(SCAN_DONE)
        except Exception as exc:  # noqa: BLE001 - report, never crash the worker
            self._finish(SCAN_FAILED, f"Scan failed: {exc}")

    def _finish(self, status: str, error: str = "") -> None:
        with self._lock:
            self._scan = {"status": status, "phase": "", "message": "", "error": error}
            data = dict(self._scan)
        self._emit("scan", data)

    # ── current scan & changes ────────────────────────────────────────────────

    @staticmethod
    def _summary(s: snap.Snapshot) -> dict:
        return {
            "id": s.id, "name": s.name, "machine_name": s.machine_name, "created_at": s.created_at,
            "plugin_count": len(s.plugins), "app_count": len(s.apps), "hardware_count": len(s.hardware),
            "plugin_formats": s.plugin_formats,
            "plugin_bytes": sum(p.size for p in s.plugins),
        }

    @staticmethod
    def _changes_dict(old: snap.Snapshot, new: snap.Snapshot) -> dict:
        result = compare(old, new)
        return {
            "old": {"id": old.id, "name": old.name, "created_at": old.created_at},
            "new": {"id": new.id, "name": new.name, "created_at": new.created_at},
            "empty": result.is_empty,
            "counts": result.counts(),
            "changes": [asdict(c) for c in result.changes],
        }

    def changes(self) -> dict:
        """What changed between this Mac's previous snapshot and the last scan."""
        with self._lock:
            return _ok(changes=self._changes)

    def save_snapshot(self, name: str = "") -> dict:
        def run() -> dict:
            with self._lock:
                if self._current is None:
                    raise ApiError("Scan this Mac first.")
                if name.strip():
                    self._current.name = name.strip()[:80]
                if self._current_saved_id:
                    path = snap.find_path(self._current_saved_id)
                    if path is not None:
                        snap.write(self._current, path)
                        return _ok(id=self._current.id)
                snap.save(self._current)
                self._current_saved_id = self._current.id
                return _ok(id=self._current.id)
        return self._guard(run)

    # ── snapshots ─────────────────────────────────────────────────────────────

    def snapshots(self) -> dict:
        infos = snap.list_snapshots()
        return _ok(snapshots=[{**asdict(i), "path": None} for i in infos])

    def snapshot(self, snapshot_id: str) -> dict:
        """Full snapshot (plug-ins, apps, hardware) for the inventory tables."""
        return self._guard(lambda: _ok(snapshot=self._load(snapshot_id).to_dict()))

    def compare_snapshots(self, old_id: str, new_id: str) -> dict:
        return self._guard(lambda: _ok(changes=self._changes_dict(self._load(old_id), self._load(new_id))))

    def rename_snapshot(self, snapshot_id: str, name: str) -> dict:
        def run() -> dict:
            name_clean = (name or "").strip()[:80]
            if not name_clean:
                raise ApiError("Give the snapshot a name.")
            path = snap.find_path(snapshot_id)
            if path is None:
                raise ApiError("That snapshot no longer exists.")
            s = snap.load(path)
            s.name = name_clean
            snap.write(s, path)
            with self._lock:
                if self._current is not None and self._current.id == snapshot_id:
                    self._current.name = name_clean
            return _ok()
        return self._guard(run)

    def delete_snapshot(self, snapshot_id: str) -> dict:
        """Move a stored snapshot to the Trash (recoverable)."""
        def run() -> dict:
            path = snap.find_path(snapshot_id)
            if path is None:
                raise ApiError("That snapshot no longer exists.")
            self._require_native().move_to_trash(str(path))
            with self._lock:
                if self._current_saved_id == snapshot_id:
                    self._current_saved_id = ""
            return _ok()
        return self._guard(run)

    def import_snapshot(self) -> dict:
        def run() -> dict:
            chosen = self._require_native().choose_open_file(
                ("Studio Vault snapshot (*.studiovault;*.json)",))
            if not chosen:
                return _ok(cancelled=True)
            return self.import_path(chosen)
        return self._guard(run)

    def import_path(self, path: str) -> dict:
        def run() -> dict:
            s = snap.import_file(Path(path))
            self._emit("snapshots", None)
            return _ok(id=s.id, name=s.name)
        return self._guard(run)

    def export_snapshot(self, snapshot_id: str) -> dict:
        def run() -> dict:
            s = self._load(snapshot_id)
            default = f"{_safe_name(s.name)} {s.created_at[:10]}{snap.FILE_SUFFIX}"
            dest = self._require_native().choose_save_file(default, ("Studio Vault snapshot (*.studiovault)",))
            if not dest:
                return _ok(cancelled=True)
            out = snap.export(s, Path(dest))
            return _ok(path=str(out))
        return self._guard(run)

    # ── checklist ─────────────────────────────────────────────────────────────

    def checklist(self, source_id: str) -> dict:
        def run() -> dict:
            source = self._load(source_id)
            built = checklist.build(source, self._this_mac_state())
            return _ok(checklist=self._checklist_dict(built))
        return self._guard(run)

    @staticmethod
    def _checklist_dict(c: checklist.Checklist) -> dict:
        def item(i: checklist.ChecklistItem) -> dict:
            return {**asdict(i), "done": i.done}
        return {
            "source_id": c.source_id, "source_name": c.source_name,
            "source_created_at": c.source_created_at,
            "total": c.total, "done_count": c.done_count,
            "groups": [{
                **{f.name: getattr(g, f.name) for f in dataclasses.fields(g) if f.name != "items"},
                "items": [item(i) for i in g.items],
                "done_count": g.done_count, "next_step": g.next_step,
            } for g in c.groups],
            "hardware": [item(i) for i in c.hardware],
        }

    def checklist_tick(self, source_id: str, item_id: str, done: bool) -> dict:
        checklist.set_done(source_id, item_id, bool(done))
        return self.checklist(source_id)

    def export_checklist(self, source_id: str, fmt: str = "html") -> dict:
        def run() -> dict:
            source = self._load(source_id)
            built = checklist.build(source, self._this_mac_state())
            ext = "csv" if fmt == "csv" else "html"
            default = f"New Mac checklist - {_safe_name(source.name)}.{ext}"
            types = ("CSV (*.csv)",) if ext == "csv" else ("Web page (*.html)",)
            dest = self._require_native().choose_save_file(default, types)
            if not dest:
                return _ok(cancelled=True)
            out = report.checklist_csv(built, Path(dest)) if ext == "csv" \
                else report.write_checklist_html(built, Path(dest))
            return _ok(path=str(out))
        return self._guard(run)

    def export_inventory(self, snapshot_id: str) -> dict:
        def run() -> dict:
            s = self._load(snapshot_id)
            stamp = (s.created_at or datetime.date.today().isoformat())[:10]
            dest = self._require_native().choose_save_file(
                f"Studio inventory - {_safe_name(s.name)} {stamp}.csv", ("CSV (*.csv)",))
            if not dest:
                return _ok(cancelled=True)
            return _ok(path=str(report.inventory_csv(s, Path(dest))))
        return self._guard(run)

    # ── Finder & browser ──────────────────────────────────────────────────────

    def reveal(self, path: str) -> dict:
        """Show a plug-in or app (path as stored in a snapshot, "~/…") in Finder."""
        def run() -> dict:
            real = os.path.expanduser(path or "")
            if not real.startswith("/") or not os.path.exists(real):
                raise ApiError("Not found on this Mac.")
            self._require_native().reveal_in_finder(real)
            return _ok()
        return self._guard(run)

    def open_url(self, url: str) -> dict:
        def run() -> dict:
            if not (url.startswith("https://") or url.startswith("mailto:")):
                raise ApiError("Only web and e-mail links can be opened.")
            self._require_native().open_url(url)
            return _ok()
        return self._guard(run)

    def _shutdown(self) -> None:
        self._cancel.set()
        thread = self._scan_thread
        if thread is not None:
            thread.join(timeout=2)
