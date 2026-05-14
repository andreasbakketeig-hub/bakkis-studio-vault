"""
Generic "coming soon" placeholder for future modules.
"""

from __future__ import annotations

import customtkinter as ctk

TEXT_PRIMARY = "#E8EAF0"
TEXT_MUTED = "#6B7280"
ACCENT = "#6C8EF5"
BG_BADGE = "#1C1F2E"

_MODULE_META: dict[str, tuple[str, str, str]] = {
    "licenses": (
        "⬡",
        "License Vault",
        "Store, organise, and retrieve plug-in serial numbers\nand activation details — all in one secure place.",
    ),
    "hardware": (
        "⬢",
        "Hardware Inventory",
        "Track audio interfaces, controllers, synthesisers,\nand every other piece of studio hardware you own.",
    ),
    "midi": (
        "♩",
        "MIDI Devices",
        "Enumerate connected MIDI devices, inspect port\nassignments, and test MIDI I/O in real time.",
    ),
    "mapper": (
        "⬡",
        "Studio Mapper",
        "Visual patch-bay and routing diagram for your\nentire studio signal chain.",
    ),
}


class ComingSoonView(ctk.CTkFrame):
    """Placeholder view shown for modules not yet implemented."""

    def __init__(self, parent: ctk.CTkFrame, module_key: str, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        icon, title, description = _MODULE_META.get(
            module_key,
            ("◈", module_key.replace("_", " ").title(), "This module is under construction."),
        )
        self._build(icon, title, description)

    def _build(self, icon: str, title: str, description: str) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        center = ctk.CTkFrame(self, fg_color="transparent")
        center.grid(row=0, column=0)

        ctk.CTkLabel(
            center,
            text=icon,
            font=ctk.CTkFont(size=48),
            text_color=ACCENT,
        ).pack(pady=(0, 16))

        ctk.CTkLabel(
            center,
            text=title,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack()

        ctk.CTkLabel(
            center,
            text=description,
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
            justify="center",
        ).pack(pady=(10, 24))

        badge = ctk.CTkFrame(center, fg_color=BG_BADGE, corner_radius=20)
        badge.pack()
        ctk.CTkLabel(
            badge,
            text="  Coming soon  ",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=ACCENT,
        ).pack(padx=16, pady=6)
