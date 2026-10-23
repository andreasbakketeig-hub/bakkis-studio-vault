"""
Handoff checks: will this Live Set open complete on the receiver's Mac?

Traffic light:
    red     something will certainly be missing for the receiver
    yellow  worth a look before sending (packs, formats, versions, …)
    green   ready to send
Packing is allowed on green and yellow.

The checks only read. When files live outside the project folder the advice is
to run File > Collect All and Save in Live; the app never moves files itself.

Self-contained: standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from studio_vault.handoff.als import (KIND_M4L, LOC_EXTERNAL, LOC_PACK, LOC_USER_LIBRARY,
                                      LiveSet, PluginUse, other_sets, version_tuple)
from studio_vault.handoff.pluginlist import PluginList

GREEN = "green"
YELLOW = "yellow"
RED = "red"
_RANK = {GREEN: 0, YELLOW: 1, RED: 2}

COLLECT_ALL = ("In Live, choose File > Collect All and Save (set Samples from other Projects, the User Library "
               "and Packs to Yes), then check again.")


@dataclass
class Finding:
    key: str
    level: str                      # green | yellow | red
    title: str
    detail: str = ""
    items: list[str] = field(default_factory=list)


@dataclass
class Report:
    set_name: str
    set_path: str
    live_version: str
    tempo: float | None
    receiver: str = ""              # receiver's machine name, "" when no list is loaded
    findings: list[Finding] = field(default_factory=list)
    plugins: list[dict] = field(default_factory=list)       # per plug-in: name, fmt, vendor, status, tracks
    frozen_tracks: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        return max((f.level for f in self.findings), key=_RANK.get, default=GREEN)

    @property
    def can_pack(self) -> bool:
        return self.level != RED


# ── matching plug-ins against the receiver's list ─────────────────────────────

_BITNESS = re.compile(r"[\s_\-]*(x64|x86_64|64[\s_\-]?bit)$", re.IGNORECASE)
_FORMAT_WORD = re.compile(r"[\s_\-]*(vst3?|au|aax|clap)$", re.IGNORECASE)

INSTALLED = "installed"
OTHER_FORMAT = "other_format"
MISSING = "missing"
UNKNOWN = "unknown"


def _key(name: str) -> str:
    name = _FORMAT_WORD.sub("", _BITNESS.sub("", (name or "").strip()))
    return re.sub(r"[^a-z0-9]+", "", name.lower())


class _Receiver:
    def __init__(self, plugin_list: PluginList) -> None:
        self.by_fmt: dict[str, dict[str, set[str]]] = {}   # fmt -> key -> vendor keys
        self.any_fmt: dict[str, set[str]] = {}               # key -> formats
        for e in plugin_list.plugins:
            k = _key(e.name)
            self.by_fmt.setdefault(e.fmt, {}).setdefault(k, set()).add(_key(e.vendor))
            self.any_fmt.setdefault(k, set()).add(e.fmt)

    def status(self, p: PluginUse) -> tuple[str, list[str]]:
        k = _key(p.name)
        same = self.by_fmt.get(p.fmt, {})
        if k in same:
            vendors = same[k]
            if p.fmt != "AU" or not p.vendor or _key(p.vendor) in vendors or "" in vendors:
                return INSTALLED, [p.fmt]
        others = sorted(self.any_fmt.get(k, set()) - {p.fmt})
        if others:
            return OTHER_FORMAT, others
        return MISSING, []


# ── the checks ────────────────────────────────────────────────────────────────

def _names(files) -> list[str]:
    """File names with the folder they are in, without long ../../ chains."""
    out = set()
    for f in files:
        parent = (f.relative_path or f.absolute_path).replace("\\", "/").rstrip("/").rsplit("/", 2)
        folder = parent[-2] if len(parent) >= 2 and parent[-2] not in ("", "..", ".") else ""
        out.add(f"{f.name} ({folder})" if folder else f.name)
    return sorted(out, key=str.lower)


def check(live_set: LiveSet, receiver: PluginList | None = None) -> Report:
    report = Report(live_set.name, live_set.path, live_set.live_version, live_set.tempo,
                    receiver.machine_name if receiver else "")
    add = report.findings.append
    files = live_set.files

    # Files that live outside the project folder, or are gone.
    outside = [f for f in files if f.location in (LOC_EXTERNAL, LOC_USER_LIBRARY)]
    missing_here = [f for f in files if f.exists is False]
    if missing_here:
        add(Finding("missing_files", RED, f"{len(missing_here)} file(s) are missing on this Mac",
                    "Live will not find them here either. Relink them in Live (File > Manage Files), "
                    "or remove them from the set.", _names(missing_here)))
    outside_ok = [f for f in outside if f.exists is not False]
    if outside_ok:
        add(Finding("outside_files", RED, f"{len(outside_ok)} file(s) are outside the project folder",
                    "They will not be in the package. " + COLLECT_ALL, _names(outside_ok)))
    if not missing_here and not outside_ok:
        add(Finding("files", GREEN, "All samples are in the project folder"))

    # Packs and Core Library.
    packs = sorted({f.pack for f in files if f.location == LOC_PACK and f.pack and f.pack != "Core Library"})
    if packs:
        add(Finding("packs", YELLOW, f"Uses content from {len(packs)} Live Pack(s)",
                    "The receiver needs these Packs installed, or collect them into the project with "
                    "Collect All and Save (Packs set to Yes).", packs))
    if any(f.pack == "Core Library" for f in files):
        add(Finding("core_library", GREEN, "Uses Core Library content",
                    "Comes with Live. Smaller editions (Intro, Lite) have less of it."))

    # Live version.
    set_v = version_tuple(live_set.live_version)
    newest = receiver.newest_live() if receiver else None
    if newest is None:
        add(Finding("live_version", YELLOW if receiver else GREEN, f"Saved with Live {live_set.live_version or '?'}",
                    "The receiver's list shows no Live installed." if receiver else
                    "Load the receiver's plug-in list to compare Live versions."))
    else:
        rec_v = version_tuple(newest.version)
        if set_v and rec_v and rec_v[:1] < set_v[:1]:
            add(Finding("live_version", RED, f"The receiver has Live {newest.version.split(' ')[0]}; the set is from "
                        f"Live {live_set.live_version}", "Older major versions of Live cannot open it. "
                        "The receiver needs to update Live."))
        elif set_v and rec_v and rec_v[:2] < set_v[:2]:
            add(Finding("live_version", YELLOW, f"The receiver has Live {newest.version.split(' ')[0]}; the set is from "
                        f"Live {live_set.live_version}", "Usually opens, but devices added in the newer version "
                        "may be missing. Ask the receiver to update."))
        else:
            add(Finding("live_version", GREEN, f"Live {live_set.live_version}: the receiver has {newest.version.split(' ')[0]}"))

    # Max for Live.
    m4l_tracks = [t.name for t in live_set.tracks if t.max_devices]
    if m4l_tracks:
        devices = sorted({d for t in live_set.tracks for d in t.max_devices}, key=str.lower)
        outside_m4l = [f for f in files if f.kind == KIND_M4L and f.location in (LOC_EXTERNAL, LOC_USER_LIBRARY)]
        if receiver and receiver.live and not receiver.has_max_for_live:
            add(Finding("max_for_live", RED, f"{len(devices)} Max for Live device(s); the receiver has no Live Suite",
                        "Max for Live needs Live Suite (or a Max for Live license). Freeze or resample those tracks.",
                        devices))
        else:
            add(Finding("max_for_live", YELLOW, f"{len(devices)} Max for Live device(s)",
                        "The receiver needs Live Suite or Max for Live."
                        + (" Some devices are outside the project folder: " + COLLECT_ALL if outside_m4l else ""),
                        devices))

    # Third-party plug-ins.
    plugins = live_set.plugins
    rec = _Receiver(receiver) if receiver else None
    frozen_ok = {t.name for t in live_set.tracks if t.frozen and t.freeze_files and all(f.exists for f in t.freeze_files)}
    problem_tracks: dict[str, list[str]] = {}
    missing_rows, other_rows = [], []
    for p in plugins:
        status, have = rec.status(p) if rec else (UNKNOWN, [])
        tracks = live_set.tracks_using(p)
        report.plugins.append({"name": p.name, "fmt": p.fmt, "vendor": p.vendor, "status": status,
                               "have_formats": have, "tracks": tracks})
        label = f"{p.name} ({p.fmt})" + (f" on {', '.join(tracks)}" if tracks else "")
        if status == MISSING:
            missing_rows.append(label)
        elif status == OTHER_FORMAT:
            other_rows.append(f"{label}: they have {', '.join(have)}")
        if status in (MISSING, OTHER_FORMAT):
            for t in tracks:
                if t not in frozen_ok:
                    problem_tracks.setdefault(t, []).append(p.name)
    if not plugins:
        add(Finding("plugins", GREEN, "No third-party plug-ins"))
    elif not rec:
        add(Finding("plugins", YELLOW, f"{len(plugins)} third-party plug-in(s)",
                    "Load the receiver's plug-in list to check them. They export it in one click: "
                    "Handoff > Receive > Export my plug-in list.", [f"{p.name} ({p.fmt})" for p in plugins]))
    else:
        if missing_rows:
            add(Finding("plugins_missing", RED, f"{len(missing_rows)} plug-in(s) the receiver does not have",
                        "Freeze (or resample) the tracks that use them, so the receiver hears them.", missing_rows))
        if other_rows:
            add(Finding("plugins_format", YELLOW, f"{len(other_rows)} plug-in(s) in another format on their side",
                        "Live may not swap AU, VST and VST3 by itself. Freeze those tracks to be safe.", other_rows))
        if not missing_rows and not other_rows:
            add(Finding("plugins", GREEN, f"The receiver has all {len(plugins)} plug-in(s)"))
        if problem_tracks:
            add(Finding("freeze_suggestion", YELLOW, f"Suggest freezing {len(problem_tracks)} track(s)",
                        "Frozen tracks play back without the plug-in.",
                        [f"{t}: {', '.join(sorted(set(ps)))}" for t, ps in sorted(problem_tracks.items())]))

    # Frozen tracks and their freeze files.
    frozen = [t for t in live_set.tracks if t.frozen]
    report.frozen_tracks = [t.name for t in frozen]
    broken = [t.name for t in frozen if not t.freeze_files or any(f.exists is False for f in t.freeze_files)]
    if broken:
        add(Finding("freeze_files", RED, f"{len(broken)} frozen track(s) without their freeze files",
                    "Unfreeze and freeze them again in Live, then save, so the freeze files are in the project.",
                    broken))
    elif frozen:
        add(Finding("frozen", GREEN, f"{len(frozen)} frozen track(s) with freeze files",
                    items=[t.name for t in frozen]))

    # Other versions of the set in the same folder.
    others = other_sets(live_set)
    if others:
        add(Finding("other_sets", YELLOW, f"{len(others)} other Live Set(s) in the project folder",
                    "Only the set you picked goes in the package as the main version.", others))

    report.findings.sort(key=lambda f: -_RANK[f.level])
    return report
