"""
Plugin scanner — discovers audio plug-ins in standard macOS locations
and extracts bundle metadata via Info.plist and filesystem stats.
"""

from __future__ import annotations

import datetime
import os
import plistlib
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

    # 1. AudioComponents array (AU / VST3 often populate this)
    audio_components = plist.get("AudioComponents") or []
    if audio_components and isinstance(audio_components, list):
        comp_name: str = audio_components[0].get("name", "")
        if ":" in comp_name:
            developer = comp_name.split(":")[0].strip()

    # 2. CFBundleGetInfoString  e.g. "Plugin 2.0, © 2023 Acme Audio"
    if not developer:
        info_str: str = plist.get("CFBundleGetInfoString", "")
        if "©" in info_str:
            parts = info_str.split("©")
            candidate = parts[-1].strip().split(" ")[0]
            if len(candidate) > 2:
                developer = candidate

    # 3. NSHumanReadableCopyright  e.g. "© 2023 Acme Audio, Inc."
    if not developer:
        copyright_str: str = plist.get("NSHumanReadableCopyright", "")
        if copyright_str:
            # Strip leading "© YYYY " pattern
            import re
            match = re.search(r"©\s*\d{0,4}\s*([\w\s&]+?)(?:,|\.|Inc|LLC|Ltd|$)", copyright_str)
            if match:
                developer = match.group(1).strip()

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
