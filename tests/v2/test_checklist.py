"""Tests for studio_vault.checklist."""

from __future__ import annotations

from studio_vault import checklist as cl
from studio_vault.snapshot import SnapApp, SnapHardware, SnapPlugin, Snapshot
from studio_vault.vendors import LICENSE_ILOK, LICENSE_SERIAL


def _snap(id="old", plugins=(), apps=(), hardware=()) -> Snapshot:
    return Snapshot(id=id, name="Old Mac", machine_name="Old Mac", machine_id="",
                    created_at="2026-06-01T10:00:00",
                    plugins=list(plugins), apps=list(apps), hardware=list(hardware))


OLD = _snap(
    plugins=[
        SnapPlugin("Serum", "VST3", "Xfer Records", "1.36", "com.xferrecords.Serum"),
        SnapPlugin("Serum", "AU", "Xfer Records", "1.36"),
        SnapPlugin("Pro-Q 3", "VST3", "FabFilter", "3.2"),
        SnapPlugin("Massive X", "VST3", "Native Instruments GmbH", "1.4"),
        SnapPlugin("Decapitator", "AU", "Soundtoys", "5.4"),
        SnapPlugin("Tiny Synth", "AU", "Indie Dev Inc.", "0.9"),
        SnapPlugin("Mystery", "VST", "", ""),
        SnapPlugin("Year Only", "VST", "2004–2025", ""),
    ],
    apps=[SnapApp("Native Access", "Plugin Manager", "Native Instruments", "3.1"),
          SnapApp("Ableton Live 12 Suite", "DAW", "Ableton", "12.1")],
    hardware=[SnapHardware("BiG SiX", "Solid State Logic", "Audio Interface", "USB"),
              SnapHardware("H90 Pedal", "Eventide", "MIDI Device", "MIDI")],
)


def _group(checklist, key):
    return next(g for g in checklist.groups if g.key == key)


def _item(checklist, name):
    return next(i for i in checklist.all_items() if i.name == name)


def test_empty_new_mac_everything_missing():
    c = cl.build(OLD, _snap(id="new"), manual_done=set())
    assert c.total == 7 + 2 + 2   # 7 plug-in products, 2 apps, 2 hardware
    assert c.done_count == 0
    serum = _item(c, "Serum")
    assert serum.formats == ["VST3", "AU"]
    assert serum.status == cl.STATUS_MISSING


def test_groups_by_vendor_with_install_info():
    c = cl.build(OLD, _snap(id="new"), manual_done=set())
    ni = _group(c, "native_instruments")
    assert [i.name for i in ni.items] == ["Native Access", "Massive X"]   # apps first
    assert ni.manager_app == "Native Access"
    assert ni.manager_installed == ""
    assert "Install Native Access" in ni.next_step
    assert _group(c, "soundtoys").license_system == LICENSE_ILOK
    assert "iLok" in _group(c, "soundtoys").next_step
    assert _group(c, "fabfilter").license_system == LICENSE_SERIAL
    assert _group(c, "fabfilter").download_url.startswith("https://")


def test_unknown_developers_grouped_by_name_and_other_last():
    c = cl.build(OLD, _snap(id="new"), manual_done=set())
    indie = _group(c, "dev:indiedev")
    assert indie.name == "Indie Dev"
    assert c.groups[-1].key == cl.OTHER_GROUP_KEY
    assert [i.name for i in c.groups[-1].items] == ["Mystery", "Year Only"]


def test_auto_ticks_from_current_scan():
    new = _snap(id="new",
                plugins=[SnapPlugin("Serum VST3", "VST3"), SnapPlugin("Pro-Q 3", "VST3"),
                         SnapPlugin("Pro-Q 3", "AU")],
                apps=[SnapApp("Native Access 2", "Plugin Manager"), SnapApp("ableton live 12 suite")],
                hardware=[SnapHardware("Big Six")])
    c = cl.build(OLD, new, manual_done=set())
    serum = _item(c, "Serum")
    assert serum.status == cl.STATUS_PARTIAL
    assert serum.missing_formats == ["AU"]
    assert not serum.done
    assert _item(c, "Pro-Q 3").status == cl.STATUS_INSTALLED
    assert _item(c, "Ableton Live 12 Suite").done
    assert _item(c, "Native Access").status == cl.STATUS_MISSING      # different app name
    assert _group(c, "native_instruments").manager_installed == "Native Access 2"
    assert "Open Native Access 2" in _group(c, "native_instruments").next_step
    assert _item(c, "BiG SiX").done
    assert not _item(c, "H90 Pedal").done


def test_hardware_items_carry_vendor_link():
    c = cl.build(OLD, _snap(id="new"), manual_done=set())
    h90 = _item(c, "H90 Pedal")
    assert h90.vendor == "Eventide"
    assert h90.download_url.startswith("https://")


def test_manual_ticks_persist_per_source():
    c = cl.build(OLD, _snap(id="new"))
    item = _item(c, "Tiny Synth")
    assert cl.set_done(OLD.id, item.id, True) == {item.id}
    assert _item(cl.build(OLD, _snap(id="new")), "Tiny Synth").done
    assert cl.load_state("other-source") == set()
    cl.set_done(OLD.id, item.id, False)
    assert not _item(cl.build(OLD, _snap(id="new")), "Tiny Synth").done


def test_item_ids_are_stable():
    a = {i.id for i in cl.build(OLD, _snap(id="new"), set()).all_items()}
    b = {i.id for i in cl.build(OLD, _snap(id="new2"), set()).all_items()}
    assert a == b
    assert "plugin:serum" in a


def test_group_done_when_all_items_done():
    new = _snap(id="new", plugins=[SnapPlugin("Pro-Q 3", "VST3")])
    g = _group(cl.build(OLD, new, set()), "fabfilter")
    assert g.done
    assert g.next_step == "Done."


def test_corrupt_state_file_is_ignored():
    path = cl._state_path("old")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops")
    assert cl.load_state("old") == set()
    path.write_text('{"done": ["plugin:serum", 5]}')
    assert cl.load_state("old") == {"plugin:serum"}
