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

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from studio_vault.handoff import als
from studio_vault.handoff.match import PluginIndex
from studio_vault.snapshot import Snapshot, scrub_path

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

def parse_als(path: Path | str) -> Project:
    """The plug-ins a set uses, read with the Handoff reader (one reader for the whole app)."""
    path = Path(path)
    project = Project(name=path.stem, path=scrub_path(str(path)))
    try:
        live_set = als.read(path)
    except als.AlsError as exc:
        project.error = str(exc)
        return project
    project.live_version = live_set.live_version
    project.plugins = [ProjectPlugin(p.name, p.fmt, p.vendor) for p in live_set.plugins]
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

def _index(target: Snapshot) -> PluginIndex:
    """What *target* has, with the names Live stores (AU components, VST3 classes) as well."""
    entries: list[tuple[str, str, str]] = []
    for p in target.plugins:
        entries.append((p.name, p.fmt, p.developer))
        for live_name in p.live_names:
            vendor, _, name = live_name.partition(": ") if p.fmt == "AU" else ("", "", live_name)
            entries.append((name or live_name, p.fmt, vendor or p.developer))
    return PluginIndex(entries)


def check(project: Project, target: Snapshot, installed: PluginIndex | None = None) -> ProjectCheck:
    index = installed or _index(target)
    results: list[PluginCheck] = []
    for p in project.plugins:
        status, have = index.status(p.name, p.fmt, p.vendor)
        results.append(PluginCheck(p.name, p.fmt, p.vendor, status, have))
    order = {MISSING: 0, OTHER_FORMAT: 1, INSTALLED: 2}
    results.sort(key=lambda r: (order[r.status], r.name.lower()))
    return ProjectCheck(project, results)


def check_all(projects: Iterable[Project], target: Snapshot) -> list[ProjectCheck]:
    index = _index(target)
    checks = [check(p, target, index) for p in projects]
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
