"""Tests for studio_vault.scanners.plugins (temp-dir bundles only)."""

from __future__ import annotations

import os
import threading

from studio_vault.scanners.plugins import (
    SizeCache,
    bundle_metadata,
    group_by_product,
    normalize_product_name,
    scan_plugins,
)
from tests.v2.conftest import make_bundle


def _plist(version="1.0", bundle_id="com.acme.reverb", **extra) -> dict:
    return {"CFBundleShortVersionString": version, "CFBundleIdentifier": bundle_id, **extra}


class TestScanPlugins:
    def test_finds_every_format_including_clap(self, tmp_path):
        for name in ("Verb.vst3", "Verb.component", "Verb.clap", "Verb.vst", "Verb.aaxplugin"):
            make_bundle(tmp_path, name, _plist())
        result = scan_plugins([str(tmp_path)])
        assert sorted(p.fmt for p in result.plugins) == ["AAX", "AU", "CLAP", "VST", "VST3"]

    def test_walks_vendor_subfolders(self, tmp_path):
        make_bundle(tmp_path / "Acme", "Comp.vst3", _plist())
        result = scan_plugins([str(tmp_path)])
        assert [p.name for p in result.plugins] == ["Comp"]

    def test_ignores_non_plugin_files_and_missing_folders(self, tmp_path):
        (tmp_path / "readme.txt").write_text("x")
        result = scan_plugins([str(tmp_path), str(tmp_path / "missing")])
        assert result.plugins == []
        assert result.errors == []

    def test_same_folder_twice_is_deduplicated(self, tmp_path):
        make_bundle(tmp_path, "A.vst3", _plist())
        result = scan_plugins([str(tmp_path), str(tmp_path)])
        assert result.count == 1

    def test_reads_version_bundle_id_and_size(self, tmp_path):
        make_bundle(tmp_path, "A.vst3", _plist(version="2.5.1", bundle_id="com.acme.a"), payload=4096)
        plugin = scan_plugins([str(tmp_path)]).plugins[0]
        assert plugin.version == "2.5.1"
        assert plugin.bundle_id == "com.acme.a"
        assert plugin.file_size >= 4096
        assert plugin.modified

    def test_bundle_without_plist_still_listed(self, tmp_path):
        (tmp_path / "Bare.vst3").mkdir()
        plugin = scan_plugins([str(tmp_path)]).plugins[0]
        assert plugin.name == "Bare"
        assert plugin.version == ""

    def test_cancel_stops_scan(self, tmp_path):
        make_bundle(tmp_path, "A.vst3", _plist())
        cancel = threading.Event()
        cancel.set()
        result = scan_plugins([str(tmp_path)], cancel=cancel)
        assert result.cancelled
        assert result.plugins == []

    def test_progress_messages(self, tmp_path):
        messages: list[str] = []
        scan_plugins([str(tmp_path)], progress_cb=messages.append)
        assert messages[0].startswith("Scanning")
        assert messages[-1].startswith("Done")


class TestDeveloper:
    def test_audio_components_name(self, tmp_path):
        b = make_bundle(tmp_path, "X.component", _plist(AudioComponents=[{"name": "FabFilter: Pro-Q 3"}]))
        assert bundle_metadata(b)["developer"] == "FabFilter"

    def test_copyright_with_year_range(self, tmp_path):
        b = make_bundle(tmp_path, "X.vst3", _plist(bundle_id="", NSHumanReadableCopyright="© 2001-2023 Acme Audio, Inc."))
        assert bundle_metadata(b)["developer"] == "Acme Audio"

    def test_copyright_year_range_with_spaces(self, tmp_path):
        b = make_bundle(tmp_path, "X.vst3", _plist(bundle_id="", CFBundleGetInfoString="M1 1.0, © 2016 - 2023 Korg Inc."))
        assert bundle_metadata(b)["developer"] == "Korg Inc"

    def test_bundle_id_fallback(self, tmp_path):
        b = make_bundle(tmp_path, "X.vst3", _plist(bundle_id="com.u-he.diva"))
        assert bundle_metadata(b)["developer"] == "U He"


class TestSizeCache:
    def test_cache_hit_skips_walk_until_bundle_changes(self, tmp_path, monkeypatch):
        bundle = make_bundle(tmp_path, "A.vst3", _plist(), payload=100)
        cache_file = tmp_path / "cache.json"
        first = SizeCache(cache_file).size_of(bundle)
        cache = SizeCache(cache_file)
        assert cache.size_of(bundle) == first  # in-memory miss would also give this; check persistence:
        cache.save()

        calls = []
        import studio_vault.scanners.plugins as mod
        real = mod.bundle_size
        monkeypatch.setattr(mod, "bundle_size", lambda p: calls.append(p) or real(p))

        SizeCache(cache_file).size_of(bundle)
        assert calls == []

        plist = bundle / "Contents" / "Info.plist"
        st = plist.stat()
        os.utime(plist, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        SizeCache(cache_file).size_of(bundle)
        assert calls == [bundle]

    def test_corrupt_cache_file_is_ignored(self, tmp_path):
        bundle = make_bundle(tmp_path, "A.vst3", _plist(), payload=10)
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{not json")
        assert SizeCache(cache_file).size_of(bundle) >= 10


class TestGrouping:
    def test_normalize_strips_format_suffix(self):
        assert normalize_product_name("Serum VST3") == "serum"
        assert normalize_product_name("Surge_CLAP") == "surge"

    def test_group_by_product_orders_formats(self, tmp_path):
        for name in ("Serum.component", "Serum.vst3", "Serum.clap", "Other.vst"):
            make_bundle(tmp_path, name, _plist())
        groups = group_by_product(scan_plugins([str(tmp_path)]).plugins)
        assert [g.product_name for g in groups] == ["Other", "Serum"]
        assert groups[1].format_names == ["VST3", "AU", "CLAP"]
