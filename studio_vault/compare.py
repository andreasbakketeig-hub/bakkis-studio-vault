"""
Compare two snapshots: what was added, removed or updated between *old* and *new*.

Used for "What changed since <date>" (old = last snapshot of this Mac, new = the
current scan) and for comparing any two saved snapshots. Read-only.

Matching keys:
    plug-ins  normalised product name + format ("Serum VST3" and "Serum" match)
    apps      app name, case-insensitive
    hardware  name with punctuation/spacing removed ("BiG SiX" == "Big Six")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, TypeVar

from studio_vault.scanners.plugins import normalize_product_name
from studio_vault.snapshot import SnapApp, SnapHardware, SnapPlugin, Snapshot

ADDED = "added"
REMOVED = "removed"
UPDATED = "updated"

CAT_PLUGINS = "plugins"
CAT_APPS = "apps"
CAT_HARDWARE = "hardware"


@dataclass(frozen=True)
class Change:
    kind: str            # added | removed | updated
    category: str        # plugins | apps | hardware
    name: str
    vendor: str = ""
    fmt: str = ""        # plug-ins only
    old_version: str = ""
    new_version: str = ""
    direction: int = 0   # updated only: 1 newer, -1 older, 0 unknown


@dataclass
class Comparison:
    old: Snapshot
    new: Snapshot
    changes: list[Change] = field(default_factory=list)

    def of(self, category: str, kind: str | None = None) -> list[Change]:
        return [c for c in self.changes
                if c.category == category and (kind is None or c.kind == kind)]

    @property
    def is_empty(self) -> bool:
        return not self.changes

    def counts(self) -> dict[str, dict[str, int]]:
        """{category: {added, removed, updated}} for summary chips."""
        out = {cat: {ADDED: 0, REMOVED: 0, UPDATED: 0}
               for cat in (CAT_PLUGINS, CAT_APPS, CAT_HARDWARE)}
        for c in self.changes:
            out[c.category][c.kind] += 1
        return out


# ── Version ordering ──────────────────────────────────────────────────────────

def compare_versions(a: str, b: str) -> int:
    """
    1 if *b* is newer than *a*, -1 if older, 0 if equal or not comparable.
    Compares the leading numeric parts ("1.2.10" > "1.2.9", "2.0 beta" ~ "2.0").
    """
    def parts(v: str) -> tuple[int, ...] | None:
        m = re.match(r"\s*v?(\d+(?:\.\d+)*)", v or "")
        if not m:
            return None
        nums = [int(x) for x in m.group(1).split(".")]
        while len(nums) > 1 and nums[-1] == 0:
            nums.pop()
        return tuple(nums)

    pa, pb = parts(a), parts(b)
    if pa is None or pb is None or pa == pb:
        return 0
    return 1 if pb > pa else -1


# ── Comparison ────────────────────────────────────────────────────────────────

def _hardware_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


T = TypeVar("T", SnapPlugin, SnapApp, SnapHardware)


def _index(items: Iterable[T], key: Callable[[T], object]) -> dict[object, T]:
    out: dict[object, T] = {}
    for item in items:
        out.setdefault(key(item), item)
    return out


def compare(old: Snapshot, new: Snapshot) -> Comparison:
    result = Comparison(old=old, new=new)

    def diff(category: str, old_items, new_items, key, vendor, fmt, version) -> None:
        before = _index(old_items, key)
        after = _index(new_items, key)
        for k, item in after.items():
            if k not in before:
                result.changes.append(Change(ADDED, category, item.name, vendor(item), fmt(item),
                                             new_version=version(item)))
        for k, item in before.items():
            if k not in after:
                result.changes.append(Change(REMOVED, category, item.name, vendor(item), fmt(item),
                                             old_version=version(item)))
                continue
            old_v, new_v = version(item), version(after[k])
            if old_v and new_v and old_v != new_v:
                result.changes.append(Change(
                    UPDATED, category, after[k].name, vendor(after[k]) or vendor(item), fmt(item),
                    old_version=old_v, new_version=new_v, direction=compare_versions(old_v, new_v),
                ))

    diff(CAT_PLUGINS, old.plugins, new.plugins,
         key=lambda p: (normalize_product_name(p.name), p.fmt),
         vendor=lambda p: p.developer, fmt=lambda p: p.fmt, version=lambda p: p.version)
    diff(CAT_APPS, old.apps, new.apps,
         key=lambda a: a.name.lower(),
         vendor=lambda a: a.developer, fmt=lambda a: "", version=lambda a: a.version)
    diff(CAT_HARDWARE, old.hardware, new.hardware,
         key=lambda h: _hardware_key(h.name),
         vendor=lambda h: h.vendor, fmt=lambda h: "", version=lambda h: "")

    order = {ADDED: 0, UPDATED: 1, REMOVED: 2}
    result.changes.sort(key=lambda c: (c.category, order[c.kind], c.name.lower(), c.fmt))
    return result


# ── Side by side (two Macs, product level, grouped by vendor) ─────────────────

ONLY_A = "only_a"
ONLY_B = "only_b"
DIFFERENT = "different"
SAME = "same"


@dataclass
class SideRow:
    category: str            # plugins | apps | hardware
    name: str
    status: str              # only_a | only_b | different | same
    a_formats: list[str] = field(default_factory=list)
    b_formats: list[str] = field(default_factory=list)
    a_version: str = ""
    b_version: str = ""
    note: str = ""           # what differs, in words


@dataclass
class SideGroup:
    key: str
    name: str
    download_url: str = ""
    rows: list[SideRow] = field(default_factory=list)


@dataclass
class SideBySide:
    a: Snapshot
    b: Snapshot
    groups: list[SideGroup] = field(default_factory=list)   # plug-ins and apps, by vendor
    hardware: list[SideRow] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {ONLY_A: 0, ONLY_B: 0, DIFFERENT: 0, SAME: 0}
        for row in [r for g in self.groups for r in g.rows] + self.hardware:
            out[row.status] += 1
        return out


def _ordered(formats: set[str]) -> list[str]:
    from studio_vault.scanners.plugins import FORMAT_ORDER
    return [f for f in FORMAT_ORDER if f in formats] + sorted(formats - set(FORMAT_ORDER))


def _plugin_products(s: Snapshot) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in s.plugins:
        g = out.setdefault(normalize_product_name(p.name), {
            "name": p.name, "formats": set(), "version": "", "developer": "", "bundle_id": ""})
        g["formats"].add(p.fmt)
        for k in ("version", "developer", "bundle_id"):
            g[k] = g[k] or getattr(p, k)
    return out


def side_by_side(a: Snapshot, b: Snapshot) -> SideBySide:
    """Everything on Mac A and Mac B, per product, grouped by vendor."""
    from studio_vault.vendors import OTHER_GROUP_KEY, vendor_group

    result = SideBySide(a=a, b=b)
    groups: dict[str, SideGroup] = {}

    def group(developer: str, bundle_id: str = "") -> SideGroup:
        key, name, vendor = vendor_group(developer, bundle_id)
        if key not in groups:
            groups[key] = SideGroup(key, name, vendor.download_url if vendor else "")
        return groups[key]

    pa, pb = _plugin_products(a), _plugin_products(b)
    for key in pa.keys() | pb.keys():
        x, y = pa.get(key), pb.get(key)
        ref = x or y
        row = SideRow("plugins", ref["name"], SAME,
                      _ordered(x["formats"]) if x else [], _ordered(y["formats"]) if y else [],
                      x["version"] if x else "", y["version"] if y else "")
        if not y:
            row.status = ONLY_A
        elif not x:
            row.status = ONLY_B
        else:
            notes = []
            if x["formats"] != y["formats"]:
                if x["formats"] - y["formats"]:
                    notes.append(f"only A has {', '.join(_ordered(x['formats'] - y['formats']))}")
                if y["formats"] - x["formats"]:
                    notes.append(f"only B has {', '.join(_ordered(y['formats'] - x['formats']))}")
            if row.a_version and row.b_version and compare_versions(row.a_version, row.b_version) != 0:
                notes.append(f"version {row.a_version} vs {row.b_version}")
            if notes:
                row.status, row.note = DIFFERENT, "; ".join(notes)
        group(ref["developer"], ref["bundle_id"]).rows.append(row)

    aa = {x.name.lower(): x for x in a.apps}
    ab = {x.name.lower(): x for x in b.apps}
    for key in aa.keys() | ab.keys():
        x, y = aa.get(key), ab.get(key)
        ref = x or y
        row = SideRow("apps", ref.name, SAME, a_version=x.version if x else "", b_version=y.version if y else "")
        if not y:
            row.status = ONLY_A
        elif not x:
            row.status = ONLY_B
        elif x.version and y.version and compare_versions(x.version, y.version) != 0:
            row.status, row.note = DIFFERENT, f"version {x.version} vs {y.version}"
        group(ref.developer).rows.append(row)

    ha = {_hardware_key(h.name): h for h in a.hardware}
    hb = {_hardware_key(h.name): h for h in b.hardware}
    for key in ha.keys() | hb.keys():
        ref = ha.get(key) or hb.get(key)
        status = SAME if key in ha and key in hb else (ONLY_A if key in ha else ONLY_B)
        result.hardware.append(SideRow("hardware", ref.name, status, note=ref.details or ref.vendor))

    order = {ONLY_A: 0, ONLY_B: 1, DIFFERENT: 2, SAME: 3}
    for g in groups.values():
        g.rows.sort(key=lambda r: (order[r.status], r.category != "apps", r.name.lower()))
    result.groups = sorted(groups.values(), key=lambda g: (g.key == OTHER_GROUP_KEY, g.name.lower()))
    result.hardware.sort(key=lambda r: (order[r.status], r.name.lower()))
    return result
