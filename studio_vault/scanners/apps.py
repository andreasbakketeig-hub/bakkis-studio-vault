"""
Music Software Scanner — discovers installed music applications on macOS.

Scans /Applications and ~/Applications for DAWs, DJ software, plugin managers,
license managers, sample managers, audio utilities, hardware utilities, and
cloud sync/music tools. No files are modified by this module.
"""

from __future__ import annotations

import datetime
import os
import plistlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from studio_vault.scanners.plugins import _developer_from_plist

# ── Category constants ────────────────────────────────────────────────────────

CATEGORY_DAW              = "DAW"
CATEGORY_DJ               = "DJ Software"
CATEGORY_PLUGIN_MANAGER   = "Plugin Manager"
CATEGORY_LICENSE_MANAGER  = "License Manager"
CATEGORY_SAMPLE_MANAGER   = "Sample Manager"
CATEGORY_AUDIO_UTILITY    = "Audio Utility"
CATEGORY_HARDWARE_UTILITY = "Hardware Utility"
CATEGORY_CLOUD_SYNC       = "Cloud & Sync"

ALL_CATEGORIES: list[str] = [
    CATEGORY_DAW,
    CATEGORY_DJ,
    CATEGORY_PLUGIN_MANAGER,
    CATEGORY_LICENSE_MANAGER,
    CATEGORY_SAMPLE_MANAGER,
    CATEGORY_AUDIO_UTILITY,
    CATEGORY_HARDWARE_UTILITY,
    CATEGORY_CLOUD_SYNC,
]

# ── Scan paths ────────────────────────────────────────────────────────────────

SCAN_PATHS: list[str] = [
    "/Applications",
    os.path.expanduser("~/Applications"),
]

# ── Primary DAW detection hints ───────────────────────────────────────────────
# Lower index = higher priority when modification dates are equal.
# Logic Pro leads since it ships with macOS and is the most common Mac DAW.

PRIMARY_DAW_HINTS: list[str] = [
    "Logic Pro",
    "Ableton Live",
    "Pro Tools",
    "Cubase",
    "FL Studio",
    "Bitwig Studio",
    "Studio One",
    "Reason",
    "Nuendo",
    "Reaper",
    "GarageBand",
    "Digital Performer",
    "Waveform",
    "Mixcraft",
    "Ardour",
    "Pyramix",
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
    ("Bitwig",                  CATEGORY_DAW,             "Bitwig"),
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
    ("Serato",                  CATEGORY_DJ,              "Serato"),
    ("Traktor",                 CATEGORY_DJ,              "Native Instruments"),
    ("VirtualDJ",               CATEGORY_DJ,              "Atomix"),
    ("djay",                    CATEGORY_DJ,              "algoriddim"),
    ("Mixxx",                   CATEGORY_DJ,              "Mixxx"),
    ("Denon DJ",                CATEGORY_DJ,              "Denon DJ"),
    ("Engine DJ",               CATEGORY_DJ,              "Denon DJ"),

    # ── Plugin / Software Managers ────────────────────────────────────────────
    ("Native Access",           CATEGORY_PLUGIN_MANAGER,  "Native Instruments"),
    ("Waves Central",           CATEGORY_PLUGIN_MANAGER,  "Waves"),
    ("Arturia Software Center", CATEGORY_PLUGIN_MANAGER,  "Arturia"),
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
    ("Komplete",                CATEGORY_PLUGIN_MANAGER,  "Native Instruments"),
    ("Maschine",                CATEGORY_PLUGIN_MANAGER,  "Native Instruments"),

    # ── License Managers ──────────────────────────────────────────────────────
    ("iLok License Manager",    CATEGORY_LICENSE_MANAGER, "PACE Anti-Piracy"),
    ("iLok",                    CATEGORY_LICENSE_MANAGER, "PACE Anti-Piracy"),
    ("eLicenser Control Center",CATEGORY_LICENSE_MANAGER, "Steinberg"),
    ("eLicenser",               CATEGORY_LICENSE_MANAGER, "Steinberg"),
    ("CodeMeter",               CATEGORY_LICENSE_MANAGER, "WIBU-SYSTEMS"),

    # ── Sample Managers ───────────────────────────────────────────────────────
    ("Loopcloud",               CATEGORY_SAMPLE_MANAGER,  "Loopmasters"),
    ("Noiiz",                   CATEGORY_SAMPLE_MANAGER,  "Noiiz"),
    ("Samples from Mars",       CATEGORY_SAMPLE_MANAGER,  "Samples from Mars"),
    ("Sounds",                  CATEGORY_SAMPLE_MANAGER,  "Native Instruments"),
    ("LANDR",                   CATEGORY_SAMPLE_MANAGER,  "LANDR"),

    # ── Cloud & Sync ──────────────────────────────────────────────────────────
    ("Splice",                  CATEGORY_CLOUD_SYNC,      "Splice"),

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
    ("Boom",                    CATEGORY_AUDIO_UTILITY,   "Global Delight"),
    ("Permute",                 CATEGORY_AUDIO_UTILITY,   "Chaotic Box"),
    ("Compressor",              CATEGORY_AUDIO_UTILITY,   "Apple"),
    ("MIDI Monitor",            CATEGORY_AUDIO_UTILITY,   "Snoize"),
    ("MidiKeys",                CATEGORY_AUDIO_UTILITY,   "Chord Software"),
    ("AudioSwitcher",           CATEGORY_AUDIO_UTILITY,   "Ahmad Azizi"),
    ("Rogue Amoeba",            CATEGORY_AUDIO_UTILITY,   "Rogue Amoeba"),

    # ── Hardware Utilities ────────────────────────────────────────────────────
    ("Focusrite Control",       CATEGORY_HARDWARE_UTILITY, "Focusrite"),
    ("Universal Audio Console", CATEGORY_HARDWARE_UTILITY, "Universal Audio"),
    ("UA Console",              CATEGORY_HARDWARE_UTILITY, "Universal Audio"),
    ("RME TotalMix",            CATEGORY_HARDWARE_UTILITY, "RME"),
    ("TotalMix",                CATEGORY_HARDWARE_UTILITY, "RME"),
    ("MOTU Audio Setup",        CATEGORY_HARDWARE_UTILITY, "MOTU"),
    ("MOTU CueMix",             CATEGORY_HARDWARE_UTILITY, "MOTU"),
    ("Elektron Transfer",       CATEGORY_HARDWARE_UTILITY, "Elektron"),
    ("Overbridge",              CATEGORY_HARDWARE_UTILITY, "Elektron"),
    ("Novation Components",     CATEGORY_HARDWARE_UTILITY, "Novation"),
    ("PreSonus Universal Control", CATEGORY_HARDWARE_UTILITY, "PreSonus"),
    ("Universal Control",       CATEGORY_HARDWARE_UTILITY, "PreSonus"),
    ("SSL 360",                 CATEGORY_HARDWARE_UTILITY, "Solid State Logic"),
    ("MOTIV",                   CATEGORY_HARDWARE_UTILITY, "Shure"),
    ("Apogee Control",          CATEGORY_HARDWARE_UTILITY, "Apogee Electronics"),
    ("Ableton Push",            CATEGORY_HARDWARE_UTILITY, "Ableton"),
    ("iConnectivity",           CATEGORY_HARDWARE_UTILITY, "iConnectivity"),
    ("Scarlett",                CATEGORY_HARDWARE_UTILITY, "Focusrite"),
    ("Clarett",                 CATEGORY_HARDWARE_UTILITY, "Focusrite"),
    ("Audient EVO",             CATEGORY_HARDWARE_UTILITY, "Audient"),
    ("RME",                     CATEGORY_HARDWARE_UTILITY, "RME"),
    ("Digicheck",               CATEGORY_HARDWARE_UTILITY, "RME"),
    ("SSL Native",              CATEGORY_HARDWARE_UTILITY, "Solid State Logic"),
    ("Apollo",                  CATEGORY_HARDWARE_UTILITY, "Universal Audio"),
    ("Volt Control",            CATEGORY_HARDWARE_UTILITY, "Universal Audio"),
    ("BOSS Tone Studio",        CATEGORY_HARDWARE_UTILITY, "Roland"),
    ("Line 6",                  CATEGORY_HARDWARE_UTILITY, "Line 6"),
    ("Helix Native",            CATEGORY_HARDWARE_UTILITY, "Line 6"),
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


# ── Primary DAW detection ─────────────────────────────────────────────────────

def _daw_hint_priority(app: MusicApp) -> int:
    """Return hint-list index for *app* (lower = higher priority)."""
    name_lower = app.name.lower()
    for i, hint in enumerate(PRIMARY_DAW_HINTS):
        if hint.lower() in name_lower:
            return i
    return len(PRIMARY_DAW_HINTS)


def detect_primary_daw(apps: list[MusicApp]) -> MusicApp | None:
    """
    Return the most likely primary DAW from *apps*.

    Prefers the DAW with the most recent modification date.
    Ties are broken by :data:`PRIMARY_DAW_HINTS` order (lower index wins).
    Returns ``None`` if no DAWs are present in *apps*.
    """
    daws = [a for a in apps if a.category == CATEGORY_DAW]
    if not daws:
        return None
    # (modified_date, -priority) — max picks most-recent date,
    # then highest-priority hint (smallest index → largest negative).
    return max(daws, key=lambda a: (a.modified, -_daw_hint_priority(a)))


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_music_apps(
    paths: list[str] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> list[MusicApp]:
    """
    Walk *paths* (defaults to SCAN_PATHS) up to three directory levels deep,
    find .app bundles matching the known-app registry, and return a sorted list
    of :class:`MusicApp` instances (by category then name).

    Each base path is scanned concurrently via :class:`ThreadPoolExecutor`
    for faster wall-clock performance on machines with many sub-directories.
    """
    targets = [Path(p) for p in (paths if paths is not None else SCAN_PATHS)]

    def _scan_base(base: Path) -> list[MusicApp]:
        if not base.exists():
            return []
        local: list[MusicApp] = []
        seen: set[str] = set()
        try:
            _walk(base, depth=0, max_depth=3, results=local, seen=seen)
        except PermissionError:
            pass
        if progress_cb:
            progress_cb(f"Scanned {base}…")
        return local

    all_apps: list[MusicApp] = []
    global_seen: set[str] = set()

    with ThreadPoolExecutor(max_workers=min(len(targets), 4)) as pool:
        futures = {pool.submit(_scan_base, t): t for t in targets}
        for future in as_completed(futures):
            try:
                for app in future.result():
                    key = str(Path(app.path).resolve())
                    if key not in global_seen:
                        global_seen.add(key)
                        all_apps.append(app)
            except Exception:
                pass

    if progress_cb:
        progress_cb(f"Done — {len(all_apps)} music app(s) found.")

    return sorted(all_apps, key=lambda a: (a.category, a.name.lower()))


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
            # The registry name is curated; Info.plist strings are often just "© 2024".
            developer = known_developer or meta["developer"]
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

    developer = _developer_from_plist(plist)

    meta["developer"] = developer
    return meta
