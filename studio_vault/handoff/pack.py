"""
Pack a checked Live project into one zip for a collaborator.

    Track_v08_AB.zip
    └── Track_v08_AB Project/
        ├── Track_v08_AB.als        the main set, renamed to the version name
        ├── HANDOFF.txt             version, tempo, plug-ins, frozen tracks, what changed …
        ├── Samples/ …              everything else in the project folder
        └── Ableton Project Info/

Left out of the zip (never deleted from the project folder): Backup/, *.asd analysis files,
.DS_Store / ._* files and the other .als versions. The project folder is only read; the
only file written is the zip the user chose. Packing is refused while the check is red.

Self-contained: standard library only.
"""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from studio_vault.handoff.als import LiveSet, other_sets
from studio_vault.handoff.check import RED, Report

SKIP_DIRS = {"Backup", ".git", "__MACOSX"}
SKIP_SUFFIXES = (".asd",)
SKIP_NAMES = {".DS_Store", "Icon\r"}
# Audio is already compressed or does not shrink: store it, deflate the rest.
STORED_SUFFIXES = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".alac", ".zip")

_VERSION = re.compile(r"^(?P<base>.*?)[ _\-]*v(?P<num>\d{1,3})(?:[ _\-]+(?P<who>[A-Za-z]{1,4}))?$", re.IGNORECASE)


class PackError(Exception):
    """Packing was refused or failed; the message is for the user."""


@dataclass(frozen=True)
class PackResult:
    zip_path: str
    version_name: str
    files: int
    bytes: int


# ── version names ─────────────────────────────────────────────────────────────

def initials_from_name(full_name: str) -> str:
    """'Andreas Bakketeig' → 'AB'."""
    parts = [p for p in re.split(r"[\s\-]+", full_name or "") if p and p[0].isalpha()]
    return "".join(p[0].upper() for p in parts[:3])


def user_initials() -> str:
    """Initials from this Mac's account name (System Settings › Users & Groups)."""
    try:
        name = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        name = ""
    return initials_from_name(name)


def split_version(name: str) -> tuple[str, int | None]:
    """'Track_v07_AB' → ('Track', 7); 'Track' → ('Track', None)."""
    m = _VERSION.match(name.strip())
    if not m or not m.group("base").strip(" _-"):
        return name.strip(), None
    return m.group("base").strip(" _-"), int(m.group("num"))


def suggest_version_name(live_set: LiveSet, initials: str) -> str:
    """Next version after every version of this set in its folder: 'Track_v08_AB'."""
    base, current = split_version(live_set.name)
    numbers = [current or 0]
    for other in other_sets(live_set):
        b, n = split_version(Path(other).stem)
        if n is not None and b.lower() == base.lower():
            numbers.append(n)
    name = f"{base}_v{max(numbers) + 1:02d}"
    return f"{name}_{initials}" if initials else name


def clean_version_name(name: str) -> str:
    """A safe file and folder name (no slashes, colons or leading dots)."""
    name = re.sub(r"[/\\:\x00-\x1f]+", "-", (name or "").strip()).strip(" .")
    if not name:
        raise PackError("Give the version a name.")
    return name[:120]


# ── HANDOFF.txt ───────────────────────────────────────────────────────────────

def handoff_text(live_set: LiveSet, report: Report, version_name: str, note: str, sender: str = "",
                 now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    lines = [
        f"HANDOFF — {version_name}",
        "=" * (10 + len(version_name)),
        "",
        f"Date:           {now.strftime('%Y-%m-%d %H:%M')}",
    ]
    if sender:
        lines.append(f"From:           {sender}")
    if report.receiver:
        lines.append(f"Checked for:    {report.receiver}")
    lines += [
        f"Live Set:       {version_name}.als (was {live_set.name}.als)",
        f"Live version:   {live_set.live_version or 'unknown'}",
        f"Tempo:          {live_set.tempo:g} BPM" if live_set.tempo else "Tempo:          unknown",
        f"Tracks:         {live_set.track_count} (Main not counted)",
        "",
        "WHAT CHANGED",
        "------------",
        note.strip(),
        "",
        "PLUG-INS",
        "--------",
    ]
    if report.plugins:
        label = {"missing": "  [receiver does not have it]", "other_format": "  [receiver has another format]"}
        for p in report.plugins:
            vendor = f", {p['vendor']}" if p.get("vendor") else ""
            tracks = f" — {', '.join(p['tracks'])}" if p.get("tracks") else ""
            lines.append(f"- {p['name']} ({p['fmt']}{vendor}){tracks}{label.get(p.get('status'), '')}")
    else:
        lines.append("None (only Live's own devices).")
    frozen = [t.name for t in live_set.tracks if t.frozen]
    lines += ["", "FROZEN TRACKS", "-------------"] + ([f"- {t}" for t in frozen] or ["None."])
    devices = sorted({d for t in live_set.tracks for d in t.max_devices}, key=str.lower)
    if devices:
        lines += ["", "MAX FOR LIVE (needs Live Suite or a Max for Live license)", "---------------"]
        lines += [f"- {d}" for d in devices]
    packs = sorted({f.pack for f in live_set.files if f.pack and f.pack != "Core Library"})
    if packs:
        lines += ["", "LIVE PACKS USED", "---------------"] + [f"- {p}" for p in packs]
    notes = [f for f in report.findings if f.level != "green"]
    if notes:
        lines += ["", "CHECK BEFORE OPENING", "--------------------"]
        for f in notes:
            lines.append(f"- {f.title}")
            lines += [f"    {item}" for item in f.items[:12]]
    lines += [
        "",
        "NOT IN THIS PACKAGE",
        "-------------------",
        "- Libraries inside plug-ins (Kontakt libraries, Serum wavetables, presets)",
        "- Plug-ins themselves: install them before opening the set",
        "",
        "Packed with BAKKIS STUDIO VAULT · Handoff",
        "",
    ]
    return "\n".join(lines)


# ── packing ───────────────────────────────────────────────────────────────────

def files_to_pack(live_set: LiveSet, exclude: Path | None = None) -> list[Path]:
    """Every file in the project folder that goes in the zip (the main set included)."""
    root = live_set.project_dir
    main = Path(live_set.path).resolve()
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if (name in SKIP_NAMES or name.startswith("._") or name.lower().endswith(SKIP_SUFFIXES)
                    or (name.lower().endswith(".als") and path.resolve() != main)
                    or (exclude is not None and path.resolve() == exclude)):
                continue
            out.append(path)
    return out


def pack(live_set: LiveSet, report: Report, dest: Path | str, version_name: str, note: str,
         sender: str = "", progress: Callable[[int, int], None] | None = None,
         cancelled: Callable[[], bool] | None = None) -> PackResult:
    """Write the zip to *dest*. Raises PackError when refused (red, no note) or on failure."""
    if report.level == RED:
        raise PackError("Fix the red points first: something would be missing for the receiver.")
    if not (note or "").strip():
        raise PackError('Write what you changed ("What did you change?") before packing.')
    version_name = clean_version_name(version_name)
    dest = Path(dest)
    if dest.suffix.lower() != ".zip":
        dest = dest.with_name(dest.name + ".zip")
    root_dir = live_set.project_dir.resolve()
    if dest.resolve().parent == root_dir or root_dir in dest.resolve().parents:
        raise PackError("Save the zip outside the project folder.")

    files = files_to_pack(live_set, exclude=dest.resolve())
    total = sum(p.stat().st_size for p in files)
    top = f"{version_name} Project"
    main = Path(live_set.path).resolve()
    tmp = dest.with_name(dest.name + ".part")
    done = 0
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            zf.writestr(f"{top}/HANDOFF.txt", handoff_text(live_set, report, version_name, note, sender))
            for path in files:
                if cancelled is not None and cancelled():
                    raise PackError("Packing cancelled.")
                rel = path.relative_to(live_set.project_dir)
                arc = f"{top}/{version_name}.als" if path.resolve() == main else f"{top}/{rel.as_posix()}"
                method = zipfile.ZIP_STORED if path.suffix.lower() in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
                zf.write(path, arc, compress_type=method)
                done += path.stat().st_size
                if progress is not None:
                    progress(done, total)
        tmp.replace(dest)
    except PackError:
        tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise PackError(f"Could not write the zip: {exc.strerror or exc}") from exc
    return PackResult(str(dest), version_name, len(files) + 1, total)
