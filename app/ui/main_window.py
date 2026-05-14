"""
Main application window — mounts the sidebar and swaps content views.
"""

from __future__ import annotations

import customtkinter as ctk

from app.core.scanner import Plugin
from app.ui.sidebar import Sidebar
from app.ui.views.plugin_scanner import PluginScannerView
from app.ui.views.format_analysis import FormatAnalysisView
from app.ui.views.coming_soon import ComingSoonView

BG_MAIN = "#0D0F18"
BG_CONTENT = "#10131C"


class MainWindow(ctk.CTk):
    """Root application window."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Bakkis Studio Vault")
        self.geometry("1200x740")
        self.minsize(900, 600)
        self.configure(fg_color=BG_MAIN)

        # macOS window chrome
        try:
            self.tk.call("::tk::unsupported::MacWindowStyle", "style", self._w, "document", "closeBox collapseBox resizable")  # noqa: E501
        except Exception:
            pass

        self._views: dict[str, ctk.CTkFrame] = {}
        self._active_key: str = ""
        self._plugins: list[Plugin] = []

        self._build()
        self._navigate("plugins")

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self._sidebar = Sidebar(self, on_navigate=self._navigate)
        self._sidebar.grid(row=0, column=0, sticky="nsew")

        # Content area
        self._content_area = ctk.CTkFrame(self, fg_color=BG_CONTENT, corner_radius=0)
        self._content_area.grid(row=0, column=1, sticky="nsew")
        self._content_area.grid_rowconfigure(0, weight=1)
        self._content_area.grid_columnconfigure(0, weight=1)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate(self, key: str) -> None:
        if key == self._active_key:
            return

        # Hide current view
        if self._active_key and self._active_key in self._views:
            self._views[self._active_key].grid_remove()

        # Create view on first visit
        if key not in self._views:
            self._views[key] = self._create_view(key)

        self._views[key].grid(row=0, column=0, sticky="nsew")
        self._active_key = key
        self._sidebar.activate(key)

    def _on_plugins_ready(self, plugins: list[Plugin]) -> None:
        """Called by PluginScannerView when a scan completes."""
        self._plugins = plugins
        if "format_analysis" in self._views:
            self._views["format_analysis"].refresh(plugins)  # type: ignore[union-attr]

    def _create_view(self, key: str) -> ctk.CTkFrame:
        match key:
            case "plugins":
                return PluginScannerView(
                    self._content_area,
                    on_plugins_ready=self._on_plugins_ready,
                )
            case "format_analysis":
                view = FormatAnalysisView(self._content_area)
                if self._plugins:
                    view.refresh(self._plugins)
                return view
            case _:
                return ComingSoonView(self._content_area, module_key=key)
