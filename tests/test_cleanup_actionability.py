"""
Tests for Cleanup Recommendation Actionability Layer.

Coverage:
- classify_row_actionability  (actionable, system_locked, already_quarantined, missing_path)
- classify_rec_actionability  (rec-level aggregation)
- cleanup_actionability_summary (counts and byte totals)
- generate_cleanup_report_rows (export content)
- copy-path selection logic (path list from redundant_format_paths)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.cleanup import (
    ACT_ACTIONABLE,
    ACT_ALREADY_QUAR,
    ACT_MISSING_PATH,
    ACT_NEEDS_PICKER,
    ACT_SYSTEM_LOCKED,
    ACT_UNSUPPORTED,
    CleanupRecommendation,
    CONF_REVIEW,
    CONF_SAFE,
    CONF_UNKNOWN,
    ActionabilitySummary,
    classify_rec_actionability,
    classify_row_actionability,
    cleanup_actionability_summary,
    generate_cleanup_report_rows,
    redundant_format_paths,
)
from app.core.scanner import Plugin


# ── helpers ───────────────────────────────────────────────────────────────────

def _plugin(name: str, fmt: str, path: str, *, developer: str = "Dev", file_size: int = 1_000_000) -> Plugin:
    return Plugin(
        name=name,
        fmt=fmt,
        path=path,
        developer=developer,
        file_size=file_size,
        version="1.0",
        modified="2024-01-01",
    )


def _rec(
    product: str,
    *,
    installed: dict[str, Plugin],
    keep: list[str],
    redundant: list[str],
    confidence: str = CONF_REVIEW,
) -> CleanupRecommendation:
    return CleanupRecommendation(
        product_name=product,
        developer="Dev",
        installed_formats=installed,
        keep_formats=keep,
        redundant_formats=redundant,
        confidence=confidence,
    )


def _make_bundle(parent: Path, name: str, suffix: str) -> Path:
    bundle = parent / f"{name}{suffix}"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "Contents").mkdir(exist_ok=True)
    return bundle


# ── classify_row_actionability ────────────────────────────────────────────────

class TestClassifyRowActionability(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_au(self, name: str = "Synth") -> tuple[Path, Plugin]:
        p = _make_bundle(self.tmp, name, ".component")
        plugin = _plugin(name, "AU", str(p), file_size=5_000_000)
        return p, plugin

    def _make_vst(self, name: str = "Synth") -> tuple[Path, Plugin]:
        p = _make_bundle(self.tmp, name, ".vst")
        plugin = _plugin(name, "VST", str(p), file_size=3_000_000)
        return p, plugin

    # --- actionable row ---

    def test_actionable_row(self):
        _, au_plugin = self._make_au()
        _, vst_plugin = self._make_vst()
        rec = _rec(
            "Synth",
            installed={"AU": au_plugin, "VST": vst_plugin},
            keep=["AU"],
            redundant=["VST"],
        )

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target") as mock_pf:
            mock_pf.return_value.can_offer_in_ui = True
            mock_pf.return_value.requires_system_ack = False
            mock_pf.return_value.not_writable = False
            mock_pf.return_value.message = ""

            act = classify_row_actionability(rec, "VST")

        self.assertEqual(act.status, ACT_ACTIONABLE)
        self.assertEqual(act.fmt, "VST")
        self.assertEqual(act.recoverable_size, 3_000_000)
        self.assertTrue(act.is_actionable)
        self.assertFalse(act.is_system_locked)
        self.assertEqual(act.label, "Can Quarantine")

    # --- system_locked row ---

    def test_system_locked_row(self):
        _, vst_plugin = self._make_vst()
        rec = _rec(
            "Synth",
            installed={"AU": _plugin("Synth", "AU", "/Library/Audio/Plug-Ins/Components/Synth.component"),
                       "VST": vst_plugin},
            keep=["AU"],
            redundant=["VST"],
        )

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target") as mock_pf:
            mock_pf.return_value.can_offer_in_ui = False
            mock_pf.return_value.requires_system_ack = False
            mock_pf.return_value.not_writable = True
            mock_pf.return_value.message = "not writable"

            act = classify_row_actionability(rec, "VST")

        self.assertEqual(act.status, ACT_SYSTEM_LOCKED)
        self.assertTrue(act.is_system_locked)
        self.assertFalse(act.is_actionable)
        self.assertIn("protected system location", act.reason)
        self.assertEqual(act.label, "System Locked")

    # --- already_quarantined row ---

    def test_already_quarantined_row(self):
        _, vst_plugin = self._make_vst()
        rec = _rec(
            "Synth",
            installed={"AU": _plugin("Synth", "AU", ""), "VST": vst_plugin},
            keep=["AU"],
            redundant=["VST"],
        )

        with patch("app.core.quarantine.is_path_quarantined", return_value=True):
            act = classify_row_actionability(rec, "VST")

        self.assertEqual(act.status, ACT_ALREADY_QUAR)
        self.assertEqual(act.label, "Already Quarantined")

    # --- missing_path row (no path recorded) ---

    def test_missing_path_row_empty_string(self):
        plugin = _plugin("Synth", "VST", "")
        rec = _rec(
            "Synth",
            installed={"AU": _plugin("Synth", "AU", "/some/path.component"), "VST": plugin},
            keep=["AU"],
            redundant=["VST"],
        )
        act = classify_row_actionability(rec, "VST")
        self.assertEqual(act.status, ACT_MISSING_PATH)
        self.assertEqual(act.label, "No Path")

    # --- missing_path row (path does not exist on disk) ---

    def test_missing_path_row_nonexistent(self):
        plugin = _plugin("Synth", "VST", "/tmp/this_does_not_exist_xyz.vst")
        rec = _rec(
            "Synth",
            installed={"AU": _plugin("Synth", "AU", ""), "VST": plugin},
            keep=["AU"],
            redundant=["VST"],
        )
        act = classify_row_actionability(rec, "VST")
        self.assertEqual(act.status, ACT_MISSING_PATH)


# ── classify_rec_actionability ────────────────────────────────────────────────

class TestClassifyRecActionability(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_actionable_rec(self):
        vst_path = self.tmp / "Synth.vst"
        vst_path.mkdir()
        vst = _plugin("Synth", "VST", str(vst_path), file_size=4_000_000)
        au  = _plugin("Synth", "AU",  str(self.tmp / "Synth.component"), file_size=5_000_000)
        rec = _rec(
            "Synth",
            installed={"AU": au, "VST": vst},
            keep=["AU"],
            redundant=["VST"],
        )

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target") as mock_pf:
            mock_pf.return_value.can_offer_in_ui = True
            mock_pf.return_value.requires_system_ack = False
            mock_pf.return_value.not_writable = False
            mock_pf.return_value.message = ""

            status, reason = classify_rec_actionability(rec)

        self.assertEqual(status, ACT_ACTIONABLE)

    def test_system_locked_rec(self):
        vst_path = self.tmp / "Synth.vst"
        vst_path.mkdir()
        vst = _plugin("Synth", "VST", str(vst_path), file_size=4_000_000)
        au  = _plugin("Synth", "AU",  str(self.tmp / "Synth.component"))
        rec = _rec(
            "Synth",
            installed={"AU": au, "VST": vst},
            keep=["AU"],
            redundant=["VST"],
        )

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target") as mock_pf:
            mock_pf.return_value.can_offer_in_ui = False
            mock_pf.return_value.requires_system_ack = False
            mock_pf.return_value.not_writable = True
            mock_pf.return_value.message = "not writable"

            status, reason = classify_rec_actionability(rec)

        self.assertEqual(status, ACT_SYSTEM_LOCKED)
        self.assertIn("protected system location", reason)

    def test_already_quarantined_rec(self):
        vst_path = self.tmp / "Synth.vst"
        vst_path.mkdir()
        vst = _plugin("Synth", "VST", str(vst_path))
        au  = _plugin("Synth", "AU",  "")
        rec = _rec(
            "Synth",
            installed={"AU": au, "VST": vst},
            keep=["AU"],
            redundant=["VST"],
        )

        with patch("app.core.quarantine.is_path_quarantined", return_value=True):
            status, _ = classify_rec_actionability(rec)

        self.assertEqual(status, ACT_ALREADY_QUAR)

    def test_no_redundant_returns_unsupported(self):
        au = _plugin("Synth", "AU", "")
        rec = _rec("Synth", installed={"AU": au}, keep=["AU"], redundant=[])
        status, _ = classify_rec_actionability(rec)
        self.assertEqual(status, ACT_UNSUPPORTED)

    def test_needs_picker_when_multiple_actionable(self):
        vst_path  = self.tmp / "Synth.vst";  vst_path.mkdir()
        aax_path  = self.tmp / "Synth.aaxplugin"; aax_path.mkdir()
        vst = _plugin("Synth", "VST",  str(vst_path),  file_size=3_000_000)
        aax = _plugin("Synth", "AAX",  str(aax_path),  file_size=6_000_000)
        au  = _plugin("Synth", "AU",   "")
        rec = _rec(
            "Synth",
            installed={"AU": au, "VST": vst, "AAX": aax},
            keep=["AU"],
            redundant=["VST", "AAX"],
            confidence=CONF_UNKNOWN,
        )

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target") as mock_pf:
            mock_pf.return_value.can_offer_in_ui = True
            mock_pf.return_value.requires_system_ack = False
            mock_pf.return_value.not_writable = False
            mock_pf.return_value.message = ""

            status, _ = classify_rec_actionability(rec)

        self.assertEqual(status, ACT_NEEDS_PICKER)


# ── cleanup_actionability_summary ─────────────────────────────────────────────

class TestCleanupActionabilitySummary(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _actionable_vst(self, name: str, size: int = 4_000_000) -> tuple[CleanupRecommendation, Plugin]:
        vst_path = self.tmp / f"{name}.vst"
        vst_path.mkdir(exist_ok=True)
        vst = _plugin(name, "VST", str(vst_path), file_size=size)
        au  = _plugin(name, "AU",  "")
        rec = _rec(name, installed={"AU": au, "VST": vst}, keep=["AU"], redundant=["VST"])
        return rec, vst

    def _system_locked_vst(self, name: str, size: int = 10_000_000) -> CleanupRecommendation:
        vst_path = self.tmp / f"{name}.vst"
        vst_path.mkdir(exist_ok=True)
        vst = _plugin(name, "VST", str(vst_path), file_size=size)
        au  = _plugin(name, "AU",  "")
        return _rec(name, installed={"AU": au, "VST": vst}, keep=["AU"], redundant=["VST"])

    def test_actionable_vs_system_locked_totals(self):
        rec_act, _ = self._actionable_vst("Actionable", size=4_000_000)
        rec_lock   = self._system_locked_vst("Locked",    size=10_000_000)

        def _pf_side_effect(path, **kw):
            from unittest.mock import MagicMock
            m = MagicMock()
            if "Actionable" in path:
                m.can_offer_in_ui = True
                m.requires_system_ack = False
                m.not_writable = False
            else:
                m.can_offer_in_ui = False
                m.requires_system_ack = False
                m.not_writable = True
                m.message = "locked"
            return m

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target", side_effect=_pf_side_effect):

            summary = cleanup_actionability_summary([rec_act, rec_lock])

        self.assertEqual(summary.recs_actionable, 1)
        self.assertEqual(summary.recs_system_locked, 1)
        self.assertEqual(summary.actionable_bytes, 4_000_000)
        self.assertEqual(summary.system_locked_bytes, 10_000_000)
        self.assertEqual(summary.total_bytes, 14_000_000)

    def test_empty_recs(self):
        summary = cleanup_actionability_summary([])
        self.assertEqual(summary.total_bytes, 0)
        self.assertEqual(summary.recs_actionable, 0)

    def test_already_quarantined_not_counted_as_actionable(self):
        rec_act, _ = self._actionable_vst("Synth", size=5_000_000)

        with patch("app.core.quarantine.is_path_quarantined", return_value=True):
            summary = cleanup_actionability_summary([rec_act])

        self.assertEqual(summary.recs_actionable, 0)
        self.assertEqual(summary.recs_already_quar, 1)
        self.assertEqual(summary.actionable_bytes, 0)


# ── generate_cleanup_report_rows ──────────────────────────────────────────────

class TestGenerateCleanupReportRows(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_report_has_expected_fields(self):
        vst_path = self.tmp / "Synth.vst"
        vst_path.mkdir()
        vst = _plugin("Synth", "VST", str(vst_path), file_size=3_000_000)
        au  = _plugin("Synth", "AU",  "")
        rec = _rec("Synth", installed={"AU": au, "VST": vst}, keep=["AU"], redundant=["VST"])

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target") as mock_pf:
            mock_pf.return_value.can_offer_in_ui = True
            mock_pf.return_value.requires_system_ack = False
            mock_pf.return_value.not_writable = False
            mock_pf.return_value.message = ""

            rows = generate_cleanup_report_rows([rec])

        self.assertEqual(len(rows), 1)
        row = rows[0]

        required_keys = [
            "Product", "Developer", "Installed Formats", "Keep Formats",
            "Redundant Format", "File Path", "Actionability", "Reason",
            "Est. Recoverable", "Est. Recoverable (bytes)", "Confidence",
            "Suggested Action",
        ]
        for key in required_keys:
            self.assertIn(key, row, f"Missing key: {key}")

        self.assertEqual(row["Product"], "Synth")
        self.assertEqual(row["Redundant Format"], "VST")
        self.assertEqual(row["Actionability"], "Can Quarantine")
        self.assertIn("Quarantine", row["Suggested Action"])
        self.assertEqual(row["Est. Recoverable (bytes)"], 3_000_000)

    def test_system_locked_row_has_manual_suggestion(self):
        vst_path = self.tmp / "Synth.vst"
        vst_path.mkdir()
        vst = _plugin("Synth", "VST", str(vst_path), file_size=8_000_000)
        au  = _plugin("Synth", "AU",  "")
        rec = _rec("Synth", installed={"AU": au, "VST": vst}, keep=["AU"], redundant=["VST"])

        with patch("app.core.quarantine.is_path_quarantined", return_value=False), \
             patch("app.core.quarantine.preflight_quarantine_target") as mock_pf:
            mock_pf.return_value.can_offer_in_ui = False
            mock_pf.return_value.requires_system_ack = False
            mock_pf.return_value.not_writable = True
            mock_pf.return_value.message = "locked"

            rows = generate_cleanup_report_rows([rec])

        self.assertEqual(rows[0]["Actionability"], "System Locked")
        self.assertIn("vendor", rows[0]["Suggested Action"].lower())

    def test_no_redundant_recs_excluded(self):
        au = _plugin("Synth", "AU", "")
        rec = _rec("Synth", installed={"AU": au}, keep=["AU"], redundant=[])
        rows = generate_cleanup_report_rows([rec])
        self.assertEqual(rows, [])

    def test_already_quarantined_row(self):
        vst_path = self.tmp / "Synth.vst"
        vst_path.mkdir()
        vst = _plugin("Synth", "VST", str(vst_path))
        au  = _plugin("Synth", "AU",  "")
        rec = _rec("Synth", installed={"AU": au, "VST": vst}, keep=["AU"], redundant=["VST"])

        with patch("app.core.quarantine.is_path_quarantined", return_value=True):
            rows = generate_cleanup_report_rows([rec])

        self.assertEqual(rows[0]["Actionability"], "Already Quarantined")
        self.assertIn("quarantined", rows[0]["Suggested Action"].lower())


# ── Copy-path selection logic ─────────────────────────────────────────────────

class TestCopyPathPaths(unittest.TestCase):
    """
    The copy-path UI relies on redundant_format_paths() to get candidate paths.
    Verify the correct paths are returned for single- and multi-path recs.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_single_path_copy(self):
        vst_path = self.tmp / "Synth.vst"
        vst_path.mkdir()
        vst = _plugin("Synth", "VST", str(vst_path))
        au  = _plugin("Synth", "AU",  "")
        rec = _rec("Synth", installed={"AU": au, "VST": vst}, keep=["AU"], redundant=["VST"])

        paths = redundant_format_paths(rec)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].path, str(vst_path))
        self.assertEqual(paths[0].fmt, "VST")

    def test_multi_path_copy_shows_all(self):
        vst_path = self.tmp / "Synth.vst";  vst_path.mkdir()
        aax_path = self.tmp / "Synth.aaxplugin"; aax_path.mkdir()
        vst = _plugin("Synth", "VST",  str(vst_path),  file_size=3_000_000)
        aax = _plugin("Synth", "AAX",  str(aax_path),  file_size=6_000_000)
        au  = _plugin("Synth", "AU",   "")
        rec = _rec(
            "Synth",
            installed={"AU": au, "VST": vst, "AAX": aax},
            keep=["AU"],
            redundant=["VST", "AAX"],
        )

        paths = redundant_format_paths(rec)
        self.assertEqual(len(paths), 2)
        fmts = {p.fmt for p in paths}
        self.assertIn("VST", fmts)
        self.assertIn("AAX", fmts)

    def test_nonexistent_path_excluded(self):
        vst = _plugin("Synth", "VST", "/tmp/does_not_exist_xyz.vst")
        au  = _plugin("Synth", "AU",  "")
        rec = _rec("Synth", installed={"AU": au, "VST": vst}, keep=["AU"], redundant=["VST"])

        paths = redundant_format_paths(rec)
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
