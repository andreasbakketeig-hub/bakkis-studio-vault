"""
Desktop app: a pywebview (WKWebView) window showing ``web/index.html`` with
:class:`studio_vault.api.Api` as ``window.pywebview.api``.

Native actions the page cannot do itself (file dialogs, Finder, browser,
Trash) live in :class:`NativeBridge`.

Files reach the app three ways, all through :meth:`NativeBridge.open_paths`:
dropped on the window, opened with the app from Finder or the Dock (macOS
``application:openFiles:``), or given on the command line. A Live Set or a
project folder goes to Handoff, a plug-in list to Handoff, a snapshot is
imported. Paths that arrive before the page is ready wait for it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from studio_vault import APP_NAME
from studio_vault.api import Api
from studio_vault.config import bundle_dir
from studio_vault.snapshot import FILE_SUFFIX

OPEN_DIALOG = 10   # webview.FileDialog.OPEN
FOLDER_DIALOG = 20  # webview.FileDialog.FOLDER
SAVE_DIALOG = 30   # webview.FileDialog.SAVE
WINDOW_SIZE = (1240, 820)
MIN_SIZE = (900, 620)
BACKGROUND = "#0E0F11"
SNAPSHOT_SUFFIXES = (FILE_SUFFIX, ".json")
HANDOFF_LIST_SUFFIX = ".handoffplugins"


def snapshot_files_from_drop(paths: list[str | None]) -> list[str]:
    """Dropped paths that look like snapshot files."""
    return [p for p in paths if p and p.lower().endswith(SNAPSHOT_SUFFIXES) and Path(p).is_file()]


def sets_in_folder(folder: Path) -> list[str]:
    """The Live Sets a dropped project folder holds, newest first (Live's Backup folder left out)."""
    try:
        sets = [p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() == ".als" and not p.name.startswith("._")]
    except OSError:
        return []
    sets.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in sets]


def classify_paths(paths: list[str | None]) -> dict[str, list[str]]:
    """Sort opened or dropped paths: {"als", "plugin_lists", "snapshots"}. Folders stand for the sets in them."""
    als: list[str] = []
    lists: list[str] = []
    for raw in paths:
        if not raw:
            continue
        p = Path(raw)
        low = raw.lower()
        if p.is_dir():
            als += sets_in_folder(p)
        elif low.endswith(".als") and p.is_file():
            als.append(raw)
        elif low.endswith(HANDOFF_LIST_SUFFIX) and p.is_file():
            lists.append(raw)
    return {"als": als, "plugin_lists": lists, "snapshots": snapshot_files_from_drop(paths)}


class NativeBridge:
    """Window-level actions. ``window`` is a ``webview.Window`` (or a test double)."""

    def __init__(self, window: Any) -> None:
        self.window = window
        self.api: Api | None = None
        self._drop_registered = False
        self._lock = threading.Lock()
        self._pending: list[str] = []      # paths opened before the page was ready

    # ── Native protocol (used by Api) ─────────────────────────────────────────

    def choose_open_file(self, file_types: tuple[str, ...]) -> str | None:
        result = self.window.create_file_dialog(
            OPEN_DIALOG, directory=str(Path.home() / "Downloads"), file_types=file_types)
        return self._first(result)

    def choose_save_file(self, default_name: str, file_types: tuple[str, ...]) -> str | None:
        result = self.window.create_file_dialog(
            SAVE_DIALOG, directory=str(Path.home() / "Desktop"),
            save_filename=default_name, file_types=file_types)
        return self._first(result)

    def choose_open_files(self, file_types: tuple[str, ...]) -> list[str]:
        result = self.window.create_file_dialog(
            OPEN_DIALOG, directory=str(Path.home() / "Music"), allow_multiple=True, file_types=file_types)
        return [str(p) for p in result] if result else []

    def choose_folder(self) -> str | None:
        return self._first(self.window.create_file_dialog(FOLDER_DIALOG, directory="/Volumes"))

    @staticmethod
    def _first(result: Any) -> str | None:
        if not result:
            return None
        return str(result[0] if isinstance(result, (list, tuple)) else result)

    def reveal_in_finder(self, path: str) -> None:
        subprocess.run(["open", "-R", path], check=False)

    def open_url(self, url: str) -> None:
        subprocess.run(["open", url], check=False)

    def copy_to_clipboard(self, text: str) -> None:
        subprocess.run(["pbcopy"], input=text, text=True, check=False)

    def move_to_trash(self, path: str) -> None:
        from Foundation import NSURL, NSFileManager

        ok, _url, error = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            NSURL.fileURLWithPath_(path), None, None)
        if not ok:
            raise OSError(str(error) if error else "Could not move to Trash")

    # ── Events to the page ────────────────────────────────────────────────────

    def quit_app(self) -> None:
        """Close the window (used by the updater); main() then returns and the process exits."""
        self.window.destroy()

    def emit(self, event: str, data: Any) -> None:
        self.window.evaluate_js(
            f"window.vault && vault.onEvent({json.dumps(event)}, {json.dumps(data)})")

    # ── Window lifecycle ──────────────────────────────────────────────────────

    def on_loaded(self) -> None:
        """Dark title bar, and register the drop handler once (the page is never reloaded)."""
        with self._lock:
            if self._drop_registered:
                return
            self._drop_registered = True
        self._dark_title_bar()
        from webview.dom import DOMEventHandler

        self.window.dom.document.events.drop += DOMEventHandler(
            self.on_drop, prevent_default=True, stop_propagation=False)
        with self._lock:
            pending, self._pending = self._pending, []
        if pending:
            self.open_paths(pending)

    def _dark_title_bar(self) -> None:
        """Match the window chrome to the dark UI, whatever the system appearance is."""
        native = getattr(self.window, "native", None)
        if native is None:
            return
        try:
            from AppKit import NSAppearance
            from PyObjCTools import AppHelper

            dark = NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua")
            AppHelper.callAfter(lambda: native.setAppearance_(dark))
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    def on_drop(self, event: dict) -> None:
        files = ((event or {}).get("dataTransfer") or {}).get("files") or []
        self.open_paths([f.get("pywebviewFullPath") for f in files if isinstance(f, dict)])

    def open_paths(self, paths: list[str | None], opened: bool = False) -> None:
        """Dropped, "Open with" or command-line paths. *opened* means Finder/Dock: a set always goes to Handoff."""
        with self._lock:
            if not self._drop_registered:          # the page is not ready yet: hand them over when it is
                self._pending += [p for p in paths if p]
                return
        found = classify_paths(paths)
        if found["als"] or found["plugin_lists"]:
            # The page decides: Handoff takes them when it is open or they were opened with the app,
            # else .als files go to Projects.
            self.emit("dropped", {"als": found["als"], "plugin_lists": found["plugin_lists"], "opened": opened})
            return
        if not found["snapshots"]:
            self.emit("toast", {"level": "warning", "text": "Drop a Live project folder or .als file, a plug-in list or a .studiovault snapshot."})
            return
        assert self.api is not None
        for path in found["snapshots"]:
            result = self.api.import_path(path)
            if result.get("ok"):
                self.emit("toast", {"level": "ok", "text": f"Imported “{result['name']}”."})
            else:
                self.emit("toast", {"level": "error", "text": result.get("error", "Import failed.")})


def install_open_with(bridge: NativeBridge) -> None:
    """Receive files opened with the app (Finder "Open With", Dock drops) through pywebview's app delegate."""
    if sys.platform != "darwin":
        return
    from webview.platforms.cocoa import BrowserView

    class OpenWithDelegate(BrowserView.AppDelegate):
        def application_openFiles_(self, app, filenames):
            bridge.open_paths([str(f) for f in filenames], opened=True)
            app.replyToOpenOrPrint_(0)        # NSApplicationDelegateReplySuccess
            app.activateIgnoringOtherApps_(True)

    BrowserView._shared_app_delegate = OpenWithDelegate.alloc().init()
    BrowserView.app.setDelegate_(BrowserView._shared_app_delegate)


def main(argv: list[str] | None = None) -> int:
    import webview

    debug = bool(os.environ.get("STUDIO_VAULT_DEBUG"))
    api = Api()
    window = webview.create_window(
        APP_NAME,
        url=str(bundle_dir() / "web" / "index.html"),
        js_api=api,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
        text_select=False,
    )
    bridge = NativeBridge(window)
    bridge.api = api
    api._attach(native=bridge, emit=bridge.emit)
    window.events.loaded += bridge.on_loaded
    window.events.closed += api._shutdown
    install_open_with(bridge)
    args = [a for a in (sys.argv[1:] if argv is None else argv) if not a.startswith("-")]
    if args:
        bridge.open_paths(args, opened=True)      # waits for the page
    webview.start(http_server=True, private_mode=True, debug=debug)
    return 0
