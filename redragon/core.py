"""Shared application operations. The CLI and native UI use the same state."""

from copy import deepcopy
from pathlib import Path
import re

from .config import ConfigStore, DEFAULTS, atomic_write, read_json
from .devices import discover_devices, resolve_device, resolve_config_device, ConnectionStore
from .errors import ControlError
from . import runtime

RESET_MESSAGE = (
    "On the K686 MAX, hold Fn + Esc for 3 seconds to restore the keyboard's factory defaults. "
    "Close the app first. The Fn key is handled inside the keyboard, so software cannot "
    "press this combination for you. This erases the keyboard's custom settings."
)
MANUAL_URL = "https://cdn.shopify.com/s/files/1/0012/4957/4961/files/K686_user_manual.pdf?v=1723515517"


class Controller:
    def __init__(self, config_path=None, demo=False):
        self.demo = demo
        self.store = ConfigStore(config_path)
        self._demo_config = deepcopy(DEFAULTS)
        self._demo_config["device_id"] = "258a:010c@demo"
        self._demo_running = False

    def _config(self):
        return deepcopy(self._demo_config) if self.demo else self.store.read()

    def _update(self, operation):
        if self.demo:
            from .config import validate_config
            config = self._config()
            operation(config)
            self._demo_config = validate_config(config)
            return deepcopy(self._demo_config)
        return self.store.update(operation)

    def _devices(self):
        if self.demo:
            return [{"id": "258a:010c@demo", "vendor_id": 0x258a, "product_id": 0x010c,
                     "name": "Redragon K686 MAX · Demo", "transport": "USB", "accessible": True,
                     "hidraw_paths": [], "event_paths": [], "physical_path": "demo"}]
        return discover_devices()

    def _device(self):
        device_id = self._config()["device_id"]
        if not device_id:
            return None
        try:
            return resolve_config_device(self.store.path, device_id, self._devices()) if not self.demo else resolve_device(device_id, self._devices())
        except ControlError:
            return None

    def _lighting(self):
        from .lighting import LightingBackend
        return LightingBackend(self._device())

    def status(self):
        device = self._device()
        if self.demo:
            capabilities = {"rgb": True, "factory_reset": False, "remap": False, "modes": ["static", "off"]}
            message = "Demo preview. Changes here do not affect your keyboard or saved settings."
        else:
            capabilities = self._lighting().capabilities()
            message = capabilities.get("message", "")
            capabilities["remap"] = False
        return {"device": device, "devices": self._devices(), "config": self._config(),
                "capabilities": capabilities, "rgb_message": message,
                "factory_reset_message": RESET_MESSAGE, "manual_url": MANUAL_URL,
                "daemon": {"running": self._demo_running} if self.demo else runtime.daemon_status(self.store.path),
                "lighting_daemon": {"running": False} if self.demo else runtime.daemon_status(self.store.path, "rgb"),
                "background": {"remap": False, "rgb": False},
                "linked_device_ids": [] if self.demo else ConnectionStore(self.store.path).aliases(self._config()["device_id"]),
                "lighting_state": {} if self.demo else self._saved_lighting_state(),
                "appearance": self.appearance(), "demo": self.demo}

    def _saved_lighting_state(self):
        import json
        from .native_lighting import backup_path
        path = backup_path(self.store.path)
        if not path.exists():
            return {}
        try:
            saved = json.loads(path.read_text())
            device_id = self._config()['device_id']
            matches = saved['device_id'] == device_id or saved['device_id'] in ConnectionStore(self.store.path).aliases(device_id)
            return {'recovery_available': matches, 'saved_on_keyboard': matches and saved.get('committed', False),
                    'lighting': saved.get('lighting', {}) if matches else {}}
        except (OSError, ValueError, KeyError, TypeError):
            return {'recovery_available': True, 'saved_on_keyboard': False}

    def appearance(self):
        from .appearance import AppearanceStore, resolve_theme
        choice = getattr(self, '_demo_theme', 'auto') if self.demo else AppearanceStore(self.store.path).read()['theme']
        return {'theme': choice, 'resolved_theme': resolve_theme(choice)}

    def set_theme(self, theme):
        from .appearance import AppearanceStore, THEMES
        if theme not in THEMES:
            raise ControlError('Choose Automatic, Adwaita or Omarchy.')
        if self.demo:
            self._demo_theme = theme
        else:
            AppearanceStore(self.store.path).set(theme)
        return self.appearance()

    def select_device(self, device_id):
        device = resolve_device(device_id, self._devices())
        if not self.demo:
            runtime.stop_daemon(self.store.path)
            runtime.stop_daemon(self.store.path, "rgb")
        return self._update(lambda config: config.update(device_id=device["id"]))

    def link_device(self, device_id):
        if self.demo:
            raise ControlError("Linking connections requires a real keyboard.")
        anchor = self._config()["device_id"]
        if not anchor:
            raise ControlError("Select the keyboard's first connection before linking another.")
        device = resolve_device(device_id, self._devices())
        ids = {anchor.split("@")[0], device["id"].split("@")[0]}
        if ids != {"258a:010c", "3554:fa09"}:
            raise ControlError("Link only the K686 wired connection and its 2.4 GHz receiver.")
        return {"linked_device_ids": ConnectionStore(self.store.path).link(anchor, device["id"])}

    def set_lighting(self, mode=None, color=None, brightness=None, speed=None, apply=False):
        changes = {k: v for k, v in locals().items() if k in ("mode", "color", "brightness", "speed") and v is not None}
        config = self._update(lambda config: config["lighting"].update(changes))
        result = {"saved": True, "applied": False, "lighting": config["lighting"],
                  "live_reload": False}
        if apply:
            result.update(self.apply_lighting())
        return result

    def apply_lighting(self):
        if self.demo:
            return {"applied": False, "demo": True, "message": "Demo preview only."}
        # Stop old input/tray workers before the single lighting transaction.
        self.retire_background()
        backend = self._lighting()
        try:
            if not backend.capabilities()['rgb']:
                raise ControlError(backend.capabilities()['message'])
            result = backend.apply_native(self._config()['lighting'], self.store.path)
        finally:
            if hasattr(backend, "close"):
                backend.close()
        return {**result, "applied": True, "daemon": {"running": False}, "software_effect": False}

    def restore_lighting(self):
        if self.demo:
            return {'restored': False, 'demo': True}
        self.retire_background()
        backend = self._lighting()
        try:
            return backend.restore_native(self.store.path)
        finally:
            backend.close()

    def detect_keyboard(self):
        """Select a sole connected keyboard; leave ambiguous choices to the user."""
        from .setup import keyboard_candidates
        state = self.status()
        candidates = keyboard_candidates(state['devices'])
        if state['device'] not in candidates and len(candidates) == 1:
            self.select_device(candidates[0]['id'])
            state = self.status()
        state['devices'] = keyboard_candidates(state['devices'])
        if state['device'] not in state['devices']:
            state['device'] = None
        return state

    def start_daemon(self):
        raise ControlError("Key and wheel remapping have been removed because they require continuous input interception, which can cause missed or repeated keystrokes.")

    def retire_background(self):
        if self.demo:
            return
        from .config import default_path
        if self.store.path.resolve() == default_path().resolve():
            from .autostart import disable
            disable()
        from .background import retire
        from .runtime import stop_legacy_trays
        try:
            stop_legacy_trays(self.store.path)
        finally:
            # Disable persisted intent and release input even if an old tray
            # cannot finish quitting; it must not keep restarting workers.
            retire(self)

    def _background_enabled(self, kind, enabled):
        if not self.demo:
            from .background import BackgroundStore
            BackgroundStore(self.store.path).set(kind, enabled)

    def stop_daemon(self):
        if self.demo:
            self._demo_running = False
            return {"running": False, "demo": True}
        self._background_enabled("remap", False)
        return runtime.stop_daemon(self.store.path)

    def stop_lighting(self):
        if self.demo:
            return {"running": False, "demo": True}
        self._background_enabled("rgb", False)
        return runtime.stop_daemon(self.store.path, "rgb")

    def stop_all(self):
        self.retire_background()
        return {"remap": {"running": False}, "rgb": {"running": False}}

    def reset_app(self):
        self.stop_all()
        # Preserve the explicit hardware selection; clear all remaps and local lighting preferences.
        if self.demo:
            config = deepcopy(DEFAULTS)
            config["device_id"] = self._demo_config["device_id"]
            self._demo_config = config
        else:
            config = self.store.reset()
        return {"reset": "app", "hardware_reset": False, "config": config}

    def factory_reset(self):
        self.stop_all()
        return {"hardware_reset": False, "manual_action_required": True,
                "message": RESET_MESSAGE, "manual_url": MANUAL_URL}

    def export_profile(self, path):
        if self.demo:
            raise ControlError("Exporting profiles is unavailable in demo mode.")
        atomic_write(path, self._config())
        return {"exported": str(Path(path).resolve())}

    def import_profile(self, path):
        config = read_json(path)
        # Profiles carry bindings/lighting; they cannot silently change the selected keyboard.
        if self.demo:
            config["device_id"] = self._demo_config["device_id"]
            self._demo_config = config
        else:
            self.store.update(lambda current: current.update(lighting=config["lighting"], bindings=config["bindings"]))
        return {"imported": str(Path(path).resolve()), "applied": False,
                "live_reload": {"remap": False, "rgb": False}}

    def _profile_path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"[\w -]{1,64}", name) or name in (".", ".."):
            raise ControlError("Use a profile name of 1–64 letters, numbers, spaces, underscores or hyphens.")
        return self.store.path.parent / "profiles" / f"{name}.json"

    def list_profiles(self):
        directory = self.store.path.parent / "profiles"
        return sorted(path.stem for path in directory.glob("*.json"))

    def save_profile(self, name):
        if self.demo:
            raise ControlError("Saving profiles is unavailable in demo mode.")
        return self.export_profile(self._profile_path(name))

    def load_profile(self, name):
        return self.import_profile(self._profile_path(name))
