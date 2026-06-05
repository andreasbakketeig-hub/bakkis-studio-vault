"""
Settings view — full-featured application settings control center.

Six tabbed sections: Studio, Scanning, Cleanup, Migration, Interface, Database.
All settings are persisted via the SQLite settings repository.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from app.core.settings import (
    ALL_FORMATS,
    DAW_OPTIONS,
    MACHINE_ROLES,
    DASHBOARD_DENSITIES,
    COMPARISON_BEHAVIORS,
    VST2_SENSITIVITIES,
    THEME_PRESETS,
    AppSettings,
)
from app.db.database import DEFAULT_DB_PATH

if TYPE_CHECKING:
    from app.db.database import Database

# ── Palette ───────────────────────────────────────────────────────────────────
BG_CARD        = "#13161F"
BG_INNER       = "#0D0F18"
BG_FOOTER      = "#0F1219"
ACCENT         = "#6C8EF5"
ACCENT_HOVER   = "#8BAAF7"
ACCENT_DANGER  = "#F56C6C"
DANGER_HOVER   = "#F78080"
ACCENT_GREEN   = "#4ADE80"
TEXT_PRIMARY   = "#E8EAF0"
TEXT_SECONDARY = "#94A3B8"
TEXT_MUTED     = "#6B7280"
BORDER         = "#1C1F2E"
BG_PILL        = "#1C1F2E"
BORDER_BRIGHT  = "#242B48"

TABS: list[tuple[str, str]] = [
    ("studio",    "Studio"),
    ("scanning",  "Scanning"),
    ("cleanup",   "Cleanup"),
    ("migration", "Migration"),
    ("interface", "Interface"),
    ("database",  "Database"),
]

ACCENT_SWATCHES: list[tuple[str, str]] = [
    ("#6C8EF5", "Blue"),
    ("#4ADE80", "Green"),
    ("#F59E0B", "Amber"),
    ("#F87171", "Red"),
    ("#A855F7", "Purple"),
    ("#22D3EE", "Cyan"),
    ("#FB923C", "Orange"),
    ("#E879F9", "Pink"),
]


class SettingsView(ctk.CTkFrame):
    """Full settings control center with six tabbed sections."""

    def __init__(self, parent: ctk.CTkFrame, db: "Database", **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._db = db

        from app.db.repositories.settings import SettingsRepository
        from app.db.repositories.plugins import PluginRepository
        from app.db.repositories.music_apps import MusicAppRepository

        self._settings_repo = SettingsRepository(db)
        self._plugin_repo   = PluginRepository(db)
        self._apps_repo     = MusicAppRepository(db)
        self._settings      = AppSettings.load(self._settings_repo)

        self._active_tab: str = "studio"
        self._tab_btns: dict[str, ctk.CTkButton] = {}
        self._tab_scrolls: dict[str, ctk.CTkScrollableFrame] = {}

        # All tk.Vars are initialised here so _save() can read every tab's
        # state regardless of which tab is currently visible.
        self._init_vars()
        self._build()

    # ── Var initialisation ────────────────────────────────────────────────────

    def _init_vars(self) -> None:
        s = self._settings

        # Studio
        self._daw_var          = tk.StringVar(value=s.preferred_daw or "Select DAW…")
        self._format_vars: dict[str, tk.BooleanVar] = {
            fmt: tk.BooleanVar(value=fmt in s.preferred_formats)
            for fmt in ALL_FORMATS
        }
        self._machine_role_var = tk.StringVar(value=s.machine_role or MACHINE_ROLES[0])

        # Scanning
        self._deep_scan_var    = tk.BooleanVar(value=s.deep_scan_enabled)
        self._auto_rescan_var  = tk.BooleanVar(value=s.auto_rescan_on_launch)
        self._bg_scanning_var  = tk.BooleanVar(value=s.background_scanning)
        self._auto_load_var    = tk.BooleanVar(value=s.auto_load_cache)
        self._max_sessions_var = tk.StringVar(value=str(s.cache_max_sessions))

        # Cleanup
        self._never_remove_var   = tk.BooleanVar(value=s.never_remove_only_format)
        self._safe_mode_var      = tk.BooleanVar(value=s.safe_mode_cleanup)
        self._vst2_sens_var      = tk.StringVar(value=s.legacy_vst2_sensitivity)
        self._ignored_vendors: list[str] = list(s.ignored_vendors)

        # Migration
        self._machine_name_var  = tk.StringVar(value=s.machine_display_name)
        self._snapshot_var      = tk.StringVar(value=s.snapshot_export_folder)
        self._comparison_var    = tk.StringVar(value=s.comparison_behavior)
        self._threshold_var     = tk.DoubleVar(value=float(s.migration_readiness_threshold))

        # Interface
        self._compact_sidebar_var   = tk.BooleanVar(value=s.compact_sidebar)
        self._reduced_motion_var    = tk.BooleanVar(value=s.reduced_motion)
        self._dashboard_density_var = tk.StringVar(value=s.dashboard_density)
        self._accent_color_var      = tk.StringVar(value=s.accent_color)
        self._theme_preset_var      = tk.StringVar(value=s.theme_preset)

    # ── Top-level layout ──────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_tab_bar()
        self._build_content_area()
        self._build_save_row()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Settings",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Studio profile, scan configuration, and application preferences",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

    # ── Tab bar ───────────────────────────────────────────────────────────────

    def _build_tab_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=28, pady=(18, 0))

        for key, label in TABS:
            active = key == self._active_tab
            btn = ctk.CTkButton(
                bar,
                text=label,
                width=100,
                height=34,
                corner_radius=9,
                font=ctk.CTkFont(size=12, weight="bold" if active else "normal"),
                fg_color=ACCENT if active else BG_CARD,
                hover_color=ACCENT_HOVER if active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
                border_width=1,
                border_color=ACCENT if active else BORDER,
                command=lambda k=key: self._switch_tab(k),
            )
            btn.pack(side="left", padx=(0, 6))
            self._tab_btns[key] = btn

    def _switch_tab(self, key: str) -> None:
        if key == self._active_tab:
            return

        if self._active_tab in self._tab_scrolls:
            self._tab_scrolls[self._active_tab].grid_remove()

        for k, btn in self._tab_btns.items():
            active = k == key
            btn.configure(
                fg_color=ACCENT if active else BG_CARD,
                hover_color=ACCENT_HOVER if active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
                font=ctk.CTkFont(size=12, weight="bold" if active else "normal"),
                border_color=ACCENT if active else BORDER,
            )

        self._active_tab = key
        if key in self._tab_scrolls:
            self._tab_scrolls[key].grid()

    # ── Content area ──────────────────────────────────────────────────────────

    def _build_content_area(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=2, column=0, sticky="nsew", padx=28, pady=(14, 0))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        for key, _ in TABS:
            scroll = ctk.CTkScrollableFrame(
                container,
                fg_color="transparent",
                scrollbar_button_color=BORDER,
                scrollbar_button_hover_color=ACCENT,
            )
            scroll.grid(row=0, column=0, sticky="nsew")
            scroll.grid_columnconfigure(0, weight=1)
            self._tab_scrolls[key] = scroll

        self._build_studio_tab(self._tab_scrolls["studio"])
        self._build_scanning_tab(self._tab_scrolls["scanning"])
        self._build_cleanup_tab(self._tab_scrolls["cleanup"])
        self._build_migration_tab(self._tab_scrolls["migration"])
        self._build_interface_tab(self._tab_scrolls["interface"])
        self._build_database_tab(self._tab_scrolls["database"])

        for key, scroll in self._tab_scrolls.items():
            if key != self._active_tab:
                scroll.grid_remove()

    # ── Tab: Studio ───────────────────────────────────────────────────────────

    def _build_studio_tab(self, parent: ctk.CTkScrollableFrame) -> None:
        card = self._card(parent, "Primary DAW")

        daw_row = ctk.CTkFrame(card, fg_color="transparent")
        daw_row.pack(fill="x", padx=16, pady=(0, 16))
        daw_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            daw_row, text="Preferred DAW",
            font=ctk.CTkFont(size=13), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        ctk.CTkOptionMenu(
            daw_row,
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
            width=240,
        ).grid(row=0, column=1, sticky="w")

        # ── Plugin Formats ────────────────────────────────────────────────────
        card2 = self._card(parent, "Preferred Plugin Formats")

        ctk.CTkLabel(
            card2,
            text="Used for cleanup recommendations, health analysis, and migration scoring",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        fmt_row = ctk.CTkFrame(card2, fg_color="transparent")
        fmt_row.pack(fill="x", padx=16, pady=(0, 16))

        for fmt in ALL_FORMATS:
            ctk.CTkCheckBox(
                fmt_row,
                text=fmt,
                variable=self._format_vars[fmt],
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                checkmark_color="#FFFFFF",
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(size=13),
            ).pack(side="left", padx=(0, 28))

        # ── Machine Role ──────────────────────────────────────────────────────
        card3 = self._card(parent, "Machine Role")

        ctk.CTkLabel(
            card3,
            text="Describes how this machine is used in your studio workflow",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        role_grid = ctk.CTkFrame(card3, fg_color="transparent")
        role_grid.pack(fill="x", padx=16, pady=(0, 16))

        for i, role in enumerate(MACHINE_ROLES):
            ctk.CTkRadioButton(
                role_grid,
                text=role,
                variable=self._machine_role_var,
                value=role,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(size=13),
            ).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 28), pady=(0, 8))

    # ── Tab: Scanning ─────────────────────────────────────────────────────────

    def _build_scanning_tab(self, parent: ctk.CTkScrollableFrame) -> None:
        # Plugin scan locations
        card = self._card(parent, "Plugin Scan Locations")

        ctk.CTkLabel(
            card, text="Plugin scan paths",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 6))

        self._plugin_paths_frame = ctk.CTkFrame(card, fg_color=BG_INNER, corner_radius=8)
        self._plugin_paths_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._plugin_path_labels: list = []
        self._refresh_path_list(
            self._plugin_paths_frame,
            self._settings.plugin_scan_paths,
            self._plugin_path_labels,
            is_plugin=True,
        )

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            btn_row, text="+ Add Path",
            width=130, height=32, corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color=BG_PILL, hover_color=BORDER, text_color=ACCENT,
            command=self._add_plugin_path,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Reset to Defaults",
            width=148, height=32, corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", hover_color=BORDER,
            text_color=TEXT_MUTED, border_width=1, border_color=BORDER,
            command=self._reset_plugin_paths,
        ).pack(side="left", padx=(8, 0))

        # Music software scan locations
        card2 = self._card(parent, "Music Software Scan Locations")

        ctk.CTkLabel(
            card2, text="Music software scan paths",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 6))

        self._app_paths_frame = ctk.CTkFrame(card2, fg_color=BG_INNER, corner_radius=8)
        self._app_paths_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._app_path_labels: list = []
        self._refresh_path_list(
            self._app_paths_frame,
            self._settings.app_scan_paths,
            self._app_path_labels,
            is_plugin=False,
        )

        btn_row2 = ctk.CTkFrame(card2, fg_color="transparent")
        btn_row2.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            btn_row2, text="+ Add Path",
            width=130, height=32, corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color=BG_PILL, hover_color=BORDER, text_color=ACCENT,
            command=self._add_app_path,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row2, text="Reset to Defaults",
            width=148, height=32, corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="transparent", hover_color=BORDER,
            text_color=TEXT_MUTED, border_width=1, border_color=BORDER,
            command=self._reset_app_paths,
        ).pack(side="left", padx=(8, 0))

        # Scan behavior toggles
        card3 = self._card(parent, "Scan Behavior")

        self._toggle_row(
            card3, "Deep scan",
            "Scan all nested subdirectories — slower but more thorough",
            self._deep_scan_var,
        )
        ctk.CTkFrame(card3, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=2)
        self._toggle_row(
            card3, "Auto-rescan on launch",
            "Automatically trigger a fresh scan each time the app starts",
            self._auto_rescan_var,
        )
        ctk.CTkFrame(card3, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=2)
        self._toggle_row(
            card3, "Background scanning",
            "Run scans in the background without blocking the UI",
            self._bg_scanning_var,
        )
        ctk.CTkFrame(card3, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=2)
        self._toggle_row(
            card3, "Load cached results on startup",
            "Use stored scan data on launch instead of rescanning",
            self._auto_load_var,
        )

        ctk.CTkFrame(card3, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=(2, 8))

        sessions_row = ctk.CTkFrame(card3, fg_color="transparent")
        sessions_row.pack(fill="x", padx=16, pady=(0, 16))
        sessions_row.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(sessions_row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            left, text="Max cached sessions",
            font=ctk.CTkFont(size=13), text_color=TEXT_PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            left, text="Number of scan sessions stored in the database",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(1, 0))

        ctk.CTkEntry(
            sessions_row,
            textvariable=self._max_sessions_var,
            width=72, height=34,
            fg_color=BG_INNER, text_color=TEXT_PRIMARY,
            border_color=BORDER, font=ctk.CTkFont(size=13),
        ).grid(row=0, column=1, sticky="e")

    # ── Tab: Cleanup ──────────────────────────────────────────────────────────

    def _build_cleanup_tab(self, parent: ctk.CTkScrollableFrame) -> None:
        card = self._card(parent, "Safety Rules")

        self._toggle_row(
            card,
            "Never recommend removing the only available format",
            "Protects against being left with no usable version of a plugin",
            self._never_remove_var,
        )
        ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=2)
        self._toggle_row(
            card,
            "Safe mode",
            "Show extra confirmation prompts before any destructive cleanup actions",
            self._safe_mode_var,
        )

        ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=(2, 8))
        ctk.CTkLabel(
            card,
            text="These rules apply globally to Cleanup Recommendations and Migration modules.",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 16))

        # VST2 sensitivity
        card2 = self._card(parent, "Legacy VST2 Warning Sensitivity")

        ctk.CTkLabel(
            card2,
            text="Controls how aggressively VST2 plugins are flagged as legacy or redundant",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        vst2_row = ctk.CTkFrame(card2, fg_color="transparent")
        vst2_row.pack(fill="x", padx=16, pady=(0, 8))

        for sensitivity in VST2_SENSITIVITIES:
            ctk.CTkRadioButton(
                vst2_row,
                text=sensitivity,
                variable=self._vst2_sens_var,
                value=sensitivity,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(size=13),
            ).pack(side="left", padx=(0, 28))

        _vst2_desc_map = {
            "Low":    "Only flag VST2 when a VST3 equivalent is also present",
            "Medium": "Flag VST2 when a VST3 alternative exists, even if installed alone",
            "High":   "Flag all VST2 plugins regardless of available alternatives",
        }

        self._vst2_desc_label = ctk.CTkLabel(
            card2,
            text=_vst2_desc_map.get(self._vst2_sens_var.get(), ""),
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        )
        self._vst2_desc_label.pack(anchor="w", padx=16, pady=(0, 16))

        def _on_vst2_change(*_):
            self._vst2_desc_label.configure(
                text=_vst2_desc_map.get(self._vst2_sens_var.get(), "")
            )

        self._vst2_sens_var.trace_add("write", _on_vst2_change)

        # Ignored vendors / plugins
        card3 = self._card(parent, "Ignored Vendors & Plugins")

        ctk.CTkLabel(
            card3,
            text="Vendors and plugin names listed here are excluded from all cleanup analysis",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        self._vendor_list_frame = ctk.CTkFrame(card3, fg_color=BG_INNER, corner_radius=8)
        self._vendor_list_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._refresh_vendor_list()

        add_row = ctk.CTkFrame(card3, fg_color="transparent")
        add_row.pack(fill="x", padx=16, pady=(0, 16))
        add_row.grid_columnconfigure(0, weight=1)

        self._vendor_entry_var = tk.StringVar()
        entry = ctk.CTkEntry(
            add_row,
            textvariable=self._vendor_entry_var,
            placeholder_text="Vendor or plugin name…",
            height=34,
            fg_color=BG_INNER,
            text_color=TEXT_PRIMARY,
            border_color=BORDER,
            font=ctk.CTkFont(size=12),
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        entry.bind("<Return>", lambda _e: self._add_ignored_vendor())

        ctk.CTkButton(
            add_row, text="Add",
            width=80, height=34, corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color=BG_PILL, hover_color=BORDER, text_color=ACCENT,
            command=self._add_ignored_vendor,
        ).grid(row=0, column=1)

    # ── Tab: Migration ────────────────────────────────────────────────────────

    def _build_migration_tab(self, parent: ctk.CTkScrollableFrame) -> None:
        card = self._card(parent, "Machine Identity")

        ctk.CTkLabel(
            card,
            text="Identifies this machine in migration snapshots and cross-machine comparisons",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        name_row = ctk.CTkFrame(card, fg_color="transparent")
        name_row.pack(fill="x", padx=16, pady=(0, 16))
        name_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            name_row, text="Display name",
            font=ctk.CTkFont(size=13), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))

        ctk.CTkEntry(
            name_row,
            textvariable=self._machine_name_var,
            placeholder_text="e.g.  MacBook Pro (Main Studio)",
            height=36,
            fg_color=BG_INNER,
            text_color=TEXT_PRIMARY,
            border_color=BORDER,
            font=ctk.CTkFont(size=13),
        ).grid(row=0, column=1, sticky="ew")

        # Snapshot export folder
        card2 = self._card(parent, "Snapshot Export Folder")

        ctk.CTkLabel(
            card2,
            text="Default destination for plugin inventory snapshot files",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        folder_frame = ctk.CTkFrame(card2, fg_color=BG_INNER, corner_radius=8)
        folder_frame.pack(fill="x", padx=16, pady=(0, 8))
        folder_frame.grid_columnconfigure(0, weight=1)

        self._snapshot_path_label = ctk.CTkLabel(
            folder_frame,
            text=self._snapshot_var.get() or "No folder selected",
            font=ctk.CTkFont(size=11, family="SF Mono"),
            text_color=TEXT_PRIMARY if self._snapshot_var.get() else TEXT_MUTED,
            anchor="w",
        )
        self._snapshot_path_label.grid(row=0, column=0, sticky="w", padx=12, pady=10)

        ctk.CTkButton(
            folder_frame, text="Choose…",
            width=80, height=28, corner_radius=6,
            font=ctk.CTkFont(size=11),
            fg_color=BG_PILL, hover_color=BORDER_BRIGHT, text_color=ACCENT,
            command=self._pick_snapshot_folder,
        ).grid(row=0, column=1, sticky="e", padx=(0, 8))

        ctk.CTkLabel(
            card2,
            text="Snapshots compare plugin inventories between machines to assess migration readiness.",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 16))

        # Comparison behavior
        card3 = self._card(parent, "Comparison Behavior")

        ctk.CTkLabel(
            card3,
            text="How plugins are matched when comparing two machine snapshots",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        for behavior in COMPARISON_BEHAVIORS:
            ctk.CTkRadioButton(
                card3,
                text=behavior,
                variable=self._comparison_var,
                value=behavior,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(size=13),
            ).pack(anchor="w", padx=16, pady=(0, 8))

        ctk.CTkFrame(card3, height=8, fg_color="transparent").pack()

        # Migration readiness threshold
        card4 = self._card(parent, "Migration Readiness Threshold")

        ctk.CTkLabel(
            card4,
            text="Minimum match percentage required before a migration is considered ready",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 14))

        threshold_row = ctk.CTkFrame(card4, fg_color="transparent")
        threshold_row.pack(fill="x", padx=16, pady=(0, 8))
        threshold_row.grid_columnconfigure(0, weight=1)

        ctk.CTkSlider(
            threshold_row,
            from_=0, to=100,
            variable=self._threshold_var,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            fg_color=BORDER,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 16))

        self._threshold_label = ctk.CTkLabel(
            threshold_row,
            text=f"{int(self._threshold_var.get())}%",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=ACCENT,
            width=56,
        )
        self._threshold_label.grid(row=0, column=1, sticky="e")

        def _on_threshold(*_):
            self._threshold_label.configure(
                text=f"{int(self._threshold_var.get())}%"
            )

        self._threshold_var.trace_add("write", _on_threshold)

        ctk.CTkLabel(
            card4,
            text="Migrations with a match percentage below this threshold will be flagged as not ready.",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(4, 16))

    # ── Tab: Interface ────────────────────────────────────────────────────────

    def _build_interface_tab(self, parent: ctk.CTkScrollableFrame) -> None:
        card = self._card(parent, "Layout")

        self._toggle_row(
            card, "Compact sidebar",
            "Reduce sidebar width and show icon-only navigation",
            self._compact_sidebar_var,
        )
        ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=2)
        self._toggle_row(
            card, "Reduced motion",
            "Minimize animations and transitions throughout the app",
            self._reduced_motion_var,
        )

        ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=(2, 8))

        density_row = ctk.CTkFrame(card, fg_color="transparent")
        density_row.pack(fill="x", padx=16, pady=(0, 16))
        density_row.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(density_row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            left, text="Dashboard density",
            font=ctk.CTkFont(size=13), text_color=TEXT_PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            left, text="Controls spacing and information density across views",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(1, 0))

        ctk.CTkOptionMenu(
            density_row,
            values=DASHBOARD_DENSITIES,
            variable=self._dashboard_density_var,
            fg_color=BG_INNER,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_text_color=TEXT_PRIMARY,
            dropdown_hover_color=BG_PILL,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=13),
            width=180,
        ).grid(row=0, column=1, sticky="e")

        # Appearance
        card2 = self._card(parent, "Appearance")

        ctk.CTkLabel(
            card2, text="Accent color",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        swatch_row = ctk.CTkFrame(card2, fg_color="transparent")
        swatch_row.pack(fill="x", padx=16, pady=(0, 16))

        self._swatch_btns: dict[str, ctk.CTkButton] = {}
        for color, _name in ACCENT_SWATCHES:
            selected = self._accent_color_var.get() == color
            btn = ctk.CTkButton(
                swatch_row,
                text="✓" if selected else "",
                width=34, height=34,
                corner_radius=17,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=color,
                hover_color=color,
                text_color="#FFFFFF",
                border_width=3 if selected else 0,
                border_color="#FFFFFF" if selected else color,
                command=lambda c=color: self._select_accent(c),
            )
            btn.pack(side="left", padx=(0, 10))
            self._swatch_btns[color] = btn

        ctk.CTkFrame(card2, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            card2, text="Theme preset",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        theme_row = ctk.CTkFrame(card2, fg_color="transparent")
        theme_row.pack(fill="x", padx=16, pady=(0, 10))

        self._theme_btns: dict[str, ctk.CTkButton] = {}
        for preset in THEME_PRESETS:
            selected = self._theme_preset_var.get() == preset
            btn = ctk.CTkButton(
                theme_row,
                text=preset,
                height=34, corner_radius=9,
                font=ctk.CTkFont(size=12),
                fg_color=ACCENT if selected else BG_CARD,
                hover_color=ACCENT_HOVER if selected else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if selected else TEXT_MUTED,
                border_width=1,
                border_color=ACCENT if selected else BORDER,
                command=lambda p=preset: self._select_theme(p),
            )
            btn.pack(side="left", padx=(0, 8))
            self._theme_btns[preset] = btn

        ctk.CTkLabel(
            card2,
            text="Accent color can be customized independently of the theme preset.",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(2, 16))

    # ── Tab: Database ─────────────────────────────────────────────────────────

    def _build_database_tab(self, parent: ctk.CTkScrollableFrame) -> None:
        card = self._card(parent, "Database Status")

        path_frame = ctk.CTkFrame(card, fg_color=BG_INNER, corner_radius=8)
        path_frame.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(
            path_frame, text="Database path",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            path_frame,
            text=str(DEFAULT_DB_PATH),
            font=ctk.CTkFont(size=11, family="SF Mono"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        self._db_size_label = ctk.CTkLabel(
            card,
            text=self._get_db_size_str(),
            font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY,
        )
        self._db_size_label.pack(anchor="w", padx=16, pady=(0, 6))

        self._stats_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._stats_frame.pack(fill="x", padx=16, pady=(0, 16))
        self._refresh_stats()

        # Cache management
        card2 = self._card(parent, "Cache Management")

        ctk.CTkLabel(
            card2,
            text="Manage stored scan history and computed analytics data",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        actions_row = ctk.CTkFrame(card2, fg_color="transparent")
        actions_row.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkButton(
            actions_row, text="Clear Plugin Cache",
            width=170, height=36, corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="transparent", hover_color=ACCENT_DANGER,
            text_color=ACCENT_DANGER, border_width=1, border_color=ACCENT_DANGER,
            command=self._clear_plugin_cache,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            actions_row, text="Clear App Cache",
            width=150, height=36, corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="transparent", hover_color=ACCENT_DANGER,
            text_color=ACCENT_DANGER, border_width=1, border_color=ACCENT_DANGER,
            command=self._clear_app_cache,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            actions_row, text="Rebuild Analytics",
            width=160, height=36, corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="transparent", hover_color=BORDER_BRIGHT,
            text_color=TEXT_SECONDARY, border_width=1, border_color=BORDER,
            command=self._rebuild_analytics,
        ).pack(side="left")

        ctk.CTkLabel(
            card2,
            text="Clearing cache removes all stored scan history and cannot be undone.\n"
                 "Rebuild analytics refreshes all computed statistics without removing data.",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(4, 16))

    # ── Save / Reset row ──────────────────────────────────────────────────────

    def _build_save_row(self) -> None:
        footer = ctk.CTkFrame(self, fg_color=BG_FOOTER, corner_radius=0)
        footer.grid(row=3, column=0, sticky="ew")

        inner = ctk.CTkFrame(footer, fg_color="transparent")
        inner.pack(fill="x", padx=28, pady=14)

        ctk.CTkButton(
            inner, text="Save Settings",
            width=160, height=40, corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF",
            command=self._save,
        ).pack(side="left")

        ctk.CTkButton(
            inner, text="Reset to Defaults",
            width=152, height=40, corner_radius=8,
            font=ctk.CTkFont(size=13),
            fg_color="transparent", hover_color=BORDER,
            text_color=TEXT_MUTED, border_width=1, border_color=BORDER,
            command=self._reset_to_defaults,
        ).pack(side="left", padx=(10, 0))

        self._save_status = ctk.CTkLabel(
            inner, text="",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
        )
        self._save_status.pack(side="left", padx=16)

    # ── Save handler ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        s = self._settings

        # Studio
        daw = self._daw_var.get()
        s.preferred_daw      = "" if daw == "Select DAW…" else daw
        s.preferred_formats  = [f for f, v in self._format_vars.items() if v.get()]
        s.machine_role       = self._machine_role_var.get()

        # Scanning
        s.deep_scan_enabled     = self._deep_scan_var.get()
        s.auto_rescan_on_launch = self._auto_rescan_var.get()
        s.background_scanning   = self._bg_scanning_var.get()
        s.auto_load_cache       = self._auto_load_var.get()
        try:
            s.cache_max_sessions = max(1, int(self._max_sessions_var.get()))
        except ValueError:
            s.cache_max_sessions = 10

        # Cleanup
        s.never_remove_only_format = self._never_remove_var.get()
        s.safe_mode_cleanup        = self._safe_mode_var.get()
        s.legacy_vst2_sensitivity  = self._vst2_sens_var.get()
        s.ignored_vendors          = list(self._ignored_vendors)

        # Migration
        s.machine_display_name           = self._machine_name_var.get().strip()
        s.snapshot_export_folder         = self._snapshot_var.get()
        s.comparison_behavior            = self._comparison_var.get()
        s.migration_readiness_threshold  = int(round(self._threshold_var.get()))

        # Interface
        s.compact_sidebar    = self._compact_sidebar_var.get()
        s.reduced_motion     = self._reduced_motion_var.get()
        s.dashboard_density  = self._dashboard_density_var.get()
        s.accent_color       = self._accent_color_var.get()
        s.theme_preset       = self._theme_preset_var.get()

        s.save(self._settings_repo)

        self._save_status.configure(text="✓  Settings saved", text_color=ACCENT_GREEN)
        self.after(2500, lambda: self._save_status.configure(text=""))

    # ── Reset to defaults ─────────────────────────────────────────────────────

    def _reset_to_defaults(self) -> None:
        if not messagebox.askyesno(
            "Reset Settings",
            "Reset all settings to their default values?\n"
            "Changes will not be saved until you press Save Settings.",
        ):
            return

        d = AppSettings()

        self._daw_var.set(d.preferred_daw or "Select DAW…")
        for fmt, var in self._format_vars.items():
            var.set(fmt in d.preferred_formats)
        self._machine_role_var.set(d.machine_role)

        self._deep_scan_var.set(d.deep_scan_enabled)
        self._auto_rescan_var.set(d.auto_rescan_on_launch)
        self._bg_scanning_var.set(d.background_scanning)
        self._auto_load_var.set(d.auto_load_cache)
        self._max_sessions_var.set(str(d.cache_max_sessions))

        self._never_remove_var.set(d.never_remove_only_format)
        self._safe_mode_var.set(d.safe_mode_cleanup)
        self._vst2_sens_var.set(d.legacy_vst2_sensitivity)
        self._ignored_vendors.clear()
        self._refresh_vendor_list()

        self._machine_name_var.set(d.machine_display_name)
        self._snapshot_var.set(d.snapshot_export_folder)
        self._snapshot_path_label.configure(text="No folder selected", text_color=TEXT_MUTED)
        self._comparison_var.set(d.comparison_behavior)
        self._threshold_var.set(float(d.migration_readiness_threshold))

        self._compact_sidebar_var.set(d.compact_sidebar)
        self._reduced_motion_var.set(d.reduced_motion)
        self._dashboard_density_var.set(d.dashboard_density)
        self._select_accent(d.accent_color)
        self._select_theme(d.theme_preset)

        self._save_status.configure(
            text="Defaults loaded — press Save Settings to apply",
            text_color=TEXT_MUTED,
        )
        self.after(3500, lambda: self._save_status.configure(text=""))

    # ── Accent / theme selection ──────────────────────────────────────────────

    def _select_accent(self, color: str) -> None:
        self._accent_color_var.set(color)
        for c, btn in self._swatch_btns.items():
            selected = c == color
            btn.configure(
                text="✓" if selected else "",
                border_width=3 if selected else 0,
                border_color="#FFFFFF" if selected else c,
            )

    def _select_theme(self, preset: str) -> None:
        self._theme_preset_var.set(preset)
        for p, btn in self._theme_btns.items():
            active = p == preset
            btn.configure(
                fg_color=ACCENT if active else BG_CARD,
                hover_color=ACCENT_HOVER if active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
                border_color=ACCENT if active else BORDER,
            )

    # ── Path management ───────────────────────────────────────────────────────

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
        path = filedialog.askdirectory(title="Add Music Software Scan Path")
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
            self._settings.plugin_scan_paths = [
                p for p in self._settings.plugin_scan_paths if p != path
            ]
            self._refresh_path_list(
                self._plugin_paths_frame,
                self._settings.plugin_scan_paths,
                self._plugin_path_labels,
                is_plugin=True,
            )
        else:
            self._settings.app_scan_paths = [
                p for p in self._settings.app_scan_paths if p != path
            ]
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

    # ── Vendor ignore list ────────────────────────────────────────────────────

    def _add_ignored_vendor(self) -> None:
        name = self._vendor_entry_var.get().strip()
        if name and name not in self._ignored_vendors:
            self._ignored_vendors.append(name)
            self._vendor_entry_var.set("")
            self._refresh_vendor_list()

    def _remove_ignored_vendor(self, name: str) -> None:
        if name in self._ignored_vendors:
            self._ignored_vendors.remove(name)
        self._refresh_vendor_list()

    # ── Snapshot folder ───────────────────────────────────────────────────────

    def _pick_snapshot_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select Snapshot Export Folder")
        if folder:
            self._snapshot_var.set(folder)
            self._snapshot_path_label.configure(text=folder, text_color=TEXT_PRIMARY)

    # ── Cache / database actions ──────────────────────────────────────────────

    def _clear_plugin_cache(self) -> None:
        if messagebox.askyesno(
            "Clear Plugin Cache",
            "Delete all plugin scan history from the database?\nThis cannot be undone.",
        ):
            self._plugin_repo.clear_all()
            self._refresh_stats()
            self._db_size_label.configure(text=self._get_db_size_str())
            self._save_status.configure(text="✓  Plugin cache cleared", text_color=ACCENT_GREEN)
            self.after(2500, lambda: self._save_status.configure(text=""))

    def _clear_app_cache(self) -> None:
        if messagebox.askyesno(
            "Clear App Cache",
            "Delete all music app scan history from the database?\nThis cannot be undone.",
        ):
            self._apps_repo.clear_all()
            self._refresh_stats()
            self._db_size_label.configure(text=self._get_db_size_str())
            self._save_status.configure(text="✓  App cache cleared", text_color=ACCENT_GREEN)
            self.after(2500, lambda: self._save_status.configure(text=""))

    def _rebuild_analytics(self) -> None:
        self._save_status.configure(text="Rebuilding analytics…", text_color=TEXT_MUTED)
        self.update_idletasks()
        self.after(600, self._finish_rebuild)

    def _finish_rebuild(self) -> None:
        self._refresh_stats()
        self._db_size_label.configure(text=self._get_db_size_str())
        self._save_status.configure(text="✓  Analytics rebuilt", text_color=ACCENT_GREEN)
        self.after(2500, lambda: self._save_status.configure(text=""))

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _card(self, parent, title: str) -> ctk.CTkFrame:
        """Styled card with a title divider, appended to parent."""
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
        card.pack(fill="x", pady=(0, 14))

        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(14, 10))

        ctk.CTkLabel(
            title_row, text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")

        ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=16, pady=(0, 12))

        return card

    def _toggle_row(
        self,
        parent,
        label: str,
        description: str,
        var: tk.BooleanVar,
    ) -> ctk.CTkSwitch:
        """A labelled toggle row with an inline CTkSwitch."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 4))
        row.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", pady=6)

        ctk.CTkLabel(
            left, text=label,
            font=ctk.CTkFont(size=13), text_color=TEXT_PRIMARY, anchor="w",
        ).pack(anchor="w")

        if description:
            ctk.CTkLabel(
                left, text=description,
                font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="w",
            ).pack(anchor="w", pady=(1, 0))

        switch = ctk.CTkSwitch(
            row, text="",
            variable=var,
            onvalue=True, offvalue=False,
            progress_color=ACCENT,
            button_color="#FFFFFF",
            button_hover_color=ACCENT_HOVER,
            width=46,
        )
        switch.grid(row=0, column=1, sticky="e", padx=(16, 0))
        return switch

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
                container, text="No paths configured",
                font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
            ).pack(anchor="w", padx=12, pady=8)
            return

        for i, p in enumerate(paths):
            row = ctk.CTkFrame(container, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(4 if i == 0 else 0, 0))
            row.grid_columnconfigure(0, weight=1)

            lbl = ctk.CTkLabel(
                row, text=p,
                font=ctk.CTkFont(size=11, family="SF Mono"),
                text_color=TEXT_MUTED, anchor="w",
            )
            lbl.grid(row=0, column=0, sticky="w", padx=(4, 8), pady=4)

            ctk.CTkButton(
                row, text="✕",
                width=24, height=24, corner_radius=4,
                font=ctk.CTkFont(size=10),
                fg_color="transparent", hover_color=ACCENT_DANGER,
                text_color=TEXT_MUTED,
                command=lambda path=p, ip=is_plugin: self._remove_path(path, ip),
            ).grid(row=0, column=1, sticky="e", padx=(0, 4))

            label_list.append(lbl)

    def _refresh_vendor_list(self) -> None:
        for w in self._vendor_list_frame.winfo_children():
            w.destroy()

        if not self._ignored_vendors:
            ctk.CTkLabel(
                self._vendor_list_frame, text="No vendors or plugins ignored",
                font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
            ).pack(anchor="w", padx=12, pady=8)
            return

        for i, name in enumerate(self._ignored_vendors):
            row = ctk.CTkFrame(self._vendor_list_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(4 if i == 0 else 0, 0))
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row, text=name,
                font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY, anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(4, 8), pady=4)

            ctk.CTkButton(
                row, text="✕",
                width=24, height=24, corner_radius=4,
                font=ctk.CTkFont(size=10),
                fg_color="transparent", hover_color=ACCENT_DANGER,
                text_color=TEXT_MUTED,
                command=lambda n=name: self._remove_ignored_vendor(n),
            ).grid(row=0, column=1, sticky="e", padx=(0, 4))

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
                row, text=label,
                font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=str(value),
                font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_PRIMARY,
            ).pack(side="left", padx=(8, 0))

    def _get_db_size_str(self) -> str:
        try:
            size = DEFAULT_DB_PATH.stat().st_size
            if size < 1_024:
                return f"Database size:  {size} B"
            elif size < 1_048_576:
                return f"Database size:  {size / 1_024:.1f} KB"
            else:
                return f"Database size:  {size / 1_048_576:.2f} MB"
        except OSError:
            return "Database size:  unknown"
