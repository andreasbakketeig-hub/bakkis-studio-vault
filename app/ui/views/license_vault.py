"""
License Vault view — inventory and health tracking for plugin licenses.

Tabs:
  Overview  — health dashboard + vendor summary cards
  Products  — full product table (name, vendor, version, manager, status, formats)
  Vendors   — per-vendor aggregation table
  Managers  — detected license manager table + actions

Read-only.  No activation, deactivation, update, or uninstall logic.
"""

from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence

import customtkinter as ctk

from app.core.license_vault import (
    LicenseStatus,
    LicenseProduct,
    LicenseVaultReport,
    InstalledManager,
    VendorSummary,
    build_license_vault_report,
    LICENSE_MANAGER_REGISTRY,
)
from app.core.scanner import Plugin
from app.core.music_software_scanner import MusicApp

# ── Design tokens ──────────────────────────────────────────────────────────────
BG_VIEW          = "transparent"
BG_CARD          = "#131720"
BG_CARD_INNER    = "#181D2C"
BG_TABLE         = "#0D1020"
BG_TABLE_ROW     = "#131720"
BG_TABLE_ROW_ALT = "#161B28"
BG_TABLE_SEL     = "#1B2848"
BG_TAB_ACTIVE    = "#1A2545"
BG_TAB_HOVER     = "#141828"

ACCENT           = "#6C8EF5"
ACCENT_HOVER     = "#8BAAF7"
TEXT_PRIMARY     = "#EEF0F8"
TEXT_SECONDARY   = "#94A3B8"
TEXT_MUTED       = "#4B5870"
BORDER           = "#1C2038"
BORDER_BRIGHT    = "#242B48"

COLOR_MANAGED         = "#4ADE80"
COLOR_WEBSITE         = "#60A5FA"
COLOR_MISSING         = "#F59E0B"
COLOR_UNKNOWN         = "#94A3B8"
COLOR_MANUAL          = "#A855F7"

DIM_MANAGED           = "#183A28"
DIM_WEBSITE           = "#122038"
DIM_MISSING           = "#2A1E08"
DIM_UNKNOWN           = "#1C222E"
DIM_MANUAL            = "#21133A"

STATUS_COLOR: dict[LicenseStatus, str] = {
    LicenseStatus.MANAGED:         COLOR_MANAGED,
    LicenseStatus.WEBSITE_MANAGED: COLOR_WEBSITE,
    LicenseStatus.MISSING_MANAGER: COLOR_MISSING,
    LicenseStatus.UNKNOWN:         COLOR_UNKNOWN,
    LicenseStatus.MANUAL_LICENSE:  COLOR_MANUAL,
}

STATUS_DIM: dict[LicenseStatus, str] = {
    LicenseStatus.MANAGED:         DIM_MANAGED,
    LicenseStatus.WEBSITE_MANAGED: DIM_WEBSITE,
    LicenseStatus.MISSING_MANAGER: DIM_MISSING,
    LicenseStatus.UNKNOWN:         DIM_UNKNOWN,
    LicenseStatus.MANUAL_LICENSE:  DIM_MANUAL,
}

TABS = ["Overview", "Products", "Vendors", "Managers"]


class LicenseVaultView(ctk.CTkFrame):
    """Root frame for the License Vault module."""

    def __init__(
        self,
        parent: ctk.CTkFrame,
        plugins: list[Plugin] | None = None,
        music_apps: list[MusicApp] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(parent, fg_color=BG_VIEW, **kwargs)

        self._plugins: list[Plugin] = plugins or []
        self._music_apps: list[MusicApp] = music_apps or []
        self._report: LicenseVaultReport | None = None
        self._active_tab: str = "Overview"

        self._tab_frames: dict[str, ctk.CTkFrame] = {}
        self._tab_buttons: dict[str, ctk.CTkButton] = {}

        self._build()
        if self._plugins or self._music_apps:
            self._run_analysis()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_tab_bar()
        self._build_tab_content()

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=30, pady=(28, 0))
        hdr.grid_columnconfigure(0, weight=1)

        title_row = ctk.CTkFrame(hdr, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            title_row,
            text="License Vault",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self._refresh_btn = ctk.CTkButton(
            title_row,
            text="  ⬡  Analyze",
            width=130,
            height=36,
            corner_radius=9,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._run_analysis,
        )
        self._refresh_btn.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            hdr,
            text="Inventory and health tracking for your plugin licenses — read-only",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

    def _build_tab_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=30, pady=(18, 0))

        for i, tab in enumerate(TABS):
            btn = ctk.CTkButton(
                bar,
                text=tab,
                width=110,
                height=34,
                corner_radius=8,
                font=ctk.CTkFont(size=12),
                fg_color=BG_TAB_ACTIVE if tab == self._active_tab else "transparent",
                hover_color=BG_TAB_HOVER,
                text_color=TEXT_PRIMARY if tab == self._active_tab else TEXT_MUTED,
                border_width=1,
                border_color=BORDER if tab == self._active_tab else "transparent",
                command=lambda t=tab: self._switch_tab(t),
            )
            btn.pack(side="left", padx=(0, 6) if i < len(TABS) - 1 else 0)
            self._tab_buttons[tab] = btn

    def _build_tab_content(self) -> None:
        self._content_host = ctk.CTkFrame(self, fg_color="transparent")
        self._content_host.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        self._content_host.grid_columnconfigure(0, weight=1)
        self._content_host.grid_rowconfigure(0, weight=1)

        self._tab_frames["Overview"]  = _OverviewTab(self._content_host)
        self._tab_frames["Products"]  = _ProductsTab(self._content_host)
        self._tab_frames["Vendors"]   = _VendorsTab(self._content_host)
        self._tab_frames["Managers"]  = _ManagersTab(self._content_host)

        for tab, frame in self._tab_frames.items():
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_remove()

        self._tab_frames[self._active_tab].grid()

    # ── Tab switching ──────────────────────────────────────────────────────────

    def _switch_tab(self, tab: str) -> None:
        if tab == self._active_tab:
            return
        self._tab_frames[self._active_tab].grid_remove()
        self._tab_buttons[self._active_tab].configure(
            fg_color="transparent",
            text_color=TEXT_MUTED,
            border_color="transparent",
        )
        self._active_tab = tab
        self._tab_frames[tab].grid()
        self._tab_buttons[tab].configure(
            fg_color=BG_TAB_ACTIVE,
            text_color=TEXT_PRIMARY,
            border_color=BORDER,
        )

    # ── Analysis ───────────────────────────────────────────────────────────────

    def _run_analysis(self) -> None:
        self._refresh_btn.configure(state="disabled", text="  ⬡  Analyzing…")
        report = build_license_vault_report(self._plugins, self._music_apps)
        self._report = report
        self._populate_all(report)
        self._refresh_btn.configure(state="normal", text="  ⬡  Analyze")

    def _populate_all(self, report: LicenseVaultReport) -> None:
        self._tab_frames["Overview"].populate(report)   # type: ignore[union-attr]
        self._tab_frames["Products"].populate(report)   # type: ignore[union-attr]
        self._tab_frames["Vendors"].populate(report)    # type: ignore[union-attr]
        self._tab_frames["Managers"].populate(report)   # type: ignore[union-attr]

    # ── Public refresh API ─────────────────────────────────────────────────────

    def refresh(
        self,
        plugins: list[Plugin] | None = None,
        music_apps: list[MusicApp] | None = None,
    ) -> None:
        """Called by MainWindow when plugin or app scan completes."""
        if plugins is not None:
            self._plugins = plugins
        if music_apps is not None:
            self._music_apps = music_apps
        self._run_analysis()


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _status_badge_color(status: LicenseStatus) -> str:
    return STATUS_COLOR.get(status, COLOR_UNKNOWN)


def _make_treeview_style(style_name: str) -> None:
    """Configure a dark Treeview style named *style_name*."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        style_name,
        background=BG_TABLE,
        foreground=TEXT_PRIMARY,
        fieldbackground=BG_TABLE,
        rowheight=36,
        borderwidth=0,
        font=("SF Pro Text", 12),
    )
    style.configure(
        f"{style_name}.Heading",
        background=BG_TABLE,
        foreground=TEXT_MUTED,
        font=("SF Pro Text", 10),
        relief="flat",
        borderwidth=0,
    )
    style.map(
        style_name,
        background=[("selected", BG_TABLE_SEL)],
        foreground=[("selected", TEXT_PRIMARY)],
    )
    style.layout(style_name, [(f"{style_name}.treearea", {"sticky": "nswe"})])


def _card_row(
    parent: ctk.CTkFrame,
    col: int,
    key: str,
    title: str,
    color: str,
    dim: str,
    icon: str,
) -> ctk.CTkLabel:
    """Build a summary card and return its count label."""
    card = ctk.CTkFrame(
        parent, fg_color=BG_CARD, corner_radius=12,
        border_width=1, border_color=BORDER,
    )
    card.grid(row=0, column=col, sticky="ew", padx=(0, 10) if col < 4 else (0, 0))
    card.grid_columnconfigure(1, weight=1)

    icon_box = ctk.CTkFrame(card, width=38, height=38, corner_radius=9, fg_color=dim)
    icon_box.grid(row=0, column=0, rowspan=2, padx=(14, 0), pady=14)
    icon_box.grid_propagate(False)
    ctk.CTkLabel(
        icon_box, text=icon,
        font=ctk.CTkFont(size=15), text_color=color,
    ).place(relx=0.5, rely=0.5, anchor="center")

    ctk.CTkLabel(
        card, text=title.upper(),
        font=ctk.CTkFont(size=9, weight="bold"),
        text_color=TEXT_MUTED, anchor="w",
    ).grid(row=0, column=1, sticky="sw", padx=(12, 14), pady=(14, 0))

    lbl = ctk.CTkLabel(
        card, text="—",
        font=ctk.CTkFont(size=26, weight="bold"),
        text_color=color, anchor="w",
    )
    lbl.grid(row=1, column=1, sticky="nw", padx=(12, 14), pady=(0, 14))
    return lbl


# ── Tab: Overview ──────────────────────────────────────────────────────────────

class _OverviewTab(ctk.CTkFrame):
    def __init__(self, parent: ctk.CTkFrame, **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    def _build(self) -> None:
        # ── Health cards ──────────────────────────────────────────────────────
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.grid(row=0, column=0, sticky="ew", padx=30, pady=(8, 14))
        for i in range(5):
            cards_row.grid_columnconfigure(i, weight=1)

        _CARDS = [
            ("total",    "Products Detected",       ACCENT,         DIM_WEBSITE,  "◈"),
            ("managed",  "Managed Products",         COLOR_MANAGED,  DIM_MANAGED,  "✓"),
            ("unknown",  "Unknown Products",         COLOR_UNKNOWN,  DIM_UNKNOWN,  "?"),
            ("vendors",  "Vendors Detected",         COLOR_MANUAL,   DIM_MANUAL,   "⬡"),
            ("managers", "Installed Managers",       COLOR_WEBSITE,  DIM_WEBSITE,  "⬢"),
        ]
        self._card_labels: dict[str, ctk.CTkLabel] = {}
        for col, (key, title, color, dim, icon) in enumerate(_CARDS):
            self._card_labels[key] = _card_row(cards_row, col, key, title, color, dim, icon)

        # ── Vendor summary ─────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="VENDOR SUMMARY",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=30, pady=(4, 6))

        self._vendor_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=BG_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
            scrollbar_fg_color=BG_TABLE,
            scrollbar_button_color="#232840",
            scrollbar_button_hover_color="#323A5A",
        )
        self._vendor_scroll.grid(row=2, column=0, sticky="nsew", padx=30, pady=(0, 24))
        self._vendor_scroll.grid_columnconfigure(0, weight=1)

        self._empty_lbl = ctk.CTkLabel(
            self._vendor_scroll,
            text="Click  ⬡ Analyze  to build your license inventory",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_lbl.grid(row=0, column=0, pady=40)

    def populate(self, report: LicenseVaultReport) -> None:
        # Update cards
        self._card_labels["total"].configure(text=str(report.total_products))
        self._card_labels["managed"].configure(
            text=str(report.managed_count + report.website_managed_count)
        )
        self._card_labels["unknown"].configure(text=str(report.unknown_count))
        self._card_labels["vendors"].configure(text=str(report.vendor_count))
        self._card_labels["managers"].configure(text=str(report.manager_count))

        # Clear vendor cards
        for w in self._vendor_scroll.winfo_children():
            w.destroy()

        if not report.vendors:
            ctk.CTkLabel(
                self._vendor_scroll,
                text="No plugins found — run a plugin scan first",
                font=ctk.CTkFont(size=13),
                text_color=TEXT_MUTED,
            ).grid(row=0, column=0, pady=40)
            return

        for row_idx, vendor in enumerate(report.vendors):
            self._build_vendor_card(row_idx, vendor)

    def _build_vendor_card(self, row: int, vendor: VendorSummary) -> None:
        color = STATUS_COLOR.get(vendor.status, COLOR_UNKNOWN)
        dim   = STATUS_DIM.get(vendor.status, DIM_UNKNOWN)

        card = ctk.CTkFrame(
            self._vendor_scroll,
            fg_color=BG_CARD_INNER,
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
        )
        card.grid(row=row, column=0, sticky="ew", padx=12, pady=(6, 0))
        card.grid_columnconfigure(1, weight=1)

        # Status dot
        dot = tk.Canvas(card, width=10, height=10, bg=BG_CARD_INNER, highlightthickness=0)
        dot.grid(row=0, column=0, rowspan=3, padx=(14, 0), pady=14)
        dot.create_oval(1, 1, 9, 9, fill=color, outline="")

        # Vendor name
        ctk.CTkLabel(
            card,
            text=vendor.display_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        # Metadata row
        meta = f"Products: {vendor.product_count}   •   Manager: {vendor.manager_display}"
        ctk.CTkLabel(
            card,
            text=meta,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
            anchor="w",
        ).grid(row=1, column=1, sticky="w", padx=(10, 0))

        # Status badge
        ctk.CTkLabel(
            card,
            text=vendor.status.value,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=color,
            fg_color=dim,
            corner_radius=5,
            anchor="w",
        ).grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(2, 10))

        # Website button (right side)
        if vendor.website:
            ctk.CTkButton(
                card,
                text="↗ Website",
                width=90,
                height=28,
                corner_radius=7,
                font=ctk.CTkFont(size=11),
                fg_color="transparent",
                hover_color=BG_TAB_HOVER,
                text_color=TEXT_MUTED,
                border_width=1,
                border_color=BORDER,
                command=lambda url=vendor.website: subprocess.run(["open", url], check=False),
            ).grid(row=0, column=2, rowspan=3, padx=(0, 14), pady=14)


# ── Tab: Products ──────────────────────────────────────────────────────────────

class _ProductsTab(ctk.CTkFrame):
    """Scrollable table of all products with search/filter."""

    COLUMNS = [
        ("product",  "PRODUCT",   220, True,  "w"),
        ("vendor",   "VENDOR",    160, False, "w"),
        ("version",  "VERSION",    80, False, "center"),
        ("manager",  "MANAGER",   200, True,  "w"),
        ("status",   "STATUS",    140, False, "w"),
        ("formats",  "FORMATS",   110, False, "center"),
    ]

    def __init__(self, parent: ctk.CTkFrame, **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._all_products: list[LicenseProduct] = []
        self._build()

    def _build(self) -> None:
        # ── Toolbar ────────────────────────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=30, pady=(8, 10))
        bar.grid_columnconfigure(1, weight=1)

        search_frame = ctk.CTkFrame(
            bar, fg_color=BG_CARD, corner_radius=9,
            border_width=1, border_color=BORDER,
        )
        search_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        search_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            search_frame, text="⌕",
            font=ctk.CTkFont(size=16), text_color=TEXT_MUTED, width=30,
        ).grid(row=0, column=0, padx=(10, 0))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        ctk.CTkEntry(
            search_frame,
            textvariable=self._search_var,
            placeholder_text="Filter by product, vendor, manager, status, or format…",
            fg_color="transparent",
            border_width=0,
            text_color=TEXT_PRIMARY,
            placeholder_text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            height=38,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 10))

        self._count_lbl = ctk.CTkLabel(
            search_frame, text="",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        )
        self._count_lbl.grid(row=0, column=2, padx=(0, 14))

        # ── Table ──────────────────────────────────────────────────────────────
        container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        container.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 24))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        _make_treeview_style("LVProducts.Treeview")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=[c[0] for c in self.COLUMNS],
            show="headings",
            style="LVProducts.Treeview",
            selectmode="browse",
        )
        for col_id, heading, width, stretch, anchor in self.COLUMNS:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=50, stretch=stretch, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.tag_configure("even", background=BG_TABLE_ROW)
        self._tree.tag_configure("odd",  background=BG_TABLE_ROW_ALT)
        for st in LicenseStatus:
            tag = f"status_{st.name}"
            self._tree.tag_configure(tag, foreground=STATUS_COLOR[st])

        self._empty_lbl = ctk.CTkLabel(
            container,
            text="No products loaded — click  ⬡ Analyze  to start",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_lbl.grid(row=0, column=0, pady=40)

    def populate(self, report: LicenseVaultReport) -> None:
        self._all_products = report.products
        self._apply_filter(self._search_var.get())

    def _apply_filter(self, query: str) -> None:
        q = query.strip().lower()
        if q:
            filtered = [
                p for p in self._all_products
                if q in p.product_name.lower()
                or q in p.developer.lower()
                or q in p.vendor_display.lower()
                or q in p.license_manager.lower()
                or q in p.license_status.value.lower()
                or q in p.formats_str.lower()
                or q in p.version.lower()
            ]
        else:
            filtered = list(self._all_products)
        self._populate_tree(filtered)
        n = len(filtered)
        total = len(self._all_products)
        extra = f" of {total:,}" if q and n != total else ""
        self._count_lbl.configure(
            text=f"{n:,} {'product' if n == 1 else 'products'}{extra}"
        )

    def _populate_tree(self, products: list[LicenseProduct]) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)

        if not products:
            self._empty_lbl.grid()
            return
        self._empty_lbl.grid_remove()

        for i, p in enumerate(products):
            row_tag = "even" if i % 2 == 0 else "odd"
            status_tag = f"status_{p.license_status.name}"
            self._tree.insert(
                "", "end",
                values=(
                    p.product_name,
                    p.vendor_display,
                    p.version or "—",
                    p.license_manager or "—",
                    p.license_status.value,
                    p.formats_str,
                ),
                tags=(row_tag, status_tag),
            )

    def _on_search(self, *_) -> None:
        self._apply_filter(self._search_var.get())


# ── Tab: Vendors ───────────────────────────────────────────────────────────────

class _VendorsTab(ctk.CTkFrame):
    COLUMNS = [
        ("vendor",   "VENDOR",        200, True,  "w"),
        ("count",    "PRODUCTS",       90, False, "center"),
        ("manager",  "MANAGER",       200, True,  "w"),
        ("website",  "WEBSITE",       260, True,  "w"),
        ("status",   "STATUS",        140, False, "w"),
    ]

    def __init__(self, parent: ctk.CTkFrame, **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._all_vendors: list[VendorSummary] = []
        self._build()

    def _build(self) -> None:
        container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        container.grid(row=0, column=0, sticky="nsew", padx=30, pady=(8, 24))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        _make_treeview_style("LVVendors.Treeview")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=[c[0] for c in self.COLUMNS],
            show="headings",
            style="LVVendors.Treeview",
            selectmode="browse",
        )
        for col_id, heading, width, stretch, anchor in self.COLUMNS:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=50, stretch=stretch, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("even", background=BG_TABLE_ROW)
        self._tree.tag_configure("odd",  background=BG_TABLE_ROW_ALT)
        for st in LicenseStatus:
            self._tree.tag_configure(f"status_{st.name}", foreground=STATUS_COLOR[st])

        self._empty_lbl = ctk.CTkLabel(
            container,
            text="No vendor data — click  ⬡ Analyze",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_lbl.grid(row=0, column=0, pady=40)

    def populate(self, report: LicenseVaultReport) -> None:
        self._all_vendors = report.vendors
        for row in self._tree.get_children():
            self._tree.delete(row)

        if not report.vendors:
            self._empty_lbl.grid()
            return
        self._empty_lbl.grid_remove()

        for i, v in enumerate(report.vendors):
            row_tag = "even" if i % 2 == 0 else "odd"
            status_tag = f"status_{v.status.name}"
            self._tree.insert(
                "", "end",
                values=(
                    v.display_name,
                    str(v.product_count),
                    v.manager_display,
                    v.website or "—",
                    v.status.value,
                ),
                tags=(row_tag, status_tag),
            )


# ── Tab: Managers ──────────────────────────────────────────────────────────────

class _ManagersTab(ctk.CTkFrame):
    """Shows detected license managers with action buttons."""

    def __init__(self, parent: ctk.CTkFrame, **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build()

    def _build(self) -> None:
        # ── Not-installed section label ────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="DETECTED LICENSE MANAGERS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=30, pady=(8, 6))

        # ── Manager table ──────────────────────────────────────────────────────
        container = ctk.CTkFrame(
            self, fg_color=BG_CARD, corner_radius=14,
            border_width=1, border_color=BORDER,
        )
        container.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 24))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        tree_frame = tk.Frame(container, bg=BG_TABLE)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        COLS = [
            ("manager",   "MANAGER",         220, True,  "w"),
            ("installed", "INSTALLED",         90, False, "center"),
            ("location",  "LOCATION",         360, True,  "w"),
            ("managed",   "PRODUCTS MANAGED", 160, False, "center"),
        ]

        _make_treeview_style("LVManagers.Treeview")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=[c[0] for c in COLS],
            show="headings",
            style="LVManagers.Treeview",
            selectmode="browse",
        )
        for col_id, heading, width, stretch, anchor in COLS:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, minwidth=50, stretch=stretch, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("even",      background=BG_TABLE_ROW)
        self._tree.tag_configure("odd",       background=BG_TABLE_ROW_ALT)
        self._tree.tag_configure("installed", foreground=COLOR_MANAGED)
        self._tree.tag_configure("missing",   foreground=COLOR_MISSING)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        self._empty_lbl = ctk.CTkLabel(
            container,
            text="No manager data — click  ⬡ Analyze",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        self._empty_lbl.grid(row=0, column=0, pady=40)

        # ── Action bar ─────────────────────────────────────────────────────────
        action_bar = ctk.CTkFrame(self, fg_color="transparent")
        action_bar.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 24))

        self._open_btn = ctk.CTkButton(
            action_bar,
            text="  ▶  Open Manager",
            width=155,
            height=36,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            state="disabled",
            command=self._open_manager,
        )
        self._open_btn.pack(side="left", padx=(0, 8))

        self._reveal_btn = ctk.CTkButton(
            action_bar,
            text="  ⌘  Reveal in Finder",
            width=155,
            height=36,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=BG_CARD,
            hover_color=BG_TAB_HOVER,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            state="disabled",
            command=self._reveal_in_finder,
        )
        self._reveal_btn.pack(side="left", padx=(0, 8))

        self._website_btn = ctk.CTkButton(
            action_bar,
            text="  ↗  Open Website",
            width=140,
            height=36,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=BG_CARD,
            hover_color=BG_TAB_HOVER,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            state="disabled",
            command=self._open_website,
        )
        self._website_btn.pack(side="left")

        self._installed_managers: list[InstalledManager] = []
        self._manager_rows: list[dict] = []

    def populate(self, report: LicenseVaultReport) -> None:
        self._installed_managers = report.installed_managers
        for row in self._tree.get_children():
            self._tree.delete(row)

        # Compute products-managed count per manager key
        mgr_product_count: dict[str, int] = {}
        for p in report.products:
            # Find manager key for this product's manager display name
            for mgr in report.installed_managers:
                if mgr.display_name == p.license_manager:
                    mgr_product_count[mgr.manager_key] = (
                        mgr_product_count.get(mgr.manager_key, 0) + 1
                    )
                    break

        # Build rows: installed first, then known-but-missing
        self._manager_rows = []
        installed_keys = {m.manager_key for m in report.installed_managers}

        # Installed managers
        for i, mgr in enumerate(report.installed_managers):
            row_tag = "even" if i % 2 == 0 else "odd"
            prod_count = mgr_product_count.get(mgr.manager_key, 0)
            self._tree.insert(
                "", "end",
                values=(
                    mgr.display_name,
                    "✓ Installed",
                    mgr.app_path or "—",
                    str(prod_count) if prod_count else "—",
                ),
                tags=(row_tag, "installed"),
            )
            self._manager_rows.append({"installed": True, "mgr": mgr})

        # Known managers that aren't installed (informational)
        offset = len(report.installed_managers)
        for j, mgr_def in enumerate(LICENSE_MANAGER_REGISTRY):
            if mgr_def.manager_key in installed_keys:
                continue
            i = offset + j
            row_tag = "even" if i % 2 == 0 else "odd"
            self._tree.insert(
                "", "end",
                values=(
                    mgr_def.display_name,
                    "— Not Found",
                    "—",
                    "—",
                ),
                tags=(row_tag, "missing"),
            )
            self._manager_rows.append({"installed": False, "mgr": None})

        if self._manager_rows:
            self._empty_lbl.grid_remove()
        else:
            self._empty_lbl.grid()

    def _on_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            self._open_btn.configure(state="disabled")
            self._reveal_btn.configure(state="disabled")
            self._website_btn.configure(state="disabled")
            return

        idx = self._tree.index(sel[0])
        if idx >= len(self._manager_rows):
            return
        row = self._manager_rows[idx]
        installed = row["installed"]
        mgr: InstalledManager | None = row["mgr"]

        self._open_btn.configure(state="normal" if installed else "disabled")
        self._reveal_btn.configure(state="normal" if installed else "disabled")

        # Website available via LICENSE_MANAGER_REGISTRY even if not installed
        has_website = False
        if mgr and mgr.website:
            has_website = True
        else:
            mgr_def_name = self._tree.item(sel[0], "values")[0]
            for md in LICENSE_MANAGER_REGISTRY:
                if md.display_name == mgr_def_name and md.website:
                    has_website = True
                    break
        self._website_btn.configure(state="normal" if has_website else "disabled")

    def _selected_manager(self) -> InstalledManager | None:
        sel = self._tree.selection()
        if not sel:
            return None
        idx = self._tree.index(sel[0])
        if idx >= len(self._manager_rows):
            return None
        row = self._manager_rows[idx]
        return row["mgr"] if row["installed"] else None

    def _open_manager(self) -> None:
        mgr = self._selected_manager()
        if mgr:
            mgr.open_app()

    def _reveal_in_finder(self) -> None:
        mgr = self._selected_manager()
        if mgr:
            mgr.reveal_in_finder()

    def _open_website(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._tree.index(sel[0])
        if idx >= len(self._manager_rows):
            return
        row = self._manager_rows[idx]
        mgr: InstalledManager | None = row["mgr"]
        if mgr and mgr.website:
            subprocess.run(["open", mgr.website], check=False)
            return
        # Look up from registry
        mgr_name = self._tree.item(sel[0], "values")[0]
        for md in LICENSE_MANAGER_REGISTRY:
            if md.display_name == mgr_name and md.website:
                subprocess.run(["open", md.website], check=False)
                return
