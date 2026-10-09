"""Read-only Linux HID discovery, with explicit physical-device selection.

No evdev or hidapi installation is needed to list devices.  The IDs deliberately
include a physical-family fingerprint: an attached second keyboard must never
silently expand the set of devices an existing profile grabs.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import json

from .errors import ControlError


SYS_CLASS_INPUT = Path("/sys/class/input")
SYS_CLASS_HIDRAW = Path("/sys/class/hidraw")
DEV_ROOT = Path("/dev")
VIRTUAL_NAME = "Redragon Control"


class DeviceSelectionError(ControlError, ValueError):
    """A device selection is missing, disconnected, or ambiguous."""


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return default


def physical_family(physical_path: str) -> str:
    """Join USB keyboard/consumer-control interfaces, preserving receiver slots.

    ``/input0`` and ``/input1`` are interfaces of the same USB device.  A suffix
    such as Logitech's ``/input2:1`` identifies a receiver child and is retained.
    """
    return re.sub(r"/input\d+$", "", physical_path)


def _fallback_family(device_path: Path) -> str:
    # Prefer the USB device ancestor, not its changing HID/input enumeration ID.
    for parent in (device_path, *device_path.parents):
        if (parent / "idVendor").exists() and (parent / "idProduct").exists():
            return str(parent)
    for parent in (device_path, *device_path.parents):
        if re.fullmatch(r"[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]+", parent.name):
            return str(parent.parent)
    return str(device_path)


def _transport(bus: int) -> str:
    return {0x03: "usb", 0x05: "bluetooth", 0x06: "virtual"}.get(bus, "other")


def _node_accessible(path: str, write: bool = False) -> bool:
    return os.access(path, os.R_OK | (os.W_OK if write else 0))


def discover_devices() -> list[dict]:
    """Return HID devices grouped by VID:PID and physical input family.

    ``accessible`` reports whether any relevant node is currently accessible;
    ``input_accessible`` and ``hidraw_accessible`` distinguish the operations.
    Discovery only reads sysfs and access permissions; it never opens hardware.
    """
    families: dict[tuple[int, int, str], dict] = {}

    def add(vendor: int, product: int, phys: str, resolved: Path,
            name: str, bus: int, node: str, node_kind: str) -> None:
        if name.startswith(VIRTUAL_NAME) or phys.startswith("redragon-control/"):
            return
        family = physical_family(phys) if phys else _fallback_family(resolved)
        key = (vendor, product, family)
        if key not in families:
            fingerprint = hashlib.sha256(family.encode("utf-8")).hexdigest()[:12]
            families[key] = {
                "id": f"{vendor:04x}:{product:04x}@{fingerprint}",
                "vendor_id": vendor, "product_id": product,
                "name": name or "Unnamed HID device", "names": [],
                "transport": _transport(bus), "physical_path": family,
                "hidraw_paths": [], "event_paths": [],
            }
        record = families[key]
        if name and name not in record["names"]:
            record["names"].append(name)
            # The base interface generally has the shortest, most useful name.
            if len(name) < len(record["name"]):
                record["name"] = name
        if node not in record[node_kind]:
            record[node_kind].append(node)

    for path in sorted(SYS_CLASS_HIDRAW.glob("hidraw*")):
        device = path / "device"
        fields = dict(line.split("=", 1) for line in _read(device / "uevent").splitlines() if "=" in line)
        try:
            bus, vendor, product = (int(value, 16) for value in fields["HID_ID"].split(":"))
        except (KeyError, ValueError):
            continue
        add(vendor, product, fields.get("HID_PHYS", ""), device.resolve(),
            fields.get("HID_NAME", ""), bus, str(DEV_ROOT / path.name), "hidraw_paths")

    for path in sorted(SYS_CLASS_INPUT.glob("event*")):
        device = path / "device"
        try:
            vendor = int(_read(device / "id/vendor"), 16)
            product = int(_read(device / "id/product"), 16)
            bus = int(_read(device / "id/bustype"), 16)
        except ValueError:
            continue
        # Include only HID transports; power buttons, audio jacks, and virtual
        # application devices are not candidate keyboards.
        if bus not in (0x03, 0x05):
            continue
        add(vendor, product, _read(device / "phys"), device.resolve(),
            _read(device / "name"), bus, str(DEV_ROOT / "input" / path.name), "event_paths")

    for record in families.values():
        record["event_paths"].sort(key=lambda p: int(Path(p).name.removeprefix("event")))
        record["hidraw_paths"].sort(key=lambda p: int(Path(p).name.removeprefix("hidraw")))
        record["input_accessible"] = bool(record["event_paths"]) and all(
            _node_accessible(path) for path in record["event_paths"])
        record["hidraw_accessible"] = any(_node_accessible(path, write=True) for path in record["hidraw_paths"])
        record["accessible"] = record["input_accessible"] or record["hidraw_accessible"]
    return sorted(families.values(), key=lambda item: (item["vendor_id"], item["product_id"], item["id"]))


def resolve_device(device_id: str | None, devices: list[dict] | None = None) -> dict:
    """Resolve an explicit family ID; allow a VID:PID only if it is unambiguous."""
    if not isinstance(device_id, str) or not device_id.strip():
        raise DeviceSelectionError("Select a device first with 'redragonctl select DEVICE_ID'.")
    selection = device_id.strip().lower()
    candidates = discover_devices() if devices is None else devices
    matches = [device for device in candidates if device["id"].lower() == selection]
    if not matches and re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", selection):
        matches = [device for device in candidates if f'{device["vendor_id"]:04x}:{device["product_id"]:04x}' == selection]
    if len(matches) > 1:
        raise DeviceSelectionError(f"Device {device_id!r} is ambiguous. Select its full physical-family ID from the devices list.")
    if not matches:
        raise DeviceSelectionError(f"Selected device {device_id!r} is disconnected or unavailable. List devices and select the intended keyboard.")
    return matches[0]


class ConnectionStore:
    """Explicitly linked physical endpoints, never a VID/PID-wide fallback."""
    def __init__(self, config_path):
        self.path = Path(config_path).with_name(Path(config_path).stem + ".connections.json")

    def read(self):
        if not self.path.exists():
            return []
        try:
            groups = json.loads(self.path.read_text())
            if not isinstance(groups, list) or any(not isinstance(group, list) or not group or
                    any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}@[a-zA-Z0-9_-]+", item) for item in group)
                    for group in groups):
                raise ValueError("Invalid linked device IDs")
            return groups
        except (OSError, ValueError) as exc:
            raise ControlError(f"Cannot read keyboard connection links: {exc}") from exc

    def link(self, first, second):
        from .config import ConfigStore, atomic_write
        if not all(isinstance(item, str) and re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}@[a-zA-Z0-9_-]+", item) for item in (first, second)):
            raise ControlError("Connection links require full physical device IDs.")
        with ConfigStore(self.path).lock():
            groups = self.read()
            merged = {first, second}
            remaining = []
            for group in groups:
                if merged.intersection(group):
                    merged.update(group)
                else:
                    remaining.append(group)
            remaining.append(sorted(merged))
            atomic_write(self.path, remaining)
        return sorted(merged)

    def aliases(self, selected):
        return [item for group in self.read() if selected in group for item in group if item != selected]


def resolve_config_device(config_path, device_id, devices=None):
    candidates = discover_devices() if devices is None else devices
    try:
        return resolve_device(device_id, candidates)
    except DeviceSelectionError as original:
        aliases = ConnectionStore(config_path).aliases(device_id)
        matches = [device for device in candidates if device["id"] in aliases]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DeviceSelectionError("Multiple linked keyboard connections are present; select the active connection explicitly.")
        raise original
