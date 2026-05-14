"""
Music Software Scanner view — scan and browse music applications on macOS.
"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

import customtkinter as ctk

from app.core.music_software_scanner import (
    CATEGORY_DAW,
    CATEGORY_DJ,
    CATEGORY_HARDWARE_UTILITY,
    CATEGORY_LICENSE_MANAGER,
    CATEGORY_PLUGIN_MANAGER,
    CATEGORY_SAMPLE_MANAGER,
    CATEGORY_AUDIO_UTILITY,
    MusicApp,
    scan_music_apps,
)

# ── Design System ─────────────────────────────────────────────────────────────
BG_CARD          = "#131720"
BG_CARD_INNER    = "#181D2C"
BG_TABLE         = "#0D1020"
BG_TABLE_ROW     = "#131720"
BG_TABLE_ROW_ALT = "#161B28"
BG_TABLE_SEL     = "#1B2848"
ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
TEXT_PRIMARY     = "#EEF0F8"
TEXT_SECONDARY   = "#94A3B8"
TEXT_MUTED       = "#4B5870"
BORDER           = "#1C2038"
BORDER_BRIGHT    = "#242B48"

CAT_COLORS: dict[str, str] = {
    CATEGORY_DAW:              "#4ADE80",
    CATEGORY_DJ:               "#F59E0B",
    CATEGORY_PLUGIN_MANAGER:   "#6C8EF5",
    CATEGORY_LICENSE_MANAGER:  "#A855F7",
    CATEGORY_SAMPLE_MANAGER:   "#60A5FA",
    CATEGORY_AUDIO_UTILITY:    "#2DD4BF",
    CATEGORY_HARDWARE_UTILITY: "#F59E0B",
}

CAT_DIM: dict[str, str] = {
    CATEGORY_DAW:              "#183A28",
    CATEGORY_DJ:               "#2A1E08",
    CATEGORY_PLUGIN_MANAGER:   "#1A2545",
    CATEGORY_LICENSE_MANAGER:  "#21133A",
    CATEGORY_SAMPLE_MANAGER:   "#122038",
    CATEGORY_AUDIO_UTILITY:    "#0E2A28",
    CATEGORY_HARDWARE_UTILITY: "#2A1E08",
}

_CARDS = [
    ("total",    "Total Music Apps",          ACCENT,    "#1A2545", "◈"),
    ("daws",     "DAWs",                      "#4ADE80", "#183A28", "♩"),
    ("managers", "License & Plugin Managers", "#A855F7", "#21133A", "⬡"),
    ("hardware", "Hardware Utilities",        "#F59E0B", "#2A1E08", "⬢"),
]


class MusicSoftwareScannerView(ctk.CTkFrame):
    """Content frame for the Music Software Scanner module."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_apps_ready: Callable[[list[MusicApp]], None] | None = None,
        db=None,
        last_scanned: str | None = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._all_apps: list[MusicApp] = []
        self._filtered: list[MusicApp] = []
        self._scanning = False
        self._on_apps_ready = on_apps_ready

        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_summary_cards()
        self._build_table()
        self._build_statusbar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Music Software Scanner",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Detect DAWs, DJ software, plugin managers, and hardware utilities on this Mac",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(3, 0))

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=30, pady=(18, 10))
        bar.grid_columnconfigure(1, weight=1)

        self._scan_btn = ctk.CTkButton(
            bar,
            text="  ♬  Scan Apps",
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

        search_frame = ctk.CTkFrame(
            bar, fg_color=BG_CARD, corner_radius=9,
            border_width=1, border_color=BORDER,
        )
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
            placeholder_text="Search by name, category, developer, or path…",
            fg_color="transparent",
            border_width=0,
            text_color=TEXT_PRIMARY,
            placeholder_text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            height=40,
        )
        self._search_entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))

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
        self._reveal_btn.grid(row=0, column=2, sticky="e", padx=(10, 0))

    def _build_summary_cards(self) -> None:
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.grid(row=2, column=0, sticky="ew", padx=30, pady=(4, 14))
        for i in range(len(_CARDS)):
            cards_row.grid_columnconfigure(i, weight=1)

        self._card_labels: dict[str, ctk.CTkLabel] = {}
        for col, (key, title, color, dim, icon) in enumerate(_CARDS):
            padx = (0, 10) if col < len(_CARDS) - 1 else (0, 0)
            card = ctk.CTkFrame(
                cards_row, fg_color=BG_CARD, corner_radius=12,
                border_width=1, border_color=BORDER,
            )
            card.grid(row=0, column=col, sticky="ew", padx=padx)
            card.grid_columnconfigure(1, weight=1)

            icon_box = ctk.CTkFrame(card, width=38, height=38, corner_radius=9, fg_color=dim)
            icon_box.grid(row=0, column=0, rowspan=2, padx=(14, 0), pady=14)
            icon_box.grid_propagate(False)
            ctk.CTkLabel(
                icon_box, text=icon,
                font=ctk.CTkFont(size=15), text_color=color,
            ).place(relx=0.5, rely=0.5, anchor="center")

            ctk.CTkLabel(
                card, text=title.upper(),
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=TEXT_MUTED, anchor="w",
            ).grid(row=0, column=1, sticky="sw", padx=(12, 14), pady=(14, 0))

            count_lbl = ctk.CTkLabel(
                card, text="—",
                font=ctk.CTkFont(size=26, weight="bold"),
                text_color=color, anchor="w",
            )
            count_lbl.grid(row=1, column=1, sticky="nw", padx=(12, 14), pady=(0, 14))
            self._card_labels[key] = count_lbl

    def _build_table(self) -> None:
        container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        container.grid(row=3, column=0, sticky="nsew", padx=30)
        container.grid_rowconfigure(2, weight=1)
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(container, height=1, fg_color=BORDER).grid(
            row=1, column=0, sticky="ew", padx=16, pady=(12, 0),
        )

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Music.Treeview",
            background=BG_TABLE,
            foreground=TEXT_PRIMARY,
            fieldbackground=BG_TABLE,
            rowheight=36,
            borderwidth=0,
            font=("SF Pro Text", 12),
        )
        style.configure(
            "Music.Treeview.Heading",
            background=BG_TABLE,
            foreground=TEXT_MUTED,
            font=("SF Pro Text", 10),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Music.Treeview",
            background=[("selected", BG_TABLE_SEL)],
            foreground=[("selected", TEXT_PRIMARY)],
        )
        style.layout("Music.Treeview", [("Music.Treeview.treearea", {"sticky": "nswe"})])

        self._tree = ttk.Treeview(
            tree_frame,
            columns=("name", "category", "developer", "version", "path", "modified"),
            show="headings",
            style="Music.Treeview",
            selectmode="browse",
        )
        col_cfg = [
            ("name",      "NAME",       200, True,  "w"),
            ("category",  "CATEGORY",   140, False, "w"),
            ("developer", "DEVELOPER",  160, True,  "w"),
            ("version",   "VERSION",     80, False, "center"),
            ("path",      "PATH",       340, True,  "w"),
            ("modified",  "MODIFIED",    95, False, "center"),
        ]
        for col_id, heading, width, stretch, anchor in col_cfg:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=50, stretch=stretch, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("even", background=BG_TABLE_ROW)
        self._tree.tag_configure("odd",  background=BG_TABLE_ROW_ALT)
        for cat, color in CAT_COLORS.items():
            self._tree.tag_configure(f"cat_{cat.replace(' ', '_')}", foreground=color)

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self._empty_label = ctk.CTkLabel(
            container,
            text="Press  ♬ Scan Apps  to discover music software on this Mac",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=2, column=0)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=4, column=0, sticky="ew", padx=30, pady=(8, 22))
        bar.grid_columnconfigure(0, weight=1)

        self._status_var = tk.StringVar(value="Ready")
        ctk.CTkLabel(
            bar,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self._count_label = ctk.CTkLabel(
            bar, text="",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="e",
        )
        self._count_label.grid(row=0, column=1, sticky="e")

    # ── Scanning ──────────────────────────────────────────────────────────────

    def _start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.configure(state="disabled", text="  ♬  Scanning…")
        self._clear_table()
        self._empty_label.grid_remove()
        self._status_var.set("Starting scan…")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        apps = scan_music_apps(progress_cb=self._on_progress)
        self.after(0, self._on_scan_complete, apps)

    def _on_progress(self, msg: str) -> None:
        self.after(0, self._status_var.set, msg)

    def _on_scan_complete(self, apps: list[MusicApp]) -> None:
        self._all_apps = apps
        self._scanning = False
        self._scan_btn.configure(state="normal", text="  ♬  Scan Apps")
        self._update_cards(apps)
        if self._on_apps_ready is not None:
            self._on_apps_ready(apps)

        if apps:
            self._apply_filter(self._search_var.get())
        else:
            self._empty_label.configure(
                text="No music software found in /Applications or ~/Applications."
            )
            self._empty_label.grid()

        n = len(apps)
        self._count_label.configure(text=f"{n:,} {'app' if n == 1 else 'apps'}")

    def _update_cards(self, apps: list[MusicApp]) -> None:
        total    = len(apps)
        daws     = sum(1 for a in apps if a.category == CATEGORY_DAW)
        managers = sum(
            1 for a in apps
            if a.category in (CATEGORY_PLUGIN_MANAGER, CATEGORY_LICENSE_MANAGER)
        )
        hardware = sum(1 for a in apps if a.category == CATEGORY_HARDWARE_UTILITY)

        self._card_labels["total"].configure(text=str(total))
        self._card_labels["daws"].configure(text=str(daws))
        self._card_labels["managers"].configure(text=str(managers))
        self._card_labels["hardware"].configure(text=str(hardware))

    def _clear_table(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)
        self._reveal_btn.configure(state="disabled", text_color=TEXT_MUTED)

    def _populate_table(self, apps: list[MusicApp]) -> None:
        self._clear_table()
        for i, app in enumerate(apps):
            row_tag = "even" if i % 2 == 0 else "odd"
            cat_tag = f"cat_{app.category.replace(' ', '_')}"
            self._tree.insert("", "end", values=app.row, tags=(row_tag, cat_tag))

        if apps:
            self._empty_label.grid_remove()
        else:
            self._empty_label.configure(text="No results match your search.")
            self._empty_label.grid()

    def _on_search(self, *_) -> None:
        self._apply_filter(self._search_var.get())

    def _apply_filter(self, query: str) -> None:
        q = query.strip().lower()
        if not q:
            self._filtered = list(self._all_apps)
        else:
            self._filtered = [
                a for a in self._all_apps
                if q in a.name.lower()
                or q in a.category.lower()
                or q in a.developer.lower()
                or q in a.version.lower()
                or q in a.path.lower()
                or q in a.modified.lower()
            ]
        self._populate_table(self._filtered)
        displayed = len(self._filtered)
        total = len(self._all_apps)
        suffix = "app" if displayed == 1 else "apps"
        extra = f" of {total:,}" if q and displayed != total else ""
        self._count_label.configure(text=f"{displayed:,} {suffix}{extra}")

    def _on_tree_select(self, _event=None) -> None:
        has_sel = bool(self._tree.selection())
        self._reveal_btn.configure(
            state="normal" if has_sel else "disabled",
            text_color=TEXT_PRIMARY if has_sel else TEXT_MUTED,
        )

    def _reveal_in_finder(self) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        path = self._tree.item(selected[0], "values")[4]
        if path:
            subprocess.run(["open", "-R", path], check=False)
