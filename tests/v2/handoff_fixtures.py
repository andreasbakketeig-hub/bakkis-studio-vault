"""Build small Live Sets (.als) for the Handoff tests. Shapes follow real Live 11/12 sets."""

from __future__ import annotations

import gzip
from pathlib import Path


def file_ref(path_type: int, relative: str = "", absolute: str = "", pack: str = "") -> str:
    return (f'<FileRef><RelativePathType Value="{path_type}" /><RelativePath Value="{relative}" />'
            f'<Path Value="{absolute}" /><Type Value="2" /><LivePackName Value="{pack}" />'
            f'<LivePackId Value="" /></FileRef>')


def sample(ref: str) -> str:
    return f"<AudioClip><SampleRef>{ref}<LastModDate Value=\"0\" /></SampleRef></AudioClip>"


def vst(name: str) -> str:
    return (f'<PluginDevice><PluginDesc><VstPluginInfo Id="0"><Path Value="/Library/Audio/Plug-Ins/VST/{name}.vst" />'
            f'<PlugName Value="{name}" /><Preset><VstPreset Id="1"><Name Value="preset" /></VstPreset></Preset>'
            f'</VstPluginInfo></PluginDesc></PluginDevice>')


def vst3(name: str) -> str:
    return f'<PluginDevice><PluginDesc><Vst3PluginInfo Id="0"><Name Value="{name}" /></Vst3PluginInfo></PluginDesc></PluginDevice>'


def au(name: str, vendor: str) -> str:
    return (f'<AuPluginDevice><PluginDesc><AuPluginInfo Id="0"><Name Value="{name}" />'
            f'<Manufacturer Value="{vendor}" /></AuPluginInfo></PluginDesc></AuPluginDevice>')


def m4l(ref: str, user_name: str = "") -> str:
    return (f'<MxDeviceAudioEffect Id="3"><UserName Value="{user_name}" />'
            f'<PatchSlot><Value><MxPatchRef Id="2">{ref}</MxPatchRef></Value></PatchSlot></MxDeviceAudioEffect>')


def track(tag: str, name: str, body: str = "", frozen: bool = False, freeze_samples: str = "") -> str:
    return (f'<{tag} Id="1"><Name><EffectiveName Value="{name}" /><UserName Value="" /></Name>'
            f'<Freeze Value="{"true" if frozen else "false"}" />'
            f'<DeviceChain><Devices>{body}</Devices>'
            f'<FreezeSequencer><ClipSlotList>{freeze_samples}</ClipSlotList></FreezeSequencer></DeviceChain></{tag}>')


def live_set(tracks: str, version: str = "12.1.10", tempo: float = 124.0, main_tag: str = "MainTrack") -> str:
    main = (f'<{main_tag}><Name><EffectiveName Value="Main" /></Name><DeviceChain><Mixer><Tempo>'
            f'<Manual Value="{tempo:g}" /></Tempo></Mixer></DeviceChain></{main_tag}>')
    return (f'<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12120" '
            f'Creator="Ableton Live {version}"><LiveSet><Tracks>{tracks}</Tracks>{main}</LiveSet></Ableton>')


def write_set(path: Path, xml: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    return path


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF")
    return path
