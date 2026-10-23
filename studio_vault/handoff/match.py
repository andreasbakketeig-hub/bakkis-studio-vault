"""
Match plug-in names as Live stores them in a set against what a Mac has.

One matcher for Handoff and Project check, so both give the same answer.
Live's names and the installed names differ in predictable ways only:
    "Serum_x64" / "Kickstart-64bit"   bitness suffix          → stripped
    "Serum VST3"                      format word             → stripped
    "Pro-C 2" (AU, FabFilter)         vendor left out         → vendor + name
    "FF Pro-L 2" (AU, FabFilter)      vendor abbreviated      → vendor + rest
    "Voxengo SPAN" vs "SPAN"          vendor put in front     → vendor + name
    "Pro-Q 4" vs "FabFilter Pro-Q 4"  bundle named with vendor → name without a known vendor prefix
A vendor prefix is only dropped when it is a vendor that Mac actually has, so a
short generic name ("Verb") never matches a longer product ("ValhallaVintageVerb").

Self-contained: standard library only.
"""

from __future__ import annotations

import re
from typing import Iterable

INSTALLED = "installed"
OTHER_FORMAT = "other_format"
MISSING = "missing"

_BITNESS = re.compile(r"[\s_\-]*(x64|x86_64|64[\s_\-]?bit)$", re.IGNORECASE)
_FORMAT_WORD = re.compile(r"[\s_\-]*(vst3?|au|aax|clap)$", re.IGNORECASE)
_MIN_ALIAS = 4


def key(name: str) -> str:
    """Normalised plug-in name: lower-case letters and digits, no bitness or format suffix."""
    name = _FORMAT_WORD.sub("", _BITNESS.sub("", (name or "").strip()))
    return re.sub(r"[^a-z0-9]+", "", name.lower())


class PluginIndex:
    """Formats available per plug-in name on one Mac. Entries are (name, fmt, vendor)."""

    def __init__(self, entries: Iterable[tuple[str, str, str]]) -> None:
        entries = [(n, f, v) for n, f, v in entries if n]
        self.vendors = {key(v) for _n, _f, v in entries if len(key(v)) >= 3}
        self._by_key: dict[str, set[str]] = {}
        self._au: set[tuple[str, str]] = set()
        for name, fmt, vendor in entries:
            k, v = key(name), key(vendor)
            for alias in self._aliases(k, v):
                self._by_key.setdefault(alias, set()).add(fmt)
            if fmt == "AU":
                self._au.add((k, v))

    def _aliases(self, k: str, v: str) -> set[str]:
        out = {k}
        if v:
            out.add(v + k)                              # "SPAN" by Voxengo → "voxengospan"
        for vendor in self.vendors:                     # "FabFilter Pro-Q 4" → "proq4"
            if k.startswith(vendor) and len(k) - len(vendor) >= _MIN_ALIAS:
                out.add(k[len(vendor):])
        return out

    def formats(self, name: str, vendor: str = "") -> set[str]:
        k, v = key(name), key(vendor)
        found = set(self._by_key.get(k, set()))
        if not found and v:
            found = set(self._by_key.get(v + k, set()))
            parts = name.strip().split(" ", 1)
            if not found and len(parts) == 2 and len(key(parts[0])) <= 3:
                found = set(self._by_key.get(v + key(parts[1]), set()) | self._by_key.get(key(parts[1]), set()))
        return found

    def status(self, name: str, fmt: str, vendor: str = "") -> tuple[str, list[str]]:
        """(installed | other_format | missing, formats the Mac has)."""
        have = self.formats(name, vendor)
        k, v = key(name), key(vendor)
        au_vendors = {av for (ak, av) in self._au if ak == k}
        if fmt == "AU" and v and au_vendors and v not in au_vendors and "" not in au_vendors:
            # Same AU name from another vendor is a different plug-in.
            have.discard("AU")
        if fmt in have:
            return INSTALLED, sorted(have)
        if have:
            return OTHER_FORMAT, sorted(have)
        return MISSING, []
