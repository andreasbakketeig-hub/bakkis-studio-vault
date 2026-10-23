"""
Audio Devices — read-only view of all CoreAudio devices detected on macOS.

Shows device name, input/output channel counts, default I/O assignment,
manufacturer, transport type, and connection status.

Actions: Refresh · Copy Device Info · Export CSV
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from app.core.audio_device_scanner import (
    AudioDevice,
    AudioScanResult,
    scan_audio_devices,
    export_csv,
)

# ── Design System ──────────────────────────────────────────────────────────────
BG_CARD          = "#131720"
BG_TABLE         = "#0D1020"
BG_TABLE_ROW     = "#131720"
BG_TABLE_ROW_ALT = "#161B28"
BG_TABLE_SEL     = "#1B2848"
ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
ACCENT_DIM       = "#1A2545"
TEXT_PRIMARY     = "#EEF0F8"
TEXT_SECONDARY   = "#94A3B8"
TEXT_MUTED       = "#4B5870"
BORDER           = "#1C2038"
BORDER_BRIGHT    = "#242B48"
GREEN            = "#4ADE80"
TEAL             = "#2DD4BF"
ORANGE           = "#F59E0B"
RED              = "#F87171"

# Transport → accent colour for the tag dot in the name column
_TRANSPORT_COLORS: dict[str, str] = {
    "Built-in":   TEXT_MUTED,
    "USB":        TEAL,
    "Bluetooth":  ACCENT,
    "Thunderbolt": GREEN,
    "FireWire":   ORANGE,
    "Virtual":    TEXT_SECONDARY,
    "Aggregate":  TEXT_SECONDARY,
    "HDMI":       TEXT_SECONDARY,
    "DisplayPort": TEXT_SECONDARY,
}

# Column definitions: (id, heading, initial_width, min_width, anchor)
_COLUMNS: list[tuple[str, str, int, int, str]] = [
    ("name",        "Device Name",    220, 120, "w"),
    ("inputs",      "Input Ch",        72,  50, "center"),
    ("outputs",     "Output Ch",       72,  50, "center"),
    ("default_in",  "Default In",      82,  60, "center"),
    ("default_out", "Default Out",     82,  60, "center"),
    ("manufacturer","Manufacturer",   150,  80, "w"),
    ("transport",   "Transport",      110,  70, "w"),
    ("status",      "Status",          90,  60, "w"),
]


class AudioDevicesView(ctk.CTkFrame):
    """Read-only view listing every CoreAudio device registered with macOS."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_devices_ready: Callable[[list[AudioDevice]], None] | None = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._devices: list[AudioDevice] = []
        self._scanning = False
        self._last_result: AudioScanResult | None = None
        self._on_devices_ready = on_devices_ready

        self._build()
        # Scan automatically on first load
        self.after(200, self._start_scan)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_summary()
        self._build_table()
        self._build_statusbar()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="Audio Devices",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="All CoreAudio devices detected on this Mac — read-only, no audio monitoring",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(3, 0))

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=30, pady=(18, 10))

        self._refresh_btn = ctk.CTkButton(
            bar,
            text="  ◉  Refresh",
            width=145,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._start_scan,
        )
        self._refresh_btn.pack(side="left")

        self._copy_btn = ctk.CTkButton(
            bar,
            text="  ⎘  Copy Device Info",
            width=175,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13),
            fg_color=BG_CARD,
            hover_color=ACCENT_DIM,
            text_color=TEXT_SECONDARY,
            border_width=1,
            border_color=BORDER_BRIGHT,
            command=self._copy_selected,
            state="disabled",
        )
        self._copy_btn.pack(side="left", padx=(10, 0))

        self._export_btn = ctk.CTkButton(
            bar,
            text="  ↓  Export CSV",
            width=145,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13),
            fg_color=BG_CARD,
            hover_color=ACCENT_DIM,
            text_color=TEXT_SECONDARY,
            border_width=1,
            border_color=BORDER_BRIGHT,
            command=self._export_csv,
            state="disabled",
        )
        self._export_btn.pack(side="left", padx=(10, 0))

    # ── Summary strip ─────────────────────────────────────────────────────────

    def _build_summary(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 10))

        self._card_total   = self._make_stat_card(row, "TOTAL DEVICES", "—", TEXT_PRIMARY)
        self._card_inputs  = self._make_stat_card(row, "INPUT DEVICES", "—", TEAL)
        self._card_outputs = self._make_stat_card(row, "OUTPUT DEVICES", "—", GREEN)
        self._card_def_in  = self._make_stat_card(row, "DEFAULT INPUT", "—", ACCENT)
        self._card_def_out = self._make_stat_card(row, "DEFAULT OUTPUT", "—", ACCENT)

    @staticmethod
    def _make_stat_card(
        parent: ctk.CTkFrame,
        label: str,
        value: str,
        value_color: str,
    ) -> ctk.CTkLabel:
        card = ctk.CTkFrame(
            parent,
            fg_color=BG_CARD,
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
        )
        card.pack(side="left", padx=(0, 10))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=16, pady=10)

        ctk.CTkLabel(
            inner,
            text=label,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(anchor="w")

        val_lbl = ctk.CTkLabel(
            inner,
            text=value,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=value_color,
        )
        val_lbl.pack(anchor="w")
        return val_lbl

    # ── Table ─────────────────────────────────────────────────────────────────

    def _build_table(self) -> None:
        container = ctk.CTkFrame(
            self,
            fg_color=BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        container.grid(row=3, column=0, sticky="nsew", padx=30, pady=(0, 0))
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            container,
            text="DETECTED AUDIO DEVICES",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        table_wrap = ctk.CTkFrame(container, fg_color=BG_TABLE, corner_radius=8)
        table_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        col_ids = [c[0] for c in _COLUMNS]
        self._tree = ttk.Treeview(
            table_wrap,
            columns=col_ids,
            show="headings",
            selectmode="browse",
            height=12,
        )

        self._apply_treeview_style()

        for col_id, heading, width, minwidth, anchor in _COLUMNS:
            self._tree.heading(col_id, text=heading, anchor=anchor)
            self._tree.column(col_id, width=width, minwidth=minwidth, anchor=anchor)

        self._tree.tag_configure("even", background=BG_TABLE_ROW)
        self._tree.tag_configure("odd",  background=BG_TABLE_ROW_ALT)
        self._tree.tag_configure("default_io", foreground=ACCENT)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        scroll = ctk.CTkScrollbar(table_wrap, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 8))

        self._empty_label = ctk.CTkLabel(
            container,
            text="Scanning CoreAudio devices…",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=2, column=0, pady=(0, 16))

    @staticmethod
    def _apply_treeview_style() -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=BG_TABLE,
            fieldbackground=BG_TABLE,
            foreground=TEXT_PRIMARY,
            borderwidth=0,
            rowheight=30,
            font=("SF Pro Text", 11),
        )
        style.configure(
            "Treeview.Heading",
            background=BG_CARD,
            foreground=TEXT_MUTED,
            borderwidth=0,
            font=("SF Pro Text", 10, "bold"),
        )
        style.map("Treeview", background=[("selected", BG_TABLE_SEL)])

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=4, column=0, sticky="ew", padx=30, pady=(8, 22))
        bar.grid_columnconfigure(0, weight=1)

        self._status_var = tk.StringVar(value="Ready — CoreAudio device scan")
        ctk.CTkLabel(
            bar,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

    # ── Scanning ──────────────────────────────────────────────────────────────

    def _start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._refresh_btn.configure(state="disabled", text="  ◉  Scanning…")
        self._copy_btn.configure(state="disabled")
        self._export_btn.configure(state="disabled")
        self._clear_table()
        self._empty_label.configure(text="Scanning CoreAudio devices…")
        self._empty_label.grid()
        self._status_var.set("Running system_profiler SPAudioDataType…")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        result = scan_audio_devices()
        self.after(0, self._on_scan_complete, result)

    def _on_scan_complete(self, result: AudioScanResult) -> None:
        self._scanning = False
        self._last_result = result
        self._devices = result.devices

        self._refresh_btn.configure(state="normal", text="  ◉  Refresh")

        if self._on_devices_ready is not None:
            self._on_devices_ready(self._devices)

        # Update summary cards
        self._card_total.configure(text=str(result.total))
        self._card_inputs.configure(text=str(result.input_count))
        self._card_outputs.configure(text=str(result.output_count))

        def_in  = result.default_input
        def_out = result.default_output
        self._card_def_in.configure(
            text=def_in.name if def_in else "—",
            font=ctk.CTkFont(size=11, weight="bold") if def_in else ctk.CTkFont(size=18, weight="bold"),
        )
        self._card_def_out.configure(
            text=def_out.name if def_out else "—",
            font=ctk.CTkFont(size=11, weight="bold") if def_out else ctk.CTkFont(size=18, weight="bold"),
        )

        if result.devices:
            self._populate_table(result.devices)
            self._empty_label.grid_remove()
            self._export_btn.configure(state="normal")
            self._status_var.set(
                f"Found {result.total} device(s) — "
                f"{result.input_count} input, {result.output_count} output"
            )
        else:
            self._clear_table()
            msg = result.errors[0] if result.errors else "No CoreAudio devices detected."
            self._empty_label.configure(text=msg)
            self._empty_label.grid()
            self._status_var.set(result.status[-1] if result.status else "No devices found")

    # ── Table helpers ─────────────────────────────────────────────────────────

    def _clear_table(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)

    def _populate_table(self, devices: list[AudioDevice]) -> None:
        self._clear_table()
        for i, dev in enumerate(devices):
            tags: list[str] = ["even" if i % 2 == 0 else "odd"]
            if dev.is_default_input or dev.is_default_output:
                tags.append("default_io")
            self._tree.insert("", "end", iid=str(i), values=dev.row, tags=tags)

    def _on_select(self, _event: tk.Event) -> None:
        selected = self._tree.selection()
        state = "normal" if selected else "disabled"
        self._copy_btn.configure(state=state)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _copy_selected(self) -> None:
        """Copy the selected device's info block to the system clipboard."""
        selection = self._tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        if idx >= len(self._devices):
            return
        device = self._devices[idx]
        try:
            self.clipboard_clear()
            self.clipboard_append(device.copy_text)
            self._status_var.set(f"Copied info for: {device.name}")
        except tk.TclError:
            messagebox.showerror("Copy Failed", "Could not access the clipboard.")

    def _export_csv(self) -> None:
        """Prompt for a save location and write all devices to CSV."""
        if not self._devices:
            return

        dest = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="bakkis_audio_devices.csv",
            title="Export Audio Devices",
        )
        if not dest:
            return

        try:
            path = export_csv(self._devices, dest_path=dest)
            self._status_var.set(f"Exported {len(self._devices)} device(s) → {path}")
            messagebox.showinfo("Export Complete", f"Audio devices exported to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))
