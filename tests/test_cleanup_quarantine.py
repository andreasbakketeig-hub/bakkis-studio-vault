"""Tests for Cleanup Recommendations quarantine integration."""

from __future__ import annotations

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
    get_profile,
    make_custom_profile,
    redundant_format_paths,
    requires_format_picker,
)
from app.core.scanner import Plugin
from app.core import quarantine as q


def _plugin(name: str, fmt: str, path: str, **kwargs) -> Plugin:
    return Plugin(
        name=name,
        fmt=fmt,
        path=path,
        developer=kwargs.get("developer", "Test Dev"),
        file_size=kwargs.get("file_size", 4096),
        version=kwargs.get("version", "1.0"),
        modified=kwargs.get("modified", "2024-01-01"),
    )


def _fake_bundle(parent: Path, name: str, suffix: str) -> Path:
    bundle = parent / name
    if suffix == ".vst3":
        bundle.mkdir(parents=True)
        (bundle / "Contents").mkdir()
        (bundle / "Contents" / "Info.plist").write_bytes(
            b'<?xml version="1.0"?><plist version="1.0"><dict/></plist>'
        )
    else:
        bundle.mkdir(parents=True)
    return bundle


class CleanupPathResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.vst3 = _fake_bundle(root / "VST3", "Product.vst3", ".vst3")
        self.vst = _fake_bundle(root / "VST", "Product.vst", ".vst")

    def test_redundant_paths_resolve_exact_files(self) -> None:
        plugins = [
            _plugin("Product", "VST3", str(self.vst3)),
            _plugin("Product", "VST", str(self.vst)),
        ]
        recs = analyze_cleanup(plugins, get_profile("ableton"))
        flagged = [r for r in recs if r.has_redundant]
        self.assertEqual(len(flagged), 1)
        rec = flagged[0]
        paths = redundant_format_paths(rec)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].fmt, "VST")
        self.assertEqual(paths[0].path, str(self.vst))

    def test_no_paths_when_redundant_missing_on_disk(self) -> None:
        rec = CleanupRecommendation(
            product_name="Ghost",
            developer="Dev",
            installed_formats={
                "VST": _plugin("Ghost", "VST", "/no/such/path.vst"),
            },
            keep_formats=["VST3"],
            redundant_formats=["VST"],
            confidence=CONF_SAFE,
        )
        self.assertEqual(redundant_format_paths(rec), [])

    def test_quarantine_disabled_without_paths(self) -> None:
        rec = CleanupRecommendation(
            product_name="Ghost",
            developer="Dev",
            installed_formats={},
            keep_formats=["VST3"],
            redundant_formats=["VST"],
            confidence=CONF_SAFE,
        )
        self.assertFalse(can_offer_cleanup_quarantine(rec))

    def test_multi_format_requires_picker_but_enables_button(self) -> None:
        rec = CleanupRecommendation(
            product_name="Multi",
            developer="Dev",
            installed_formats={
                "VST": _plugin("Multi", "VST", str(self.vst)),
                "AAX": _plugin("Multi", "AAX", str(_fake_bundle(
                    Path(self._tmp.name) / "AAX", "Multi.aaxplugin", ".aaxplugin"
                ))),
            },
            keep_formats=["VST3"],
            redundant_formats=["VST", "AAX"],
            confidence=CONF_REVIEW,
        )
        self.assertTrue(requires_format_picker(rec))
        with patch(
            "app.core.quarantine._allowed_roots",
            return_value=[Path(self._tmp.name).resolve()],
        ):
            self.assertTrue(can_offer_cleanup_quarantine(rec))

    def test_unknown_confidence_enables_picker_flow(self) -> None:
        rec = CleanupRecommendation(
            product_name="Unknown",
            developer="Dev",
            installed_formats={"VST": _plugin("Unknown", "VST", str(self.vst))},
            keep_formats=["VST3"],
            redundant_formats=["VST"],
            confidence=CONF_UNKNOWN,
        )
        self.assertTrue(requires_format_picker(rec))
        with patch(
            "app.core.quarantine._allowed_roots",
            return_value=[Path(self._tmp.name).resolve()],
        ):
            self.assertTrue(can_offer_cleanup_quarantine(rec))


class CleanupQuarantineRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.vst3 = _fake_bundle(root / "VST3", "RefreshProduct.vst3", ".vst3")
        self.vst = _fake_bundle(root / "VST", "RefreshProduct.vst", ".vst")
        self.q_root = root / "quarantine"
        self.plugin_root = root / "plugins" / "VST3"
        self.plugin_root.mkdir(parents=True)
        self._allowed = patch.object(
            q, "_allowed_roots",
            return_value=[self.plugin_root.resolve(), root.resolve()],
        )
        self._allowed.start()
        self.addCleanup(self._allowed.stop)

    def test_after_quarantine_recommendation_drops_removed_format(self) -> None:
        from app.core.quarantine import move_to_quarantine

        plugins = [
            _plugin("RefreshProduct", "VST3", str(self.vst3)),
            _plugin("RefreshProduct", "VST", str(self.vst)),
        ]
        rec_before = [r for r in analyze_cleanup(plugins, get_profile("ableton")) if r.has_redundant][0]
        self.assertIn("VST", rec_before.redundant_formats)

        move_to_quarantine(
            str(self.vst),
            "cleanup test",
            root=self.q_root,
            scan_paths=[str(self.plugin_root.parent.parent)],
        )

        plugins_after = [_plugin("RefreshProduct", "VST3", str(self.vst3))]
        rec_after = analyze_cleanup(plugins_after, get_profile("ableton"))
        multi = [r for r in rec_after if r.product_name == "RefreshProduct"]
        self.assertTrue(
            all("VST" not in r.redundant_formats for r in multi)
        )


class SafeModeLogicTests(unittest.TestCase):
    def test_safe_mode_does_not_imply_auto_quarantine(self) -> None:
        """Safe Mode only affects confidence labels, not quarantine eligibility hooks."""
        rec = CleanupRecommendation(
            product_name="Safe",
            developer="Dev",
            installed_formats={
                "VST": _plugin("Safe", "VST", "/tmp/fake.vst"),
            },
            keep_formats=["VST3"],
            redundant_formats=["VST"],
            confidence=CONF_REVIEW,
        )
        with patch.object(q, "is_path_quarantined", return_value=False):
            with patch(
                "app.core.cleanup.redundant_format_paths",
                return_value=[],
            ):
                self.assertFalse(can_offer_cleanup_quarantine(rec))


if __name__ == "__main__":
    unittest.main()
