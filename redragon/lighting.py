"""Model-gated direct RGB and onboard effects for the K686 MAX.

Native effects use the verified wireless configuration transaction with recovery.
There is no guessed factory-reset or firmware command.
See docs/protocol.md for provenance and the keepalive requirement.
"""

from __future__ import annotations

import colorsys
import fcntl
import math
import os
import re
import struct
import select
import time
from pathlib import Path

from .devices import physical_family
from .errors import ControlError
from .effects import NATIVE_EFFECTS

WIRED_ID = (0x258A, 0x010C)
WIRELESS_ID = (0x3554, 0xFA09)
WIRELESS_PSD = bytes.fromhex("03 00 00 00 01 20")
K686_MODEL_IDS = frozenset((0x05, 0x20))
REPORT_SIZE = 520
LED_COUNT = 113
DIRECT_MODES = ("static", "off")
FACTORY_RESET_INSTRUCTIONS = "Hold Fn + Esc on the keyboard for 3 seconds."


class _UnverifiedModel(ControlError):
    def __init__(self, response: bytes):
        self.model_id = response[13] if len(response) > 13 else None
        self.response_header = response[:32].hex(" ")
        super().__init__(f"Refusing RGB writes: firmware model {self.model_id!r} is not a verified K686 (0x05 or 0x20).")


def _ioc(number: int, size: int, direction: int = 3) -> int:
    """Linux HIDIOCSFEATURE/HIDIOCGFEATURE (_IOWR, asm-generic ABI)."""
    return (direction << 30) | (size << 16) | (ord("H") << 8) | number


def _report_size(path: str, report_id: int, main_tag: int) -> int:
    """Read the descriptor, never query an unrelated HID interface."""
    name = Path(path).name
    if not re.fullmatch(r"hidraw\d+", name):
        return 0
    try:
        data = (Path("/sys/class/hidraw") / name / "device/report_descriptor").read_bytes()
    except OSError:
        return 0
    report_size = report_count = current_id = 0
    stack: list[tuple[int, int, int]] = []
    bits: dict[int, int] = {}
    offset = 0
    while offset < len(data):
        prefix = data[offset]
        offset += 1
        if prefix == 0xFE:
            if offset + 2 > len(data):
                return 0
            length = data[offset]
            offset += 2 + length
            continue
        length = (0, 1, 2, 4)[prefix & 3]
        if offset + length > len(data):
            return 0
        value = int.from_bytes(data[offset:offset + length], "little")
        offset += length
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1:
            if tag == 7:
                report_size = value
            elif tag == 8:
                current_id = value
            elif tag == 9:
                report_count = value
            elif tag == 10:
                stack.append((report_size, report_count, current_id))
            elif tag == 11 and stack:
                report_size, report_count, current_id = stack.pop()
        elif kind == 0 and tag == main_tag:
            bits[current_id] = bits.get(current_id, 0) + report_size * report_count
    return (bits.get(report_id, 0) + 7) // 8 + (1 if report_id in bits else 0)


def _feature_report_size(path, report_id):
    return _report_size(path, report_id, 11)


def _output_report_size(path, report_id):
    return _report_size(path, report_id, 9)


def wireless_packet(command, pages=0, sequence=0, payload=b""):
    if len(payload) > 15:
        raise ControlError("Wireless payload is too large.")
    packet = bytearray(20)
    packet[:4] = bytes((0x13, command, pages, sequence))
    packet[4:4 + len(payload)] = payload
    packet[-1] = sum(packet[:-1]) & 255
    return bytes(packet)


def wireless_frames(settings):
    """Volatile audio/direct RGB: grouped colors, no flash/config commands."""
    rgb = direct_packet(settings)[8:11]
    if rgb == b"\0\0\0":
        return [wireless_packet(0x88, 1, 0, b"\x23")]
    data = rgb + bytes((LED_COUNT,)) + bytes(range(LED_COUNT))
    chunks = [data[i:i + 14] for i in range(0, len(data), 14)]
    return [wireless_packet(0x88, len(chunks), i, bytes((0x10 + len(chunk),)) + chunk)
            for i, chunk in enumerate(chunks)]


class _FeatureDevice:
    def __init__(self, path: str):
        self.path = path
        self.fd = -1

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CLOEXEC)
        return self

    def __exit__(self, *_):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def send(self, packet: bytes) -> None:
        buffer = bytearray(packet)
        result = fcntl.ioctl(self.fd, _ioc(0x06, len(buffer)), buffer, True)
        if result != len(buffer):
            raise ControlError("The keyboard did not accept the complete RGB feature report.")

    def receive(self) -> bytes:
        buffer = bytearray(REPORT_SIZE)
        buffer[0] = 0x06
        result = fcntl.ioctl(self.fd, _ioc(0x07, len(buffer)), buffer, True)
        if result < 14:
            raise ControlError("The keyboard returned an incomplete model response.")
        return bytes(buffer[:result])

    def send_output(self, packet):
        if os.write(self.fd, packet) != len(packet):
            raise ControlError("Incomplete wireless RGB output report.")

    def wireless_model(self):
        self.send_output(wireless_packet(0x05))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.fd], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            response = os.read(self.fd, 64)
            if len(response) != 20 or response[:2] != b"\x13\x05":
                continue
            if sum(response[:-1]) & 255 != response[-1]:
                raise ControlError("Wireless model response has an invalid checksum.")
            if response[2:5] != b"\x01\x00\x0a" or response[5:11] != WIRELESS_PSD:
                raise ControlError("Receiver is not paired with a verified K686 MAX; refusing lighting writes.")
            return response[10]
        raise ControlError("Receiver did not answer. Wake the keyboard and select its 2.4 GHz mode.")

    def identity(self) -> dict:
        """Read identity from the opened fd, which cannot follow a recycled path."""
        info = bytearray(8)
        fcntl.ioctl(self.fd, _ioc(0x03, len(info), 2), info, True)
        bus, vendor, product = struct.unpack("Ihh", info)
        physical = bytearray(512)
        fcntl.ioctl(self.fd, _ioc(0x05, len(physical), 2), physical, True)
        node = os.fstat(self.fd).st_rdev
        sysfs_device = Path(f"/sys/dev/char/{os.major(node)}:{os.minor(node)}/device").resolve()
        return {
            "bus": bus, "vendor_id": vendor & 0xFFFF, "product_id": product & 0xFFFF,
            "physical_path": physical.split(b"\0", 1)[0].decode("utf-8", errors="replace"),
            "sysfs_device": str(sysfs_device),
        }


def _percent(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        raise ControlError(f"{name} must be a number from 0 to 100.")
    return value


def direct_packet(settings: dict) -> bytes:
    """Build a volatile RGB frame; this function performs no hardware I/O."""
    mode = settings.get("mode", "static")
    if mode not in DIRECT_MODES:
        raise ControlError(f"{mode} requires the lighting daemon; direct writes support static and off.")
    color = settings.get("color", "#e01b24")
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ControlError("RGB colour must use #RRGGBB format.")
    brightness = _percent(settings.get("brightness", 70), "Brightness")
    rgb = (0, 0, 0) if mode == "off" else tuple(
        round(int(color[index:index + 2], 16) * brightness / 100) for index in (1, 3, 5)
    )
    packet = bytearray(REPORT_SIZE)
    packet[:8] = bytes((0x06, 0x08, 0, 0, 0x01, 0, 0x7A, 0x01))
    packet[8:8 + LED_COUNT * 3] = bytes(rgb) * LED_COUNT
    return bytes(packet)


def render_frame(settings: dict, elapsed: float) -> dict:
    """Legacy uniform frame helper; native modes sample the spatial preview.

    The GUI samples each key via preview.sample. Neither helper drives native
    hardware animations.
    """
    result = dict(settings)
    if result.get('mode') == 'smooth-breathing':
        result['mode'] = 'breathing'
        result['brightness'] = round(result['brightness'] * 4 / 100) * 25
        result['speed'] = round(result['speed'] * 4 / 100) * 25
    mode = result.get("mode", "static")
    if mode in DIRECT_MODES:
        return result
    if mode in NATIVE_EFFECTS and mode != 'smooth-breathing':
        from .preview import sample
        rgb = sample(dict(settings, brightness=100), elapsed, 7.5, 2.5)
        result['mode'] = 'static'
        result['brightness'] = _percent(settings.get('brightness', 70), 'Brightness')
        result['color'] = '#' + ''.join(f'{round(channel * 255):02x}' for channel in rgb)
        return result
    if mode not in ('breathing', 'rainbow'):
        raise ControlError(f"Unsupported lighting mode: {mode}")
    speed = _percent(result.get("speed", 50), "Speed")
    brightness = _percent(result.get("brightness", 70), "Brightness")
    period = 8.0 - 7.0 * speed / 100
    phase = (float(elapsed) % period) / period
    result["mode"] = "static"
    if mode == "breathing":
        # Quantize only when encoding the final 8-bit RGB channels, so the
        # fade retains sub-percent levels instead of stepping by whole percent.
        result["brightness"] = brightness * (1 + math.cos(phase * math.tau)) / 2
    else:
        rgb = colorsys.hsv_to_rgb(phase, 1, 1)
        result["color"] = "#" + "".join(f"{round(channel * 255):02x}" for channel in rgb)
    return result


# Short alias retained for callers that generate frames themselves.
frame = render_frame


class LightingBackend:
    def __init__(self, device: dict | None):
        self.device = device
        self._session: _FeatureDevice | None = None
        self._model_id: int | None = None
        self._wireless = bool(device) and (device.get("vendor_id"), device.get("product_id")) == WIRELESS_ID
        self._native = None

    def close(self) -> None:
        if self._session is not None:
            try:
                if self._native is not None:
                    self._native.restore()
            finally:
                self._session.__exit__(None, None, None)
                self._session = None
                self._model_id = None
                self._native = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def capabilities(self) -> dict:
        wired = bool(self.device) and (
            self.device.get("vendor_id"), self.device.get("product_id")
        ) == WIRED_ID
        supported = wired or self._wireless
        return {
            "rgb": supported,
            "factory_reset": False,
            "remap": False,
            "modes": list(DIRECT_MODES) + list(NATIVE_EFFECTS) if self._wireless else list(DIRECT_MODES) if supported else [],
            "native_breathing": self._wireless,
            "native_effects": self._wireless,
            "hardware_modes": list(NATIVE_EFFECTS) if self._wireless else [],
            "software_modes": [],
            "software_effects": False,
            "keepalive_required": supported,
            "requires_model_verification": supported,
            "wireless": self._wireless,
            "message": (
                "Built-in animations run on the keyboard. Static color and Off use the background lighting service. Original onboard settings are backed up and restored when stopped."
                if self._wireless else
                "Static color and Off are available over USB. Use the 2.4 GHz receiver for built-in animations; the wired native write protocol remains unverified."
                if wired else "Select the K686 USB keyboard or its 2.4 GHz receiver for RGB control."
            ),
            "factory_reset_instructions": FACTORY_RESET_INSTRUCTIONS,
        }

    def _open_verified(self) -> None:
        paths = self.device.get("hidraw_paths", [])
        candidates = [path for path in paths if
                      (_output_report_size(path, 0x13) == 20 if self._wireless else _feature_report_size(path, 0x06) == REPORT_SIZE)]
        if not candidates:
            raise ControlError("No compatible RGB HID interface was found. Reconnect the keyboard or receiver.")
        failures: list[str] = []
        for path in candidates:
            hid = _FeatureDevice(path)
            try:
                hid.__enter__()
                identity = hid.identity()
                expected_id = WIRELESS_ID if self._wireless else WIRED_ID
                if identity["bus"] != 3 or (identity["vendor_id"], identity["product_id"]) != expected_id:
                    raise ControlError("The opened RGB interface changed USB identity; reconnect and select the keyboard again.")
                expected_family = self.device.get("physical_path", "")
                if expected_family.startswith("/"):
                    matches_family = identity["sysfs_device"] == expected_family or identity["sysfs_device"].startswith(expected_family.rstrip("/") + "/")
                else:
                    matches_family = bool(expected_family) and physical_family(identity["physical_path"]) == expected_family
                if not matches_family:
                    raise ControlError("The opened RGB interface belongs to another physical device; select the keyboard again.")
                if self._wireless:
                    self._model_id = hid.wireless_model()
                    self._session = hid
                    return
                query = bytearray(REPORT_SIZE)
                query[:7] = bytes((0x06, 0x82, 0x01, 0, 0x01, 0, 0x06))
                hid.send(bytes(query))
                response = hid.receive()
                if len(response) < 14 or response[0] != 0x06 or response[13] not in K686_MODEL_IDS:
                    raise _UnverifiedModel(response)
                # Keep this open file descriptor: validation can be reused only
                # for the same opened device, never for a recycled /dev path.
                self._session = hid
                self._model_id = response[13]
                return
            except PermissionError:
                failures.append(f"Permission denied for {path}; install the supplied udev rules and reconnect the keyboard.")
            except OSError as error:
                failures.append(f"Could not communicate with {path}: {error.strerror or error}")
            except ControlError:
                hid.__exit__(None, None, None)
                raise
            hid.__exit__(None, None, None)
        raise ControlError(" ".join(failures) or "The selected RGB interface was unavailable.")

    def probe(self) -> dict:
        """Query model identity without sending a colour or configuration change."""
        if not self.capabilities()["rgb"]:
            raise ControlError(self.capabilities()["message"])
        try:
            if self._session is None:
                self._open_verified()
        except _UnverifiedModel as error:
            return {"supported": False, "model_id": error.model_id,
                    "response_header": error.response_header, "lighting_written": False,
                    "message": str(error)}
        return {"supported": True, "model_id": self._model_id,
                "backend": "compx-wireless-direct" if self._wireless else "sinowealth-wired-direct", "lighting_written": False}

    def apply(self, settings: dict) -> dict:
        if self._native is not None and self._native.path.exists():
            self._native.restore()
        packet = direct_packet(settings)  # Validate fully before opening a device.
        if not self.capabilities()["rgb"]:
            raise ControlError(self.capabilities()["message"])
        if self._session is None:
            self._open_verified()
        try:
            if self._wireless:
                for report in wireless_frames(settings):
                    self._session.send_output(report)
            else:
                self._session.send(packet)
        except (OSError, ControlError) as error:
            self.close()
            raise ControlError(f"RGB connection failed: {error}") from error
        return {
            "applied": True,
            "backend": "compx-wireless-direct" if self._wireless else "sinowealth-wired-direct",
            "model_id": self._model_id,
            "mode": settings.get("mode", "static"),
            "transient": True,
            "keepalive_required": True,
        }

    def recover_native(self, config_path):
        from .native_lighting import backup_path
        if self._wireless and backup_path(config_path).exists():
            self._native = self._native_session(config_path)
            self._native.restore()

    def apply_native(self, settings, config_path):
        if self._native is None:
            self._native = self._native_session(config_path)
        self._native.apply(settings)

    def _native_session(self, config_path):
        from .native_lighting import NativeLighting
        if not self._wireless:
            raise ControlError('Use the K686 MAX 2.4 GHz receiver for built-in effects. The wired native write protocol is not verified.')
        if self._session is None:
            self._open_verified()
        if self._model_id != 0x20:
            raise ControlError('Built-in effects are verified only for the K686 MAX firmware model 0x20.')
        return NativeLighting(self._session, self.device['id'], config_path)

    def factory_reset(self) -> dict:
        raise ControlError("A USB factory-reset command has not been verified. " + FACTORY_RESET_INSTRUCTIONS)
