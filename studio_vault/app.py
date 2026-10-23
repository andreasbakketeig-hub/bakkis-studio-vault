"""
Desktop app: a pywebview (WKWebView) window showing ``web/index.html`` with
:class:`studio_vault.api.Api` as ``window.pywebview.api``.

Native actions the page cannot do itself (file dialogs, Finder, browser,
Trash) live in :class:`NativeBridge`. Dropping a snapshot file on the window
imports it (pywebview only exposes full paths of dropped files to Python).
"""

from __future__ import annotations

import json
import os
import subprocess
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


def snapshot_files_from_drop(paths: list[str | None]) -> list[str]:
    """Dropped paths that look like snapshot files."""
    return [p for p in paths if p and p.lower().endswith(SNAPSHOT_SUFFIXES) and Path(p).is_file()]


class NativeBridge:
    """Window-level actions. ``window`` is a ``webview.Window`` (or a test double)."""

    def __init__(self, window: Any) -> None:
        self.window = window
        self.api: Api | None = None
        self._drop_registered = False
        self._lock = threading.Lock()

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
        paths = snapshot_files_from_drop([f.get("pywebviewFullPath") for f in files if isinstance(f, dict)])
        if not paths:
            self.emit("toast", {"level": "warning", "text": "Drop a .studiovault snapshot file to import it."})
            return
        assert self.api is not None
        for path in paths:
            result = self.api.import_path(path)
            if result.get("ok"):
                self.emit("toast", {"level": "ok", "text": f"Imported “{result['name']}”."})
            else:
                self.emit("toast", {"level": "error", "text": result.get("error", "Import failed.")})


def main() -> int:
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
    webview.start(http_server=True, private_mode=True, debug=debug)
    return 0
