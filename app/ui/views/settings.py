"""
Settings view — application preferences, scan locations, and database controls.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from app.core.settings import (
    ALL_FORMATS,
    DAW_OPTIONS,
    AppSettings,
)
from app.db.database import DEFAULT_DB_PATH

if TYPE_CHECKING:
    from app.db.database import Database
    from app.db.repositories.settings import SettingsRepository

# ── Palette ───────────────────────────────────────────────────────────────────
BG_CARD       = "#13161F"
BG_INNER      = "#0D0F18"
ACCENT        = "#6C8EF5"
ACCENT_HOVER  = "#8BAAF7"
ACCENT_DANGER = "#F56C6C"
DANGER_HOVER  = "#F78080"
TEXT_PRIMARY  = "#E8EAF0"
TEXT_MUTED    = "#6B7280"
BORDER        = "#1C1F2E"
BG_PILL       = "#1C1F2E"


class SettingsView(ctk.CTkFrame):
    """Application settings and database management panel."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        db: "Database",
        **kwargs,
    ) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._db = db

        from app.db.repositories.settings import SettingsRepository
        from app.db.repositories.plugins import PluginRepository
        from app.db.repositories.music_apps import MusicAppRepository

        self._settings_repo = SettingsRepository(db)
        self._plugin_repo   = PluginRepository(db)
        self._apps_repo     = MusicAppRepository(db)
        self._settings      = AppSettings.load(self._settings_repo)

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_scroll_body()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Settings",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="DAW profile, plugin formats, scan locations, and database controls",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

    def _build_scroll_body(self) -> None:
        outer = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT,
        )
        outer.grid(row=1, column=0, sticky="nsew", padx=28, pady=(20, 20))
        outer.grid_columnconfigure(0, weight=1)

        self._build_daw_section(outer)
        self._build_formats_section(outer)
        self._build_scan_paths_section(outer)
        self._build_cache_section(outer)
        self._build_database_section(outer)
        self._build_save_row(outer)

    # ── Section: DAW Profile ─────────────────────────────────────────────────

    def _build_daw_section(self, parent: ctk.CTkFrame) -> None:
        card = self._card(parent, "DAW Profile", "⊕")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 16))
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row,
            text="Preferred DAW",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        self._daw_var = tk.StringVar(
            value=self._settings.preferred_daw or "Select DAW…"
        )
        self._daw_menu = ctk.CTkOptionMenu(
            row,
            values=DAW_OPTIONS,
            variable=self._daw_var,
            fg_color=BG_INNER,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_text_color=TEXT_PRIMARY,
            dropdown_hover_color=BG_PILL,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=13),
            width=220,
        )
        self._daw_menu.grid(row=0, column=1, sticky="w")

    # ── Section: Plugin Formats ──────────────────────────────────────────────

    def _build_formats_section(self, parent: ctk.CTkFrame) -> None:
        card = self._card(parent, "Plugin Formats", "◈")

        ctk.CTkLabel(
            card,
            text="Preferred formats (used for cleanup recommendations and health analysis)",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 16))

        self._format_vars: dict[str, tk.BooleanVar] = {}
        for fmt in ALL_FORMATS:
            var = tk.BooleanVar(value=fmt in self._settings.preferred_formats)
            self._format_vars[fmt] = var
            cb = ctk.CTkCheckBox(
                row,
                text=fmt,
                variable=var,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                checkmark_color="#FFFFFF",
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(size=13),
            )
            cb.pack(side="left", padx=(0, 20))

    # ── Section: Scan Paths ──────────────────────────────────────────────────

    def _build_scan_paths_section(self, parent: ctk.CTkFrame) -> None:
        card = self._card(parent, "Scan Locations", "⊞")

        # Plugin paths
        ctk.CTkLabel(
            card,
            text="Plugin scan paths",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 6))

        self._plugin_paths_frame = ctk.CTkFrame(card, fg_color=BG_INNER, corner_radius=8)
        self._plugin_paths_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._plugin_path_labels: list[ctk.CTkLabel] = []
        self._refresh_path_list(
            self._plugin_paths_frame,
            self._settings.plugin_scan_paths,
            self._plugin_path_labels,
            is_plugin=True,
        )

        plugin_btn_row = ctk.CTkFrame(card, fg_color="transparent")
        plugin_btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            plugin_btn_row,
            text="+ Add Plugin Path",
            width=160,
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color=BG_PILL,
            hover_color=BORDER,
            text_color=ACCENT,
            command=self._add_plugin_path,
        ).pack(side="left")
        ctk.CTkButton(
            plugin_btn_row,
            text="Reset to Defaults",
            width=140,
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover_color=BORDER,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._reset_plugin_paths,
        ).pack(side="left", padx=(8, 0))

        # App paths
        ctk.CTkLabel(
            card,
            text="Music software scan paths",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 6))

        self._app_paths_frame = ctk.CTkFrame(card, fg_color=BG_INNER, corner_radius=8)
        self._app_paths_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._app_path_labels: list[ctk.CTkLabel] = []
        self._refresh_path_list(
            self._app_paths_frame,
            self._settings.app_scan_paths,
            self._app_path_labels,
            is_plugin=False,
        )

        app_btn_row = ctk.CTkFrame(card, fg_color="transparent")
        app_btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            app_btn_row,
            text="+ Add App Path",
            width=140,
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color=BG_PILL,
            hover_color=BORDER,
            text_color=ACCENT,
            command=self._add_app_path,
        ).pack(side="left")
        ctk.CTkButton(
            app_btn_row,
            text="Reset to Defaults",
            width=140,
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover_color=BORDER,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._reset_app_paths,
        ).pack(side="left", padx=(8, 0))

    def _refresh_path_list(
        self,
        container: ctk.CTkFrame,
        paths: list[str],
        label_list: list,
        is_plugin: bool,
    ) -> None:
        for w in container.winfo_children():
            w.destroy()
        label_list.clear()

        if not paths:
            ctk.CTkLabel(
                container,
                text="No paths configured",
                font=ctk.CTkFont(size=12),
                text_color=TEXT_MUTED,
            ).pack(anchor="w", padx=12, pady=8)
            return

        for i, p in enumerate(paths):
            row = ctk.CTkFrame(container, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(4 if i == 0 else 0, 0))
            row.grid_columnconfigure(0, weight=1)

            lbl = ctk.CTkLabel(
                row,
                text=p,
                font=ctk.CTkFont(size=11, family="SF Mono"),
                text_color=TEXT_MUTED,
                anchor="w",
            )
            lbl.grid(row=0, column=0, sticky="w", padx=(4, 8), pady=4)

            rm_btn = ctk.CTkButton(
                row,
                text="✕",
                width=24,
                height=24,
                corner_radius=4,
                font=ctk.CTkFont(size=10),
                fg_color="transparent",
                hover_color=ACCENT_DANGER,
                text_color=TEXT_MUTED,
                command=lambda path=p, ip=is_plugin: self._remove_path(path, ip),
            )
            rm_btn.grid(row=0, column=1, sticky="e", padx=(0, 4))
            label_list.append(lbl)

    # ── Section: Cache ────────────────────────────────────────────────────────

    def _build_cache_section(self, parent: ctk.CTkFrame) -> None:
        card = self._card(parent, "Cache Behaviour", "◎")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 8))
        row.grid_columnconfigure(1, weight=1)

        self._auto_load_var = tk.BooleanVar(value=self._settings.auto_load_cache)
        ctk.CTkCheckBox(
            row,
            text="Load cached results on startup (skip full rescan if cache exists)",
            variable=self._auto_load_var,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            checkmark_color="#FFFFFF",
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=13),
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ctk.CTkLabel(
            card,
            text="Max scan sessions to keep",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self._max_sessions_var = tk.StringVar(
            value=str(self._settings.cache_max_sessions)
        )
        ctk.CTkEntry(
            card,
            textvariable=self._max_sessions_var,
            width=80,
            height=34,
            fg_color=BG_INNER,
            text_color=TEXT_PRIMARY,
            border_color=BORDER,
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", padx=16, pady=(0, 16))

    # ── Section: Database ─────────────────────────────────────────────────────

    def _build_database_section(self, parent: ctk.CTkFrame) -> None:
        card = self._card(parent, "Database", "⊘")

        # DB path
        path_frame = ctk.CTkFrame(card, fg_color=BG_INNER, corner_radius=8)
        path_frame.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            path_frame,
            text="Database path",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            path_frame,
            text=str(DEFAULT_DB_PATH),
            font=ctk.CTkFont(size=11, family="SF Mono"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # Session counts
        self._stats_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._stats_frame.pack(fill="x", padx=16, pady=(0, 12))
        self._refresh_stats()

        # Danger zone
        danger_row = ctk.CTkFrame(card, fg_color="transparent")
        danger_row.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkButton(
            danger_row,
            text="Clear Plugin Cache",
            width=160,
            height=36,
            corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color=ACCENT_DANGER,
            text_color=ACCENT_DANGER,
            border_width=1,
            border_color=ACCENT_DANGER,
            command=self._clear_plugin_cache,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            danger_row,
            text="Clear App Cache",
            width=160,
            height=36,
            corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color=ACCENT_DANGER,
            text_color=ACCENT_DANGER,
            border_width=1,
            border_color=ACCENT_DANGER,
            command=self._clear_app_cache,
        ).pack(side="left")

    def _refresh_stats(self) -> None:
        for w in self._stats_frame.winfo_children():
            w.destroy()

        plugin_sessions = self._plugin_repo.get_session_count()
        app_sessions    = self._apps_repo.get_session_count()

        for label, value in [
            ("Plugin scan sessions", plugin_sessions),
            ("Music app scan sessions", app_sessions),
        ]:
            row = ctk.CTkFrame(self._stats_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row,
                text=label,
                font=ctk.CTkFont(size=12),
                text_color=TEXT_MUTED,
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=str(value),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=TEXT_PRIMARY,
            ).pack(side="left", padx=(8, 0))

    # ── Save row ──────────────────────────────────────────────────────────────

    def _build_save_row(self, parent: ctk.CTkFrame) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))

        ctk.CTkButton(
            row,
            text="  ✓  Save Settings",
            width=180,
            height=42,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._save,
        ).pack(side="left")

        self._save_status = ctk.CTkLabel(
            row,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        )
        self._save_status.pack(side="left", padx=16)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _add_plugin_path(self) -> None:
        path = filedialog.askdirectory(title="Add Plugin Scan Path")
        if path and path not in self._settings.plugin_scan_paths:
            self._settings.plugin_scan_paths.append(path)
            self._refresh_path_list(
                self._plugin_paths_frame,
                self._settings.plugin_scan_paths,
                self._plugin_path_labels,
                is_plugin=True,
            )

    def _add_app_path(self) -> None:
        path = filedialog.askdirectory(title="Add App Scan Path")
        if path and path not in self._settings.app_scan_paths:
            self._settings.app_scan_paths.append(path)
            self._refresh_path_list(
                self._app_paths_frame,
                self._settings.app_scan_paths,
                self._app_path_labels,
                is_plugin=False,
            )

    def _remove_path(self, path: str, is_plugin: bool) -> None:
        if is_plugin:
            if path in self._settings.plugin_scan_paths:
                self._settings.plugin_scan_paths.remove(path)
            self._refresh_path_list(
                self._plugin_paths_frame,
                self._settings.plugin_scan_paths,
                self._plugin_path_labels,
                is_plugin=True,
            )
        else:
            if path in self._settings.app_scan_paths:
                self._settings.app_scan_paths.remove(path)
            self._refresh_path_list(
                self._app_paths_frame,
                self._settings.app_scan_paths,
                self._app_path_labels,
                is_plugin=False,
            )

    def _reset_plugin_paths(self) -> None:
        from app.core.scanner import SCAN_PATHS
        self._settings.plugin_scan_paths = list(SCAN_PATHS)
        self._refresh_path_list(
            self._plugin_paths_frame,
            self._settings.plugin_scan_paths,
            self._plugin_path_labels,
            is_plugin=True,
        )

    def _reset_app_paths(self) -> None:
        from app.core.music_software_scanner import SCAN_PATHS
        self._settings.app_scan_paths = list(SCAN_PATHS)
        self._refresh_path_list(
            self._app_paths_frame,
            self._settings.app_scan_paths,
            self._app_path_labels,
            is_plugin=False,
        )

    def _clear_plugin_cache(self) -> None:
        if messagebox.askyesno(
            "Clear Plugin Cache",
            "Delete all plugin scan history from the database?\nThis cannot be undone.",
        ):
            self._plugin_repo.clear_all()
            self._refresh_stats()
            messagebox.showinfo("Cache cleared", "Plugin scan history has been removed.")

    def _clear_app_cache(self) -> None:
        if messagebox.askyesno(
            "Clear App Cache",
            "Delete all music app scan history from the database?\nThis cannot be undone.",
        ):
            self._apps_repo.clear_all()
            self._refresh_stats()
            messagebox.showinfo("Cache cleared", "Music app scan history has been removed.")

    def _save(self) -> None:
        # Collect DAW
        daw = self._daw_var.get()
        if daw == "Select DAW…":
            daw = ""
        self._settings.preferred_daw = daw

        # Collect formats
        self._settings.preferred_formats = [
            fmt for fmt, var in self._format_vars.items() if var.get()
        ]

        # Auto-load cache
        self._settings.auto_load_cache = self._auto_load_var.get()

        # Max sessions
        try:
            self._settings.cache_max_sessions = max(
                1, int(self._max_sessions_var.get())
            )
        except ValueError:
            self._settings.cache_max_sessions = 10

        self._settings.save(self._settings_repo)

        self._save_status.configure(text="✓ Settings saved", text_color=ACCENT)
        self.after(2500, lambda: self._save_status.configure(text=""))

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _card(self, parent: ctk.CTkFrame, title: str, icon: str) -> ctk.CTkFrame:
        """Return a styled card frame with a title, appended to *parent*."""
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
        card.pack(fill="x", pady=(0, 16))

        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(14, 10))

        ctk.CTkLabel(
            title_row,
            text=f"{icon}  {title}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(
            fill="x", padx=16, pady=(0, 12)
        )

        return card
