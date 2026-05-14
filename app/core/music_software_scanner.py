"""
Music Software Scanner — discovers installed music applications on macOS.

Scans /Applications and ~/Applications for DAWs, DJ software, plugin managers,
license managers, sample managers, audio utilities, and hardware utilities.
No files are modified by this module.
"""

from __future__ import annotations

import datetime
import os
import plistlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# ── Category constants ────────────────────────────────────────────────────────

CATEGORY_DAW              = "DAW"
CATEGORY_DJ               = "DJ Software"
CATEGORY_PLUGIN_MANAGER   = "Plugin Manager"
CATEGORY_LICENSE_MANAGER  = "License Manager"
CATEGORY_SAMPLE_MANAGER   = "Sample Manager"
CATEGORY_AUDIO_UTILITY    = "Audio Utility"
CATEGORY_HARDWARE_UTILITY = "Hardware Utility"

ALL_CATEGORIES: list[str] = [
    CATEGORY_DAW,
    CATEGORY_DJ,
    CATEGORY_PLUGIN_MANAGER,
    CATEGORY_LICENSE_MANAGER,
    CATEGORY_SAMPLE_MANAGER,
    CATEGORY_AUDIO_UTILITY,
    CATEGORY_HARDWARE_UTILITY,
]

# ── Scan paths ────────────────────────────────────────────────────────────────

SCAN_PATHS: list[str] = [
    "/Applications",
    os.path.expanduser("~/Applications"),
]

# ── Known app registry ────────────────────────────────────────────────────────
# Each entry: (match_substring, category, fallback_developer)
# Matching is case-insensitive substring search against the .app filename stem.
# Entries are evaluated in order; first match wins — list specific before general.

KNOWN_APPS: list[tuple[str, str, str]] = [
    # ── DAWs ──────────────────────────────────────────────────────────────────
    ("Logic Pro",               CATEGORY_DAW,             "Apple"),
    ("Ableton Live",            CATEGORY_DAW,             "Ableton"),
    ("FL Studio",               CATEGORY_DAW,             "Image-Line"),
    ("Cubase",                  CATEGORY_DAW,             "Steinberg"),
    ("Studio One",              CATEGORY_DAW,             "PreSonus"),
    ("Pro Tools",               CATEGORY_DAW,             "Avid"),
    ("Bitwig Studio",           CATEGORY_DAW,             "Bitwig"),
    ("Reason",                  CATEGORY_DAW,             "Reason Studios"),
    ("Nuendo",                  CATEGORY_DAW,             "Steinberg"),
    ("Reaper",                  CATEGORY_DAW,             "Cockos"),
    ("GarageBand",              CATEGORY_DAW,             "Apple"),
    ("Digital Performer",       CATEGORY_DAW,             "MOTU"),
    ("Waveform",                CATEGORY_DAW,             "Tracktion"),
    ("Mixcraft",                CATEGORY_DAW,             "Acoustica"),
    ("Ardour",                  CATEGORY_DAW,             "Ardour"),
    ("Pyramix",                 CATEGORY_DAW,             "Merging Technologies"),

    # ── DJ Software ───────────────────────────────────────────────────────────
    ("rekordbox",               CATEGORY_DJ,              "Pioneer DJ"),
    ("Serato DJ",               CATEGORY_DJ,              "Serato"),
    ("Traktor",                 CATEGORY_DJ,              "Native Instruments"),
    ("VirtualDJ",               CATEGORY_DJ,              "Atomix"),
    ("djay",                    CATEGORY_DJ,              "algoriddim"),
    ("Mixxx",                   CATEGORY_DJ,              "Mixxx"),
    ("Denon DJ",                CATEGORY_DJ,              "Denon DJ"),

    # ── Plugin / Software Managers ────────────────────────────────────────────
    ("Native Access",           CATEGORY_PLUGIN_MANAGER,  "Native Instruments"),
    ("Waves Central",           CATEGORY_PLUGIN_MANAGER,  "Waves"),
    ("Arturia Software Center", CATEGORY_PLUGIN_MANAGER,  "Arturia"),
    ("Splice",                  CATEGORY_PLUGIN_MANAGER,  "Splice"),
    ("Plugin Alliance",         CATEGORY_PLUGIN_MANAGER,  "Plugin Alliance"),
    ("Softube Central",         CATEGORY_PLUGIN_MANAGER,  "Softube"),
    ("Output Hub",              CATEGORY_PLUGIN_MANAGER,  "Output"),
    ("Roland Cloud",            CATEGORY_PLUGIN_MANAGER,  "Roland"),
    ("KORG Software Pass",      CATEGORY_PLUGIN_MANAGER,  "KORG"),
    ("UA Connect",              CATEGORY_PLUGIN_MANAGER,  "Universal Audio"),
    ("Avid Link",               CATEGORY_PLUGIN_MANAGER,  "Avid"),
    ("iZotope Product Portal",  CATEGORY_PLUGIN_MANAGER,  "iZotope"),
    ("Izotope Product Portal",  CATEGORY_PLUGIN_MANAGER,  "iZotope"),
    ("Soundtoys",               CATEGORY_PLUGIN_MANAGER,  "Soundtoys"),
    ("Apogee Software",         CATEGORY_PLUGIN_MANAGER,  "Apogee Electronics"),
    ("Vienna Ensemble",         CATEGORY_PLUGIN_MANAGER,  "Vienna Symphonic Library"),
    ("East West",               CATEGORY_PLUGIN_MANAGER,  "EastWest"),
    ("Komplete Kontrol",        CATEGORY_PLUGIN_MANAGER,  "Native Instruments"),

    # ── License Managers ──────────────────────────────────────────────────────
    ("iLok License Manager",    CATEGORY_LICENSE_MANAGER, "PACE Anti-Piracy"),
    ("eLicenser Control Center",CATEGORY_LICENSE_MANAGER, "Steinberg"),
    ("eLicenser",               CATEGORY_LICENSE_MANAGER, "Steinberg"),
    ("CodeMeter",               CATEGORY_LICENSE_MANAGER, "WIBU-SYSTEMS"),

    # ── Sample Managers ───────────────────────────────────────────────────────
    ("Loopcloud",               CATEGORY_SAMPLE_MANAGER,  "Loopmasters"),
    ("Noiiz",                   CATEGORY_SAMPLE_MANAGER,  "Noiiz"),
    ("Samples from Mars",       CATEGORY_SAMPLE_MANAGER,  "Samples from Mars"),
    ("Sounds",                  CATEGORY_SAMPLE_MANAGER,  "Native Instruments"),

    # ── Audio Utilities ───────────────────────────────────────────────────────
    ("Loopback",                CATEGORY_AUDIO_UTILITY,   "Rogue Amoeba"),
    ("Audio Hijack",            CATEGORY_AUDIO_UTILITY,   "Rogue Amoeba"),
    ("SoundSource",             CATEGORY_AUDIO_UTILITY,   "Rogue Amoeba"),
    ("Fission",                 CATEGORY_AUDIO_UTILITY,   "Rogue Amoeba"),
    ("Piezo",                   CATEGORY_AUDIO_UTILITY,   "Rogue Amoeba"),
    ("Farrago",                 CATEGORY_AUDIO_UTILITY,   "Rogue Amoeba"),
    ("Sound Siphon",            CATEGORY_AUDIO_UTILITY,   "StateSide Software"),
    ("BlackHole",               CATEGORY_AUDIO_UTILITY,   "Existential Audio"),
    ("Boom 3",                  CATEGORY_AUDIO_UTILITY,   "Global Delight"),
    ("Permute",                 CATEGORY_AUDIO_UTILITY,   "Chaotic Box"),
    ("Compressor",              CATEGORY_AUDIO_UTILITY,   "Apple"),
    ("MIDI Monitor",            CATEGORY_AUDIO_UTILITY,   "Snoize"),

    # ── Hardware Utilities ────────────────────────────────────────────────────
    ("Focusrite Control",       CATEGORY_HARDWARE_UTILITY, "Focusrite"),
    ("Universal Audio Console", CATEGORY_HARDWARE_UTILITY, "Universal Audio"),
    ("UA Console",              CATEGORY_HARDWARE_UTILITY, "Universal Audio"),
    ("RME TotalMix",            CATEGORY_HARDWARE_UTILITY, "RME"),
    ("TotalMix",                CATEGORY_HARDWARE_UTILITY, "RME"),
    ("MOTU Audio Setup",        CATEGORY_HARDWARE_UTILITY, "MOTU"),
    ("Elektron Transfer",       CATEGORY_HARDWARE_UTILITY, "Elektron"),
    ("Overbridge",              CATEGORY_HARDWARE_UTILITY, "Elektron"),
    ("Novation Components",     CATEGORY_HARDWARE_UTILITY, "Novation"),
    ("PreSonus Universal Control", CATEGORY_HARDWARE_UTILITY, "PreSonus"),
    ("Universal Control",       CATEGORY_HARDWARE_UTILITY, "PreSonus"),
    ("SSL 360",                 CATEGORY_HARDWARE_UTILITY, "Solid State Logic"),
    ("Apogee Control",          CATEGORY_HARDWARE_UTILITY, "Apogee Electronics"),
    ("Ableton Push",            CATEGORY_HARDWARE_UTILITY, "Ableton"),
    ("iConnectivity",           CATEGORY_HARDWARE_UTILITY, "iConnectivity"),
    ("Scarlett",                CATEGORY_HARDWARE_UTILITY, "Focusrite"),
    ("Clarett",                 CATEGORY_HARDWARE_UTILITY, "Focusrite"),
    ("Audient EVO",             CATEGORY_HARDWARE_UTILITY, "Audient"),
    ("RME",                     CATEGORY_HARDWARE_UTILITY, "RME"),
]


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MusicApp:
    name: str
    category: str
    developer: str
    version: str
    path: str
    modified: str

    @property
    def row(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.name,
            self.category,
            self.developer,
            self.version,
            self.path,
            self.modified,
        )


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_music_apps(
    paths: list[str] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> list[MusicApp]:
    """
    Walk *paths* (defaults to SCAN_PATHS) up to three directory levels deep,
    find .app bundles matching the known-app registry, and return a sorted list
    of :class:`MusicApp` instances (by category then name).
    """
    targets = paths if paths is not None else SCAN_PATHS
    results: list[MusicApp] = []
    seen: set[str] = set()

    for base in targets:
        base_path = Path(base)
        if progress_cb:
            progress_cb(f"Scanning {base_path}…")
        if not base_path.exists():
            continue
        try:
            _walk(base_path, depth=0, max_depth=3, results=results, seen=seen)
        except PermissionError:
            pass

    if progress_cb:
        progress_cb(f"Done — {len(results)} music app(s) found.")

    return sorted(results, key=lambda a: (a.category, a.name.lower()))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _walk(
    path: Path,
    depth: int,
    max_depth: int,
    results: list[MusicApp],
    seen: set[str],
) -> None:
    if depth > max_depth:
        return
    try:
        for item in path.iterdir():
            if item.suffix.lower() == ".app":
                resolved = str(item.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    app = _classify(item)
                    if app is not None:
                        results.append(app)
            elif item.is_dir():
                _walk(item, depth + 1, max_depth, results, seen)
    except PermissionError:
        pass


def _classify(app_path: Path) -> MusicApp | None:
    """
    Return a :class:`MusicApp` if *app_path* matches any entry in
    :data:`KNOWN_APPS`, else return ``None``.
    """
    stem_lower = app_path.stem.lower()
    for match_str, category, known_developer in KNOWN_APPS:
        if match_str.lower() in stem_lower:
            meta = _app_metadata(app_path)
            developer = meta["developer"] or known_developer
            return MusicApp(
                name=app_path.stem,
                category=category,
                developer=developer,
                version=meta["version"],
                path=str(app_path),
                modified=meta["modified"],
            )
    return None


def _app_metadata(app_path: Path) -> dict:
    """Read version, developer, and last-modified date from a .app bundle."""
    meta: dict = {"version": "", "developer": "", "modified": ""}

    try:
        stat = app_path.stat()
        meta["modified"] = datetime.datetime.fromtimestamp(
            stat.st_mtime
        ).strftime("%Y-%m-%d")
    except OSError:
        pass

    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        return meta

    try:
        with plist_path.open("rb") as fh:
            plist: dict = plistlib.load(fh)
    except Exception:
        return meta

    meta["version"] = (
        plist.get("CFBundleShortVersionString")
        or plist.get("CFBundleVersion")
        or ""
    ).strip()

    developer = ""

    copyright_str: str = plist.get("NSHumanReadableCopyright", "")
    if copyright_str:
        match = re.search(
            r"©\s*\d{0,4}\s*([\w\s&]+?)(?:,|\.|Inc|LLC|Ltd|GmbH|$)",
            copyright_str,
        )
        if match:
            developer = match.group(1).strip()

    if not developer:
        info_str: str = plist.get("CFBundleGetInfoString", "")
        if "©" in info_str:
            parts = info_str.split("©")
            candidate = parts[-1].strip().split(" ")[0]
            if len(candidate) > 2:
                developer = candidate

    if not developer:
        bundle_id: str = plist.get("CFBundleIdentifier", "")
        parts = bundle_id.split(".")
        if len(parts) >= 2 and parts[0] in ("com", "org", "net", "io", "audio"):
            developer = parts[1].replace("-", " ").replace("_", " ").title()

    meta["developer"] = developer
    return meta
