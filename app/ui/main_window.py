"""
Main application window — mounts the sidebar and swaps content views.
"""

from __future__ import annotations

import customtkinter as ctk

from app.core.scanner import Plugin
from app.core.music_software_scanner import MusicApp
from app.db.database import Database
from app.db.repositories.plugins import PluginRepository
from app.db.repositories.music_apps import MusicAppRepository
from app.db.repositories.settings import SettingsRepository
from app.core.settings import AppSettings
from app.core.quarantine import apply_quarantine_settings
from app.ui.sidebar import Sidebar
from app.ui.views.studio_overview import StudioOverviewView
from app.ui.views.plugin_scanner import PluginScannerView
from app.ui.views.format_analysis import FormatAnalysisView
from app.ui.views.plugin_health import PluginHealthView
from app.ui.views.quarantined_items import QuarantinedItemsView
from app.ui.views.cleanup_recommendations import CleanupRecommendationsView
from app.ui.views.music_software_scanner import MusicSoftwareScannerView
from app.ui.views.migration_assistant import MigrationAssistantView
from app.ui.views.settings import SettingsView
from app.ui.views.coming_soon import ComingSoonView
from app.ui.views.hardware_inventory import HardwareInventoryView
from app.core.hardware_scanner import HardwareDevice

BG_MAIN = "#0D0F18"
BG_CONTENT = "#10131C"

_PREFERRED_W = 1800
_PREFERRED_H = 1100
_MIN_W = 1400
_MIN_H = 900


def _initial_window_geometry(root: ctk.CTk) -> tuple[int, int, int, int]:
    """Return (width, height, x, y) for the launch window."""
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()

    if screen_w >= _PREFERRED_W and screen_h >= _PREFERRED_H:
        width, height = _PREFERRED_W, _PREFERRED_H
    else:
        width = int(screen_w * 0.90)
        height = int(screen_h * 0.85)

    width = min(width, screen_w)
    height = min(height, screen_h)

    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    return width, height, x, y

# Theme preset → (main_bg, content_bg)
_THEME_COLORS: dict[str, tuple[str, str]] = {
    "Midnight Blue": ("#0D0F18", "#10131C"),
    "Deep Space":    ("#08090F", "#0C0E16"),
    "Graphite":      ("#0F1014", "#111318"),
    "Obsidian":      ("#0A0A0A", "#0D0D0D"),
}


class MainWindow(ctk.CTk):
    """Root application window."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Bakkis Studio Manager")
        self.configure(fg_color=BG_MAIN)

        self.minsize(_MIN_W, _MIN_H)

        width, height, x, y = _initial_window_geometry(self)
        self.geometry(f"{width}x{height}+{x}+{y}")

        # Must be last in window setup: MacWindowStyle (removed) was resetting wm resizable
        # to (0, 0) on macOS, which removes resize handles.
        self.resizable(True, True)
        self.after_idle(self._ensure_resizable)

        # ── Database & repositories ───────────────────────────────────────────
        self._db              = Database()
        self._plugin_repo     = PluginRepository(self._db)
        self._apps_repo       = MusicAppRepository(self._db)
        self._settings_repo   = SettingsRepository(self._db)
        self._app_settings    = AppSettings.load(self._settings_repo)
        apply_quarantine_settings(self._app_settings)

        # Apply theme preset from persisted settings immediately
        self._apply_theme_colors()

        # ── Load cached scan data ─────────────────────────────────────────────
        self._views: dict[str, ctk.CTkFrame] = {}
        self._active_key: str = ""
        self._plugin_scan_in_progress: bool = False

        self._hardware_devices: list[HardwareDevice] = []
        if self._app_settings.auto_load_cache:
            self._plugins, self._plugin_scan_ts = self._plugin_repo.load_latest()
            self._music_apps, self._apps_scan_ts = self._apps_repo.load_latest()
        else:
            self._plugins: list[Plugin] = []
            self._music_apps: list[MusicApp] = []
            self._plugin_scan_ts: str | None = None
            self._apps_scan_ts: str | None = None

        self._build()
        self._navigate("studio_overview")

        # ── Auto rescan on launch ─────────────────────────────────────────────
        if self._app_settings.auto_rescan_on_launch:
            self.after(800, self._trigger_auto_rescan)

        # Tidy up the DB connection when the window is closed
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _ensure_resizable(self) -> None:
        """Re-assert resize capability after Tk finishes initial window setup."""
        self.resizable(True, True)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._sidebar = Sidebar(self, on_navigate=self._navigate)
        self._sidebar.grid(row=0, column=0, sticky="nsew")

        self._content_area = ctk.CTkFrame(self, fg_color=BG_CONTENT, corner_radius=0)
        self._content_area.grid(row=0, column=1, sticky="nsew")
        self._content_area.grid_rowconfigure(0, weight=1)
        self._content_area.grid_columnconfigure(0, weight=1)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate(self, key: str) -> None:
        if key == self._active_key:
            return

        if self._active_key and self._active_key in self._views:
            self._views[self._active_key].grid_remove()

        if key not in self._views:
            self._views[key] = self._create_view(key)

        view = self._views[key]
        view.grid(row=0, column=0, sticky="nsew")
        self._active_key = key
        self._sidebar.activate(key)

        # Re-run responsive table layout after the view is mapped at full size.
        relayout = getattr(view, "_relayout_tree_columns", None)
        if callable(relayout):
            self.after_idle(relayout)
            self.after(100, relayout)

        if hasattr(view, "refresh_db_stats"):
            view.refresh_db_stats()

        if key == "quarantine" and hasattr(view, "refresh"):
            view.refresh()  # type: ignore[union-attr]

        if key == "studio_overview" and hasattr(view, "update_settings"):
            self._app_settings = AppSettings.load(self._settings_repo)
            view.update_settings(self._app_settings)

    # ── Scan callbacks ────────────────────────────────────────────────────────

    def scan_all_plugins(self, *, navigate: bool = False) -> None:
        """Shared entry point for Studio Overview Rescan All and Plugin Scanner."""
        if self._plugin_scan_in_progress:
            return

        if navigate:
            if self._active_key != "plugins":
                self._navigate("plugins")
        elif "plugins" not in self._views:
            self._views["plugins"] = self._create_view("plugins")

        scanner = self._views.get("plugins")
        if scanner is None or not hasattr(scanner, "begin_scan"):
            return

        self._plugin_scan_in_progress = True
        self._notify_plugin_scan_status("Scanning plugins…", scanning=True)
        if not scanner.begin_scan():  # type: ignore[union-attr]
            self._plugin_scan_in_progress = False
            self._notify_plugin_scan_status("Scan already in progress", scanning=False)

    def _notify_plugin_scan_status(self, message: str, *, scanning: bool) -> None:
        overview = self._views.get("studio_overview")
        if overview is not None and hasattr(overview, "set_scan_status"):
            overview.set_scan_status(message, scanning=scanning)  # type: ignore[union-attr]

    def _on_plugin_scan_progress(self, message: str) -> None:
        if self._plugin_scan_in_progress:
            self._notify_plugin_scan_status(message, scanning=True)

    def _on_plugin_scan_failed(self, error: str) -> None:
        self._plugin_scan_in_progress = False
        self._notify_plugin_scan_status(f"Scan failed: {error}", scanning=False)

    def _plugin_scan_paths(self) -> list[str]:
        paths = self._app_settings.plugin_scan_paths
        return list(paths) if paths else []

    def _refresh_quarantine_view(self) -> None:
        view = self._views.get("quarantine")
        if view is not None and hasattr(view, "refresh"):
            view.refresh()  # type: ignore[union-attr]

    def _on_cleanup_quarantine_complete(self) -> None:
        """Rescan and refresh all plugin-dependent views after cleanup quarantine."""
        self._refresh_quarantine_view()
        self.scan_all_plugins(navigate=False)

    def _on_plugins_ready(self, plugins: list[Plugin]) -> None:
        """Called by PluginScannerView when a scan completes."""
        self._plugins = plugins
        self._plugin_repo.save_scan(plugins)
        self._plugin_scan_in_progress = False
        self._notify_plugin_scan_status("Scan complete", scanning=False)

        for key in ("studio_overview", "format_analysis", "cleanup", "migration"):
            if key in self._views:
                self._views[key].refresh(plugins)  # type: ignore[union-attr]

        health = self._views.get("plugin_health")
        if health is not None and hasattr(health, "refresh"):
            health.refresh(plugins, self._music_apps)  # type: ignore[union-attr]

        if "settings" in self._views:
            self._views["settings"].refresh_db_stats()  # type: ignore[union-attr]

    def _on_apps_ready(self, apps: list[MusicApp]) -> None:
        """Called by MusicSoftwareScannerView when a scan completes."""
        self._music_apps = apps
        self._apps_repo.save_scan(apps)

        if "studio_overview" in self._views:
            self._views["studio_overview"].refresh_apps(apps)  # type: ignore[union-attr]

        health = self._views.get("plugin_health")
        if health is not None and self._plugins and hasattr(health, "refresh"):
            health.refresh(self._plugins, apps)  # type: ignore[union-attr]

        if "settings" in self._views:
            self._views["settings"].refresh_db_stats()  # type: ignore[union-attr]

    def _on_hardware_ready(self, devices: list[HardwareDevice]) -> None:
        """Called by HardwareInventoryView when a hardware scan completes."""
        self._hardware_devices = devices

        if "studio_overview" in self._views:
            self._views["studio_overview"].refresh_hardware(devices)  # type: ignore[union-attr]

    # ── View factory ──────────────────────────────────────────────────────────

    def _create_view(self, key: str) -> ctk.CTkFrame:
        s = self._app_settings
        match key:
            case "studio_overview":
                view = StudioOverviewView(
                    self._content_area,
                    on_navigate=self._navigate,
                    on_rescan_all=lambda: self.scan_all_plugins(navigate=True),
                    settings=s,
                )
                if self._plugins:
                    view.refresh(self._plugins)
                if self._music_apps:
                    view.refresh_apps(self._music_apps)
                if self._hardware_devices:
                    view.refresh_hardware(self._hardware_devices)
                return view

            case "hardware":
                view = HardwareInventoryView(
                    self._content_area,
                    on_hardware_ready=self._on_hardware_ready,
                )
                return view

            case "plugins":
                return PluginScannerView(
                    self._content_area,
                    on_plugins_ready=self._on_plugins_ready,
                    on_request_scan=lambda: self.scan_all_plugins(navigate=False),
                    on_scan_progress=self._on_plugin_scan_progress,
                    on_scan_failed=self._on_plugin_scan_failed,
                    db=self._db,
                    last_scanned=self._plugin_scan_ts,
                    scan_paths=self._plugin_scan_paths(),
                )

            case "format_analysis":
                view = FormatAnalysisView(self._content_area, settings=s)
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "plugin_health":
                view = PluginHealthView(
                    self._content_area,
                    settings=s,
                    on_request_rescan=lambda: self.scan_all_plugins(navigate=False),
                    on_quarantine_complete=self._refresh_quarantine_view,
                    scan_paths=self._plugin_scan_paths(),
                )
                if self._plugins:
                    view.refresh(self._plugins, self._music_apps)
                return view

            case "quarantine":
                view = QuarantinedItemsView(
                    self._content_area,
                    on_restore_complete=lambda: self.scan_all_plugins(navigate=False),
                )
                return view

            case "cleanup":
                view = CleanupRecommendationsView(
                    self._content_area,
                    settings=s,
                    on_quarantine_complete=self._on_cleanup_quarantine_complete,
                    scan_paths=self._plugin_scan_paths(),
                )
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "music_software":
                return MusicSoftwareScannerView(
                    self._content_area,
                    on_apps_ready=self._on_apps_ready,
                    db=self._db,
                    last_scanned=self._apps_scan_ts,
                )

            case "migration":
                view = MigrationAssistantView(self._content_area, settings=s)
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "settings":
                return SettingsView(
                    self._content_area,
                    db=self._db,
                    on_settings_saved=self._on_settings_saved,
                )

            case _:
                return ComingSoonView(self._content_area, module_key=key)

    # ── Settings saved callback ───────────────────────────────────────────────

    def _on_settings_saved(self, saved: AppSettings) -> None:
        """Called by SettingsView after the user saves. Propagates changes live."""
        # Prefer the saved in-memory object (just validated); reload keeps parity.
        self._app_settings = saved
        apply_quarantine_settings(self._app_settings)

        # Live accent: update sidebar indicator immediately
        self._sidebar.update_accent(self._app_settings.accent_color)

        # Live theme: update window and content area background colors
        self._apply_theme_colors()

        # Invalidate all cached views (except settings) so they're recreated
        # with the new settings on next navigation.
        active = self._active_key
        for key in list(self._views.keys()):
            if key == "settings":
                continue
            try:
                self._views[key].grid_remove()
                self._views[key].destroy()
            except Exception:
                pass
            del self._views[key]

        # Re-navigate to the current non-settings view so it refreshes instantly
        if active and active != "settings":
            self._active_key = ""
            self._navigate(active)

    def _apply_theme_colors(self) -> None:
        """Apply theme preset background colors to window and content area."""
        main_bg, content_bg = _THEME_COLORS.get(
            self._app_settings.theme_preset, (BG_MAIN, BG_CONTENT)
        )
        self.configure(fg_color=main_bg)
        if hasattr(self, "_content_area"):
            self._content_area.configure(fg_color=content_bg)

    # ── Auto rescan on launch ─────────────────────────────────────────────────

    def _trigger_auto_rescan(self) -> None:
        """Run a background scan if auto_rescan_on_launch is enabled."""
        import threading
        from app.core.music_software_scanner import scan_music_apps

        self.scan_all_plugins(navigate=False)

        def _scan_apps() -> None:
            try:
                apps = scan_music_apps()
                self.after(0, lambda a=apps: self._on_apps_ready(a))
            except Exception:
                pass

        threading.Thread(target=_scan_apps, daemon=True).start()

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass
        self.destroy()
