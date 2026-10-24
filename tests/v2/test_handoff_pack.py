"""Tests for studio_vault.handoff.pack (zip for the collaborator)."""

from __future__ import annotations

import datetime
import zipfile

import pytest

from studio_vault.handoff import als, check, pack
from studio_vault.handoff.pluginlist import Entry, LiveInstall, PluginList
from tests.v2.handoff_fixtures import file_ref, live_set, sample, touch, track, vst3, write_set

KICK = sample(file_ref(3, "Samples/Imported/kick.wav"))


def receiver(*plugins):
    return PluginList("Laptop", "2026-10-24T10:00:00", [LiveInstall("Ableton Live 12 Suite", "12.1.10", "Suite")],
                      list(plugins))


def project(tmp_path, name="Track_v07_AB", tracks=None, extra_sets=()):
    proj = tmp_path / "Track Project"
    touch(proj / "Samples" / "Imported" / "kick.wav")
    touch(proj / "Samples" / "Imported" / "kick.wav.asd")
    touch(proj / "Backup" / "Track [2026-10-20 101010].als")
    touch(proj / ".DS_Store")
    touch(proj / "Samples" / "._kick.wav")
    touch(proj / "Ableton Project Info" / "Project8_1.cfg")
    tracks = tracks if tracks is not None else [track("AudioTrack", "Drums", vst3("Pro-Q 3") + KICK)]
    path = write_set(proj / f"{name}.als", live_set("".join(tracks)))
    for other in extra_sets:
        write_set(proj / other, live_set(""))
    return als.read(path)


def names(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return sorted(zf.namelist())


# ── version names ─────────────────────────────────────────────────────────────

def test_initials():
    assert pack.initials_from_name("Andreas Bakketeig") == "AB"
    assert pack.initials_from_name("jean-luc picard") == "JLP"
    assert pack.initials_from_name("") == ""


@pytest.mark.parametrize("name, expected", [
    ("Track_v07_AB", ("Track", 7)),
    ("Track v3", ("Track", 3)),
    ("My Song-v12", ("My Song", 12)),
    ("Track", ("Track", None)),
    ("v2", ("v2", None)),
])
def test_split_version(name, expected):
    assert pack.split_version(name) == expected


def test_suggest_next_version_after_all_in_folder(tmp_path):
    s = project(tmp_path, extra_sets=["Track_v09_KL.als", "Other_v20.als"])
    assert pack.suggest_version_name(s, "AB") == "Track_v10_AB"
    assert pack.suggest_version_name(s, "") == "Track_v10"


def test_suggest_for_unversioned_set(tmp_path):
    s = project(tmp_path, name="Song")
    assert pack.suggest_version_name(s, "AB") == "Song_v01_AB"


def test_clean_version_name():
    assert pack.clean_version_name("  a/b:c  ") == "a-b-c"
    with pytest.raises(pack.PackError):
        pack.clean_version_name(" .. ")


# ── packing ───────────────────────────────────────────────────────────────────

def test_pack_contents_and_cleanup(tmp_path):
    s = project(tmp_path, extra_sets=["Track_v06_AB.als"])
    r = check.check(s, receiver(Entry("Pro-Q 3", "VST3")))
    assert r.level != check.RED
    out = pack.pack(s, r, tmp_path / "out" / "Track_v08_AB", "Track_v08_AB", "New chorus and mix")
    assert out.zip_path.endswith("Track_v08_AB.zip")
    assert names(out.zip_path) == [
        "Track_v08_AB Project/Ableton Project Info/Project8_1.cfg",
        "Track_v08_AB Project/HANDOFF.txt",
        "Track_v08_AB Project/Samples/Imported/kick.wav",
        "Track_v08_AB Project/Track_v08_AB.als",
    ]
    # Nothing in the project folder was touched.
    proj = tmp_path / "Track Project"
    assert (proj / "Backup").is_dir() and (proj / ".DS_Store").exists()
    assert (proj / "Samples" / "Imported" / "kick.wav.asd").exists()
    assert (proj / "Track_v07_AB.als").exists() and not (proj / "Track_v08_AB.als").exists()
    # The packed set is the real set, readable by the reader.
    with zipfile.ZipFile(out.zip_path) as zf:
        zf.extractall(tmp_path / "unzipped")
    packed = als.read(tmp_path / "unzipped" / "Track_v08_AB Project" / "Track_v08_AB.als")
    assert [p.name for p in packed.plugins] == ["Pro-Q 3"]
    assert not list((tmp_path / "out").glob("*.part"))


def test_handoff_txt(tmp_path):
    s = project(tmp_path, tracks=[track("AudioTrack", "Drums", vst3("Pro-Q 3") + KICK),
                                  track("MidiTrack", "Bass", vst3("Serum"), frozen=True)])
    r = check.check(s, receiver(Entry("Pro-Q 3", "VST3")))
    text = pack.handoff_text(s, r, "Track_v08_AB", "  New chorus  ", "AB",
                             now=datetime.datetime(2026, 10, 24, 12, 0))
    assert "HANDOFF — Track_v08_AB" in text
    assert "Date:           2026-10-24 12:00" in text
    assert "Checked for:    Laptop" in text
    assert "Tempo:          124 BPM" in text
    assert "Live version:   12.1.10" in text
    assert "WHAT CHANGED\n------------\nNew chorus\n" in text
    assert "- Pro-Q 3 (VST3) — Drums" in text
    assert "- Serum (VST3) — Bass  [receiver does not have it]" in text
    assert "FROZEN TRACKS\n-------------\n- Bass" in text
    assert "Kontakt" in text


def test_red_is_refused(tmp_path):
    s = project(tmp_path, tracks=[track("AudioTrack", "Vox", sample(file_ref(1, "", "/nowhere/vocal.wav")))])
    r = check.check(s, receiver())
    assert r.level == check.RED
    with pytest.raises(pack.PackError, match="red"):
        pack.pack(s, r, tmp_path / "x.zip", "Track_v08_AB", "note")
    assert not (tmp_path / "x.zip").exists()


def test_note_is_required(tmp_path):
    s = project(tmp_path)
    r = check.check(s, receiver(Entry("Pro-Q 3", "VST3")))
    with pytest.raises(pack.PackError, match="What did you change"):
        pack.pack(s, r, tmp_path / "x.zip", "Track_v08_AB", "   ")


def test_zip_inside_project_is_refused(tmp_path):
    s = project(tmp_path)
    r = check.check(s, receiver(Entry("Pro-Q 3", "VST3")))
    with pytest.raises(pack.PackError, match="outside"):
        pack.pack(s, r, s.project_dir / "Samples" / "x.zip", "Track_v08_AB", "note")


def test_cancel_removes_partial_zip(tmp_path):
    s = project(tmp_path)
    r = check.check(s, receiver(Entry("Pro-Q 3", "VST3")))
    with pytest.raises(pack.PackError, match="cancelled"):
        pack.pack(s, r, tmp_path / "x.zip", "Track_v08_AB", "note", cancelled=lambda: True)
    assert not list(tmp_path.glob("x.zip*"))


def test_progress_reaches_total(tmp_path):
    s = project(tmp_path)
    r = check.check(s, receiver(Entry("Pro-Q 3", "VST3")))
    seen = []
    res = pack.pack(s, r, tmp_path / "x.zip", "Track_v08_AB", "note", progress=lambda d, t: seen.append((d, t)))
    assert seen[-1][0] == seen[-1][1] == res.bytes
