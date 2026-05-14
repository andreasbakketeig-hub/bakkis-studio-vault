"""
Cleanup Recommendations view — surfaces safe format-cleanup suggestions
without deleting or quarantining any files.
"""

from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from app.core.cleanup import (
    CONF_REVIEW,
    CONF_SAFE,
    CONF_UNKNOWN,
    DAW_PROFILES,
    PROFILE_ABLETON,
    PROFILE_CUSTOM,
    CleanupRecommendation,
    DawProfile,
    analyze_cleanup,
    get_profile,
    make_custom_profile,
)
from app.core.scanner import Plugin, _fmt_size

# ── Design System ─────────────────────────────────────────────────────────────
BG_CARD          = "#131720"
BG_CARD_INNER    = "#181D2C"
BG_TABLE         = "#0D1020"
BG_TABLE_ROW     = "#131720"
BG_TABLE_ROW_ALT = "#161B28"
BG_TABLE_SEL     = "#1B2848"
ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
ACCENT_DIM       = "#1A2545"
ACCENT_GREEN     = "#4ADE80"
ACCENT_WARN      = "#F59E0B"
ACCENT_SAFE      = "#4ADE80"
ACCENT_REVIEW    = "#F59E0B"
ACCENT_UNKNOWN   = "#94A3B8"
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

CONF_COLORS: dict[str, str] = {
    CONF_SAFE:    ACCENT_SAFE,
    CONF_REVIEW:  ACCENT_REVIEW,
    CONF_UNKNOWN: ACCENT_UNKNOWN,
}

_CUSTOM_FMT_ORDER: list[str] = ["VST3", "AU", "VST", "AAX"]

FILTER_ALL       = "all"
FILTER_SAFE      = "safe"
FILTER_REVIEW    = "review"
FILTER_HIGH_DISK = "high_disk"
FILTER_MULTI     = "multi"

_FILTERS: list[tuple[str, str]] = [
    (FILTER_ALL,       "All"),
    (FILTER_SAFE,      "Safe"),
    (FILTER_REVIEW,    "Review"),
    (FILTER_HIGH_DISK, "High Disk"),
    (FILTER_MULTI,     "Multi-Format"),
]

_ROW_HEADER  = 0
_ROW_PROFILE = 1
_ROW_STATS   = 2
_ROW_FILTERS = 3
_ROW_TABLE   = 4
_ROW_STATUS  = 5


class CleanupRecommendationsView(ctk.CTkFrame):
    """Cleanup Recommendations — read-only analysis of plugin format redundancy."""

    def __init__(self, parent: ctk.CTkFrame, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._plugins: list[Plugin] = []
        self._recs: list[CleanupRecommendation] = []
        self._active_filter: str = FILTER_ALL
        self._active_profile_key: str = PROFILE_ABLETON
        self._filter_btns: dict[str, ctk.CTkButton] = {}
        self._profile_btns: dict[str, ctk.CTkButton] = {}
        self._iid_to_rec: dict[str, CleanupRecommendation] = {}

        self._custom_vars: dict[str, tk.BooleanVar] = {
            "VST3": tk.BooleanVar(value=True),
            "AU":   tk.BooleanVar(value=True),
            "VST":  tk.BooleanVar(value=False),
            "AAX":  tk.BooleanVar(value=False),
        }

        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(_ROW_TABLE, weight=1)

        self._build_header()
        self._build_profile_bar()
        self._build_stats_row()
        self._build_filter_bar()
        self._build_table()
        self._build_statusbar()
        self._show_empty_state(initial=True)

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=_ROW_HEADER, column=0, sticky="ew", padx=30, pady=(28, 0))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Cleanup Recommendations",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Safe format-redundancy suggestions  ·  No files are deleted",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        legend = ctk.CTkFrame(header, fg_color="transparent")
        legend.grid(row=0, column=1, rowspan=2, sticky="e")

        ctk.CTkLabel(
            legend, text="Confidence:",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(side="right")

        for conf, color in CONF_COLORS.items():
            badge = ctk.CTkFrame(legend, fg_color=BORDER_BRIGHT, corner_radius=6)
            badge.pack(side="right", padx=(4, 0))
            ctk.CTkLabel(
                badge, text=f"● {conf}",
                font=ctk.CTkFont(size=10), text_color=color,
            ).pack(padx=8, pady=4)

    def _build_profile_bar(self) -> None:
        card = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=12,
            border_width=1, border_color=BORDER,
        )
        card.grid(row=_ROW_PROFILE, column=0, sticky="ew", padx=30, pady=(16, 0))
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text="DAW Profile",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, padx=(18, 14), pady=(13, 0), sticky="w")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=0, column=1, sticky="w", padx=(0, 16), pady=(11, 0))

        for profile in DAW_PROFILES:
            is_active = profile.key == self._active_profile_key
            btn = ctk.CTkButton(
                btn_row,
                text=profile.name,
                width=115,
                height=30,
                corner_radius=8,
                font=ctk.CTkFont(size=12),
                fg_color=ACCENT if is_active else BG_CARD_INNER,
                hover_color=ACCENT_HOVER if is_active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if is_active else TEXT_MUTED,
                border_width=1,
                border_color=BORDER,
                command=lambda k=profile.key: self._set_profile(k),
            )
            btn.pack(side="left", padx=(0, 6))
            self._profile_btns[profile.key] = btn

        self._profile_desc_label = ctk.CTkLabel(
            card,
            text=get_profile(self._active_profile_key).description,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        self._profile_desc_label.grid(
            row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(4, 12),
        )

        self._custom_fmt_frame = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(
            self._custom_fmt_frame,
            text="Preferred formats:",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).pack(side="left", padx=(0, 10))

        for fmt in _CUSTOM_FMT_ORDER:
            cb = ctk.CTkCheckBox(
                self._custom_fmt_frame,
                text=fmt,
                variable=self._custom_vars[fmt],
                font=ctk.CTkFont(size=12),
                text_color=FMT_COLORS.get(fmt, TEXT_PRIMARY),
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                checkmark_color=TEXT_PRIMARY,
                border_color=BORDER,
                command=self._on_custom_format_change,
            )
            cb.pack(side="left", padx=(0, 14))

    def _build_stats_row(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=_ROW_STATS, column=0, sticky="ew", padx=30, pady=(14, 0))
        for i in range(4):
            row.grid_columnconfigure(i, weight=1, uniform="cstat")

        self._stat_analyzed = self._make_stat_card(row, 0, "PRODUCTS ANALYZED",     "—", ACCENT)
        self._stat_flagged  = self._make_stat_card(row, 1, "FORMATS FLAGGED",        "—", ACCENT_WARN)
        self._stat_safe     = self._make_stat_card(row, 2, "SAFE TO REMOVE",         "—", ACCENT_SAFE)
        self._stat_space    = self._make_stat_card(row, 3, "EST. RECOVERABLE SPACE", "—", ACCENT_GREEN)

    def _make_stat_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        label: str,
        initial: str,
        color: str,
    ) -> ctk.CTkLabel:
        pad = (0, 10) if col < 3 else (0, 0)
        card = ctk.CTkFrame(
            parent, fg_color=BG_CARD, corner_radius=12,
            border_width=1, border_color=BORDER,
        )
        card.grid(row=0, column=col, sticky="ew", padx=pad)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=label,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 2))

        lbl = ctk.CTkLabel(
            card, text=initial,
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=color, anchor="w",
        )
        lbl.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 16))
        return lbl

    def _build_filter_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=_ROW_FILTERS, column=0, sticky="ew", padx=30, pady=(12, 0))

        for key, label in _FILTERS:
            is_active = key == FILTER_ALL
            btn = ctk.CTkButton(
                bar,
                text=label,
                width=120,
                height=32,
                corner_radius=9,
                font=ctk.CTkFont(size=12),
                fg_color=ACCENT if is_active else BG_CARD,
                hover_color=ACCENT_HOVER if is_active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if is_active else TEXT_MUTED,
                border_width=1,
                border_color=BORDER,
                command=lambda k=key: self._set_filter(k),
            )
            btn.pack(side="left", padx=(0, 8))
            self._filter_btns[key] = btn

    def _build_table(self) -> None:
        container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        container.grid(row=_ROW_TABLE, column=0, sticky="nsew", padx=30, pady=(12, 0))
        container.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(container, height=1, fg_color=BORDER).grid(
            row=0, column=0, sticky="ew", padx=16, pady=(12, 0),
        )

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure(
            "Cleanup.Treeview",
            background=BG_TABLE,
            foreground=TEXT_PRIMARY,
            fieldbackground=BG_TABLE,
            rowheight=36,
            borderwidth=0,
            font=("SF Pro Text", 12),
        )
        style.configure(
            "Cleanup.Treeview.Heading",
            background=BG_TABLE,
            foreground=TEXT_MUTED,
            font=("SF Pro Text", 10),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Cleanup.Treeview",
            background=[("selected", BG_TABLE_SEL)],
            foreground=[("selected", TEXT_PRIMARY)],
        )
        style.layout("Cleanup.Treeview", [("Cleanup.Treeview.treearea", {"sticky": "nswe"})])

        columns = ("name", "developer", "installed", "keep", "redundant", "space", "confidence")
        self._tree = ttk.Treeview(
            tree_frame, columns=columns,
            show="headings", style="Cleanup.Treeview", selectmode="browse",
        )

        col_cfg = [
            ("name",       "PLUGIN NAME",        200, True,  "w"),
            ("developer",  "DEVELOPER",           140, True,  "w"),
            ("installed",  "INSTALLED FORMATS",   160, False, "w"),
            ("keep",       "KEEP",                130, False, "w"),
            ("redundant",  "SUGGESTED REMOVAL",   150, False, "w"),
            ("space",      "RECOVERABLE",          95, False, "e"),
            ("confidence", "CONFIDENCE",            90, False, "center"),
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

        for conf, color in CONF_COLORS.items():
            self._tree.tag_configure(f"{conf}_even", background=BG_TABLE_ROW,     foreground=color)
            self._tree.tag_configure(f"{conf}_odd",  background=BG_TABLE_ROW_ALT, foreground=color)
        self._tree.tag_configure("none_even", background=BG_TABLE_ROW,     foreground=TEXT_MUTED)
        self._tree.tag_configure("none_odd",  background=BG_TABLE_ROW_ALT, foreground=TEXT_MUTED)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._empty_label = ctk.CTkLabel(
            container, text="",
            font=ctk.CTkFont(size=13), text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=1, column=0)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=_ROW_STATUS, column=0, sticky="ew", padx=30, pady=(8, 22))
        bar.grid_columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(
            bar, text="",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="w",
        )
        self._status_label.grid(row=0, column=0, sticky="w")

        self._reveal_btn = ctk.CTkButton(
            bar,
            text="⌘  Reveal in Finder",
            width=155,
            height=34,
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
        self._reveal_btn.grid(row=0, column=1, sticky="e")

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self, plugins: list[Plugin]) -> None:
        self._plugins = plugins
        self._reanalyze()

    def _set_profile(self, key: str) -> None:
        if key == self._active_profile_key:
            return
        self._active_profile_key = key
        self._update_profile_buttons()
        self._update_profile_description()
        self._toggle_custom_checkboxes()
        self._reanalyze()

    def _update_profile_buttons(self) -> None:
        for key, btn in self._profile_btns.items():
            active = key == self._active_profile_key
            btn.configure(
                fg_color=ACCENT if active else BG_CARD_INNER,
                hover_color=ACCENT_HOVER if active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
            )

    def _update_profile_description(self) -> None:
        profile = self._active_profile()
        if self._active_profile_key == PROFILE_CUSTOM:
            preferred = self._custom_preferred()
            text = (
                f"Custom preferred: {' · '.join(preferred)}" if preferred
                else "No formats selected — select at least one preferred format"
            )
        else:
            text = profile.description
        self._profile_desc_label.configure(text=text)

    def _toggle_custom_checkboxes(self) -> None:
        if self._active_profile_key == PROFILE_CUSTOM:
            self._custom_fmt_frame.grid(
                row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(4, 12),
            )
            self._profile_desc_label.grid_remove()
        else:
            self._custom_fmt_frame.grid_remove()
            self._profile_desc_label.grid(
                row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(4, 12),
            )

    def _on_custom_format_change(self) -> None:
        self._update_profile_description()
        if self._active_profile_key == PROFILE_CUSTOM:
            self._reanalyze()

    def _active_profile(self) -> DawProfile:
        if self._active_profile_key == PROFILE_CUSTOM:
            return make_custom_profile(self._custom_preferred())
        return get_profile(self._active_profile_key)

    def _custom_preferred(self) -> list[str]:
        return [f for f in _CUSTOM_FMT_ORDER if self._custom_vars[f].get()]

    def _reanalyze(self) -> None:
        if not self._plugins:
            self._recs = []
            self._show_empty_state(initial=False)
            self._reset_stats()
            return

        profile = self._active_profile()
        if self._active_profile_key == PROFILE_CUSTOM and not profile.preferred:
            self._recs = []
            self._empty_label.configure(
                text="Select at least one preferred format above to generate recommendations."
            )
            self._empty_label.grid()
            self._reset_stats()
            return

        self._recs = analyze_cleanup(self._plugins, profile)
        self._active_filter = FILTER_ALL
        self._update_filter_buttons()
        self._update_stat_cards()
        self._populate()

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
                hover_color=ACCENT_HOVER if active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
            )

    def _filtered_recs(self) -> list[CleanupRecommendation]:
        if self._active_filter == FILTER_SAFE:
            return [r for r in self._recs if r.confidence == CONF_SAFE and r.has_redundant]
        if self._active_filter == FILTER_REVIEW:
            return [r for r in self._recs if r.confidence == CONF_REVIEW]
        if self._active_filter == FILTER_HIGH_DISK:
            return [r for r in self._recs if r.is_high_disk_usage]
        if self._active_filter == FILTER_MULTI:
            return [r for r in self._recs if r.is_multi_format]
        return self._recs

    def _show_empty_state(self, *, initial: bool) -> None:
        msg = (
            "Run a scan in  ◈ Plug-in Scanner  to generate cleanup recommendations."
            if initial
            else "No recommendations match the current filter."
        )
        self._empty_label.configure(text=msg)
        self._empty_label.grid()

    def _reset_stats(self) -> None:
        for lbl in (self._stat_analyzed, self._stat_flagged, self._stat_safe, self._stat_space):
            lbl.configure(text="—")
        self._status_label.configure(text="")

    def _update_stat_cards(self) -> None:
        if not self._recs:
            self._reset_stats()
            return
        total_analyzed = len(self._recs)
        total_flagged  = sum(len(r.redundant_formats) for r in self._recs)
        total_safe     = sum(1 for r in self._recs if r.confidence == CONF_SAFE and r.has_redundant)
        total_space    = sum(r.recoverable_size for r in self._recs)
        self._stat_analyzed.configure(text=str(total_analyzed))
        self._stat_flagged.configure(text=str(total_flagged))
        self._stat_safe.configure(text=str(total_safe))
        self._stat_space.configure(text=_fmt_size(total_space) if total_space else "0 B")

    def _populate(self) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._iid_to_rec.clear()
        self._reveal_btn.configure(state="disabled", text_color=TEXT_MUTED)

        if not self._recs:
            self._show_empty_state(initial=True)
            return

        recs = self._filtered_recs()

        if not recs:
            self._show_empty_state(initial=False)
            self._status_label.configure(text="No recommendations match the current filter.")
            return

        self._empty_label.grid_remove()

        conf_row: dict[str, int] = {CONF_SAFE: 0, CONF_REVIEW: 0, CONF_UNKNOWN: 0, "none": 0}

        for rec in recs:
            installed_str = "  ·  ".join(
                f for f in ("VST3", "AU", "VST", "AAX") if f in rec.installed_formats
            )
            keep_str      = "  ·  ".join(rec.keep_formats) if rec.keep_formats else "—"
            redundant_str = "  ·  ".join(rec.redundant_formats) if rec.redundant_formats else "—"
            space_str     = rec.recoverable_size_human if rec.has_redundant else "—"

            tag_key = rec.confidence if rec.has_redundant else "none"
            idx     = conf_row.get(tag_key, 0)
            parity  = "even" if idx % 2 == 0 else "odd"
            tag     = f"{tag_key}_{parity}"
            conf_row[tag_key] = idx + 1

            iid = self._tree.insert(
                "", "end",
                values=(rec.product_name, rec.developer or "—", installed_str,
                        keep_str, redundant_str, space_str, rec.confidence),
                tags=(tag,),
            )
            self._iid_to_rec[iid] = rec

        self._update_status(len(recs))

    def _update_status(self, visible: int) -> None:
        if not self._recs:
            self._status_label.configure(text="")
            return
        flagged      = [r for r in self._recs if r.has_redundant]
        safe_count   = sum(1 for r in flagged if r.confidence == CONF_SAFE)
        review_count = sum(1 for r in flagged if r.confidence == CONF_REVIEW)
        profile_name = self._active_profile().name

        if self._active_filter == FILTER_ALL:
            self._status_label.configure(
                text=f"{len(flagged)} of {len(self._recs)} products have redundant formats"
                     f"  [{profile_name}]  ·  {safe_count} safe  ·  {review_count} need review"
            )
        else:
            label = next(lbl for k, lbl in _FILTERS if k == self._active_filter)
            self._status_label.configure(
                text=f"Showing {visible} result(s) — {label}  [{profile_name}]"
            )

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
        rec = self._iid_to_rec.get(selected[0])
        if not rec:
            return
        target_fmt = rec.redundant_formats[0] if rec.redundant_formats else None
        if not target_fmt:
            target_fmt = next(iter(rec.installed_formats), None)
        if target_fmt and target_fmt in rec.installed_formats:
            path = rec.installed_formats[target_fmt].path
            if path:
                subprocess.run(["open", "-R", path], check=False)
