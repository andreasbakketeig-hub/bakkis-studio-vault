"""
Sidebar navigation panel — premium dark macOS-style design.

Layout
------
  Sidebar (CTkFrame, fixed width, fills window height)
  ├── Header  — brand name + collapse toggle  [fixed, never scrolls]
  ├── Nav     — CTkScrollableFrame            [expands, scrollable]
  │   ├── section headers (DASHBOARD, PLUGIN MANAGEMENT, …)
  │   └── nav items with left-accent indicator
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

# ── Navigation sections  (title, [(key, icon, label), …]) ─────────────────────
NAV_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("DASHBOARD", [
        ("studio_overview", "▣", "Studio Overview"),
    ]),
    ("PLUGIN MANAGEMENT", [
        ("plugins",         "◈", "Plug-in Scanner"),
        ("format_analysis", "⊞", "Format Analysis"),
        ("plugin_health",   "◎", "Plugin Health"),
        ("cleanup",         "◯", "Cleanup Recommendations"),
        ("quarantine",      "▣", "Quarantined Items"),
    ]),
    ("STUDIO SYSTEM", [
        ("music_software",   "♬", "Music Software Scanner"),
        ("studio_snapshots", "⊟", "Studio Snapshots"),
        ("migration",        "⇄", "Migration Assistant"),
    ]),
    ("HARDWARE & I/O", [
        ("hardware",      "⬢", "Studio Hardware"),
        ("audio_devices", "◉", "Audio Devices"),
        ("midi",          "♩", "MIDI Devices"),
        ("mapper",        "⋈", "Studio Mapper"),
    ]),
    ("ADMIN", [
        ("licenses", "⬡", "License Vault"),
        ("settings", "⚙", "Settings"),
    ]),
]

# Flat list derived from sections — used for collapse/expand label restoration.
NAV_ITEMS: list[tuple[str, str, str]] = [
    item for _title, items in NAV_SECTIONS for item in items
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
        self._buttons:         dict[str, ctk.CTkButton] = {}
        self._indicators:      dict[str, tk.Canvas]     = {}
        self._wrappers:        dict[str, tk.Frame]       = {}
        self._section_labels:  list[ctk.CTkLabel]       = []

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

        # Brand area (logo image or text fallback)
        brand = ctk.CTkFrame(hdr, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=20, pady=(24, 0))

        self._brand_logo_label: ctk.CTkLabel | None = None
        self._brand_logo_image: ctk.CTkImage | None = None
        self._brand_title_label: ctk.CTkLabel | None = None
        self._build_brand_logo(brand)

        self._brand_sub = ctk.CTkLabel(
            brand,
            text="Studio Manager",
            font=ctk.CTkFont(family="SF Pro Display", size=9, weight="bold"),
            text_color=ACCENT,
            anchor="w",
        )
        self._brand_sub.pack(anchor="w", pady=(3, 0))

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

    def _build_brand_logo(self, parent: ctk.CTkFrame) -> None:
        """Load BAKKIS wordmark for the sidebar header. Falls back to styled text."""
        logo_path = Path(__file__).parent.parent / "assets" / "branding" / "bakkislogo.png"
        if not logo_path.is_file():
            logo_path = Path(__file__).parent.parent.parent / "assets" / "bakkislogo.png"

        if logo_path.is_file():
            photo = self._load_brand_photo(logo_path)
            if photo is not None:
                lbl = tk.Label(
                    parent,
                    image=photo,
                    bg=BG_SIDEBAR,
                    bd=0,
                    highlightthickness=0,
                    cursor="",
                )
                lbl.pack(anchor="w")
                self._brand_logo_label = lbl  # type: ignore[assignment]
                self._brand_photo = photo
                return

        # Text fallback — styled wordmark matching the visual weight of the logo
        self._brand_title_label = ctk.CTkLabel(
            parent,
            text="BAKKIS",
            font=ctk.CTkFont(family="SF Pro Display", size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        self._brand_title_label.pack(anchor="w")

    def _load_brand_photo(self, logo_path: Path) -> tk.PhotoImage | None:
        """Return a scaled PhotoImage for the header wordmark."""
        target_h = 32

        # Prefer Pillow when available — sharper resize on Retina displays.
        try:
            from PIL import Image, ImageTk

            img = Image.open(logo_path).convert("RGBA")
            aspect = img.width / img.height
            target_w = max(1, int(target_h * aspect))
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS  # type: ignore[attr-defined]
            img_display = img.resize((target_w, target_h), resample)
            return ImageTk.PhotoImage(img_display)
        except ImportError:
            pass
        except Exception:
            pass

        # No Pillow: Tk can load PNG directly and downscale via subsample().
        try:
            photo = tk.PhotoImage(file=str(logo_path))
            orig_w, orig_h = photo.width(), photo.height()
            if orig_h <= target_h:
                return photo

            target_w = max(1, int(target_h * orig_w / orig_h))
            factor_x = max(1, round(orig_w / target_w))
            factor_y = max(1, round(orig_h / target_h))
            return photo.subsample(factor_x, factor_y)
        except Exception:
            return None

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

        # ── Section headers + nav items ───────────────────────────────────────
        grid_row = 0
        for section_idx, (section_title, section_items) in enumerate(NAV_SECTIONS):
            top_pad = (14, 4) if section_idx == 0 else (16, 4)
            section_lbl = ctk.CTkLabel(
                self._nav_scroll,
                text=section_title,
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=SECTION_LABEL,
                anchor="w",
            )
            section_lbl.grid(row=grid_row, column=0, sticky="w", padx=22, pady=top_pad)
            self._section_labels.append(section_lbl)
            grid_row += 1

            for key, icon, label in section_items:
                self._build_nav_item(key, icon, label, row=grid_row)
                grid_row += 1

        # Small bottom padding inside scroll area
        ctk.CTkFrame(self._nav_scroll, height=10, fg_color="transparent").grid(
            row=grid_row, column=0,
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

        self._version_lbl = ctk.CTkLabel(
            footer,
            text="v1.0.0",
            font=ctk.CTkFont(size=9),
            text_color=TEXT_MUTED,
        )
        self._version_lbl.pack(pady=(0, 0))

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
        # Hide logo/wordmark and subtitle; show a minimal text initial
        if self._brand_logo_label:
            self._brand_logo_label.pack_forget()
        if self._brand_title_label:
            self._brand_title_label.configure(text="B")
        self._brand_sub.pack_forget()
        for lbl in self._section_labels:
            lbl.grid_remove()
        self._toggle_btn.configure(text="›")
        # Buttons: icon only, centred
        for key, icon, _label in NAV_ITEMS:
            if key in self._buttons:
                self._buttons[key].configure(text=f" {icon} ", anchor="center")
        # Hide version in collapsed state
        self._version_lbl.pack_forget()

    def _apply_expanded(self) -> None:
        self.configure(width=SIDEBAR_W)
        # Restore logo/wordmark
        if self._brand_logo_label:
            self._brand_logo_label.pack(anchor="w")
        if self._brand_title_label:
            self._brand_title_label.configure(text="BAKKIS")
        self._brand_sub.pack(anchor="w", pady=(3, 0))
        for lbl in self._section_labels:
            lbl.grid()
        self._toggle_btn.configure(text="‹")
        # Buttons: icon + full label
        for key, icon, label in NAV_ITEMS:
            if key in self._buttons:
                self._buttons[key].configure(
                    text=f"  {icon}   {label}", anchor="w",
                )
        self._version_lbl.pack(pady=(0, 0))

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

    def update_accent(self, color: str) -> None:
        """Apply a new accent color to the active nav indicator immediately."""
        key = self._active_key
        if key and key in self._indicators:
            self._indicators[key].configure(bg=color)
