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


class MainWindow(ctk.CTk):
    """Root application window."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Bakkis Studio Manager")
        self.geometry("1200x740")
        self.minsize(900, 600)
        self.configure(fg_color=BG_MAIN)

        # macOS window chrome
        try:
            self.tk.call(
                "::tk::unsupported::MacWindowStyle",
                "style", self._w, "document",
                "closeBox collapseBox resizable",
            )
        except Exception:
            pass

        # ── Database & repositories ───────────────────────────────────────────
        self._db              = Database()
        self._plugin_repo     = PluginRepository(self._db)
        self._apps_repo       = MusicAppRepository(self._db)
        self._settings_repo   = SettingsRepository(self._db)
        self._app_settings    = AppSettings.load(self._settings_repo)

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

        # Tidy up the DB connection when the window is closed
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        match key:
            case "studio_overview":
                view = StudioOverviewView(
                    self._content_area,
                    on_navigate=self._navigate,
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
                view = FormatAnalysisView(self._content_area)
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "plugin_health":
                view = PluginHealthView(self._content_area)
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "cleanup":
                view = CleanupRecommendationsView(self._content_area)
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
                view = MigrationAssistantView(self._content_area)
                if self._plugins:
                    view.refresh(self._plugins)
                return view

            case "settings":
                return SettingsView(self._content_area, db=self._db)

            case _:
                return ComingSoonView(self._content_area, module_key=key)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass
        self.destroy()
