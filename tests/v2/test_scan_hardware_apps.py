"""Tests for the hardware and music-app scanners with recorded-style fixtures."""

from __future__ import annotations

import sys
from unittest.mock import patch

from studio_vault.scanners.apps import CATEGORY_DAW, CATEGORY_PLUGIN_MANAGER, scan_music_apps
from studio_vault.scanners.hardware import scan_hardware
from studio_vault.scanners.midi import MidiDevice
from tests.v2.conftest import make_bundle

PROFILER = {
    "SPAudioDataType": {"SPAudioDataType": [{"_name": "coreaudio_device", "_items": [
        {"_name": "Scarlett 2i2 USB", "coreaudio_device_manufacturer": "Focusrite",
         "coreaudio_device_transport": "coreaudio_device_type_usb"},
        {"_name": "MacBook Pro Speakers", "coreaudio_device_manufacturer": "Apple Inc.",
         "coreaudio_device_transport": "coreaudio_device_type_builtin"},
    ]}]},
    "SPMIDIDataType": {"SPMIDIDataType": [
        {"_name": "mio XL", "manufacturer": "iConnectivity"},
        {"_name": "IAC Driver"},
    ]},
    "SPUSBDataType": {"SPUSBDataType": [{"_name": "USB 3.1 Bus", "_items": [
        {"_name": "Scarlett 2i2 USB", "product_id": "0x8210",
         "vendor_id": "0x1235 (Focusrite-Novation)", "manufacturer": "Focusrite"},
        {"_name": "USB Keyboard", "product_id": "0x0001", "manufacturer": "Logitech"},
    ]}]},
}


def _fake_profiler(data_type, timeout=60):
    return PROFILER[data_type], None


class TestScanHardware:
    def test_merges_sources_and_drops_builtin_and_clutter(self):
        with patch.object(sys, "platform", "darwin"), \
             patch("studio_vault.scanners.hardware.run_system_profiler", side_effect=_fake_profiler):
            result = scan_hardware(debug_log=False)
        names = sorted(d.name for d in result.devices)
        assert names == ["Scarlett 2i2 USB", "mio XL"]
        scarlett = next(d for d in result.devices if d.name == "Scarlett 2i2 USB")
        assert scarlett.vendor == "Focusrite"
        assert "CoreAudio" in scarlett.source and "USB" in scarlett.source

    def test_profiler_error_is_reported_not_raised(self):
        def failing(data_type, timeout=60):
            if data_type == "SPMIDIDataType":
                return PROFILER[data_type], None
            return None, f"{data_type}: boom"
        with patch.object(sys, "platform", "darwin"), \
             patch("studio_vault.scanners.hardware.run_system_profiler", side_effect=failing):
            result = scan_hardware(debug_log=False)
        assert any("boom" in e for e in result.errors)
        assert [d.name for d in result.devices] == ["mio XL"]

    def test_core_midi_fallback_when_profiler_has_no_midi(self):
        def no_midi(data_type, timeout=60):
            if data_type == "SPMIDIDataType":
                return {"SPMIDIDataType": []}, None
            return PROFILER[data_type], None

        core = [
            MidiDevice("H90 Pedal", "Eventide", 1, 1, True, "USB", "CoreMIDI"),
            MidiDevice("MicroFreak", "Arturia", 1, 1, False, "USB", "CoreMIDI"),
            MidiDevice("UMP-nettverk", "", 0, 0, True, "Network", "CoreMIDI"),
        ]
        with patch.object(sys, "platform", "darwin"), \
             patch("studio_vault.scanners.hardware.run_system_profiler", side_effect=no_midi), \
             patch("studio_vault.scanners.midi._scan_core_midi", return_value=(core, [], [])):
            result = scan_hardware(debug_log=False)
        midi_names = [d.name for d in result.devices if d.device_type == "MIDI Device"]
        assert midi_names == ["H90 Pedal"]

    def test_non_macos(self):
        with patch.object(sys, "platform", "linux"):
            assert scan_hardware(debug_log=False).errors


class TestScanMusicApps:
    def test_finds_known_apps_only(self, tmp_path):
        apps = tmp_path / "Applications"
        make_bundle(apps, "Ableton Live 12 Suite.app",
                    {"CFBundleShortVersionString": "12.1", "CFBundleIdentifier": "com.ableton.live"})
        make_bundle(apps / "Native Instruments", "Native Access.app", {"CFBundleShortVersionString": "3.14"})
        make_bundle(apps, "Safari.app", {})
        found = scan_music_apps([str(apps)])
        by_name = {a.name: a for a in found}
        assert set(by_name) == {"Ableton Live 12 Suite", "Native Access"}
        assert by_name["Ableton Live 12 Suite"].category == CATEGORY_DAW
        assert by_name["Ableton Live 12 Suite"].version == "12.1"
        assert by_name["Native Access"].category == CATEGORY_PLUGIN_MANAGER
