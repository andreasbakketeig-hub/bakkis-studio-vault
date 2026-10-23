"""
Plug-in list: the receiver exports what they have installed, in one click, to a
small file the sender loads to check a project before sending it.

The list holds the names Live itself stores in a Live Set, so a check is exact:
    AU    vendor + name from the component ("FabFilter", "Pro-C 2")
    VST3  the class names in moduleinfo.json, else the bundle name
    VST   the bundle name
plus the Live versions and editions installed (Suite includes Max for Live).

No file paths, serials or machine ids are written. Self-contained: standard
library only.

File: <name>.handoffplugins (JSON)
    {"format": "handoff-plugin-list", "version": 1, "created_at": "…",
     "machine_name": "Studio Mac",
     "live": [{"name": "Ableton Live 12 Suite", "version": "12.1.10", "edition": "Suite"}],
     "plugins": [{"name": "Pro-C 2", "fmt": "AU", "vendor": "FabFilter", "version": "2.30"}, …]}
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import plistlib
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

FORMAT_ID = "handoff-plugin-list"
FORMAT_VERSION = 1
FILE_SUFFIX = ".handoffplugins"
MAX_FILE_BYTES = 20 * 1024 * 1024

# Formats Ableton Live loads (it does not use AAX).
_SUFFIX_FMT = {".vst": "VST", ".vst3": "VST3", ".component": "AU"}
PLUGIN_DIRS = (
    "/Library/Audio/Plug-Ins/VST", "/Library/Audio/Plug-Ins/VST3", "/Library/Audio/Plug-Ins/Components",
    "~/Library/Audio/Plug-Ins/VST", "~/Library/Audio/Plug-Ins/VST3", "~/Library/Audio/Plug-Ins/Components",
)
APP_DIRS = ("/Applications", "~/Applications")
EDITIONS = ("Suite", "Standard", "Intro", "Lite", "Trial")


class PluginListError(Exception):
    """Not a plug-in list this version understands."""


@dataclass(frozen=True)
class Entry:
    name: str        # the name Live stores for this format
    fmt: str         # VST | VST3 | AU
    vendor: str = ""
    version: str = ""


@dataclass(frozen=True)
class LiveInstall:
    name: str        # "Ableton Live 12 Suite"
    version: str     # "12.1.10"
    edition: str = ""


@dataclass
class PluginList:
    machine_name: str
    created_at: str
    live: list[LiveInstall] = field(default_factory=list)
    plugins: list[Entry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"format": FORMAT_ID, "version": FORMAT_VERSION, **asdict(self)}

    @property
    def has_max_for_live(self) -> bool:
        # The Live trial is a full Suite. Standard needs a separate Max for Live license (not visible here).
        return any(i.edition in ("Suite", "Trial") for i in self.live)

    def newest_live(self) -> LiveInstall | None:
        def key(i: LiveInstall) -> tuple[int, ...]:
            m = re.match(r"(\d+(?:\.\d+)*)", i.version)
            return tuple(int(x) for x in m.group(1).split(".")) if m else ()
        return max(self.live, key=key, default=None)


# ── scanning (the receiver's Mac) ─────────────────────────────────────────────

def _plist(bundle: Path) -> dict:
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as fh:
            data = plistlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _version(plist: dict) -> str:
    return str(plist.get("CFBundleShortVersionString") or plist.get("CFBundleVersion") or "").strip()


def vst3_class_names(bundle: Path) -> list[str]:
    """Audio Module Class names from a VST3 bundle's moduleinfo.json (what Live stores)."""
    try:
        text = (bundle / "Contents" / "Resources" / "moduleinfo.json").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # JSON5-ish (trailing commas): read class blocks with a regex instead of json.loads.
    names: list[str] = []
    for block in re.findall(r"\{[^{}]*\"Category\"\s*:\s*\"Audio Module Class\"[^{}]*\}", text, re.S):
        m = re.search(r"\"Name\"\s*:\s*\"([^\"]+)\"", block)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def _entries_for(bundle: Path) -> list[Entry]:
    fmt = _SUFFIX_FMT[bundle.suffix.lower()]
    plist = _plist(bundle)
    version = _version(plist)
    if fmt == "AU":
        out = [Entry(name, fmt, vendor, version) for vendor, name in au_component_names(plist)]
        return out or [Entry(bundle.stem, fmt, "", version)]
    if fmt == "VST3":
        names = vst3_class_names(bundle) or [bundle.stem]
        return [Entry(n, fmt, "", version) for n in names]
    return [Entry(bundle.stem, fmt, "", version)]


def au_component_names(plist: dict) -> list[tuple[str, str]]:
    """(vendor, name) per Audio Unit component ("FabFilter: Pro-C 2"), as Live stores them."""
    out: list[tuple[str, str]] = []
    for comp in plist.get("AudioComponents") or []:
        if not isinstance(comp, dict):
            continue
        full = str(comp.get("name") or "")
        vendor, _, name = full.partition(":")
        if not name:
            vendor, name = "", full
        if name.strip() and (vendor.strip(), name.strip()) not in out:
            out.append((vendor.strip(), name.strip()))
    return out


def _find_bundles(root: Path) -> list[Path]:
    """Plug-in bundles under *root*; folder symlinks are followed, each real folder once."""
    found: list[Path] = []
    visited: set[str] = set()
    for dirpath, dirnames, _files in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in visited:
            dirnames[:] = []
            continue
        visited.add(real)
        keep = []
        for d in dirnames:
            if Path(d).suffix.lower() in _SUFFIX_FMT:
                found.append(Path(dirpath) / d)
            elif not d.startswith("."):
                keep.append(d)
        dirnames[:] = keep
    for f in root.iterdir() if root.is_dir() else []:
        if f.is_file() and f.suffix.lower() == ".vst3":     # single-file VST3 (rare)
            found.append(f)
    return found


def _live_installs(app_dirs: tuple[str, ...]) -> list[LiveInstall]:
    out = []
    for base in app_dirs:
        root = Path(os.path.expanduser(base))
        try:
            apps = sorted(root.glob("Ableton Live*.app"))
        except OSError:
            continue
        for app in apps:
            edition = next((e for e in EDITIONS if e.lower() in app.stem.lower()), "")
            out.append(LiveInstall(app.stem, _version(_plist(app)), edition))
    return out


def machine_name() -> str:
    try:
        name = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True,
                              timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        name = ""
    return name or platform.node().removesuffix(".local") or "Mac"


def scan(plugin_dirs: tuple[str, ...] = PLUGIN_DIRS, app_dirs: tuple[str, ...] = APP_DIRS,
         name: str | None = None) -> PluginList:
    """What this Mac has: plug-ins Live can load, and Live itself."""
    entries: dict[tuple[str, str, str], Entry] = {}
    for base in plugin_dirs:
        root = Path(os.path.expanduser(base))
        if not root.is_dir():
            continue
        for bundle in _find_bundles(root):
            for e in _entries_for(bundle):
                entries.setdefault((e.name.lower(), e.fmt, e.vendor.lower()), e)
    return PluginList(
        machine_name=name if name is not None else machine_name(),
        created_at=datetime.datetime.now().isoformat(timespec="seconds"),
        live=_live_installs(app_dirs),
        plugins=sorted(entries.values(), key=lambda e: (e.name.lower(), e.fmt)),
    )


# ── file ──────────────────────────────────────────────────────────────────────

def save(plugin_list: PluginList, dest: Path | str) -> Path:
    dest = Path(dest)
    if not dest.name.endswith(FILE_SUFFIX):
        dest = dest.with_name(dest.name + FILE_SUFFIX)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(plugin_list.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return dest


def _str(d: dict, key: str) -> str:
    v = d.get(key, "")
    return v.strip() if isinstance(v, str) else ""


def load(path: Path | str) -> PluginList:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise PluginListError("The file is too large to be a plug-in list.")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise PluginListError("Could not read the plug-in list.") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT_ID:
        raise PluginListError("Not a plug-in list.")
    version = data.get("version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise PluginListError("This plug-in list was made by a newer version of the app.")
    plugins = [Entry(_str(p, "name"), _str(p, "fmt"), _str(p, "vendor"), _str(p, "version"))
               for p in data.get("plugins") or [] if isinstance(p, dict) and _str(p, "name")]
    live = [LiveInstall(_str(i, "name"), _str(i, "version"), _str(i, "edition"))
            for i in data.get("live") or [] if isinstance(i, dict)]
    return PluginList(_str(data, "machine_name") or "Mac", _str(data, "created_at"), live, plugins)
