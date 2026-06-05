"""Lightweight tests for read-only plugin insights."""

from __future__ import annotations

import datetime
import unittest

from app.core.music_software_scanner import MusicApp
from app.core.plugin_insights import (
    FILTER_UPDATE_GUIDANCE,
    FILTER_VERSION_CONFLICT,
    KIND_MANUAL_UPDATE_CHECK,
    KIND_STALE_MODIFIED,
    KIND_UPDATE_MANAGER_AVAILABLE,
    KIND_VENDOR_WEBSITE,
    KIND_VERSION_CONFLICT,
    UPDATE_VERSION_MISMATCH,
    analyze_insights,
    insight_options_from_settings,
)
from app.core.scanner import Plugin
from app.core.settings import AppSettings
from app.core.vendor_registry import match_vendor


def _plugin(
    name: str,
    fmt: str,
    path: str,
    *,
    version: str = "",
    developer: str = "",
    modified: str = "",
) -> Plugin:
    return Plugin(
        name=name,
        fmt=fmt,
        path=path,
        version=version,
        developer=developer,
        modified=modified,
    )


class PluginInsightsTests(unittest.TestCase):
    def test_version_conflict_across_formats(self) -> None:
        plugins = [
            _plugin("Reverb X", "VST3", "/tmp/Reverb X.vst3", version="2.1.0", developer="Acme"),
            _plugin("Reverb X", "AU", "/tmp/Reverb X.component", version="2.0.0", developer="Acme"),
        ]
        report = analyze_insights(plugins)
        self.assertEqual(len(report.version_conflicts), 1)
        self.assertEqual(report.version_conflict_products, 1)
        conflict = report.version_conflicts[0]
        self.assertEqual(conflict.issue_kind, KIND_VERSION_CONFLICT)
        self.assertEqual(conflict.update_status, UPDATE_VERSION_MISMATCH)

    def test_version_equivalent_not_conflict(self) -> None:
        plugins = [
            _plugin("P", "VST3", "/tmp/P.vst3", version="1.0"),
            _plugin("P", "AU", "/tmp/P.component", version="1.0.0"),
        ]
        report = analyze_insights(plugins)
        self.assertEqual(len(report.version_conflicts), 0)

    def test_stale_modified_thresholds(self) -> None:
        old = (datetime.date.today() - datetime.timedelta(days=365 * 4)).strftime("%Y-%m-%d")
        ancient = (datetime.date.today() - datetime.timedelta(days=365 * 6)).strftime("%Y-%m-%d")
        recent = datetime.date.today().strftime("%Y-%m-%d")
        plugins = [
            _plugin("Old", "AU", "/tmp/Old.component", modified=old),
            _plugin("Ancient", "VST3", "/tmp/Ancient.vst3", modified=ancient),
            _plugin("Fresh", "VST3", "/tmp/Fresh.vst3", modified=recent),
        ]
        report = analyze_insights(plugins)
        stale = report.stale_plugins
        self.assertEqual(len(stale), 2)
        kinds = {i.plugin_name: i.risk_level for i in stale}
        self.assertEqual(kinds["Old"], "medium")
        self.assertEqual(kinds["Ancient"], "high")

    def test_native_access_not_satisfied_by_komplete_kontrol(self) -> None:
        plugins = [
            _plugin(
                "Kontakt",
                "AU",
                "/tmp/Kontakt.component",
                developer="Native Instruments",
                version="7.0.0",
            ),
        ]
        apps = [
            MusicApp(
                name="Komplete Kontrol",
                category="Plugin Manager",
                developer="Native Instruments",
                version="1.0",
                path="/Applications/Komplete Kontrol.app",
                modified="2024-01-01",
            ),
        ]
        report = analyze_insights(plugins, apps)
        guidance = report.by_filter(FILTER_UPDATE_GUIDANCE)
        self.assertEqual(len(guidance), 1)
        self.assertEqual(guidance[0].issue_kind, KIND_MANUAL_UPDATE_CHECK)
        self.assertNotEqual(guidance[0].recommended_action, "open_update_manager")

    def test_native_instruments_native_access_installed(self) -> None:
        plugins = [
            _plugin(
                "Kontakt",
                "AU",
                "/tmp/Kontakt.component",
                developer="Native Instruments",
            ),
        ]
        apps = [
            MusicApp(
                name="Native Access",
                category="Plugin Manager",
                developer="Native Instruments",
                version="1.0",
                path="/Applications/Native Access.app",
                modified="2024-01-01",
            ),
        ]
        report = analyze_insights(plugins, apps)
        guidance = report.by_filter(FILTER_UPDATE_GUIDANCE)
        self.assertEqual(guidance[0].issue_kind, KIND_UPDATE_MANAGER_AVAILABLE)
        self.assertEqual(guidance[0].manager_app_name, "Native Access")
        self.assertIn("Native Access", guidance[0].recommendation)

    def test_izotope_manual_update_when_portal_missing(self) -> None:
        plugins = [
            _plugin("Ozone", "VST3", "/tmp/Ozone.vst3", developer="iZotope", version="11.0.0"),
        ]
        report = analyze_insights(plugins, [])
        guidance = report.by_filter(FILTER_UPDATE_GUIDANCE)
        self.assertEqual(len(guidance), 1)
        self.assertEqual(guidance[0].issue_kind, KIND_MANUAL_UPDATE_CHECK)
        self.assertEqual(guidance[0].recommended_action, "check_vendor_website")

    def test_fabfilter_website_only_not_manager_missing(self) -> None:
        plugins = [_plugin("Pro-Q", "AU", "/tmp/Pro-Q.component", developer="FabFilter")]
        report = analyze_insights(plugins, [])
        guidance = report.update_guidance[0]
        self.assertEqual(guidance.issue_kind, KIND_VENDOR_WEBSITE)

    def test_no_stale_without_modified_date(self) -> None:
        plugins = [_plugin("NoDate", "AU", "/tmp/NoDate.component")]
        report = analyze_insights(plugins)
        self.assertEqual(len(report.stale_plugins), 0)

    def test_version_filter(self) -> None:
        plugins = [
            _plugin("P", "VST3", "/a.vst3", version="1.0"),
            _plugin("P", "AU", "/a.component", version="2.0"),
        ]
        report = analyze_insights(plugins)
        filtered = report.by_filter(FILTER_VERSION_CONFLICT)
        self.assertEqual(len(filtered), len(report.version_conflicts))

    def test_healthy_count_includes_related_paths(self) -> None:
        plugins = [
            _plugin("P", "VST3", "/a.vst3", version="1.0"),
            _plugin("P", "AU", "/a.component", version="2.0"),
            _plugin("Q", "AU", "/q.component", version="1.0"),
        ]
        report = analyze_insights(plugins)
        self.assertEqual(report.version_conflict_products, 1)
        self.assertEqual(report.healthy_count, 0)

    def test_overview_settings_parity_with_plugin_health(self) -> None:
        plugins = [
            _plugin("P", "VST", "/a.vst", developer="FabFilter"),
            _plugin("P", "VST3", "/a.vst3", version="1", developer="FabFilter"),
        ]
        settings = AppSettings(legacy_vst2_sensitivity="Low", ignored_vendors=["FabFilter"])
        opts = insight_options_from_settings(settings)
        report = analyze_insights(plugins, [], **opts)
        self.assertEqual(report.total_plugins, 2)


class VendorRegistryTests(unittest.TestCase):
    def test_ssl_substring_does_not_match_unrelated(self) -> None:
        self.assertIsNone(match_vendor("Russell Audio Labs"))
        self.assertIsNone(match_vendor("Passport Designs"))

    def test_ssl_matches_solid_state_logic(self) -> None:
        entry = match_vendor("Solid State Logic Ltd")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.vendor_key, "ssl")
        self.assertTrue(entry.website_only)

    def test_output_does_not_match_generic_word(self) -> None:
        self.assertIsNone(match_vendor("High Output Audio"))
        self.assertIsNone(match_vendor("Audio Output Module"))

    def test_output_matches_company(self) -> None:
        entry = match_vendor("Output")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.vendor_key, "output")


if __name__ == "__main__":
    unittest.main()
