"""
License Vault — read-only license inventory and health tracking.

Phase 1: inventory & health only.
No license modification, no activation logic, no online services.

Consumes data from:
  - app.core.scanner.Plugin          (plugin scan results)
  - app.core.music_software_scanner  (installed music apps)
  - app.core.vendor_registry         (existing vendor/manager mapping)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from app.core.scanner import Plugin
from app.core.music_software_scanner import MusicApp
from app.core.vendor_registry import VENDOR_REGISTRY, VendorRegistryEntry


# ── License Status ─────────────────────────────────────────────────────────────

class LicenseStatus(str, Enum):
    MANAGED         = "Managed"
    UNKNOWN         = "Unknown"
    MANUAL_LICENSE  = "Manual License"
    MISSING_MANAGER = "Missing Manager"
    WEBSITE_MANAGED = "Website Managed"


# ── License Manager Registry ───────────────────────────────────────────────────
# Superset of vendor_registry manager entries, keyed by manager app name.
# Each entry maps a canonical manager name to the vendor keys it serves.

@dataclass(frozen=True)
class LicenseManagerDef:
    """A known license/update manager app."""
    manager_key: str          # stable identifier
    display_name: str         # human display name
    app_name_hints: tuple[str, ...]  # substrings to match against MusicApp.name
    vendor_keys: tuple[str, ...]     # which vendor_registry entries it covers
    open_command: str = ""    # app bundle name for `open -a`
    website: str = ""


LICENSE_MANAGER_REGISTRY: tuple[LicenseManagerDef, ...] = (
    LicenseManagerDef(
        "native_access",
        "Native Access",
        ("native access",),
        ("native_instruments",),
        "Native Access",
        "https://www.native-instruments.com/",
    ),
    LicenseManagerDef(
        "waves_central",
        "Waves Central",
        ("waves central",),
        ("waves",),
        "Waves Central",
        "https://www.waves.com/",
    ),
    LicenseManagerDef(
        "izotope_portal",
        "iZotope Product Portal",
        ("izotope product portal", "product portal"),
        ("izotope",),
        "iZotope Product Portal",
        "https://www.izotope.com/",
    ),
    LicenseManagerDef(
        "arturia_software_center",
        "Arturia Software Center",
        ("arturia software center",),
        ("arturia",),
        "Arturia Software Center",
        "https://www.arturia.com/",
    ),
    LicenseManagerDef(
        "plugin_alliance_manager",
        "Plugin Alliance Installation Manager",
        ("plugin alliance installation manager", "plugin alliance",),
        ("plugin_alliance",),
        "Plugin Alliance Installation Manager",
        "https://www.plugin-alliance.com/",
    ),
    LicenseManagerDef(
        "ua_connect",
        "UA Connect",
        ("ua connect",),
        ("universal_audio",),
        "UA Connect",
        "https://www.uaudio.com/",
    ),
    LicenseManagerDef(
        "ssl_360",
        "SSL 360°",
        ("ssl 360",),
        ("ssl",),
        "SSL 360",
        "https://www.solidstatelogic.com/",
    ),
    LicenseManagerDef(
        "softube_central",
        "Softube Central",
        ("softube central",),
        ("softube",),
        "Softube Central",
        "https://www.softube.com/",
    ),
    LicenseManagerDef(
        "output_hub",
        "Output Hub",
        ("output hub",),
        ("output",),
        "Output Hub",
        "https://output.com/",
    ),
    LicenseManagerDef(
        "spitfire_audio",
        "Spitfire Audio",
        ("spitfire audio",),
        ("spitfire",),
        "Spitfire Audio",
        "https://www.spitfireaudio.com/",
    ),
    LicenseManagerDef(
        "loopcloud",
        "Loopcloud",
        ("loopcloud",),
        ("loopcloud",),
        "Loopcloud",
        "https://www.loopcloud.com/",
    ),
    LicenseManagerDef(
        "steinberg_download_assistant",
        "Steinberg Download Assistant",
        ("steinberg download assistant", "steinberg licensing", "elicenser",),
        ("steinberg",),
        "Steinberg Download Assistant",
        "https://www.steinberg.net/",
    ),
    LicenseManagerDef(
        "soundtoys",
        "Soundtoys",
        ("soundtoys",),
        ("soundtoys",),
        "Soundtoys",
        "https://www.soundtoys.com/",
    ),
)

# Vendor keys for vendors that are strictly website-managed (no app manager).
WEBSITE_MANAGED_VENDOR_KEYS: frozenset[str] = frozenset(
    entry.vendor_key
    for entry in VENDOR_REGISTRY
    if entry.website_only
)

# Build a quick lookup: vendor_key → LicenseManagerDef
_VENDOR_TO_MANAGER: dict[str, LicenseManagerDef] = {}
for _mgr in LICENSE_MANAGER_REGISTRY:
    for _vk in _mgr.vendor_keys:
        _VENDOR_TO_MANAGER[_vk] = _mgr


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InstalledManager:
    """A license manager app found on this machine."""
    manager_key: str
    display_name: str
    app_name: str       # actual app name from scan
    app_path: str       # full path
    website: str = ""

    def open_app(self) -> None:
        """Open this manager app (read-only action)."""
        if self.app_path:
            subprocess.run(["open", self.app_path], check=False)

    def reveal_in_finder(self) -> None:
        """Reveal app bundle in Finder (read-only action)."""
        if self.app_path:
            subprocess.run(["open", "-R", self.app_path], check=False)

    def open_website(self) -> None:
        if self.website:
            subprocess.run(["open", self.website], check=False)


@dataclass(frozen=True)
class LicenseProduct:
    """A single installed plugin product with license metadata."""
    product_name: str
    developer: str
    version: str
    formats: tuple[str, ...]        # e.g. ("VST3", "AU")
    vendor_key: str                 # "" if no match
    vendor_display: str             # human display name
    license_manager: str            # manager display name or ""
    license_status: LicenseStatus
    website: str = ""

    @property
    def formats_str(self) -> str:
        return ", ".join(self.formats) if self.formats else "—"


@dataclass
class VendorSummary:
    """Aggregated view of one vendor's products."""
    vendor_key: str
    display_name: str
    product_count: int
    manager_display: str
    website: str
    status: LicenseStatus
    products: list[LicenseProduct] = field(default_factory=list)


@dataclass
class LicenseVaultReport:
    """Top-level output of the License Vault engine."""
    products: list[LicenseProduct]
    vendors: list[VendorSummary]
    installed_managers: list[InstalledManager]

    # Health metrics
    total_products: int = 0
    managed_count: int = 0
    unknown_count: int = 0
    website_managed_count: int = 0
    missing_manager_count: int = 0
    manual_count: int = 0
    vendor_count: int = 0
    manager_count: int = 0


# ── Manager detection ──────────────────────────────────────────────────────────

def detect_installed_managers(
    music_apps: Sequence[MusicApp],
) -> list[InstalledManager]:
    """
    Walk *music_apps* and return one :class:`InstalledManager` per detected
    license manager.  Deduplicates by manager_key (first match wins).
    """
    found: dict[str, InstalledManager] = {}

    for app in music_apps:
        name_lower = app.name.lower()
        for mgr_def in LICENSE_MANAGER_REGISTRY:
            if mgr_def.manager_key in found:
                continue
            for hint in mgr_def.app_name_hints:
                if hint in name_lower:
                    found[mgr_def.manager_key] = InstalledManager(
                        manager_key=mgr_def.manager_key,
                        display_name=mgr_def.display_name,
                        app_name=app.name,
                        app_path=app.path,
                        website=mgr_def.website,
                    )
                    break

    return sorted(found.values(), key=lambda m: m.display_name.lower())


# ── Vendor matching ────────────────────────────────────────────────────────────

def _match_vendor_entry(developer: str) -> VendorRegistryEntry | None:
    """Return the vendor registry entry for *developer*, if any."""
    from app.core.vendor_registry import match_vendor
    return match_vendor(developer)


# ── Product classification ─────────────────────────────────────────────────────

def _group_plugins_by_product(plugins: Sequence[Plugin]) -> list[tuple[str, str, list[Plugin]]]:
    """
    Group *plugins* by (name_lower, developer_lower) and return
    [(canonical_name, canonical_dev, [plugins])].
    """
    groups: dict[tuple[str, str], list[Plugin]] = {}
    canonical: dict[tuple[str, str], tuple[str, str]] = {}

    for p in plugins:
        key = (p.name.lower().strip(), p.developer.lower().strip())
        if key not in groups:
            groups[key] = []
            canonical[key] = (p.name, p.developer)
        groups[key].append(p)

    return [
        (canonical[k][0], canonical[k][1], v)
        for k, v in groups.items()
    ]


def classify_products(
    plugins: Sequence[Plugin],
    installed_managers: list[InstalledManager],
) -> list[LicenseProduct]:
    """
    For each unique plugin product in *plugins*, determine its license status
    by matching its developer against the vendor registry and checking whether
    the relevant license manager is installed.
    """
    installed_keys: set[str] = {m.manager_key for m in installed_managers}
    results: list[LicenseProduct] = []

    for product_name, developer, group in _group_plugins_by_product(plugins):
        formats = tuple(sorted({p.fmt for p in group}))
        version = next((p.version for p in group if p.version), "")

        vendor_entry = _match_vendor_entry(developer)

        if vendor_entry is None:
            status = LicenseStatus.UNKNOWN
            vendor_key = ""
            vendor_display = developer or "Unknown"
            license_manager = ""
            website = ""
        else:
            vendor_key = vendor_entry.vendor_key
            vendor_display = vendor_entry.display_name
            website = vendor_entry.website_url
            mgr_def = _VENDOR_TO_MANAGER.get(vendor_key)
            if mgr_def is not None:
                # Known manager exists for this vendor — check if installed
                if mgr_def.manager_key in installed_keys:
                    status = LicenseStatus.MANAGED
                    license_manager = mgr_def.display_name
                else:
                    status = LicenseStatus.MISSING_MANAGER
                    license_manager = mgr_def.display_name
            elif vendor_entry.website_only:
                # No app manager — vendor explicitly uses website licensing
                status = LicenseStatus.WEBSITE_MANAGED
                license_manager = vendor_entry.manager_display
            else:
                # Vendor known but no manager mapping and not website-only → manual
                status = LicenseStatus.MANUAL_LICENSE
                license_manager = ""

        results.append(LicenseProduct(
            product_name=product_name,
            developer=developer,
            version=version,
            formats=formats,
            vendor_key=vendor_key,
            vendor_display=vendor_display,
            license_manager=license_manager,
            license_status=status,
            website=website,
        ))

    return sorted(results, key=lambda p: (p.vendor_display.lower(), p.product_name.lower()))


# ── Vendor summary ─────────────────────────────────────────────────────────────

def build_vendor_summaries(products: list[LicenseProduct]) -> list[VendorSummary]:
    """Aggregate *products* into per-vendor :class:`VendorSummary` objects."""
    summaries: dict[str, VendorSummary] = {}

    for product in products:
        key = product.vendor_key or f"__unknown__{product.developer.lower()}"
        if key not in summaries:
            # Determine vendor-level status from registry
            vendor_entry = next(
                (e for e in VENDOR_REGISTRY if e.vendor_key == product.vendor_key),
                None,
            )
            website = vendor_entry.website_url if vendor_entry else product.website

            summaries[key] = VendorSummary(
                vendor_key=key,
                display_name=product.vendor_display,
                product_count=0,
                manager_display=product.license_manager or "—",
                website=website,
                status=product.license_status,
            )
        summaries[key].product_count += 1
        summaries[key].products.append(product)

        # Upgrade vendor status if any product is better classified
        _upgrade_vendor_status(summaries[key], product.license_status)

    return sorted(summaries.values(), key=lambda v: v.display_name.lower())


_STATUS_RANK = {
    LicenseStatus.MANAGED:         0,
    LicenseStatus.WEBSITE_MANAGED: 1,
    LicenseStatus.MANUAL_LICENSE:  2,
    LicenseStatus.MISSING_MANAGER: 3,
    LicenseStatus.UNKNOWN:         4,
}


def _upgrade_vendor_status(summary: VendorSummary, status: LicenseStatus) -> None:
    """Set *summary* status to the 'best' (lowest rank) seen so far."""
    if _STATUS_RANK[status] < _STATUS_RANK[summary.status]:
        summary.status = status


# ── Health metrics ─────────────────────────────────────────────────────────────

def _compute_health(
    products: list[LicenseProduct],
    vendors: list[VendorSummary],
    installed_managers: list[InstalledManager],
) -> dict[str, int]:
    from collections import Counter
    counts = Counter(p.license_status for p in products)
    return {
        "total_products":       len(products),
        "managed_count":        counts[LicenseStatus.MANAGED],
        "website_managed_count":counts[LicenseStatus.WEBSITE_MANAGED],
        "missing_manager_count":counts[LicenseStatus.MISSING_MANAGER],
        "manual_count":         counts[LicenseStatus.MANUAL_LICENSE],
        "unknown_count":        counts[LicenseStatus.UNKNOWN],
        "vendor_count":         len(vendors),
        "manager_count":        len(installed_managers),
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def build_license_vault_report(
    plugins: Sequence[Plugin],
    music_apps: Sequence[MusicApp],
) -> LicenseVaultReport:
    """
    Build a complete :class:`LicenseVaultReport` from plugin and music-app
    scan results.  Pure read-only computation — no I/O, no network.
    """
    installed_managers = detect_installed_managers(music_apps)
    products = classify_products(plugins, installed_managers)
    vendors = build_vendor_summaries(products)
    health = _compute_health(products, vendors, installed_managers)

    return LicenseVaultReport(
        products=products,
        vendors=vendors,
        installed_managers=installed_managers,
        **health,
    )
