"""Tests for studio_vault.handoff.match (one plug-in matcher for Handoff and Project check)."""

from __future__ import annotations

import pytest

from studio_vault.handoff.match import INSTALLED, MISSING, OTHER_FORMAT, PluginIndex, key

MAC = PluginIndex([
    ("Pro-C 2", "AU", "FabFilter"), ("FabFilter Pro-Q 4", "VST3", ""), ("FabFilter Pro-L 2", "AU", "FabFilter"),
    ("SPAN", "AU", "Voxengo"), ("Serum", "VST", ""), ("ValhallaVintageVerb", "VST3", ""), ("Kickstart 2", "VST3", ""),
    ("Compressor", "AU", "Acme"),
])


@pytest.mark.parametrize("name,fmt,vendor,status", [
    ("Pro-C 2", "AU", "FabFilter", INSTALLED),
    ("Pro-Q 4", "VST3", "", INSTALLED),                 # bundle named "FabFilter Pro-Q 4"
    ("FF Pro-L 2", "AU", "FabFilter", INSTALLED),       # vendor abbreviated
    ("Voxengo SPAN", "VST", "", OTHER_FORMAT),          # vendor in front; they have the AU
    ("Serum_x64", "VST", "", INSTALLED),
    ("Serum VST3", "VST3", "", OTHER_FORMAT),
    ("Verb", "VST3", "", MISSING),                      # no generic suffix match any more
    ("Kickstart", "VST3", "", MISSING),                 # Kickstart 1 is another product
    ("Compressor", "AU", "Other Co", MISSING),          # same AU name, other vendor
    ("Compressor", "AU", "Acme", INSTALLED),
    ("Sylenth1", "VST", "", MISSING),
])
def test_status(name, fmt, vendor, status):
    assert MAC.status(name, fmt, vendor)[0] == status


def test_other_format_lists_what_they_have():
    assert MAC.status("Pro-C 2", "VST3", "FabFilter") == (OTHER_FORMAT, ["AU"])


def test_key():
    assert key("Serum_x64") == key("serum-64bit") == key("Serum VST3") == "serum"
    assert key("") == ""


def test_short_vendor_prefix_is_not_stripped():
    idx = PluginIndex([("IK Kick", "VST3", ""), ("Thing", "AU", "IK")])
    assert idx.status("Kick", "VST3")[0] == MISSING
