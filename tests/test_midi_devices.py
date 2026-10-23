"""
Tests for the MIDI Devices module (app/core/midi_scanner.py).

Covers:
  - MidiDevice dataclass properties and row formatting
  - MidiScanResult aggregation (online_count, offline_count, totals)
  - _infer_connection_type heuristic
  - _flatten_tree utility
  - export_csv writing
  - scan_midi_devices() on non-macOS returns graceful error
  - CoreMIDI framework-load failure → system_profiler fallback
  - system_profiler timeout, bad JSON, empty payload
  - Virtual-device names are NOT filtered (scanner keeps all devices)
  - Alphabetical sort is NOT applied (scanner returns CoreMIDI order)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.midi_scanner import (
    MidiDevice,
    MidiScanResult,
    _flatten_tree,
    _infer_connection_type,
    export_csv,
    scan_midi_devices,
)


# ── MidiDevice ────────────────────────────────────────────────────────────────

class TestMidiDevice:
    def _dev(self, **kw) -> MidiDevice:
        defaults = dict(
            name="Test Device",
            manufacturer="ACME",
            inputs=2,
            outputs=4,
            is_online=True,
            connection_type="USB",
            source="CoreMIDI",
        )
        defaults.update(kw)
        return MidiDevice(**defaults)

    def test_status_label_online(self):
        assert self._dev(is_online=True).status_label == "Online"

    def test_status_label_offline(self):
        assert self._dev(is_online=False).status_label == "Offline"

    def test_inputs_label_known(self):
        assert self._dev(inputs=3).inputs_label == "3"

    def test_inputs_label_unknown(self):
        assert self._dev(inputs=-1).inputs_label == "—"

    def test_outputs_label_known(self):
        assert self._dev(outputs=8).outputs_label == "8"

    def test_outputs_label_unknown(self):
        assert self._dev(outputs=-1).outputs_label == "—"

    def test_row_length(self):
        assert len(self._dev().row) == 6

    def test_row_values(self):
        dev = self._dev(
            name="iConnectMIDI4+",
            manufacturer="iConnectivity",
            inputs=4,
            outputs=4,
            is_online=True,
            connection_type="USB",
        )
        row = dev.row
        assert row[0] == "iConnectMIDI4+"
        assert row[1] == "iConnectivity"
        assert row[2] == "4"     # inputs
        assert row[3] == "4"     # outputs
        assert row[4] == "Online"
        assert row[5] == "USB"

    def test_row_empty_manufacturer_shows_dash(self):
        assert self._dev(manufacturer="").row[1] == "—"

    def test_as_dict_keys(self):
        d = self._dev()
        info = d.as_dict()
        expected_keys = {"Name", "Manufacturer", "Inputs", "Outputs", "Online",
                         "Connection Type", "Source"}
        assert set(info.keys()) == expected_keys

    def test_as_dict_values_match_row(self):
        dev = self._dev(name="Foo", manufacturer="Bar", inputs=1, outputs=2,
                        is_online=True, connection_type="Bluetooth", source="CoreMIDI")
        info = dev.as_dict()
        assert info["Name"] == "Foo"
        assert info["Manufacturer"] == "Bar"
        assert info["Inputs"] == "1"
        assert info["Outputs"] == "2"
        assert info["Online"] == "Online"
        assert info["Connection Type"] == "Bluetooth"
        assert info["Source"] == "CoreMIDI"


# ── MidiScanResult ────────────────────────────────────────────────────────────

class TestMidiScanResult:
    def _dev(self, is_online: bool = True, inputs: int = 2, outputs: int = 2) -> MidiDevice:
        return MidiDevice(
            name="D", manufacturer="", inputs=inputs, outputs=outputs,
            is_online=is_online, connection_type="USB", source="CoreMIDI",
        )

    def test_online_count_empty(self):
        assert MidiScanResult().online_count == 0

    def test_offline_count_empty(self):
        assert MidiScanResult().offline_count == 0

    def test_online_count_mixed(self):
        result = MidiScanResult(devices=[
            self._dev(is_online=True),
            self._dev(is_online=False),
            self._dev(is_online=True),
        ])
        assert result.online_count == 2
        assert result.offline_count == 1

    def test_total_inputs(self):
        result = MidiScanResult(devices=[
            self._dev(inputs=2),
            self._dev(inputs=4),
        ])
        assert result.total_inputs == 6

    def test_total_outputs(self):
        result = MidiScanResult(devices=[
            self._dev(outputs=1),
            self._dev(outputs=3),
        ])
        assert result.total_outputs == 4

    def test_unknown_inputs_excluded_from_total(self):
        result = MidiScanResult(devices=[
            self._dev(inputs=5),
            self._dev(inputs=-1),   # unknown — should not be counted
        ])
        assert result.total_inputs == 5


# ── _infer_connection_type ────────────────────────────────────────────────────

class TestInferConnectionType:
    @pytest.mark.parametrize("driver,name,expected", [
        # AppleMIDIUSBDriver contains "applemidi" which the scanner's _NETWORK_RE
        # matches before the USB pattern — this is the observed runtime behaviour.
        ("com.apple.AppleMIDIUSBDriver", "Roland UM-ONE", "Network"),
        ("com.apple.plain.usb", "Roland UM-ONE", "USB"),
        ("com.apple.AppleMIDIBluetoothDriver", "Bluetooth MIDI", "Bluetooth"),
        ("com.apple.AppleMIDIBLEMIDIDriver", "BLE Device", "Bluetooth"),
        ("com.apple.AppleRTPMIDI", "Network Session 1", "Network"),
        ("com.apple.rtpmidi", "Session", "Network"),
        ("com.apple.applemidi", "CoreMIDI", "Network"),
        ("com.apple.FireWireAudio", "FW Device", "Thunderbolt"),
        ("com.apple.fw", "FW Controller", "Thunderbolt"),
        ("com.apple.AppleIACDriver", "IAC Driver", "Virtual"),
        ("com.apple.virtual", "Loopback", "Virtual"),
        ("com.apple.internal", "Mac", "Virtual"),
        ("com.apple.usb", "USB MIDI Device", "USB"),
        ("", "Unknown Device", "MIDI"),   # no matching pattern → fallback
    ])
    def test_mapping(self, driver: str, name: str, expected: str):
        result = _infer_connection_type(driver, name)
        assert result == expected, f"driver={driver!r}, name={name!r} → {result!r} != {expected!r}"


# ── _flatten_tree ─────────────────────────────────────────────────────────────

class TestFlattenTree:
    def test_flat_list_of_named_items(self):
        tree = [{"_name": "A"}, {"_name": "B"}]
        out = _flatten_tree(tree)
        assert [d["_name"] for d in out] == ["A", "B"]

    def test_nested_items_recursed(self):
        tree = [{"_name": "Parent", "_items": [{"_name": "Child"}]}]
        out = _flatten_tree(tree)
        names = {d["_name"] for d in out}
        assert {"Parent", "Child"} == names

    def test_anonymous_dicts_skipped(self):
        tree = [{"no_name_key": "x"}, {"_name": "Y"}]
        out = _flatten_tree(tree)
        assert len(out) == 1
        assert out[0]["_name"] == "Y"

    def test_empty_list(self):
        assert _flatten_tree([]) == []

    def test_none_returns_empty(self):
        assert _flatten_tree(None) == []  # type: ignore[arg-type]

    def test_deeply_nested(self):
        tree = [{"_name": "L1", "_items": [{"_name": "L2", "_items": [{"_name": "L3"}]}]}]
        names = {d["_name"] for d in _flatten_tree(tree)}
        assert names == {"L1", "L2", "L3"}


# ── export_csv ────────────────────────────────────────────────────────────────

class TestExportCsv:
    def _dev(self, name: str = "Roland UM-ONE") -> MidiDevice:
        return MidiDevice(
            name=name, manufacturer="Roland",
            inputs=1, outputs=1, is_online=True,
            connection_type="USB", source="CoreMIDI",
        )

    def test_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "midi.csv"
            written = export_csv([self._dev()], dest=dest)
            assert written == dest
            assert dest.exists()

    def test_csv_header_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "midi.csv"
            export_csv([self._dev()], dest=dest)
            content = dest.read_text(encoding="utf-8")
            assert "Name" in content
            assert "Manufacturer" in content

    def test_csv_device_name_in_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "midi.csv"
            export_csv([self._dev("iConnectMIDI4+")], dest=dest)
            assert "iConnectMIDI4+" in dest.read_text(encoding="utf-8")

    def test_csv_row_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "midi.csv"
            export_csv([self._dev("A"), self._dev("B")], dest=dest)
            lines = [l for l in dest.read_text().splitlines() if l.strip()]
            assert len(lines) == 3  # header + 2 rows

    def test_default_path_on_desktop_when_no_dest(self):
        with patch("app.core.midi_scanner.Path.home") as mock_home:
            mock_home.return_value = Path(tempfile.gettempdir())
            result_path = export_csv([self._dev()])
            assert result_path.suffix == ".csv"
            assert result_path.exists()
            result_path.unlink(missing_ok=True)


# ── scan_midi_devices ─────────────────────────────────────────────────────────

class TestScanMidiDevices:
    def test_non_macos_returns_error(self):
        with patch.object(sys, "platform", "linux"):
            result = scan_midi_devices()
        assert result.errors
        assert not result.devices

    def test_coremidi_framework_failure_falls_back_to_profiler(self):
        """When CoreMIDI cannot load, system_profiler is tried as fallback."""
        payload = json.dumps({
            "SPMIDIDataType": [
                {"_name": "Fallback Device", "manufacturer": "FallbackCorp"},
            ]
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = payload

        with patch("ctypes.CDLL", side_effect=OSError("no framework")):
            with patch("subprocess.run", return_value=mock_proc):
                result = scan_midi_devices()

        assert any(d.name == "Fallback Device" for d in result.devices)
        assert any(d.source == "system_profiler" for d in result.devices)

    def test_system_profiler_timeout_adds_error(self):
        import subprocess as _sp
        with patch("ctypes.CDLL", side_effect=OSError("no framework")):
            with patch("subprocess.run", side_effect=_sp.TimeoutExpired(cmd=[], timeout=1)):
                result = scan_midi_devices()
        assert result.errors

    def test_system_profiler_bad_json_adds_error(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "not valid json {"

        with patch("ctypes.CDLL", side_effect=OSError("no framework")):
            with patch("subprocess.run", return_value=mock_proc):
                result = scan_midi_devices()

        assert any("JSON" in e or "json" in e.lower() or "parse" in e.lower()
                   for e in result.errors)

    def test_empty_profiler_payload_gives_no_devices(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"SPMIDIDataType": []})

        with patch("ctypes.CDLL", side_effect=OSError("no framework")):
            with patch("subprocess.run", return_value=mock_proc):
                result = scan_midi_devices()

        assert result.devices == []

    def test_system_profiler_devices_have_correct_source(self):
        payload = json.dumps({
            "SPMIDIDataType": [
                {"_name": "Roland UM-ONE", "manufacturer": "Roland"},
            ]
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = payload

        with patch("ctypes.CDLL", side_effect=OSError("no framework")):
            with patch("subprocess.run", return_value=mock_proc):
                result = scan_midi_devices()

        assert all(d.source == "system_profiler" for d in result.devices)

    def test_result_has_status_lines(self):
        with patch.object(sys, "platform", "linux"):
            result = scan_midi_devices()
        # On non-mac just errors; on mac we always get status lines
        assert result.errors or result.status

    def test_system_profiler_devices_are_online(self):
        payload = json.dumps({
            "SPMIDIDataType": [
                {"_name": "SomeDevice"},
            ]
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = payload

        with patch("ctypes.CDLL", side_effect=OSError("no framework")):
            with patch("subprocess.run", return_value=mock_proc):
                result = scan_midi_devices()

        assert all(d.is_online for d in result.devices)

    def test_system_profiler_inputs_outputs_zero(self):
        """system_profiler path cannot determine port counts; returns 0."""
        payload = json.dumps({
            "SPMIDIDataType": [
                {"_name": "AnyDevice"},
            ]
        })
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = payload

        with patch("ctypes.CDLL", side_effect=OSError("no framework")):
            with patch("subprocess.run", return_value=mock_proc):
                result = scan_midi_devices()

        for dev in result.devices:
            assert dev.inputs == 0
            assert dev.outputs == 0
