"""
New-Mac migration checklist.

Built from a snapshot of the old Mac (*source*) and the current state of this
Mac (*current*, a fresh scan or the latest snapshot). Software is grouped by
vendor so each group says where to get it, which app installs it and how it is
licensed. Items tick off automatically when *current* has them; anything else
can be ticked by hand and that state is saved per source snapshot.

Plug-ins are listed per product, not per format: installing Serum once usually
brings back VST3, AU and CLAP together. A product that is back in some formats
but not all is "partial".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from studio_vault import config
from studio_vault.scanners.plugins import FORMAT_ORDER, normalize_product_name
from studio_vault.snapshot import Snapshot
from studio_vault.vendors import (
    LICENSE_ACCOUNT,
    LICENSE_APP_STORE,
    LICENSE_ILOK,
    LICENSE_SERIAL,
    LICENSE_UNKNOWN,
    Vendor,
    OTHER_GROUP_KEY,
    developer_group,
    installed_manager,
    match_vendor,
)

KIND_PLUGIN = "plugin"
KIND_APP = "app"
KIND_HARDWARE = "hardware"

STATUS_INSTALLED = "installed"
STATUS_PARTIAL = "partial"
STATUS_MISSING = "missing"



@dataclass
class ChecklistItem:
    id: str                       # stable across rebuilds, used for manual ticks
    kind: str                     # plugin | app | hardware
    name: str
    version: str = ""             # version on the old Mac
    formats: list[str] = field(default_factory=list)          # plug-ins: formats on the old Mac
    missing_formats: list[str] = field(default_factory=list)  # plug-ins: formats not back yet
    category: str = ""            # apps: DAW, Plugin Manager … / hardware: device type
    vendor: str = ""              # hardware only
    download_url: str = ""        # hardware only: vendor driver page when known
    status: str = STATUS_MISSING  # automatic, from the current scan
    manual_done: bool = False

    @property
    def done(self) -> bool:
        return self.status == STATUS_INSTALLED or self.manual_done


@dataclass
class VendorGroup:
    key: str
    name: str
    manager_app: str = ""
    manager_installed: str = ""   # installed manager app name on this Mac, "" if not
    license_system: str = LICENSE_UNKNOWN
    download_url: str = ""
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.items if i.done)

    @property
    def done(self) -> bool:
        return self.done_count == len(self.items)

    @property
    def next_step(self) -> str:
        return next_step(self)


@dataclass
class Checklist:
    source_id: str
    source_name: str
    source_created_at: str
    groups: list[VendorGroup] = field(default_factory=list)   # software, by vendor
    hardware: list[ChecklistItem] = field(default_factory=list)

    def all_items(self) -> list[ChecklistItem]:
        return [i for g in self.groups for i in g.items] + list(self.hardware)

    @property
    def total(self) -> int:
        return len(self.all_items())

    @property
    def done_count(self) -> int:
        return sum(1 for i in self.all_items() if i.done)


# ── Next step text ────────────────────────────────────────────────────────────

def next_step(group: VendorGroup) -> str:
    """One plain sentence telling the user what to do for this vendor."""
    if group.done:
        return "Done."
    if group.manager_app:
        if group.manager_installed:
            return f"Open {group.manager_installed}, sign in and install the missing items."
        return f"Install {group.manager_app}, sign in and install the missing items."
    if group.license_system == LICENSE_ILOK:
        return "Download the installers from the vendor's site and activate them in iLok License Manager."
    if group.license_system == LICENSE_SERIAL:
        return "Download the installers from the vendor's site and enter your serial or license file."
    if group.license_system == LICENSE_ACCOUNT:
        return "Sign in on the vendor's site, then download and install the missing items."
    if group.license_system == LICENSE_APP_STORE:
        return "Reinstall from the Mac App Store (Purchased)."
    if group.download_url:
        return "Download the missing items from the vendor's site."
    return "Find the installers for these items (check your e-mail receipts)."


# ── Grouping helpers ──────────────────────────────────────────────────────────

def _item_id(kind: str, name: str) -> str:
    return f"{kind}:{re.sub(r'[^a-z0-9]+', '', name.lower())}"


def _ordered_formats(formats: set[str]) -> list[str]:
    return [f for f in FORMAT_ORDER if f in formats] + sorted(formats - set(FORMAT_ORDER))


# ── Building ──────────────────────────────────────────────────────────────────

def build(source: Snapshot, current: Snapshot, manual_done: set[str] | None = None) -> Checklist:
    """Checklist for getting *source*'s software and hardware onto the Mac described by *current*."""
    manual = manual_done if manual_done is not None else load_state(source.id)
    groups: dict[str, VendorGroup] = {}

    def group_for(developer: str, bundle_id: str = "") -> VendorGroup:
        vendor: Vendor | None = match_vendor(developer, bundle_id)
        if vendor is not None:
            key = vendor.key
            if key not in groups:
                groups[key] = VendorGroup(
                    key=key, name=vendor.name, manager_app=vendor.manager_app,
                    manager_installed=installed_manager(vendor, current.apps),
                    license_system=vendor.license_system, download_url=vendor.download_url,
                )
            return groups[key]
        key, name = developer_group(developer)
        if key not in groups:
            groups[key] = VendorGroup(key=key, name=name)
        return groups[key]

    # Plug-ins, one item per product.
    current_formats: dict[str, set[str]] = {}
    for p in current.plugins:
        current_formats.setdefault(normalize_product_name(p.name), set()).add(p.fmt)

    products: dict[str, list] = {}
    for p in source.plugins:
        products.setdefault(normalize_product_name(p.name), []).append(p)

    for key, copies in products.items():
        rep = copies[0]
        developer = next((c.developer for c in copies if c.developer), "")
        bundle_id = next((c.bundle_id for c in copies if c.bundle_id), "")
        formats = {c.fmt for c in copies}
        have = current_formats.get(key, set())
        missing = formats - have
        status = STATUS_INSTALLED if not missing else (STATUS_PARTIAL if have else STATUS_MISSING)
        item_id = _item_id(KIND_PLUGIN, key)
        group_for(developer, bundle_id).items.append(ChecklistItem(
            id=item_id, kind=KIND_PLUGIN, name=rep.name,
            version=next((c.version for c in copies if c.version), ""),
            formats=_ordered_formats(formats), missing_formats=_ordered_formats(missing),
            status=status, manual_done=item_id in manual,
        ))

    # Apps.
    current_apps = {a.name.lower() for a in current.apps}
    for a in source.apps:
        item_id = _item_id(KIND_APP, a.name)
        group_for(a.developer).items.append(ChecklistItem(
            id=item_id, kind=KIND_APP, name=a.name, version=a.version, category=a.category,
            status=STATUS_INSTALLED if a.name.lower() in current_apps else STATUS_MISSING,
            manual_done=item_id in manual,
        ))

    # Hardware: "connected and working on this Mac" means it shows up in the current scan.
    current_hw = {re.sub(r"[^a-z0-9]+", "", h.name.lower()) for h in current.hardware}
    hardware: list[ChecklistItem] = []
    for h in source.hardware:
        item_id = _item_id(KIND_HARDWARE, h.name)
        hw_vendor = match_vendor(h.vendor)
        hardware.append(ChecklistItem(
            id=item_id, kind=KIND_HARDWARE, name=h.name, category=h.device_type,
            vendor=h.vendor, download_url=hw_vendor.download_url if hw_vendor else "",
            status=STATUS_INSTALLED if item_id.split(":", 1)[1] in current_hw else STATUS_MISSING,
            manual_done=item_id in manual,
        ))

    for g in groups.values():
        g.items.sort(key=lambda i: (i.kind != KIND_APP, i.name.lower()))
    ordered = sorted(groups.values(), key=lambda g: (g.key == OTHER_GROUP_KEY, g.name.lower()))
    hardware.sort(key=lambda i: i.name.lower())

    return Checklist(
        source_id=source.id, source_name=source.name, source_created_at=source.created_at,
        groups=ordered, hardware=hardware,
    )


# ── Manual tick state ─────────────────────────────────────────────────────────

def _state_path(source_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9]+", "", source_id) or "unknown"
    return config.checklists_dir() / f"{safe}.json"


def load_state(source_id: str) -> set[str]:
    try:
        data = json.loads(_state_path(source_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    done = data.get("done") if isinstance(data, dict) else None
    return {x for x in done if isinstance(x, str)} if isinstance(done, list) else set()


def set_done(source_id: str, item_id: str, done: bool) -> set[str]:
    """Tick or untick *item_id* by hand. Returns the new set of manual ticks."""
    state = load_state(source_id)
    if done:
        state.add(item_id)
    else:
        state.discard(item_id)
    path = _state_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"done": sorted(state)}, indent=1), encoding="utf-8")
    tmp.replace(path)
    return state
