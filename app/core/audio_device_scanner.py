"""
Audio Device Scanner — read-only enumeration of all CoreAudio devices on macOS.

Uses system_profiler SPAudioDataType as the primary source. Parses device names,
channel counts, default input/output assignments, manufacturer, and transport type.
No audio monitoring or driver interaction.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Transport label map ────────────────────────────────────────────────────────

_TRANSPORT_MAP: dict[str, str] = {
    "coreaudio_device_type_builtin":   "Built-in",
    "coreaudio_device_type_usb":       "USB",
    "coreaudio_device_type_bluetooth": "Bluetooth",
    "coreaudio_device_type_thunderbolt": "Thunderbolt",
    "coreaudio_device_type_virtual":   "Virtual",
    "coreaudio_device_type_aggregate": "Aggregate",
    "coreaudio_device_type_multich":   "Multi-Channel",
    "coreaudio_device_type_hdmi":      "HDMI",
    "coreaudio_device_type_displayport": "DisplayPort",
    "coreaudio_device_type_firewire":  "FireWire",
    "coreaudio_device_type_pci":       "PCI",
    "coreaudio_device_type_avb":       "AVB",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AudioDevice:
    """Immutable snapshot of a single CoreAudio device."""

    name: str
    manufacturer: str
    input_channels: int
    output_channels: int
    is_default_input: bool
    is_default_output: bool
    transport: str
    is_connected: bool = True
    raw_metadata: dict[str, Any] | None = None

    # ── Labels ────────────────────────────────────────────────────────────────

    @property
    def status_label(self) -> str:
        return "Connected" if self.is_connected else "Disconnected"

    @property
    def default_input_label(self) -> str:
        return "✓" if self.is_default_input else "—"

    @property
    def default_output_label(self) -> str:
        return "✓" if self.is_default_output else "—"

    @property
    def input_channels_label(self) -> str:
        return str(self.input_channels) if self.input_channels > 0 else "—"

    @property
    def output_channels_label(self) -> str:
        return str(self.output_channels) if self.output_channels > 0 else "—"

    # ── Table row ─────────────────────────────────────────────────────────────

    @property
    def row(self) -> tuple[str, str, str, str, str, str, str, str]:
        """Values in display-column order for the Treeview."""
        return (
            self.name,
            self.input_channels_label,
            self.output_channels_label,
            self.default_input_label,
            self.default_output_label,
            self.manufacturer or "—",
            self.transport or "—",
            self.status_label,
        )

    # ── Copy / export ─────────────────────────────────────────────────────────

    @property
    def copy_text(self) -> str:
        """Human-readable block suitable for clipboard copy."""
        lines = [
            f"Device:           {self.name}",
            f"Manufacturer:     {self.manufacturer or '—'}",
            f"Transport:        {self.transport or '—'}",
            f"Input Channels:   {self.input_channels_label}",
            f"Output Channels:  {self.output_channels_label}",
            f"Default Input:    {'Yes' if self.is_default_input else 'No'}",
            f"Default Output:   {'Yes' if self.is_default_output else 'No'}",
            f"Status:           {self.status_label}",
        ]
        return "\n".join(lines)

    @property
    def csv_row(self) -> list[str]:
        """Values aligned with CSV_HEADERS."""
        return [
            self.name,
            self.manufacturer or "",
            self.transport or "",
            self.input_channels_label,
            self.output_channels_label,
            "Yes" if self.is_default_input else "No",
            "Yes" if self.is_default_output else "No",
            self.status_label,
        ]


CSV_HEADERS: list[str] = [
    "Device Name",
    "Manufacturer",
    "Transport",
    "Input Channels",
    "Output Channels",
    "Default Input",
    "Default Output",
    "Status",
]


@dataclass
class AudioScanResult:
    """Aggregated result of a single audio device scan pass."""

    devices: list[AudioDevice] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.devices)

    @property
    def input_count(self) -> int:
        return sum(1 for d in self.devices if d.input_channels > 0)

    @property
    def output_count(self) -> int:
        return sum(1 for d in self.devices if d.output_channels > 0)

    @property
    def default_input(self) -> AudioDevice | None:
        return next((d for d in self.devices if d.is_default_input), None)

    @property
    def default_output(self) -> AudioDevice | None:
        return next((d for d in self.devices if d.is_default_output), None)


# ── Public API ────────────────────────────────────────────────────────────────

def scan_audio_devices() -> AudioScanResult:
    """
    Enumerate all CoreAudio devices registered with macOS.

    Returns an :class:`AudioScanResult` containing every device reported by
    ``system_profiler SPAudioDataType``.  Read-only — no audio streams are
    opened or modified.
    """
    if sys.platform != "darwin":
        return AudioScanResult(
            errors=["Audio device scanning is only supported on macOS."],
            status=["Unsupported platform"],
        )

    result = AudioScanResult()
    payload, err = _run_system_profiler("SPAudioDataType")

    if err:
        result.errors.append(err)
        result.status.append("system_profiler SPAudioDataType: failed")
        return result

    items = _extract_items(payload)
    result.status.append(f"system_profiler: {len(items)} audio item(s) found")

    for item in items:
        device = _parse_device(item)
        if device is not None:
            result.devices.append(device)

    result.status.append(f"Parsed {result.total} audio device(s)")
    return result


# ── system_profiler helpers ───────────────────────────────────────────────────

def _run_system_profiler(data_type: str) -> tuple[dict[str, Any] | None, str | None]:
    """Run ``system_profiler <data_type> -json`` and return (payload, error)."""
    cmd = ["system_profiler", data_type, "-json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{data_type}: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return None, f"{data_type}: {err}"

    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        snippet = (proc.stdout or "")[:200]
        return None, f"{data_type}: invalid JSON ({exc}); snippet={snippet!r}"


def _extract_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Pull the device-list from the SPAudioDataType JSON envelope."""
    if not payload:
        return []
    # system_profiler wraps the list under the data-type key
    for value in payload.values():
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


# ── Per-device parsing ────────────────────────────────────────────────────────

def _parse_device(item: dict[str, Any]) -> AudioDevice | None:
    """Convert one SPAudioDataType dict into an :class:`AudioDevice`."""
    name = (item.get("_name") or "").strip()
    if not name:
        return None

    manufacturer = (item.get("coreaudio_device_manufacturer") or "").strip()
    transport_raw = (item.get("coreaudio_device_transport") or "").strip().lower()
    transport = _TRANSPORT_MAP.get(transport_raw, _humanise_transport(transport_raw))

    input_channels = _parse_channels(
        item.get("coreaudio_device_input")
        or item.get("coreaudio_input_number")
    )
    output_channels = _parse_channels(
        item.get("coreaudio_device_output")
        or item.get("coreaudio_output_number")
    )

    is_default_input = _is_yes(item.get("coreaudio_default_audio_input_device"))
    is_default_output = _is_yes(item.get("coreaudio_default_audio_output_device"))

    return AudioDevice(
        name=name,
        manufacturer=manufacturer,
        input_channels=input_channels,
        output_channels=output_channels,
        is_default_input=is_default_input,
        is_default_output=is_default_output,
        transport=transport,
        is_connected=True,
        raw_metadata=dict(item),
    )


# ── Value parsers ─────────────────────────────────────────────────────────────

def _parse_channels(value: Any) -> int:
    """Return an integer channel count from a SPAudioDataType field value."""
    if value is None:
        return 0
    try:
        return max(0, int(str(value).strip()))
    except (ValueError, TypeError):
        return 0


def _is_yes(value: Any) -> bool:
    """Return True if *value* represents an affirmative CoreAudio flag."""
    return str(value or "").strip().lower() in ("yes", "true", "1")


def _humanise_transport(raw: str) -> str:
    """Convert an unknown transport token to a readable label."""
    if not raw:
        return "Unknown"
    # Strip common prefixes and title-case what's left
    cleaned = raw.replace("coreaudio_device_type_", "").replace("_", " ")
    return cleaned.title() if cleaned else raw


# ── CSV export helper ─────────────────────────────────────────────────────────

def export_csv(devices: list[AudioDevice], dest_path: str | None = None) -> str:
    """
    Write *devices* to a CSV file and return the path written.

    If *dest_path* is None the file lands on the Desktop with a timestamp.
    """
    import csv
    import datetime
    from pathlib import Path

    if dest_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = str(Path.home() / "Desktop" / f"bakkis_audio_devices_{ts}.csv")

    path = Path(dest_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADERS)
        for device in devices:
            writer.writerow(device.csv_row)

    return str(path)
