"""
Generic "coming soon" placeholder for future modules.
"""

from __future__ import annotations

import customtkinter as ctk

TEXT_PRIMARY = "#EEF0F8"
TEXT_SECONDARY = "#94A3B8"
TEXT_MUTED   = "#4B5870"
ACCENT       = "#6C8EF5"
ACCENT_DIM   = "#1A2545"
BG_BADGE     = "#161B28"
BORDER       = "#1C2038"
BORDER_BRIGHT = "#242B48"

_MODULE_META: dict[str, tuple[str, str, str, str]] = {
    "licenses": (
        "⬡",
        "License Vault",
        "Store, organise, and retrieve plug-in serial numbers\n"
        "and activation details — all in one secure place.",
        "#A855F7",
    ),
    "midi": (
        "♩",
        "MIDI Devices",
        "Enumerate connected MIDI devices, inspect port\n"
        "assignments, and test MIDI I/O in real time.",
        "#2DD4BF",
    ),
    "mapper": (
        "⋈",
        "Studio Mapper",
        "Visual patch-bay and routing diagram for your\n"
        "entire studio signal chain.",
        "#60A5FA",
    ),
    "settings": (
        "⚙",
        "Settings",
        "Configure DAW profiles, preferred formats,\n"
        "scan paths, and application preferences.",
        "#94A3B8",
    ),
}


class ComingSoonView(ctk.CTkFrame):
    """Placeholder view shown for modules not yet implemented."""

    def __init__(self, parent: ctk.CTkFrame, module_key: str, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        meta = _MODULE_META.get(module_key)
        if meta:
            icon, title, description, color = meta
        else:
            icon  = "◈"
            title = module_key.replace("_", " ").title()
            description = "This module is under construction."
            color = ACCENT

        self._build(icon, title, description, color)

    def _build(self, icon: str, title: str, description: str, color: str) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        center = ctk.CTkFrame(self, fg_color="transparent")
        center.grid(row=0, column=0)

        # Icon badge
        icon_card = ctk.CTkFrame(
            center, width=72, height=72, corner_radius=20,
            fg_color=ACCENT_DIM, border_width=1, border_color=BORDER_BRIGHT,
        )
        icon_card.pack(pady=(0, 20))
        icon_card.pack_propagate(False)
        ctk.CTkLabel(
            icon_card, text=icon,
            font=ctk.CTkFont(size=28), text_color=color,
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            center,
            text=title,
            font=ctk.CTkFont(family="SF Pro Display", size=24, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack()

        ctk.CTkLabel(
            center,
            text=description,
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
            justify="center",
        ).pack(pady=(10, 28))

        badge = ctk.CTkFrame(
            center, fg_color=BG_BADGE, corner_radius=20,
            border_width=1, border_color=BORDER,
        )
        badge.pack()
        ctk.CTkLabel(
            badge,
            text="  Coming soon  ",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=ACCENT,
        ).pack(padx=16, pady=7)
