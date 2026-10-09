"""Persist background intent independently from portable keyboard profiles."""

import json
import time

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


class BackgroundSupervisor:
    """Retry enabled services after login, permission delays and reconnects."""
    def __init__(self, controller):
        self.controller = controller
        self.preferences = BackgroundStore(controller.store.path)
        self.retry_after = {"remap": 0, "rgb": 0}
        self.errors = {}

    def tick(self):
        desired = self.preferences.read()
        state = self.controller.status()
        for kind, status_key in (("remap", "daemon"), ("rgb", "lighting_daemon")):
            running = state[status_key]["running"]
            if not desired[kind]:
                self.errors.pop(kind, None)
                if running:
                    runtime.stop_daemon(self.controller.store.path, kind)
            elif running:
                self.errors.pop(kind, None)
            elif state["device"] is not None and time.monotonic() >= self.retry_after[kind]:
                self.retry_after[kind] = time.monotonic() + 10
                try:
                    runtime.start_daemon(self.controller.store.path, kind)
                    # Respect a pause/reset requested while the process started.
                    if not self.preferences.read()[kind]:
                        runtime.stop_daemon(self.controller.store.path, kind)
                    self.errors.pop(kind, None)
                except (ControlError, OSError) as exc:
                    self.errors[kind] = str(exc)
        return self.controller.status()
