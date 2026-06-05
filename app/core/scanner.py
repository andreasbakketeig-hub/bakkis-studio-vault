"""
Plugin scanner — discovers audio plug-ins in standard macOS locations
and extracts bundle metadata via Info.plist and filesystem stats.
"""

from __future__ import annotations

import datetime
import os
import plistlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ── Format registry ──────────────────────────────────────────────────────────

PLUGIN_FORMATS: dict[str, str] = {
    ".vst": "VST",
    ".vst3": "VST3",
    ".component": "AU",
    ".aaxplugin": "AAX",
}

SCAN_PATHS: list[str] = [
    "/Library/Audio/Plug-Ins/VST",
    "/Library/Audio/Plug-Ins/VST3",
    "/Library/Audio/Plug-Ins/Components",
    "/Library/Application Support/Avid/Audio/Plug-Ins",
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST"),
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST3"),
    os.path.expanduser("~/Library/Audio/Plug-Ins/Components"),
]


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Plugin:
    name: str
    fmt: str
    path: str
    version: str = ""
    developer: str = ""
    file_size: int = 0        # bytes
    modified: str = ""        # ISO date string YYYY-MM-DD

    @property
    def file_size_human(self) -> str:
        return _fmt_size(self.file_size)

    @property
    def row(self) -> tuple[str, str, str, str, str, str, str]:
        return (
            self.name,
            self.developer,
            self.version,
            self.fmt,
            self.file_size_human,
            self.modified,
            self.path,
        )


@dataclass
class ScanResult:
    plugins: list[Plugin] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.plugins)


# ── Format-group analysis ─────────────────────────────────────────────────────

_FORMAT_PRIORITY: list[str] = ["VST3", "AU", "VST", "AAX"]


def _normalize_product_name(name: str) -> str:
    """Strip common format suffixes so the same product groups across formats."""
    cleaned = re.sub(r"[\s_\-]*(vst3?|au|aax)\s*$", "", name, flags=re.IGNORECASE).strip()
    return (cleaned or name).lower()


@dataclass
class FormatGroup:
    """One logical product that may exist in several format copies."""

    product_name: str
    developer: str
    formats: dict[str, Plugin]  # fmt -> representative Plugin

    @property
    def is_duplicate(self) -> bool:
        return len(self.formats) > 1

    @property
    def total_size(self) -> int:
        return sum(p.file_size for p in self.formats.values())

    @property
    def redundant_size(self) -> int:
        """Bytes that could be reclaimed by keeping only the largest copy."""
        if not self.is_duplicate:
            return 0
        sizes = sorted(p.file_size for p in self.formats.values())
        return sum(sizes[:-1])

    @property
    def format_names(self) -> list[str]:
        present = set(self.formats.keys())
        ordered = [f for f in _FORMAT_PRIORITY if f in present]
        ordered += sorted(present - set(_FORMAT_PRIORITY))
        return ordered


def analyze_formats(plugins: list[Plugin]) -> list[FormatGroup]:
    """
    Group *plugins* by normalised product name and return one
    :class:`FormatGroup` per logical product, sorted alphabetically.
    """
    raw: dict[str, dict] = {}
    for plugin in plugins:
        key = _normalize_product_name(plugin.name)
        if key not in raw:
            raw[key] = {
                "product_name": plugin.name,
                "developer": plugin.developer,
                "formats": {},
            }
        raw[key]["formats"][plugin.fmt] = plugin
        if not raw[key]["developer"] and plugin.developer:
            raw[key]["developer"] = plugin.developer

    groups = [
        FormatGroup(
            product_name=g["product_name"],
            developer=g["developer"],
            formats=g["formats"],
        )
        for g in raw.values()
    ]
    return sorted(groups, key=lambda g: g.product_name.lower())


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_plugins(
    paths: list[str] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> ScanResult:
    """
    Walk *paths* (defaults to SCAN_PATHS) and collect all recognised plug-in
    bundles with metadata.  Calls *progress_cb(message)* for UI updates.
    """
    targets = paths if paths is not None else SCAN_PATHS
    result = ScanResult()
    seen: set[str] = set()

    for base in targets:
        base_path = Path(base)
        if progress_cb:
            progress_cb(f"Scanning {base_path}…")

        if not base_path.exists():
            continue

        try:
            for entry in _walk_plugins(base_path):
                if entry.path not in seen:
                    seen.add(entry.path)
                    result.plugins.append(entry)
        except PermissionError as exc:
            result.errors.append(str(exc))

    if progress_cb:
        progress_cb(f"Done — {result.count} plug-in(s) found.")

    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _walk_plugins(root: Path) -> list[Plugin]:
    """Recursively collect plug-in bundles under *root*."""
    found: list[Plugin] = []
    try:
        for item in root.iterdir():
            suffix = item.suffix.lower()
            if suffix in PLUGIN_FORMATS:
                fmt = PLUGIN_FORMATS[suffix]
                meta = _bundle_metadata(item)
                found.append(Plugin(
                    name=item.stem,
                    fmt=fmt,
                    path=str(item),
                    **meta,
                ))
            elif item.is_dir() and suffix not in PLUGIN_FORMATS:
                found.extend(_walk_plugins(item))
    except PermissionError:
        pass
    return found


def _bundle_metadata(bundle: Path) -> dict:
    """Extract version, developer, file_size, and modified from a bundle."""
    meta: dict = {
        "version": "",
        "developer": "",
        "file_size": 0,
        "modified": "",
    }

    # ── Filesystem stats ──────────────────────────────────────────────────
    try:
        stat = bundle.stat()
        mtime = stat.st_mtime
        meta["modified"] = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        meta["file_size"] = _bundle_size(bundle)
    except OSError:
        pass

    # ── Info.plist ────────────────────────────────────────────────────────
    plist_path = bundle / "Contents" / "Info.plist"
    if not plist_path.exists():
        return meta

    try:
        with plist_path.open("rb") as fh:
            plist: dict = plistlib.load(fh)
    except Exception:
        return meta

    # Version — prefer human-readable short string
    meta["version"] = (
        plist.get("CFBundleShortVersionString")
        or plist.get("CFBundleVersion")
        or ""
    ).strip()

    # Developer — try several keys in priority order
    developer = ""

    def _is_year_or_version(s: str) -> bool:
        """Return True when s is a bare year, year-range, or version number."""
        return bool(re.fullmatch(r"\d{4}(?:-\d{4})?|\d+\.\d+(?:\.\d+)*", s.strip()))

    # 1. AudioComponents array (AU / VST3 often populate this).
    #    Format is "Manufacturer: Plugin Name" — use the part before the colon.
    #    If no colon is present, fall back to the explicit 'manufacturer' string key.
    audio_components = plist.get("AudioComponents") or []
    if audio_components and isinstance(audio_components, list):
        comp = audio_components[0]
        comp_name: str = comp.get("name", "")
        if ":" in comp_name:
            candidate = comp_name.split(":")[0].strip()
            if candidate and not _is_year_or_version(candidate):
                developer = candidate
        if not developer:
            # 'manufacturer' inside AudioComponents is a 4-char OSType int on
            # some plists, but is occasionally a human-readable string.
            mfr = comp.get("manufacturer", "")
            if isinstance(mfr, str) and len(mfr) > 2 and not _is_year_or_version(mfr):
                developer = mfr.strip()

    # 2. CFBundleGetInfoString  e.g. "Plugin 2.0, © 2023 Acme Audio"
    #    Split on ©, strip the leading year / year-range, then take the text
    #    up to the first comma or period as the vendor name.
    if not developer:
        info_str: str = plist.get("CFBundleGetInfoString", "")
        if "©" in info_str:
            after_copy = info_str.split("©")[-1].strip()
            # Remove leading year or year-range (e.g. "2023" or "2001-2023")
            after_copy = re.sub(r"^\d{4}(?:-\d{4})?\s*", "", after_copy)
            candidate = re.split(r"[,.\n]", after_copy)[0].strip()
            if candidate and not _is_year_or_version(candidate):
                developer = candidate

    # 3. NSHumanReadableCopyright  e.g. "© 2023 Acme Audio, Inc."
    #    Year-ranges like "2001-2023" must be consumed before the capture group.
    if not developer:
        copyright_str: str = plist.get("NSHumanReadableCopyright", "")
        if copyright_str:
            match = re.search(
                r"©\s*\d{4}(?:-\d{4})?\s*([\w][\w\s&\-]*?)(?:\s*,|\s*\.|Inc|LLC|Ltd|GmbH|AB|BV|$)",
                copyright_str,
            )
            if match:
                candidate = match.group(1).strip()
                if candidate and not _is_year_or_version(candidate):
                    developer = candidate

    # 4. CFBundleIdentifier  e.g. "com.acmeaudio.reverb"  → "Acmeaudio"
    if not developer:
        bundle_id: str = plist.get("CFBundleIdentifier", "")
        parts = bundle_id.split(".")
        if len(parts) >= 2 and parts[0] in ("com", "org", "net", "io", "audio"):
            developer = parts[1].replace("-", " ").replace("_", " ").title()

    meta["developer"] = developer
    return meta


def _bundle_size(path: Path) -> int:
    """Return total byte size of a file or bundle directory."""
    if path.is_file():
        return path.stat().st_size
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
    except PermissionError:
        pass
    return total


def _fmt_size(n: int) -> str:
    if n == 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
