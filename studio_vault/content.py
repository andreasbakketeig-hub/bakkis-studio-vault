"""
Presets and your own content: folders worth backing up before moving to a new Mac.

Plug-ins can be reinstalled; your presets, patches, user libraries and samples
cannot. Two sources:
  - KNOWN folders with a fixed place (Logic, Audio Unit presets, Ableton User
    Library, Native Instruments, FabFilter, Serum, Splice)
  - folders in ~/Documents and ~/Music named after a vendor whose plug-ins are
    on this Mac (KORG, Eventide, Spitfire Audio …)

Only folders that exist are listed. Sizes are measured with a time budget per
folder so a huge sample folder cannot stall the scan. Read-only.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from studio_vault.vendors import developer_group

SIZE_BUDGET_SECONDS = 1.0

# (label, path relative to the home folder)
KNOWN: tuple[tuple[str, str], ...] = (
    ("Logic Pro: patches, channel strips, plug-in settings", "Music/Audio Music Apps"),
    ("Audio Unit presets (all vendors)", "Library/Audio/Presets"),
    ("Ableton Live User Library", "Music/Ableton/User Library"),
    ("Native Instruments user content", "Documents/Native Instruments"),
    ("FabFilter presets", "Documents/FabFilter"),
    ("Serum presets", "Documents/Xfer"),
    ("Splice samples", "Splice"),
)

VENDOR_ROOTS: tuple[str, ...] = ("Documents", "Music")


@dataclass(frozen=True)
class ContentFolder:
    label: str
    path: str          # absolute
    size: int          # bytes (lower bound when approximate)
    files: int
    approximate: bool  # the time budget ran out before every file was counted


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def folder_size(path: Path, budget: float = SIZE_BUDGET_SECONDS) -> tuple[int, int, bool]:
    """(bytes, files, approximate) for *path*, stopping after *budget* seconds."""
    start = time.monotonic()
    total = files = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
                files += 1
            except OSError:
                pass
        if time.monotonic() - start > budget:
            return total, files, True
    return total, files, False


def find(vendor_names: Iterable[str], home: Path | None = None,
         budget: float = SIZE_BUDGET_SECONDS) -> list[ContentFolder]:
    """Existing content folders on this Mac, known ones first, then vendor folders."""
    home = home or Path.home()
    found: dict[str, str] = {}
    for label, rel in KNOWN:
        path = home / rel
        if path.is_dir():
            found[str(path)] = label

    # "Korg Inc" → "korg"; company suffixes are dropped before matching folder names.
    wanted = {_norm(developer_group(v)[1]) for v in vendor_names}
    wanted = {w for w in wanted if len(w) >= 3 and w != "other"}
    known_paths = set(found)
    for root in VENDOR_ROOTS:
        base = home / root
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith(".") or str(entry) in known_paths:
                continue
            # "~/Music/Ableton" holds the User Library listed above, plus reinstallable packs.
            if any(k.startswith(str(entry) + os.sep) for k in known_paths):
                continue
            key = _norm(entry.name)
            if any(key == w or key.startswith(w) for w in wanted):
                found[str(entry)] = f"{entry.name} ({root})"

    out: list[ContentFolder] = []
    for path, label in found.items():
        size, files, approximate = folder_size(Path(path), budget)
        if files:
            out.append(ContentFolder(label, path, size, files, approximate))
    return out
