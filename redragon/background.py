"""Migrate old background preferences to disabled and release legacy workers."""

import json

from .config import ConfigStore, atomic_write
from .errors import ControlError
from . import runtime


class BackgroundStore:
    def __init__(self, config_path):
        self.path = config_path.with_name(config_path.stem + ".background.json")
        self.lock = ConfigStore(self.path).lock

    def read(self):
        defaults = {"remap": False, "rgb": False}
        if not self.path.exists():
            return defaults
        try:
            value = json.loads(self.path.read_text())
            if set(value) != set(defaults) or any(type(v) is not bool for v in value.values()):
                raise ValueError("Expected remap and rgb boolean values")
            return value
        except (OSError, ValueError, TypeError) as exc:
            raise ControlError(f"Cannot read background preferences: {exc}") from exc

    def set(self, kind, enabled):
        if kind not in ("remap", "rgb") or type(enabled) is not bool:
            raise ControlError("Invalid background service preference.")
        with self.lock():
            value = self.read()
            value[kind] = enabled
            atomic_write(self.path, value)
        return value


def retire(controller):
    """Disable old persisted intent before stopping workers, including corrupt preferences."""
    preferences = BackgroundStore(controller.store.path)
    if preferences.path.exists():
        with preferences.lock():
            atomic_write(preferences.path, {"remap": False, "rgb": False})
    errors = []
    for kind in ("remap", "rgb"):
        try:
            runtime.stop_daemon(controller.store.path, kind)
        except (ControlError, OSError) as exc:
            errors.append(str(exc))
    if errors:
        raise ControlError("; ".join(errors))
