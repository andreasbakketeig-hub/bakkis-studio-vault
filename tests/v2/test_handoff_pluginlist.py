"""Tests for studio_vault.handoff.pluginlist (receiver's plug-in export)."""

from __future__ import annotations

import json
import plistlib

import pytest

from studio_vault.handoff import pluginlist


def bundle(path, plist=None, moduleinfo=None):
    (path / "Contents" / "Resources").mkdir(parents=True)
    with (path / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist or {}, fh)
    if moduleinfo is not None:
        (path / "Contents" / "Resources" / "moduleinfo.json").write_text(moduleinfo)
    return path


@pytest.fixture
def studio(tmp_path):
    plugs, apps = tmp_path / "Plug-Ins", tmp_path / "Applications"
    bundle(plugs / "Components" / "FabFilter Pro-C 2.component",
           {"CFBundleShortVersionString": "2.30", "AudioComponents": [{"name": "FabFilter: Pro-C 2", "type": "aufx"}]})
    bundle(plugs / "Components" / "WaveShell1-AU 15.0.component",
           {"AudioComponents": [{"name": "Waves: H-Delay Stereo"}, {"name": "Waves: CLA-2A Mono"}]})
    bundle(plugs / "VST3" / "Vendor Folder" / "Serum2.vst3", {"CFBundleShortVersionString": "2.0.3"},
           '{"Classes": [{"Category": "Audio Module Class", "Name": "Serum 2",}, '
           '{"Category": "Component Controller Class", "Name": "Serum 2 Controller",},],}')
    bundle(plugs / "VST3" / "Diva.vst3", {"CFBundleShortVersionString": "1.4.8"})
    bundle(plugs / "VST" / "Sylenth1.vst", {"CFBundleShortVersionString": "3.0"})
    bundle(plugs / "AAX" / "Pro-Q 3.aaxplugin")
    bundle(apps / "Ableton Live 12 Suite.app", {"CFBundleShortVersionString": "12.1.10"})
    bundle(apps / "Ableton Live 11 Standard.app", {"CFBundleShortVersionString": "11.3.25"})
    return pluginlist.scan(plugin_dirs=(str(plugs / "Components"), str(plugs / "VST3"), str(plugs / "VST"), str(plugs / "AAX")),
                           app_dirs=(str(apps),), name="Laptop")


def test_scan_uses_the_names_live_stores(studio):
    got = {(e.name, e.fmt, e.vendor) for e in studio.plugins}
    assert got == {("Pro-C 2", "AU", "FabFilter"), ("H-Delay Stereo", "AU", "Waves"), ("CLA-2A Mono", "AU", "Waves"),
                   ("Serum 2", "VST3", ""), ("Diva", "VST3", ""), ("Sylenth1", "VST", "")}   # no AAX: Live can't use it
    assert next(e for e in studio.plugins if e.name == "Pro-C 2").version == "2.30"


def test_live_installs(studio):
    assert {(i.name, i.version, i.edition) for i in studio.live} == {
        ("Ableton Live 12 Suite", "12.1.10", "Suite"), ("Ableton Live 11 Standard", "11.3.25", "Standard")}
    assert studio.newest_live().version == "12.1.10"
    assert studio.has_max_for_live


def test_save_load_round_trip_without_paths(studio, tmp_path):
    out = pluginlist.save(studio, tmp_path / "out" / "Laptop plug-ins")
    assert out.name == "Laptop plug-ins.handoffplugins"
    text = out.read_text()
    assert "/Users/" not in text and str(tmp_path) not in text
    again = pluginlist.load(out)
    assert again.plugins == studio.plugins and again.live == studio.live and again.machine_name == "Laptop"


@pytest.mark.parametrize("content,message", [
    ("not json", "Could not read"), ('{"format": "x"}', "Not a plug-in list"),
    ('{"format": "handoff-plugin-list", "version": 99}', "newer version"),
])
def test_load_errors(tmp_path, content, message):
    path = tmp_path / "x.handoffplugins"
    path.write_text(content)
    with pytest.raises(pluginlist.PluginListError, match=message):
        pluginlist.load(path)


def test_load_skips_bad_entries(tmp_path):
    path = tmp_path / "x.handoffplugins"
    path.write_text(json.dumps({"format": "handoff-plugin-list", "version": 1, "machine_name": "M",
                                "plugins": [{"name": "A", "fmt": "AU"}, {"name": 5}, "junk"], "live": "nope"}))
    pl = pluginlist.load(path)
    assert [p.name for p in pl.plugins] == ["A"] and pl.live == [] and not pl.has_max_for_live
