"""
MIDI scanner — enumerate and inspect MIDI devices on macOS.

Primary source : CoreMIDI (via ctypes).
  Per device: name, manufacturer, offline flag, driver-owner bundle,
  entity count, sources (inputs to host) and destinations (outputs from host).

Fallback       : system_profiler SPMIDIDataType.
  Used automatically when CoreMIDI returns 0 devices (e.g. permission issues).
  Inputs/outputs are reported as 0 from this path because the profiler omits
  port-level detail.

The scanner is read-only — it never opens MIDI ports or sends/receives messages.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Skip list ─────────────────────────────────────────────────────────────────

_SHOW_ALL_DEVICES = True  # show IAC, Network, etc. with appropriate type labels

# ── Connection type inference ─────────────────────────────────────────────────

_BLUETOOTH_RE = re.compile(r"bluetooth|btle|ble", re.IGNORECASE)
_NETWORK_RE   = re.compile(r"network|rtpmidi|rtp\.midi|applemidi", re.IGNORECASE)
_USB_RE       = re.compile(r"usb", re.IGNORECASE)
_VIRTUAL_RE   = re.compile(r"iac|loopback|virtual|internal", re.IGNORECASE)
_THUNDERBOLT_RE = re.compile(r"thunderbolt|firewire|fw", re.IGNORECASE)


def _infer_connection_type(driver_owner: str, name: str) -> str:
    """Derive a human-readable connection type from the CoreMIDI driver bundle ID."""
    blob = f"{driver_owner} {name}"
    if _BLUETOOTH_RE.search(blob):
        return "Bluetooth"
    if _NETWORK_RE.search(blob):
        return "Network"
    if _THUNDERBOLT_RE.search(blob):
        return "Thunderbolt"
    if _USB_RE.search(blob):
        return "USB"
    if _VIRTUAL_RE.search(blob):
        return "Virtual"
    return "MIDI"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MidiDevice:
    """A single MIDI device as detected by CoreMIDI or system_profiler."""

    name: str
    manufacturer: str
    inputs: int            # MIDI sources  (data flowing *into* the host)
    outputs: int           # MIDI destinations (data flowing *out of* the host)
    is_online: bool
    connection_type: str   # USB | Bluetooth | Network | Virtual | MIDI | Unknown
    source: str            # "CoreMIDI" | "system_profiler"

    @property
    def status_label(self) -> str:
        return "Online" if self.is_online else "Offline"

    @property
    def inputs_label(self) -> str:
        return str(self.inputs) if self.inputs >= 0 else "—"

    @property
    def outputs_label(self) -> str:
        return str(self.outputs) if self.outputs >= 0 else "—"

    @property
    def row(self) -> tuple[str, str, str, str, str, str]:
        """Values for a Treeview row: name, manufacturer, inputs, outputs, status, connection."""
        return (
            self.name,
            self.manufacturer or "—",
            self.inputs_label,
            self.outputs_label,
            self.status_label,
            self.connection_type or "—",
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "Name":            self.name,
            "Manufacturer":    self.manufacturer or "",
            "Inputs":          self.inputs_label,
            "Outputs":         self.outputs_label,
            "Online":          self.status_label,
            "Connection Type": self.connection_type,
            "Source":          self.source,
        }


@dataclass
class MidiScanResult:
    devices: list[MidiDevice] = field(default_factory=list)
    errors:  list[str]        = field(default_factory=list)
    status:  list[str]        = field(default_factory=list)

    @property
    def online_count(self) -> int:
        return sum(1 for d in self.devices if d.is_online)

    @property
    def offline_count(self) -> int:
        return sum(1 for d in self.devices if not d.is_online)

    @property
    def total_inputs(self) -> int:
        return sum(d.inputs for d in self.devices if d.inputs >= 0)

    @property
    def total_outputs(self) -> int:
        return sum(d.outputs for d in self.devices if d.outputs >= 0)


# ── Public API ────────────────────────────────────────────────────────────────

def scan_midi_devices(*, debug_log: bool = False) -> MidiScanResult:
    """
    Enumerate MIDI devices on macOS.

    Tries CoreMIDI first; falls back to system_profiler SPMIDIDataType when
    CoreMIDI reports zero devices.
    """
    if sys.platform != "darwin":
        return MidiScanResult(errors=["MIDI scanning is only supported on macOS."])

    result = MidiScanResult()

    devices, errors, status = _scan_core_midi()
    result.errors.extend(errors)
    result.status.extend(status)

    if devices:
        result.devices = devices
        result.status.append(
            f"CoreMIDI: {len(devices)} device(s) — {result.online_count} online, "
            f"{result.offline_count} offline"
        )
    else:
        result.status.append("CoreMIDI: 0 devices — trying system_profiler fallback")
        fb_devices, fb_errors, fb_status = _scan_system_profiler()
        result.devices = fb_devices
        result.errors.extend(fb_errors)
        result.status.extend(fb_status)
        result.status.append(
            f"system_profiler: {len(fb_devices)} device(s)"
        )

    if debug_log:
        _debug_log(result)

    return result


def export_csv(devices: list[MidiDevice], dest: Path | str | None = None) -> Path:
    """Write *devices* to a timestamped CSV file. Returns the written path."""
    if dest is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path.home() / "Desktop" / f"bakkis_midi_devices_{ts}.csv"

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    headers = ["Name", "Manufacturer", "Inputs", "Outputs", "Online", "Connection Type", "Source"]
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for d in devices:
            writer.writerow(d.as_dict())

    return dest


# ── CoreMIDI source ───────────────────────────────────────────────────────────

def _scan_core_midi() -> tuple[list[MidiDevice], list[str], list[str]]:
    errors: list[str] = []
    status: list[str] = []
    devices: list[MidiDevice] = []

    try:
        import ctypes
        from ctypes import c_uint32, c_void_p
    except ImportError as exc:
        errors.append(f"CoreMIDI: ctypes unavailable — {exc}")
        status.append("CoreMIDI: unavailable")
        return devices, errors, status

    try:
        lib = ctypes.CDLL("/System/Library/Frameworks/CoreMIDI.framework/CoreMIDI")
        cf  = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError as exc:
        errors.append(f"CoreMIDI: framework load failed — {exc}")
        status.append("CoreMIDI: framework load failed")
        return devices, errors, status

    # ── CoreFoundation string helpers ─────────────────────────────────────────

    cf.CFStringCreateWithCString.restype  = c_void_p
    cf.CFStringCreateWithCString.argtypes = [c_void_p, ctypes.c_char_p, c_uint32]
    cf.CFRelease.argtypes = [c_void_p]
    cf.CFStringGetLength.restype = ctypes.c_long
    cf.CFStringGetLength.argtypes = [c_void_p]
    cf.CFStringGetCStringPtr.restype  = ctypes.c_char_p
    cf.CFStringGetCStringPtr.argtypes = [c_void_p, c_uint32]
    cf.CFStringGetCString.restype  = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [c_void_p, ctypes.c_char_p, ctypes.c_long, c_uint32]

    _kCFStringEncodingUTF8 = 0x08000100

    def _mk_key(tag: str) -> c_void_p:
        return cf.CFStringCreateWithCString(None, tag.encode("ascii"), _kCFStringEncodingUTF8)

    def _cfstring_to_str(ref: int | None) -> str:
        if not ref:
            return ""
        ptr = cf.CFStringGetCStringPtr(ref, _kCFStringEncodingUTF8)
        if ptr:
            return ptr.decode("utf-8", errors="replace")
        length = cf.CFStringGetLength(ref)
        buf = ctypes.create_string_buffer(length * 4 + 1)
        if cf.CFStringGetCString(ref, buf, len(buf), _kCFStringEncodingUTF8):
            return buf.value.decode("utf-8", errors="replace")
        return ""

    # ── Property key constants ────────────────────────────────────────────────
    k_name    = _mk_key("name")
    k_manu    = _mk_key("manu")
    k_offline = _mk_key("offline")
    k_driver  = _mk_key("drvr")   # kMIDIPropertyDriverOwner

    # ── CoreMIDI function bindings ────────────────────────────────────────────
    lib.MIDIGetNumberOfDevices.restype = c_uint32
    lib.MIDIGetDevice.restype  = c_uint32
    lib.MIDIGetDevice.argtypes = [c_uint32]

    lib.MIDIObjectGetStringProperty.restype  = ctypes.c_int32
    lib.MIDIObjectGetStringProperty.argtypes = [c_uint32, c_void_p, ctypes.POINTER(c_void_p)]

    lib.MIDIObjectGetIntegerProperty.restype  = ctypes.c_int32
    lib.MIDIObjectGetIntegerProperty.argtypes = [c_uint32, c_void_p, ctypes.POINTER(ctypes.c_int32)]

    lib.MIDIDeviceGetNumberOfEntities.restype  = c_uint32
    lib.MIDIDeviceGetNumberOfEntities.argtypes = [c_uint32]

    lib.MIDIDeviceGetEntity.restype  = c_uint32
    lib.MIDIDeviceGetEntity.argtypes = [c_uint32, c_uint32]

    lib.MIDIEntityGetNumberOfSources.restype      = c_uint32
    lib.MIDIEntityGetNumberOfSources.argtypes     = [c_uint32]
    lib.MIDIEntityGetNumberOfDestinations.restype  = c_uint32
    lib.MIDIEntityGetNumberOfDestinations.argtypes = [c_uint32]

    def _get_string(obj_id: int, prop: Any) -> str:
        out = c_void_p()
        err = lib.MIDIObjectGetStringProperty(obj_id, prop, ctypes.byref(out))
        if err != 0 or not out.value:
            return ""
        try:
            return _cfstring_to_str(out.value)
        finally:
            if out.value:
                cf.CFRelease(out.value)

    def _get_int(obj_id: int, prop: Any) -> int | None:
        val = ctypes.c_int32()
        err = lib.MIDIObjectGetIntegerProperty(obj_id, prop, ctypes.byref(val))
        return int(val.value) if err == 0 else None

    # ── Enumerate devices ─────────────────────────────────────────────────────
    count = lib.MIDIGetNumberOfDevices()
    status.append(f"CoreMIDI: {count} device reference(s) reported")

    for i in range(count):
        dev_ref = lib.MIDIGetDevice(i)
        if not dev_ref:
            continue

        name   = _get_string(dev_ref, k_name).strip()
        manu   = _get_string(dev_ref, k_manu).strip()
        driver = _get_string(dev_ref, k_driver).strip()

        offline_val = _get_int(dev_ref, k_offline)
        is_online   = (offline_val != 1)

        # Count inputs and outputs across all entities
        total_inputs  = 0
        total_outputs = 0
        try:
            n_entities = lib.MIDIDeviceGetNumberOfEntities(dev_ref)
            for j in range(n_entities):
                entity = lib.MIDIDeviceGetEntity(dev_ref, j)
                if entity:
                    total_inputs  += lib.MIDIEntityGetNumberOfSources(entity)
                    total_outputs += lib.MIDIEntityGetNumberOfDestinations(entity)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"CoreMIDI: entity enumeration error for '{name}': {exc}")

        conn_type = _infer_connection_type(driver, name)

        if not name:
            name = f"MIDI Device {i}"

        devices.append(MidiDevice(
            name=name,
            manufacturer=manu,
            inputs=total_inputs,
            outputs=total_outputs,
            is_online=is_online,
            connection_type=conn_type,
            source="CoreMIDI",
        ))

    # Release CF strings
    for key_ref in (k_name, k_manu, k_offline, k_driver):
        if key_ref:
            try:
                cf.CFRelease(key_ref)
            except Exception:  # noqa: BLE001
                pass

    return devices, errors, status


# ── system_profiler fallback ──────────────────────────────────────────────────

def _scan_system_profiler() -> tuple[list[MidiDevice], list[str], list[str]]:
    errors: list[str] = []
    status: list[str] = []
    devices: list[MidiDevice] = []

    cmd = ["system_profiler", "SPMIDIDataType", "-json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"system_profiler: {exc}")
        status.append("system_profiler: failed")
        return devices, errors, status

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        errors.append(f"system_profiler: {err}")
        status.append("system_profiler: non-zero exit")
        return devices, errors, status

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        errors.append(f"system_profiler: invalid JSON — {exc}")
        status.append("system_profiler: JSON parse error")
        return devices, errors, status

    root = payload.get("SPMIDIDataType") if payload else None
    if not root:
        status.append("system_profiler SPMIDIDataType: empty")
        return devices, errors, status

    items = _flatten_tree(root)
    status.append(f"system_profiler: {len(items)} item(s) in tree")

    for item in items:
        name = (item.get("_name") or "").strip()
        if not name:
            continue

        manu = str(
            item.get("manufacturer")
            or item.get("midi_manufacturer")
            or item.get("vendor")
            or ""
        ).strip()

        conn_type = _infer_connection_type("", name)

        devices.append(MidiDevice(
            name=name,
            manufacturer=manu,
            inputs=0,
            outputs=0,
            is_online=True,
            connection_type=conn_type,
            source="system_profiler",
        ))

    return devices, errors, status


def _flatten_tree(node: Any) -> list[dict[str, Any]]:
    """Recursively collect all dict nodes with a '_name' key."""
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


# ── Diagnostics ───────────────────────────────────────────────────────────────

def _debug_log(result: MidiScanResult) -> None:
    lines = ["── MIDI scan ──"]
    for s in result.status:
        lines.append(f"  status: {s}")
    for e in result.errors:
        lines.append(f"  error:  {e}")
    if not result.devices:
        lines.append("  devices: (none)")
    for d in result.devices:
        lines.append(
            f"  {d.name!r} | manu={d.manufacturer!r} | "
            f"in={d.inputs} out={d.outputs} | "
            f"{d.status_label} | {d.connection_type} | src={d.source}"
        )
    text = "\n".join(lines)
    logger.info("%s", text)
    print(text, flush=True)


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    r = scan_midi_devices(debug_log=True)
    print(f"\nTotal: {len(r.devices)}  Online: {r.online_count}  "
          f"Inputs: {r.total_inputs}  Outputs: {r.total_outputs}")
