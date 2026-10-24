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

    def test_usb_host_data_type_fallback(self):
        host = {"SPUSBHostDataType": [{"_name": "USB 3.1 Bus", "_items": [
            {"_name": "USB2.0 Hub", "USBDeviceKeyProductID": "0x5801", "_items": [
                {"_name": "Scarlett 2i2 USB", "USBDeviceKeyProductID": "0x8210",
                 "USBDeviceKeyVendorID": "0x1235", "USBDeviceKeyVendorName": "Focusrite"},
                {"_name": "USB2.0 HID", "USBDeviceKeyProductID": "0x1100", "USBDeviceKeyVendorName": "Realtek"},
            ]},
        ]}]}

        def profiler(data_type, timeout=60):
            if data_type == "SPUSBDataType":
                return {"SPUSBDataType": []}, None
            if data_type == "SPUSBHostDataType":
                return host, None
            return {data_type: []}, None

        with patch.object(sys, "platform", "darwin"), \
             patch("studio_vault.scanners.hardware.run_system_profiler", side_effect=profiler), \
             patch("studio_vault.scanners.midi._scan_core_midi", return_value=([], [], [])):
            result = scan_hardware(debug_log=False)
        assert [(d.name, d.vendor, d.source) for d in result.devices] == [("Scarlett 2i2 USB", "Focusrite", "USB")]

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

    def test_developer_is_never_a_bare_year(self, tmp_path):
        apps = tmp_path / "Applications"
        make_bundle(apps, "Maschine 2.app", {"CFBundleGetInfoString": "Maschine 2, © 2024",
                                             "CFBundleIdentifier": "com.native-instruments.Maschine 2"})
        [app] = scan_music_apps([str(apps)])
        assert app.developer == "Native Instruments"


    def test_music_tools_and_no_uninstallers(self, tmp_path):
        apps = tmp_path / "Applications"
        for name in ("Melodyne.app", "iZotope RX 8 Audio Editor.app", "MPC.app", "Max.app", "XO.app", "Vital.app",
                     "3ds Max.app", "Xojo.app", "Overbridge_Uninstaller.app", "Uninstall_SubBoomBass.app",
                     "Remove Soundtoys.app", "MOTIVMix Uninstaller.app", "Overbridge Engine.app", "Hermes.app", "Cubase13.app"):
            make_bundle(apps, name, {})
        names = {a.name for a in scan_music_apps([str(apps)])}
        assert names == {"Melodyne", "iZotope RX 8 Audio Editor", "MPC", "Max", "XO", "Vital", "Overbridge Engine", "Cubase13"}


class TestDeviceDetails:
    def test_channels_rate_and_connection(self):
        from studio_vault.scanners.hardware import HardwareDevice, device_details
        dev = HardwareDevice("Shure MV7", "Shure Inc", "Audio Interface", "USB", "CoreAudio",
                             raw_metadata={"coreaudio_device_input": 1, "coreaudio_device_output": 2,
                                           "coreaudio_device_srate": 48000})
        assert device_details(dev) == "1 in · 2 out · 48 kHz · USB"

    def test_merged_device_and_44_1(self):
        from studio_vault.scanners.hardware import HardwareDevice, device_details
        dev = HardwareDevice("BiG SiX", "SSL", "Audio Interface", "USB", "CoreAudio, USB",
                             raw_metadata={"merged_sources": ["CoreAudio", "USB"],
                                           "entries": [{"product_id": "0x1"}, {"coreaudio_device_input": 12,
                                                       "coreaudio_device_output": 12, "coreaudio_device_srate": 44100}]})
        assert device_details(dev) == "12 in · 12 out · 44.1 kHz · USB"

    def test_midi_device_without_audio(self):
        from studio_vault.scanners.hardware import HardwareDevice, device_details
        assert device_details(HardwareDevice("mioXL", "iConnectivity", "MIDI Device", "MIDI", "MIDI")) == ""
