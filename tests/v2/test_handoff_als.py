"""Tests for studio_vault.handoff.als (Live Set reader)."""

from __future__ import annotations

import gzip

import pytest

from studio_vault.handoff import als
from tests.v2.handoff_fixtures import (au, file_ref, live_set, m4l, sample, touch, track, vst, vst3,
                                       write_set)


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "Song Project"
    touch(proj / "Samples" / "Imported" / "kick.wav")
    touch(proj / "Samples" / "Processed" / "Freeze" / "Freeze Bass.wav")
    touch(proj / "Presets" / "Audio Effects" / "Max Audio Effect" / "Imported" / "Glue.amxd")
    outside = touch(tmp_path / "Elsewhere" / "vocal.wav")
    tracks = (
        track("AudioTrack", "Drums", vst3("Pro-Q 3") + au("Pro-C 2", "FabFilter")
              + sample(file_ref(3, "Samples/Imported/kick.wav", str(proj / "Samples/Imported/kick.wav")))
              + sample(file_ref(3, "Samples/Imported/gone.wav", str(proj / "Samples/Imported/gone.wav")))),
        track("AudioTrack", "Vocal", sample(file_ref(1, "../Elsewhere/vocal.wav", str(outside)))
              + sample(file_ref(6, "Samples/My/riser.wav", "/Users/someone/Music/Ableton/User Library/Samples/My/riser.wav"))),
        track("MidiTrack", "Bass", vst("Serum_x64"), frozen=True,
              freeze_samples=sample(file_ref(3, "Samples/Processed/Freeze/Freeze Bass.wav", ""))),
        track("MidiTrack", "Lead", vst("Serum_x64") + m4l(file_ref(3, "Presets/Audio Effects/Max Audio Effect/Imported/Glue.amxd", ""))
              + m4l(file_ref(1, "../../Max/LFO.amxd", "/Users/someone/Max/LFO.amxd"), user_name="My LFO"), frozen=True),
        track("MidiTrack", "Pads", sample(file_ref(5, "Samples/Pads/warm.wav", "/x/Packs/Drone Lab/warm.wav", pack="Drone Lab"))
              + sample(file_ref(5, "Devices/Compressor.adv", "/Applications/Live.app/Core Library/x", pack="Core Library"))
              + sample(file_ref(7, "Samples/Hybrid/IR.wav", "/Applications/Live.app/Builtin/IR.wav"))
              + sample(file_ref(0))),
        track("ReturnTrack", "A-Reverb", vst3("ValhallaVintageVerb")),
    )
    path = write_set(proj / "Song.als", live_set("".join(tracks)))
    write_set(proj / "Song v2.als", live_set(""))
    write_set(proj / "Backup" / "Song [2026-01-01].als", live_set(""))
    return path


def test_header_tempo_and_tracks(project):
    s = als.read(project)
    assert s.name == "Song"
    assert s.live_version == "12.1.10"
    assert s.tempo == 124.0
    assert [(t.name, t.kind) for t in s.tracks] == [
        ("Drums", "audio"), ("Vocal", "audio"), ("Bass", "midi"), ("Lead", "midi"), ("Pads", "midi"),
        ("A-Reverb", "return"), ("Main", "main")]


def test_plugins_per_track_and_unique(project):
    s = als.read(project)
    assert [(p.name, p.fmt, p.vendor) for p in s.plugins] == [
        ("Pro-C 2", "AU", "FabFilter"), ("Pro-Q 3", "VST3", ""), ("Serum_x64", "VST", ""), ("ValhallaVintageVerb", "VST3", "")]
    serum = next(p for p in s.plugins if p.name == "Serum_x64")
    assert s.tracks_using(serum) == ["Bass", "Lead"]


def test_file_locations_and_existence(project):
    files = {f.name: f for f in als.read(project).files}
    assert (files["kick.wav"].location, files["kick.wav"].exists) == ("project", True)
    assert (files["gone.wav"].location, files["gone.wav"].exists) == ("project", False)
    assert (files["vocal.wav"].location, files["vocal.wav"].exists) == ("external", True)
    assert (files["riser.wav"].location, files["riser.wav"].exists) == ("user_library", False)
    assert (files["warm.wav"].location, files["warm.wav"].pack) == ("pack", "Drone Lab")
    assert files["Compressor.adv"].pack == "Core Library"
    assert files["IR.wav"].location == "builtin"
    assert len(files) == 10         # RelativePathType 0 is no file


def test_max_for_live_devices(project):
    lead = next(t for t in als.read(project).tracks if t.name == "Lead")
    assert lead.max_devices == ["Glue", "My LFO"]
    m4l_files = {f.name: f for f in lead.files if f.kind == "max_device"}
    assert m4l_files["Glue.amxd"].exists is True
    assert m4l_files["LFO.amxd"].location == "external"


def test_frozen_tracks_and_freeze_files(project):
    tracks = {t.name: t for t in als.read(project).tracks}
    assert tracks["Bass"].frozen and [f.name for f in tracks["Bass"].freeze_files] == ["Freeze Bass.wav"]
    assert tracks["Bass"].freeze_files[0].exists
    assert tracks["Lead"].frozen and tracks["Lead"].freeze_files == []
    assert not tracks["Drums"].frozen


def test_other_sets_in_folder(project):
    assert als.other_sets(als.read(project)) == ["Song v2.als"]


def test_live_11_master_track_tempo(tmp_path):
    path = write_set(tmp_path / "Old.als", live_set("", version="11.3.25", tempo=98.5, main_tag="MasterTrack"))
    s = als.read(path)
    assert (s.live_version, s.tempo) == ("11.3.25", 98.5)


def test_live_10_relative_path_elements(tmp_path):
    proj = tmp_path / "P"
    touch(proj / "Samples" / "Recorded" / "take.wav")
    ref = ('<FileRef><HasRelativePath Value="true" /><RelativePathType Value="" /><RelativePath>'
           '<RelativePathElement Dir="Samples" /><RelativePathElement Dir="Recorded" /></RelativePath>'
           '<Name Value="take.wav" /></FileRef>').replace('<RelativePathType Value="" />', "")
    path = write_set(proj / "Ten.als", live_set(track("AudioTrack", "Gtr", sample(ref)), version="10.1.30"))
    [f] = als.read(path).files
    assert (f.name, f.location, f.exists) == ("take.wav", "project", True)


@pytest.mark.parametrize("content,message", [
    (b"", "empty"), (b"\xab\x1e old binary", "Live 7"), (gzip.compress(b"<x"), "damaged"),
    (gzip.compress(b"<Other/>"), "Not an Ableton"), (gzip.compress(b"<Ableton/>"), "Not an Ableton"),
])
def test_errors(tmp_path, content, message):
    path = tmp_path / "bad.als"
    path.write_bytes(content)
    with pytest.raises(als.AlsError, match=message):
        als.read(path)


def test_version_tuple():
    assert als.version_tuple("12.1.10") == (12, 1, 10)
    assert als.version_tuple("11.3.25 Beta") == (11, 3, 25)
    assert als.version_tuple("") == ()


def test_reader_never_writes(project):
    before = project.read_bytes()
    stat = project.stat()
    als.read(project)
    assert project.read_bytes() == before and project.stat().st_mtime_ns == stat.st_mtime_ns


def test_track_count_leaves_out_main(tmp_path):
    from tests.v2.handoff_fixtures import live_set, track, write_set
    path = write_set(tmp_path / "P" / "Song.als", live_set(track("AudioTrack", "A") + track("MidiTrack", "B")))
    s = als.read(path)
    assert len(s.tracks) == 3 and s.track_count == 2
