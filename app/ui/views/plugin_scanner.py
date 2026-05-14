"""
Plug-in Scanner view — scan, browse, search, and export audio plug-ins.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from app.core.scanner import Plugin, ScanResult, scan_plugins
from app.core.exporter import export_csv
from app.utils.helpers import humanize_count

# ── Palette ───────────────────────────────────────────────────────────────────
BG_CARD = "#13161F"
BG_TABLE = "#0D0F18"
BG_TABLE_ROW = "#13161F"
BG_TABLE_ROW_ALT = "#161924"
BG_TABLE_SEL = "#1E2A4A"
ACCENT = "#6C8EF5"
ACCENT_HOVER = "#8BAAF7"
ACCENT_DANGER = "#F56C6C"
TEXT_PRIMARY = "#E8EAF0"
TEXT_MUTED = "#6B7280"
BORDER = "#1C1F2E"
FMT_COLORS: dict[str, str] = {
    "VST":  "#F5A623",
    "VST3": "#7ED321",
    "AU":   "#4A90E2",
    "AAX":  "#BD10E0",
}


class PluginScannerView(ctk.CTkFrame):
    """Main content frame for the Plug-in Scanner module."""

    def __init__(self, parent: ctk.CTkFrame, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._all_plugins: list[Plugin] = []
        self._filtered: list[Plugin] = []
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
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 0))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Plug-in Scanner",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Detect VST / VST3 / AU / AAX plug-ins installed on this Mac",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=28, pady=(20, 12))
        bar.grid_columnconfigure(1, weight=1)

        # Scan button
        self._scan_btn = ctk.CTkButton(
            bar,
            text="  ◈  Scan Plugins",
            width=160,
            height=40,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._start_scan,
        )
        self._scan_btn.grid(row=0, column=0, sticky="w")

        # Search box
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)

        search_frame = ctk.CTkFrame(bar, fg_color=BG_CARD, corner_radius=8)
        search_frame.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        search_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            search_frame,
            text="⌕",
            font=ctk.CTkFont(size=16),
            text_color=TEXT_MUTED,
            width=30,
        ).grid(row=0, column=0, padx=(10, 0))

        self._search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self._search_var,
            placeholder_text="Search by name, format, or path…",
            fg_color="transparent",
            border_width=0,
            text_color=TEXT_PRIMARY,
            placeholder_text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=13),
            height=40,
        )
        self._search_entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))

        # Export button
        self._export_btn = ctk.CTkButton(
            bar,
            text="↓  Export CSV",
            width=130,
            height=40,
            corner_radius=8,
            font=ctk.CTkFont(size=13),
            fg_color=BG_CARD,
            hover_color="#1C1F2E",
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._export_csv,
            state="disabled",
        )
        self._export_btn.grid(row=0, column=2, sticky="e", padx=(12, 0))

    def _build_table(self) -> None:
        container = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=12)
        container.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 0))
        container.grid_rowconfigure(2, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # Divider below (invisible) header row
        ctk.CTkFrame(container, height=1, fg_color=BORDER).grid(
            row=1, column=0, sticky="ew", padx=16, pady=(12, 0)
        )

        # Treeview inside a plain tk Frame (needed for scrollbar pairing)
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
            rowheight=34,
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

        # Columns: name · developer · version · fmt · size · modified · path
        self._tree = ttk.Treeview(
            tree_frame,
            columns=("name", "developer", "version", "fmt", "size", "modified", "path"),
            show="headings",
            style="Vault.Treeview",
            selectmode="extended",
        )
        col_cfg = [
            ("name",      "NAME",       200, True,  "w"),
            ("developer", "DEVELOPER",  160, True,  "w"),
            ("version",   "VERSION",     80, False, "center"),
            ("fmt",       "FORMAT",      70, False, "center"),
            ("size",      "SIZE",        75, False, "e"),
            ("modified",  "MODIFIED",    95, False, "center"),
            ("path",      "PATH",       340, True,  "w"),
        ]
        for col_id, heading, width, stretch, anchor in col_cfg:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=50, stretch=stretch, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Alternate row colours + format colour tags
        self._tree.tag_configure("even", background=BG_TABLE_ROW)
        self._tree.tag_configure("odd", background=BG_TABLE_ROW_ALT)
        for fmt, color in FMT_COLORS.items():
            self._tree.tag_configure(f"fmt_{fmt}", foreground=color)

        # Empty-state overlay
        self._empty_label = ctk.CTkLabel(
            container,
            text="Press  ◈ Scan Plugins  to discover audio plug-ins on this Mac",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=2, column=0)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=3, column=0, sticky="ew", padx=28, pady=(8, 20))
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

    def _populate_table(self, plugins: list[Plugin]) -> None:
        self._clear_table()
        for i, p in enumerate(plugins):
            tags = ["even" if i % 2 == 0 else "odd", f"fmt_{p.fmt}"]
            self._tree.insert("", "end", values=p.row, tags=tags)

        if plugins:
            self._empty_label.grid_remove()
        else:
            self._empty_label.configure(text="No results match your search.")
            self._empty_label.grid()

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
