"""Tests for studio_vault.snapshot (schema v2, v1 import, privacy, storage)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from studio_vault import config
from studio_vault import snapshot as snap
from studio_vault.snapshot import SnapshotError

THIS_MAC = snap.hash_machine_id("THIS-MAC-UUID")


@pytest.fixture(autouse=True)
def fake_machine():
    with patch.object(snap, "this_machine_id", return_value=THIS_MAC), \
         patch.object(snap, "this_machine_name", return_value="Studio Mac"):
        yield


@dataclass
class P:
    name: str
    fmt: str
    path: str
    developer: str = "Acme"
    version: str = "1.0"
    bundle_id: str = "com.acme.x"
    file_size: int = 10
    modified: str = "2026-01-01"


@dataclass
class A:
    name: str
    path: str
    category: str = "DAW"
    developer: str = "Ableton"
    version: str = "12.1"


@dataclass
class H:
    name: str
    vendor: str = "SSL"
    device_type: str = "Audio Interface"
    connection_type: str = "USB"


def _scan_snapshot(name=""):
    return snap.from_scan(
        [P("Serum", "VST3", "/Users/andreas/Library/Audio/Plug-Ins/VST3/Serum.vst3"),
         P("Pro-Q 3", "AU", "/Library/Audio/Plug-Ins/Components/Pro-Q 3.component")],
        [A("Ableton Live 12 Suite", "/Applications/Ableton Live 12 Suite.app")],
        [H("BiG SiX")],
        name=name,
    )


V1_STUDIO = {
    "schema_version": 1,
    "machine_name": "Old Mac",
    "machine_id": "12345678-AAAA-BBBB-CCCC-1234567890AB",
    "scan_date": "2026-06-05T10:00:00",
    "app_version": "",
    "plugins": [{"name": "Serum", "developer": "Xfer Records", "version": "1.35", "fmt": "VST3",
                 "path": "/Users/olduser/Library/Audio/Plug-Ins/VST3/Serum.vst3",
                 "size": 123, "modified": "2025-11-01"}],
    "music_software": [{"name": "Logic Pro", "version": "11.0", "category": "DAW",
                        "path": "/Applications/Logic Pro.app"}],
    "hardware": [{"name": "Scarlett 2i2", "vendor": "Focusrite", "device_type": "Audio Interface",
                  "connection_type": "USB"}],
    "summary": {"total_plugins": 1},
}

V1_MIGRATION = {
    "created_at": "2026-05-01T09:00:00",
    "hostname": "Laptop  [Old Mac]",
    "plugins": [{"name": "Diva", "fmt": "AU", "developer": "u-he", "version": "1.4.5",
                 "file_size": 999, "modified": "2025-01-01",
                 "path": "/Users/someone/Library/Audio/Plug-Ins/Components/Diva.component"}],
    "apps": [{"name": "Native Access", "category": "Plugin Manager", "developer": "NI",
              "version": "3.1", "path": "/Applications/Native Access.app", "modified": ""}],
}


class TestPrivacy:
    @pytest.mark.parametrize("raw,clean", [
        ("/Users/andreas/Library/Audio/x.vst3", "~/Library/Audio/x.vst3"),
        ("/Users/andreas", "~"),
        ("/Library/Audio/x.vst3", "/Library/Audio/x.vst3"),
        ("/Applications/Live.app", "/Applications/Live.app"),
        ("", ""),
    ])
    def test_scrub_path(self, raw, clean):
        assert snap.scrub_path(raw) == clean

    def test_scan_snapshot_has_no_user_paths_or_raw_uuid(self):
        text = json.dumps(_scan_snapshot().to_dict())
        assert "/Users/" not in text
        assert "THIS-MAC-UUID" not in text

    def test_v1_import_scrubs_paths_and_hashes_uuid(self):
        s = snap.parse(V1_STUDIO)
        text = json.dumps(s.to_dict())
        assert "/Users/" not in text
        assert "12345678-AAAA" not in text
        assert s.machine_id == snap.hash_machine_id(V1_STUDIO["machine_id"])


class TestFromScan:
    def test_fields(self):
        s = _scan_snapshot(name="Before upgrade")
        assert s.name == "Before upgrade"
        assert s.machine_name == "Studio Mac"
        assert s.machine_id == THIS_MAC
        assert s.source == snap.SOURCE_SCAN
        assert [p.name for p in s.plugins] == ["Pro-Q 3", "Serum"]  # sorted
        assert s.plugins[1].path == "~/Library/Audio/Plug-Ins/VST3/Serum.vst3"
        assert s.plugins[1].size == 10
        assert s.plugin_formats == {"AU": 1, "VST3": 1}

    def test_default_name_is_machine_name(self):
        assert _scan_snapshot().name == "Studio Mac"


class TestParse:
    def test_v2_round_trip(self):
        s = _scan_snapshot()
        s.plugins[0] = type(s.plugins[0])(**{**s.plugins[0].__dict__, "arch": "intel", "min_macos": "10.13"})
        s.cpu = "arm64"
        s.content = [snap.SnapContent("Splice samples", "~/Splice", 123, 4, True)]
        again = snap.parse(json.loads(json.dumps(s.to_dict())))
        assert again == s

    def test_v1_studio_snapshot(self):
        s = snap.parse(V1_STUDIO)
        assert s.source == snap.SOURCE_IMPORT_V1
        assert s.machine_name == "Old Mac"
        assert s.created_at == "2026-06-05T10:00:00"
        assert s.plugins[0].size == 123
        assert s.apps[0].name == "Logic Pro"
        assert s.hardware[0].name == "Scarlett 2i2"

    def test_v1_migration_snapshot(self):
        s = snap.parse(V1_MIGRATION)
        assert s.machine_name == "Laptop"
        assert s.name == "Laptop  [Old Mac]"
        assert s.plugins[0].size == 999
        assert s.plugins[0].path == "~/Library/Audio/Plug-Ins/Components/Diva.component"
        assert s.apps[0].name == "Native Access"
        assert s.hardware == []

    def test_v1_ids_are_stable(self):
        assert snap.parse(V1_STUDIO).id == snap.parse(dict(V1_STUDIO)).id

    @pytest.mark.parametrize("data", [[], "x", {}, {"foo": 1}, {"schema_version": 7}])
    def test_rejects_non_snapshots(self, data):
        with pytest.raises(SnapshotError):
            snap.parse(data)

    def test_rejects_newer_schema(self):
        data = _scan_snapshot().to_dict() | {"schema_version": 99}
        with pytest.raises(SnapshotError, match="newer version"):
            snap.parse(data)

    def test_tolerates_bad_field_types(self):
        data = _scan_snapshot().to_dict()
        data["plugins"] = [{"name": 5, "fmt": "VST3", "size": -3}, "junk"]
        data["apps"] = "not a list"
        s = snap.parse(data)
        assert s.plugins[0].name == ""
        assert s.plugins[0].size == 0
        assert s.apps == []

    def test_load_unreadable_file(self, tmp_path):
        bad = tmp_path / "bad.studiovault"
        bad.write_text("{nope")
        with pytest.raises(SnapshotError):
            snap.load(bad)


class TestStorage:
    def test_save_list_load(self):
        s = _scan_snapshot()
        path = snap.save(s)
        assert path.parent == config.snapshots_dir()
        assert path.suffix == ".studiovault"
        [info] = snap.list_snapshots()
        assert info.id == s.id
        assert info.plugin_count == 2
        assert info.is_this_mac
        assert snap.load(info.path) == s

    def test_list_newest_first_and_skips_corrupt(self):
        a = _scan_snapshot(); a.created_at = "2026-01-01T00:00:00"
        b = _scan_snapshot(); b.created_at = "2026-02-01T00:00:00"
        snap.save(a); snap.save(b)
        (config.snapshots_dir() / "broken.studiovault").write_text("{")
        assert [i.id for i in snap.list_snapshots()] == [b.id, a.id]

    def test_latest_for_this_mac_ignores_other_macs(self):
        other = snap.parse(V1_STUDIO)
        other.created_at = "2030-01-01T00:00:00"
        snap.save(other)
        mine = _scan_snapshot()
        snap.save(mine)
        assert snap.latest_for_this_mac().id == mine.id

    def test_export_adds_suffix_and_import_dedupes(self, tmp_path):
        s = _scan_snapshot()
        out = snap.export(s, tmp_path / "share" / "my studio")
        assert out.name == "my studio.studiovault"
        snap.import_file(out)
        snap.import_file(out)
        assert len(snap.list_snapshots()) == 1

    def test_import_legacy_folder(self, tmp_path):
        legacy = tmp_path / "BakkisStudioManager"
        (legacy / "snapshots").mkdir(parents=True)
        (legacy / "snapshots" / "a.json").write_text(json.dumps(V1_STUDIO))
        (legacy / "snapshots" / "junk.json").write_text("[]")
        assert snap.import_legacy(legacy) == 1
        assert snap.import_legacy(legacy) == 1  # re-run imports nothing new
        assert len(snap.list_snapshots()) == 1

    def test_import_legacy_missing_folder(self, tmp_path):
        assert snap.import_legacy(tmp_path / "nope") == 0
