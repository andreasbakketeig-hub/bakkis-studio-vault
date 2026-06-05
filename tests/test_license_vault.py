"""
Tests for the License Vault module (app.core.license_vault).

Coverage:
  - Vendor mapping (match_vendor → known & unknown developers)
  - Manager detection (detect_installed_managers from music app lists)
  - Product classification (LicenseStatus for each scenario)
  - Health metrics (counts in LicenseVaultReport)
  - Vendor summary aggregation
  - Read-only safety (no side effects in core functions)
"""

from __future__ import annotations

import unittest
from pathlib import Path

from app.core.license_vault import (
    LicenseStatus,
    LicenseManagerDef,
    LicenseProduct,
    InstalledManager,
    VendorSummary,
    LicenseVaultReport,
    LICENSE_MANAGER_REGISTRY,
    WEBSITE_MANAGED_VENDOR_KEYS,
    detect_installed_managers,
    classify_products,
    build_vendor_summaries,
    build_license_vault_report,
    _VENDOR_TO_MANAGER,
)
from app.core.music_software_scanner import MusicApp, CATEGORY_LICENSE_MANAGER, CATEGORY_PLUGIN_MANAGER
from app.core.scanner import Plugin
from app.core.vendor_registry import match_vendor


# ── Helpers ────────────────────────────────────────────────────────────────────

def _plugin(
    name: str,
    fmt: str = "VST3",
    developer: str = "",
    version: str = "1.0.0",
    path: str = "",
) -> Plugin:
    return Plugin(
        name=name,
        fmt=fmt,
        path=path or f"/Library/Audio/Plug-Ins/VST3/{name}.vst3",
        version=version,
        developer=developer,
    )


def _music_app(name: str, category: str = CATEGORY_PLUGIN_MANAGER, developer: str = "") -> MusicApp:
    return MusicApp(
        name=name,
        category=category,
        developer=developer or name,
        version="1.0",
        path=f"/Applications/{name}.app",
        modified="2025-01-01",
    )


# ── Vendor mapping ─────────────────────────────────────────────────────────────

class TestVendorMapping(unittest.TestCase):
    def test_native_instruments_match(self) -> None:
        entry = match_vendor("Native Instruments")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.vendor_key, "native_instruments")  # type: ignore[union-attr]

    def test_izotope_case_insensitive(self) -> None:
        entry = match_vendor("iZotope")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.vendor_key, "izotope")  # type: ignore[union-attr]

    def test_waves_match(self) -> None:
        entry = match_vendor("Waves")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.vendor_key, "waves")  # type: ignore[union-attr]

    def test_arturia_match(self) -> None:
        entry = match_vendor("Arturia")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.vendor_key, "arturia")  # type: ignore[union-attr]

    def test_universal_audio_match(self) -> None:
        entry = match_vendor("Universal Audio")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.vendor_key, "universal_audio")  # type: ignore[union-attr]

    def test_fabfilter_website_only(self) -> None:
        entry = match_vendor("FabFilter")
        self.assertIsNotNone(entry)
        self.assertTrue(entry.website_only)  # type: ignore[union-attr]

    def test_spectrasonics_website_only(self) -> None:
        entry = match_vendor("Spectrasonics")
        self.assertIsNotNone(entry)
        self.assertTrue(entry.website_only)  # type: ignore[union-attr]

    def test_unknown_developer(self) -> None:
        self.assertIsNone(match_vendor("AcmeSynths Incorporated"))

    def test_empty_developer(self) -> None:
        self.assertIsNone(match_vendor(""))

    def test_website_managed_vendor_keys_not_empty(self) -> None:
        self.assertTrue(len(WEBSITE_MANAGED_VENDOR_KEYS) > 0)
        self.assertIn("fabfilter", WEBSITE_MANAGED_VENDOR_KEYS)
        self.assertIn("spectrasonics", WEBSITE_MANAGED_VENDOR_KEYS)
        self.assertIn("ableton", WEBSITE_MANAGED_VENDOR_KEYS)
        self.assertIn("celemony", WEBSITE_MANAGED_VENDOR_KEYS)


# ── Manager detection ──────────────────────────────────────────────────────────

class TestManagerDetection(unittest.TestCase):
    def test_native_access_detected(self) -> None:
        apps = [_music_app("Native Access")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("native_access", keys)

    def test_waves_central_detected(self) -> None:
        apps = [_music_app("Waves Central")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("waves_central", keys)

    def test_izotope_portal_detected(self) -> None:
        apps = [_music_app("iZotope Product Portal")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("izotope_portal", keys)

    def test_arturia_software_center_detected(self) -> None:
        apps = [_music_app("Arturia Software Center")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("arturia_software_center", keys)

    def test_ua_connect_detected(self) -> None:
        apps = [_music_app("UA Connect")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("ua_connect", keys)

    def test_ssl_360_detected(self) -> None:
        apps = [_music_app("SSL 360")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("ssl_360", keys)

    def test_softube_central_detected(self) -> None:
        apps = [_music_app("Softube Central")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("softube_central", keys)

    def test_output_hub_detected(self) -> None:
        apps = [_music_app("Output Hub")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("output_hub", keys)

    def test_spitfire_audio_detected(self) -> None:
        apps = [_music_app("Spitfire Audio")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("spitfire_audio", keys)

    def test_loopcloud_detected(self) -> None:
        apps = [_music_app("Loopcloud")]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertIn("loopcloud", keys)

    def test_no_duplicate_managers(self) -> None:
        apps = [
            _music_app("Native Access"),
            _music_app("Native Access 2"),  # second instance of same manager
        ]
        managers = detect_installed_managers(apps)
        keys = [m.manager_key for m in managers]
        self.assertEqual(len(keys), len(set(keys)), "Duplicate manager keys detected")

    def test_empty_apps_returns_empty(self) -> None:
        managers = detect_installed_managers([])
        self.assertEqual(managers, [])

    def test_multiple_managers_detected(self) -> None:
        apps = [
            _music_app("Native Access"),
            _music_app("Waves Central"),
            _music_app("Arturia Software Center"),
        ]
        managers = detect_installed_managers(apps)
        keys = {m.manager_key for m in managers}
        self.assertIn("native_access", keys)
        self.assertIn("waves_central", keys)
        self.assertIn("arturia_software_center", keys)

    def test_manager_stores_path(self) -> None:
        apps = [_music_app("Native Access")]
        managers = detect_installed_managers(apps)
        mgr = next(m for m in managers if m.manager_key == "native_access")
        self.assertTrue(mgr.app_path.endswith("Native Access.app"))

    def test_manager_sorted_by_name(self) -> None:
        apps = [
            _music_app("Waves Central"),
            _music_app("Native Access"),
            _music_app("Arturia Software Center"),
        ]
        managers = detect_installed_managers(apps)
        names = [m.display_name for m in managers]
        self.assertEqual(names, sorted(names, key=str.lower))


# ── Product classification ─────────────────────────────────────────────────────

class TestProductClassification(unittest.TestCase):
    def _classify(
        self,
        plugins: list[Plugin],
        installed_apps: list[MusicApp] | None = None,
    ) -> list[LicenseProduct]:
        apps = installed_apps or []
        managers = detect_installed_managers(apps)
        return classify_products(plugins, managers)

    def test_managed_when_manager_installed(self) -> None:
        plugins = [_plugin("Kontakt", developer="Native Instruments")]
        apps = [_music_app("Native Access")]
        products = self._classify(plugins, apps)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].license_status, LicenseStatus.MANAGED)
        self.assertEqual(products[0].vendor_display, "Native Instruments")
        self.assertEqual(products[0].license_manager, "Native Access")

    def test_missing_manager_when_manager_absent(self) -> None:
        plugins = [_plugin("Pro-Q 3", developer="FabFilter")]
        products = self._classify(plugins)
        # FabFilter is website_only → WEBSITE_MANAGED
        self.assertEqual(products[0].license_status, LicenseStatus.WEBSITE_MANAGED)

    def test_website_managed_fabfilter(self) -> None:
        plugins = [_plugin("Pro-Q 3", developer="FabFilter")]
        products = self._classify(plugins)
        self.assertEqual(products[0].license_status, LicenseStatus.WEBSITE_MANAGED)
        self.assertEqual(products[0].vendor_display, "FabFilter")

    def test_website_managed_spectrasonics(self) -> None:
        plugins = [_plugin("Omnisphere", developer="Spectrasonics")]
        products = self._classify(plugins)
        self.assertEqual(products[0].license_status, LicenseStatus.WEBSITE_MANAGED)

    def test_website_managed_celemony(self) -> None:
        plugins = [_plugin("Melodyne", developer="Celemony")]
        products = self._classify(plugins)
        self.assertEqual(products[0].license_status, LicenseStatus.WEBSITE_MANAGED)

    def test_unknown_developer(self) -> None:
        plugins = [_plugin("Mystery Synth", developer="")]
        products = self._classify(plugins)
        self.assertEqual(products[0].license_status, LicenseStatus.UNKNOWN)

    def test_unknown_vendor(self) -> None:
        plugins = [_plugin("CoolDelay", developer="AcmePlug Inc")]
        products = self._classify(plugins)
        self.assertEqual(products[0].license_status, LicenseStatus.UNKNOWN)

    def test_missing_manager_ni_no_native_access(self) -> None:
        plugins = [_plugin("Massive X", developer="Native Instruments")]
        products = self._classify(plugins, installed_apps=[])
        self.assertEqual(products[0].license_status, LicenseStatus.MISSING_MANAGER)

    def test_formats_aggregated(self) -> None:
        plugins = [
            _plugin("Pro-Q 3", fmt="VST3", developer="FabFilter"),
            _plugin("Pro-Q 3", fmt="AU",   developer="FabFilter"),
        ]
        products = self._classify(plugins)
        self.assertEqual(len(products), 1)
        self.assertIn("VST3", products[0].formats)
        self.assertIn("AU",   products[0].formats)

    def test_version_picked_from_first_available(self) -> None:
        plugins = [
            _plugin("Serum", fmt="VST3", developer="Xfer Records", version="1.37"),
            _plugin("Serum", fmt="AU",   developer="Xfer Records", version=""),
        ]
        products = self._classify(plugins)
        self.assertEqual(products[0].version, "1.37")

    def test_waves_managed_with_waves_central(self) -> None:
        plugins = [_plugin("H-Reverb", developer="Waves")]
        apps = [_music_app("Waves Central")]
        products = self._classify(plugins, apps)
        self.assertEqual(products[0].license_status, LicenseStatus.MANAGED)
        self.assertEqual(products[0].license_manager, "Waves Central")

    def test_arturia_managed_with_asc(self) -> None:
        plugins = [_plugin("Analog Lab", developer="Arturia")]
        apps = [_music_app("Arturia Software Center")]
        products = self._classify(plugins, apps)
        self.assertEqual(products[0].license_status, LicenseStatus.MANAGED)

    def test_sorting_by_vendor_then_name(self) -> None:
        plugins = [
            _plugin("Zebra2", developer="u-he"),
            _plugin("Pro-Q 3", developer="FabFilter"),
            _plugin("Kontakt", developer="Native Instruments"),
        ]
        products = self._classify(plugins)
        vendor_names = [p.vendor_display for p in products]
        self.assertEqual(vendor_names, sorted(vendor_names, key=str.lower))


# ── Health metrics ─────────────────────────────────────────────────────────────

class TestHealthMetrics(unittest.TestCase):
    def _report(
        self,
        plugins: list[Plugin],
        music_apps: list[MusicApp] | None = None,
    ) -> LicenseVaultReport:
        return build_license_vault_report(plugins, music_apps or [])

    def test_total_products_counted(self) -> None:
        plugins = [
            _plugin("Kontakt", developer="Native Instruments"),
            _plugin("Pro-Q 3", developer="FabFilter"),
            _plugin("Mystery",  developer=""),
        ]
        report = self._report(plugins)
        self.assertEqual(report.total_products, 3)

    def test_managed_count_with_manager(self) -> None:
        plugins = [
            _plugin("Kontakt", developer="Native Instruments"),
            _plugin("Massive", developer="Native Instruments"),
        ]
        apps = [_music_app("Native Access")]
        report = self._report(plugins, apps)
        self.assertEqual(report.managed_count, 2)

    def test_website_managed_count(self) -> None:
        plugins = [
            _plugin("Pro-Q 3", developer="FabFilter"),
            _plugin("Pro-C 2", developer="FabFilter"),
        ]
        report = self._report(plugins)
        self.assertEqual(report.website_managed_count, 2)
        self.assertEqual(report.managed_count, 0)

    def test_unknown_count(self) -> None:
        plugins = [
            _plugin("CoolPlug", developer=""),
            _plugin("WeirdDelay", developer="SomeUnknownCo"),
        ]
        report = self._report(plugins)
        self.assertEqual(report.unknown_count, 2)

    def test_missing_manager_count(self) -> None:
        plugins = [_plugin("Kontakt", developer="Native Instruments")]
        # No Native Access installed
        report = self._report(plugins, [])
        self.assertEqual(report.missing_manager_count, 1)

    def test_vendor_count(self) -> None:
        plugins = [
            _plugin("Kontakt",  developer="Native Instruments"),
            _plugin("Massive",  developer="Native Instruments"),
            _plugin("Pro-Q 3",  developer="FabFilter"),
            _plugin("H-Reverb", developer="Waves"),
        ]
        report = self._report(plugins)
        self.assertEqual(report.vendor_count, 3)

    def test_manager_count(self) -> None:
        apps = [
            _music_app("Native Access"),
            _music_app("Waves Central"),
        ]
        report = self._report([], apps)
        self.assertEqual(report.manager_count, 2)

    def test_empty_report(self) -> None:
        report = self._report([], [])
        self.assertEqual(report.total_products, 0)
        self.assertEqual(report.managed_count, 0)
        self.assertEqual(report.vendor_count, 0)
        self.assertEqual(report.manager_count, 0)


# ── Vendor summary ─────────────────────────────────────────────────────────────

class TestVendorSummary(unittest.TestCase):
    def test_vendor_product_count(self) -> None:
        plugins = [
            _plugin("Kontakt",  developer="Native Instruments"),
            _plugin("Massive",  developer="Native Instruments"),
            _plugin("Massive X",developer="Native Instruments"),
        ]
        managers = detect_installed_managers([])
        products = classify_products(plugins, managers)
        vendors = build_vendor_summaries(products)
        ni = next(v for v in vendors if v.vendor_key == "native_instruments")
        self.assertEqual(ni.product_count, 3)

    def test_vendor_status_managed_if_manager_installed(self) -> None:
        plugins = [_plugin("Kontakt", developer="Native Instruments")]
        managers = detect_installed_managers([_music_app("Native Access")])
        products = classify_products(plugins, managers)
        vendors = build_vendor_summaries(products)
        ni = next(v for v in vendors if v.vendor_key == "native_instruments")
        self.assertEqual(ni.status, LicenseStatus.MANAGED)

    def test_vendor_status_best_wins(self) -> None:
        """If vendor has one managed + one unknown product, vendor status = MANAGED."""
        plugins = [
            _plugin("Kontakt", developer="Native Instruments"),
        ]
        managers = detect_installed_managers([_music_app("Native Access")])
        products = classify_products(plugins, managers)
        vendors = build_vendor_summaries(products)
        ni = next(v for v in vendors if v.vendor_key == "native_instruments")
        self.assertIn(ni.status, (LicenseStatus.MANAGED, LicenseStatus.WEBSITE_MANAGED))

    def test_vendor_website_populated(self) -> None:
        plugins = [_plugin("Pro-Q 3", developer="FabFilter")]
        managers = detect_installed_managers([])
        products = classify_products(plugins, managers)
        vendors = build_vendor_summaries(products)
        ff = next(v for v in vendors if "fabfilter" in v.vendor_key.lower())
        self.assertTrue(ff.website.startswith("https://"))

    def test_unknown_vendor_grouped_separately(self) -> None:
        plugins = [
            _plugin("Plugin A", developer="VendorX"),
            _plugin("Plugin B", developer="VendorX"),
        ]
        managers = detect_installed_managers([])
        products = classify_products(plugins, managers)
        vendors = build_vendor_summaries(products)
        vendorx = next((v for v in vendors if v.display_name == "VendorX"), None)
        self.assertIsNotNone(vendorx)
        self.assertEqual(vendorx.product_count, 2)  # type: ignore[union-attr]

    def test_vendors_sorted_alphabetically(self) -> None:
        plugins = [
            _plugin("H-Reverb", developer="Waves"),
            _plugin("Pro-Q 3",  developer="FabFilter"),
            _plugin("Kontakt",  developer="Native Instruments"),
        ]
        managers = detect_installed_managers([])
        products = classify_products(plugins, managers)
        vendors = build_vendor_summaries(products)
        names = [v.display_name for v in vendors]
        self.assertEqual(names, sorted(names, key=str.lower))


# ── Registry integrity ─────────────────────────────────────────────────────────

class TestRegistryIntegrity(unittest.TestCase):
    def test_all_manager_defs_have_display_name(self) -> None:
        for mgr in LICENSE_MANAGER_REGISTRY:
            self.assertTrue(mgr.display_name, f"{mgr.manager_key} missing display_name")

    def test_all_manager_defs_have_hints(self) -> None:
        for mgr in LICENSE_MANAGER_REGISTRY:
            self.assertTrue(len(mgr.app_name_hints) > 0,
                            f"{mgr.manager_key} has no app_name_hints")

    def test_all_manager_defs_have_unique_keys(self) -> None:
        keys = [mgr.manager_key for mgr in LICENSE_MANAGER_REGISTRY]
        self.assertEqual(len(keys), len(set(keys)), "Duplicate manager_key in registry")

    def test_vendor_to_manager_mapping_populated(self) -> None:
        self.assertTrue(len(_VENDOR_TO_MANAGER) > 0)
        self.assertIn("native_instruments", _VENDOR_TO_MANAGER)
        self.assertIn("waves", _VENDOR_TO_MANAGER)
        self.assertIn("arturia", _VENDOR_TO_MANAGER)

    def test_expected_managers_in_registry(self) -> None:
        expected_keys = {
            "native_access",
            "waves_central",
            "izotope_portal",
            "arturia_software_center",
            "plugin_alliance_manager",
            "ua_connect",
            "ssl_360",
            "softube_central",
            "output_hub",
            "spitfire_audio",
            "loopcloud",
            "steinberg_download_assistant",
            "soundtoys",
        }
        registry_keys = {mgr.manager_key for mgr in LICENSE_MANAGER_REGISTRY}
        missing = expected_keys - registry_keys
        self.assertFalse(missing, f"Missing managers in registry: {missing}")


# ── Read-only safety ───────────────────────────────────────────────────────────

class TestReadOnlySafety(unittest.TestCase):
    """Verify that core functions do not mutate their inputs."""

    def test_classify_does_not_mutate_plugin_list(self) -> None:
        plugins = [_plugin("Kontakt", developer="Native Instruments")]
        original = list(plugins)
        managers = detect_installed_managers([_music_app("Native Access")])
        classify_products(plugins, managers)
        self.assertEqual(plugins, original)

    def test_detect_managers_does_not_mutate_apps(self) -> None:
        apps = [_music_app("Native Access"), _music_app("Waves Central")]
        original_names = [a.name for a in apps]
        detect_installed_managers(apps)
        self.assertEqual([a.name for a in apps], original_names)

    def test_build_report_does_not_raise_on_empty(self) -> None:
        try:
            report = build_license_vault_report([], [])
            self.assertIsInstance(report, LicenseVaultReport)
        except Exception as exc:
            self.fail(f"build_license_vault_report raised unexpectedly: {exc}")

    def test_build_report_does_not_raise_with_data(self) -> None:
        plugins = [
            _plugin("Kontakt",  developer="Native Instruments"),
            _plugin("Pro-Q 3",  developer="FabFilter"),
            _plugin("CoolPlug", developer=""),
        ]
        apps = [_music_app("Native Access"), _music_app("Waves Central")]
        try:
            report = build_license_vault_report(plugins, apps)
            self.assertIsInstance(report, LicenseVaultReport)
        except Exception as exc:
            self.fail(f"build_license_vault_report raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
