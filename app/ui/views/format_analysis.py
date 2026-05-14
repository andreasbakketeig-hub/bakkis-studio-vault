"""
Format Analysis view — groups scanned plug-ins by product name and
highlights plugins installed in multiple formats (VST / VST3 / AU / AAX).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from app.core.scanner import FormatGroup, Plugin, analyze_formats

# ── Palette ───────────────────────────────────────────────────────────────────
BG_CARD = "#13161F"
BG_TABLE = "#0D0F18"
BG_TABLE_ROW = "#13161F"
BG_TABLE_ROW_ALT = "#161924"
BG_TABLE_ROW_DUP = "#1C1630"
BG_TABLE_ROW_DUP_ALT = "#1F1934"
BG_TABLE_SEL = "#1E2A4A"
ACCENT = "#6C8EF5"
ACCENT_WARN = "#F5A623"
ACCENT_GREEN = "#7ED321"
TEXT_PRIMARY = "#E8EAF0"
TEXT_MUTED = "#6B7280"
BORDER = "#1C1F2E"
FMT_COLORS: dict[str, str] = {
    "VST":  "#F5A623",
    "VST3": "#7ED321",
    "AU":   "#4A90E2",
    "AAX":  "#BD10E0",
}


class FormatAnalysisView(ctk.CTkFrame):
    """Shows plug-ins grouped by product name with format-overlap analysis."""

    def __init__(self, parent: ctk.CTkFrame, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._groups: list[FormatGroup] = []
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_stats_row()
        self._build_table()
        self._build_statusbar()
        self._show_empty_state(initial=True)

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Format Analysis",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Detect plug-ins installed in multiple formats — VST · VST3 · AU · AAX",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _build_stats_row(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=28, pady=(20, 0))
        row.grid_columnconfigure(0, weight=1, uniform="stat")
        row.grid_columnconfigure(1, weight=1, uniform="stat")
        row.grid_columnconfigure(2, weight=1, uniform="stat")

        self._stat_dupes    = self._make_stat_card(row, 0, "DUPLICATE PLUGINS",      "—", ACCENT_WARN)
        self._stat_redundant = self._make_stat_card(row, 1, "REDUNDANT FORMATS",      "—", ACCENT)
        self._stat_space    = self._make_stat_card(row, 2, "EST. RECOVERABLE SPACE",  "—", ACCENT_GREEN)

    def _make_stat_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        label: str,
        initial_value: str,
        value_color: str,
    ) -> ctk.CTkLabel:
        pad_right = (0, 12) if col < 2 else (0, 0)
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        card.grid(row=0, column=col, sticky="ew", padx=pad_right)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=label,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))

        value_lbl = ctk.CTkLabel(
            card,
            text=initial_value,
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=value_color,
            anchor="w",
        )
        value_lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))
        return value_lbl

    def _build_table(self) -> None:
        container = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=12)
        container.grid(row=3, column=0, sticky="nsew", padx=28, pady=(16, 0))
        container.grid_rowconfigure(2, weight=1)
        container.grid_columnconfigure(0, weight=1)

        # Legend
        legend = ctk.CTkFrame(container, fg_color="transparent")
        legend.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))

        ctk.CTkLabel(
            legend,
            text="⬥  Multiple formats installed",
            font=ctk.CTkFont(size=10),
            text_color=ACCENT_WARN,
        ).pack(side="left")

        ctk.CTkLabel(
            legend,
            text="    Single format",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
        ).pack(side="left")

        # Format key badges
        for fmt, color in FMT_COLORS.items():
            ctk.CTkLabel(
                legend,
                text=f"  {fmt}",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=color,
            ).pack(side="right")

        # Divider
        ctk.CTkFrame(container, height=1, fg_color=BORDER).grid(
            row=1, column=0, sticky="ew", padx=16, pady=(8, 0)
        )

        # Treeview
        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure(
            "Analysis.Treeview",
            background=BG_TABLE,
            foreground=TEXT_PRIMARY,
            fieldbackground=BG_TABLE,
            rowheight=36,
            borderwidth=0,
            font=("SF Pro Text", 12),
        )
        style.configure(
            "Analysis.Treeview.Heading",
            background=BG_TABLE,
            foreground=TEXT_MUTED,
            font=("SF Pro Text", 10),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Analysis.Treeview",
            background=[("selected", BG_TABLE_SEL)],
            foreground=[("selected", TEXT_PRIMARY)],
        )
        style.layout("Analysis.Treeview", [("Analysis.Treeview.treearea", {"sticky": "nswe"})])

        columns = ("name", "developer", "formats", "count", "total_size", "redundant")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            style="Analysis.Treeview",
            selectmode="browse",
        )
        col_cfg = [
            ("name",      "PRODUCT NAME",        220, True,  "w"),
            ("developer", "DEVELOPER",            160, True,  "w"),
            ("formats",   "FORMATS INSTALLED",    200, True,  "w"),
            ("count",     "COPIES",                60, False, "center"),
            ("total_size","TOTAL SIZE",             90, False, "e"),
            ("redundant", "REDUNDANT",              90, False, "e"),
        ]
        for col_id, heading, width, stretch, anchor in col_cfg:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=50, stretch=stretch, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # Row tags: duplicates get a distinct background + warning foreground
        self._tree.tag_configure("dup_even",    background=BG_TABLE_ROW_DUP,     foreground=ACCENT_WARN)
        self._tree.tag_configure("dup_odd",     background=BG_TABLE_ROW_DUP_ALT, foreground=ACCENT_WARN)
        self._tree.tag_configure("single_even", background=BG_TABLE_ROW,         foreground=TEXT_PRIMARY)
        self._tree.tag_configure("single_odd",  background=BG_TABLE_ROW_ALT,     foreground=TEXT_PRIMARY)

        # Empty-state overlay (shown until data is loaded)
        self._empty_label = ctk.CTkLabel(
            container,
            text="",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=2, column=0)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=4, column=0, sticky="ew", padx=28, pady=(8, 20))
        bar.grid_columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(
            bar,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self._status_label.grid(row=0, column=0, sticky="w")

        self._total_label = ctk.CTkLabel(
            bar,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="e",
        )
        self._total_label.grid(row=0, column=1, sticky="e")

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self, plugins: list[Plugin]) -> None:
        """Recompute and render format groups from *plugins*."""
        if not plugins:
            self._show_empty_state(initial=False)
            return

        self._groups = analyze_formats(plugins)
        self._populate()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _show_empty_state(self, initial: bool) -> None:
        msg = (
            "Run a scan in  ◈ Plug-in Scanner  to populate format analysis."
            if initial
            else "No plug-ins found — try scanning again."
        )
        self._empty_label.configure(text=msg)
        self._empty_label.grid()
        self._reset_stats()

    def _reset_stats(self) -> None:
        self._stat_dupes.configure(text="—")
        self._stat_redundant.configure(text="—")
        self._stat_space.configure(text="—")
        self._status_label.configure(text="")
        self._total_label.configure(text="")

    def _populate(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)

        duplicates = [g for g in self._groups if g.is_duplicate]
        total_redundant_formats = sum(len(g.formats) - 1 for g in duplicates)
        total_recoverable = sum(g.redundant_size for g in duplicates)

        dup_i = single_i = 0

        for g in self._groups:
            fmt_str = "  ·  ".join(g.format_names)
            values = (
                g.product_name,
                g.developer or "—",
                fmt_str,
                str(len(g.formats)),
                _fmt_size(g.total_size),
                _fmt_size(g.redundant_size) if g.redundant_size else "—",
            )

            if g.is_duplicate:
                tag = "dup_even" if dup_i % 2 == 0 else "dup_odd"
                dup_i += 1
            else:
                tag = "single_even" if single_i % 2 == 0 else "single_odd"
                single_i += 1

            self._tree.insert("", "end", values=values, tags=(tag,))

        if self._groups:
            self._empty_label.grid_remove()
        else:
            self._empty_label.configure(text="No plug-in groups to display.")
            self._empty_label.grid()

        # Update stat cards
        self._stat_dupes.configure(text=str(len(duplicates)) if duplicates else "0")
        self._stat_redundant.configure(text=str(total_redundant_formats) if duplicates else "0")
        self._stat_space.configure(
            text=_fmt_size(total_recoverable) if total_recoverable else "0 B"
        )

        # Status bar
        total_products = len(self._groups)
        pct = f"{100 * len(duplicates) / total_products:.0f}%" if total_products else "0%"
        self._status_label.configure(
            text=f"{len(duplicates):,} of {total_products:,} products have multiple formats  ({pct})"
        )
        self._total_label.configure(
            text=f"{sum(len(g.formats) for g in self._groups):,} total format copies scanned"
        )


# ── Utility ───────────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n == 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
