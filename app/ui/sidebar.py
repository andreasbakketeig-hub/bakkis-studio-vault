"""
Sidebar navigation panel — premium dark macOS-style design.

Layout
------
  Sidebar (CTkFrame, fixed width, fills window height)
  ├── Header  — brand name + collapse toggle  [fixed, never scrolls]
  ├── Nav     — CTkScrollableFrame            [expands, scrollable]
  │   ├── "MODULES" section label
  │   └── 12 nav items with left-accent indicator
  └── Footer  — logo + version               [fixed, never scrolls]

Collapse mode
-------------
  Toggle with the ‹ / › button in the header.
  Collapsed width = 52 px, shows icons only.
  Expanded width  = 218 px, shows icons + labels.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

import customtkinter as ctk

# ── Design tokens ─────────────────────────────────────────────────────────────
BG_SIDEBAR      = "#0C0F1C"
BG_NAV_HOVER    = "#141828"
BG_NAV_ACTIVE   = "#172044"
ACCENT          = "#6C8EF5"
TEXT_PRIMARY    = "#EEF0F8"
TEXT_MUTED      = "#4A5470"
SECTION_LABEL   = "#323A5A"
DIVIDER         = "#161C2E"
SCROLLBAR_TRACK = "#0E1120"
SCROLLBAR_THUMB = "#232840"
SCROLLBAR_HOVER = "#323A5A"

SIDEBAR_W   = 218   # expanded width
SIDEBAR_COL = 52    # collapsed width

# ── Navigation items  (key, icon, full label) ─────────────────────────────────
NAV_ITEMS: list[tuple[str, str, str]] = [
    ("studio_overview", "▣", "Studio Overview"),
    ("plugins",         "◈", "Plug-in Scanner"),
    ("format_analysis", "⊞", "Format Analysis"),
    ("plugin_health",   "◎", "Plugin Health"),
    ("cleanup",         "◯", "Cleanup Recommendations"),
    ("music_software",  "♬", "Music Software Scanner"),
    ("migration",       "⇄", "Migration Assistant"),
    ("licenses",        "⬡", "License Vault"),
    ("hardware",        "⬢", "Hardware Inventory"),
    ("midi",            "♩", "MIDI Devices"),
    ("mapper",          "⋈", "Studio Mapper"),
    ("settings",        "⚙", "Settings"),
]


class Sidebar(ctk.CTkFrame):
    """
    Vertical navigation rail.

    Public API
    ----------
    activate(key)   — highlight *key* without triggering navigation callback
    """

    def __init__(
        self,
        parent: ctk.CTk,
        on_navigate: Callable[[str], None],
        **kwargs,
    ):
        super().__init__(
            parent,
            width=SIDEBAR_W,
            corner_radius=0,
            fg_color=BG_SIDEBAR,
            **kwargs,
        )
        self._on_navigate  = on_navigate
        self._active_key   = ""
        self._collapsed    = False
        self._buttons:    dict[str, ctk.CTkButton] = {}
        self._indicators: dict[str, tk.Canvas]     = {}
        self._wrappers:   dict[str, tk.Frame]       = {}

        # Prevent the frame from shrinking to fit children;
        # parent grid gives it its actual height.
        self.grid_propagate(False)
        self._build()

    # ──────────────────────────────────────────────────────────────────────────
    # Build
    # ──────────────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Column 0 fills the whole sidebar width
        self.grid_columnconfigure(0, weight=1)
        # Row 1 (nav scroll) expands; header (0) and footer (2) are fixed
        self.grid_rowconfigure(1, weight=1)

        self._build_header(row=0)
        self._build_nav_scroll(row=1)
        self._build_footer(row=2)

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self, row: int) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=row, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        # Brand text (inside a sub-frame so pack works)
        brand = ctk.CTkFrame(hdr, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=20, pady=(24, 0))

        self._brand_title = ctk.CTkLabel(
            brand,
            text="BAKKIS",
            font=ctk.CTkFont(family="SF Pro Display", size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        self._brand_title.pack(anchor="w")

        self._brand_sub = ctk.CTkLabel(
            brand,
            text="STUDIO MANAGER",
            font=ctk.CTkFont(family="SF Pro Display", size=9, weight="bold"),
            text_color=ACCENT,
            anchor="w",
        )
        self._brand_sub.pack(anchor="w", pady=(1, 0))

        # Collapse toggle — top-right corner
        self._toggle_btn = ctk.CTkButton(
            hdr,
            text="‹",
            width=26,
            height=26,
            corner_radius=7,
            font=ctk.CTkFont(size=14),
            fg_color="transparent",
            hover_color=BG_NAV_HOVER,
            text_color=TEXT_MUTED,
            command=self._toggle_collapse,
        )
        self._toggle_btn.grid(row=0, column=1, sticky="ne", padx=(0, 10), pady=(26, 0))

        # Horizontal divider
        ctk.CTkFrame(hdr, height=1, fg_color=DIVIDER).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 0),
        )

    # ── Scrollable nav ────────────────────────────────────────────────────────

    def _build_nav_scroll(self, row: int) -> None:
        self._nav_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=BG_SIDEBAR,
            corner_radius=0,
            scrollbar_fg_color=SCROLLBAR_TRACK,
            scrollbar_button_color=SCROLLBAR_THUMB,
            scrollbar_button_hover_color=SCROLLBAR_HOVER,
        )
        self._nav_scroll.grid(row=row, column=0, sticky="nsew")
        # Make the inner scrollable column fill the sidebar width
        self._nav_scroll.grid_columnconfigure(0, weight=1)

        # ── Section label ─────────────────────────────────────────────────────
        self._section_lbl = ctk.CTkLabel(
            self._nav_scroll,
            text="MODULES",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=SECTION_LABEL,
            anchor="w",
        )
        self._section_lbl.grid(row=0, column=0, sticky="w", padx=22, pady=(14, 4))

        # ── Nav items ─────────────────────────────────────────────────────────
        for i, (key, icon, label) in enumerate(NAV_ITEMS):
            self._build_nav_item(key, icon, label, row=1 + i)

        # Small bottom padding inside scroll area
        ctk.CTkFrame(self._nav_scroll, height=10, fg_color="transparent").grid(
            row=1 + len(NAV_ITEMS), column=0,
        )

    def _build_nav_item(self, key: str, icon: str, label: str, row: int) -> None:
        """One nav row: [4 px accent strip] [CTkButton with icon + label]."""
        wrapper = tk.Frame(self._nav_scroll, bg=BG_SIDEBAR)
        wrapper.grid(row=row, column=0, sticky="ew", padx=0, pady=1)
        wrapper.grid_columnconfigure(1, weight=1)
        self._wrappers[key] = wrapper

        # Left accent strip — tk.Canvas so bg colour is reliable
        indicator = tk.Canvas(
            wrapper,
            width=4,
            height=35,
            bg=BG_SIDEBAR,
            highlightthickness=0,
        )
        indicator.grid(row=0, column=0, sticky="ns", padx=(7, 0))
        self._indicators[key] = indicator

        btn = ctk.CTkButton(
            wrapper,
            text=f"  {icon}   {label}",
            anchor="w",
            height=35,
            corner_radius=8,
            fg_color="transparent",
            hover_color=BG_NAV_HOVER,
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            command=lambda k=key: self._navigate(k),
        )
        btn.grid(row=0, column=1, sticky="ew", padx=(2, 10), pady=1)
        self._buttons[key] = btn

    # ── Footer ────────────────────────────────────────────────────────────────

    def _build_footer(self, row: int) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 16))

        ctk.CTkFrame(footer, height=1, fg_color=DIVIDER).pack(fill="x", pady=(0, 10))

        self._logo_label: ctk.CTkLabel | None = None
        self._logo_image: ctk.CTkImage | None = None
        self._build_logo(footer)

        self._version_lbl = ctk.CTkLabel(
            footer,
            text="v1.0.0",
            font=ctk.CTkFont(size=9),
            text_color=TEXT_MUTED,
        )
        self._version_lbl.pack(pady=(4, 0))

    def _build_logo(self, parent: ctk.CTkFrame) -> None:
        logo_path = Path(__file__).parent.parent.parent / "assets" / "bakkislogo.png"
        if logo_path.is_file():
            try:
                from PIL import Image

                img = Image.open(logo_path).convert("RGBA")
                target_h = 28
                scale = target_h / img.height
                target_w = max(1, int(img.width * scale))
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    resample = Image.LANCZOS  # type: ignore[attr-defined]
                img = img.resize((target_w, target_h), resample)
                self._logo_image = ctk.CTkImage(
                    light_image=img, dark_image=img, size=(target_w, target_h),
                )
                self._logo_label = ctk.CTkLabel(
                    parent, image=self._logo_image, text="", fg_color="transparent",
                )
                self._logo_label.pack(anchor="center")
                return
            except Exception:
                pass

        # Fallback text logo
        ctk.CTkLabel(
            parent,
            text="BAKKIS",
            font=ctk.CTkFont(family="SF Pro Display", size=13, weight="bold"),
            text_color=TEXT_MUTED,
            fg_color="transparent",
        ).pack(anchor="center")

    # ──────────────────────────────────────────────────────────────────────────
    # Collapse / expand
    # ──────────────────────────────────────────────────────────────────────────

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._apply_collapsed()
        else:
            self._apply_expanded()

    def _apply_collapsed(self) -> None:
        self.configure(width=SIDEBAR_COL)
        # Shrink brand to just the first letter
        self._brand_title.configure(text="B")
        self._brand_sub.pack_forget()
        self._section_lbl.grid_remove()
        self._toggle_btn.configure(text="›")
        # Buttons: icon only, centred
        for key, icon, _label in NAV_ITEMS:
            if key in self._buttons:
                self._buttons[key].configure(text=f" {icon} ", anchor="center")
        # Hide logo / version in collapsed state
        if self._logo_label:
            self._logo_label.pack_forget()
        self._version_lbl.pack_forget()

    def _apply_expanded(self) -> None:
        self.configure(width=SIDEBAR_W)
        self._brand_title.configure(text="BAKKIS")
        self._brand_sub.pack(anchor="w", pady=(1, 0))
        self._section_lbl.grid()
        self._toggle_btn.configure(text="‹")
        # Buttons: icon + full label
        for key, icon, label in NAV_ITEMS:
            if key in self._buttons:
                self._buttons[key].configure(
                    text=f"  {icon}   {label}", anchor="w",
                )
        # Restore footer widgets
        if self._logo_label:
            self._logo_label.pack(anchor="center", before=self._version_lbl)
        self._version_lbl.pack(pady=(4, 0))

    # ──────────────────────────────────────────────────────────────────────────
    # Navigation state
    # ──────────────────────────────────────────────────────────────────────────

    def _navigate(self, key: str) -> None:
        self._set_active(key)
        self._on_navigate(key)

    def _set_active(self, key: str) -> None:
        # Deactivate previous
        prev = self._active_key
        if prev and prev in self._buttons:
            self._buttons[prev].configure(fg_color="transparent", text_color=TEXT_MUTED)
        if prev and prev in self._indicators:
            self._indicators[prev].configure(bg=BG_SIDEBAR)
        if prev and prev in self._wrappers:
            self._wrappers[prev].configure(bg=BG_SIDEBAR)

        # Activate new
        self._active_key = key
        if key in self._buttons:
            self._buttons[key].configure(fg_color=BG_NAV_ACTIVE, text_color=TEXT_PRIMARY)
        if key in self._indicators:
            self._indicators[key].configure(bg=ACCENT)

    def activate(self, key: str) -> None:
        """Highlight *key* as active without triggering the navigation callback."""
        self._set_active(key)
