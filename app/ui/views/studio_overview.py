"""
Studio Overview — premium infographic dashboard with canvas charts.
"""

from __future__ import annotations

import getpass
import math
import tkinter as tk
from datetime import datetime
from typing import Callable

import customtkinter as ctk

from app.core.scanner import Plugin, analyze_formats
from app.core.cleanup import analyze_cleanup
from app.core.plugin_insights import analyze_insights, insight_options_from_settings
from app.core.music_software_scanner import (
    MusicApp,
    CATEGORY_DAW,
    CATEGORY_LICENSE_MANAGER,
    CATEGORY_PLUGIN_MANAGER,
)
from app.core.hardware_scanner import HardwareDevice

# ── Premium Design System ─────────────────────────────────────────────────────
BG_CONTENT   = "#0E111E"
BG_CARD      = "#131720"
BG_CARD_INNER = "#181D2C"
BG_KPI       = "#161B28"
BG_ACTION    = "#0F1420"
ACCENT       = "#6C8EF5"
ACCENT_DIM   = "#2A3660"
GREEN        = "#4ADE80"
GREEN_DIM    = "#183A28"
ORANGE       = "#F59E0B"
ORANGE_DIM   = "#2A1E08"
RED          = "#F87171"
RED_DIM      = "#2A1018"
PURPLE       = "#A855F7"
PURPLE_DIM   = "#21133A"
TEAL         = "#2DD4BF"
TEAL_DIM     = "#0E2A28"
BLUE         = "#60A5FA"
BLUE_DIM     = "#122038"
TEXT_PRIMARY = "#EEF0F8"
TEXT_SECONDARY = "#94A3B8"
TEXT_MUTED   = "#4B5870"
BORDER       = "#1C2038"
BORDER_BRIGHT = "#242B48"

VENDOR_PALETTE = [ACCENT, BLUE, GREEN, ORANGE, TEAL]

FMT_COLORS = {
    "VST3": ACCENT,
    "AU":   BLUE,
    "VST":  ORANGE,
    "AAX":  PURPLE,
}


def _fmt_size(n: int) -> str:
    if n == 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} GB"


def _username() -> str:
    try:
        name = getpass.getuser()
        return name.replace(".", " ").replace("_", " ").title()
    except Exception:
        return "there"


def _bind_tooltip(widget: tk.Widget, text: str) -> None:
    """Show full *text* in a small floating label on hover."""
    tip_win: list[tk.Toplevel | None] = [None]

    def _show(_event=None) -> None:
        if not text or tip_win[0] is not None:
            return
        tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tw.configure(bg=BORDER_BRIGHT)
        tk.Label(
            tw,
            text=text,
            bg=BORDER_BRIGHT,
            fg=TEXT_PRIMARY,
            font=("SF Pro Text", 10),
            padx=8,
            pady=4,
        ).pack()
        tw.update_idletasks()
        x = widget.winfo_rootx() + 8
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tw.geometry(f"+{x}+{y}")
        tip_win[0] = tw

    def _hide(_event=None) -> None:
        if tip_win[0] is not None:
            tip_win[0].destroy()
            tip_win[0] = None

    widget.bind("<Enter>", _show, add="+")
    widget.bind("<Leave>", _hide, add="+")


# ── Canvas chart helpers ──────────────────────────────────────────────────────

class _DonutChart(tk.Canvas):
    """Donut-style pie chart drawn on a Canvas."""

    def __init__(self, parent: tk.Widget, size: int = 120,
                 bg_color: str = BG_CARD, **kw):
        super().__init__(
            parent, width=size, height=size,
            bg=bg_color, highlightthickness=0, **kw,
        )
        self._size = size
        self._bg = bg_color

    def render(
        self,
        segments: list[tuple[float, str]],
        center_text: str = "",
        center_sub: str = "",
        gap_deg: float = 2.0,
    ) -> None:
        self.delete("all")
        s = self._size
        cx, cy = s // 2, s // 2
        outer_r = s // 2 - 6
        inner_r = outer_r - int(outer_r * 0.42)

        total = sum(v for v, _ in segments if v > 0)

        # Background ring
        self.create_oval(
            cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
            fill=BG_CARD_INNER, outline="",
        )

        if total > 0:
            start = 90.0
            for value, color in segments:
                if value <= 0:
                    continue
                extent = -(360.0 * value / total)
                # Apply gap
                adj_start = start + gap_deg / 2
                adj_extent = extent + gap_deg
                self.create_arc(
                    cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
                    start=adj_start, extent=adj_extent,
                    fill=color, outline="",
                )
                start += extent

        # Punch out center hole
        self.create_oval(
            cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
            fill=self._bg, outline="",
        )

        # Center text
        if center_text:
            offset = -7 if center_sub else 0
            self.create_text(
                cx, cy + offset,
                text=center_text,
                font=("SF Pro Display", 15, "bold"),
                fill=TEXT_PRIMARY,
            )
        if center_sub:
            self.create_text(
                cx, cy + 10,
                text=center_sub,
                font=("SF Pro Text", 8),
                fill=TEXT_MUTED,
            )


class _ArcProgress(tk.Canvas):
    """Single-value arc progress ring."""

    def __init__(self, parent: tk.Widget, size: int = 110,
                 bg_color: str = BG_CARD, **kw):
        super().__init__(
            parent, width=size, height=size,
            bg=bg_color, highlightthickness=0, **kw,
        )
        self._size = size
        self._bg = bg_color

    def render(
        self,
        value: float,
        max_val: float = 1.0,
        color: str = GREEN,
        center_text: str = "",
        center_sub: str = "",
        start_angle: float = 220,
        arc_span: float = 280,
        ring_width: int = 9,
    ) -> None:
        self.delete("all")
        s = self._size
        cx, cy = s // 2, s // 2
        r = s // 2 - ring_width // 2 - 4

        # Background arc
        self.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=start_angle - arc_span,
            extent=arc_span,
            style="arc",
            outline=BG_CARD_INNER,
            width=ring_width,
        )

        # Value arc
        ratio = min(value / max(max_val, 1e-9), 1.0)
        if ratio > 0:
            val_extent = arc_span * ratio
            self.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start_angle,
                extent=-val_extent,
                style="arc",
                outline=color,
                width=ring_width,
            )

        if center_text:
            offset = -8 if center_sub else 0
            self.create_text(
                cx, cy + offset,
                text=center_text,
                font=("SF Pro Display", 17, "bold"),
                fill=TEXT_PRIMARY,
            )
        if center_sub:
            self.create_text(
                cx, cy + 10,
                text=center_sub,
                font=("SF Pro Text", 9),
                fill=TEXT_MUTED,
            )


# ── Main view ─────────────────────────────────────────────────────────────────

class StudioOverviewView(ctk.CTkFrame):
    """Premium infographic dashboard."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        on_navigate: Callable[[str], None] | None = None,
        on_rescan_all: Callable[[], None] | None = None,
        settings=None,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._on_navigate = on_navigate
        self._on_rescan_all = on_rescan_all
        self._rescan_btn: ctk.CTkButton | None = None
        self._plugins: list[Plugin] = []
        self._apps: list[MusicApp] = []
        self._hardware: list[HardwareDevice] = []
        self._lbl: dict[str, ctk.CTkLabel] = {}
        self._bar: dict[str, ctk.CTkProgressBar] = {}
        self._vendor_frame: ctk.CTkFrame | None = None
        self._fmt_donut: _DonutChart | None = None
        self._health_ring: _ArcProgress | None = None
        self._mig_ring: _ArcProgress | None = None
        self._last_scan_lbl: ctk.CTkLabel | None = None

        # Settings-derived values
        self._preferred_daw: str = settings.preferred_daw if settings else ""
        self._machine_role: str = settings.machine_role if settings else ""
        self._machine_name: str = settings.machine_display_name if settings else ""
        self._preferred_formats: list[str] = (
            settings.preferred_formats if settings else ["VST3", "AU"]
        )
        self._migration_threshold: int = (
            settings.migration_readiness_threshold if settings else 80
        )
        self._settings = settings

        self._build()

    # ── Public API ─────────────────────────────────────────────────────────────

    def update_settings(self, settings) -> None:
        """Apply updated settings — currently refreshes the welcome name."""
        self._settings = settings
        name = (
            settings.user_full_name.strip()
            if settings and settings.user_full_name.strip()
            else _username()
        )
        if hasattr(self, "_welcome_lbl"):
            self._welcome_lbl.configure(text=f"Welcome back, {name}.")

    def refresh(self, plugins: list[Plugin]) -> None:
        self._plugins = plugins
        self._update_plugin_stats()

    def refresh_apps(self, apps: list[MusicApp]) -> None:
        self._apps = apps
        self._update_app_stats()

    def refresh_hardware(self, devices: list[HardwareDevice]) -> None:
        self._hardware = devices
        n = sum(1 for d in devices if d.is_connected)
        self._lbl["snap_hardware"].configure(text=str(n))

    def set_scan_status(self, message: str, *, scanning: bool = False) -> None:
        """Update header scan status and Rescan All button state."""
        if self._last_scan_lbl is not None:
            self._last_scan_lbl.configure(text=message)
        if self._rescan_btn is not None:
            self._rescan_btn.configure(state="disabled" if scanning else "normal")

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=24, pady=(14, 12))

        name = (
            self._settings.user_full_name.strip()
            if self._settings and self._settings.user_full_name.strip()
            else _username()
        )
        self._welcome_lbl = ctk.CTkLabel(
            left,
            text=f"Welcome back, {name}.",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self._welcome_lbl.pack(anchor="w")
        ctk.CTkLabel(
            left,
            text="Here's an overview of your studio.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(3, 0))

        # Studio profile context line (DAW + machine role)
        context_parts: list[str] = []
        if self._preferred_daw:
            context_parts.append(f"DAW: {self._preferred_daw}")
        if self._machine_role:
            label = self._machine_name or "This machine"
            context_parts.append(f"{label}  ·  {self._machine_role}")
        if context_parts:
            ctk.CTkLabel(
                left,
                text="  ·  ".join(context_parts),
                font=ctk.CTkFont(size=10),
                text_color=ACCENT,
            ).pack(anchor="w", pady=(2, 0))

        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=24)

        ts = datetime.now().strftime("%b %d, %Y")
        self._last_scan_lbl = ctk.CTkLabel(
            right,
            text=f"Last scan: {ts}",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        )
        self._last_scan_lbl.pack(side="right", padx=(12, 0))

        if self._on_rescan_all:
            self._rescan_btn = ctk.CTkButton(
                right,
                text="  ⟳  Rescan All",
                width=130,
                height=36,
                corner_radius=8,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color=ACCENT_DIM,
                hover_color=ACCENT,
                text_color=TEXT_PRIMARY,
                border_width=1,
                border_color=ACCENT,
                command=self._on_rescan_all,
            )
            self._rescan_btn.pack(side="right")

        # Bottom border on header
        ctk.CTkFrame(hdr, height=1, fg_color=BORDER).grid(
            row=1, column=0, columnspan=2, sticky="ew",
        )

    def _build_body(self) -> None:
        # Scrollable body — rows size to content; page scrolls when taller than viewport.
        body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#252D48",
        )
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        self._build_kpi_row(body, row=0)

        mid = ctk.CTkFrame(body, fg_color="transparent")
        mid.grid(row=1, column=0, sticky="ew", padx=20, pady=(10, 0))
        for c in range(3):
            mid.grid_columnconfigure(c, weight=1, uniform="mid")
        self._build_formats(mid, col=0, padx=(0, 6))
        self._build_health(mid, col=1, padx=(6, 6))
        self._build_migration(mid, col=2, padx=(6, 0))

        bot = ctk.CTkFrame(body, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        for c in range(3):
            bot.grid_columnconfigure(c, weight=1, uniform="bot")
        self._build_storage(bot, col=0, padx=(0, 6))
        self._build_vendors(bot, col=1, padx=(6, 6))
        self._build_quick_actions(bot, col=2, padx=(6, 0))

        ctk.CTkFrame(body, height=16, fg_color="transparent").grid(row=3, column=0)

    # ── KPI Row ───────────────────────────────────────────────────────────────

    def _build_kpi_row(self, parent: ctk.CTkFrame, row: int) -> None:
        g = ctk.CTkFrame(parent, fg_color="transparent")
        g.grid(row=row, column=0, sticky="ew", padx=20, pady=(14, 0))
        for c in range(6):
            g.grid_columnconfigure(c, weight=1, uniform="kpi")

        kpi_defs = [
            ("snap_files",    "◈",  "PLUG-IN FILES",      "Total installed",   ACCENT,  ACCENT_DIM),
            ("snap_products", "⊞",  "PLUG-IN PRODUCTS",   "Unique products",   BLUE,    BLUE_DIM),
            ("snap_apps",     "♬",  "MUSIC APPLICATIONS", "Installed",         GREEN,   GREEN_DIM),
            ("snap_licenses", "⬡",  "LICENSE MANAGERS",   "Detected",         ORANGE,  ORANGE_DIM),
            ("snap_hardware", "⬢",  "HARDWARE DEVICES",   "Connected",        TEAL,    TEAL_DIM),
            ("snap_daws",     "♩",  "DAWs",               "Active DAWs",      PURPLE,  PURPLE_DIM),
        ]
        for col, (key, icon, title, sub, color, dim) in enumerate(kpi_defs):
            padx = (0, 6) if col < 5 else (6, 0)
            self._kpi_tile(g, col, key, icon, title, sub, color, dim, padx)

    def _kpi_tile(
        self,
        parent: ctk.CTkFrame,
        col: int,
        key: str,
        icon: str,
        title: str,
        subtitle: str,
        color: str,
        dim_color: str,
        padx: tuple[int, int],
    ) -> None:
        tile = ctk.CTkFrame(
            parent, fg_color=BG_KPI, corner_radius=12,
            border_width=1, border_color=BORDER_BRIGHT,
        )
        tile.grid(row=0, column=col, sticky="new", padx=padx)
        tile.grid_columnconfigure(1, weight=1)

        icon_box = ctk.CTkFrame(
            tile, width=30, height=30, corner_radius=8, fg_color=dim_color,
        )
        icon_box.grid(row=0, column=0, rowspan=3, padx=(10, 0), pady=10)
        icon_box.grid_propagate(False)
        ctk.CTkLabel(
            icon_box, text=icon,
            font=ctk.CTkFont(size=14), text_color=color,
        ).place(relx=0.5, rely=0.5, anchor="center")

        title_lbl = ctk.CTkLabel(
            tile, text=title,
            font=ctk.CTkFont(size=8, weight="bold"),
            text_color=TEXT_MUTED, anchor="w",
            wraplength=120,
            justify="left",
        )
        title_lbl.grid(row=0, column=1, sticky="sw", padx=(8, 8), pady=(10, 0))
        _bind_tooltip(title_lbl, title)

        def _sync_kpi_title(_event=None, lbl=title_lbl, host=tile) -> None:
            wrap = max(60, host.winfo_width() - 46)
            lbl.configure(wraplength=wrap)

        tile.bind("<Configure>", _sync_kpi_title, add="+")

        val_lbl = ctk.CTkLabel(
            tile, text="—",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY, anchor="w",
        )
        val_lbl.grid(row=1, column=1, sticky="w", padx=(8, 8))
        self._lbl[key] = val_lbl

        ctk.CTkLabel(
            tile, text=subtitle,
            font=ctk.CTkFont(size=8),
            text_color=TEXT_MUTED, anchor="w",
        ).grid(row=2, column=1, sticky="nw", padx=(8, 8), pady=(0, 10))

    # ── Plugin Formats ────────────────────────────────────────────────────────

    def _build_formats(self, parent: ctk.CTkFrame, col: int,
                       padx: tuple[int, int]) -> None:
        c = self._card(parent, 0, col, "⊞  PLUGIN FORMATS",
                       "Format distribution across your library", padx=padx)

        body = ctk.CTkFrame(c, fg_color="transparent")
        body.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 0))
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        # Donut chart
        self._fmt_donut = _DonutChart(body, size=96, bg_color=BG_CARD)
        self._fmt_donut.grid(row=0, column=0, rowspan=4, padx=(2, 10), pady=2)
        self._fmt_donut.render([], "—", "Total")

        # Format bars
        for r, (fmt, color) in enumerate([
            ("VST3", ACCENT),
            ("AU",   BLUE),
            ("VST",  ORANGE),
            ("AAX",  PURPLE),
        ]):
            row_f = ctk.CTkFrame(body, fg_color="transparent")
            row_f.grid(row=r, column=1, sticky="ew", pady=2)
            row_f.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                row_f, text=fmt, width=38,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=color, anchor="w",
            ).grid(row=0, column=0, sticky="w")

            bar = ctk.CTkProgressBar(
                row_f, height=5, corner_radius=3,
                progress_color=color, fg_color=BG_CARD_INNER,
            )
            bar.set(0)
            bar.grid(row=0, column=1, sticky="ew", padx=(6, 8))
            self._bar[f"fmt_{fmt.lower()}"] = bar

            cnt = ctk.CTkLabel(
                row_f, text="—", width=40,
                font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="e",
            )
            cnt.grid(row=0, column=2, sticky="e")
            self._lbl[f"fmt_{fmt.lower()}_n"] = cnt

        # Dup / recoverable summary
        ctk.CTkFrame(c, height=1, fg_color=BORDER).grid(
            row=4, column=0, sticky="ew", padx=14, pady=(8, 0),
        )
        summary = ctk.CTkFrame(c, fg_color="transparent")
        summary.grid(row=5, column=0, sticky="ew", padx=14, pady=(6, 10))
        summary.grid_columnconfigure(0, weight=1, uniform="fs")
        summary.grid_columnconfigure(1, weight=1, uniform="fs")

        self._mini_stat_card(summary, 0, "fmt_dup",   "Multi-format products", ORANGE, (0, 6))
        self._mini_stat_card(summary, 1, "fmt_space", "Est. recoverable",      GREEN,  (6, 0))

        hint = ctk.CTkLabel(
            c, text="Run  ◈ Plug-in Scanner  to populate format data",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        )
        hint.grid(row=6, column=0, sticky="ew", padx=14, pady=(0, 14))
        self._lbl["fmt_hint"] = hint

    # ── Studio Health ─────────────────────────────────────────────────────────

    def _build_health(self, parent: ctk.CTkFrame, col: int,
                      padx: tuple[int, int]) -> None:
        c = self._card(parent, 0, col, "◎  STUDIO HEALTH",
                       "Plugin health status at a glance", padx=padx)

        ring_row = ctk.CTkFrame(c, fg_color="transparent")
        ring_row.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 0))
        ring_row.grid_columnconfigure(0, weight=1)

        self._health_ring = _ArcProgress(ring_row, size=92, bg_color=BG_CARD)
        self._health_ring.grid(row=0, column=0, pady=2)
        self._health_ring.render(0, center_text="—", center_sub="Health")

        # Health stats grid
        stats = ctk.CTkFrame(c, fg_color="transparent")
        stats.grid(row=4, column=0, sticky="ew", padx=14, pady=(6, 0))
        for sc in range(2):
            stats.grid_columnconfigure(sc, weight=1, uniform="hs")

        health_items = [
            ("h_ok",   "◉ Healthy",   GREEN,  (0, 0, 0, 6)),
            ("h_warn", "◍ Warnings",  ORANGE, (0, 0, 6, 6)),
            ("h_dup",  "⊗ Duplicate", BLUE,   (6, 0, 0, 6)),
            ("h_bad",  "✕ Broken",    RED,    (6, 0, 6, 6)),
        ]
        for i, (key, label, color, pad) in enumerate(health_items):
            r, c_idx = divmod(i, 2)
            f = ctk.CTkFrame(stats, fg_color=BG_KPI, corner_radius=8)
            f.grid(
                row=r, column=c_idx, sticky="new",
                padx=(pad[0], pad[1]), pady=(pad[2], pad[3]),
            )
            f.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                f, text=label,
                font=ctk.CTkFont(size=9), text_color=color, anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 1))
            lbl = ctk.CTkLabel(
                f, text="—",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=color, anchor="w",
            )
            lbl.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
            self._lbl[key] = lbl

        legacy = ctk.CTkFrame(c, fg_color=BG_CARD_INNER, corner_radius=8)
        legacy.grid(row=5, column=0, sticky="ew", padx=14, pady=(6, 0))
        legacy.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            legacy, text="Legacy VST2",
            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=8)
        leg_lbl = ctk.CTkLabel(
            legacy, text="—",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=ORANGE, anchor="e",
        )
        leg_lbl.grid(row=0, column=1, sticky="e", padx=12)
        self._lbl["h_legacy"] = leg_lbl

        insights_row = ctk.CTkLabel(
            c,
            text="—",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
            anchor="w",
            wraplength=280,
        )
        insights_row.grid(row=6, column=0, sticky="ew", padx=14, pady=(4, 0))
        self._lbl["h_insights"] = insights_row

        hint = ctk.CTkLabel(
            c, text="Run  ◈ Plug-in Scanner  to analyze health",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        )
        hint.grid(row=7, column=0, sticky="ew", padx=14, pady=(8, 14))
        self._lbl["health_hint"] = hint

    # ── Migration Readiness ───────────────────────────────────────────────────

    def _build_migration(self, parent: ctk.CTkFrame, col: int,
                         padx: tuple[int, int]) -> None:
        c = self._card(parent, 0, col, "⬡  MIGRATION READINESS",
                       "Plugin & app migration progress", padx=padx)

        ring_row = ctk.CTkFrame(c, fg_color="transparent")
        ring_row.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 0))
        ring_row.grid_columnconfigure(0, weight=1)

        self._mig_ring = _ArcProgress(ring_row, size=92, bg_color=BG_CARD)
        self._mig_ring.grid(row=0, column=0, pady=2)
        self._mig_ring.render(0, center_text="—", center_sub="Ready",
                              color=GREEN, start_angle=220, arc_span=280)

        items_f = ctk.CTkFrame(c, fg_color="transparent")
        items_f.grid(row=4, column=0, sticky="ew", padx=14, pady=(6, 0))
        items_f.grid_columnconfigure(1, weight=1)

        mig_items = [
            ("mig_apps",     "● Installed apps",      ACCENT),
            ("mig_licenses", "● License managers",    PURPLE),
            ("mig_cleanup",  "● Cleanup items",       ORANGE),
            ("mig_review",   "● Needs attention",     RED),
        ]
        for r, (key, label, color) in enumerate(mig_items):
            ctk.CTkLabel(
                items_f, text=label,
                font=ctk.CTkFont(size=11), text_color=color, anchor="w",
            ).grid(row=r, column=0, sticky="w", pady=3)
            v = ctk.CTkLabel(
                items_f, text="—",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=color, anchor="e",
            )
            v.grid(row=r, column=1, sticky="e", pady=3)
            self._lbl[key] = v

        # Threshold label (below progress items)
        threshold_lbl = ctk.CTkLabel(
            c,
            text=f"Threshold: {self._migration_threshold}%",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        threshold_lbl.grid(row=5, column=0, sticky="w", padx=14, pady=(2, 0))
        self._lbl["mig_threshold"] = threshold_lbl

        if self._on_navigate:
            ctk.CTkButton(
                c,
                text="Open Migration Assistant  →",
                height=30,
                corner_radius=8,
                font=ctk.CTkFont(size=11),
                fg_color=ACCENT_DIM,
                hover_color=ACCENT,
                text_color=TEXT_PRIMARY,
                command=lambda: self._on_navigate("migration"),
            ).grid(row=6, column=0, sticky="ew", padx=14, pady=(8, 4))

        apps_hint = ctk.CTkLabel(
            c, text="Run  ♬ Music Software Scanner  to detect apps",
            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, anchor="w",
        )
        apps_hint.grid(row=7, column=0, sticky="ew", padx=14, pady=(0, 14))
        self._lbl["mig_hint"] = apps_hint

    # ── Storage Overview ──────────────────────────────────────────────────────

    def _build_storage(self, parent: ctk.CTkFrame, col: int,
                       padx: tuple[int, int]) -> None:
        c = self._card(parent, 0, col, "⬢  STORAGE OVERVIEW",
                       "Plugin disk usage and redundant storage", padx=padx)

        kpi = ctk.CTkFrame(c, fg_color="transparent")
        kpi.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 0))
        kpi.grid_columnconfigure(0, weight=1, uniform="sk")
        kpi.grid_columnconfigure(1, weight=1, uniform="sk")
        self._mini_stat_card(kpi, 0, "stor_total", "Total Plugin Storage", ACCENT, (0, 6))
        self._mini_stat_card(kpi, 1, "stor_redu",  "Redundant Formats",    ORANGE, (6, 0))

        bar_wrap = ctk.CTkFrame(c, fg_color="transparent")
        bar_wrap.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 0))
        bar_wrap.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bar_wrap, text="REDUNDANT  (%  OF TOTAL)",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w")

        sb = ctk.CTkProgressBar(
            bar_wrap, height=7, corner_radius=4,
            progress_color=ORANGE, fg_color=BG_CARD_INNER,
        )
        sb.set(0)
        sb.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._bar["stor"] = sb

        sp = ctk.CTkLabel(
            bar_wrap, text="—",
            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, anchor="e",
        )
        sp.grid(row=2, column=0, sticky="e", pady=(2, 0))
        self._lbl["stor_pct"] = sp

        ctk.CTkFrame(c, height=1, fg_color=BORDER).grid(
            row=5, column=0, sticky="ew", padx=14, pady=(8, 0),
        )
        ctk.CTkLabel(
            c, text="TOP DEVELOPERS",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED, anchor="w",
        ).grid(row=6, column=0, sticky="w", padx=14, pady=(6, 2))

        self._vendor_frame = ctk.CTkFrame(c, fg_color="transparent")
        self._vendor_frame.grid(row=7, column=0, sticky="ew", padx=14, pady=(0, 14))
        self._vendor_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self._vendor_frame,
            text="Run plug-in scanner to see vendor breakdown",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w")

    # ── Top 5 Vendors ─────────────────────────────────────────────────────────

    def _build_vendors(self, parent: ctk.CTkFrame, col: int,
                       padx: tuple[int, int]) -> None:
        c = self._card(parent, 0, col, "⊕  TOP 5 LARGEST VENDORS",
                       "By total plugin storage size", padx=padx)

        self._vendor_bars_frame = ctk.CTkFrame(c, fg_color="transparent")
        self._vendor_bars_frame.grid(
            row=3, column=0, sticky="ew", padx=14, pady=(8, 14),
        )
        self._vendor_bars_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self._vendor_bars_frame,
            text="Run plug-in scanner to populate",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w")

    # ── Quick Actions ─────────────────────────────────────────────────────────

    def _build_quick_actions(self, parent: ctk.CTkFrame, col: int,
                             padx: tuple[int, int]) -> None:
        c = self._card(parent, 0, col, "⚡  QUICK ACTIONS",
                       "Shortcuts to key modules", padx=padx)

        actions = [
            ("◈  Run Plug-in Scan",             "plugins"),
            ("⊞  Analyze Formats",              "format_analysis"),
            ("◯  View Cleanup Recommendations", "cleanup"),
            ("⇄  Create Studio Snapshot",       "migration"),
        ]

        for i, (label, nav_key) in enumerate(actions):
            row_f = ctk.CTkFrame(c, fg_color=BG_ACTION, corner_radius=8)
            row_f.grid(
                row=3 + i, column=0, sticky="ew",
                padx=14, pady=(3 if i == 0 else 2, 3 if i == len(actions) - 1 else 2),
            )
            row_f.grid_columnconfigure(0, weight=1)

            action_btn = ctk.CTkButton(
                row_f,
                text=f"  {label}",
                anchor="w",
                height=32,
                corner_radius=7,
                fg_color="transparent",
                hover_color=BORDER_BRIGHT,
                text_color=TEXT_SECONDARY,
                font=ctk.CTkFont(size=11),
                command=(lambda k=nav_key: self._on_navigate(k))
                if self._on_navigate else None,
            )
            action_btn.grid(row=0, column=0, sticky="ew")

            ctk.CTkLabel(
                row_f, text="→",
                font=ctk.CTkFont(size=13), text_color=TEXT_MUTED,
            ).grid(row=0, column=1, sticky="e", padx=(0, 12))

        ctk.CTkFrame(c, height=10, fg_color="transparent").grid(
            row=3 + len(actions), column=0,
        )

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _card(
        self,
        parent: ctk.CTkFrame,
        row: int,
        col: int,
        title: str,
        subtitle: str,
        padx: tuple[int, int] = (0, 0),
    ) -> ctk.CTkFrame:
        c = ctk.CTkFrame(
            parent, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        c.grid(row=row, column=col, sticky="new", padx=padx)
        c.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            c, text=title,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))

        ctk.CTkLabel(
            c, text=subtitle,
            font=ctk.CTkFont(size=10),
            text_color=BORDER_BRIGHT, anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(1, 0))

        ctk.CTkFrame(c, height=1, fg_color=BORDER).grid(
            row=2, column=0, sticky="ew", padx=14, pady=(8, 0),
        )
        return c

    def _mini_stat_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        key: str,
        label: str,
        color: str,
        padx: tuple[int, int] = (0, 0),
    ) -> None:
        f = ctk.CTkFrame(parent, fg_color=BG_CARD_INNER, corner_radius=8)
        f.grid(row=0, column=col, sticky="ew", padx=padx)
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            f, text=label,
            font=ctk.CTkFont(size=9), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 1))
        lbl = ctk.CTkLabel(
            f, text="—",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=color, anchor="w",
        )
        lbl.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))
        self._lbl[key] = lbl

    # ── Data refresh ──────────────────────────────────────────────────────────

    def _update_plugin_stats(self) -> None:
        plugins = self._plugins
        if not plugins:
            return

        n = len(plugins)
        self._lbl["snap_files"].configure(text=f"{n:,}")

        groups = analyze_formats(plugins)
        self._lbl["snap_products"].configure(text=f"{len(groups):,}")

        # Format counts + donut data
        fmt_counts: dict[str, int] = {}
        for fmt in ("VST", "VST3", "AU", "AAX"):
            fmt_counts[fmt] = sum(1 for p in plugins if p.fmt == fmt)

        segments = [
            (fmt_counts["VST3"], FMT_COLORS["VST3"]),
            (fmt_counts["AU"],   FMT_COLORS["AU"]),
            (fmt_counts["VST"],  FMT_COLORS["VST"]),
            (fmt_counts["AAX"],  FMT_COLORS["AAX"]),
        ]
        if self._fmt_donut:
            self._fmt_donut.render(
                segments,
                center_text=f"{n:,}",
                center_sub="Total",
            )

        for fmt, key_sfx in [("VST3", "vst3"), ("AU", "au"), ("VST", "vst"), ("AAX", "aax")]:
            cnt = fmt_counts[fmt]
            self._lbl[f"fmt_{key_sfx}_n"].configure(text=str(cnt))
            self._bar[f"fmt_{key_sfx}"].set(cnt / max(n, 1))

        dups = [g for g in groups if g.is_duplicate]
        redu_bytes = sum(g.redundant_size for g in dups)
        self._lbl["fmt_dup"].configure(text=str(len(dups)))
        self._lbl["fmt_space"].configure(text=_fmt_size(redu_bytes))
        self._lbl["fmt_hint"].grid_remove()

        # Health (single insights pass — matches Plugin Health settings)
        ins = analyze_insights(
            plugins,
            self._apps,
            **insight_options_from_settings(self._settings),
        )
        ok_count = ins.healthy_count
        n_warn = len(ins.warnings)
        n_dup = len(ins.duplicates)
        n_bad = len(ins.broken)
        n_legacy = sum(1 for p in plugins if p.fmt == "VST")

        self._lbl["h_ok"].configure(text=f"{ok_count:,}")
        self._lbl["h_warn"].configure(text=f"{n_warn:,}")
        self._lbl["h_dup"].configure(text=f"{n_dup:,}")
        self._lbl["h_bad"].configure(text=f"{n_bad:,}")
        self._lbl["h_legacy"].configure(text=f"{n_legacy:,}")

        n_ver = ins.version_conflict_products
        n_stale = len(ins.stale_plugins)
        n_upd = len(ins.update_guidance)
        self._lbl["h_insights"].configure(
            text=f"{n_ver} version conflicts · {n_stale} stale · {n_upd} update tips"
        )

        score = ok_count / max(ins.total_plugins, 1)
        bar_color = GREEN if score >= 0.8 else (ORANGE if score >= 0.5 else RED)
        pct_int = int(score * 100)
        quality = "Good" if score >= 0.8 else ("Fair" if score >= 0.5 else "Poor")
        if self._health_ring:
            self._health_ring.render(
                score, color=bar_color,
                center_text=f"{pct_int}%",
                center_sub=quality,
            )
        self._lbl["health_hint"].grid_remove()

        # Migration counts
        recs = analyze_cleanup(plugins)
        with_cleanup = sum(1 for r in recs if r.has_redundant)
        self._lbl["mig_cleanup"].configure(text=str(with_cleanup))
        self._lbl["mig_review"].configure(text=str(n_bad + with_cleanup))

        # Update migration ring if apps present
        self._refresh_migration_ring()

        # Storage
        total_size = sum(p.file_size for p in plugins)
        self._lbl["stor_total"].configure(text=_fmt_size(total_size))
        self._lbl["stor_redu"].configure(text=_fmt_size(redu_bytes))
        if total_size > 0:
            ratio = min(redu_bytes / total_size, 1.0)
            self._bar["stor"].set(ratio)
            self._lbl["stor_pct"].configure(
                text=f"{int(ratio * 100)}% of storage is redundant"
            )

        # Vendor breakdown
        vsizes: dict[str, int] = {}
        for p in plugins:
            dev = p.developer.strip() or "Unknown"
            vsizes[dev] = vsizes.get(dev, 0) + p.file_size
        top5 = sorted(vsizes.items(), key=lambda x: x[1], reverse=True)[:5]
        self._rebuild_vendors(top5, total_size)

    def _update_app_stats(self) -> None:
        apps = self._apps
        n_all  = len(apps)
        n_daws = sum(1 for a in apps if a.category == CATEGORY_DAW)
        n_lic  = sum(1 for a in apps if a.category == CATEGORY_LICENSE_MANAGER)

        self._lbl["snap_apps"].configure(text=str(n_all))
        self._lbl["snap_daws"].configure(text=str(n_daws))
        self._lbl["snap_licenses"].configure(text=str(n_lic))

        self._lbl["mig_apps"].configure(text=str(n_all))
        self._lbl["mig_licenses"].configure(text=str(n_lic))
        if n_all:
            self._lbl["mig_hint"].grid_remove()

        self._refresh_migration_ring()

    def _refresh_migration_ring(self) -> None:
        if not self._mig_ring:
            return
        n_apps = len(self._apps)
        n_plugins = len(self._plugins)
        total = n_apps + n_plugins
        if total == 0:
            return

        # Use preferred_formats from settings to determine "migration-clean" plugins
        preferred_set = set(self._preferred_formats) if self._preferred_formats else {"VST3", "AU"}
        n_clean = n_apps + sum(1 for p in self._plugins if p.fmt in preferred_set)
        pct = int(100 * n_clean / max(total, 1))
        pct = min(pct, 100)

        # Apply readiness threshold from settings for color coding
        threshold = self._migration_threshold
        if pct >= threshold:
            ring_color = GREEN
            sub_text = "Ready"
        elif pct >= threshold * 0.6:
            ring_color = ORANGE
            sub_text = "In Progress"
        else:
            ring_color = RED
            sub_text = "Not Ready"

        self._mig_ring.render(
            pct, max_val=100,
            color=ring_color,
            center_text=f"{pct}%",
            center_sub=sub_text,
        )

        # Update threshold hint label if it exists
        if "mig_threshold" in self._lbl:
            self._lbl["mig_threshold"].configure(
                text=f"Threshold: {threshold}%",
                text_color=TEXT_MUTED,
            )

    def _rebuild_vendors(
        self,
        top5: list[tuple[str, int]],
        total_size: int,
    ) -> None:
        # Update the inline vendor_frame (in storage card)
        if self._vendor_frame:
            for w in self._vendor_frame.winfo_children():
                w.destroy()
            self._vendor_frame.grid_columnconfigure(0, weight=1)
            if not top5:
                ctk.CTkLabel(
                    self._vendor_frame, text="No vendor data available",
                    font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="w",
                ).grid(row=0, column=0, sticky="w")
                return
            max_size = top5[0][1] if top5 else 1
            for i, (vendor, size) in enumerate(top5):
                rf = ctk.CTkFrame(self._vendor_frame, fg_color="transparent")
                rf.grid(row=i, column=0, sticky="ew", pady=2)
                rf.grid_columnconfigure(0, weight=1)
                rf.grid_columnconfigure(1, weight=2)
                color = VENDOR_PALETTE[i % len(VENDOR_PALETTE)]
                name_lbl = ctk.CTkLabel(
                    rf, text=vendor,
                    font=ctk.CTkFont(size=10), text_color=TEXT_PRIMARY, anchor="w",
                )
                name_lbl.grid(row=0, column=0, sticky="ew")
                _bind_tooltip(name_lbl, vendor)
                b = ctk.CTkProgressBar(
                    rf, height=4, corner_radius=2,
                    progress_color=color, fg_color=BG_CARD_INNER,
                )
                b.set(size / max(max_size, 1))
                b.grid(row=0, column=1, sticky="ew", padx=(6, 6))
                ctk.CTkLabel(
                    rf, text=_fmt_size(size), width=72,
                    font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, anchor="e",
                ).grid(row=0, column=2, sticky="e")

        # Update the dedicated vendor bars frame
        if not hasattr(self, "_vendor_bars_frame"):
            return
        for w in self._vendor_bars_frame.winfo_children():
            w.destroy()
        self._vendor_bars_frame.grid_columnconfigure(0, weight=1)
        if not top5:
            ctk.CTkLabel(
                self._vendor_bars_frame,
                text="Run plug-in scanner to populate",
                font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, anchor="w",
            ).grid(row=0, column=0, sticky="w")
            return
        max_size = top5[0][1] if top5 else 1
        for i, (vendor, size) in enumerate(top5):
            rf = ctk.CTkFrame(self._vendor_bars_frame, fg_color="transparent")
            rf.grid(row=i, column=0, sticky="ew", pady=3)
            rf.grid_columnconfigure(0, weight=1)
            rf.grid_columnconfigure(1, weight=2)
            color = VENDOR_PALETTE[i % len(VENDOR_PALETTE)]
            name_lbl = ctk.CTkLabel(
                rf, text=vendor,
                font=ctk.CTkFont(size=11), text_color=TEXT_PRIMARY, anchor="w",
            )
            name_lbl.grid(row=0, column=0, sticky="ew")
            _bind_tooltip(name_lbl, vendor)
            b = ctk.CTkProgressBar(
                rf, height=5, corner_radius=3,
                progress_color=color, fg_color=BG_CARD_INNER,
            )
            b.set(size / max(max_size, 1))
            b.grid(row=0, column=1, sticky="ew", padx=(8, 8))
            ctk.CTkLabel(
                rf, text=f"{_fmt_size(size)}",
                font=ctk.CTkFont(size=10), text_color=TEXT_MUTED, anchor="e",
                width=72,
            ).grid(row=0, column=2, sticky="e")
