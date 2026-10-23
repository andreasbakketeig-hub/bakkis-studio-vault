"""
Static vendor registry — maps plugin developers to update managers and websites.

Read-only reference data; does not fetch versions or open network connections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VendorRegistryEntry:
    """How to guide a user toward updates for plugins from one vendor."""

    vendor_key: str
    display_name: str
    developer_patterns: tuple[str, ...]
    manager_app_names: tuple[str, ...]
    manager_display: str
    website_url: str
    website_only: bool = False


@dataclass(frozen=True)
class ResolvedManager:
    """Installed update-manager app resolved from a music-app scan."""

    app_name: str
    app_path: str


# Substrings / phrases matched against Plugin.developer (see match_vendor).
VENDOR_REGISTRY: tuple[VendorRegistryEntry, ...] = (
    VendorRegistryEntry(
        "native_instruments",
        "Native Instruments",
        ("native instruments",),
        ("Native Access",),
        "Native Access",
        "https://www.native-instruments.com/",
    ),
    VendorRegistryEntry(
        "izotope",
        "iZotope",
        ("izotope",),
        ("iZotope Product Portal", "Izotope Product Portal"),
        "iZotope Product Portal",
        "https://www.izotope.com/",
    ),
    VendorRegistryEntry(
        "waves",
        "Waves",
        ("waves audio", "waves"),
        ("Waves Central",),
        "Waves Central",
        "https://www.waves.com/",
    ),
    VendorRegistryEntry(
        "arturia",
        "Arturia",
        ("arturia",),
        ("Arturia Software Center",),
        "Arturia Software Center",
        "https://www.arturia.com/",
    ),
    VendorRegistryEntry(
        "plugin_alliance",
        "Plugin Alliance",
        ("plugin alliance",),
        (
            "Plugin Alliance Installation Manager",
            "Plugin Alliance",
        ),
        "Plugin Alliance Installation Manager",
        "https://www.plugin-alliance.com/",
    ),
    VendorRegistryEntry(
        "universal_audio",
        "Universal Audio",
        ("universal audio", "uaudio"),
        ("UA Connect",),
        "UA Connect",
        "https://www.uaudio.com/",
    ),
    VendorRegistryEntry(
        "ssl",
        "Solid State Logic",
        ("solid state logic",),
        (),
        "SSL website",
        "https://www.solidstatelogic.com/",
        website_only=True,
    ),
    VendorRegistryEntry(
        "soundtoys",
        "Soundtoys",
        ("soundtoys",),
        ("Soundtoys",),
        "Soundtoys",
        "https://www.soundtoys.com/",
    ),
    VendorRegistryEntry(
        "softube",
        "Softube",
        ("softube",),
        ("Softube Central",),
        "Softube Central",
        "https://www.softube.com/",
    ),
    VendorRegistryEntry(
        "output",
        "Output",
        ("^output$", "output inc", "output, inc", "output llc"),
        ("Output Hub",),
        "Output Hub",
        "https://output.com/",
    ),
    VendorRegistryEntry(
        "spitfire",
        "Spitfire Audio",
        ("spitfire audio", "spitfire"),
        ("Spitfire Audio",),
        "Spitfire Audio",
        "https://www.spitfireaudio.com/",
    ),
    VendorRegistryEntry(
        "loopcloud",
        "Loopcloud",
        ("loopmasters", "loopcloud"),
        ("Loopcloud",),
        "Loopcloud",
        "https://www.loopcloud.com/",
    ),
    VendorRegistryEntry(
        "fabfilter",
        "FabFilter",
        ("fabfilter",),
        (),
        "FabFilter website",
        "https://www.fabfilter.com/",
        website_only=True,
    ),
    VendorRegistryEntry(
        "valhalla",
        "Valhalla DSP",
        ("valhalla dsp", "valhalla"),
        (),
        "Valhalla DSP website",
        "https://valhalladsp.com/",
        website_only=True,
    ),
    VendorRegistryEntry(
        "xfer",
        "Xfer Records",
        ("xfer records", "xfer"),
        (),
        "Xfer Records website",
        "https://xferrecords.com/",
        website_only=True,
    ),
    VendorRegistryEntry(
        "spectrasonics",
        "Spectrasonics",
        ("spectrasonics",),
        (),
        "Spectrasonics website",
        "https://www.spectrasonics.net/",
        website_only=True,
    ),
    VendorRegistryEntry(
        "ableton",
        "Ableton",
        ("ableton",),
        (),
        "Ableton website",
        "https://www.ableton.com/",
        website_only=True,
    ),
    VendorRegistryEntry(
        "celemony",
        "Celemony",
        ("celemony",),
        (),
        "Celemony website",
        "https://www.celemony.com/",
        website_only=True,
    ),
)


def _developer_matches_pattern(pattern: str, developer: str) -> bool:
    """
    Match *pattern* against *developer* with word-boundary safety.

    Multi-word patterns use phrase containment. Single-word patterns require a
    whole-word match (not a substring inside another word).
    """
    pat = pattern.strip().lower()
    dev = developer.strip().lower()
    if not pat or not dev:
        return False
    if pat.startswith("^") and pat.endswith("$"):
        return bool(re.search(pat, dev, re.IGNORECASE))
    if " " in pat:
        return pat in dev
    return bool(re.search(rf"\b{re.escape(pat)}\b", dev))


def match_vendor(developer: str) -> VendorRegistryEntry | None:
    """Return the first registry entry whose patterns match *developer*."""
    dev = (developer or "").strip()
    if not dev:
        return None
    for entry in VENDOR_REGISTRY:
        for pattern in entry.developer_patterns:
            if _developer_matches_pattern(pattern, dev):
                return entry
    return None


def resolve_manager_app(
    entry: VendorRegistryEntry,
    music_apps: list,
) -> ResolvedManager | None:
    """Return installed manager app name + path for *entry*, if found."""
    if entry.website_only or not entry.manager_app_names:
        return None
    for app in music_apps:
        name_lower = app.name.lower()
        for needle in entry.manager_app_names:
            needle_lower = needle.lower()
            if needle_lower in name_lower:
                return ResolvedManager(app_name=app.name, app_path=app.path)
    return None
