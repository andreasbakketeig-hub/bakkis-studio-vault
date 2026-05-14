"""
Plugin scanner — discovers audio plug-ins in standard macOS locations.
"""

from __future__ import annotations

import os
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

    @property
    def row(self) -> tuple[str, str, str]:
        return (self.name, self.fmt, self.path)


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
    Walk *paths* (defaults to SCAN_PATHS) and collect all recognized plug-in
    bundles.  Calls *progress_cb(message)* after each directory is processed so
    callers can update a progress indicator.
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


def _walk_plugins(root: Path) -> list[Plugin]:
    """Recursively collect plug-in bundles under *root*."""
    found: list[Plugin] = []

    try:
        for item in root.iterdir():
            suffix = item.suffix.lower()
            if suffix in PLUGIN_FORMATS:
                fmt = PLUGIN_FORMATS[suffix]
                found.append(Plugin(name=item.stem, fmt=fmt, path=str(item)))
            elif item.is_dir() and suffix not in PLUGIN_FORMATS:
                # Descend into plain directories (not into bundles)
                found.extend(_walk_plugins(item))
    except PermissionError:
        pass

    return found
