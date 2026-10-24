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
import time
import urllib.parse
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Protocol

from studio_vault import APP_NAME, __version__, checklist, config, content, leave, projects, report, updater, updates
from studio_vault.handoff import als as handoff_als, check as handoff_check, pack as handoff_pack, pluginlist
from studio_vault import snapshot as snap
from studio_vault.compare import compare, compare_versions, side_by_side
from studio_vault.scanners.apps import scan_music_apps
from studio_vault.scanners.hardware import scan_hardware
from studio_vault.scanners.plugins import ARCH_INTEL, FORMAT_ORDER, SCAN_PATHS, SizeCache, normalize_product_name, scan_plugins
from studio_vault.vendors import match_vendor

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
    def choose_folder(self) -> str | None: ...
    def choose_open_files(self, file_types: tuple[str, ...]) -> list[str]: ...
    def reveal_in_finder(self, path: str) -> None: ...
    def open_url(self, url: str) -> None: ...
    def move_to_trash(self, path: str) -> None: ...
    def quit_app(self) -> None: ...
    def copy_to_clipboard(self, text: str) -> None: ...


class ApiError(Exception):
    """A user-facing error; the message is shown in the UI."""


def _ok(**data: Any) -> dict:
    return {"ok": True, **data}


def _fail(message: str) -> dict:
    return {"ok": False, "error": message}


def _format_rank(fmt: str) -> int:
    return FORMAT_ORDER.index(fmt) if fmt in FORMAT_ORDER else len(FORMAT_ORDER)


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
        self._projects: list[projects.Project] = []
        self._projects_job: dict[str, Any] = {"status": SCAN_IDLE, "done": 0, "total": 0, "source": ""}
        self._projects_thread: threading.Thread | None = None
        self._projects_cancel = threading.Event()
        self._handoff_set: str = ""
        self._handoff_receiver: pluginlist.PluginList | None = None
        self._handoff_initials: str | None = None
        self._pack_job: dict[str, Any] = {"status": SCAN_IDLE, "done": 0, "total": 0}
        self._pack_thread: threading.Thread | None = None
        self._pack_cancel = threading.Event()
        self._update_result: dict | None = None
        self._updater = updater.Installer(updater.app_bundle())
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
            allowed = {"scan_on_launch", "auto_save_snapshot", "extra_plugin_folders", "welcome_seen", "check_for_updates"}
            picked = {k: v for k, v in (changes or {}).items() if k in allowed}
            merged = {**asdict(self._settings), **picked}
            self._settings = config.normalize_settings(merged)
            config.save_settings(self._settings)
            return _ok(settings=asdict(self._settings))

    def add_plugin_folder(self) -> dict:
        def run() -> dict:
            folder = self._require_native().choose_folder()
            if not folder:
                return _ok(cancelled=True)
            folders = list(self._settings.extra_plugin_folders)
            if folder not in folders:
                folders.append(folder)
            return self.set_settings({"extra_plugin_folders": folders})
        return self._guard(run)

    def remove_plugin_folder(self, path: str) -> dict:
        folders = [f for f in self._settings.extra_plugin_folders if f != path]
        return self.set_settings({"extra_plugin_folders": folders})

    def about(self) -> dict:
        macos = platform.mac_ver()[0]
        body = (f"What happened:\n\n\nWhat did you expect:\n\n\n"
                f"---\n{APP_NAME} {__version__} · macOS {macos} · {platform.machine()}")
        report_url = "mailto:bakkis@bakkis.com?" + urllib.parse.urlencode(
            {"subject": f"{APP_NAME} {__version__}: problem", "body": body}, quote_via=urllib.parse.quote)
        return _ok(app_name=APP_NAME, version=__version__, macos=macos, links=LINKS, report_url=report_url)

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
            self._progress("content", "Measuring presets and your own content…")
            # Only vendors whose plug-ins are on this Mac, by developer name and registry name.
            vendor_names = {p.developer for p in plugins.plugins if p.developer}
            vendor_names |= {v.name for p in plugins.plugins if (v := match_vendor(p.developer, p.bundle_id))}
            user_content = content.find(vendor_names)
            if self._cancel.is_set():
                return self._finish(SCAN_CANCELLED)

            current = snap.from_scan(plugins.plugins, apps, hardware, content=user_content)
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
    def _products(s: snap.Snapshot) -> list[dict]:
        """Plug-ins grouped per product (all formats in one row) with their vendor."""
        groups: dict[str, dict] = {}
        for p in s.plugins:
            g = groups.setdefault(normalize_product_name(p.name), {
                "name": p.name, "developer": "", "bundle_id": "", "version": "", "kind": "",
                "formats": [], "size": 0, "path": "", "intel_formats": [], "min_macos": "",
            })
            if p.fmt not in g["formats"]:
                g["formats"].append(p.fmt)
            # Point Finder/copy at the most common format's copy (VST3 → AU → CLAP → VST → AAX).
            if _format_rank(p.fmt) < _format_rank(g.get("_path_fmt", "")):
                g["path"], g["_path_fmt"] = p.path, p.fmt
            g["size"] += p.size
            if p.arch == ARCH_INTEL:
                g["intel_formats"].append(p.fmt)
            if p.min_macos and (not g["min_macos"] or compare_versions(g["min_macos"], p.min_macos) == 1):
                g["min_macos"] = p.min_macos
            for key in ("developer", "bundle_id", "version", "kind"):
                g[key] = g[key] or getattr(p, key)
        out = []
        for g in groups.values():
            vendor = match_vendor(g["developer"], g["bundle_id"])
            g["vendor"] = vendor.name if vendor else g["developer"]
            g["vendor_url"] = vendor.download_url if vendor else ""
            g["matched"] = vendor is not None
            g["formats"].sort(key=_format_rank)
            g["intel_formats"].sort(key=_format_rank)
            # intel: every copy is Intel-only; mixed: some formats are.
            g["arch"] = ("intel" if g["intel_formats"] and len(g["intel_formats"]) == len(g["formats"])
                         else "mixed" if g["intel_formats"] else "")
            del g["bundle_id"]
            g.pop("_path_fmt", None)
            out.append(g)
        return sorted(out, key=lambda g: g["name"].lower())

    def _summary(self, s: snap.Snapshot) -> dict:
        products = self._products(s)
        vendors = {p["vendor"] for p in products if p["vendor"]}
        matched = sum(1 for p in products if p["matched"])
        return {
            "id": s.id, "name": s.name, "machine_name": s.machine_name, "created_at": s.created_at,
            "plugin_count": len(s.plugins), "app_count": len(s.apps), "hardware_count": len(s.hardware),
            "product_count": len(products), "vendor_count": len(vendors),
            "matched_pct": round(100 * matched / len(products)) if products else 0,
            "plugin_formats": s.plugin_formats,
            "plugin_bytes": sum(p.size for p in s.plugins),
            "app_names": [a.name for a in s.apps[:3]],
            "cpu": s.cpu,
            "intel_files": sum(1 for p in s.plugins if p.arch == ARCH_INTEL),
            "intel_products": sum(1 for p in products if p["arch"]),
            "hardware_names": [h.name for h in s.hardware[:3]],
        }

    def inventory(self, snapshot_id: str) -> dict:
        """Inventory tables: plug-in products, apps and hardware of one snapshot."""
        def run() -> dict:
            s = self._load(snapshot_id)
            return _ok(
                snapshot={"id": s.id, "name": s.name, "created_at": s.created_at},
                products=self._products(s),
                apps=[asdict(a) for a in s.apps],
                hardware=[asdict(h) for h in s.hardware],
            )
        return self._guard(run)

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

    def side_by_side(self, a_id: str, b_id: str) -> dict:
        """Two Macs (or two snapshots) side by side, per product, grouped by vendor."""
        def run() -> dict:
            a, b = self._load(a_id), self._load(b_id)
            r = side_by_side(a, b)
            label = lambda s: {"id": s.id, "name": s.name, "machine_name": s.machine_name, "created_at": s.created_at}
            return _ok(compare={
                "a": label(a), "b": label(b), "counts": r.counts(),
                "groups": [{"key": g.key, "name": g.name, "download_url": g.download_url,
                            "rows": [asdict(x) for x in g.rows]} for g in r.groups],
                "hardware": [asdict(x) for x in r.hardware],
            })
        return self._guard(run)

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
            "content": [item(i) for i in c.content],
        }

    def checklist_tick(self, source_id: str, item_id: str, done: bool) -> dict:
        checklist.set_done(source_id, item_id, bool(done))
        return self.checklist(source_id)

    def leave_list(self) -> dict:
        """'Before you leave this Mac' for this Mac's last scan or snapshot."""
        def run() -> dict:
            this_mac = self._this_mac_state()
            if this_mac.id == "empty":
                raise ApiError("Scan this Mac first.")
            built = leave.build(this_mac)
            return _ok(leave={**{k: v for k, v in asdict(built).items()},
                              "export_id": "current" if self._current is not None else this_mac.id})
        return self._guard(run)

    def leave_tick(self, item_id: str, done: bool) -> dict:
        checklist.set_done(leave.LEAVE_ID, item_id, bool(done))
        return self.leave_list()

    # ── project check (Ableton Live) ──────────────────────────────────────────

    def projects_choose_files(self) -> dict:
        def run() -> dict:
            paths = self._require_native().choose_open_files(("Ableton Live Set (*.als)",))
            if not paths:
                return _ok(cancelled=True)
            return self.projects_check_paths(list(paths))
        return self._guard(run)

    def projects_choose_folder(self) -> dict:
        def run() -> dict:
            folder = self._require_native().choose_folder()
            if not folder:
                return _ok(cancelled=True)
            return self._start_projects(folder=folder)
        return self._guard(run)

    def projects_check_paths(self, paths: list[str]) -> dict:
        als = [p for p in paths if str(p).lower().endswith(".als")]
        if not als:
            return _fail("Choose Ableton Live Sets (.als files).")
        return self._start_projects(paths=als)

    def projects_cancel(self) -> dict:
        self._projects_cancel.set()
        self._pack_cancel.set()
        return _ok()

    def _start_projects(self, paths: list[str] | None = None, folder: str = "") -> dict:
        with self._lock:
            if self._projects_job["status"] == SCAN_RUNNING:
                return _fail("Already checking projects.")
            self._projects_cancel.clear()
            label = snap.scrub_path(folder) if folder else f"{len(paths or [])} project file(s)"
            self._projects_job = {"status": SCAN_RUNNING, "done": 0, "total": 0, "source": label}
            self._projects_thread = threading.Thread(
                target=self._run_projects, args=(paths, folder), name="projects", daemon=True)
            self._projects_thread.start()
            return _ok(job=dict(self._projects_job))

    def _run_projects(self, paths: list[str] | None, folder: str) -> None:
        def progress(done: int, total: int) -> None:
            with self._lock:
                self._projects_job.update(done=done, total=total)
                data = dict(self._projects_job)
            self._emit("projects", data)
        try:
            files = [Path(p) for p in paths] if paths else projects.find_projects(folder)
            progress(0, len(files))
            parsed = projects.parse_many(files, progress, self._projects_cancel.is_set)
            status = SCAN_CANCELLED if self._projects_cancel.is_set() else SCAN_DONE
            with self._lock:
                self._projects = parsed
                self._projects_job["status"] = status
                data = dict(self._projects_job)
        except Exception as exc:  # noqa: BLE001 - report, never crash the worker
            with self._lock:
                self._projects_job.update(status=SCAN_FAILED, error=f"Could not check projects: {exc}")
                data = dict(self._projects_job)
        self._emit("projects", data)

    def projects_result(self, target_id: str = "") -> dict:
        """The checked projects against this Mac (default) or a snapshot."""
        def run() -> dict:
            target = self._load(target_id) if target_id else self._this_mac_state()
            with self._lock:
                parsed = list(self._projects)
                job = dict(self._projects_job)
            checks = projects.check_all([p for p in parsed if not p.error], target)
            return _ok(
                job=job,
                target={"id": target_id or "this-mac", "name": target.name, "created_at": target.created_at},
                projects=[{
                    "name": c.project.name, "path": c.project.path, "live_version": c.project.live_version,
                    "missing": c.missing, "total": len(c.plugins),
                    "plugins": [asdict(p) for p in c.plugins],
                } for c in checks],
                unreadable=[{"name": p.name, "path": p.path, "error": p.error} for p in parsed if p.error],
                missing=projects.missing_summary(checks),
            )
        return self._guard(run)

    # ── Handoff ───────────────────────────────────────────────────────────────

    def handoff_export_plugins(self) -> dict:
        """Receiver: save the plug-ins this Mac has (one click, then a save dialog)."""
        def run() -> dict:
            pl = pluginlist.scan()
            dest = self._require_native().choose_save_file(
                f"{_safe_name(pl.machine_name)} plug-ins{pluginlist.FILE_SUFFIX}", ("Plug-in list (*.handoffplugins)",))
            if not dest:
                return _ok(cancelled=True)
            out = pluginlist.save(pl, Path(dest))
            return _ok(path=str(out), plugins=len(pl.plugins),
                       live=[f"{i.name} {i.version.split(' ')[0]}" for i in pl.live])
        return self._guard(run)

    def handoff_choose_set(self) -> dict:
        def run() -> dict:
            path = self._require_native().choose_open_file(("Ableton Live Set (*.als)",))
            if not path:
                return _ok(cancelled=True)
            with self._lock:
                self._handoff_set = path
            return self.handoff_report()
        return self._guard(run)

    def handoff_choose_receiver(self) -> dict:
        def run() -> dict:
            path = self._require_native().choose_open_file(("Plug-in list (*.handoffplugins)",))
            if not path:
                return _ok(cancelled=True)
            return self.handoff_open_paths([path])
        return self._guard(run)

    def handoff_open_paths(self, paths: list[str]) -> dict:
        """A dropped or chosen .als (the set to send) and/or .handoffplugins (the receiver's list)."""
        try:
            for p in paths:
                if p.lower().endswith(pluginlist.FILE_SUFFIX):
                    loaded = pluginlist.load(p)
                    with self._lock:
                        self._handoff_receiver = loaded
                elif p.lower().endswith(".als"):
                    with self._lock:
                        self._handoff_set = p
        except pluginlist.PluginListError as exc:
            return _fail(str(exc))
        return self.handoff_report()

    def handoff_clear_receiver(self) -> dict:
        with self._lock:
            self._handoff_receiver = None
        return self.handoff_report()

    def handoff_report(self) -> dict:
        # pywebview calls each method on its own thread: read the pair once, together.
        with self._lock:
            rec, set_path = self._handoff_receiver, self._handoff_set
        receiver = None if rec is None else {
            "name": rec.machine_name, "created_at": rec.created_at, "plugins": len(rec.plugins),
            "live": [f"{i.name} {i.version.split(' ')[0]}" for i in rec.live]}
        if not set_path:
            return _ok(report=None, receiver=receiver)
        try:
            live_set = handoff_als.read(set_path)
        except handoff_als.AlsError as exc:
            return _fail(str(exc))
        r = handoff_check.check(live_set, rec)
        if self._handoff_initials is None:
            self._handoff_initials = handoff_pack.user_initials()
        return _ok(receiver=receiver, report={
            "set_name": r.set_name, "set_path": snap.scrub_path(r.set_path), "live_version": r.live_version,
            "tempo": r.tempo, "level": r.level, "can_pack": r.can_pack, "tracks": len(live_set.tracks),
            "findings": [asdict(f) for f in r.findings], "plugins": r.plugins, "frozen_tracks": r.frozen_tracks,
            "other_sets": handoff_als.other_sets(live_set),
            "suggested_name": handoff_pack.suggest_version_name(live_set, self._handoff_initials),
        })

    def handoff_use_set(self, name: str) -> dict:
        """Switch to another .als in the same project folder (pick the main version)."""
        with self._lock:
            current = self._handoff_set
        if not current:
            return _fail("Choose a Live Set first.")
        other = Path(current).parent / Path(str(name)).name
        if other.suffix.lower() != ".als" or not other.is_file():
            return _fail("That Live Set is no longer in the project folder.")
        with self._lock:
            self._handoff_set = str(other)
        return self.handoff_report()

    def handoff_pack(self, version_name: str, note: str) -> dict:
        """Ask where to save, then zip the project on a worker thread (progress: event "pack")."""
        def run() -> dict:
            if not (note or "").strip():
                raise ApiError('Write what you changed ("What did you change?") first.')
            name = handoff_pack.clean_version_name(version_name)
            with self._lock:
                set_path, rec = self._handoff_set, self._handoff_receiver
                if self._pack_job["status"] == SCAN_RUNNING:
                    raise ApiError("Already packing.")
            if not set_path:
                raise ApiError("Choose a Live Set first.")
            live_set = handoff_als.read(set_path)
            report_ = handoff_check.check(live_set, rec)
            if not report_.can_pack:
                raise ApiError("Fix the red points first: something would be missing for the receiver.")
            dest = self._require_native().choose_save_file(f"{name}.zip", ("Zip archive (*.zip)",))
            if not dest:
                return _ok(cancelled=True)
            with self._lock:
                self._pack_cancel.clear()
                self._pack_job = {"status": SCAN_RUNNING, "done": 0, "total": 0}
                self._pack_thread = threading.Thread(
                    target=self._run_pack, args=(live_set, report_, dest, name, note), name="pack", daemon=True)
                self._pack_thread.start()
                return _ok(job=dict(self._pack_job))
        try:
            return self._guard(run)
        except (handoff_als.AlsError, handoff_pack.PackError) as exc:
            return _fail(str(exc))

    def _run_pack(self, live_set: handoff_als.LiveSet, report_: handoff_check.Report, dest: str,
                  name: str, note: str) -> None:
        last = [0.0]

        def progress(done: int, total: int) -> None:
            with self._lock:
                self._pack_job.update(done=done, total=total)
                data = dict(self._pack_job)
            now = time.monotonic()
            if now - last[0] >= 0.2 or done == total:
                last[0] = now
                self._emit("pack", data)
        try:
            res = handoff_pack.pack(live_set, report_, dest, name, note, sender=self._handoff_initials or "",
                                    progress=progress, cancelled=self._pack_cancel.is_set)
            with self._lock:
                self._pack_job.update(status=SCAN_DONE, path=res.zip_path, files=res.files, bytes=res.bytes)
                data = dict(self._pack_job)
        except handoff_pack.PackError as exc:
            status = SCAN_CANCELLED if self._pack_cancel.is_set() else SCAN_FAILED
            with self._lock:
                self._pack_job.update(status=status, error=str(exc))
                data = dict(self._pack_job)
        except Exception as exc:  # noqa: BLE001 - report, never crash the worker
            with self._lock:
                self._pack_job.update(status=SCAN_FAILED, error=f"Could not pack the project: {exc}")
                data = dict(self._pack_job)
        self._emit("pack", data)

    def handoff_pack_cancel(self) -> dict:
        self._pack_cancel.set()
        return _ok()

    def handoff_pack_status(self) -> dict:
        with self._lock:
            return _ok(job=dict(self._pack_job))

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

    @staticmethod
    def _existing_path(path: str) -> str:
        """A path as stored in a snapshot ("~/…") expanded, if it exists on this Mac."""
        real = os.path.expanduser(path or "")
        if not real.startswith("/") or not os.path.exists(real):
            raise ApiError("Not found on this Mac.")
        return real

    def reveal(self, path: str) -> dict:
        """Show a plug-in or app (path as stored in a snapshot, "~/…") in Finder."""
        def run() -> dict:
            self._require_native().reveal_in_finder(self._existing_path(path))
            return _ok()
        return self._guard(run)

    def copy_path(self, path: str) -> dict:
        """Copy a plug-in or app path (as stored, "~/…") to the clipboard as a full path."""
        def run() -> dict:
            real = self._existing_path(path)
            self._require_native().copy_to_clipboard(real)
            return _ok(path=real)
        return self._guard(run)

    def open_url(self, url: str) -> dict:
        def run() -> dict:
            if not (url.startswith("https://") or url.startswith("mailto:")):
                raise ApiError("Only web and e-mail links can be opened.")
            self._require_native().open_url(url)
            return _ok()
        return self._guard(run)

    # ── updates (GitHub Releases; only when the setting is on) ────────────────

    def check_update(self) -> dict:
        """Ask GitHub Releases once per launch whether a newer version exists. Nothing else is sent."""
        if not self._settings.check_for_updates:
            return _ok(current=__version__, error="disabled")
        if self._update_result is None:
            self._update_result = updates.check()
        r = {k: v for k, v in self._update_result.items() if k != "release"}
        if r.get("newer"):
            problem = updater.install_problem(self._updater.bundle)
            r.update(can_install=problem is None, install_problem=problem)
        return _ok(**r)

    def update_install(self) -> dict:
        """Download and verify the newer version in the background (the UI polls update_status)."""
        r = self._update_result or {}
        if not r.get("newer"):
            return _fail("No newer version to install.")
        try:
            return _ok(**self._updater.start(r.get("release") or {}, r["latest"]))
        except updater.UpdateError as exc:
            return _fail(str(exc))

    def update_status(self) -> dict:
        return _ok(**self._updater.snapshot())

    def update_restart(self) -> dict:
        """Swap in the downloaded version and quit; the helper reopens the app once this process has exited."""
        try:
            self._updater.restart()
        except updater.UpdateError as exc:
            return _fail(str(exc))
        if self._native is not None:
            threading.Timer(0.3, self._native.quit_app).start()   # let this response reach the page first
        return _ok(**self._updater.snapshot())

    def _shutdown(self) -> None:
        self._cancel.set()
        self._projects_cancel.set()
        self._pack_cancel.set()
        thread = self._scan_thread
        if thread is not None:
            thread.join(timeout=2)
