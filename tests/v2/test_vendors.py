"""Tests for studio_vault.vendors."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from studio_vault.vendors import (
    LICENSE_ILOK,
    LICENSE_SERIAL,
    VENDORS,
    installed_manager,
    match_vendor,
    vendor_by_key,
)


@dataclass
class App:
    name: str


@pytest.mark.parametrize("developer,key", [
    ("Native Instruments GmbH", "native_instruments"),
    ("FabFilter", "fabfilter"),
    ("Waves Audio Ltd.", "waves"),
    ("u-he", "uhe"),
    ("Output", "output"),
    ("Output, Inc", "output"),
])
def test_match_by_developer(developer, key):
    assert match_vendor(developer).key == key


def test_single_word_needs_whole_word():
    assert match_vendor("Microwaves Ltd") is None
    assert match_vendor("Outputs Unlimited") is None


def test_waves_bundle_prefix_and_developer_variant():
    assert match_vendor("", "com.wavesaudio.WaveShell1-VST3.15.0").key == "waves"
    assert match_vendor("Wavesaudio").key == "waves"


def test_bundle_id_wins_over_developer():
    assert match_vendor("Some Reseller", "com.fabfilter.Pro-Q.3").key == "fabfilter"


def test_unknown_vendor():
    assert match_vendor("Tiny Indie Dev", "com.tinyindie.thing") is None
    assert match_vendor("", "") is None


def test_keys_are_unique_and_lookup_works():
    keys = [v.key for v in VENDORS]
    assert len(keys) == len(set(keys))
    assert vendor_by_key("waves").name == "Waves"
    assert vendor_by_key("nope") is None


def test_every_vendor_has_https_download_url():
    assert all(v.download_url.startswith("https://") for v in VENDORS)


def test_license_systems():
    assert vendor_by_key("eventide").license_system == LICENSE_ILOK
    assert vendor_by_key("fabfilter").license_system == LICENSE_SERIAL
    assert vendor_by_key("fabfilter").website_only


def test_installed_manager():
    apps = [App("Logic Pro"), App("Native Access 2")]
    assert installed_manager(vendor_by_key("izotope"), apps) == "Native Access 2"
    assert installed_manager(vendor_by_key("waves"), apps) == ""
    assert installed_manager(vendor_by_key("fabfilter"), apps) == ""


def test_control_app_for_hardware():
    from types import SimpleNamespace as NS
    from studio_vault.vendors import control_app
    apps = [NS(name="SSL 360", category="Hardware Utility", developer="Solid State Logic"),
            NS(name="MOTIV Mix", category="Hardware Utility", developer="Shure"),
            NS(name="Logic Pro", category="DAW", developer="Apple")]
    assert control_app("Solid State Logic", apps) == "SSL 360"
    assert control_app("Shure Inc", apps) == "MOTIV Mix"
    assert control_app("Apple Inc.", apps) == ""          # not a hardware utility
    assert control_app("", apps) == ""
