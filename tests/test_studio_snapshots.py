"""
Tests for app/core/studio_snapshots.py

Run with:
    python -m pytest tests/test_studio_snapshots.py -v

Testing two exported snapshot files manually
--------------------------------------------
1.  On Machine A, export a snapshot via the UI (or call the helper below in a REPL):

        from app.core.studio_snapshots import export_snapshot, save_snapshot
        from app.core.scanner import scan_plugins
        from app.core.music_software_scanner import scan_music_apps

        plugins  = scan_plugins()
        apps     = scan_music_apps()
        snap_a   = export_snapshot(plugins, apps, machine_name="Machine A")
        path_a   = save_snapshot(snap_a)          # writes to SNAPSHOTS_DIR
        print("Saved to", path_a)

2.  Copy the resulting JSON to Machine B, export Machine B's snapshot, and run:

        from app.core.studio_snapshots import load_snapshot, compare_snapshots

        snap_a = load_snapshot("/path/to/snapshot_Machine_A_....json")
        snap_b = load_snapshot("/path/to/snapshot_Machine_B_....json")
        cmp    = compare_snapshots(snap_b, snap_a)   # local=B, other=A
        print("Missing locally:", [d.name for d in cmp.plugins_missing_locally])
        print("Missing on other:", [d.name for d in cmp.plugins_missing_on_other])
        print("Version diffs:", [(d.name, d.local_version, d.other_version)
                                  for d in cmp.plugin_version_diffs])
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.core.studio_snapshots import (
    SnapshotComparison,
    SnapshotHardware,
    SnapshotPlugin,
    SnapshotSoftware,
    SnapshotSummary,
    StudioSnapshot,
    _plugin_key,
    compare_snapshots,
    load_snapshot,
    save_snapshot,
)

# ── Fixture helpers ───────────────────────────────────────────────────────────

def _make_plugin(
    name: str = "Serum",
    developer: str = "Xfer Records",
    version: str = "1.35",
    fmt: str = "VST3",
    path: str = "/Library/Audio/Plug-Ins/VST3/Serum.vst3",
    size: int = 0,
    modified: str = "2025-01-01",
) -> SnapshotPlugin:
    return SnapshotPlugin(
        name=name, developer=developer, version=version,
        fmt=fmt, path=path, size=size, modified=modified,
    )


def _make_software(
    name: str = "Logic Pro",
    version: str = "11.0",
    category: str = "DAW",
    path: str = "/Applications/Logic Pro.app",
) -> SnapshotSoftware:
    return SnapshotSoftware(name=name, version=version, category=category, path=path)


def _make_hardware(
    name: str = "Focusrite Scarlett 2i2",
    vendor: str = "Focusrite",
    device_type: str = "Audio Interface",
    connection_type: str = "USB",
) -> SnapshotHardware:
    return SnapshotHardware(
        name=name, vendor=vendor, device_type=device_type, connection_type=connection_type,
    )


def _make_snapshot(
    machine_name: str = "Test Machine",
    plugins: list[SnapshotPlugin] | None = None,
    software: list[SnapshotSoftware] | None = None,
    hardware: list[SnapshotHardware] | None = None,
) -> StudioSnapshot:
    plugins  = plugins  or []
    software = software or []
    hardware = hardware or []
    fmt_counts: dict[str, int] = {}
    for p in plugins:
        fmt_counts[p.fmt] = fmt_counts.get(p.fmt, 0) + 1
    return StudioSnapshot(
        schema_version=1,
        machine_name=machine_name,
        machine_id="test-uuid",
        scan_date="2026-06-05T10:00:00",
        app_version="1.0.0",
        plugins=plugins,
        music_software=software,
        hardware=hardware,
        summary=SnapshotSummary(
            total_plugins=len(plugins),
            total_software=len(software),
            total_hardware=len(hardware),
            plugin_formats=fmt_counts,
        ),
    )


# ── _plugin_key normalisation ─────────────────────────────────────────────────

class TestPluginKey:
    def test_strips_vst3_suffix(self):
        assert _plugin_key("Serum VST3") == _plugin_key("Serum")

    def test_strips_vst_suffix(self):
        assert _plugin_key("Serum VST") == _plugin_key("Serum")

    def test_strips_au_suffix(self):
        assert _plugin_key("Serum AU") == _plugin_key("Serum")

    def test_strips_aax_suffix(self):
        assert _plugin_key("Serum AAX") == _plugin_key("Serum")

    def test_case_insensitive(self):
        assert _plugin_key("Serum") == _plugin_key("SERUM")

    def test_empty_string(self):
        result = _plugin_key("")
        assert isinstance(result, str)


# ── Serialisation round-trips ─────────────────────────────────────────────────

class TestSerialization:
    def test_plugin_round_trip(self):
        p = _make_plugin()
        assert SnapshotPlugin.from_dict(p.to_dict()) == p

    def test_software_round_trip(self):
        s = _make_software()
        assert SnapshotSoftware.from_dict(s.to_dict()) == s

    def test_hardware_round_trip(self):
        h = _make_hardware()
        assert SnapshotHardware.from_dict(h.to_dict()) == h

    def test_snapshot_round_trip(self):
        snap = _make_snapshot(
            plugins=[_make_plugin()],
            software=[_make_software()],
            hardware=[_make_hardware()],
        )
        restored = StudioSnapshot.from_dict(snap.to_dict())
        assert restored.machine_name == snap.machine_name
        assert len(restored.plugins) == 1
        assert restored.plugins[0].name == "Serum"
        assert len(restored.music_software) == 1
        assert len(restored.hardware) == 1

    def test_snapshot_missing_fields_graceful(self):
        snap = StudioSnapshot.from_dict({})
        assert snap.machine_name == ""
        assert snap.plugins == []
        assert snap.hardware == []


# ── save_snapshot / load_snapshot ─────────────────────────────────────────────

class TestIO:
    def test_save_and_load(self, tmp_path: Path):
        snap = _make_snapshot(plugins=[_make_plugin(name="Vital")])
        saved = save_snapshot(snap, dest=tmp_path / "snapshot_test.json")
        assert saved.exists()

        loaded = load_snapshot(saved)
        assert loaded.machine_name == snap.machine_name
        assert loaded.plugins[0].name == "Vital"

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        snap = _make_snapshot()
        dest = tmp_path / "deep" / "nested" / "snap.json"
        saved = save_snapshot(snap, dest=dest)
        assert saved.exists()

    def test_saved_file_is_valid_json(self, tmp_path: Path):
        snap = _make_snapshot(plugins=[_make_plugin()])
        path = save_snapshot(snap, dest=tmp_path / "snap.json")
        data = json.loads(path.read_text())
        assert data["schema_version"] == 1
        assert "plugins" in data
        assert "music_software" in data
        assert "hardware" in data
        assert "summary" in data

    def test_load_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(Exception):
            load_snapshot(tmp_path / "nonexistent.json")

    def test_auto_filename_in_folder(self, tmp_path: Path):
        snap = _make_snapshot(machine_name="Studio Mac")
        path = save_snapshot(snap, dest=tmp_path)
        assert path.parent == tmp_path
        assert path.suffix == ".json"
        assert "Studio_Mac" in path.name or "snapshot_" in path.name


# ── compare_snapshots ─────────────────────────────────────────────────────────

class TestCompareSnapshots:

    def test_identical_snapshots_no_diffs(self):
        plugins  = [_make_plugin("Serum"), _make_plugin("Vital", fmt="AU")]
        software = [_make_software("Logic Pro")]
        hardware = [_make_hardware()]

        local = _make_snapshot(plugins=plugins, software=software, hardware=hardware)
        other = _make_snapshot(plugins=plugins, software=software, hardware=hardware)
        cmp = compare_snapshots(local, other)

        assert not cmp.has_differences
        assert cmp.total_differences == 0

    def test_plugin_missing_locally(self):
        local = _make_snapshot(plugins=[_make_plugin("Serum")])
        other = _make_snapshot(plugins=[
            _make_plugin("Serum"),
            _make_plugin("Vital", developer="Matt Tytel"),
        ])
        cmp = compare_snapshots(local, other)

        missing_names = [d.name for d in cmp.plugins_missing_locally]
        assert "Vital" in missing_names
        assert "Serum" not in missing_names

    def test_plugin_missing_on_other(self):
        local = _make_snapshot(plugins=[
            _make_plugin("Serum"),
            _make_plugin("Massive", developer="Native Instruments"),
        ])
        other = _make_snapshot(plugins=[_make_plugin("Serum")])
        cmp = compare_snapshots(local, other)

        missing_names = [d.name for d in cmp.plugins_missing_on_other]
        assert "Massive" in missing_names
        assert "Serum" not in missing_names

    def test_version_difference_detected(self):
        local_plugin = _make_plugin("Serum", version="1.30")
        other_plugin = _make_plugin("Serum", version="1.35")

        local = _make_snapshot(plugins=[local_plugin])
        other = _make_snapshot(plugins=[other_plugin])
        cmp = compare_snapshots(local, other)

        assert len(cmp.plugin_version_diffs) == 1
        diff = cmp.plugin_version_diffs[0]
        assert diff.name == "Serum"
        assert diff.local_version == "1.30"
        assert diff.other_version == "1.35"
        assert diff.diff_type == "version_diff"

    def test_version_diff_not_triggered_when_same(self):
        p = _make_plugin("Serum", version="1.35")
        local = _make_snapshot(plugins=[p])
        other = _make_snapshot(plugins=[p])
        cmp = compare_snapshots(local, other)
        assert cmp.plugin_version_diffs == []

    def test_version_diff_not_triggered_when_empty(self):
        local_p = _make_plugin("Serum", version="")
        other_p = _make_plugin("Serum", version="1.35")
        local = _make_snapshot(plugins=[local_p])
        other = _make_snapshot(plugins=[other_p])
        cmp = compare_snapshots(local, other)
        assert cmp.plugin_version_diffs == []

    def test_format_difference_detected(self):
        local_p = _make_plugin("Serum", fmt="VST3")
        other_p = _make_plugin("Serum", fmt="AU")

        local = _make_snapshot(plugins=[local_p])
        other = _make_snapshot(plugins=[other_p])
        cmp = compare_snapshots(local, other)

        assert len(cmp.plugin_format_diffs) == 1
        assert "VST3" in cmp.plugin_format_diffs[0].fmt
        assert "AU"   in cmp.plugin_format_diffs[0].fmt

    def test_software_missing_locally(self):
        local = _make_snapshot(software=[_make_software("Logic Pro")])
        other = _make_snapshot(software=[
            _make_software("Logic Pro"),
            _make_software("Ableton Live", category="DAW"),
        ])
        cmp = compare_snapshots(local, other)

        sw_names = [d.name for d in cmp.software_diffs]
        assert "Ableton Live" in sw_names

    def test_software_version_diff(self):
        local = _make_snapshot(software=[_make_software("Logic Pro", version="10.8")])
        other = _make_snapshot(software=[_make_software("Logic Pro", version="11.0")])
        cmp = compare_snapshots(local, other)

        version_diffs = [d for d in cmp.software_diffs if d.diff_type == "version_diff"]
        assert len(version_diffs) == 1
        assert version_diffs[0].local_version == "10.8"
        assert version_diffs[0].other_version == "11.0"

    def test_hardware_missing_locally(self):
        local = _make_snapshot(hardware=[])
        other = _make_snapshot(hardware=[_make_hardware("Focusrite Scarlett 2i2")])
        cmp = compare_snapshots(local, other)

        hw_names = [d.name for d in cmp.hardware_diffs]
        assert "Focusrite Scarlett 2i2" in hw_names
        assert cmp.hardware_diffs[0].diff_type == "missing_locally"

    def test_hardware_missing_on_other(self):
        local = _make_snapshot(hardware=[_make_hardware("Apollo Twin")])
        other = _make_snapshot(hardware=[])
        cmp = compare_snapshots(local, other)

        assert cmp.hardware_diffs[0].name == "Apollo Twin"
        assert cmp.hardware_diffs[0].diff_type == "missing_on_other"

    def test_total_differences_sum(self):
        local = _make_snapshot(
            plugins=[_make_plugin("Serum", version="1.30")],
            software=[_make_software("Logic Pro")],
            hardware=[_make_hardware()],
        )
        other = _make_snapshot(
            plugins=[
                _make_plugin("Serum", version="1.35"),    # version diff
                _make_plugin("Vital", developer="Matt"),  # missing locally
            ],
            software=[_make_software("Ableton Live")],   # both: local missing on other, other missing locally
            hardware=[],                                   # local missing on other
        )
        cmp = compare_snapshots(local, other)
        assert cmp.total_differences == sum([
            len(cmp.plugins_missing_locally),
            len(cmp.plugins_missing_on_other),
            len(cmp.plugin_version_diffs),
            len(cmp.plugin_format_diffs),
            len(cmp.software_diffs),
            len(cmp.hardware_diffs),
        ])

    def test_diff_type_fields(self):
        local = _make_snapshot(plugins=[_make_plugin("Serum")])
        other = _make_snapshot(plugins=[_make_plugin("Vital")])
        cmp = compare_snapshots(local, other)

        for diff in cmp.plugins_missing_locally:
            assert diff.diff_type == "missing_locally"
        for diff in cmp.plugins_missing_on_other:
            assert diff.diff_type == "missing_on_other"

    def test_empty_snapshots(self):
        local = _make_snapshot()
        other = _make_snapshot()
        cmp = compare_snapshots(local, other)
        assert not cmp.has_differences

    def test_normalised_name_matching(self):
        """Serum VST3 on local matches Serum on other (format-suffix stripped)."""
        local = _make_snapshot(plugins=[_make_plugin("Serum VST3", fmt="VST3")])
        other = _make_snapshot(plugins=[_make_plugin("Serum", fmt="VST3")])
        cmp = compare_snapshots(local, other)
        # Should NOT be reported as missing on either side (same normalised key + fmt)
        assert not cmp.plugins_missing_locally
        assert not cmp.plugins_missing_on_other


# ── StudioSnapshot.display_date ───────────────────────────────────────────────

class TestDisplayDate:
    def test_formats_iso_date(self):
        snap = _make_snapshot()
        snap.scan_date  # type: ignore  # noqa: B018 — just ensure it doesn't crash
        assert isinstance(snap.display_date, str)

    def test_falls_back_on_bad_date(self):
        snap = _make_snapshot()
        snap.__dict__["scan_date"] = "not-a-date"
        assert snap.display_date == "not-a-date"


# ── SnapshotComparison properties ─────────────────────────────────────────────

class TestComparisonProperties:
    def test_has_differences_false_when_clean(self):
        local = _make_snapshot()
        other = _make_snapshot()
        cmp = compare_snapshots(local, other)
        assert not cmp.has_differences

    def test_has_differences_true_when_plugins_differ(self):
        local = _make_snapshot(plugins=[_make_plugin("Serum")])
        other = _make_snapshot(plugins=[_make_plugin("Vital")])
        cmp = compare_snapshots(local, other)
        assert cmp.has_differences
