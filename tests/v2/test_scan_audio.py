"""
Tests for the Audio Devices module.

Coverage:
  - AudioDevice dataclass: labels, row, copy_text, csv_row
  - AudioScanResult: aggregation properties
  - _parse_channels: valid, zero, negative, non-numeric
  - _is_yes: affirmative variants
  - _humanise_transport: known and unknown tokens
  - _parse_device: valid item, missing name → None
  - _extract_items: correct envelope unwrapping
  - export_csv: writes correct header + rows to a temp file
  - Read-only: scan_audio_devices returns AudioScanResult on non-macOS
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio_vault.scanners.audio import (
    CSV_HEADERS,
    AudioDevice,
    AudioScanResult,
    _extract_items,
    _humanise_transport,
    _is_yes,
    _parse_channels,
    _parse_device,
    export_csv,
    scan_audio_devices,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_device(
    name: str = "Scarlett 2i2",
    manufacturer: str = "Focusrite",
    input_channels: int = 2,
    output_channels: int = 2,
    is_default_input: bool = False,
    is_default_output: bool = False,
    transport: str = "USB",
    is_connected: bool = True,
) -> AudioDevice:
    return AudioDevice(
        name=name,
        manufacturer=manufacturer,
        input_channels=input_channels,
        output_channels=output_channels,
        is_default_input=is_default_input,
        is_default_output=is_default_output,
        transport=transport,
        is_connected=is_connected,
    )


def _make_sp_item(**overrides: object) -> dict:
    base = {
        "_name": "Test Device",
        "coreaudio_device_manufacturer": "ACME Audio",
        "coreaudio_device_transport": "coreaudio_device_type_usb",
        "coreaudio_device_input": "2",
        "coreaudio_device_output": "2",
        "coreaudio_default_audio_input_device": "no",
        "coreaudio_default_audio_output_device": "no",
    }
    base.update(overrides)
    return base


# ── AudioDevice dataclass ─────────────────────────────────────────────────────

class TestAudioDeviceLabels(unittest.TestCase):

    def test_status_connected(self):
        d = _make_device(is_connected=True)
        self.assertEqual(d.status_label, "Connected")

    def test_status_disconnected(self):
        d = _make_device(is_connected=False)
        self.assertEqual(d.status_label, "Disconnected")

    def test_default_input_yes(self):
        d = _make_device(is_default_input=True)
        self.assertEqual(d.default_input_label, "✓")

    def test_default_input_no(self):
        d = _make_device(is_default_input=False)
        self.assertEqual(d.default_input_label, "—")

    def test_default_output_yes(self):
        d = _make_device(is_default_output=True)
        self.assertEqual(d.default_output_label, "✓")

    def test_default_output_no(self):
        d = _make_device(is_default_output=False)
        self.assertEqual(d.default_output_label, "—")

    def test_input_channels_positive(self):
        d = _make_device(input_channels=4)
        self.assertEqual(d.input_channels_label, "4")

    def test_input_channels_zero(self):
        d = _make_device(input_channels=0)
        self.assertEqual(d.input_channels_label, "—")

    def test_output_channels_positive(self):
        d = _make_device(output_channels=6)
        self.assertEqual(d.output_channels_label, "6")

    def test_output_channels_zero(self):
        d = _make_device(output_channels=0)
        self.assertEqual(d.output_channels_label, "—")


class TestAudioDeviceRow(unittest.TestCase):

    def test_row_length(self):
        d = _make_device()
        self.assertEqual(len(d.row), 8)

    def test_row_name(self):
        d = _make_device(name="Apollo Twin")
        self.assertEqual(d.row[0], "Apollo Twin")

    def test_row_channels(self):
        d = _make_device(input_channels=2, output_channels=4)
        self.assertEqual(d.row[1], "2")   # inputs
        self.assertEqual(d.row[2], "4")   # outputs

    def test_row_defaults(self):
        d = _make_device(is_default_input=True, is_default_output=False)
        self.assertEqual(d.row[3], "✓")
        self.assertEqual(d.row[4], "—")

    def test_row_manufacturer_fallback(self):
        d = _make_device(manufacturer="")
        self.assertEqual(d.row[5], "—")

    def test_row_transport_fallback(self):
        d = _make_device(transport="")
        self.assertEqual(d.row[6], "—")

    def test_row_status(self):
        d = _make_device(is_connected=True)
        self.assertEqual(d.row[7], "Connected")


class TestAudioDeviceCopyText(unittest.TestCase):

    def test_copy_text_contains_name(self):
        d = _make_device(name="RME Babyface Pro")
        self.assertIn("RME Babyface Pro", d.copy_text)

    def test_copy_text_contains_channels(self):
        d = _make_device(input_channels=2, output_channels=4)
        self.assertIn("2", d.copy_text)
        self.assertIn("4", d.copy_text)

    def test_copy_text_default_input(self):
        d = _make_device(is_default_input=True)
        self.assertIn("Yes", d.copy_text)

    def test_copy_text_is_multiline(self):
        d = _make_device()
        lines = d.copy_text.splitlines()
        self.assertGreater(len(lines), 4)


class TestAudioDeviceCsvRow(unittest.TestCase):

    def test_csv_row_length_matches_headers(self):
        d = _make_device()
        self.assertEqual(len(d.csv_row), len(CSV_HEADERS))

    def test_csv_row_name(self):
        d = _make_device(name="Focusrite Scarlett")
        self.assertEqual(d.csv_row[0], "Focusrite Scarlett")

    def test_csv_row_default_yes(self):
        d = _make_device(is_default_input=True, is_default_output=True)
        self.assertEqual(d.csv_row[5], "Yes")
        self.assertEqual(d.csv_row[6], "Yes")

    def test_csv_row_default_no(self):
        d = _make_device(is_default_input=False, is_default_output=False)
        self.assertEqual(d.csv_row[5], "No")
        self.assertEqual(d.csv_row[6], "No")


# ── AudioScanResult aggregation ───────────────────────────────────────────────

class TestAudioScanResult(unittest.TestCase):

    def setUp(self):
        self.d_input_output = _make_device(
            name="Interface A", input_channels=2, output_channels=2,
            is_default_input=True,
        )
        self.d_output_only = _make_device(
            name="Speakers B", input_channels=0, output_channels=2,
            is_default_output=True,
        )
        self.d_input_only = _make_device(
            name="Microphone C", input_channels=1, output_channels=0,
        )
        self.result = AudioScanResult(
            devices=[self.d_input_output, self.d_output_only, self.d_input_only],
        )

    def test_total(self):
        self.assertEqual(self.result.total, 3)

    def test_input_count(self):
        # d_input_output + d_input_only have input channels
        self.assertEqual(self.result.input_count, 2)

    def test_output_count(self):
        # d_input_output + d_output_only have output channels
        self.assertEqual(self.result.output_count, 2)

    def test_default_input(self):
        self.assertEqual(self.result.default_input, self.d_input_output)

    def test_default_output(self):
        self.assertEqual(self.result.default_output, self.d_output_only)

    def test_empty_result(self):
        r = AudioScanResult()
        self.assertEqual(r.total, 0)
        self.assertEqual(r.input_count, 0)
        self.assertEqual(r.output_count, 0)
        self.assertIsNone(r.default_input)
        self.assertIsNone(r.default_output)


# ── _parse_channels ───────────────────────────────────────────────────────────

class TestParseChannels(unittest.TestCase):

    def test_integer_string(self):
        self.assertEqual(_parse_channels("2"), 2)

    def test_zero_string(self):
        self.assertEqual(_parse_channels("0"), 0)

    def test_none(self):
        self.assertEqual(_parse_channels(None), 0)

    def test_non_numeric(self):
        self.assertEqual(_parse_channels("n/a"), 0)

    def test_negative_clamped(self):
        self.assertEqual(_parse_channels("-1"), 0)

    def test_integer_value(self):
        self.assertEqual(_parse_channels(4), 4)

    def test_whitespace(self):
        self.assertEqual(_parse_channels("  6  "), 6)


# ── _is_yes ───────────────────────────────────────────────────────────────────

class TestIsYes(unittest.TestCase):

    def test_yes(self):
        self.assertTrue(_is_yes("yes"))

    def test_yes_mixed_case(self):
        self.assertTrue(_is_yes("Yes"))

    def test_true(self):
        self.assertTrue(_is_yes("true"))

    def test_one(self):
        self.assertTrue(_is_yes("1"))

    def test_no(self):
        self.assertFalse(_is_yes("no"))

    def test_none(self):
        self.assertFalse(_is_yes(None))

    def test_empty(self):
        self.assertFalse(_is_yes(""))

    def test_whitespace_yes(self):
        self.assertTrue(_is_yes("  yes  "))


# ── _humanise_transport ────────────────────────────────────────────────────────

class TestHumaniseTransport(unittest.TestCase):

    def test_strips_prefix(self):
        result = _humanise_transport("coreaudio_device_type_firewire")
        self.assertEqual(result, "Firewire")

    def test_empty_string(self):
        self.assertEqual(_humanise_transport(""), "Unknown")

    def test_unknown_token(self):
        result = _humanise_transport("some_random_token")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


# ── _parse_device ─────────────────────────────────────────────────────────────

class TestParseDevice(unittest.TestCase):

    def test_valid_item(self):
        item = _make_sp_item()
        dev = _parse_device(item)
        self.assertIsNotNone(dev)
        self.assertEqual(dev.name, "Test Device")
        self.assertEqual(dev.manufacturer, "ACME Audio")
        self.assertEqual(dev.transport, "USB")
        self.assertEqual(dev.input_channels, 2)
        self.assertEqual(dev.output_channels, 2)
        self.assertFalse(dev.is_default_input)
        self.assertFalse(dev.is_default_output)
        self.assertTrue(dev.is_connected)

    def test_missing_name_returns_none(self):
        item = _make_sp_item(**{"_name": ""})
        self.assertIsNone(_parse_device(item))

    def test_none_name_returns_none(self):
        item = _make_sp_item(**{"_name": None})
        self.assertIsNone(_parse_device(item))

    def test_default_input_flag(self):
        item = _make_sp_item(**{"coreaudio_default_audio_input_device": "yes"})
        dev = _parse_device(item)
        self.assertTrue(dev.is_default_input)

    def test_default_output_flag(self):
        item = _make_sp_item(**{"coreaudio_default_audio_output_device": "yes"})
        dev = _parse_device(item)
        self.assertTrue(dev.is_default_output)

    def test_builtin_transport(self):
        item = _make_sp_item(**{"coreaudio_device_transport": "coreaudio_device_type_builtin"})
        dev = _parse_device(item)
        self.assertEqual(dev.transport, "Built-in")

    def test_zero_channels(self):
        item = _make_sp_item(**{
            "coreaudio_device_input": "0",
            "coreaudio_device_output": "0",
        })
        dev = _parse_device(item)
        self.assertEqual(dev.input_channels, 0)
        self.assertEqual(dev.output_channels, 0)

    def test_raw_metadata_stored(self):
        item = _make_sp_item()
        dev = _parse_device(item)
        self.assertIsNotNone(dev.raw_metadata)
        self.assertEqual(dev.raw_metadata.get("_name"), "Test Device")


# ── _extract_items ────────────────────────────────────────────────────────────

class TestExtractItems(unittest.TestCase):

    def test_extracts_list(self):
        payload = {"SPAudioDataType": [{"_name": "Dev A"}, {"_name": "Dev B"}]}
        items = _extract_items(payload)
        self.assertEqual(len(items), 2)

    def test_empty_list(self):
        payload = {"SPAudioDataType": []}
        self.assertEqual(_extract_items(payload), [])

    def test_none_payload(self):
        self.assertEqual(_extract_items(None), [])

    def test_filters_non_dict(self):
        payload = {"SPAudioDataType": [{"_name": "Good"}, "bad_string", 42]}
        items = _extract_items(payload)
        self.assertEqual(len(items), 1)


# ── export_csv ────────────────────────────────────────────────────────────────

class TestExportCsv(unittest.TestCase):

    def setUp(self):
        self.devices = [
            _make_device(
                name="Scarlett 2i2",
                manufacturer="Focusrite",
                input_channels=2,
                output_channels=2,
                is_default_input=True,
                is_default_output=False,
                transport="USB",
            ),
            _make_device(
                name="MacBook Speakers",
                manufacturer="Apple",
                input_channels=0,
                output_channels=2,
                is_default_input=False,
                is_default_output=True,
                transport="Built-in",
            ),
        ]

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "test_export.csv")
            export_csv(self.devices, dest_path=dest)
            self.assertTrue(Path(dest).exists())

    def test_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "out.csv")
            returned = export_csv(self.devices, dest_path=dest)
            self.assertEqual(returned, dest)

    def test_header_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "out.csv")
            export_csv(self.devices, dest_path=dest)
            with open(dest, newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                header = next(reader)
            self.assertEqual(header, CSV_HEADERS)

    def test_data_rows_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "out.csv")
            export_csv(self.devices, dest_path=dest)
            with open(dest, newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            # header + 2 data rows
            self.assertEqual(len(rows), 3)

    def test_device_name_in_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "out.csv")
            export_csv(self.devices, dest_path=dest)
            content = Path(dest).read_text(encoding="utf-8")
            self.assertIn("Scarlett 2i2", content)
            self.assertIn("MacBook Speakers", content)

    def test_default_flags_in_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / "out.csv")
            export_csv(self.devices, dest_path=dest)
            content = Path(dest).read_text(encoding="utf-8")
            self.assertIn("Yes", content)


# ── scan_audio_devices — platform guard ───────────────────────────────────────

class TestScanAudioDevicesPlatformGuard(unittest.TestCase):

    @unittest.skipIf(sys.platform == "darwin", "Runs natively on macOS — skip mock")
    def test_non_macos_returns_error(self):
        with patch("studio_vault.scanners.audio.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = scan_audio_devices()
        self.assertIsInstance(result, AudioScanResult)
        self.assertTrue(any("macOS" in e for e in result.errors))

    def test_returns_audio_scan_result(self):
        with patch("studio_vault.scanners.audio.run_system_profiler") as mock_sp:
            mock_sp.return_value = (
                {"SPAudioDataType": [_make_sp_item()]},
                None,
            )
            result = scan_audio_devices()
        self.assertIsInstance(result, AudioScanResult)

    def test_devices_parsed_from_mock(self):
        payload = {"SPAudioDataType": [_make_sp_item(), _make_sp_item(_name="Device B")]}
        with patch("studio_vault.scanners.audio.run_system_profiler") as mock_sp:
            mock_sp.return_value = (payload, None)
            result = scan_audio_devices()
        self.assertEqual(result.total, 2)

    def test_error_propagated(self):
        with patch("studio_vault.scanners.audio.run_system_profiler") as mock_sp:
            mock_sp.return_value = (None, "system_profiler: timeout")
            result = scan_audio_devices()
        self.assertGreater(len(result.errors), 0)
        self.assertIn("system_profiler", result.errors[0])


if __name__ == "__main__":
    unittest.main()
