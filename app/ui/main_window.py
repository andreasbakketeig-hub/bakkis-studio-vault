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
from app.ui.sidebar import Sidebar
from app.ui.views.studio_overview import StudioOverviewView
from app.ui.views.plugin_scanner import PluginScannerView
from app.ui.views.format_analysis import FormatAnalysisView
from app.ui.views.plugin_health import PluginHealthView
from app.ui.views.cleanup_recommendations import CleanupRecommendationsView
from app.ui.views.music_software_scanner import MusicSoftwareScannerView
from app.ui.views.migration_assistant import MigrationAssistantView
from app.ui.views.settings import SettingsView
from app.ui.views.coming_soon import ComingSoonView

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

        # Apply theme preset from persisted settings immediately
        self._apply_theme_colors()

        # ── Load cached scan data ─────────────────────────────────────────────
        self._views: dict[str, ctk.CTkFrame] = {}
        self._active_key: str = ""

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

    # ── Scan callbacks ────────────────────────────────────────────────────────

    def _on_plugins_ready(self, plugins: list[Plugin]) -> None:
        """Called by PluginScannerView when a scan completes."""
        self._plugins = plugins
        self._plugin_repo.save_scan(plugins)

        for key in ("studio_overview", "format_analysis", "plugin_health", "cleanup", "migration"):
            if key in self._views:
                self._views[key].refresh(plugins)  # type: ignore[union-attr]

        if "settings" in self._views:
            self._views["settings"].refresh_db_stats()  # type: ignore[union-attr]

    def _on_apps_ready(self, apps: list[MusicApp]) -> None:
        """Called by MusicSoftwareScannerView when a scan completes."""
        self._music_apps = apps
        self._apps_repo.save_scan(apps)

        if "studio_overview" in self._views:
            self._views["studio_overview"].refresh_apps(apps)  # type: ignore[union-attr]

        if "settings" in self._views:
            self._views["settings"].refresh_db_stats()  # type: ignore[union-attr]

    # ── View factory ──────────────────────────────────────────────────────────

    def _create_view(self, key: str) -> ctk.CTkFrame:
        s = self._app_settings
        match key:
            case "studio_overview":
                view = StudioOverviewView(
                    self._content_area,
                    on_navigate=self._navigate,
                    settings=s,
                )
                if self._plugins:
                    view.refresh(self._plugins)
                if self._music_apps:
                    view.refresh_apps(self._music_apps)
                return view

            case "plugins":
                return PluginScannerView(
                    self._content_area,
                    on_plugins_ready=self._on_plugins_ready,
                    db=self._db,
                    last_scanned=self._plugin_scan_ts,
                )

            case "format_analysis":
                view = FormatAnalysisView(self._content_area, settings=s)
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "plugin_health":
                view = PluginHealthView(self._content_area, settings=s)
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "cleanup":
                view = CleanupRecommendationsView(self._content_area, settings=s)
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

    def _on_settings_saved(self, _saved: AppSettings) -> None:
        """Called by SettingsView after the user saves. Propagates changes live."""
        # Reload fresh settings from DB
        self._app_settings = AppSettings.load(self._settings_repo)

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
        from app.core.scanner import scan_plugins
        from app.core.music_software_scanner import scan_music_apps

        def _scan() -> None:
            try:
                result = scan_plugins()
                self.after(0, lambda r=result: self._on_plugins_ready(r.plugins))
            except Exception:
                pass
            try:
                apps = scan_music_apps()
                self.after(0, lambda a=apps: self._on_apps_ready(a))
            except Exception:
                pass

        threading.Thread(target=_scan, daemon=True).start()

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass
        self.destroy()
