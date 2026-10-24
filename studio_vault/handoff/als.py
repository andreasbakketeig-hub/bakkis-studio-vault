"""
Read an Ableton Live Set (.als: gzip-compressed XML). Read-only: the file is
never written to.

What it reports (for the Handoff checks):
  - Live version the set was saved with, and its tempo
  - tracks: name, kind, frozen or not, the plug-ins and Max for Live devices on them
  - files the set refers to (samples, Max for Live devices), each with where it
    lives: inside the project, external, the sender's User Library, a Live Pack
    or Core Library, or built into Live — and whether it exists on this Mac

Where a file lives comes from FileRef/RelativePathType (Live 11 and 12):
    3 project folder · 1 external (absolute) · 6 User Library · 5 Live Pack or
    Core Library (LivePackName says which) · 7 built into Live · 0 none
Live 10 sets have no RelativePathType; their FileRef holds RelativePathElement
dirs plus a Name, resolved against the project folder.
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

MAX_XML_BYTES = 256 * 1024 * 1024

LOC_PROJECT = "project"
LOC_EXTERNAL = "external"
LOC_USER_LIBRARY = "user_library"
LOC_PACK = "pack"
LOC_BUILTIN = "builtin"
LOC_UNKNOWN = "unknown"

_PATH_TYPES = {"3": LOC_PROJECT, "1": LOC_EXTERNAL, "6": LOC_USER_LIBRARY, "5": LOC_PACK, "7": LOC_BUILTIN}

KIND_SAMPLE = "sample"
KIND_M4L = "max_device"

_PLUGIN_TAGS = {"VstPluginInfo": "VST", "Vst3PluginInfo": "VST3", "AuPluginInfo": "AU"}
_M4L_TAGS = ("MxDeviceAudioEffect", "MxDeviceMidiEffect", "MxDeviceInstrument")
_TRACK_TAGS = {"AudioTrack": "audio", "MidiTrack": "midi", "GroupTrack": "group", "ReturnTrack": "return",
               "MasterTrack": "main", "MainTrack": "main", "PreHearTrack": "prehear"}


class AlsError(Exception):
    """The file is not a Live Set this reader understands."""


@dataclass(frozen=True)
class PluginUse:
    name: str
    fmt: str            # VST | VST3 | AU
    vendor: str = ""    # AU only (Live stores the manufacturer for AUs)


@dataclass(frozen=True)
class FileUse:
    kind: str           # sample | max_device
    name: str           # file name
    location: str       # LOC_*
    relative_path: str = ""
    absolute_path: str = ""
    pack: str = ""      # Live Pack name for LOC_PACK ("Core Library" ships with Live)
    exists: bool | None = None   # on this Mac; None when it cannot be checked
    frozen: bool = False         # a freeze file of a frozen track


@dataclass
class Track:
    name: str
    kind: str
    frozen: bool = False
    plugins: list[PluginUse] = field(default_factory=list)
    max_devices: list[str] = field(default_factory=list)
    files: list[FileUse] = field(default_factory=list)

    @property
    def freeze_files(self) -> list[FileUse]:
        return [f for f in self.files if f.frozen]


@dataclass
class LiveSet:
    path: str
    name: str
    live_version: str = ""      # "12.1.10"
    tempo: float | None = None
    tracks: list[Track] = field(default_factory=list)

    @property
    def project_dir(self) -> Path:
        return Path(self.path).parent

    @property
    def track_count(self) -> int:
        """Audio, MIDI, group and return tracks; the Main track is not counted."""
        return sum(1 for t in self.tracks if t.kind not in ("main", "prehear"))

    @property
    def plugins(self) -> list[PluginUse]:
        seen: dict[tuple[str, str], PluginUse] = {}
        for t in self.tracks:
            for p in t.plugins:
                seen.setdefault((p.name.lower(), p.fmt), p)
        return sorted(seen.values(), key=lambda p: (p.name.lower(), p.fmt))

    @property
    def files(self) -> list[FileUse]:
        seen: dict[tuple[str, str], FileUse] = {}
        for t in self.tracks:
            for f in t.files:
                seen.setdefault((f.kind, f.absolute_path or f.relative_path or f.name), f)
        return list(seen.values())

    def tracks_using(self, plugin: PluginUse) -> list[str]:
        return [t.name for t in self.tracks
                if any(p.name.lower() == plugin.name.lower() and p.fmt == plugin.fmt for p in t.plugins)]


# ── helpers ───────────────────────────────────────────────────────────────────

def _value(el: ET.Element | None, child: str) -> str:
    if el is None:
        return ""
    node = el.find(child)
    return (node.get("Value") or "").strip() if node is not None else ""


def version_tuple(version: str) -> tuple[int, ...]:
    m = re.match(r"(\d+(?:\.\d+)*)", version or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def _track_name(track: ET.Element) -> str:
    name = track.find("Name")
    return _value(name, "EffectiveName") or _value(name, "UserName") or ""


def _file_ref(ref: ET.Element, project_dir: Path, kind: str, frozen: bool) -> FileUse | None:
    path_type = _value(ref, "RelativePathType")
    rel_node = ref.find("RelativePath")
    relative = (rel_node.get("Value") or "").strip() if rel_node is not None else ""
    absolute = _value(ref, "Path")
    pack = _value(ref, "LivePackName")

    if not path_type and rel_node is not None and rel_node.get("Value") is None:
        # Live 10: <RelativePath><RelativePathElement Dir="Samples"/>…</RelativePath><Name Value="x.wav"/>
        dirs = [e.get("Dir") or "" for e in rel_node.findall("RelativePathElement")]
        file_name = _value(ref, "Name")
        if not file_name:
            return None
        relative = "/".join([d for d in dirs if d] + [file_name])
        location = LOC_PROJECT if dirs and ".." not in dirs else LOC_UNKNOWN
    else:
        location = _PATH_TYPES.get(path_type, LOC_UNKNOWN if (relative or absolute) else "")
    if not location:
        return None                          # RelativePathType 0: no file
    if pack and location != LOC_PACK:
        location = LOC_PACK

    name = Path(relative or absolute).name
    if not name:
        return None
    exists: bool | None = None
    if location == LOC_PROJECT and relative:
        exists = (project_dir / relative).is_file()
    elif location in (LOC_EXTERNAL, LOC_USER_LIBRARY):
        # Like Live: try the absolute path, then the path relative to the project
        # (it still works after the project or the home folder moved).
        exists = bool(absolute) and Path(absolute).is_file()
        if not exists and relative:
            exists = (project_dir / relative).is_file()
    return FileUse(kind, name, location, relative, absolute, pack, exists, frozen)


def _within(track: ET.Element, tag: str) -> list[ET.Element]:
    return list(track.iter(tag))


# ── reading ───────────────────────────────────────────────────────────────────

def read(path: Path | str) -> LiveSet:
    """Read *path*. Raises AlsError with a user-facing message if it cannot."""
    path = Path(path)
    try:
        with path.open("rb") as raw:
            magic = raw.read(2)
    except OSError as exc:
        raise AlsError("Could not open the file.") from exc
    if not magic:
        raise AlsError("The file is empty.")
    if magic != b"\x1f\x8b":
        raise AlsError("Saved by Live 7 or older. Open it in a newer Live and save it first.")
    try:
        with gzip.open(path, "rb") as fh:
            data = fh.read(MAX_XML_BYTES + 1)
        if len(data) > MAX_XML_BYTES:
            raise AlsError("The file is too large to read.")
        root = ET.fromstring(data)
    except (OSError, EOFError, ET.ParseError) as exc:
        raise AlsError("The file is damaged or not a Live Set.") from exc
    if root.tag != "Ableton":
        raise AlsError("Not an Ableton Live Set.")

    live_set = root.find("LiveSet")
    if live_set is None:
        raise AlsError("Not an Ableton Live Set.")
    result = LiveSet(path=str(path), name=path.stem,
                     live_version=(root.get("Creator") or "").replace("Ableton Live", "").strip())
    project_dir = path.parent

    for tag, kind in _TRACK_TAGS.items():
        for track_el in live_set.iter(tag):
            if kind == "prehear":
                continue
            track = Track(name=_track_name(track_el) or ("Main" if kind == "main" else ""), kind=kind,
                          frozen=_value(track_el, "Freeze") == "true")
            if kind == "main" and result.tempo is None:
                tempo = track_el.find(".//Tempo/Manual")
                try:
                    result.tempo = float(tempo.get("Value")) if tempo is not None else None
                except (TypeError, ValueError):
                    result.tempo = None
            seen_plugins: set[tuple[str, str]] = set()
            for ptag, fmt in _PLUGIN_TAGS.items():
                for el in _within(track_el, ptag):
                    if fmt == "VST":
                        name, vendor = _value(el, "PlugName") or Path(_value(el, "Path")).stem, ""
                    else:
                        name, vendor = _value(el, "Name"), _value(el, "Manufacturer")
                    if name and (name.lower(), fmt) not in seen_plugins:
                        seen_plugins.add((name.lower(), fmt))
                        track.plugins.append(PluginUse(name, fmt, vendor))
            for mtag in _M4L_TAGS:
                for el in _within(track_el, mtag):
                    ref = el.find(".//PatchSlot//FileRef")
                    use = _file_ref(ref, project_dir, KIND_M4L, False) if ref is not None else None
                    label = _value(el, "UserName") or (Path(use.name).stem if use else "Max for Live device")
                    track.max_devices.append(label)
                    if use:
                        track.files.append(use)
            freeze_refs = {id(r) for seq in _within(track_el, "FreezeSequencer") for r in seq.iter("FileRef")}
            for sample_ref in _within(track_el, "SampleRef"):
                ref = sample_ref.find("FileRef")
                if ref is None:
                    continue
                use = _file_ref(ref, project_dir, KIND_SAMPLE, id(ref) in freeze_refs)
                if use:
                    track.files.append(use)
            result.tracks.append(track)
    return result


def other_sets(live_set: LiveSet) -> list[str]:
    """Other .als files next to this one (pick the main version before sending)."""
    folder = live_set.project_dir
    try:
        names = sorted(p.name for p in folder.iterdir()
                       if p.suffix.lower() == ".als" and not p.name.startswith("._"))
    except OSError:
        return []
    return [n for n in names if n != Path(live_set.path).name]
