"""
Hardware scanner — read-only detection of connected studio hardware on macOS.

Uses system_profiler (CoreAudio, MIDI, USB) with Core MIDI as a MIDI fallback when
SPMIDIDataType returns no data. USB entries are supporting metadata for deduplication.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from studio_vault.scanners._system import run_system_profiler

logger = logging.getLogger(__name__)

# ── Device type constants ─────────────────────────────────────────────────────

DEVICE_TYPE_AUDIO = "Audio Interface"
DEVICE_TYPE_MIDI = "MIDI Device"
DEVICE_TYPE_USB = "USB Device"
DEVICE_TYPE_UNKNOWN = "Unknown"

SOURCE_COREAUDIO = "CoreAudio"
SOURCE_MIDI = "MIDI"
SOURCE_USB = "USB"
SOURCE_CORE_MIDI = "Core MIDI"

# Built-in / display audio devices to omit from studio hardware results
_SKIP_AUDIO_NAME_PARTS = (
    "built-in",
    "built in",
    "displayport",
    "hdmi",
    "thunderbolt display",
    "airpods",
    "iphone",
    "ipad",
)
_SKIP_AUDIO_TRANSPORTS = (
    "coreaudio_device_type_builtin",
    "coreaudio_device_type_virtual",
    "built-in",
    "displayport",
    "hdmi",
)

_SKIP_MIDI_NAMES = frozenset(
    {
        "iac-driver",
        "iac driver",
        "bluetooth",
        "nettverk",
        "network",
        "ump-nettverk",
        "ump network",
        "macbook pro",
        "loopback audio",
    }
)

# USB classes we never treat as studio hardware on their own
_SKIP_USB_NAME_PARTS = (
    "hub",
    "storage",
    "lan",
    "keyboard",
    "mouse",
    "trackpad",
    "receiver",
    "bluetooth",
    "card reader",
    "billboard",
)

_STUDIO_USB_HINTS = re.compile(
    r"(ssl|big\s*six|iconnect|mio\s*xl|mio\b|focusrite|scarlett|clarett|"
    r"universal\s*audio|apollo|rme|motu|audient|behringer|presonus|"
    r"novation|arturia|elektron|midi\s*interface|audio\s*interface)",
    re.IGNORECASE,
)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HardwareDevice:
    name: str
    vendor: str
    device_type: str
    connection_type: str
    source: str
    is_connected: bool = True
    raw_metadata: dict[str, Any] | None = None

    @property
    def status_label(self) -> str:
        return "Connected" if self.is_connected else "Disconnected"

    @property
    def row(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.name,
            self.vendor or "—",
            self.device_type,
            self.connection_type or "—",
            self.source,
            self.status_label,
        )


@dataclass
class HardwareScanResult:
    devices: list[HardwareDevice] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)

    @property
    def connected_count(self) -> int:
        return sum(1 for d in self.devices if d.is_connected)


# ── Public API ────────────────────────────────────────────────────────────────

def scan_hardware(*, debug_log: bool = True) -> HardwareScanResult:
    """
    Detect connected studio hardware on macOS.

    Returns merged, deduplicated devices plus per-source errors and status lines.
    """
    if sys.platform != "darwin":
        return HardwareScanResult(
            errors=["Hardware scanning is only supported on macOS."],
        )

    result = HardwareScanResult()
    candidates: list[HardwareDevice] = []

    audio, audio_err, audio_status = _scan_coreaudio()
    candidates.extend(audio)
    result.errors.extend(audio_err)
    result.status.extend(audio_status)

    midi, midi_err, midi_status = _scan_system_profiler_midi()
    candidates.extend(midi)
    result.errors.extend(midi_err)
    result.status.extend(midi_status)

    if not midi:
        cmidi, cmidi_err, cmidi_status = _scan_core_midi()
        candidates.extend(cmidi)
        result.errors.extend(cmidi_err)
        result.status.extend(cmidi_status)

    usb, usb_err, usb_status = _scan_usb()
    candidates.extend(usb)
    result.errors.extend(usb_err)
    result.status.extend(usb_status)

    merged = _merge_candidates(candidates)
    result.devices = [
        d for d in merged if d.is_connected and _is_studio_hardware(d)
    ]

    result.status.append(
        f"Merged {len(candidates)} candidate(s) → {len(result.devices)} studio device(s)"
    )

    if debug_log:
        _debug_log(result)

    return result


# ── system_profiler helpers ───────────────────────────────────────────────────

def _scan_coreaudio() -> tuple[list[HardwareDevice], list[str], list[str]]:
    errors: list[str] = []
    status: list[str] = []
    devices: list[HardwareDevice] = []

    payload, err = run_system_profiler("SPAudioDataType", timeout=120)
    if err:
        errors.append(err)
        status.append("CoreAudio: failed")
        return devices, errors, status

    items = _profiler_items(payload, "SPAudioDataType")
    status.append(f"CoreAudio: {len(items)} device(s) from system_profiler")

    for item in items:
        name = (item.get("_name") or "").strip()
        if not name or _should_skip_audio(name, item):
            continue
        if not _is_external_audio_device(item):
            continue

        vendor = (item.get("coreaudio_device_manufacturer") or "").strip()
        transport = (item.get("coreaudio_device_transport") or "").strip()
        connection = _map_coreaudio_transport(transport)

        dev = HardwareDevice(
            name=name,
            vendor=vendor,
            device_type=DEVICE_TYPE_AUDIO,
            connection_type=connection,
            source=SOURCE_COREAUDIO,
            is_connected=True,
            raw_metadata=dict(item),
        )
        devices.append(dev)

    return devices, errors, status


def _scan_system_profiler_midi() -> tuple[list[HardwareDevice], list[str], list[str]]:
    errors: list[str] = []
    status: list[str] = []
    devices: list[HardwareDevice] = []

    payload, err = run_system_profiler("SPMIDIDataType", timeout=120)
    if err:
        errors.append(err)
        status.append("MIDI (system_profiler): failed")
        return devices, errors, status

    root = payload.get("SPMIDIDataType") if payload else None
    if not root:
        status.append("MIDI (system_profiler): empty")
        return devices, errors, status

    items = _flatten_profiler_tree(root)
    status.append(f"MIDI (system_profiler): {len(items)} item(s)")

    for item in items:
        name = (item.get("_name") or "").strip()
        if not name:
            continue
        vendor = (
            item.get("manufacturer")
            or item.get("midi_manufacturer")
            or item.get("vendor")
            or ""
        )
        vendor = str(vendor).strip()
        devices.append(
            HardwareDevice(
                name=name,
                vendor=vendor,
                device_type=DEVICE_TYPE_MIDI,
                connection_type="MIDI",
                source=SOURCE_MIDI,
                is_connected=True,
                raw_metadata=dict(item),
            )
        )

    return devices, errors, status


def _scan_usb() -> tuple[list[HardwareDevice], list[str], list[str]]:
    errors: list[str] = []
    status: list[str] = []
    devices: list[HardwareDevice] = []

    payload, err = run_system_profiler("SPUSBDataType", timeout=120)
    if err:
        errors.append(err)
        status.append("USB: failed")
        return devices, errors, status

    leaves = _usb_leaf_nodes(payload)
    if not leaves:
        # Newer macOS leaves SPUSBDataType empty and reports devices under SPUSBHostDataType.
        host_payload, host_err = run_system_profiler("SPUSBHostDataType", timeout=120)
        if host_err:
            errors.append(host_err)
        leaves = _usb_host_leaf_nodes(host_payload)
    status.append(f"USB: {len(leaves)} leaf device(s)")

    for item in leaves:
        name = (item.get("_name") or "").strip()
        if not name or _should_skip_usb(name):
            continue

        vendor = (item.get("manufacturer") or _vendor_from_usb_id(item.get("vendor_id")) or "")
        vendor = str(vendor).strip()

        if not _studio_usb_hint(name, vendor):
            continue

        device_type = _infer_type_from_name_vendor(name, vendor, default=DEVICE_TYPE_USB)
        devices.append(
            HardwareDevice(
                name=name,
                vendor=vendor,
                device_type=device_type,
                connection_type="USB",
                source=SOURCE_USB,
                is_connected=True,
                raw_metadata=dict(item),
            )
        )

    return devices, errors, status


# ── Core MIDI fallback (macOS) ────────────────────────────────────────────────

def _scan_core_midi() -> tuple[list[HardwareDevice], list[str], list[str]]:
    """Core MIDI fallback, reusing the MIDI scanner's Core MIDI reader."""
    from studio_vault.scanners import midi

    midi_devices, errors, status = midi._scan_core_midi()
    devices: list[HardwareDevice] = []
    seen: set[str] = set()
    skipped_offline = 0

    for md in midi_devices:
        name = md.name.strip()
        if not name or _should_skip_midi_name(name):
            continue
        if not md.is_online:
            skipped_offline += 1
            continue
        key = _merge_key(name, md.manufacturer)
        if key in seen:
            continue
        seen.add(key)
        devices.append(
            HardwareDevice(
                name=name,
                vendor=md.manufacturer.strip(),
                device_type=DEVICE_TYPE_MIDI,
                connection_type="MIDI",
                source=SOURCE_CORE_MIDI,
                is_connected=True,
                raw_metadata={"connection_type": md.connection_type},
            )
        )

    status.append(
        f"Core MIDI: {len(devices)} online, {skipped_offline} offline skipped "
        f"(of {len(midi_devices)} listed)"
    )
    return devices, errors, status


# ── Merge & filter ────────────────────────────────────────────────────────────

def _merge_candidates(candidates: list[HardwareDevice]) -> list[HardwareDevice]:
    groups: dict[str, list[HardwareDevice]] = {}
    for dev in candidates:
        groups.setdefault(_merge_key(dev.name, dev.vendor), []).append(dev)

    merged: list[HardwareDevice] = []
    for group in groups.values():
        merged.append(_merge_group(group))
    merged.sort(key=lambda d: (d.device_type, d.name.lower()))
    return merged


def _merge_group(group: list[HardwareDevice]) -> HardwareDevice:
    if len(group) == 1:
        return group[0]

    name = _best_name(group)
    vendor = _best_vendor(group)
    device_type = _best_device_type(group)
    connection_type = _best_connection(group)
    sources = ", ".join(sorted({d.source for d in group}))
    meta = {
        "merged_sources": [d.source for d in group],
        "entries": [d.raw_metadata for d in group if d.raw_metadata],
    }
    return HardwareDevice(
        name=name,
        vendor=vendor,
        device_type=device_type,
        connection_type=connection_type,
        source=sources,
        is_connected=any(d.is_connected for d in group),
        raw_metadata=meta,
    )


def _is_studio_hardware(dev: HardwareDevice) -> bool:
    """Keep external studio gear; drop built-in monitors and generic USB clutter."""
    name_l = dev.name.lower()
    vendor_l = (dev.vendor or "").lower()

    if dev.device_type == DEVICE_TYPE_AUDIO:
        if _should_skip_audio(dev.name, dev.raw_metadata or {}):
            return False
        if "apple" in vendor_l and any(
            x in name_l for x in ("built-in", "built in", "display", "microphone", "output")
        ):
            return False
        return True

    if dev.device_type == DEVICE_TYPE_MIDI:
        return not _should_skip_midi_name(dev.name)

    if dev.source == SOURCE_USB or SOURCE_USB in dev.source:
        return _studio_usb_hint(dev.name, dev.vendor)

    return _studio_usb_hint(dev.name, dev.vendor)


# ── Parsing utilities ─────────────────────────────────────────────────────────

def _profiler_items(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    if not payload:
        return []
    root = payload.get(key)
    if isinstance(root, list) and root:
        first = root[0]
        if isinstance(first, dict) and "_items" in first:
            return [i for i in first.get("_items", []) if isinstance(i, dict)]
    return _flatten_profiler_tree(root)


def _flatten_profiler_tree(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            for child in obj:
                walk(child)
        elif isinstance(obj, dict):
            if obj.get("_name"):
                out.append(obj)
            for child in obj.get("_items", []):
                walk(child)

    walk(node)
    return out


def _usb_leaf_nodes(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            items = node.get("_items")
            if items:
                for child in items:
                    walk(child)
            elif node.get("_name") and node.get("product_id"):
                leaves.append(node)

    if payload:
        walk(payload.get("SPUSBDataType"))
    return leaves


def _usb_host_leaf_nodes(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Leaf devices from SPUSBHostDataType, mapped to the SPUSBDataType keys used above."""
    leaves: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            items = node.get("_items")
            if items:
                walk(items)
            elif node.get("_name") and node.get("USBDeviceKeyProductID"):
                leaves.append({
                    **node,
                    "product_id": node.get("USBDeviceKeyProductID"),
                    "vendor_id": node.get("USBDeviceKeyVendorID"),
                    "manufacturer": node.get("USBDeviceKeyVendorName", ""),
                })

    if payload:
        walk(payload.get("SPUSBHostDataType"))
    return leaves


def _vendor_from_usb_id(vendor_id: Any) -> str:
    if not vendor_id:
        return ""
    text = str(vendor_id)
    if "(" in text:
        return text.split("(", 1)[1].rstrip(")").strip()
    return text


def _map_coreaudio_transport(transport: str) -> str:
    mapping = {
        "coreaudio_device_type_usb": "USB",
        "coreaudio_device_type_builtin": "Built-in",
        "coreaudio_device_type_pci": "PCI",
        "coreaudio_device_type_firewire": "FireWire",
        "coreaudio_device_type_bluetooth": "Bluetooth",
        "coreaudio_device_type_aggregate": "Aggregate",
        "coreaudio_device_type_virtual": "Virtual",
    }
    return mapping.get(transport, transport.replace("coreaudio_device_type_", "").replace("_", " ").title() or "Unknown")


def _should_skip_audio(name: str, meta: dict[str, Any]) -> bool:
    lower = name.lower()
    if any(part in lower for part in _SKIP_AUDIO_NAME_PARTS):
        return True
    transport = str(meta.get("coreaudio_device_transport", "")).lower()
    if any(part in transport for part in _SKIP_AUDIO_TRANSPORTS):
        return True
    return False


def _should_skip_usb(name: str) -> bool:
    lower = name.lower()
    return any(part in lower for part in _SKIP_USB_NAME_PARTS)


def _should_skip_midi_name(name: str) -> bool:
    return name.strip().lower() in _SKIP_MIDI_NAMES


def _is_external_audio_device(meta: dict[str, Any]) -> bool:
    """Keep USB/PCI/FW audio endpoints; drop virtual drivers and built-in paths."""
    transport = str(meta.get("coreaudio_device_transport", "")).lower()
    if "virtual" in transport or "builtin" in transport:
        return False
    if transport == "coreaudio_device_type_usb":
        return True
    if transport in (
        "coreaudio_device_type_pci",
        "coreaudio_device_type_firewire",
        "coreaudio_device_type_thunderbolt",
    ):
        return True
    name = str(meta.get("_name", ""))
    return _studio_usb_hint(name, str(meta.get("coreaudio_device_manufacturer", "")))


def _studio_usb_hint(name: str, vendor: str) -> bool:
    blob = f"{name} {vendor}"
    return bool(_STUDIO_USB_HINTS.search(blob))


def _infer_type_from_name_vendor(
    name: str,
    vendor: str,
    *,
    default: str,
) -> str:
    blob = f"{name} {vendor}".lower()
    if re.search(r"\bmio\b|mioxl|iconnect", blob):
        return DEVICE_TYPE_MIDI
    if re.search(r"big\s*six|ssl|scarlett|clarett|apollo|audio\s*interface|ucx|motu", blob):
        return DEVICE_TYPE_AUDIO
    return default


def _normalize_key_part(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _merge_key(name: str, vendor: str) -> str:
    n = _normalize_key_part(name)
    if "bigsix" in n or (n.startswith("big") and "six" in n):
        n = "bigsix"
    if "mioxl" in n:
        n = "mioxl"
    return n


def _best_name(group: list[HardwareDevice]) -> str:
    for prefer in (SOURCE_COREAUDIO, SOURCE_MIDI, SOURCE_CORE_MIDI, SOURCE_USB):
        for d in group:
            if d.source == prefer or prefer in d.source:
                return d.name
    return group[0].name


def _best_vendor(group: list[HardwareDevice]) -> str:
    for d in group:
        if d.vendor:
            return d.vendor
    return ""


def _best_device_type(group: list[HardwareDevice]) -> str:
    priority = {
        DEVICE_TYPE_AUDIO: 0,
        DEVICE_TYPE_MIDI: 1,
        DEVICE_TYPE_USB: 2,
        DEVICE_TYPE_UNKNOWN: 3,
    }
    return min(group, key=lambda d: priority.get(d.device_type, 99)).device_type


def _best_connection(group: list[HardwareDevice]) -> str:
    for d in group:
        if d.connection_type and d.connection_type != "USB":
            return d.connection_type
        if d.device_type == DEVICE_TYPE_AUDIO and d.connection_type:
            return d.connection_type
    for d in group:
        if d.connection_type:
            return d.connection_type
    return "Unknown"


def _debug_log(result: HardwareScanResult) -> None:
    lines = ["── Hardware scan ──"]
    for line in result.status:
        lines.append(f"  status: {line}")
    for err in result.errors:
        lines.append(f"  error: {err}")
    if not result.devices:
        lines.append("  devices: (none)")
    for dev in result.devices:
        lines.append(
            f"  device: {dev.name!r} | {dev.vendor!r} | {dev.device_type} | "
            f"{dev.connection_type} | {dev.source} | {dev.status_label}"
        )
    text = "\n".join(lines)
    logger.info("%s", text)
    print(text, flush=True)


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = scan_hardware()
    print(f"\nConnected studio devices: {r.connected_count}")
    for d in r.devices:
        print(d.row)
