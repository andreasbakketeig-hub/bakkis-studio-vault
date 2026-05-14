"""
Migration Assistant view — snapshot, compare, and track studio migrations.

Four tabs:
  1. Snapshot    — scan this system and create a studio snapshot
  2. Report      — detailed report with export options (JSON / CSV / HTML→PDF)
  3. Compare     — load a reference snapshot and diff against current system
  4. Dashboard   — migration progress bars and full item list with status badges
"""

from __future__ import annotations

import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

import customtkinter as ctk

from app.core.migration_assistant import (
    STATUS_INSTALLED,
    STATUS_MISSING,
    STATUS_NEEDS_REVIEW,
    ComparisonResult,
    MigrationSnapshot,
    compare_snapshots,
    create_snapshot,
    export_migration_csv,
    export_migration_html,
    load_snapshot_json,
    save_snapshot_json,
)
from app.core.music_software_scanner import MusicApp, scan_music_apps
from app.core.scanner import Plugin, scan_plugins

if TYPE_CHECKING:
    pass

# ── Design System ─────────────────────────────────────────────────────────────

BG_MAIN      = "#0D1020"
BG_CARD      = "#131720"
BG_TABLE     = "#0D1020"
BG_ROW_EVEN  = "#131720"
BG_ROW_ODD   = "#161B28"
ACCENT       = "#6C8EF5"
ACCENT_HOVER = "#8BAAF7"
WARN         = "#F59E0B"
SUCCESS      = "#4ADE80"
DANGER       = "#F87171"
TEXT_PRIMARY = "#EEF0F8"
TEXT_SECONDARY = "#94A3B8"
TEXT_MUTED   = "#4B5870"
BORDER       = "#1C2038"
BORDER_BRIGHT = "#242B48"
BTN_SEC      = "#161B28"
BTN_SEC_HVR  = "#1C2038"

_TAG_STATUS = {
    STATUS_INSTALLED:    "installed",
    STATUS_MISSING:      "missing",
    STATUS_NEEDS_REVIEW: "needs_review",
}


# ── Main view ─────────────────────────────────────────────────────────────────

class MigrationAssistantView(ctk.CTkFrame):
    """Root frame for the Migration Assistant module."""

    def __init__(self, parent: ctk.CTkFrame, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._snapshot: MigrationSnapshot | None = None
        self._reference: MigrationSnapshot | None = None
        self._comparison: ComparisonResult | None = None
        self._current_plugins: list[Plugin] = []
        self._current_apps: list[MusicApp] = []
        self._scanning = False
        self._report_widgets: list[tk.Widget | ctk.CTkBaseClass] = []

        self._build()

    # ── Public API (wired from main window if plugins already scanned) ────────

    def refresh(self, plugins: list[Plugin]) -> None:
        """Accept plugin data shared from the main plugin scanner."""
        self._current_plugins = plugins

    # ── Top-level layout ──────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_header()
        self._build_tabs()

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 0))

        ctk.CTkLabel(
            hdr,
            text="Migration Assistant",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            hdr,
            text="Snapshot  ·  Compare  ·  Migrate",
            font=ctk.CTkFont(size=12),
            text_color=ACCENT,
            anchor="w",
        ).pack(side="left", padx=(14, 0))

    def _build_tabs(self) -> None:
        self._tabview = ctk.CTkTabview(
            self,
            fg_color=BG_CARD,
            segmented_button_fg_color=BG_MAIN,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=BG_MAIN,
            segmented_button_unselected_hover_color=BORDER_BRIGHT,
            text_color=TEXT_PRIMARY,
            text_color_disabled=TEXT_MUTED,
            corner_radius=14,
        )
        self._tabview.grid(row=1, column=0, sticky="nsew", padx=28, pady=(12, 24))

        for name in ("  Snapshot  ", "  Report  ", "  Compare  ", "  Dashboard  "):
            self._tabview.add(name)
            tab = self._tabview.tab(name)
            tab.grid_rowconfigure(0, weight=1)
            tab.grid_columnconfigure(0, weight=1)

        self._build_snapshot_tab(self._tabview.tab("  Snapshot  "))
        self._build_report_tab(self._tabview.tab("  Report  "))
        self._build_compare_tab(self._tabview.tab("  Compare  "))
        self._build_dashboard_tab(self._tabview.tab("  Dashboard  "))

    # =========================================================================
    # Tab 1 — Snapshot
    # =========================================================================

    def _build_snapshot_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(3, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))

        self._snap_btn = ctk.CTkButton(
            toolbar,
            text="◈  Create Studio Snapshot",
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            width=230,
            corner_radius=8,
            command=self._run_snapshot_scan,
        )
        self._snap_btn.pack(side="left")

        self._snap_status = ctk.CTkLabel(
            toolbar,
            text="No snapshot yet — click to scan this system",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        )
        self._snap_status.pack(side="left", padx=16)

        # ── Progress bar ──────────────────────────────────────────────────────
        self._snap_bar = ctk.CTkProgressBar(
            parent, fg_color=BORDER, progress_color=ACCENT, height=3, corner_radius=2,
        )
        self._snap_bar.set(0)
        self._snap_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(8, 0))

        # ── Stat cards ────────────────────────────────────────────────────────
        cards_row = ctk.CTkFrame(parent, fg_color="transparent")
        cards_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 0))

        self._snap_cards: dict[str, ctk.CTkLabel] = {}
        snap_stats = [
            ("plugins",      "Total Plugins"),
            ("products",     "Plugin Products"),
            ("apps",         "Music Apps"),
            ("daws",         "DAWs"),
            ("lic_mgrs",     "License Managers"),
            ("dup_formats",  "Dup. Formats"),
            ("savings",      "Est. Savings"),
        ]
        for i, (key, label) in enumerate(snap_stats):
            card = ctk.CTkFrame(cards_row, fg_color=BG_TABLE, corner_radius=10)
            card.grid(row=0, column=i, padx=(0, 8), sticky="ew")
            cards_row.grid_columnconfigure(i, weight=1)

            ctk.CTkLabel(
                card,
                text=label.upper(),
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=TEXT_MUTED,
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(10, 0))

            val = ctk.CTkLabel(
                card,
                text="—",
                font=ctk.CTkFont(size=22, weight="bold"),
                text_color=ACCENT,
                anchor="w",
            )
            val.pack(anchor="w", padx=12, pady=(2, 10))
            self._snap_cards[key] = val

        # ── Application table ─────────────────────────────────────────────────
        table_card = ctk.CTkFrame(parent, fg_color=BG_TABLE, corner_radius=12)
        table_card.grid(row=3, column=0, sticky="nsew", padx=20, pady=(14, 20))
        table_card.grid_rowconfigure(1, weight=1)
        table_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            table_card,
            text="APPLICATION INVENTORY",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))

        _apply_tree_style("Snap.Treeview")

        tree_host = tk.Frame(table_card, bg=BG_TABLE)
        tree_host.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)

        self._snap_tree = ttk.Treeview(
            tree_host,
            style="Snap.Treeview",
            columns=("name", "category", "developer", "version"),
            show="headings",
        )
        for col, heading, width in [
            ("name",      "Application", 240),
            ("category",  "Category",    160),
            ("developer", "Developer",   160),
            ("version",   "Version",     80),
        ]:
            self._snap_tree.heading(col, text=heading)
            self._snap_tree.column(col, width=width, minwidth=60)
        self._snap_tree.tag_configure("even", background=BG_ROW_EVEN)
        self._snap_tree.tag_configure("odd",  background=BG_ROW_ODD)

        vsb = ttk.Scrollbar(tree_host, orient="vertical", command=self._snap_tree.yview)
        self._snap_tree.configure(yscrollcommand=vsb.set)
        self._snap_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._snap_empty = ctk.CTkLabel(
            table_card,
            text="Create a snapshot to see your installed applications",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._snap_empty.grid(row=1, column=0)
        tree_host.grid_remove()   # hidden until data arrives
        self._snap_tree_host = tree_host

    # =========================================================================
    # Tab 2 — Report
    # =========================================================================

    def _build_report_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # ── Export bar ────────────────────────────────────────────────────────
        export_bar = ctk.CTkFrame(parent, fg_color="transparent")
        export_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))

        ctk.CTkLabel(
            export_bar,
            text="Export:",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(0, 10))

        for label, cmd in [
            ("⬇  JSON Snapshot",  self._export_json),
            ("⬇  CSV Report",     self._export_csv),
            ("⬇  PDF Report",     self._export_html),
        ]:
            ctk.CTkButton(
                export_bar,
                text=label,
                fg_color=BTN_SEC,
                hover_color=BTN_SEC_HVR,
                text_color=TEXT_PRIMARY,
                font=ctk.CTkFont(size=12),
                height=34,
                corner_radius=8,
                command=cmd,
            ).pack(side="left", padx=(0, 8))

        # ── Scrollable report body ────────────────────────────────────────────
        self._report_scroll = ctk.CTkScrollableFrame(
            parent,
            fg_color=BG_CARD,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT,
            corner_radius=12,
        )
        self._report_scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(10, 20))
        self._report_scroll.grid_columnconfigure(0, weight=1)

        self._render_report_placeholder()

    def _render_report_placeholder(self) -> None:
        lbl = ctk.CTkLabel(
            self._report_scroll,
            text="Create a snapshot first to generate a migration report.",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        lbl.grid(row=0, column=0, pady=60)
        self._report_widgets.append(lbl)

    def _rebuild_report(self) -> None:
        for w in self._report_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._report_widgets.clear()

        if not self._snapshot:
            self._render_report_placeholder()
            return

        snap = self._snapshot
        row_idx = 0

        def section(title: str) -> None:
            nonlocal row_idx
            lbl = ctk.CTkLabel(
                self._report_scroll,
                text=title.upper(),
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=TEXT_MUTED,
                anchor="w",
            )
            lbl.grid(row=row_idx, column=0, sticky="ew", padx=16, pady=(20, 2))
            sep = ctk.CTkFrame(self._report_scroll, fg_color=BORDER, height=1)
            sep.grid(row=row_idx + 1, column=0, sticky="ew", padx=16)
            self._report_widgets += [lbl, sep]
            row_idx += 2

        def kv(label: str, value: str, accent: bool = False) -> None:
            nonlocal row_idx
            fr = ctk.CTkFrame(self._report_scroll, fg_color="transparent")
            fr.grid(row=row_idx, column=0, sticky="ew", padx=16, pady=2)
            fr.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                fr, text=label,
                font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
                anchor="w", width=220,
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(
                fr, text=value,
                font=ctk.CTkFont(size=12, weight="bold" if accent else "normal"),
                text_color=ACCENT if accent else TEXT_PRIMARY,
                anchor="w",
            ).grid(row=0, column=1, sticky="w")
            self._report_widgets.append(fr)
            row_idx += 1

        from app.core.migration_assistant import _fmt_size

        section("Summary")
        kv("Report generated",       snap.created_at)
        kv("Source system",          snap.hostname)
        kv("Total plugins",          str(snap.total_plugins),             accent=True)
        kv("Plugin products",        str(snap.plugin_products),           accent=True)
        kv("Music applications",     str(snap.total_apps),                accent=True)
        kv("DAWs",                   str(len(snap.daws)),                 accent=True)
        kv("License managers",       str(len(snap.license_managers)),     accent=True)
        kv("Hardware utilities",     str(len(snap.hardware_utilities)))
        kv("Plugin managers",        str(len(snap.plugin_managers)))

        section("Plugin Formats")
        for fmt, count in sorted(snap.plugin_formats.items()):
            kv(fmt, str(count))

        section("Cleanup Opportunities")
        dup = snap.duplicate_format_products
        savings = _fmt_size(snap.estimated_savings_bytes)
        if dup:
            kv("Duplicate format products", str(dup), accent=True)
            kv("Estimated storage savings", savings,  accent=True)
            kv("Recommendation", "Keep VST3 / AU; remove legacy VST copies")
        else:
            kv("Duplicate formats", "None detected ✓")

        if snap.daws:
            section("DAWs")
            for d in snap.daws:
                kv(d.get("name", ""), d.get("version", "") or "—")

        if snap.license_managers:
            section("License Managers")
            for lm in snap.license_managers:
                kv(lm.get("name", ""), lm.get("developer", "") or "—")

        if snap.hardware_utilities:
            section("Hardware Utilities")
            for hu in snap.hardware_utilities:
                kv(hu.get("name", ""), hu.get("developer", "") or "—")

    # =========================================================================
    # Tab 3 — Compare
    # =========================================================================

    def _build_compare_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))

        ctk.CTkButton(
            toolbar,
            text="⬆  Load Reference Snapshot",
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            corner_radius=8,
            command=self._load_reference_snapshot,
        ).pack(side="left")

        ctk.CTkButton(
            toolbar,
            text="⟳  Run Comparison",
            fg_color=BTN_SEC,
            hover_color=BTN_SEC_HVR,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12),
            height=38,
            corner_radius=8,
            command=self._run_comparison,
        ).pack(side="left", padx=(10, 0))

        self._cmp_ref_lbl = ctk.CTkLabel(
            toolbar,
            text="No reference snapshot loaded",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        )
        self._cmp_ref_lbl.pack(side="left", padx=16)

        # ── Summary badges ────────────────────────────────────────────────────
        badge_row = ctk.CTkFrame(parent, fg_color="transparent")
        badge_row.grid(row=1, column=0, sticky="ew", padx=20, pady=(12, 0))

        self._cmp_cards: dict[str, ctk.CTkLabel] = {}
        for i, (key, label, color) in enumerate([
            ("installed", "Installed",    SUCCESS),
            ("missing",   "Missing",      DANGER),
            ("review",    "Needs Review", WARN),
        ]):
            card = ctk.CTkFrame(badge_row, fg_color=BG_TABLE, corner_radius=10)
            card.grid(row=0, column=i, padx=(0, 10), sticky="ew")
            badge_row.grid_columnconfigure(i, weight=1)

            ctk.CTkLabel(
                card, text=label.upper(),
                font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT_MUTED, anchor="w",
            ).pack(anchor="w", padx=14, pady=(10, 0))

            val = ctk.CTkLabel(
                card, text="—",
                font=ctk.CTkFont(size=26, weight="bold"), text_color=color, anchor="w",
            )
            val.pack(anchor="w", padx=14, pady=(2, 10))
            self._cmp_cards[key] = val

        # ── Results table ─────────────────────────────────────────────────────
        table_card = ctk.CTkFrame(parent, fg_color=BG_TABLE, corner_radius=12)
        table_card.grid(row=2, column=0, sticky="nsew", padx=20, pady=(12, 20))
        table_card.grid_rowconfigure(1, weight=1)
        table_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            table_card, text="COMPARISON RESULTS",
            font=ctk.CTkFont(size=10, weight="bold"), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))

        _apply_tree_style("Cmp.Treeview")

        tree_host = tk.Frame(table_card, bg=BG_TABLE)
        tree_host.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)

        self._cmp_tree = ttk.Treeview(
            tree_host,
            style="Cmp.Treeview",
            columns=("name", "category", "status", "details"),
            show="headings",
        )
        for col, heading, width in [
            ("name",     "Name",               260),
            ("category", "Category / Format",  160),
            ("status",   "Status",             120),
            ("details",  "Details",            200),
        ]:
            self._cmp_tree.heading(col, text=heading)
            self._cmp_tree.column(col, width=width, minwidth=60)

        self._cmp_tree.tag_configure("installed",    foreground=SUCCESS)
        self._cmp_tree.tag_configure("missing",      foreground=DANGER)
        self._cmp_tree.tag_configure("needs_review", foreground=WARN)

        vsb = ttk.Scrollbar(tree_host, orient="vertical", command=self._cmp_tree.yview)
        self._cmp_tree.configure(yscrollcommand=vsb.set)
        self._cmp_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._cmp_empty = ctk.CTkLabel(
            table_card,
            text="Load a reference snapshot and click Run Comparison",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._cmp_empty.grid(row=1, column=0)
        tree_host.grid_remove()
        self._cmp_tree_host = tree_host

    # =========================================================================
    # Tab 4 — Dashboard
    # =========================================================================

    def _build_dashboard_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # ── Info label ────────────────────────────────────────────────────────
        self._dash_info = ctk.CTkLabel(
            parent,
            text="Create a snapshot, load a reference, and run a comparison to see progress.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self._dash_info.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))

        # ── Progress bars card ────────────────────────────────────────────────
        prog_card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
        prog_card.grid(row=1, column=0, sticky="ew", padx=20, pady=(10, 0))
        prog_card.grid_columnconfigure(1, weight=1)

        self._dash_bars: dict[str, ctk.CTkProgressBar] = {}
        self._dash_pcts: dict[str, ctk.CTkLabel] = {}

        for i, (key, label, color) in enumerate([
            ("installed", "Installed",    SUCCESS),
            ("missing",   "Missing",      DANGER),
            ("review",    "Needs Review", WARN),
        ]):
            pad_top = 14 if i == 0 else 6
            pad_bot = 14 if i == 2 else 0

            ctk.CTkLabel(
                prog_card, text=label,
                font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
                width=100, anchor="w",
            ).grid(row=i, column=0, sticky="w", padx=(16, 8),
                   pady=(pad_top, pad_bot))

            bar = ctk.CTkProgressBar(
                prog_card, fg_color=BORDER, progress_color=color,
                height=8, corner_radius=4,
            )
            bar.set(0)
            bar.grid(row=i, column=1, sticky="ew",
                     padx=(0, 8), pady=(pad_top, pad_bot))

            pct = ctk.CTkLabel(
                prog_card, text="0%",
                font=ctk.CTkFont(size=11), text_color=color, width=44, anchor="e",
            )
            pct.grid(row=i, column=2, sticky="e",
                     padx=(0, 16), pady=(pad_top, pad_bot))

            self._dash_bars[key] = bar
            self._dash_pcts[key] = pct

        # ── Full items table ──────────────────────────────────────────────────
        table_card = ctk.CTkFrame(parent, fg_color=BG_TABLE, corner_radius=12)
        table_card.grid(row=2, column=0, sticky="nsew", padx=20, pady=(12, 20))
        table_card.grid_rowconfigure(1, weight=1)
        table_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            table_card, text="ALL ITEMS",
            font=ctk.CTkFont(size=10, weight="bold"), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))

        _apply_tree_style("Dash.Treeview", row_height=28)

        tree_host = tk.Frame(table_card, bg=BG_TABLE)
        tree_host.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)

        self._dash_tree = ttk.Treeview(
            tree_host,
            style="Dash.Treeview",
            columns=("name", "type", "status"),
            show="headings",
        )
        for col, heading, width in [
            ("name",   "Name",           320),
            ("type",   "Type / Format",  160),
            ("status", "Status",         130),
        ]:
            self._dash_tree.heading(col, text=heading)
            self._dash_tree.column(col, width=width, minwidth=60)

        self._dash_tree.tag_configure("installed",    foreground=SUCCESS, background=BG_ROW_EVEN)
        self._dash_tree.tag_configure("missing",      foreground=DANGER,  background=BG_ROW_ODD)
        self._dash_tree.tag_configure("needs_review", foreground=WARN,    background=BG_ROW_EVEN)

        vsb = ttk.Scrollbar(tree_host, orient="vertical", command=self._dash_tree.yview)
        self._dash_tree.configure(yscrollcommand=vsb.set)
        self._dash_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._dash_empty = ctk.CTkLabel(
            table_card,
            text="Run a snapshot and comparison to populate the dashboard",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._dash_empty.grid(row=1, column=0)
        tree_host.grid_remove()
        self._dash_tree_host = tree_host

    # =========================================================================
    # Snapshot scan
    # =========================================================================

    def _run_snapshot_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._snap_btn.configure(state="disabled", text="◈  Scanning…")
        self._snap_status.configure(text="Starting scan…")
        self._snap_bar.set(0)
        self._snap_bar.start()
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self) -> None:
        def upd(msg: str) -> None:
            self.after(0, lambda m=msg: self._snap_status.configure(text=m))

        try:
            upd("Scanning plugins…")
            result = scan_plugins(progress_cb=upd)
            self._current_plugins = result.plugins

            upd("Scanning music applications…")
            self._current_apps = scan_music_apps(progress_cb=upd)

            self._snapshot = create_snapshot(self._current_plugins, self._current_apps)
            self.after(0, self._on_scan_complete)
        except Exception as exc:
            self.after(0, lambda e=exc: self._on_scan_error(str(e)))

    def _on_scan_complete(self) -> None:
        from app.core.migration_assistant import _fmt_size

        self._scanning = False
        self._snap_bar.stop()
        self._snap_bar.set(1)
        self._snap_btn.configure(state="normal", text="◈  Refresh Snapshot")

        snap = self._snapshot
        ts = snap.created_at.replace("T", " ")
        self._snap_status.configure(text=f"Snapshot created · {ts} · {snap.hostname}")

        # Update stat cards
        self._snap_cards["plugins"].configure(text=str(snap.total_plugins))
        self._snap_cards["products"].configure(text=str(snap.plugin_products))
        self._snap_cards["apps"].configure(text=str(snap.total_apps))
        self._snap_cards["daws"].configure(text=str(len(snap.daws)))
        self._snap_cards["lic_mgrs"].configure(text=str(len(snap.license_managers)))
        self._snap_cards["dup_formats"].configure(text=str(snap.duplicate_format_products))
        self._snap_cards["savings"].configure(text=_fmt_size(snap.estimated_savings_bytes))

        # Populate app inventory table
        for row in self._snap_tree.get_children():
            self._snap_tree.delete(row)

        apps = sorted(snap.apps, key=lambda a: (a.get("category", ""), a.get("name", "").lower()))
        for i, app in enumerate(apps):
            self._snap_tree.insert(
                "", "end",
                values=(
                    app.get("name", ""),
                    app.get("category", ""),
                    app.get("developer", ""),
                    app.get("version", ""),
                ),
                tags=("even" if i % 2 == 0 else "odd",),
            )

        if apps:
            self._snap_empty.grid_remove()
            self._snap_tree_host.grid()
        else:
            self._snap_tree_host.grid_remove()
            self._snap_empty.grid()

        # Rebuild report and auto-run comparison if reference is loaded
        self._rebuild_report()
        if self._reference:
            self._run_comparison()

    def _on_scan_error(self, msg: str) -> None:
        self._scanning = False
        self._snap_bar.stop()
        self._snap_bar.set(0)
        self._snap_btn.configure(state="normal", text="◈  Create Studio Snapshot")
        self._snap_status.configure(text=f"Error: {msg}")

    # =========================================================================
    # Load reference snapshot
    # =========================================================================

    def _load_reference_snapshot(self) -> None:
        path = filedialog.askopenfilename(
            title="Load Reference Snapshot (from old Mac)",
            filetypes=[("JSON Snapshot", "*.json"), ("All Files", "*.*")],
            initialdir=str(Path.home() / "Desktop"),
        )
        if not path:
            return
        try:
            self._reference = load_snapshot_json(path)
            name = os.path.basename(path)
            date = self._reference.created_at[:10]
            host = self._reference.hostname
            self._cmp_ref_lbl.configure(
                text=f"Loaded: {name}  ({host} · {date})"
            )
        except Exception as exc:
            messagebox.showerror("Load Error", f"Could not load snapshot:\n{exc}")

    # =========================================================================
    # Comparison
    # =========================================================================

    def _run_comparison(self) -> None:
        if not self._reference:
            messagebox.showinfo(
                "No Reference Snapshot",
                "Load a snapshot from your old Mac first using the Compare tab.",
            )
            return
        if not self._current_plugins and not self._current_apps:
            messagebox.showinfo(
                "No Current Data",
                "Create a snapshot of this system first (Snapshot tab).",
            )
            return

        self._comparison = compare_snapshots(
            self._reference,
            self._current_plugins,
            self._current_apps,
        )
        self._refresh_compare_tab()
        self._refresh_dashboard_tab()

    def _refresh_compare_tab(self) -> None:
        cmp = self._comparison
        if not cmp:
            return

        self._cmp_cards["installed"].configure(text=str(cmp.installed_count))
        self._cmp_cards["missing"].configure(text=str(cmp.missing_count))
        self._cmp_cards["review"].configure(text=str(cmp.review_count))

        for row in self._cmp_tree.get_children():
            self._cmp_tree.delete(row)

        for item in cmp.all_items:
            tag = _TAG_STATUS.get(item.status, "")
            self._cmp_tree.insert(
                "", "end",
                values=(item.name, item.category, item.status, item.details),
                tags=(tag,),
            )

        if cmp.all_items:
            self._cmp_empty.grid_remove()
            self._cmp_tree_host.grid()
        else:
            self._cmp_tree_host.grid_remove()
            self._cmp_empty.grid()

    def _refresh_dashboard_tab(self) -> None:
        cmp = self._comparison
        if not cmp:
            return

        total = len(cmp.all_items)
        if total == 0:
            return

        def pct(n: int) -> float:
            return n / total

        inst_p = pct(cmp.installed_count)
        miss_p = pct(cmp.missing_count)
        rev_p  = pct(cmp.review_count)

        self._dash_bars["installed"].set(inst_p)
        self._dash_bars["missing"].set(miss_p)
        self._dash_bars["review"].set(rev_p)
        self._dash_pcts["installed"].configure(text=f"{inst_p * 100:.0f}%")
        self._dash_pcts["missing"].configure(text=f"{miss_p * 100:.0f}%")
        self._dash_pcts["review"].configure(text=f"{rev_p * 100:.0f}%")

        self._dash_info.configure(
            text=(
                f"Migration progress: {cmp.installed_count}/{total} items restored  ·  "
                f"{cmp.missing_count} missing  ·  {cmp.review_count} needs review"
            )
        )

        for row in self._dash_tree.get_children():
            self._dash_tree.delete(row)

        for item in cmp.all_items:
            tag = _TAG_STATUS.get(item.status, "")
            self._dash_tree.insert(
                "", "end",
                values=(item.name, item.category, item.status),
                tags=(tag,),
            )

        if cmp.all_items:
            self._dash_empty.grid_remove()
            self._dash_tree_host.grid()
        else:
            self._dash_tree_host.grid_remove()
            self._dash_empty.grid()

    # =========================================================================
    # Export actions
    # =========================================================================

    def _export_json(self) -> None:
        if not self._snapshot:
            messagebox.showinfo("No Snapshot", "Create a snapshot first.")
            return
        try:
            path = save_snapshot_json(self._snapshot)
            messagebox.showinfo("Saved", f"JSON snapshot saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _export_csv(self) -> None:
        if not self._snapshot:
            messagebox.showinfo("No Snapshot", "Create a snapshot first.")
            return
        try:
            path = export_migration_csv(self._snapshot)
            messagebox.showinfo("Saved", f"CSV report saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))

    def _export_html(self) -> None:
        if not self._snapshot:
            messagebox.showinfo("No Snapshot", "Create a snapshot first.")
            return
        try:
            path = export_migration_html(self._snapshot)
            try:
                subprocess.Popen(["open", str(path)])
            except Exception:
                pass
            messagebox.showinfo(
                "Report Saved",
                f"HTML report saved to:\n{path}\n\n"
                "It has been opened in your browser.\n"
                "Use File › Print → Save as PDF to export a PDF.",
            )
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))


# ── Shared style helper ───────────────────────────────────────────────────────

def _apply_tree_style(name: str, row_height: int = 32) -> None:
    style = ttk.Style()
    style.configure(
        name,
        background=BG_TABLE,
        foreground=TEXT_PRIMARY,
        rowheight=row_height,
        fieldbackground=BG_TABLE,
        borderwidth=0,
        font=("SF Pro Text", 12),
    )
    style.configure(
        f"{name}.Heading",
        background=BG_MAIN,
        foreground=TEXT_MUTED,
        relief="flat",
        font=("SF Pro Text", 10, "bold"),
        borderwidth=0,
    )
    style.map(name, background=[("selected", "#1B2848")])
    style.layout(name, [(f"{name}.treearea", {"sticky": "nsew"})])
