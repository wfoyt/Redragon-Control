"""Validated, atomic user settings shared by the GUI, CLI and remapper."""

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from .errors import ControlError

DEFAULTS = {
    "version": 1,
    "device_id": None,
    "lighting": {"mode": "static", "color": "#e01b24", "brightness": 70, "speed": 50},
    "bindings": {},
}
from .effects import MODES
NATIVE_COLORS = ("#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff", "#ffffff")
SCROLL_SOURCES = {"REL_WHEEL_UP", "REL_WHEEL_DOWN", "REL_HWHEEL_LEFT", "REL_HWHEEL_RIGHT"}
SPECIAL_TARGETS = {"default", "disabled", "scroll-up", "scroll-down", "scroll-left", "scroll-right"}
# Linux's stable symbolic input key names; generated from input-event-codes.h.
from .keycodes import KEY_NAMES


def default_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "redragon-control" / "config.json"


def validate_binding(source, target):
    if not isinstance(source, str) or source not in KEY_NAMES | SCROLL_SOURCES:
        raise ControlError(f"Unknown input source: {source!r}. Use a Linux KEY_* name or a wheel direction.")
    if not isinstance(target, str):
        raise ControlError("A binding target must be a string.")
    if target in SPECIAL_TARGETS:
        return
    keys = target.split("+")
    if not 1 <= len(keys) <= 8 or any(key not in KEY_NAMES for key in keys) or len(keys) != len(set(keys)):
        raise ControlError(f"Invalid target: {target!r}. Use KEY_A, KEY_LEFTCTRL+KEY_C, a scroll direction, disabled, or default.")


def validate_config(value):
    value = deepcopy(value)
    if not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") != 1:
        raise ControlError("Expected a version 1 profile object.")
    if set(value) != set(DEFAULTS):
        raise ControlError("Profile must contain exactly version, device_id, lighting and bindings.")
    device = value.get("device_id")
    if device is not None and (not isinstance(device, str) or not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}(?:@[a-zA-Z0-9_-]+)?", device)):
        raise ControlError("Invalid device ID; select one from devices.")
    light = value.get("lighting")
    if not isinstance(light, dict) or set(light) != set(DEFAULTS["lighting"]):
        raise ControlError("Lighting requires mode, color, brightness and speed.")
    if light['mode'] == 'breathing':
        # Migrate profiles from the removed software effect.
        light['mode'] = 'smooth-breathing'
        if isinstance(light['color'], str) and re.fullmatch(r'#[0-9a-fA-F]{6}', light['color']):
            rgb = [int(light['color'][i:i + 2], 16) for i in (1, 3, 5)]
            light['color'] = min(NATIVE_COLORS, key=lambda c: sum(
                (a - int(c[i:i + 2], 16)) ** 2 for a, i in zip(rgb, (1, 3, 5))))
    if light["mode"] not in MODES:
        raise ControlError(f"Lighting mode must be one of {', '.join(MODES)}.")
    if not isinstance(light["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", light["color"]):
        raise ControlError("Color must be a hex RGB color, for example #e01b24.")
    if light['mode'] == 'smooth-breathing' and light['color'].lower() not in NATIVE_COLORS:
        raise ControlError('Smooth breathing uses preset colors: ' + ', '.join(NATIVE_COLORS))
    for field in ("brightness", "speed"):
        if type(light[field]) is not int or not 0 <= light[field] <= 100:
            raise ControlError(f"{field.capitalize()} must be an integer from 0 to 100.")
    bindings = value.get("bindings")
    if not isinstance(bindings, dict) or len(bindings) > 256:
        raise ControlError("Bindings must be an object containing at most 256 entries.")
    for source, target in bindings.items():
        validate_binding(source, target)
    return deepcopy(value)


def read_json(path):
    try:
        if Path(path).stat().st_size > 1024 * 1024:
            raise ControlError("Profile exceeds the 1 MB size limit.")
        return validate_config(json.loads(Path(path).read_text()))
    except (OSError, ValueError) as exc:
        raise ControlError(f"Cannot read settings at {path}: {exc}") from exc


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".redragon-", delete=False) as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise ControlError(f"Cannot save {path}: {exc}") from exc
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


class ConfigStore:
    def __init__(self, path=None):
        self.path = Path(path).expanduser().resolve() if path else default_path()

    def read(self):
        return read_json(self.path) if self.path.exists() else deepcopy(DEFAULTS)

    @contextmanager
    def lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def update(self, operation):
        with self.lock():
            result = self.read()
            operation(result)
            result = validate_config(result)
            atomic_write(self.path, result)
            return result

    def replace(self, value):
        value = validate_config(value)
        with self.lock():
            atomic_write(self.path, value)
        return value

    def reset(self):
        """Recover even when an interrupted/manual edit made settings invalid."""
        with self.lock():
            value = deepcopy(DEFAULTS)
            try:
                value["device_id"] = self.read()["device_id"]
            except ControlError:
                pass
            atomic_write(self.path, value)
            return value
