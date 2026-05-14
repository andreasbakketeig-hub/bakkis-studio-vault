"""
Plugin Health view — analyze scanned plug-ins for potential issues.
"""

from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from app.core.scanner import Plugin
from app.core.health import (
    HealthIssue,
    HealthReport,
    analyze_health,
    CAT_BROKEN,
    CAT_WARNING,
    CAT_DUPLICATE,
)

# ── Palette ───────────────────────────────────────────────────────────────────
BG_CARD          = "#13161F"
BG_TABLE         = "#0D0F18"
BG_TABLE_ROW     = "#13161F"
BG_TABLE_ROW_ALT = "#161924"
BG_TABLE_SEL     = "#1E2A4A"
ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
ACCENT_GREEN     = "#7ED321"
ACCENT_WARN      = "#F5A623"
ACCENT_DANGER    = "#F56C6C"
ACCENT_DUPE      = "#9B59F5"
TEXT_PRIMARY     = "#E8EAF0"
TEXT_MUTED       = "#6B7280"
BORDER           = "#1C1F2E"

_CAT_FG: dict[str, str] = {
    CAT_BROKEN:    ACCENT_DANGER,
    CAT_WARNING:   ACCENT_WARN,
    CAT_DUPLICATE: ACCENT_DUPE,
}

FILTER_ALL = "all"

_FILTERS: list[tuple[str, str]] = [
    (FILTER_ALL,    "All"),
    (CAT_WARNING,   "Warnings"),
    (CAT_DUPLICATE, "Duplicates"),
    (CAT_BROKEN,    "Broken"),
]


class PluginHealthView(ctk.CTkFrame):
    """Plugin Health module — detects and surfaces issues in the scanned plug-in list."""

    def __init__(self, parent: ctk.CTkFrame, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._report: HealthReport | None = None
        self._active_filter: str = FILTER_ALL
        self._iid_to_issue: dict[str, HealthIssue] = {}
        self._filter_btns: dict[str, ctk.CTkButton] = {}

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_stats_row()
        self._build_filter_bar()
        self._build_table()
        self._build_statusbar()
        self._show_empty_state(initial=True)

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Plugin Health",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Analyze scanned plug-ins and detect potential issues",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _build_stats_row(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=28, pady=(20, 0))
        for i in range(4):
            row.grid_columnconfigure(i, weight=1, uniform="hstat")

        self._stat_healthy    = self._make_stat_card(row, 0, "HEALTHY PLUGINS",  "—", ACCENT_GREEN)
        self._stat_warnings   = self._make_stat_card(row, 1, "WARNINGS",          "—", ACCENT_WARN)
        self._stat_duplicates = self._make_stat_card(row, 2, "DUPLICATES",        "—", ACCENT_DUPE)
        self._stat_broken     = self._make_stat_card(row, 3, "POSSIBLE BROKEN",   "—", ACCENT_DANGER)

    def _make_stat_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        label: str,
        initial: str,
        color: str,
    ) -> ctk.CTkLabel:
        pad = (0, 12) if col < 3 else (0, 0)
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        card.grid(row=0, column=col, sticky="ew", padx=pad)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=label,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))

        lbl = ctk.CTkLabel(
            card,
            text=initial,
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=color,
            anchor="w",
        )
        lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))
        return lbl

    def _build_filter_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=28, pady=(14, 0))

        for key, label in _FILTERS:
            is_active = key == FILTER_ALL
            btn = ctk.CTkButton(
                bar,
                text=label,
                width=110,
                height=34,
                corner_radius=8,
                font=ctk.CTkFont(size=12),
                fg_color=ACCENT if is_active else BG_CARD,
                hover_color=ACCENT_HOVER if is_active else "#1C1F2E",
                text_color=TEXT_PRIMARY if is_active else TEXT_MUTED,
                border_width=1,
                border_color=BORDER,
                command=lambda k=key: self._set_filter(k),
            )
            btn.pack(side="left", padx=(0, 8))
            self._filter_btns[key] = btn

    def _build_table(self) -> None:
        container = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=12)
        container.grid(row=3, column=0, sticky="nsew", padx=28, pady=(14, 0))
        container.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(container, height=1, fg_color=BORDER).grid(
            row=0, column=0, sticky="ew", padx=16, pady=(12, 0)
        )

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure(
            "Health.Treeview",
            background=BG_TABLE,
            foreground=TEXT_PRIMARY,
            fieldbackground=BG_TABLE,
            rowheight=34,
            borderwidth=0,
            font=("SF Pro Text", 12),
        )
        style.configure(
            "Health.Treeview.Heading",
            background=BG_TABLE,
            foreground=TEXT_MUTED,
            font=("SF Pro Text", 10),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Health.Treeview",
            background=[("selected", BG_TABLE_SEL)],
            foreground=[("selected", TEXT_PRIMARY)],
        )
        style.layout("Health.Treeview", [("Health.Treeview.treearea", {"sticky": "nswe"})])

        columns = ("name", "issue_type", "fmt", "path", "action")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            style="Health.Treeview",
            selectmode="browse",
        )
        col_cfg = [
            ("name",       "PLUGIN NAME",      180, True,  "w"),
            ("issue_type", "ISSUE TYPE",        190, False, "w"),
            ("fmt",        "FORMAT",             70, False, "center"),
            ("path",       "FILE PATH",         290, True,  "w"),
            ("action",     "SUGGESTED ACTION",  250, True,  "w"),
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

        # Row colour tags — one even/odd pair per category
        for cat, fg in _CAT_FG.items():
            self._tree.tag_configure(f"{cat}_even", background=BG_TABLE_ROW,     foreground=fg)
            self._tree.tag_configure(f"{cat}_odd",  background=BG_TABLE_ROW_ALT, foreground=fg)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._empty_label = ctk.CTkLabel(
            container,
            text="",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=1, column=0)

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

        self._reveal_btn = ctk.CTkButton(
            bar,
            text="⌘  Reveal in Finder",
            width=160,
            height=34,
            corner_radius=8,
            font=ctk.CTkFont(size=13),
            fg_color=BG_CARD,
            hover_color="#1C1F2E",
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._reveal_in_finder,
            state="disabled",
        )
        self._reveal_btn.grid(row=0, column=1, sticky="e")

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self, plugins: list[Plugin]) -> None:
        """Re-analyze *plugins* and repopulate the view."""
        self._report = analyze_health(plugins)
        self._active_filter = FILTER_ALL
        self._update_filter_buttons()
        self._update_stat_cards()
        self._populate()

    # ── Filtering ─────────────────────────────────────────────────────────────

    def _set_filter(self, key: str) -> None:
        if key == self._active_filter:
            return
        self._active_filter = key
        self._update_filter_buttons()
        self._populate()

    def _update_filter_buttons(self) -> None:
        for key, btn in self._filter_btns.items():
            active = key == self._active_filter
            btn.configure(
                fg_color=ACCENT if active else BG_CARD,
                hover_color=ACCENT_HOVER if active else "#1C1F2E",
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
            )

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _show_empty_state(self, *, initial: bool) -> None:
        msg = (
            "Run a scan in  ◈ Plug-in Scanner  to analyze plugin health."
            if initial
            else "No issues found matching the current filter."
        )
        self._empty_label.configure(text=msg)
        self._empty_label.grid()

    def _update_stat_cards(self) -> None:
        if self._report is None:
            for lbl in (
                self._stat_healthy,
                self._stat_warnings,
                self._stat_duplicates,
                self._stat_broken,
            ):
                lbl.configure(text="—")
            return

        r = self._report
        self._stat_healthy.configure(text=str(r.healthy_count))
        self._stat_warnings.configure(text=str(len(r.warnings)))
        self._stat_duplicates.configure(text=str(len(r.duplicates)))
        self._stat_broken.configure(text=str(len(r.broken)))

    def _populate(self) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._iid_to_issue.clear()
        self._reveal_btn.configure(state="disabled", text_color=TEXT_MUTED)

        if self._report is None:
            self._show_empty_state(initial=True)
            return

        if self._active_filter == FILTER_ALL:
            issues = self._report.issues
        elif self._active_filter == CAT_WARNING:
            issues = self._report.warnings
        elif self._active_filter == CAT_DUPLICATE:
            issues = self._report.duplicates
        else:
            issues = self._report.broken

        if not issues:
            msg = (
                f"No {self._active_filter} issues found."
                if self._active_filter != FILTER_ALL
                else "No issues detected — all scanned plug-ins appear healthy."
            )
            self._empty_label.configure(text=msg)
            self._empty_label.grid()
            self._update_status(0)
            return

        self._empty_label.grid_remove()

        # Per-category row counters for alternating colours
        cat_row: dict[str, int] = {CAT_BROKEN: 0, CAT_WARNING: 0, CAT_DUPLICATE: 0}

        for issue in issues:
            idx    = cat_row.get(issue.category, 0)
            parity = "even" if idx % 2 == 0 else "odd"
            tag    = f"{issue.category}_{parity}"
            cat_row[issue.category] = idx + 1

            iid = self._tree.insert(
                "", "end",
                values=(
                    issue.plugin_name,
                    issue.issue_type,
                    issue.fmt,
                    issue.path,
                    issue.suggested_action,
                ),
                tags=(tag,),
            )
            self._iid_to_issue[iid] = issue

        self._update_status(len(issues))

    def _update_status(self, visible: int) -> None:
        if self._report is None:
            self._status_label.configure(text="")
            return

        total   = len(self._report.issues)
        plugins = self._report.total_plugins

        if self._active_filter == FILTER_ALL:
            if total == 0:
                self._status_label.configure(
                    text=f"No issues detected across {plugins} scanned plug-in(s)"
                )
            else:
                self._status_label.configure(
                    text=f"{total} issue(s) across {plugins} scanned plug-in(s) "
                         f"— {self._report.healthy_count} healthy"
                )
        else:
            self._status_label.configure(
                text=f"Showing {visible} {self._active_filter} issue(s)"
            )

    # ── Selection / Finder ────────────────────────────────────────────────────

    def _on_select(self, _event=None) -> None:
        has_sel = bool(self._tree.selection())
        self._reveal_btn.configure(
            state="normal" if has_sel else "disabled",
            text_color=TEXT_PRIMARY if has_sel else TEXT_MUTED,
        )

    def _reveal_in_finder(self) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        issue = self._iid_to_issue.get(selected[0])
        if issue and issue.path:
            subprocess.run(["open", "-R", issue.path], check=False)
