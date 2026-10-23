"""
Hardware Inventory — connected studio hardware detection (macOS).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

import customtkinter as ctk

from app.core.hardware_scanner import HardwareDevice, HardwareScanResult, scan_hardware

# ── Design System ─────────────────────────────────────────────────────────────
BG_CARD          = "#131720"
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
TEAL             = "#2DD4BF"
ORANGE           = "#F59E0B"
RED              = "#F87171"

_TYPE_COLORS: dict[str, str] = {
    "Audio Interface": TEAL,
    "MIDI Device":     ACCENT,
    "USB Device":      ORANGE,
    "Unknown":         TEXT_MUTED,
}


class HardwareInventoryView(ctk.CTkFrame):
    """Scan and list connected physical studio hardware."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_hardware_ready: Callable[[list[HardwareDevice]], None] | None = None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._devices: list[HardwareDevice] = []
        self._scanning = False
        self._last_error: str | None = None
        self._on_hardware_ready = on_hardware_ready

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
            text="Hardware Inventory",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Detect connected audio interfaces, MIDI devices, and studio USB gear",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(3, 0))

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=30, pady=(18, 10))

        self._scan_btn = ctk.CTkButton(
            bar,
            text="  ⬢  Scan Hardware",
            width=175,
            height=40,
            corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._start_scan,
        )
        self._scan_btn.pack(side="left")

    def _build_summary(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 8))

        card = ctk.CTkFrame(
            row, fg_color=BG_CARD, corner_radius=10,
            border_width=1, border_color=BORDER,
        )
        card.pack(side="left")

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=16, pady=10)

        ctk.CTkLabel(
            inner,
            text="CONNECTED DEVICES",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        ).pack(anchor="w")

        self._count_lbl = ctk.CTkLabel(
            inner,
            text="—",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self._count_lbl.pack(anchor="w")

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
            text="DETECTED HARDWARE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        table_wrap = ctk.CTkFrame(container, fg_color=BG_TABLE, corner_radius=8)
        table_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_wrap.grid_columnconfigure(0, weight=1)
        table_wrap.grid_rowconfigure(0, weight=1)

        cols = ("name", "vendor", "type", "connection", "source", "status")
        self._tree = ttk.Treeview(
            table_wrap,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=12,
        )
        headings = {
            "name": ("Name", 180),
            "vendor": ("Vendor", 140),
            "type": ("Type", 120),
            "connection": ("Connection", 100),
            "source": ("Source", 160),
            "status": ("Status", 90),
        }
        for col, (title, width) in headings.items():
            self._tree.heading(col, text=title)
            self._tree.column(col, width=width, minwidth=60, anchor="w")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=BG_TABLE,
            fieldbackground=BG_TABLE,
            foreground=TEXT_PRIMARY,
            borderwidth=0,
            rowheight=28,
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

        scroll = ctk.CTkScrollbar(table_wrap, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 8))

        self._empty_label = ctk.CTkLabel(
            container,
            text="Press  ⬢ Scan Hardware  to detect connected studio gear",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_label.grid(row=2, column=0, pady=(0, 16))

        self._error_label = ctk.CTkLabel(
            container,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=RED,
            wraplength=700,
            justify="left",
        )
        self._error_label.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 12))
        self._error_label.grid_remove()

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        bar.grid(row=4, column=0, sticky="ew", padx=30, pady=(8, 22))
        bar.grid_columnconfigure(0, weight=1)

        self._status_var = tk.StringVar(value="Ready — macOS hardware scan")
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
        self._last_error = None
        self._scan_btn.configure(state="disabled", text="  ⬢  Scanning…")
        self._error_label.grid_remove()
        self._clear_table()
        self._empty_label.configure(text="Scanning connected hardware…")
        self._empty_label.grid()
        self._status_var.set("Running system_profiler and Core MIDI…")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        result = scan_hardware(debug_log=True)
        self.after(0, self._on_scan_complete, result)

    def _on_scan_complete(self, result: HardwareScanResult) -> None:
        self._scanning = False
        self._scan_btn.configure(state="normal", text="  ⬢  Scan Hardware")
        self._devices = result.devices
        self._last_error = "; ".join(result.errors) if result.errors else None

        if self._on_hardware_ready is not None:
            self._on_hardware_ready(self._devices)

        self._count_lbl.configure(text=str(result.connected_count))

        if result.errors:
            self._error_label.configure(
                text="Warnings: " + self._last_error,
            )
            self._error_label.grid()

        if result.devices:
            self._populate_table(result.devices)
            self._empty_label.grid_remove()
            self._status_var.set(
                f"Scan complete — {result.connected_count} device(s). "
                + (result.status[-1] if result.status else "")
            )
        else:
            self._clear_table()
            if result.errors and not any(
                "empty" in s.lower() or "0 device" in s.lower() for s in result.status
            ):
                msg = "Scan finished but no studio hardware was detected."
            else:
                msg = "No connected studio hardware detected."
            self._empty_label.configure(text=msg)
            self._empty_label.grid()
            self._status_var.set(
                result.status[-1] if result.status else "No devices found"
            )

    def _clear_table(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)

    def _populate_table(self, devices: list[HardwareDevice]) -> None:
        self._clear_table()
        for i, dev in enumerate(devices):
            tag = "even" if i % 2 == 0 else "odd"
            self._tree.insert("", "end", values=dev.row, tags=(tag,))
