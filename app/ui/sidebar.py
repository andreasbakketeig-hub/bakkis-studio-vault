"""
Sidebar navigation panel.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

# ── Palette (re-used across the app) ─────────────────────────────────────────
BG_SIDEBAR = "#0F1117"
BG_NAV_HOVER = "#1C1F2E"
BG_NAV_ACTIVE = "#1E2235"
ACCENT = "#6C8EF5"
TEXT_PRIMARY = "#E8EAF0"
TEXT_MUTED = "#6B7280"

NAV_ITEMS: list[tuple[str, str, str]] = [
    ("plugins",            "◈",  "Plug-in Scanner"),
    ("format_analysis",    "⊞",  "Format Analysis"),
    ("plugin_health",      "◎",  "Plugin Health"),
    ("cleanup",            "⊘",  "Cleanup Recommendations"),
    ("music_software",     "♬",  "Music Software"),
    ("migration",          "⇄",  "Migration Assistant"),
    ("licenses",           "⬡",  "License Vault"),
    ("hardware",           "⬢",  "Hardware Inventory"),
    ("midi",               "♩",  "MIDI Devices"),
    ("mapper",             "⬡",  "Studio Mapper"),
]


class Sidebar(ctk.CTkFrame):
    """Vertical navigation rail on the left edge of the window."""

    def __init__(
        self,
        parent: ctk.CTk,
        on_navigate: Callable[[str], None],
        **kwargs,
    ):
        super().__init__(
            parent,
            width=220,
            corner_radius=0,
            fg_color=BG_SIDEBAR,
            **kwargs,
        )
        self._on_navigate = on_navigate
        self._active_key: str = ""
        self._buttons: dict[str, ctk.CTkButton] = {}

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_rowconfigure(99, weight=1)  # push footer down

        # Logo / title block
        logo_frame = ctk.CTkFrame(self, fg_color="transparent")
        logo_frame.grid(row=0, column=0, padx=20, pady=(28, 20), sticky="ew")

        ctk.CTkLabel(
            logo_frame,
            text="BAKKIS",
            font=ctk.CTkFont(family="SF Pro Display", size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            logo_frame,
            text="STUDIO VAULT",
            font=ctk.CTkFont(family="SF Pro Display", size=10, weight="normal"),
            text_color=ACCENT,
            anchor="w",
        ).pack(anchor="w")

        # Divider
        ctk.CTkFrame(self, height=1, fg_color="#1C1F2E").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 12)
        )

        # Section label
        ctk.CTkLabel(
            self,
            text="MODULES",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 6))

        # Nav buttons
        for i, (key, icon, label) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                self,
                text=f"  {icon}   {label}",
                anchor="w",
                height=40,
                corner_radius=8,
                fg_color="transparent",
                hover_color=BG_NAV_HOVER,
                text_color=TEXT_MUTED,
                font=ctk.CTkFont(size=13),
                command=lambda k=key: self._navigate(k),
            )
            btn.grid(row=3 + i, column=0, sticky="ew", padx=10, pady=2)
            self._buttons[key] = btn

        # Footer version label
        ctk.CTkLabel(
            self,
            text="v0.1.0",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
        ).grid(row=100, column=0, pady=(0, 16))

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate(self, key: str) -> None:
        self._set_active(key)
        self._on_navigate(key)

    def _set_active(self, key: str) -> None:
        if self._active_key and self._active_key in self._buttons:
            prev = self._buttons[self._active_key]
            prev.configure(fg_color="transparent", text_color=TEXT_MUTED)

        self._active_key = key
        btn = self._buttons[key]
        btn.configure(fg_color=BG_NAV_ACTIVE, text_color=TEXT_PRIMARY)

    def activate(self, key: str) -> None:
        """Programmatically mark *key* as active without firing the callback."""
        self._set_active(key)
