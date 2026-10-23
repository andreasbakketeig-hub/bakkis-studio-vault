"""
Plug-in scanner — discovers audio plug-ins in standard macOS locations
and extracts bundle metadata via Info.plist and filesystem stats.

Read-only. Bundle sizes are cached by path + modification times so a rescan
does not walk every file inside large sample-based plug-ins again.
"""

from __future__ import annotations

import datetime
import json
import os
import plistlib
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

# ── Format registry ──────────────────────────────────────────────────────────

PLUGIN_FORMATS: dict[str, str] = {
    ".vst": "VST",
    ".vst3": "VST3",
    ".component": "AU",
    ".aaxplugin": "AAX",
    ".clap": "CLAP",
}

FORMAT_ORDER: list[str] = ["VST3", "AU", "CLAP", "VST", "AAX"]

ARCH_UNIVERSAL = "universal"
ARCH_ARM = "arm64"
ARCH_INTEL = "intel"

KIND_INSTRUMENT = "Instrument"
KIND_EFFECT = "Effect"
KIND_MIDI = "MIDI"

# AudioComponents "type" codes (AU, and some other formats that carry the same plist key).
_AU_TYPE_KIND = {"aumu": KIND_INSTRUMENT, "aufx": KIND_EFFECT, "aumf": KIND_EFFECT, "aumi": KIND_MIDI}

SCAN_PATHS: list[str] = [
    "/Library/Audio/Plug-Ins/VST",
    "/Library/Audio/Plug-Ins/VST3",
    "/Library/Audio/Plug-Ins/Components",
    "/Library/Audio/Plug-Ins/CLAP",
    "/Library/Application Support/Avid/Audio/Plug-Ins",
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST"),
    os.path.expanduser("~/Library/Audio/Plug-Ins/VST3"),
    os.path.expanduser("~/Library/Audio/Plug-Ins/Components"),
    os.path.expanduser("~/Library/Audio/Plug-Ins/CLAP"),
]


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Plugin:
    name: str
    fmt: str
    path: str
    version: str = ""
    developer: str = ""
    bundle_id: str = ""
    file_size: int = 0        # bytes
    modified: str = ""        # ISO date string YYYY-MM-DD
    kind: str = ""            # KIND_INSTRUMENT | KIND_EFFECT | KIND_MIDI | "" (unknown)
    arch: str = ""            # ARCH_UNIVERSAL | ARCH_ARM | ARCH_INTEL | "" (unknown)
    min_macos: str = ""       # LSMinimumSystemVersion, e.g. "10.13"


@dataclass
class ScanResult:
    plugins: list[Plugin] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def count(self) -> int:
        return len(self.plugins)


class CancelFlag(Protocol):
    def is_set(self) -> bool: ...


# ── Format coverage ───────────────────────────────────────────────────────────

def normalize_product_name(name: str) -> str:
    """Strip common format suffixes so the same product groups across formats."""
    cleaned = re.sub(r"[\s_\-]*(vst3?|au|aax|clap)\s*$", "", name, flags=re.IGNORECASE).strip()
    return (cleaned or name).lower()


@dataclass
class FormatGroup:
    """One logical product that may exist in several format copies."""

    product_name: str
    developer: str
    formats: dict[str, Plugin]  # fmt -> representative Plugin

    @property
    def format_names(self) -> list[str]:
        present = set(self.formats.keys())
        ordered = [f for f in FORMAT_ORDER if f in present]
        ordered += sorted(present - set(FORMAT_ORDER))
        return ordered


def group_by_product(plugins: list[Plugin]) -> list[FormatGroup]:
    """Group *plugins* by normalised product name, sorted alphabetically."""
    groups: dict[str, FormatGroup] = {}
    for plugin in plugins:
        key = normalize_product_name(plugin.name)
        group = groups.get(key)
        if group is None:
            group = groups[key] = FormatGroup(plugin.name, plugin.developer, {})
        group.formats[plugin.fmt] = plugin
        if not group.developer and plugin.developer:
            group.developer = plugin.developer
    return sorted(groups.values(), key=lambda g: g.product_name.lower())


# ── Size cache ────────────────────────────────────────────────────────────────

class SizeCache:
    """
    Bundle size cache keyed by path, valid while the bundle's and its
    Info.plist's modification times are unchanged (installers replace both).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._entries: dict[str, tuple[int, int, int]] = {}
        self._dirty = False
        if path is not None and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._entries = {k: tuple(v) for k, v in raw.items() if len(v) == 3}
            except (OSError, ValueError, TypeError):
                self._entries = {}

    def size_of(self, bundle: Path) -> int:
        stamp = _mtime_stamp(bundle)
        cached = self._entries.get(str(bundle))
        if cached is not None and (cached[0], cached[1]) == stamp:
            return cached[2]
        size = bundle_size(bundle)
        self._entries[str(bundle)] = (stamp[0], stamp[1], size)
        self._dirty = True
        return size

    def save(self) -> None:
        if self._path is None or not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._entries), encoding="utf-8")
            tmp.replace(self._path)
            self._dirty = False
        except OSError:
            pass


def _mtime_stamp(bundle: Path) -> tuple[int, int]:
    def mtime(p: Path) -> int:
        try:
            return p.stat().st_mtime_ns
        except OSError:
            return 0
    return mtime(bundle), mtime(bundle / "Contents" / "Info.plist")


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_plugins(
    paths: list[str] | None = None,
    progress_cb: Callable[[str], None] | None = None,
    cancel: CancelFlag | None = None,
    size_cache: SizeCache | None = None,
) -> ScanResult:
    """
    Walk *paths* (defaults to SCAN_PATHS) and collect all recognised plug-in
    bundles with metadata. Calls *progress_cb(message)* per folder and stops
    early when *cancel* is set.
    """
    targets = paths if paths is not None else SCAN_PATHS
    cache = size_cache or SizeCache()
    result = ScanResult()
    seen: set[str] = set()

    for base in targets:
        if cancel is not None and cancel.is_set():
            result.cancelled = True
            break
        base_path = Path(base)
        if progress_cb:
            progress_cb(f"Scanning {base_path}…")
        if not base_path.exists():
            continue
        for bundle in _find_bundles(base_path, cancel):
            key = str(bundle)
            if key in seen:
                continue
            seen.add(key)
            result.plugins.append(_read_plugin(bundle, cache))

    if cancel is not None and cancel.is_set():
        result.cancelled = True
    cache.save()
    if progress_cb:
        progress_cb(f"Done — {result.count} plug-in(s) found.")
    return result


def _find_bundles(root: Path, cancel: CancelFlag | None) -> list[Path]:
    """Recursively collect plug-in bundles under *root* (vendor subfolders included)."""
    found: list[Path] = []
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for item in entries:
        if cancel is not None and cancel.is_set():
            break
        if item.suffix.lower() in PLUGIN_FORMATS:
            found.append(item)
        elif item.is_dir() and not item.is_symlink():
            found.extend(_find_bundles(item, cancel))
    return found


def _read_plugin(bundle: Path, cache: SizeCache) -> Plugin:
    meta = bundle_metadata(bundle)
    return Plugin(
        name=bundle.stem,
        fmt=PLUGIN_FORMATS[bundle.suffix.lower()],
        path=str(bundle),
        file_size=cache.size_of(bundle),
        **meta,
    )


# ── Bundle metadata ───────────────────────────────────────────────────────────

def bundle_metadata(bundle: Path) -> dict:
    """Extract version, developer, bundle_id and modified date from a bundle."""
    meta: dict = {"version": "", "developer": "", "bundle_id": "", "modified": "", "kind": "", "arch": "", "min_macos": ""}

    try:
        meta["modified"] = datetime.datetime.fromtimestamp(
            bundle.stat().st_mtime
        ).strftime("%Y-%m-%d")
    except OSError:
        pass

    plist_path = bundle / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as fh:
            plist: dict = plistlib.load(fh)
    except Exception:
        return meta

    meta["version"] = str(
        plist.get("CFBundleShortVersionString")
        or plist.get("CFBundleVersion")
        or ""
    ).strip()
    meta["bundle_id"] = str(plist.get("CFBundleIdentifier") or "").strip()
    meta["developer"] = _developer_from_plist(plist)
    meta["kind"] = _kind_from_plist(plist) or _kind_from_vst3_moduleinfo(bundle)
    meta["min_macos"] = str(plist.get("LSMinimumSystemVersion") or "").strip()
    executable = str(plist.get("CFBundleExecutable") or "").strip()
    if executable and "/" not in executable:
        meta["arch"] = binary_arch(bundle / "Contents" / "MacOS" / executable)
    return meta


# Mach-O CPU types (mach/machine.h)
_CPU_X86_64 = 0x01000007
_CPU_ARM64 = 0x0100000C


def binary_arch(path: Path) -> str:
    """ARCH_* for a Mach-O binary, read from its header only (the binary is never loaded)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(8 + 32 * 8)
    except OSError:
        return ""
    if len(head) < 8:
        return ""
    magic = struct.unpack(">I", head[:4])[0]
    cpus: set[int] = set()
    if magic in (0xCAFEBABE, 0xCAFEBABF):          # fat / universal (big-endian header)
        count = struct.unpack(">I", head[4:8])[0]
        step = 20 if magic == 0xCAFEBABE else 32
        for i in range(min(count, 8)):
            off = 8 + i * step
            if off + 4 <= len(head):
                cpus.add(struct.unpack(">i", head[off:off + 4])[0])
    elif magic in (0xCFFAEDFE, 0xCEFAEDFE):        # thin, little-endian
        cpus.add(struct.unpack("<i", head[4:8])[0])
    else:
        return ""
    arm, intel = _CPU_ARM64 in cpus, _CPU_X86_64 in cpus
    if arm and intel:
        return ARCH_UNIVERSAL
    if arm:
        return ARCH_ARM
    if intel:
        return ARCH_INTEL
    return ""


def _kind_from_plist(plist: dict) -> str:
    components = plist.get("AudioComponents") or []
    if components and isinstance(components, list) and isinstance(components[0], dict):
        return _AU_TYPE_KIND.get(str(components[0].get("type", "")).lower(), "")
    return ""


_SUBCATS = re.compile(r'"Sub Categories"\s*:\s*\[([^\]]*)\]')


def _kind_from_vst3_moduleinfo(bundle: Path) -> str:
    """VST3 bundles may ship Contents/Resources/moduleinfo.json (JSON5-ish: trailing commas)."""
    path = bundle / "Contents" / "Resources" / "moduleinfo.json"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    cats = {c.strip().strip('"').lower() for block in _SUBCATS.findall(text) for c in block.split(",")}
    if "instrument" in cats:
        return KIND_INSTRUMENT
    if "fx" in cats:
        return KIND_EFFECT
    return ""


def _is_year_or_version(s: str) -> bool:
    """Return True when s is a bare year, year-range, or version number."""
    return bool(re.fullmatch(r"\d{4}(?:-\d{4})?|\d+\.\d+(?:\.\d+)*", s.strip()))


def _developer_from_plist(plist: dict) -> str:
    # 1. AudioComponents array (AU / VST3 often populate this).
    #    Format is "Manufacturer: Plugin Name" — use the part before the colon.
    #    If no colon is present, fall back to the explicit 'manufacturer' string key.
    audio_components = plist.get("AudioComponents") or []
    if audio_components and isinstance(audio_components, list):
        comp = audio_components[0]
        comp_name = str(comp.get("name", ""))
        if ":" in comp_name:
            candidate = comp_name.split(":")[0].strip()
            if candidate and not _is_year_or_version(candidate):
                return candidate
        # 'manufacturer' is a 4-char OSType int on most plists, occasionally a name.
        mfr = comp.get("manufacturer", "")
        if isinstance(mfr, str) and len(mfr) > 2 and not _is_year_or_version(mfr):
            return mfr.strip()

    # 2. CFBundleGetInfoString  e.g. "Plugin 2.0, © 2023 Acme Audio" or "© 2016 - 2023 Korg Inc"
    info_str = str(plist.get("CFBundleGetInfoString", ""))
    if "©" in info_str:
        after_copy = info_str.split("©")[-1].strip()
        after_copy = re.sub(r"^\d{4}(?:\s*[-–]\s*\d{4})?\s*", "", after_copy)
        candidate = re.split(r"[,.\n]", after_copy)[0].strip()
        if candidate and not _is_year_or_version(candidate):
            return candidate

    # 3. NSHumanReadableCopyright  e.g. "© 2023 Acme Audio, Inc."
    #    Year-ranges like "2001-2023" must be consumed before the capture group.
    copyright_str = str(plist.get("NSHumanReadableCopyright", ""))
    if copyright_str:
        match = re.search(
            r"©\s*\d{4}(?:\s*[-–]\s*\d{4})?\s*([\w][\w\s&\-]*?)(?:\s*,|\s*\.|Inc|LLC|Ltd|GmbH|AB|BV|$)",
            copyright_str,
        )
        if match:
            candidate = match.group(1).strip()
            if candidate and not _is_year_or_version(candidate):
                return candidate

    # 4. CFBundleIdentifier  e.g. "com.acmeaudio.reverb"  → "Acmeaudio"
    parts = str(plist.get("CFBundleIdentifier", "")).split(".")
    if len(parts) >= 2 and parts[0] in ("com", "org", "net", "io", "audio"):
        return parts[1].replace("-", " ").replace("_", " ").title()
    return ""


def bundle_size(path: Path) -> int:
    """Return total byte size of a file or bundle directory."""
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total
