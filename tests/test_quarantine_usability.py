"""Tests for quarantine usability fixes."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.cleanup import (
    CONF_REVIEW,
    CONF_SAFE,
    CONF_UNKNOWN,
    CleanupRecommendation,
    analyze_cleanup,
    can_offer_cleanup_quarantine,
    requires_format_picker,
)
from app.core.plugin_insights import PluginInsight, is_quarantine_eligible
from app.core.quarantine import (
    DEFAULT_QUARANTINE_ROOT,
    apply_quarantine_settings,
    default_quarantine_folder,
    get_quarantine_root,
    is_quarantine_path_movable,
    preflight_quarantine_target,
    set_configured_quarantine_root,
    sync_quarantine_root_from_settings,
    validate_quarantine_folder,
)
from app.core.scanner import Plugin
from app.core.settings import AppSettings, DEFAULT_QUARANTINE_FOLDER


def _plugin(name: str, fmt: str, path: str) -> Plugin:
    return Plugin(name=name, fmt=fmt, path=path, developer="Dev", file_size=100)


def _fake_bundle(parent: Path, name: str) -> Path:
    bundle = parent / name
    bundle.mkdir(parents=True)
    (bundle / "Contents").mkdir(exist_ok=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        b'<?xml version="1.0"?><plist version="1.0"><dict/></plist>'
    )
    return bundle


class CleanupQuarantineButtonTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.vst = _fake_bundle(root / "VST", "Prod.vst")
        self.aax = _fake_bundle(root / "AAX", "Prod.aaxplugin")
        self.scan = [str(root)]
        self._allowed = patch(
            "app.core.quarantine._allowed_roots",
            return_value=[root.resolve()],
        )
        self._allowed.start()
        self.addCleanup(self._allowed.stop)

    def _rec(
        self,
        fmts: dict[str, Path],
        redundant: list[str],
        confidence: str,
    ) -> CleanupRecommendation:
        installed = {
            fmt: _plugin("Prod", fmt, str(path))
            for fmt, path in fmts.items()
        }
        return CleanupRecommendation(
            product_name="Prod",
            developer="Dev",
            installed_formats=installed,
            keep_formats=["VST3"],
            redundant_formats=redundant,
            confidence=confidence,
        )

    def test_multi_format_enables_without_selected_path(self) -> None:
        rec = self._rec(
            {"VST": self.vst, "AAX": self.aax},
            ["VST", "AAX"],
            CONF_REVIEW,
        )
        self.assertTrue(requires_format_picker(rec))
        self.assertTrue(
            can_offer_cleanup_quarantine(rec, scan_paths=self.scan)
        )

    def test_unknown_confidence_enables_without_selected_path(self) -> None:
        rec = self._rec({"VST": self.vst}, ["VST"], CONF_UNKNOWN)
        self.assertTrue(requires_format_picker(rec))
        self.assertTrue(
            can_offer_cleanup_quarantine(rec, scan_paths=self.scan)
        )

    def test_single_safe_review_direct_confirm_path(self) -> None:
        rec = self._rec({"VST": self.vst}, ["VST"], CONF_SAFE)
        self.assertFalse(requires_format_picker(rec))
        self.assertTrue(
            can_offer_cleanup_quarantine(rec, scan_paths=self.scan)
        )

    def test_non_writable_path_disables_offer(self) -> None:
        rec = self._rec({"VST": self.vst}, ["VST"], CONF_SAFE)
        with patch(
            "app.core.quarantine.is_quarantine_path_movable",
            return_value=False,
        ):
            self.assertFalse(
                can_offer_cleanup_quarantine(rec, scan_paths=self.scan)
            )


class PluginHealthPrecheckTests(unittest.TestCase):
    def test_same_movability_preflight_as_cleanup(self) -> None:
        insight = PluginInsight(
            plugin_name="P",
            developer="D",
            fmt="VST",
            installed_version="1",
            path="/tmp/missing.vst",
            issue_kind="redundant_format",
            risk_level="low",
            update_status="unknown",
            recommended_action="review",
            recommendation="test",
        )
        self.assertTrue(is_quarantine_eligible(insight))
        pf = preflight_quarantine_target(insight.path)
        self.assertFalse(pf.can_offer_in_ui)


class QuarantineFolderSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.plugin_root = Path(self._tmp.name) / "plugins"
        self.plugin_root.mkdir()
        self.q_folder = Path(self._tmp.name) / "quarantine"
        set_configured_quarantine_root(None)

    def tearDown(self) -> None:
        set_configured_quarantine_root(None)

    def test_custom_folder_validation_rejects_scan_path_inside(self) -> None:
        v = validate_quarantine_folder(
            str(self.plugin_root),
            scan_paths=[str(self.plugin_root)],
        )
        self.assertFalse(v.ok)

    def test_custom_folder_accepts_writable_outside_scan_paths(self) -> None:
        v = validate_quarantine_folder(
            str(self.q_folder),
            scan_paths=[str(self.plugin_root)],
        )
        self.assertTrue(v.ok)

    def test_reset_to_default_uses_music_path(self) -> None:
        self.assertEqual(
            DEFAULT_QUARANTINE_FOLDER,
            default_quarantine_folder(),
        )

    def test_apply_settings_uses_configured_root(self) -> None:
        custom = str(self.q_folder)
        settings = AppSettings(quarantine_folder=custom)
        apply_quarantine_settings(settings)
        self.assertEqual(get_quarantine_root(), self.q_folder.resolve())

    def test_empty_setting_falls_back_to_default(self) -> None:
        apply_quarantine_settings(AppSettings(quarantine_folder=""))
        self.assertEqual(
            get_quarantine_root(),
            DEFAULT_QUARANTINE_ROOT.expanduser().resolve(),
        )

    def test_sync_reads_settings_without_relying_on_stale_global(self) -> None:
        set_configured_quarantine_root(None)
        custom = str(self.q_folder)
        settings = AppSettings(quarantine_folder=custom)
        resolved = sync_quarantine_root_from_settings(settings)
        self.assertEqual(resolved, self.q_folder.resolve())
        self.assertEqual(
            get_quarantine_root(settings=settings),
            self.q_folder.resolve(),
        )


class MovabilityTests(unittest.TestCase):
    def test_movable_temp_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _fake_bundle(Path(tmp), "X.vst3")
            self.assertTrue(is_quarantine_path_movable(str(bundle)))

    def test_non_writable_detection(self) -> None:
        with patch("app.core.quarantine.os.access", return_value=False):
            self.assertFalse(is_quarantine_path_movable("/Library/Fake/X.vst3"))


class AnalyzeCleanupIntegrationTests(unittest.TestCase):
    def test_dual_format_analyze_enables_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vst3 = _fake_bundle(root / "VST3", "Dual.vst3")
            vst = _fake_bundle(root / "VST", "Dual.vst")
            plugins = [
                _plugin("Dual", "VST3", str(vst3)),
                _plugin("Dual", "VST", str(vst)),
            ]
            with patch(
                "app.core.quarantine._allowed_roots",
                return_value=[root.resolve()],
            ):
                rec = [
                    r for r in analyze_cleanup(plugins)
                    if r.has_redundant
                ][0]
                self.assertTrue(
                    can_offer_cleanup_quarantine(
                        rec, scan_paths=[str(root)],
                    )
                )


if __name__ == "__main__":
    unittest.main()
