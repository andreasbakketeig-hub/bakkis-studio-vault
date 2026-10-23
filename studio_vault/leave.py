"""
"Before you leave this Mac": what to do on the old Mac before moving to a new one.

Built from this Mac's snapshot. Steps:
  1. save a fresh snapshot and export it (the new Mac builds its checklist from it)
  2. deactivate licenses that are tied to this computer (Waves, iLok, Steinberg …)
  3. copy the snapshot file to the new Mac

Read-only like everything else: the app only tells you what to do. Manual ticks
are kept with the checklist ticks under the id LEAVE_ID.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from studio_vault import checklist
from studio_vault.snapshot import Snapshot
from studio_vault.vendors import ILOK_DEACTIVATE, vendor_group

LEAVE_ID = "leave-this-mac"

STEP_SNAPSHOT = "step:snapshot"
STEP_COPY = "step:copy"
STEP_BACKUP = "step:backup"


@dataclass
class LeaveItem:
    id: str
    title: str
    detail: str = ""
    products: list[str] = field(default_factory=list)   # what on this Mac the step is about
    url: str = ""
    done: bool = False


@dataclass
class LeaveList:
    snapshot_id: str
    snapshot_name: str
    snapshot_created_at: str
    snapshot_is_fresh: bool
    snapshot: list[LeaveItem] = field(default_factory=list)
    backup: list[LeaveItem] = field(default_factory=list)
    folders: list[dict] = field(default_factory=list)     # presets / user content to back up
    licenses: list[LeaveItem] = field(default_factory=list)
    finish: list[LeaveItem] = field(default_factory=list)

    def all_items(self) -> list[LeaveItem]:
        return self.snapshot + self.backup + self.licenses + self.finish


def _is_fresh(created_at: str, now: datetime.datetime | None = None) -> bool:
    try:
        made = datetime.datetime.fromisoformat(created_at)
    except ValueError:
        return False
    return (now or datetime.datetime.now()) - made < datetime.timedelta(days=1)


def build(this_mac: Snapshot, manual: set[str] | None = None) -> LeaveList:
    ticks = manual if manual is not None else checklist.load_state(LEAVE_ID)
    fresh = _is_fresh(this_mac.created_at)
    out = LeaveList(this_mac.id, this_mac.name, this_mac.created_at, fresh)

    out.snapshot.append(LeaveItem(
        STEP_SNAPSHOT, "Scan this Mac and export the snapshot",
        "Scan right before you move so nothing is missed, then use Export… to save the .studiovault file.",
        done=STEP_SNAPSHOT in ticks))

    if this_mac.content:
        out.backup.append(LeaveItem(
            STEP_BACKUP, "Back up presets and your own content",
            "Installers bring plug-ins back, not your presets, patches and libraries. "
            "Copy these folders to a backup drive (or let Migration Assistant or Time Machine bring them over).",
            done=STEP_BACKUP in ticks))
        out.folders = [{"label": c.label, "path": c.path, "size": c.size, "approximate": c.approximate}
                       for c in this_mac.content]

    # Vendors on this Mac whose licenses are tied to the computer.
    by_vendor: dict[str, LeaveItem] = {}
    names: dict[str, set[str]] = {}
    for p in this_mac.plugins:
        key, name, vendor = vendor_group(p.developer, p.bundle_id)
        if vendor is None or not vendor.deactivate:
            continue
        item = by_vendor.get(key)
        if item is None:
            item_id = f"license:{key}"
            item = by_vendor[key] = LeaveItem(item_id, name, vendor.deactivate,
                                              url=vendor.download_url, done=item_id in ticks)
            names[key] = set()
        # Waves installs one "WaveShell" per format and version; the plug-ins live inside it.
        names[key].add("WaveShell (all Waves plug-ins)" if p.name.lower().startswith("waveshell") else p.name)
    for key, item in by_vendor.items():
        item.products = sorted(names[key], key=str.lower)
    # iLok License Manager installed but no known iLok vendor matched: still worth a reminder.
    has_ilok_app = any("ilok" in a.name.lower() for a in this_mac.apps)
    if has_ilok_app and not any(i.detail == ILOK_DEACTIVATE for i in by_vendor.values()):
        by_vendor["ilok"] = LeaveItem("license:ilok", "iLok", ILOK_DEACTIVATE, done="license:ilok" in ticks)
    out.licenses = sorted(by_vendor.values(), key=lambda i: i.title.lower())

    out.finish.append(LeaveItem(
        STEP_COPY, "Copy the snapshot file to the new Mac",
        "AirDrop, iCloud Drive or a USB stick. On the new Mac, open the app and choose Import from another Mac…",
        done=STEP_COPY in ticks))
    return out
