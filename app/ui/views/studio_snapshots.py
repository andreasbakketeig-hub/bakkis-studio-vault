"""
Studio Snapshots — compare plugin/software/hardware inventories across machines.

Read-only: no files are moved, no plugins are modified, no cloud sync.

Layout
------
  Header (title + subtitle)
  Toolbar (Export Snapshot | Import Snapshot | status label)
  Snapshot panel (loaded snapshot info cards)
  Compare button
  Results (tabbed sections: missing locally / missing on other /
           version diffs / format diffs / software diffs / hardware diffs)
  Status bar
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import customtkinter as ctk

from app.core.studio_snapshots import (
    SnapshotComparison,
    StudioSnapshot,
    compare_snapshots,
    export_snapshot,
    list_saved_snapshots,
    load_snapshot,
    save_snapshot,
)

# ── Design tokens ─────────────────────────────────────────────────────────────

BG_CARD          = "#131720"
BG_TABLE         = "#0D1020"
BG_TABLE_SEL     = "#1B2848"
ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
TEXT_PRIMARY     = "#EEF0F8"
TEXT_SECONDARY   = "#94A3B8"
TEXT_MUTED       = "#4B5870"
BORDER           = "#1C2038"
BORDER_BRIGHT    = "#242B48"
GREEN            = "#4ADE80"
YELLOW           = "#FBBF24"
RED              = "#F87171"
TEAL             = "#2DD4BF"
ORANGE           = "#F59E0B"

_DIFF_COLORS: dict[str, str] = {
    "missing_locally":  RED,
    "missing_on_other": YELLOW,
    "version_diff":     TEAL,
    "format_diff":      ORANGE,
}

_SECTION_ICONS: dict[str, str] = {
    "missing_locally":  "✕",
    "missing_on_other": "◌",
    "version_diff":     "↕",
    "format_diff":      "⊞",
    "software":         "♬",
    "hardware":         "⬢",
}


class StudioSnapshotsView(ctk.CTkFrame):
    """Compare studio plugin/software/hardware inventories across machines."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        plugins: list | None = None,
        music_apps: list | None = None,
        hardware_devices: list | None = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._plugins: list = plugins or []
        self._music_apps: list = music_apps or []
        self._hardware_devices: list = hardware_devices or []

        self._local_snapshot: StudioSnapshot | None = None
        self._imported_snapshot: StudioSnapshot | None = None
        self._comparison: SnapshotComparison | None = None

        self._status_text = tk.StringVar(value="No snapshot loaded yet.")
        self._local_info_text = tk.StringVar(value="—")
        self._imported_info_text = tk.StringVar(value="No snapshot imported.")

        self._build()

    # ── Public refresh API ────────────────────────────────────────────────────

    def refresh(
        self,
        plugins: list | None = None,
        music_apps: list | None = None,
        hardware_devices: list | None = None,
    ) -> None:
        if plugins is not None:
            self._plugins = plugins
        if music_apps is not None:
            self._music_apps = music_apps
        if hardware_devices is not None:
            self._hardware_devices = hardware_devices
        self._local_snapshot = None
        self._update_local_info_label()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._build_header(row=0)
        self._build_toolbar(row=1)
        self._build_snapshot_cards(row=2)
        self._build_compare_bar(row=3)
        self._build_results(row=4)
        self._build_statusbar(row=5)

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self, row: int) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=row, column=0, sticky="ew", padx=30, pady=(28, 0))

        ctk.CTkLabel(
            hdr,
            text="Studio Snapshots",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            hdr,
            text="Export your studio setup and compare against another machine",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(3, 0))

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self, row: int) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=row, column=0, sticky="ew", padx=30, pady=(18, 0))

        self._export_btn = ctk.CTkButton(
            bar,
            text="  ↑  Export Snapshot",
            width=180,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY,
            command=self._export_snapshot,
        )
        self._export_btn.pack(side="left", padx=(0, 10))

        self._import_btn = ctk.CTkButton(
            bar,
            text="  ↓  Import Snapshot",
            width=180,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_SECONDARY,
            border_width=1,
            border_color=BORDER_BRIGHT,
            command=self._import_snapshot,
        )
        self._import_btn.pack(side="left", padx=(0, 10))

        self._load_saved_btn = ctk.CTkButton(
            bar,
            text="  ⊟  Load Saved",
            width=145,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_SECONDARY,
            border_width=1,
            border_color=BORDER_BRIGHT,
            command=self._pick_saved_snapshot,
        )
        self._load_saved_btn.pack(side="left")

    # ── Snapshot info cards ───────────────────────────────────────────────────

    def _build_snapshot_cards(self, row: int) -> None:
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=row, column=0, sticky="ew", padx=30, pady=(18, 0))
        cards.grid_columnconfigure((0, 1), weight=1)

        self._local_card  = self._make_info_card(cards, col=0, title="This Machine")
        self._import_card = self._make_info_card(cards, col=1, title="Imported Machine")

        self._update_local_info_label()
        self._update_imported_info_label()

    def _make_info_card(
        self, parent: ctk.CTkFrame, col: int, title: str
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        card.grid(row=0, column=col, sticky="ew", padx=(0, 8) if col == 0 else (8, 0), pady=2)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 2))

        info_lbl = ctk.CTkLabel(
            card,
            text="—",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
            anchor="w",
            justify="left",
        )
        info_lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        card._info_label = info_lbl  # type: ignore[attr-defined]
        return card

    def _update_local_info_label(self) -> None:
        if self._local_snapshot:
            s = self._local_snapshot
            text = (
                f"{s.machine_name}\n"
                f"Scanned {s.display_date}\n"
                f"{s.summary.total_plugins} plugins  ·  "
                f"{s.summary.total_software} apps  ·  "
                f"{s.summary.total_hardware} hardware"
            )
        elif self._plugins:
            text = (
                f"{len(self._plugins)} plugins loaded\n"
                f"{len(self._music_apps)} apps  ·  "
                f"{len(self._hardware_devices)} hardware devices\n"
                "Click Export Snapshot to capture"
            )
        else:
            text = "No scan data available.\nRun a plugin scan first."
        self._local_card._info_label.configure(text=text)  # type: ignore[attr-defined]

    def _update_imported_info_label(self) -> None:
        if self._imported_snapshot:
            s = self._imported_snapshot
            text = (
                f"{s.machine_name}\n"
                f"Scanned {s.display_date}\n"
                f"{s.summary.total_plugins} plugins  ·  "
                f"{s.summary.total_software} apps  ·  "
                f"{s.summary.total_hardware} hardware"
            )
        else:
            text = "No snapshot imported.\nUse Import Snapshot to load a JSON file."
        self._import_card._info_label.configure(text=text)  # type: ignore[attr-defined]

    # ── Compare bar ───────────────────────────────────────────────────────────

    def _build_compare_bar(self, row: int) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=row, column=0, sticky="ew", padx=30, pady=(14, 0))

        self._compare_btn = ctk.CTkButton(
            bar,
            text="  ⇄  Compare Snapshots",
            width=200,
            height=38,
            corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=GREEN,
            hover_color="#22c55e",
            text_color="#0D1020",
            command=self._run_comparison,
            state="disabled",
        )
        self._compare_btn.pack(side="left", padx=(0, 16))

        self._compare_info_lbl = ctk.CTkLabel(
            bar,
            text="Import a snapshot to enable comparison",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        )
        self._compare_info_lbl.pack(side="left")

    # ── Results area ──────────────────────────────────────────────────────────

    def _build_results(self, row: int) -> None:
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.grid(row=row, column=0, sticky="nsew", padx=30, pady=(16, 0))
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        self._results_scroll = ctk.CTkScrollableFrame(
            outer,
            fg_color="transparent",
            corner_radius=0,
        )
        self._results_scroll.grid(row=0, column=0, sticky="nsew")
        self._results_scroll.grid_columnconfigure(0, weight=1)

        self._placeholder_lbl = ctk.CTkLabel(
            self._results_scroll,
            text=(
                "Export this machine's snapshot and import one from another machine,\n"
                "then click Compare Snapshots to see differences."
            ),
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
            justify="center",
        )
        self._placeholder_lbl.grid(row=0, column=0, pady=40)

        self._result_sections: list[ctk.CTkFrame] = []

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self, row: int) -> None:
        bar = ctk.CTkFrame(self, fg_color=BG_CARD, height=32, corner_radius=0)
        bar.grid(row=row, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_propagate(False)

        ctk.CTkLabel(
            bar,
            textvariable=self._status_text,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16)

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_snapshot(self) -> None:
        if not self._plugins:
            messagebox.showwarning(
                "No Scan Data",
                "Run a plugin scan first before exporting a snapshot.",
            )
            return

        dest = filedialog.asksaveasfilename(
            title="Save Studio Snapshot",
            defaultextension=".json",
            filetypes=[("Snapshot JSON", "*.json"), ("All Files", "*.*")],
            initialfile="snapshot_this_machine.json",
        )
        if not dest:
            return

        self._export_btn.configure(state="disabled", text="Exporting…")
        self._set_status("Building snapshot…")

        def _worker() -> None:
            try:
                snap = export_snapshot(
                    plugins=self._plugins,
                    music_apps=self._music_apps,
                    hardware_devices=self._hardware_devices or None,
                )
                path = save_snapshot(snap, Path(dest))
                self._local_snapshot = snap
                self.after(0, lambda: self._on_export_done(path))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_export_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_export_done(self, path: Path) -> None:
        self._export_btn.configure(state="normal", text="  ↑  Export Snapshot")
        self._update_local_info_label()
        self._set_status(f"Snapshot saved: {path.name}")
        self._refresh_compare_button()

    def _on_export_error(self, msg: str) -> None:
        self._export_btn.configure(state="normal", text="  ↑  Export Snapshot")
        self._set_status(f"Export failed: {msg}")
        messagebox.showerror("Export Failed", msg)

    # ── Import ────────────────────────────────────────────────────────────────

    def _import_snapshot(self) -> None:
        path = filedialog.askopenfilename(
            title="Import Studio Snapshot",
            filetypes=[("Snapshot JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        self._load_snapshot_from_path(Path(path))

    def _pick_saved_snapshot(self) -> None:
        saved = list_saved_snapshots()
        if not saved:
            messagebox.showinfo(
                "No Saved Snapshots",
                "No snapshots found in the default snapshots folder.\n"
                "Use Import Snapshot to load a JSON file from anywhere.",
            )
            return
        # Build a simple picker dialog
        _SnapshotPickerDialog(self, saved, callback=self._load_snapshot_from_path)

    def _load_snapshot_from_path(self, path: Path) -> None:
        self._set_status(f"Loading {path.name}…")
        try:
            snap = load_snapshot(path)
            self._imported_snapshot = snap
            self._update_imported_info_label()
            self._refresh_compare_button()
            self._set_status(
                f"Imported snapshot from '{snap.machine_name}' "
                f"({snap.summary.total_plugins} plugins)"
            )
        except Exception as exc:
            self._set_status(f"Import failed: {exc}")
            messagebox.showerror("Import Failed", str(exc))

    # ── Comparison ────────────────────────────────────────────────────────────

    def _refresh_compare_button(self) -> None:
        can_compare = self._imported_snapshot is not None and (
            self._local_snapshot is not None or bool(self._plugins)
        )
        self._compare_btn.configure(state="normal" if can_compare else "disabled")
        if can_compare:
            self._compare_info_lbl.configure(
                text="Ready to compare", text_color=GREEN
            )
        else:
            missing = []
            if not self._plugins and not self._local_snapshot:
                missing.append("local scan data")
            if not self._imported_snapshot:
                missing.append("imported snapshot")
            self._compare_info_lbl.configure(
                text=f"Need: {' and '.join(missing)}",
                text_color=TEXT_MUTED,
            )

    def _run_comparison(self) -> None:
        if not self._imported_snapshot:
            return

        self._compare_btn.configure(state="disabled", text="Comparing…")
        self._set_status("Comparing snapshots…")
        self._clear_result_sections()

        def _worker() -> None:
            try:
                local = self._local_snapshot or export_snapshot(
                    plugins=self._plugins,
                    music_apps=self._music_apps,
                    hardware_devices=self._hardware_devices or None,
                )
                cmp = compare_snapshots(local, self._imported_snapshot)  # type: ignore[arg-type]
                self.after(0, lambda c=cmp: self._display_comparison(c))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_compare_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_compare_error(self, msg: str) -> None:
        self._compare_btn.configure(state="normal", text="  ⇄  Compare Snapshots")
        self._set_status(f"Comparison failed: {msg}")
        messagebox.showerror("Comparison Failed", msg)

    def _display_comparison(self, cmp: SnapshotComparison) -> None:
        self._comparison = cmp
        self._compare_btn.configure(state="normal", text="  ⇄  Compare Snapshots")
        self._clear_result_sections()

        if self._placeholder_lbl.winfo_exists():
            self._placeholder_lbl.grid_remove()

        other_name = cmp.other_snapshot.machine_name or "Other Machine"
        local_name  = cmp.local_snapshot.machine_name or "This Machine"

        row = 0

        if cmp.plugins_missing_locally:
            section = self._make_plugin_section(
                title=f"Missing Locally  ({len(cmp.plugins_missing_locally)})",
                subtitle=f"Present on {other_name}, not on {local_name}",
                items=cmp.plugins_missing_locally,
                columns=("Plugin", "Developer", "Format", "Version on Other"),
                row_fn=lambda d: (d.name, d.developer, d.fmt, d.other_version),
                accent=RED,
                icon=_SECTION_ICONS["missing_locally"],
                grid_row=row,
            )
            self._result_sections.append(section)
            row += 1

        if cmp.plugins_missing_on_other:
            section = self._make_plugin_section(
                title=f"Missing on {other_name}  ({len(cmp.plugins_missing_on_other)})",
                subtitle=f"Present on {local_name}, not on {other_name}",
                items=cmp.plugins_missing_on_other,
                columns=("Plugin", "Developer", "Format", "Local Version"),
                row_fn=lambda d: (d.name, d.developer, d.fmt, d.local_version),
                accent=YELLOW,
                icon=_SECTION_ICONS["missing_on_other"],
                grid_row=row,
            )
            self._result_sections.append(section)
            row += 1

        if cmp.plugin_version_diffs:
            section = self._make_plugin_section(
                title=f"Version Differences  ({len(cmp.plugin_version_diffs)})",
                subtitle="Same plugin and format, different installed versions",
                items=cmp.plugin_version_diffs,
                columns=("Plugin", "Developer", "Format", f"Local ({local_name})", f"Other ({other_name})"),
                row_fn=lambda d: (d.name, d.developer, d.fmt, d.local_version, d.other_version),
                accent=TEAL,
                icon=_SECTION_ICONS["version_diff"],
                grid_row=row,
            )
            self._result_sections.append(section)
            row += 1

        if cmp.plugin_format_diffs:
            section = self._make_plugin_section(
                title=f"Format Differences  ({len(cmp.plugin_format_diffs)})",
                subtitle="Same plugin name, different formats installed",
                items=cmp.plugin_format_diffs,
                columns=("Plugin", "Developer", f"Local ({local_name})", f"Other ({other_name})"),
                row_fn=lambda d: (d.name, d.developer, d.local_version, d.other_version),
                accent=ORANGE,
                icon=_SECTION_ICONS["format_diff"],
                grid_row=row,
                extra_col=("Formats", lambda d: d.fmt),
            )
            self._result_sections.append(section)
            row += 1

        if cmp.software_diffs:
            section = self._make_software_section(
                cmp.software_diffs, local_name, other_name, grid_row=row
            )
            self._result_sections.append(section)
            row += 1

        if cmp.hardware_diffs:
            section = self._make_hardware_section(
                cmp.hardware_diffs, local_name, other_name, grid_row=row
            )
            self._result_sections.append(section)
            row += 1

        if not cmp.has_differences:
            no_diff = ctk.CTkLabel(
                self._results_scroll,
                text="✓  No differences found — the two machines match perfectly!",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=GREEN,
            )
            no_diff.grid(row=0, column=0, pady=40)
            self._result_sections.append(no_diff)  # type: ignore[arg-type]

        total = cmp.total_differences
        self._set_status(
            f"Comparison complete — {total} difference{'s' if total != 1 else ''} found  "
            f"({local_name}  vs  {other_name})"
        )

    # ── Section builders ──────────────────────────────────────────────────────

    def _make_plugin_section(
        self,
        title: str,
        subtitle: str,
        items: list,
        columns: tuple,
        row_fn: Callable,
        accent: str,
        icon: str,
        grid_row: int,
        extra_col: tuple | None = None,
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self._results_scroll,
            fg_color=BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        card.grid(row=grid_row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            hdr,
            text=f"{icon}  {title}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=accent,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            hdr,
            text=subtitle,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        all_cols = list(columns)
        if extra_col:
            all_cols.insert(2, extra_col[0])

        tree = self._make_tree(card, all_cols, grid_row=1)

        for item in items:
            vals = list(row_fn(item))
            if extra_col:
                vals.insert(2, extra_col[1](item))
            tree.insert("", "end", values=tuple(vals))

        return card

    def _make_software_section(
        self, diffs: list, local_name: str, other_name: str, grid_row: int
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self._results_scroll,
            fg_color=BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        card.grid(row=grid_row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            hdr,
            text=f"♬  Software Differences  ({len(diffs)})",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=ACCENT,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            hdr,
            text="DAWs, plugin managers, and other music apps",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        cols = ("Application", "Category", "Status", f"Local ({local_name})", f"Other ({other_name})")
        tree = self._make_tree(card, list(cols), grid_row=1)

        label_map = {
            "missing_locally":  "Only on other",
            "missing_on_other": "Only local",
            "version_diff":     "Version diff",
        }
        for d in diffs:
            tree.insert("", "end", values=(
                d.name,
                d.category,
                label_map.get(d.diff_type, d.diff_type),
                d.local_version or "—",
                d.other_version or "—",
            ))

        return card

    def _make_hardware_section(
        self, diffs: list, local_name: str, other_name: str, grid_row: int
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            self._results_scroll,
            fg_color=BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        card.grid(row=grid_row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            hdr,
            text=f"⬢  Hardware Differences  ({len(diffs)})",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=ORANGE,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            hdr,
            text="Audio interfaces, MIDI devices, and studio USB gear",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        cols = ("Device", "Vendor", "Type", "Present On")
        tree = self._make_tree(card, list(cols), grid_row=1)

        for d in diffs:
            present = local_name if d.diff_type == "missing_on_other" else other_name
            tree.insert("", "end", values=(
                d.name, d.vendor, d.device_type, present,
            ))

        return card

    # ── Shared treeview factory ───────────────────────────────────────────────

    def _make_tree(
        self,
        parent: ctk.CTkFrame,
        columns: list[str],
        grid_row: int,
    ) -> ttk.Treeview:
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Snapshot.Treeview",
            background=BG_TABLE,
            foreground=TEXT_PRIMARY,
            fieldbackground=BG_TABLE,
            borderwidth=0,
            rowheight=28,
            font=("SF Pro Text", 12),
        )
        style.configure(
            "Snapshot.Treeview.Heading",
            background=BG_CARD,
            foreground=TEXT_MUTED,
            borderwidth=0,
            font=("SF Pro Text", 11),
        )
        style.map("Snapshot.Treeview", background=[("selected", BG_TABLE_SEL)])

        col_ids = [f"c{i}" for i in range(len(columns))]

        frame = tk.Frame(parent, bg=BG_TABLE)
        frame.grid(row=grid_row, column=0, sticky="ew", padx=16, pady=(4, 14))
        frame.grid_columnconfigure(0, weight=1)

        vsb = ttk.Scrollbar(frame, orient="vertical")
        vsb.grid(row=0, column=1, sticky="ns")

        tree = ttk.Treeview(
            frame,
            columns=col_ids,
            show="headings",
            style="Snapshot.Treeview",
            yscrollcommand=vsb.set,
            height=min(len(columns) * 2 + 4, 12),
        )
        tree.grid(row=0, column=0, sticky="ew")
        vsb.configure(command=tree.yview)

        col_width = max(80, 900 // len(columns))
        for cid, cname in zip(col_ids, columns):
            tree.heading(cid, text=cname)
            tree.column(cid, width=col_width, minwidth=60, stretch=True)

        return tree

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _clear_result_sections(self) -> None:
        for widget in self._result_sections:
            try:
                widget.grid_remove()
                widget.destroy()
            except Exception:
                pass
        self._result_sections.clear()
        if self._placeholder_lbl.winfo_exists():
            self._placeholder_lbl.grid_remove()

    def _set_status(self, msg: str) -> None:
        self._status_text.set(msg)


# ── Snapshot picker dialog ────────────────────────────────────────────────────

class _SnapshotPickerDialog(ctk.CTkToplevel):
    """Modal dialog to select a previously saved snapshot."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        paths: list[Path],
        callback: Callable[[Path], None],
    ):
        super().__init__(parent)
        self.title("Load Saved Snapshot")
        self.geometry("540x380")
        self.resizable(False, False)
        self.grab_set()

        self._paths = paths
        self._callback = callback
        self._selected: Path | None = None

        self._build(paths)

    def _build(self, paths: list[Path]) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text="Select a saved snapshot to import:",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_SECONDARY,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 8))

        frame = tk.Frame(self, bg=BG_TABLE)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        vsb = ttk.Scrollbar(frame, orient="vertical")
        vsb.grid(row=0, column=1, sticky="ns")

        self._listbox = tk.Listbox(
            frame,
            bg=BG_TABLE,
            fg=TEXT_PRIMARY,
            selectbackground=BG_TABLE_SEL,
            selectforeground=TEXT_PRIMARY,
            font=("SF Pro Text", 12),
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=vsb.set,
            activestyle="none",
        )
        self._listbox.grid(row=0, column=0, sticky="nsew")
        vsb.configure(command=self._listbox.yview)

        for p in paths:
            self._listbox.insert("end", p.name)

        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=16)

        ctk.CTkButton(
            btn_bar,
            text="Load",
            width=100,
            height=36,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._load,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_bar,
            text="Cancel",
            width=90,
            height=36,
            corner_radius=8,
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_SECONDARY,
            border_width=1,
            border_color=BORDER_BRIGHT,
            font=ctk.CTkFont(size=13),
            command=self.destroy,
        ).pack(side="right")

        self._listbox.bind("<Double-Button-1>", lambda _: self._load())

    def _load(self) -> None:
        sel = self._listbox.curselection()
        if not sel:
            return
        path = self._paths[sel[0]]
        self.destroy()
        self._callback(path)
