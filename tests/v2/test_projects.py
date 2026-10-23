"""Tests for studio_vault.projects (Ableton Live project check), with generated .als files."""

from __future__ import annotations

import gzip
from pathlib import Path

from studio_vault import projects
from studio_vault.snapshot import SnapPlugin, Snapshot

ALS = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12049" Creator="Ableton Live 12.1.5">
  <LiveSet><Tracks><AudioTrack Id="1"><Name><EffectiveName Value="Mix" /></Name><DeviceChain><Devices>
    <PluginDevice><PluginDesc><VstPluginInfo Id="0">
      <Path Value="/Library/Audio/Plug-Ins/VST/Serum_x64.vst"/><PlugName Value="Serum_x64"/>
      <Preset><VstPreset Id="1"><Name Value="not a plug-in"/></VstPreset></Preset>
    </VstPluginInfo></PluginDesc></PluginDevice>
    <PluginDevice><PluginDesc><Vst3PluginInfo Id="0"><Name Value="Diva"/></Vst3PluginInfo></PluginDesc></PluginDevice>
    <PluginDevice><PluginDesc><AuPluginInfo Id="0"><Name Value="Pro-C 2"/><Manufacturer Value="FabFilter"/></AuPluginInfo></PluginDesc></PluginDevice>
    <PluginDevice><PluginDesc><AuPluginInfo Id="0"><Name Value="FF Pro-L 2"/><Manufacturer Value="FabFilter"/></AuPluginInfo></PluginDesc></PluginDevice>
    <PluginDevice><PluginDesc><AuPluginInfo Id="0"><Name Value="SPAN"/><Manufacturer Value="Voxengo"/></AuPluginInfo></PluginDesc></PluginDevice>
    <PluginDevice><PluginDesc><Vst3PluginInfo Id="0"><Name Value="Sylenth1"/></Vst3PluginInfo></PluginDesc></PluginDevice>
    <PluginDevice><PluginDesc><Vst3PluginInfo Id="0"><Name Value="Diva"/></Vst3PluginInfo></PluginDesc></PluginDevice>
  </Devices></DeviceChain></AudioTrack></Tracks></LiveSet>
</Ableton>"""


def write_als(path: Path, xml: str = ALS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(xml.encode("utf-8"))
    return path


def mac(*plugins) -> Snapshot:
    return Snapshot(id="m", name="Studio", machine_name="Studio", machine_id="", created_at="",
                    plugins=list(plugins))


STUDIO = mac(SnapPlugin("Serum", "VST", "Xfer Records"), SnapPlugin("Diva", "AU", "u-he"),
             SnapPlugin("FabFilter Pro-C 2", "AU", "FabFilter"), SnapPlugin("FabFilter Pro-L 2", "AU", "FabFilter"),
             SnapPlugin("Voxengo SPAN", "AU", "Voxengo"))


def test_parse(tmp_path):
    p = projects.parse_als(write_als(tmp_path / "Track.als"))
    assert p.error == ""
    assert p.name == "Track"
    assert p.live_version == "12.1.5"
    assert [(x.name, x.fmt) for x in p.plugins] == [
        ("Diva", "VST3"), ("FF Pro-L 2", "AU"), ("Pro-C 2", "AU"), ("Serum_x64", "VST"), ("SPAN", "AU"), ("Sylenth1", "VST3")]


def test_check_statuses(tmp_path):
    c = projects.check(projects.parse_als(write_als(tmp_path / "T.als")), STUDIO)
    st = {p.name: p.status for p in c.plugins}
    assert st == {"Serum_x64": "installed", "Pro-C 2": "installed", "FF Pro-L 2": "installed", "SPAN": "installed",
                  "Diva": "other_format", "Sylenth1": "missing"}
    assert c.missing == 2
    assert c.plugins[0].status == "missing"                     # worst first
    diva = next(p for p in c.plugins if p.name == "Diva")
    assert diva.have_formats == ["AU"]


def test_unreadable_files(tmp_path):
    (tmp_path / "empty.als").write_bytes(b"")
    (tmp_path / "old.als").write_bytes(b"\xab\x1e\x00\x00 old Live binary")
    (tmp_path / "bad.als").write_bytes(gzip.compress(b"<not xml"))
    (tmp_path / "other.als").write_bytes(gzip.compress(b"<Something/>"))
    assert projects.parse_als(tmp_path / "empty.als").error == "The file is empty."
    assert "Live 7" in projects.parse_als(tmp_path / "old.als").error
    assert "damaged" in projects.parse_als(tmp_path / "bad.als").error
    assert projects.parse_als(tmp_path / "other.als").error == "Not an Ableton Live Set."


def test_find_projects_skips_backups(tmp_path):
    write_als(tmp_path / "A Project" / "Song.als")
    write_als(tmp_path / "A Project" / "Backup" / "Song [2026-01-01].als")
    write_als(tmp_path / ".hidden" / "x.als")
    (tmp_path / "A Project" / "._Song.als").write_bytes(b"")
    assert [p.name for p in projects.find_projects(tmp_path)] == ["Song.als"]


def test_missing_summary_counts_projects(tmp_path):
    a = projects.parse_als(write_als(tmp_path / "a.als"))
    b = projects.parse_als(write_als(tmp_path / "b.als", ALS.replace("Sylenth1", "Massive")))
    rows = projects.missing_summary(projects.check_all([a, b], STUDIO))
    by = {(r["name"], r["fmt"]): r["projects"] for r in rows}
    assert by[("Diva", "VST3")] == 2
    assert by[("Sylenth1", "VST3")] == 1 and by[("Massive", "VST3")] == 1


def test_live_names_from_the_scan_are_used(tmp_path):
    xml = ALS.replace('<Name Value="Diva"/>', '<Name Value="Serum 2"/>')
    p = projects.parse_als(write_als(tmp_path / "S.als", xml))
    mac_with_names = mac(SnapPlugin("Serum2", "VST3", "Xfer Records", live_names=("Serum 2",)),
                         SnapPlugin("WaveShell1-AU 15", "AU", "Waves Audio", live_names=("Waves: H-Delay Stereo",)))
    st = {x.name: x.status for x in projects.check(p, mac_with_names).plugins}
    assert st["Serum 2"] == "installed"
    au = projects.parse_als(write_als(tmp_path / "W.als", ALS.replace('<Name Value="Pro-C 2"/><Manufacturer Value="FabFilter"/>',
                                                                       '<Name Value="H-Delay Stereo"/><Manufacturer Value="Waves"/>')))
    st = {x.name: x.status for x in projects.check(au, mac_with_names).plugins}
    assert st["H-Delay Stereo"] == "installed"


def test_generic_short_names_are_not_matched_by_suffix(tmp_path):
    p = projects.parse_als(write_als(tmp_path / "V.als", ALS.replace('<Name Value="Sylenth1"/>', '<Name Value="Verb"/>')))
    st = {x.name: x.status for x in projects.check(p, mac(SnapPlugin("ValhallaVintageVerb", "VST3"))).plugins}
    assert st["Verb"] == "missing"
