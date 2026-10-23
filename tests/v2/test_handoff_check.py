"""Tests for studio_vault.handoff.check (traffic light)."""

from __future__ import annotations

from studio_vault.handoff import als, check
from studio_vault.handoff.pluginlist import Entry, LiveInstall, PluginList
from tests.v2.handoff_fixtures import au, file_ref, live_set, m4l, sample, touch, track, vst, vst3, write_set


def receiver(*plugins, live=(("Ableton Live 12 Suite", "12.1.10", "Suite"),)):
    return PluginList("Laptop", "2026-10-24T10:00:00", [LiveInstall(*i) for i in live], list(plugins))


def make(tmp_path, tracks, version="12.1.10", extra_sets=()):
    proj = tmp_path / "Song Project"
    touch(proj / "Samples" / "Imported" / "kick.wav")
    path = write_set(proj / "Song.als", live_set("".join(tracks), version=version))
    for name in extra_sets:
        write_set(proj / name, live_set(""))
    return als.read(path)


KICK = sample(file_ref(3, "Samples/Imported/kick.wav"))


def keys(report):
    return {f.key: f.level for f in report.findings}


def test_green_when_everything_is_there(tmp_path):
    s = make(tmp_path, [track("AudioTrack", "Drums", vst3("Pro-Q 3") + au("Pro-C 2", "FabFilter") + KICK)])
    r = check.check(s, receiver(Entry("Pro-Q 3", "VST3"), Entry("Pro-C 2", "AU", "FabFilter")))
    assert r.level == check.GREEN and r.can_pack
    assert keys(r) == {"files": "green", "live_version": "green", "plugins": "green"}
    assert r.receiver == "Laptop"


def test_outside_and_missing_files_are_red(tmp_path):
    outside = touch(tmp_path / "Downloads" / "vocal.wav")
    s = make(tmp_path, [track("AudioTrack", "Vox", sample(file_ref(1, "../Downloads/vocal.wav", str(outside)))
                              + sample(file_ref(3, "Samples/Imported/gone.wav")))])
    r = check.check(s)
    assert r.level == check.RED and not r.can_pack
    f = {x.key: x for x in r.findings}
    assert f["outside_files"].items == ["vocal.wav (Downloads)"]
    assert "Collect All and Save" in f["outside_files"].detail
    assert f["missing_files"].items == ["gone.wav (Imported)"]


def test_plugins_missing_other_format_and_freeze_suggestion(tmp_path):
    s = make(tmp_path, [track("MidiTrack", "Bass", vst("Serum_x64")), track("MidiTrack", "Lead", vst3("Diva")),
                        track("AudioTrack", "Bus", au("Pro-C 2", "FabFilter"))])
    r = check.check(s, receiver(Entry("Diva", "AU", "u-he"), Entry("Pro-C 2", "AU", "FabFilter")))
    f = {x.key: x for x in r.findings}
    assert f["plugins_missing"].level == check.RED and f["plugins_missing"].items == ["Serum_x64 (VST) on Bass"]
    assert f["plugins_format"].items == ["Diva (VST3) on Lead: they have AU"]
    assert f["freeze_suggestion"].items == ["Bass: Serum_x64", "Lead: Diva"]
    by = {p["name"]: p["status"] for p in r.plugins}
    assert by == {"Serum_x64": "missing", "Diva": "other_format", "Pro-C 2": "installed"}


def test_au_vendor_must_match(tmp_path):
    s = make(tmp_path, [track("AudioTrack", "A", au("Compressor", "Acme"))])
    r = check.check(s, receiver(Entry("Compressor", "AU", "Other Co")))
    assert r.plugins[0]["status"] == "missing"


def test_frozen_track_with_freeze_files_needs_no_freeze_suggestion(tmp_path):
    proj = tmp_path / "Song Project"
    touch(proj / "Samples" / "Processed" / "Freeze" / "Freeze Bass.wav")
    s = make(tmp_path, [track("MidiTrack", "Bass", vst("Serum_x64"), frozen=True,
                              freeze_samples=sample(file_ref(3, "Samples/Processed/Freeze/Freeze Bass.wav")))])
    r = check.check(s, receiver())
    assert "freeze_suggestion" not in keys(r)
    assert keys(r)["frozen"] == check.GREEN


def test_frozen_without_freeze_files_is_red(tmp_path):
    s = make(tmp_path, [track("MidiTrack", "Bass", vst("Serum_x64"), frozen=True)])
    assert keys(check.check(s))["freeze_files"] == check.RED


def test_live_versions(tmp_path):
    s = make(tmp_path, [], version="12.1.10")
    assert keys(check.check(s, receiver(live=(("Ableton Live 11 Suite", "11.3.25", "Suite"),))))["live_version"] == check.RED
    assert keys(check.check(s, receiver(live=(("Ableton Live 12 Suite", "12.0.5", "Suite"),))))["live_version"] == check.YELLOW
    assert keys(check.check(s, receiver(live=(("Ableton Live 12 Suite", "12.4.6 (2026-09-10)", "Suite"),))))["live_version"] == check.GREEN
    assert keys(check.check(s, receiver(live=())))["live_version"] == check.YELLOW


def test_max_for_live_and_packs(tmp_path):
    s = make(tmp_path, [track("AudioTrack", "FX", m4l(file_ref(3, "Presets/x/Glue.amxd"))
                              + sample(file_ref(5, "Samples/a.wav", "/x/a.wav", pack="Drone Lab"))
                              + sample(file_ref(5, "Devices/b.adv", "/x/b.adv", pack="Core Library")))])
    k = keys(check.check(s, receiver()))
    assert k["max_for_live"] == check.YELLOW and k["packs"] == check.YELLOW and k["core_library"] == check.GREEN
    standard = receiver(live=(("Ableton Live 12 Standard", "12.1.10", "Standard"),))
    assert keys(check.check(s, standard))["max_for_live"] == check.RED


def test_other_sets_and_no_receiver(tmp_path):
    s = make(tmp_path, [track("AudioTrack", "A", vst3("Pro-Q 3"))], extra_sets=("Song v2.als",))
    k = keys(check.check(s))
    assert k["other_sets"] == check.YELLOW
    assert k["plugins"] == check.YELLOW            # no receiver list loaded
    assert check.check(s).level == check.YELLOW and check.check(s).can_pack
