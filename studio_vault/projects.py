"""
Project check: which plug-ins an Ableton Live project (.als) needs, and whether
they are on this Mac (or in another Mac's snapshot).

An .als file is gzip-compressed XML. Plug-in devices are stored as
    <VstPluginInfo>  … <PlugName Value="LFOTool"/> <Path Value="/Library/…/LFOTool.vst"/>
    <Vst3PluginInfo> … <Name Value="Serum"/>
    <AuPluginInfo>   … <Name Value="LFOTool"/> <Manufacturer Value="Xfer Records"/>
Live does not swap formats on its own: a project that uses the AU of a plug-in
needs the AU, even if the VST3 is installed. That case is reported separately.

Read-only: project files are only read, never changed.
"""

from __future__ import annotations

import gzip
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from studio_vault.scanners.plugins import normalize_product_name
from studio_vault.snapshot import Snapshot, scrub_path

MAX_XML_BYTES = 256 * 1024 * 1024   # refuse absurdly large (or malicious) files
MAX_PROJECTS = 10_000

INSTALLED = "installed"
OTHER_FORMAT = "other_format"
MISSING = "missing"

_TAGS = {"VstPluginInfo": "VST", "Vst3PluginInfo": "VST3", "AuPluginInfo": "AU"}


@dataclass(frozen=True)
class ProjectPlugin:
    name: str
    fmt: str
    vendor: str = ""


@dataclass
class Project:
    name: str
    path: str                     # scrubbed (~/…)
    live_version: str = ""
    plugins: list[ProjectPlugin] = field(default_factory=list)
    error: str = ""


@dataclass
class PluginCheck:
    name: str
    fmt: str
    vendor: str
    status: str                   # installed | other_format | missing
    have_formats: list[str] = field(default_factory=list)


@dataclass
class ProjectCheck:
    project: Project
    plugins: list[PluginCheck]

    @property
    def missing(self) -> int:
        return sum(1 for p in self.plugins if p.status != INSTALLED)


# ── Parsing ───────────────────────────────────────────────────────────────────

def _value(el: ET.Element, child: str) -> str:
    node = el.find(child)
    return (node.get("Value") or "").strip() if node is not None else ""


def parse_als(path: Path | str) -> Project:
    path = Path(path)
    project = Project(name=path.stem, path=scrub_path(str(path)))
    try:
        with path.open("rb") as raw:
            magic = raw.read(2)
    except OSError:
        project.error = "Could not open this file."
        return project
    if not magic:
        project.error = "The file is empty."
        return project
    if magic != b"\x1f\x8b":
        project.error = ("Saved by Live 7 or older, which used another file format. "
                         "Open it in Live and save it to check it here.")
        return project
    try:
        with gzip.open(path, "rb") as fh:
            data = fh.read(MAX_XML_BYTES + 1)
        if len(data) > MAX_XML_BYTES:
            raise ValueError("file too large")
        root = ET.fromstring(data)
    except (OSError, EOFError, ValueError, ET.ParseError) as exc:
        project.error = f"Could not read this project ({exc.__class__.__name__})."
        return project
    if root.tag != "Ableton":
        project.error = "Not an Ableton Live set."
        return project
    project.live_version = (root.get("Creator") or "").replace("Ableton Live", "").strip()

    seen: set[tuple[str, str]] = set()
    for tag, fmt in _TAGS.items():
        for el in root.iter(tag):
            if fmt == "VST":
                name = _value(el, "PlugName") or Path(_value(el, "Path")).stem
                vendor = ""
            else:
                name, vendor = _value(el, "Name"), _value(el, "Manufacturer")
            if not name or (name.lower(), fmt) in seen:
                continue
            seen.add((name.lower(), fmt))
            project.plugins.append(ProjectPlugin(name, fmt, vendor))
    project.plugins.sort(key=lambda p: (p.name.lower(), p.fmt))
    return project


def find_projects(folder: Path | str, limit: int = MAX_PROJECTS) -> list[Path]:
    """All .als files under *folder*, skipping Live's Backup folders and hidden folders."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "Backup"]
        for name in filenames:
            if name.lower().endswith(".als") and not name.startswith("._"):
                found.append(Path(dirpath) / name)
                if len(found) >= limit:
                    return sorted(found)
    return sorted(found)


# ── Checking against a Mac ────────────────────────────────────────────────────

_BITNESS = re.compile(r"[\s_\-]*(x64|x86_64|64[\s_\-]?bit)$", re.IGNORECASE)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_product_name(_BITNESS.sub("", name.strip())))


class _Installed:
    """Formats per product on a Mac, with the fuzzy lookups Live's names need."""

    def __init__(self, target: Snapshot) -> None:
        self.by_key: dict[str, set[str]] = {}
        for p in target.plugins:
            self.by_key.setdefault(_key(p.name), set()).add(p.fmt)
        self._cache: dict[tuple[str, str], set[str]] = {}

    def formats(self, name: str, vendor: str = "") -> set[str]:
        k, v = _key(name), re.sub(r"[^a-z0-9]+", "", vendor.lower())
        hit = self._cache.get((k, v))
        if hit is not None:
            return hit
        found = set(self.by_key.get(k, set()))
        if not found and v:
            # AU names in Live leave out the vendor ("Pro-C 2" for "FabFilter Pro-C 2"),
            # or abbreviate it ("FF Pro-L 2").
            found = set(self.by_key.get(v + k, set()))
            rest = name.strip().split(" ", 1)
            if not found and len(rest) == 2:
                found = set(self.by_key.get(v + _key(rest[1]), set()))
        if not found and len(k) >= 4:
            # "SPAN" vs "Voxengo SPAN", and the other way round.
            for key, fmts in self.by_key.items():
                if len(key) >= 4 and (key.endswith(k) or k.endswith(key)):
                    found |= fmts
        self._cache[(k, v)] = found
        return found


def check(project: Project, target: Snapshot, installed: _Installed | None = None) -> ProjectCheck:
    have_on_mac = installed or _Installed(target)
    results: list[PluginCheck] = []
    for p in project.plugins:
        have = have_on_mac.formats(p.name, p.vendor)
        if p.fmt in have:
            status = INSTALLED
        elif have:
            status = OTHER_FORMAT
        else:
            status = MISSING
        results.append(PluginCheck(p.name, p.fmt, p.vendor, status, sorted(have)))
    order = {MISSING: 0, OTHER_FORMAT: 1, INSTALLED: 2}
    results.sort(key=lambda r: (order[r.status], r.name.lower()))
    return ProjectCheck(project, results)


def check_all(projects: Iterable[Project], target: Snapshot) -> list[ProjectCheck]:
    installed = _Installed(target)
    checks = [check(p, target, installed) for p in projects]
    checks.sort(key=lambda c: (-c.missing, c.project.name.lower()))
    return checks


def missing_summary(checks: Iterable[ProjectCheck]) -> list[dict]:
    """Plug-ins missing (or in another format) across projects, most needed first."""
    tally: dict[tuple[str, str], dict] = {}
    for c in checks:
        for p in c.plugins:
            if p.status == INSTALLED:
                continue
            row = tally.setdefault((p.name.lower(), p.fmt), {
                "name": p.name, "fmt": p.fmt, "vendor": p.vendor, "status": p.status,
                "have_formats": p.have_formats, "projects": 0})
            row["projects"] += 1
    return sorted(tally.values(), key=lambda r: (-r["projects"], r["name"].lower()))


def parse_many(paths: Iterable[Path], progress: Callable[[int, int], None] | None = None,
               cancelled: Callable[[], bool] | None = None) -> list[Project]:
    paths = list(paths)
    out: list[Project] = []
    for i, path in enumerate(paths):
        if cancelled is not None and cancelled():
            break
        out.append(parse_als(path))
        if progress is not None and (i % 25 == 0 or i == len(paths) - 1):
            progress(i + 1, len(paths))
    return out
