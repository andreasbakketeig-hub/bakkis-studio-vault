"""
Plugin Health view — analyze scanned plug-ins for potential issues.
"""

from __future__ import annotations

import os
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

import customtkinter as ctk

from app.core.music_software_scanner import MusicApp
from app.core.health import CAT_BROKEN, CAT_DUPLICATE, CAT_WARNING
from app.core.plugin_insights import (
    ACTION_CHECK_VENDOR_WEBSITE,
    ACTION_OPEN_UPDATE_MANAGER,
    FILTER_ALL,
    FILTER_STALE_MODIFIED,
    FILTER_UPDATE_GUIDANCE,
    FILTER_VERSION_CONFLICT,
    PluginInsight,
    PluginInsightsReport,
    analyze_insights,
    filter_display_label,
    insight_options_from_settings,
    is_quarantine_eligible,
    open_update_manager,
    open_vendor_website,
)
from app.core.quarantine import (
    QuarantineDestinationMismatchError,
    QuarantineError,
    complete_quarantine_move,
    get_quarantine_display_root,
    is_path_quarantined,
    preflight_quarantine_target,
    register_pending_quarantine,
    sync_quarantine_root_from_settings,
)
from app.ui.dialogs.quarantine_confirm import (
    QuarantineConfirmDialog,
    QuarantineConfirmTarget,
)
from app.core.scanner import Plugin
from app.ui.tree_columns import (
    FixedColumn,
    FlexColumn,
    TreeColumnLayout,
    bind_responsive_tree_columns,
)

# ── Design System ─────────────────────────────────────────────────────────────
BG_CARD          = "#131720"
BG_TABLE         = "#0D1020"
BG_TABLE_ROW     = "#131720"
BG_TABLE_ROW_ALT = "#161B28"
BG_TABLE_SEL     = "#1B2848"
ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
ACCENT_GREEN     = "#4ADE80"
ACCENT_WARN      = "#F59E0B"
ACCENT_DANGER    = "#F87171"
ACCENT_DUPE      = "#A855F7"
GREEN_DIM        = "#183A28"
ORANGE_DIM       = "#2A1E08"
RED_DIM          = "#2A1018"
PURPLE_DIM       = "#21133A"
TEXT_PRIMARY     = "#EEF0F8"
TEXT_SECONDARY   = "#94A3B8"
TEXT_MUTED       = "#4B5870"
BORDER           = "#1C2038"
BORDER_BRIGHT    = "#242B48"

_CAT_FG: dict[str, str] = {
    CAT_BROKEN:              ACCENT_DANGER,
    CAT_WARNING:             ACCENT_WARN,
    CAT_DUPLICATE:           ACCENT_DUPE,
    FILTER_VERSION_CONFLICT: "#60A5FA",
    FILTER_STALE_MODIFIED:   "#94A3B8",
    FILTER_UPDATE_GUIDANCE:  "#38BDF8",
}

_FILTERS: list[tuple[str, str]] = [
    (FILTER_ALL,               "All Issues"),
    (FILTER_VERSION_CONFLICT,  "Version Conflicts"),
    (FILTER_STALE_MODIFIED,    "Stale Plugins"),
    (FILTER_UPDATE_GUIDANCE,   "Update Guidance"),
    (CAT_WARNING,              "Warnings"),
    (CAT_DUPLICATE,            "Duplicates"),
    (CAT_BROKEN,               "Broken"),
]

_HEALTH_COLUMNS = TreeColumnLayout(
    fixed=(
        FixedColumn("issue_type", 170, "w"),
        FixedColumn("fmt", 56, "center"),
    ),
    flex=(
        FlexColumn("name", weight=1.0, min_width=100, anchor="w"),
        FlexColumn("path", weight=1.4, min_width=140, anchor="w"),
        FlexColumn("action", weight=3.0, min_width=200, anchor="w"),
    ),
)


class PluginHealthView(ctk.CTkFrame):
    """Plugin Health module — surfaces issues in the scanned plug-in list."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        settings=None,
        on_request_rescan: Optional[Callable[[], None]] = None,
        on_quarantine_complete: Optional[Callable[[], None]] = None,
        scan_paths: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._on_request_rescan = on_request_rescan
        self._on_quarantine_complete = on_quarantine_complete
        self._scan_paths: list[str] = list(scan_paths or [])
        self._report: PluginInsightsReport | None = None
        self._active_filter: str = FILTER_ALL
        self._iid_to_insight: dict[str, PluginInsight] = {}
        self._filter_btns: dict[str, ctk.CTkButton] = {}
        self._settings = settings
        self._music_apps: list[MusicApp] = []
        self._vst2_sensitivity: str = (
            settings.legacy_vst2_sensitivity if settings else "Medium"
        )
        self._accent: str = (settings.accent_color if settings else None) or ACCENT

        self._build()

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
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Plugin Health",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Analyze scanned plug-ins and detect potential issues",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        ctk.CTkLabel(
            header,
            text="Read-only insights. Files are only moved if you explicitly use Quarantine and confirm.",
            font=ctk.CTkFont(size=11),
            text_color=ACCENT_GREEN,
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

    def _build_stats_row(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=30, pady=(20, 0))
        for i in range(4):
            row.grid_columnconfigure(i, weight=1, uniform="hstat")

        defs = [
            (0, "HEALTHY PLUGINS",  "—", ACCENT_GREEN, GREEN_DIM),
            (1, "WARNINGS",         "—", ACCENT_WARN,  ORANGE_DIM),
            (2, "DUPLICATES",       "—", ACCENT_DUPE,  PURPLE_DIM),
            (3, "POSSIBLE BROKEN",  "—", ACCENT_DANGER, RED_DIM),
        ]
        self._stat_healthy    = self._make_stat_card(row, *defs[0])
        self._stat_warnings   = self._make_stat_card(row, *defs[1])
        self._stat_duplicates = self._make_stat_card(row, *defs[2])
        self._stat_broken     = self._make_stat_card(row, *defs[3])

    def _make_stat_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        label: str,
        initial: str,
        color: str,
        dim_color: str,
    ) -> ctk.CTkLabel:
        pad = (0, 10) if col < 3 else (0, 0)
        card = ctk.CTkFrame(
            parent, fg_color=BG_CARD, corner_radius=12,
            border_width=1, border_color=BORDER,
        )
        card.grid(row=0, column=col, sticky="ew", padx=pad)
        card.grid_columnconfigure(1, weight=1)

        icon_box = ctk.CTkFrame(card, width=38, height=38, corner_radius=9, fg_color=dim_color)
        icon_box.grid(row=0, column=0, rowspan=2, padx=(14, 0), pady=14)
        icon_box.grid_propagate(False)

        ctk.CTkLabel(
            card, text=label,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=1, sticky="sw", padx=(12, 14), pady=(14, 0))

        lbl = ctk.CTkLabel(
            card, text=initial,
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=color, anchor="w",
        )
        lbl.grid(row=1, column=1, sticky="nw", padx=(12, 14), pady=(0, 14))
        return lbl

    def _build_filter_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=30, pady=(14, 0))

        # VST2 sensitivity indicator
        vst2_label_map = {
            "Low":    ("VST2 Sensitivity: Low — only flagged when modern version exists", "#4ADE80"),
            "Medium": ("VST2 Sensitivity: Medium", "#94A3B8"),
            "High":   ("VST2 Sensitivity: High — all VST2 flagged as broken", "#F87171"),
        }
        vst2_text, vst2_color = vst2_label_map.get(
            self._vst2_sensitivity, ("VST2 Sensitivity: Medium", "#94A3B8")
        )
        ctk.CTkLabel(
            bar,
            text=vst2_text,
            font=ctk.CTkFont(size=10),
            text_color=vst2_color,
        ).pack(side="right")

        for key, label in _FILTERS:
            is_active = key == FILTER_ALL
            btn = ctk.CTkButton(
                bar,
                text=label,
                width=108,
                height=34,
                corner_radius=9,
                font=ctk.CTkFont(size=12),
                fg_color=self._accent if is_active else BG_CARD,
                hover_color=ACCENT_HOVER if is_active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if is_active else TEXT_MUTED,
                border_width=1,
                border_color=BORDER,
                command=lambda k=key: self._set_filter(k),
            )
            btn.pack(side="left", padx=(0, 8))
            self._filter_btns[key] = btn

    def _build_table(self) -> None:
        self._table_container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        self._table_container.grid(row=3, column=0, sticky="nsew", padx=30, pady=(14, 0))
        self._table_container.grid_rowconfigure(1, weight=1)
        self._table_container.grid_columnconfigure(0, weight=1)
        container = self._table_container

        ctk.CTkFrame(container, height=1, fg_color=BORDER).grid(
            row=0, column=0, sticky="ew", padx=16, pady=(12, 0),
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
            rowheight=36,
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
            tree_frame, columns=columns,
            show="headings", style="Health.Treeview", selectmode="browse",
        )
        for col_id, heading in (
            ("name", "PLUGIN NAME"),
            ("issue_type", "ISSUE TYPE"),
            ("fmt", "FORMAT"),
            ("path", "FILE PATH"),
            ("action", "SUGGESTED ACTION"),
        ):
            self._tree.heading(col_id, text=heading)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        for cat, fg in _CAT_FG.items():
            self._tree.tag_configure(f"{cat}_even", background=BG_TABLE_ROW,     foreground=fg)
            self._tree.tag_configure(f"{cat}_odd",  background=BG_TABLE_ROW_ALT, foreground=fg)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._relayout_tree_columns = bind_responsive_tree_columns(
            self._tree,
            tree_frame,
            _HEALTH_COLUMNS,
            extra_hosts=(container, self),
        )

        self._empty_label = ctk.CTkLabel(
            container, text="",
            font=ctk.CTkFont(size=13), text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=1, column=0)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=4, column=0, sticky="ew", padx=30, pady=(8, 22))
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
        self._reveal_btn.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self._open_manager_btn = ctk.CTkButton(
            bar,
            text="⬆  Open Update Manager",
            width=175,
            height=34,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._open_update_manager,
            state="disabled",
        )
        self._open_manager_btn.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self._open_website_btn = ctk.CTkButton(
            bar,
            text="🌐  Open Vendor Website",
            width=175,
            height=34,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._open_vendor_website,
            state="disabled",
        )
        self._open_website_btn.grid(row=0, column=3, sticky="e", padx=(0, 8))

        self._quarantine_btn = ctk.CTkButton(
            bar,
            text="▣  Quarantine…",
            width=130,
            height=34,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            command=self._quarantine_selected,
            state="disabled",
        )
        self._quarantine_btn.grid(row=0, column=4, sticky="e")

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(
        self,
        plugins: list[Plugin],
        music_apps: list[MusicApp] | None = None,
    ) -> None:
        if music_apps is not None:
            self._music_apps = music_apps
        s = self._settings
        opts = insight_options_from_settings(s)
        opts.setdefault("vst2_sensitivity", self._vst2_sensitivity)
        self._report = analyze_insights(plugins, self._music_apps, **opts)
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
                fg_color=self._accent if active else BG_CARD,
                hover_color=ACCENT_HOVER if active else BORDER_BRIGHT,
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
            )

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
            for lbl in (self._stat_healthy, self._stat_warnings,
                        self._stat_duplicates, self._stat_broken):
                lbl.configure(text="—")
            return
        r = self._report
        self._stat_healthy.configure(text=f"{r.healthy_count:,}")
        self._stat_warnings.configure(text=f"{len(r.warnings):,}")
        self._stat_duplicates.configure(text=f"{len(r.duplicates):,}")
        self._stat_broken.configure(text=f"{len(r.broken):,}")

    def _populate(self) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._iid_to_insight.clear()
        self._reveal_btn.configure(state="disabled", text_color=TEXT_MUTED)
        self._open_manager_btn.configure(state="disabled", text_color=TEXT_MUTED)
        self._open_website_btn.configure(state="disabled", text_color=TEXT_MUTED)
        self._quarantine_btn.configure(state="disabled", text_color=TEXT_MUTED)

        if self._report is None:
            self._show_empty_state(initial=True)
            return

        issues = self._report.by_filter(self._active_filter)

        if not issues:
            label = filter_display_label(self._active_filter)
            msg = (
                f"No {label} issues found."
                if self._active_filter != FILTER_ALL
                else "No issues detected — all scanned plug-ins appear healthy."
            )
            self._empty_label.configure(text=msg)
            self._empty_label.grid()
            self._update_status(0)
            return

        self._empty_label.grid_remove()

        cat_row: dict[str, int] = {}

        for issue in issues:
            cat = issue.category
            idx    = cat_row.get(cat, 0)
            parity = "even" if idx % 2 == 0 else "odd"
            tag    = f"{cat}_{parity}"
            cat_row[cat] = idx + 1

            action_text = issue.recommendation
            iid = self._tree.insert(
                "", "end",
                values=(issue.plugin_name, issue.issue_type, issue.fmt,
                        issue.path, action_text),
                tags=(tag,),
            )
            self._iid_to_insight[iid] = issue

        self._update_status(len(issues))
        if hasattr(self, "_relayout_tree_columns"):
            self.after_idle(self._relayout_tree_columns)

    def _update_status(self, visible: int) -> None:
        if self._report is None:
            self._status_label.configure(text="")
            return

        total   = len(self._report.insights)
        plugins = self._report.total_plugins

        if self._active_filter == FILTER_ALL:
            if total == 0:
                self._status_label.configure(
                    text=f"No issues detected across {plugins:,} scanned plug-in(s)"
                )
            else:
                self._status_label.configure(
                    text=f"{total:,} issue(s) across {plugins:,} plug-in(s)  ·  "
                         f"{self._report.healthy_count:,} healthy"
                )
        else:
            label = filter_display_label(self._active_filter)
            self._status_label.configure(
                text=f"Showing {visible:,} {label} issue(s)"
            )

    def _on_select(self, _event=None) -> None:
        selected = self._tree.selection()
        has_sel = bool(selected)
        self._reveal_btn.configure(
            state="normal" if has_sel else "disabled",
            text_color=TEXT_PRIMARY if has_sel else TEXT_MUTED,
        )
        insight = self._iid_to_insight.get(selected[0]) if selected else None
        can_open = bool(insight and self._can_open_manager(insight))
        btn_label = "⬆  Open Update Manager"
        if insight and insight.manager_app_name:
            btn_label = f"⬆  Open {insight.manager_app_name}"
        self._open_manager_btn.configure(
            text=btn_label,
            state="normal" if can_open else "disabled",
            text_color=TEXT_PRIMARY if can_open else TEXT_MUTED,
        )
        can_web = bool(insight and self._can_open_website(insight))
        self._open_website_btn.configure(
            state="normal" if can_web else "disabled",
            text_color=TEXT_PRIMARY if can_web else TEXT_MUTED,
        )
        can_q, q_help = (False, "")
        if insight:
            can_q, q_help = self._quarantine_state(insight)
        self._quarantine_btn.configure(
            state="normal" if can_q else "disabled",
            text_color=TEXT_PRIMARY if can_q else TEXT_MUTED,
        )
        if q_help:
            self._status_label.configure(text=q_help)
        elif insight:
            self._status_label.configure(text="")

    def _can_open_manager(self, insight: PluginInsight) -> bool:
        return (
            insight.recommended_action == ACTION_OPEN_UPDATE_MANAGER
            and bool(insight.manager_app_path)
            and os.path.exists(insight.manager_app_path)
        )

    def _reveal_in_finder(self) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        insight = self._iid_to_insight.get(selected[0])
        if insight and insight.path:
            subprocess.run(["open", "-R", insight.path], check=False)

    def _can_open_website(self, insight: PluginInsight) -> bool:
        return (
            insight.recommended_action == ACTION_CHECK_VENDOR_WEBSITE
            and bool((insight.website_url or "").strip())
        )

    def _open_update_manager(self) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        insight = self._iid_to_insight.get(selected[0])
        if insight and self._can_open_manager(insight):
            open_update_manager(insight)

    def _open_vendor_website(self) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        insight = self._iid_to_insight.get(selected[0])
        if insight and self._can_open_website(insight):
            open_vendor_website(insight)

    def _quarantine_state(self, insight: PluginInsight) -> tuple[bool, str]:
        if not is_quarantine_eligible(insight):
            return False, ""
        if not (insight.path or "").strip():
            return False, "No plug-in path available for quarantine."
        if is_path_quarantined(insight.path):
            return False, "This plug-in is already in quarantine."
        if not os.path.exists(insight.path):
            return False, "Plug-in path no longer exists on disk."
        pf = preflight_quarantine_target(
            insight.path,
            scan_paths=self._scan_paths or None,
        )
        if not pf.can_offer_in_ui:
            return False, pf.message
        return True, ""

    def _can_quarantine(self, insight: PluginInsight) -> bool:
        return self._quarantine_state(insight)[0]

    def _quarantine_selected(self) -> None:
        selected = self._tree.selection()
        if not selected:
            return
        insight = self._iid_to_insight.get(selected[0])
        if not insight or not self._can_quarantine(insight):
            return
        qroot = sync_quarantine_root_from_settings(self._settings)
        root = self.winfo_toplevel()
        QuarantineConfirmDialog(
            root,
            QuarantineConfirmTarget.from_insight(insight),
            self._execute_quarantine,
            scan_paths=self._scan_paths,
            quarantine_root=qroot,
            display_quarantine_root=get_quarantine_display_root(self._settings),
        )

    def _execute_quarantine(
        self,
        path: str,
        reason: str,
        operation_id: str,
        expected_dest: str,
        system_ack: bool,
    ) -> None:
        insight = None
        for i in self._iid_to_insight.values():
            if i.path == path:
                insight = i
                break
        meta = {
            "plugin_name": insight.plugin_name if insight else "",
            "developer": insight.developer if insight else "",
            "fmt": insight.fmt if insight else "",
            "app_version": insight.installed_version if insight else "",
            "issue_kind": insight.issue_kind if insight else "",
        }
        qroot = sync_quarantine_root_from_settings(self._settings)
        try:
            register_pending_quarantine(
                path,
                reason,
                operation_id,
                expected_dest,
                metadata=meta,
                root=qroot,
                scan_paths=self._scan_paths,
                system_path_acknowledged=system_ack,
            )
            result = complete_quarantine_move(
                operation_id,
                expected_dest,
                root=qroot,
                scan_paths=self._scan_paths,
            )
            msg = (
                f"Moved to quarantine:\n{result.operation.quarantine_path}\n\n"
                "Insights will refresh after scan."
            )
            if result.warnings:
                msg += "\n\nWarnings:\n" + "\n".join(result.warnings)
            messagebox.showinfo("Quarantine complete", msg)
            if self._on_quarantine_complete:
                self._on_quarantine_complete()
            if self._on_request_rescan:
                self._on_request_rescan()
        except QuarantineDestinationMismatchError as exc:
            messagebox.showerror(
                "Destination changed",
                f"{exc}\n\nPlease open Quarantine again and confirm.",
            )
        except QuarantineError as exc:
            messagebox.showerror("Quarantine failed", str(exc))
