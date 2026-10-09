"""Reversible evdev/uinput keyboard remapping for one explicitly selected HID.

This module never writes keyboard firmware.  Grabs last only for this process;
all opened nodes, held output keys, and grabs are released in ``finally`` blocks.
Python-evdev is imported only when remapping or observing input is requested.
"""

from __future__ import annotations

from collections import Counter
import importlib
import json
import logging
import math
import os
from pathlib import Path
import select
import signal
import threading
import time

from .devices import DeviceSelectionError, VIRTUAL_NAME, physical_family, resolve_device, resolve_config_device
from .errors import ControlError


LOG = logging.getLogger(__name__)
WHEEL_SOURCES = {"REL_WHEEL_UP", "REL_WHEEL_DOWN", "REL_HWHEEL_LEFT", "REL_HWHEEL_RIGHT"}
SCROLL_ACTIONS = {"scroll-up", "scroll-down", "scroll-left", "scroll-right"}


class RemapError(ControlError, RuntimeError):
    """An actionable input configuration, access, or dependency error."""


def _evdev():
    try:
        return importlib.import_module("evdev")
    except ImportError as exc:
        raise RemapError("Input remapping needs python-evdev. Install python3-evdev with your distribution package manager (or pip install evdev).") from exc


def _config(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RemapError(f"Cannot read configuration {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RemapError("Input configuration must be an object with version 1.")
    if not isinstance(data.get("bindings", {}), dict):
        raise RemapError("Configuration bindings must be an object.")
    return data


def compile_bindings(bindings: dict, codes) -> dict:
    """Validate and translate binding strings into immutable runtime actions."""
    result = {}
    for source, destination in bindings.items():
        if not isinstance(source, str) or not (
            source in WHEEL_SOURCES or
            (source.startswith("KEY_") and source in codes.ecodes and source not in ("KEY_MAX", "KEY_CNT"))
        ):
            raise RemapError(f"Unknown binding source {source!r}.")
        if not isinstance(destination, str):
            raise RemapError(f"Binding destination for {source} must be text.")
        if destination in ("default", "disabled") or destination in SCROLL_ACTIONS:
            result[source] = destination
            continue
        keys = destination.split("+")
        if not keys or any(not key.startswith("KEY_") or key not in codes.ecodes or key in ("KEY_MAX", "KEY_CNT") for key in keys):
            raise RemapError(f"Invalid destination {destination!r}; use KEY_NAME, a KEY_* chord, scroll-up/down/left/right, disabled, or default.")
        values = tuple(codes.ecodes[key] for key in keys)
        if len(set(values)) != len(values):
            raise RemapError(f"Destination chord {destination!r} repeats a key.")
        result[source] = values
    aliases = {}
    for source, action in result.items():
        if source in WHEEL_SOURCES:
            continue
        number = codes.ecodes[source]
        if number in aliases and aliases[number][1] != action:
            raise RemapError(f"{source} and {aliases[number][0]} are aliases of the same input key; give them one binding.")
        aliases[number] = (source, action)
    return result


def _key_name(codes, code: int) -> str:
    name = codes.bytype.get(codes.EV_KEY, {}).get(code, f"KEY_{code}")
    if isinstance(name, (list, tuple)):
        return next((value for value in name if value.startswith("KEY_")), name[0])
    return name


def _has_effective_bindings(bindings: dict) -> bool:
    return any(destination != "default" and destination != source
               for source, destination in bindings.items())


def _verify_opened(device, selected: dict) -> None:
    if (device.info.vendor != selected["vendor_id"] or device.info.product != selected["product_id"]
            or device.name.startswith(VIRTUAL_NAME)
            or device.phys.startswith("redragon-control/")):
        raise RemapError(f"Input node {device.path} changed identity; select the keyboard again.")
    family = selected.get("physical_path", "")
    if device.phys and not family.startswith("/") and physical_family(device.phys) != family:
        raise RemapError(f"Input node {device.path} belongs to another physical device; refusing to grab it.")


class InputMapper:
    """Pure event-routing state; injectable virtual output makes it unit-testable."""

    def __init__(self, output, codes, bindings: dict):
        self.output, self.codes = output, codes
        self.bindings = compile_bindings(bindings, codes)
        self.key_bindings = {codes.ecodes[source]: action for source, action in self.bindings.items()
                             if source not in WHEEL_SOURCES}
        self.held: dict[tuple[str, int], tuple[int, ...]] = {}
        self.counts: Counter = Counter()
        self.physical_down: set[tuple[str, int]] = set()
        self.ignored: set[tuple[str, int]] = set()
        self.dropped: set[str] = set()
        self.highres: dict[tuple[str, int], int] = {}

    def ignore_initial_keys(self, source: str, keys) -> None:
        self.ignored.update((source, code) for code in keys)

    def _press(self, keys: tuple[int, ...]) -> None:
        for key in keys:
            if not self.counts[key]:
                self.output.write(self.codes.EV_KEY, key, 1)
            self.counts[key] += 1

    def _release(self, keys: tuple[int, ...]) -> None:
        for key in reversed(keys):
            if self.counts[key]:
                self.counts[key] -= 1
                if not self.counts[key]:
                    del self.counts[key]
                    self.output.write(self.codes.EV_KEY, key, 0)

    def release_all(self, source: str | None = None) -> None:
        for token in list(self.held):
            if source is None or token[0] == source:
                self._release(self.held.pop(token))
        if source is None:
            self.highres.clear()
        else:
            self.highres = {token: value for token, value in self.highres.items() if token[0] != source}
        self.output.syn()

    def update_bindings(self, bindings: dict) -> None:
        translated = compile_bindings(bindings, self.codes)
        if translated == self.bindings:
            return
        self.release_all()
        self.ignored.update(self.physical_down)
        self.physical_down.clear()
        self.bindings = translated
        self.key_bindings = {self.codes.ecodes[source]: action for source, action in translated.items()
                             if source not in WHEEL_SOURCES}

    def _scroll(self, action: str) -> None:
        horizontal = action in ("scroll-left", "scroll-right")
        code = self.codes.REL_HWHEEL if horizontal else self.codes.REL_WHEEL
        value = 1 if action in ("scroll-up", "scroll-right") else -1
        self.output.write(self.codes.EV_REL, code, value)
        hi_name = "REL_HWHEEL_HI_RES" if horizontal else "REL_WHEEL_HI_RES"
        if hasattr(self.codes, hi_name):
            self.output.write(self.codes.EV_REL, getattr(self.codes, hi_name), value * 120)

    def process(self, source: str, event, device=None) -> None:
        e = self.codes
        if event.type == e.EV_SYN and event.code == e.SYN_DROPPED:
            self.release_all(source)
            self.physical_down = {token for token in self.physical_down if token[0] != source}
            self.ignored = {token for token in self.ignored if token[0] != source}
            self.dropped.add(source)
            return
        if source in self.dropped:
            if event.type == e.EV_SYN and event.code == e.SYN_REPORT:
                self.dropped.remove(source)
                if device is not None:
                    self.ignore_initial_keys(source, device.active_keys())
            return
        if event.type == e.EV_KEY:
            token = (source, event.code)
            if token in self.ignored:
                if event.value == 0:
                    self.ignored.discard(token)
                return
            action = self.key_bindings.get(event.code, "default")
            if action == "default":
                action = (event.code,)
            if event.value == 1:
                if token in self.physical_down:
                    return
                self.physical_down.add(token)
                if isinstance(action, tuple):
                    self.held[token] = action
                    self._press(action)
                elif action in SCROLL_ACTIONS:
                    self._scroll(action)
            elif event.value == 0:
                self.physical_down.discard(token)
                self._release(self.held.pop(token, ()))
            elif event.value == 2 and token in self.physical_down:
                held = self.held.get(token)
                if held:
                    self.output.write(e.EV_KEY, held[-1], 2)
                elif action in SCROLL_ACTIONS:
                    self._scroll(action)
            return
        wheel_axes = {e.REL_WHEEL: ("REL_WHEEL_UP", "REL_WHEEL_DOWN"),
                      e.REL_HWHEEL: ("REL_HWHEEL_RIGHT", "REL_HWHEEL_LEFT")}
        high_axes = {}
        for name, low in (("REL_WHEEL_HI_RES", e.REL_WHEEL), ("REL_HWHEEL_HI_RES", e.REL_HWHEEL)):
            if hasattr(e, name):
                high_axes[getattr(e, name)] = low
        if event.type == e.EV_REL and (event.code in wheel_axes or event.code in high_axes) and event.value:
            low = high_axes.get(event.code, event.code)
            positive, negative = wheel_axes[low]
            action = self.bindings.get(positive if event.value > 0 else negative, "default")
            if action == "default":
                self.output.write_event(event)
                return
            ticks = abs(event.value)
            if event.code in high_axes:
                # Devices exposing both axes produce paired events.  Transform
                # low-resolution ticks once, suppress their high-res companions.
                if device is not None and low in device.capabilities().get(e.EV_REL, []):
                    return
                token = (source, event.code)
                total = self.highres.get(token, 0) + event.value
                signed_ticks = int(total / 120)
                self.highres[token] = total - signed_ticks * 120
                ticks = abs(signed_ticks)
            for _ in range(ticks):
                if isinstance(action, tuple):
                    self._press(action)
                    self._release(action)
                elif action in SCROLL_ACTIONS:
                    self._scroll(action)
            return
        self.output.write_event(event)


def _capabilities(devices: list, codes) -> dict:
    result: dict = {}
    for device in devices:
        for event_type, values in device.capabilities(absinfo=True).items():
            if event_type in (codes.EV_SYN, codes.EV_FF, getattr(codes, "EV_FF_STATUS", -1)):
                continue
            merged = result.setdefault(event_type, [])
            existing = {item[0] if isinstance(item, tuple) else item for item in merged}
            for item in values:
                key = item[0] if isinstance(item, tuple) else item
                if key not in existing:
                    merged.append(item)
                    existing.add(key)
    # Allow every key/chord and scroll destination without rebuilding the virtual
    # device when a saved configuration changes.
    key_codes = set()
    for value, names in codes.bytype[codes.EV_KEY].items():
        names = names if isinstance(names, (list, tuple)) else [names]
        if 0 < value <= getattr(codes, "KEY_MAX", 0x2FF) and any(
                name.startswith("KEY_") and name not in ("KEY_MAX", "KEY_CNT") for name in names):
            key_codes.add(value)
    # Preserve physical mouse buttons without advertising every joystick/touch
    # button, which would misclassify a keyboard as other input device types.
    result[codes.EV_KEY] = sorted(set(result.get(codes.EV_KEY, [])) | key_codes)
    result[codes.EV_REL] = sorted(set(result.get(codes.EV_REL, [])) | {
        getattr(codes, name) for name in ("REL_WHEEL", "REL_HWHEEL", "REL_WHEEL_HI_RES", "REL_HWHEEL_HI_RES") if hasattr(codes, name)})
    return result


class RemapDaemon:
    def __init__(self, config_path: str | os.PathLike, stop_event=None, on_ready=None):
        self.config_path = Path(config_path)
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.on_ready = on_ready
        self._reported_ready = False

    def _resolve(self, device_id):
        return resolve_config_device(self.config_path, device_id)

    def _ready(self) -> None:
        if not self._reported_ready:
            if self.on_ready is not None:
                self.on_ready()
            self._reported_ready = True

    def validate_runtime(self) -> dict:
        """Read-only preflight; never creates a virtual device or grabs input."""
        module = _evdev()
        data = _config(self.config_path)
        compile_bindings(data.get("bindings", {}), module.ecodes)
        selected = self._resolve(data.get("device_id"))
        if not selected["event_paths"]:
            raise RemapError("The selected device has no Linux input events.")
        for path in selected["event_paths"]:
            if not os.access(path, os.R_OK):
                raise RemapError(f"Input access denied ({path}). Install the supplied device-scoped udev rules and reconnect the keyboard.")
        if _has_effective_bindings(data.get("bindings", {})) and not os.access("/dev/uinput", os.W_OK):
            raise RemapError("Cannot access /dev/uinput. Install the supplied udev rule and ensure the uinput kernel module is loaded.")
        return selected

    def run(self) -> None:
        """Run until stopped, deselected, interrupted, or an input node fails.

        Disconnects fail cleanly with an actionable error.  Restarting the
        service reconnects only the saved physical device, never a substitute.
        """
        module = _evdev()
        data = _config(self.config_path)
        self._resolve(data.get("device_id"))
        while not self.stop_event.is_set():
            compile_bindings(data.get("bindings", {}), module.ecodes)
            replacement = (self._session(module, data) if _has_effective_bindings(data.get("bindings", {}))
                           else self._idle(module, data))
            if replacement is None or not replacement.get("device_id"):
                return
            data = replacement

    def _idle(self, module, data: dict) -> dict | None:
        # A profile with only defaults does not need an input grab or uinput.
        # Keep watching so its first real binding activates automatically.
        self._ready()
        last_contents = None
        while not self.stop_event.is_set():
            try:
                contents = self.config_path.read_bytes()
                if contents != last_contents:
                    last_contents = contents
                    replacement = _config(self.config_path)
                    compile_bindings(replacement.get("bindings", {}), module.ecodes)
                    if (replacement.get("device_id") != data.get("device_id")
                            or _has_effective_bindings(replacement.get("bindings", {}))):
                        return replacement
                    data = replacement
            except (RemapError, OSError) as exc:
                LOG.warning("Ignoring invalid input configuration; previous bindings remain active: %s", exc)
            self.stop_event.wait(0.25)
        return None

    def _session(self, module, data: dict) -> dict | None:
        selected = self._resolve(data.get("device_id"))
        if not selected["event_paths"]:
            raise RemapError("The selected device has no Linux input events. Use USB cable or its wireless receiver and list devices again.")
        devices, grabbed = [], []
        output = mapper = None
        try:
            compile_bindings(data.get("bindings", {}), module.ecodes)
            for path in selected["event_paths"]:
                device = module.InputDevice(path)
                devices.append(device)
                _verify_opened(device, selected)
            output = module.UInput(_capabilities(devices, module.ecodes),
                name=f"{VIRTUAL_NAME} virtual keyboard", phys=f'redragon-control/{selected["id"]}',
                vendor=0x1209, product=0xD686)
            mapper = InputMapper(output, module.ecodes, data.get("bindings", {}))
            for device in devices:
                device.grab()
                grabbed.append(device)
                mapper.ignore_initial_keys(device.path, device.active_keys())
            self._ready()
            last_contents = None
            next_reload = time.monotonic()
            while not self.stop_event.is_set():
                if time.monotonic() >= next_reload:
                    next_reload = time.monotonic() + 0.25
                    if self._resolve(data.get('device_id'))['id'] != selected['id']:
                        return data
                    try:
                        contents = self.config_path.read_bytes()
                        if contents != last_contents:
                            last_contents = contents
                            replacement = _config(self.config_path)
                            compile_bindings(replacement.get("bindings", {}), module.ecodes)
                            if replacement.get("device_id") != data.get("device_id"):
                                return replacement
                            if not _has_effective_bindings(replacement.get("bindings", {})):
                                return replacement
                            mapper.update_bindings(replacement.get("bindings", {}))
                            data = replacement
                    except (RemapError, OSError) as exc:
                        LOG.warning("Ignoring invalid input configuration; previous bindings remain active: %s", exc)
                ready, _, _ = select.select(devices, [], [], 0.1)
                for device in ready:
                    try:
                        for event in device.read():
                            mapper.process(device.path, event, device)
                    except BlockingIOError:
                        continue
            return None
        except PermissionError as exc:
            raise RemapError(f"Input access denied ({exc.filename or '/dev/uinput'}). Install the supplied device-scoped udev rules, reconnect the keyboard, and sign in again if group membership changed.") from exc
        except OSError as exc:
            raise RemapError(f"Input remapping stopped: {exc}. Original input access has been restored; reconnect the selected keyboard and restart remapping.") from exc
        finally:
            # Each cleanup is independent: a failed release must never skip the
            # ungrab/close of another composite interface.
            if mapper is not None:
                try:
                    mapper.release_all()
                except Exception:
                    LOG.debug("Could not release virtual keys during cleanup", exc_info=True)
            for device in reversed(grabbed):
                try:
                    device.ungrab()
                except Exception:
                    LOG.debug("Could not ungrab %s", device.path, exc_info=True)
            if output is not None:
                try:
                    output.close()
                except Exception:
                    LOG.debug("Could not close virtual input", exc_info=True)
            for device in devices:
                try:
                    device.close()
                except Exception:
                    LOG.debug("Could not close %s", device.path, exc_info=True)


def run_remapper(config_path: str | os.PathLike, stop_event=None) -> None:
    """Run the remapper with signal-driven cleanup when called on the main thread."""
    daemon = RemapDaemon(config_path, stop_event)
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def stop(signum, frame):
            daemon.stop_event.set()
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, stop)
    try:
        daemon.run()
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def observe_events(device_id: str, limit: int = 50, timeout: float = 10.0):
    """Yield structured events for learning buttons, without grabbing or writing.

    The timeout is a total deadline.  Closing this generator also closes every
    input node; callers that stop early should use ``contextlib.closing``.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise RemapError("Event limit must be a positive integer.")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise RemapError("Event timeout must be a finite positive number.")
    module = _evdev()
    selected = resolve_device(device_id)
    if not selected["event_paths"]:
        raise RemapError("The selected device has no Linux input events to observe.")
    devices = []
    try:
        for path in selected["event_paths"]:
            device = module.InputDevice(path)
            devices.append(device)
            _verify_opened(device, selected)
        deadline = time.monotonic() + timeout
        count = 0
        while count < limit:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            ready, _, _ = select.select(devices, [], [], min(remaining, 0.25))
            for device in ready:
                try:
                    events = device.read()
                    for event in events:
                        names = module.ecodes.bytype.get(event.type, {})
                        code_name = names.get(event.code, str(event.code))
                        if isinstance(code_name, (list, tuple)):
                            code_name = next((name for name in code_name if name.startswith("KEY_")), code_name[0])
                        source = code_name
                        if event.type == module.ecodes.EV_REL and event.value:
                            if event.code in (module.ecodes.REL_WHEEL, getattr(module.ecodes, "REL_WHEEL_HI_RES", -1)):
                                source = "REL_WHEEL_UP" if event.value > 0 else "REL_WHEEL_DOWN"
                            elif event.code in (module.ecodes.REL_HWHEEL, getattr(module.ecodes, "REL_HWHEEL_HI_RES", -1)):
                                source = "REL_HWHEEL_RIGHT" if event.value > 0 else "REL_HWHEEL_LEFT"
                        yield {"device_id": selected["id"], "event_path": device.path,
                               "timestamp": event.timestamp(), "type": event.type,
                               "code": event.code, "code_name": code_name,
                               "value": event.value, "source": source}
                        count += 1
                        if count >= limit:
                            return
                except BlockingIOError:
                    continue
    except PermissionError as exc:
        raise RemapError(f"Input access denied ({exc.filename or 'selected keyboard'}). Install the supplied device-scoped udev rules and reconnect the keyboard.") from exc
    except OSError as exc:
        raise RemapError(f"Event observation stopped: {exc}. Reconnect the selected keyboard and try again.") from exc
    finally:
        for device in devices:
            try:
                device.close()
            except Exception:
                LOG.debug("Could not close observed input", exc_info=True)
