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
