"""
MIDI Devices view — enumerate and inspect MIDI devices detected on macOS.

Read-only. No routing changes, no MIDI message monitoring.
Actions: Refresh, Copy Device Info, Export CSV.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable

import customtkinter as ctk

from app.core.midi_scanner import MidiDevice, MidiScanResult, export_csv, scan_midi_devices

# ── Design tokens ─────────────────────────────────────────────────────────────
BG_CARD          = "#131720"
BG_TABLE         = "#0D1020"
BG_TABLE_SEL     = "#1B2848"
ACCENT           = "#2DD4BF"   # teal — MIDI identity colour
ACCENT_HOVER     = "#5DE8D5"
ACCENT_DIM       = "#0F2C2A"
TEXT_PRIMARY     = "#EEF0F8"
TEXT_SECONDARY   = "#94A3B8"
TEXT_MUTED       = "#4B5870"
BORDER           = "#1C2038"
BORDER_BRIGHT    = "#242B48"
GREEN            = "#4ADE80"
ORANGE           = "#F59E0B"
RED              = "#F87171"
PURPLE           = "#A78BFA"
BLUE             = "#6C8EF5"

_CONN_COLORS: dict[str, str] = {
    "USB":         BLUE,
    "Bluetooth":   PURPLE,
    "Network":     ORANGE,
    "Virtual":     TEXT_SECONDARY,
    "Thunderbolt": ACCENT,
    "MIDI":        TEXT_SECONDARY,
    "Unknown":     TEXT_MUTED,
}

_COL_DEFS: list[tuple[str, str, int]] = [
    ("name",       "Device Name",    200),
    ("manu",       "Manufacturer",   160),
    ("inputs",     "Inputs",          70),
    ("outputs",    "Outputs",         70),
    ("status",     "Status",          80),
    ("connection", "Connection",     120),
]


class MidiDevicesView(ctk.CTkFrame):
    """Detect and display all MIDI devices reported by macOS."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_ready: Callable[[list[MidiDevice]], None] | None = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._devices: list[MidiDevice] = []
        self._scanning = False
        self._on_ready = on_ready

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_header()
        self._build_toolbar()
        self._build_summary()
        self._build_table()
        self._build_statusbar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(28, 0))

        ctk.CTkLabel(
            header,
            text="MIDI Devices",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Detect and inspect MIDI devices via CoreMIDI — read-only",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(3, 0))

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=30, pady=(18, 10))

        self._refresh_btn = ctk.CTkButton(
            bar,
            text="  ♩  Refresh",
            width=145,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#0D1820",
            command=self._start_scan,
        )
        self._refresh_btn.pack(side="left")

        self._copy_btn = ctk.CTkButton(
            bar,
            text="Copy Device Info",
            width=155,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_SECONDARY,
            border_width=1,
            border_color=BORDER_BRIGHT,
            command=self._copy_device_info,
            state="disabled",
        )
        self._copy_btn.pack(side="left", padx=(10, 0))

        self._export_btn = ctk.CTkButton(
            bar,
            text="Export CSV",
            width=125,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13),
            fg_color=BG_CARD,
            hover_color=BORDER_BRIGHT,
            text_color=TEXT_SECONDARY,
            border_width=1,
            border_color=BORDER_BRIGHT,
            command=self._export_csv,
            state="disabled",
        )
        self._export_btn.pack(side="left", padx=(10, 0))

    def _build_summary(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 12))

        self._stat_total   = self._stat_card(row, "TOTAL DEVICES", "—", TEXT_PRIMARY)
        self._stat_online  = self._stat_card(row, "ONLINE",         "—", GREEN)
        self._stat_offline = self._stat_card(row, "OFFLINE",        "—", ORANGE)
        self._stat_inputs  = self._stat_card(row, "TOTAL INPUTS",   "—", BLUE)
        self._stat_outputs = self._stat_card(row, "TOTAL OUTPUTS",  "—", PURPLE)

    @staticmethod
    def _stat_card(
        parent: ctk.CTkFrame,
        label: str,
        value: str,
        value_color: str,
    ) -> ctk.CTkLabel:
        card = ctk.CTkFrame(
            parent, fg_color=BG_CARD, corner_radius=10,
            border_width=1, border_color=BORDER,
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
        lbl = ctk.CTkLabel(
            inner,
            text=value,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=value_color,
        )
        lbl.pack(anchor="w")
        return lbl

    def _build_table(self) -> None:
        container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=12,
            border_width=1, border_color=BORDER,
        )
        container.grid(row=3, column=0, sticky="nsew", padx=30, pady=(0, 0))
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            container,
            text="DETECTED MIDI DEVICES",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        table_wrap = ctk.CTkFrame(container, fg_color=BG_TABLE, corner_radius=8)
        table_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        cols = [c[0] for c in _COL_DEFS]
        self._tree = ttk.Treeview(
            table_wrap,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=14,
        )

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Midi.Treeview",
            background=BG_TABLE,
            fieldbackground=BG_TABLE,
            foreground=TEXT_PRIMARY,
            borderwidth=0,
            rowheight=30,
            font=("SF Pro Text", 11),
        )
        style.configure(
            "Midi.Treeview.Heading",
            background=BG_CARD,
            foreground=TEXT_MUTED,
            borderwidth=0,
            font=("SF Pro Text", 10, "bold"),
        )
        style.map("Midi.Treeview", background=[("selected", BG_TABLE_SEL)])
        self._tree.configure(style="Midi.Treeview")

        for col_id, title, width in _COL_DEFS:
            anchor = "center" if col_id in ("inputs", "outputs", "status") else "w"
            self._tree.heading(col_id, text=title)
            self._tree.column(col_id, width=width, minwidth=50, anchor=anchor)

        # Tag colours for status & connection
        self._tree.tag_configure("online",    foreground=GREEN)
        self._tree.tag_configure("offline",   foreground=RED)
        self._tree.tag_configure("even",      background=BG_TABLE)
        self._tree.tag_configure("odd",       background="#0F1424")

        scroll = ctk.CTkScrollbar(table_wrap, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 8))

        self._empty_label = ctk.CTkLabel(
            container,
            text="Press  ♩ Refresh  to detect connected MIDI devices",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=2, column=0, pady=(0, 16))

        self._error_label = ctk.CTkLabel(
            container,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=ORANGE,
            wraplength=760,
            justify="left",
        )
        self._error_label.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 10))
        self._error_label.grid_remove()

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=4, column=0, sticky="ew", padx=30, pady=(8, 22))
        bar.grid_columnconfigure(0, weight=1)

        self._status_var = tk.StringVar(value="Ready — macOS CoreMIDI scan")
        ctk.CTkLabel(
            bar,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self._source_var = tk.StringVar(value="")
        ctk.CTkLabel(
            bar,
            textvariable=self._source_var,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
            anchor="e",
        ).grid(row=0, column=1, sticky="e")

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._refresh_btn.configure(state="disabled", text="  ♩  Scanning…")
        self._copy_btn.configure(state="disabled")
        self._export_btn.configure(state="disabled")
        self._error_label.grid_remove()
        self._clear_table()
        self._empty_label.configure(text="Querying CoreMIDI…")
        self._empty_label.grid()
        self._status_var.set("Scanning via CoreMIDI…")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        result = scan_midi_devices(debug_log=False)
        self.after(0, self._on_scan_complete, result)

    def _on_scan_complete(self, result: MidiScanResult) -> None:
        self._scanning = False
        self._refresh_btn.configure(state="normal", text="  ♩  Refresh")
        self._devices = result.devices

        if self._on_ready:
            self._on_ready(self._devices)

        # Update stat cards
        self._stat_total.configure(text=str(len(result.devices)))
        self._stat_online.configure(text=str(result.online_count))
        self._stat_offline.configure(text=str(result.offline_count))
        self._stat_inputs.configure(text=str(result.total_inputs))
        self._stat_outputs.configure(text=str(result.total_outputs))

        if result.errors:
            self._error_label.configure(text="Warnings: " + "; ".join(result.errors))
            self._error_label.grid()

        if result.devices:
            self._populate_table(result.devices)
            self._empty_label.grid_remove()
            self._copy_btn.configure(state="normal")
            self._export_btn.configure(state="normal")

            # Source label: CoreMIDI or system_profiler
            sources = {d.source for d in result.devices}
            self._source_var.set("Source: " + ", ".join(sorted(sources)))

            self._status_var.set(
                f"Found {len(result.devices)} device(s) — "
                f"{result.online_count} online, {result.offline_count} offline"
            )
        else:
            self._clear_table()
            self._empty_label.configure(text="No MIDI devices detected.")
            self._empty_label.grid()
            self._status_var.set("No MIDI devices found")
            self._source_var.set("")

    def _clear_table(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)

    def _populate_table(self, devices: list[MidiDevice]) -> None:
        self._clear_table()
        for i, dev in enumerate(devices):
            tags: list[str] = ["even" if i % 2 == 0 else "odd"]
            if dev.is_online:
                tags.append("online")
            else:
                tags.append("offline")
            self._tree.insert("", "end", values=dev.row, tags=tuple(tags))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _copy_device_info(self) -> None:
        if not self._devices:
            return

        lines: list[str] = ["MIDI Devices — Bakkis Studio Manager", ""]
        for d in self._devices:
            lines.append(f"Device:      {d.name}")
            lines.append(f"Manufacturer: {d.manufacturer or '—'}")
            lines.append(f"Inputs:       {d.inputs_label}")
            lines.append(f"Outputs:      {d.outputs_label}")
            lines.append(f"Status:       {d.status_label}")
            lines.append(f"Connection:   {d.connection_type}")
            lines.append(f"Source:       {d.source}")
            lines.append("")

        text = "\n".join(lines).strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status_var.set(f"Copied info for {len(self._devices)} device(s) to clipboard")

    def _export_csv(self) -> None:
        if not self._devices:
            return
        try:
            path = export_csv(self._devices)
            self._status_var.set(f"Exported → {path}")
            messagebox.showinfo(
                "Export Complete",
                f"MIDI device list saved to:\n{path}",
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001
            self._status_var.set(f"Export failed: {exc}")
            messagebox.showerror("Export Failed", str(exc), parent=self)
