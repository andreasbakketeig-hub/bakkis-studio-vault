"""
Plug-in Scanner view — scan, browse, search, and export audio plug-ins.
"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk

from app.core.scanner import Plugin, ScanResult, scan_plugins
from app.core.exporter import export_csv
from app.ui.tree_columns import (
    FixedColumn,
    FlexColumn,
    TreeColumnLayout,
    bind_responsive_tree_columns,
    truncate_for_column,
)
from app.utils.helpers import humanize_count

# ── Design System ─────────────────────────────────────────────────────────────
BG_CARD          = "#131720"
BG_TABLE         = "#0D1020"
BG_TABLE_ROW     = "#131720"
BG_TABLE_ROW_ALT = "#161B28"
BG_TABLE_SEL     = "#1B2848"
BG_SEARCH        = "#161B28"
ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
ACCENT_DIM       = "#1A2545"
ACCENT_DANGER    = "#F87171"
TEXT_PRIMARY     = "#EEF0F8"
TEXT_SECONDARY   = "#94A3B8"
TEXT_MUTED       = "#4B5870"
BORDER           = "#1C2038"
BORDER_BRIGHT    = "#242B48"

FMT_COLORS: dict[str, str] = {
    "VST":  "#F59E0B",
    "VST3": "#4ADE80",
    "AU":   "#60A5FA",
    "AAX":  "#A855F7",
}

_SCANNER_COLUMNS = TreeColumnLayout(
    fixed=(
        FixedColumn("developer", 120, "w"),
        FixedColumn("version", 68, "center"),
        FixedColumn("fmt", 56, "center"),
        FixedColumn("size", 68, "e"),
        FixedColumn("modified", 84, "center"),
    ),
    flex=(
        FlexColumn("name", weight=1.0, min_width=120, anchor="w"),
        FlexColumn("path", weight=2.0, min_width=160, anchor="w"),
    ),
)


class PluginScannerView(ctk.CTkFrame):
    """Main content frame for the Plug-in Scanner module."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_plugins_ready: Optional[Callable[[list[Plugin]], None]] = None,
        db=None,
        last_scanned: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._on_plugins_ready = on_plugins_ready
        self._all_plugins: list[Plugin] = []
        self._filtered: list[Plugin] = []
        self._iid_to_plugin: dict[str, Plugin] = {}
        self._scan_result: Optional[ScanResult] = None
        self._scanning = False

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_table()
        self._build_statusbar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(28, 0))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Plug-in Scanner",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Detect VST  ·  VST3  ·  AU  ·  AAX plug-ins installed on this Mac",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        # Format badges
        badge_row = ctk.CTkFrame(header, fg_color="transparent")
        badge_row.grid(row=0, column=1, rowspan=2, sticky="e")
        for fmt, color in FMT_COLORS.items():
            badge = ctk.CTkFrame(badge_row, fg_color=BORDER_BRIGHT, corner_radius=6)
            badge.pack(side="right", padx=(4, 0))
            ctk.CTkLabel(
                badge, text=fmt,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=color,
            ).pack(padx=10, pady=4)

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=30, pady=(18, 12))
        bar.grid_columnconfigure(1, weight=1)

        self._scan_btn = ctk.CTkButton(
            bar,
            text="  ◈  Scan Plugins",
            width=155,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._start_scan,
        )
        self._scan_btn.grid(row=0, column=0, sticky="w")

        search_frame = ctk.CTkFrame(bar, fg_color=BG_SEARCH, corner_radius=9,
                                    border_width=1, border_color=BORDER)
        search_frame.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        search_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            search_frame,
            text="⌕",
            font=ctk.CTkFont(size=16),
            text_color=TEXT_MUTED,
            width=30,
        ).grid(row=0, column=0, padx=(10, 0))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        self._search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self._search_var,
            placeholder_text="Search by name, format, developer, or path…",
            fg_color="transparent",
            border_width=0,
            text_color=TEXT_PRIMARY,
            placeholder_text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            height=40,
        )
        self._search_entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))

        self._export_btn = ctk.CTkButton(
            bar,
            text="↓  Export CSV",
            width=130,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._export_csv,
            state="disabled",
        )
        self._export_btn.grid(row=0, column=2, sticky="e", padx=(10, 0))

        self._reveal_btn = ctk.CTkButton(
            bar,
            text="⌘  Reveal in Finder",
            width=155,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._reveal_in_finder,
            state="disabled",
        )
        self._reveal_btn.grid(row=0, column=3, sticky="e", padx=(8, 0))

    def _build_table(self) -> None:
        self._table_container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        self._table_container.grid(row=2, column=0, sticky="nsew", padx=30, pady=(0, 0))
        self._table_container.grid_rowconfigure(2, weight=1)
        self._table_container.grid_columnconfigure(0, weight=1)
        container = self._table_container

        ctk.CTkFrame(container, height=1, fg_color=BORDER).grid(
            row=1, column=0, sticky="ew", padx=16, pady=(12, 0),
        )

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Vault.Treeview",
            background=BG_TABLE,
            foreground=TEXT_PRIMARY,
            fieldbackground=BG_TABLE,
            rowheight=36,
            borderwidth=0,
            font=("SF Pro Text", 12),
        )
        style.configure(
            "Vault.Treeview.Heading",
            background=BG_TABLE,
            foreground=TEXT_MUTED,
            font=("SF Pro Text", 10),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Vault.Treeview",
            background=[("selected", BG_TABLE_SEL)],
            foreground=[("selected", TEXT_PRIMARY)],
        )
        style.layout("Vault.Treeview", [("Vault.Treeview.treearea", {"sticky": "nswe"})])

        self._tree = ttk.Treeview(
            tree_frame,
            columns=("name", "developer", "version", "fmt", "size", "modified", "path"),
            show="headings",
            style="Vault.Treeview",
            selectmode="extended",
        )
        for col_id, heading in (
            ("name", "NAME"),
            ("developer", "DEVELOPER"),
            ("version", "VERSION"),
            ("fmt", "FORMAT"),
            ("size", "SIZE"),
            ("modified", "MODIFIED"),
            ("path", "PATH"),
        ):
            self._tree.heading(col_id, text=heading)

        self._tree_frame = tree_frame

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("even", background=BG_TABLE_ROW)
        self._tree.tag_configure("odd",  background=BG_TABLE_ROW_ALT)
        for fmt, color in FMT_COLORS.items():
            self._tree.tag_configure(f"fmt_{fmt}", foreground=color)

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self._relayout_tree_columns = bind_responsive_tree_columns(
            self._tree,
            tree_frame,
            _SCANNER_COLUMNS,
            on_layout=lambda _w: self._refresh_path_cells(),
            extra_hosts=(container, self),
        )

        self._empty_label = ctk.CTkLabel(
            container,
            text="Press  ◈ Scan Plugins  to discover audio plug-ins on this Mac",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=2, column=0)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=3, column=0, sticky="ew", padx=30, pady=(8, 22))
        bar.grid_columnconfigure(0, weight=1)

        self._status_var = tk.StringVar(value="Ready")
        self._status_label = ctk.CTkLabel(
            bar,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self._status_label.grid(row=0, column=0, sticky="w")

        self._count_label = ctk.CTkLabel(
            bar,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="e",
        )
        self._count_label.grid(row=0, column=1, sticky="e")

    # ── Scanning ──────────────────────────────────────────────────────────────

    def _start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.configure(state="disabled", text="  ◈  Scanning…")
        self._clear_table()
        self._empty_label.grid_remove()
        self._status_var.set("Starting scan…")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        result = scan_plugins(progress_cb=self._on_progress)
        self.after(0, self._on_scan_complete, result)

    def _on_progress(self, msg: str) -> None:
        self.after(0, self._status_var.set, msg)

    def _on_scan_complete(self, result: ScanResult) -> None:
        self._scan_result = result
        self._all_plugins = result.plugins
        self._scanning = False
        self._scan_btn.configure(state="normal", text="  ◈  Scan Plugins")

        if self._on_plugins_ready:
            self._on_plugins_ready(self._all_plugins)

        if self._all_plugins:
            self._export_btn.configure(state="normal", text_color=TEXT_PRIMARY)
            self._apply_filter(self._search_var.get())
        else:
            self._empty_label.configure(text="No plug-ins found in the standard locations.")
            self._empty_label.grid()

        count_text = humanize_count(len(self._all_plugins), "plug-in")
        if result.errors:
            count_text += f"  ·  {len(result.errors)} permission error(s)"
        self._count_label.configure(text=count_text)

    # ── Table population ──────────────────────────────────────────────────────

    def _clear_table(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._iid_to_plugin.clear()
        self._reveal_btn.configure(state="disabled", text_color=TEXT_MUTED)

    def _plugin_row_values(self, plugin: Plugin) -> tuple[str, ...]:
        path_w = int(self._tree.column("path", "width") or 180)
        return (
            plugin.name,
            plugin.developer,
            plugin.version,
            plugin.fmt,
            plugin.file_size_human,
            plugin.modified,
            truncate_for_column(plugin.path, path_w),
        )

    def _refresh_path_cells(self) -> None:
        if not self._iid_to_plugin:
            return
        path_w = int(self._tree.column("path", "width") or 180)
        for iid, plugin in self._iid_to_plugin.items():
            values = list(self._tree.item(iid, "values"))
            if len(values) >= 7:
                values[6] = truncate_for_column(plugin.path, path_w)
                self._tree.item(iid, values=values)

    def _populate_table(self, plugins: list[Plugin]) -> None:
        self._clear_table()
        for i, p in enumerate(plugins):
            tags = ["even" if i % 2 == 0 else "odd", f"fmt_{p.fmt}"]
            iid = self._tree.insert("", "end", values=self._plugin_row_values(p), tags=tags)
            self._iid_to_plugin[iid] = p

        if plugins:
            self._empty_label.grid_remove()
        else:
            self._empty_label.configure(text="No results match your search.")
            self._empty_label.grid()

        if hasattr(self, "_relayout_tree_columns"):
            self.after_idle(self._relayout_tree_columns)

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_search(self, *_) -> None:
        self._apply_filter(self._search_var.get())

    def _apply_filter(self, query: str) -> None:
        q = query.strip().lower()
        if not q:
            self._filtered = list(self._all_plugins)
        else:
            self._filtered = [
                p for p in self._all_plugins
                if q in p.name.lower()
                or q in p.fmt.lower()
                or q in p.path.lower()
                or q in p.developer.lower()
                or q in p.version.lower()
                or q in p.modified.lower()
            ]
        self._populate_table(self._filtered)
        displayed = humanize_count(len(self._filtered), "plug-in")
        total = len(self._all_plugins)
        suffix = f" of {total:,}" if q and len(self._filtered) != total else ""
        self._count_label.configure(text=f"{displayed}{suffix}")

    # ── Reveal in Finder ──────────────────────────────────────────────────────

    def _on_tree_select(self, _event=None) -> None:
        has_selection = bool(self._tree.selection())
        state = "normal" if has_selection else "disabled"
        color = TEXT_PRIMARY if has_selection else TEXT_MUTED
        self._reveal_btn.configure(state=state, text_color=color)

    def _reveal_in_finder(self) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        plugin = self._iid_to_plugin.get(selected[0])
        path = plugin.path if plugin else self._tree.item(selected[0], "values")[6]
        if path:
            subprocess.run(["open", "-R", path], check=False)

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_csv(self) -> None:
        plugins = self._filtered if self._filtered else self._all_plugins
        if not plugins:
            messagebox.showinfo("Export", "Nothing to export yet. Run a scan first.")
            return
        try:
            dest = export_csv(plugins)
            messagebox.showinfo("Export complete", f"Saved to:\n{dest}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
