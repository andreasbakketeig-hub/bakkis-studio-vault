"""Tests for studio_vault.compare."""

from __future__ import annotations

import pytest

from studio_vault.compare import (
    ADDED,
    CAT_APPS,
    CAT_HARDWARE,
    CAT_PLUGINS,
    REMOVED,
    UPDATED,
    compare,
    compare_versions,
)
from studio_vault.snapshot import SnapApp, SnapHardware, SnapPlugin, Snapshot


def _snap(plugins=(), apps=(), hardware=()) -> Snapshot:
    return Snapshot(id="x", name="n", machine_name="m", machine_id="", created_at="2026-01-01T00:00:00",
                    plugins=list(plugins), apps=list(apps), hardware=list(hardware))


@pytest.mark.parametrize("a,b,expected", [
    ("1.2.9", "1.2.10", 1),
    ("2.0", "1.9.9", -1),
    ("1.0", "1.0.0", 0),
    ("v3.1", "3.2", 1),
    ("2.0 beta", "2.0", 0),
    ("", "1.0", 0),
    ("abc", "1.0", 0),
])
def test_compare_versions(a, b, expected):
    assert compare_versions(a, b) == expected


def test_identical_snapshots_have_no_changes():
    s = _snap([SnapPlugin("Serum", "VST3", version="1.3")], [SnapApp("Logic Pro", version="11")],
              [SnapHardware("BiG SiX")])
    result = compare(s, s)
    assert result.is_empty


def test_plugins_added_removed_updated():
    old = _snap([SnapPlugin("Serum", "VST3", "Xfer", "1.35"),
                 SnapPlugin("Diva", "AU", "u-he", "1.4"),
                 SnapPlugin("Old Verb", "VST", "Acme", "1.0")])
    new = _snap([SnapPlugin("Serum VST3", "VST3", "Xfer", "1.36"),
                 SnapPlugin("Diva", "AU", "u-he", "1.4"),
                 SnapPlugin("Serum", "CLAP", "Xfer", "2.0")])
    r = compare(old, new)
    assert [(c.name, c.fmt) for c in r.of(CAT_PLUGINS, ADDED)] == [("Serum", "CLAP")]
    assert [(c.name, c.fmt) for c in r.of(CAT_PLUGINS, REMOVED)] == [("Old Verb", "VST")]
    [upd] = r.of(CAT_PLUGINS, UPDATED)
    assert (upd.name, upd.old_version, upd.new_version, upd.direction) == ("Serum VST3", "1.35", "1.36", 1)


def test_missing_version_is_not_an_update():
    old = _snap([SnapPlugin("Serum", "VST3", version="")])
    new = _snap([SnapPlugin("Serum", "VST3", version="1.36")])
    assert compare(old, new).is_empty


def test_apps_and_hardware():
    old = _snap(apps=[SnapApp("Logic Pro", version="10.8"), SnapApp("iLok License Manager", version="5")],
                hardware=[SnapHardware("BiG SiX", "SSL"), SnapHardware("Scarlett 2i2", "Focusrite")])
    new = _snap(apps=[SnapApp("logic pro", version="11.0"), SnapApp("Native Access", version="3")],
                hardware=[SnapHardware("Big Six", "SSL"), SnapHardware("H90 Pedal", "Eventide")])
    r = compare(old, new)
    assert [c.name for c in r.of(CAT_APPS, UPDATED)] == ["logic pro"]
    assert [c.name for c in r.of(CAT_APPS, ADDED)] == ["Native Access"]
    assert [c.name for c in r.of(CAT_APPS, REMOVED)] == ["iLok License Manager"]
    assert [c.name for c in r.of(CAT_HARDWARE, ADDED)] == ["H90 Pedal"]
    assert [c.name for c in r.of(CAT_HARDWARE, REMOVED)] == ["Scarlett 2i2"]


def test_counts():
    old = _snap([SnapPlugin("A", "AU")])
    new = _snap([SnapPlugin("B", "AU")], hardware=[SnapHardware("X")])
    counts = compare(old, new).counts()
    assert counts[CAT_PLUGINS] == {ADDED: 1, REMOVED: 1, UPDATED: 0}
    assert counts[CAT_HARDWARE][ADDED] == 1
    assert counts[CAT_APPS] == {ADDED: 0, REMOVED: 0, UPDATED: 0}
