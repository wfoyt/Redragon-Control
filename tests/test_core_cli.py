from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import fcntl
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from redragon.cli import main
from redragon.config import ConfigStore, DEFAULTS, atomic_write
from redragon.core import Controller
from redragon.devices import DeviceSelectionError
from redragon.errors import ControlError
from redragon import runtime


DEVICE = {"id": "258a:010c@aabbcc", "vendor_id": 0x258A, "product_id": 0x010C,
          "name": "Keyboard", "transport": "usb", "accessible": True,
          "event_paths": ["/dev/input/event5"], "hidraw_paths": ["/dev/hidraw5"],
          "physical_path": "test-keyboard"}


class CoreCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"

    def cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.path), *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_backend_errors_share_the_user_facing_exception_contract(self):
        self.assertTrue(issubclass(DeviceSelectionError, ControlError))

    def test_selection_error_is_machine_readable_json(self):
        with patch("redragon.core.discover_devices", return_value=[]):
            code, out, err = self.cli("select", "258a:010c")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        result = json.loads(err)
        self.assertFalse(result["ok"])
        self.assertIn("disconnected", result["error"])
        self.assertFalse(self.path.exists())

    def test_status_retains_disconnected_selection_without_throwing(self):
        value = deepcopy(DEFAULTS)
        value["device_id"] = DEVICE["id"]
        ConfigStore(self.path).replace(value)
        with patch("redragon.core.discover_devices", return_value=[]):
            code, out, err = self.cli("status")
        self.assertEqual((code, err), (0, ""))
        status = json.loads(out)["result"]
        self.assertIsNone(status["device"])
        self.assertEqual(status["config"]["device_id"], DEVICE["id"])
        self.assertFalse(status["capabilities"]["rgb"])

    def test_profile_import_preserves_explicit_hardware_selection(self):
        initial = deepcopy(DEFAULTS)
        initial["device_id"] = DEVICE["id"]
        ConfigStore(self.path).replace(initial)
        incoming = deepcopy(DEFAULTS)
        incoming["device_id"] = "3554:fa09@other"
        incoming["bindings"] = {"KEY_MUTE": "KEY_PLAYPAUSE"}
        incoming["lighting"]["color"] = "#00ff00"
        profile = self.path.parent / "incoming.json"
        atomic_write(profile, incoming)
        result = Controller(self.path).import_profile(profile)
        current = ConfigStore(self.path).read()
        self.assertFalse(result["applied"])
        self.assertEqual(current["device_id"], DEVICE["id"])
        self.assertEqual(current["bindings"], incoming["bindings"])
        self.assertEqual(current["lighting"], incoming["lighting"])

    def test_demo_never_discovers_opens_hardware_or_writes_saved_settings(self):
        controller = Controller(self.path, demo=True)
        with patch("redragon.core.discover_devices", side_effect=AssertionError("real discovery")), \
             patch("redragon.runtime.start_daemon", side_effect=AssertionError("real daemon")), \
             patch("redragon.runtime.stop_daemon", side_effect=AssertionError("real daemon")), \
             patch("redragon.runtime.daemon_status", side_effect=AssertionError("real runtime")), \
             patch("redragon.lighting._FeatureDevice", side_effect=AssertionError("real hardware")):
            state = controller.status()
            controller.select_device(state["device"]["id"])
            controller.set_lighting(mode="rainbow", apply=True)
            with self.assertRaises(ControlError):
                controller.start_daemon()
            controller.stop_all()
            controller.factory_reset()
            controller.reset_app()
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_demo_export_cannot_create_a_real_file(self):
        target = self.path.parent / "export.json"
        with self.assertRaises(ControlError):
            Controller(self.path, demo=True).export_profile(target)
        self.assertFalse(target.exists())

    def test_demo_cli_daemon_status_is_isolated_from_real_runtime(self):
        with patch("redragon.runtime.daemon_status", side_effect=AssertionError("real runtime")):
            code, out, err = self.cli("--demo", "daemon", "status", "--kind", "all")
        self.assertEqual((code, err), (0, ""))
        value = json.loads(out)["result"]
        self.assertFalse(value["remap"]["running"])
        self.assertFalse(value["rgb"]["running"])
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_reset_requires_confirmation_and_factory_reset_is_manual(self):
        code, out, err = self.cli("--demo", "reset", "app")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("--yes", json.loads(err)["error"])
        code, out, err = self.cli("--demo", "reset", "factory")
        self.assertEqual((code, err), (0, ""))
        value = json.loads(out)["result"]
        self.assertFalse(value["hardware_reset"])
        self.assertTrue(value["manual_action_required"])
        self.assertIn("Fn + Esc", value["message"])

    def test_app_reset_recovers_a_corrupted_settings_file(self):
        self.path.write_text('{"version": broken')
        with patch("redragon.core.runtime.stop_daemon", return_value={"running": False}):
            result = Controller(self.path).reset_app()
        self.assertFalse(result["hardware_reset"])
        self.assertEqual(ConfigStore(self.path).read(), DEFAULTS)

    def test_software_effects_preserve_input_and_stay_in_valid_brightness_range(self):
        for mode in ("breathing", "rainbow"):
            settings = {"mode": mode, "color": "#00ff00", "brightness": 72, "speed": 100}
            colours, levels = set(), set()
            for elapsed in (0, 0.25, 0.5, 1, 2, 3):
                rendered = runtime.lighting_frame(settings, elapsed)
                self.assertEqual(rendered["mode"], "static")
                self.assertTrue(0 <= rendered["brightness"] <= 72)
                self.assertRegex(rendered["color"], r"^#[0-9a-fA-F]{6}$")
                colours.add(rendered["color"])
                levels.add(rendered["brightness"])
            self.assertGreater(len(levels) if mode == "breathing" else len(colours), 1)
            self.assertEqual(settings["mode"], mode)

    def test_runtime_will_not_treat_another_command_or_service_as_its_daemon(self):
        metadata, lock_path, _ = runtime.runtime_paths(self.path, "rgb")
        atomic_write(metadata, {"pid": os.getpid(), "ready": True})
        expected = str(self.path.resolve())
        invalid_argv = (
            ["python3", "-c", f"print('redragon {expected}')"],
            ["python3", "-m", "redragon", "--config", expected, "daemon", "run", "--kind", "remap"],
            ["python3", "-m", "redragon", "--config", expected + ".other", "daemon", "run", "--kind", "rgb"],
        )
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for argv in invalid_argv:
                with self.subTest(argv=argv), patch("redragon.runtime.Path.read_bytes", return_value="\0".join(argv).encode() + b"\0"):
                    self.assertFalse(runtime.daemon_status(self.path, "rgb")["running"])

    def test_lighting_is_saved_once_without_starting_a_background_service(self):
        from redragon.background import BackgroundStore
        controller = Controller(self.path)
        backend = Mock()
        backend.capabilities.return_value = {'rgb': True}
        backend.apply_native.return_value = {'saved_on_keyboard': True, 'keepalive_required': False}
        with patch.object(controller, '_lighting', return_value=backend), \
             patch('redragon.runtime.stop_daemon'), patch('redragon.runtime.start_daemon') as start:
            for mode in ('static', 'off', 'rainbow'):
                result = controller.set_lighting(mode=mode, apply=True)
                self.assertTrue(result['saved_on_keyboard'])
                self.assertFalse(result['daemon']['running'])
        self.assertEqual(backend.apply_native.call_count, 3)
        backend.apply.assert_not_called()
        self.assertFalse(BackgroundStore(self.path).read()['rgb'])
        start.assert_not_called()

    def test_lighting_preferences_do_not_live_reload_or_write_hardware(self):
        with patch('redragon.lighting._FeatureDevice') as opened, \
             patch('redragon.runtime.daemon_status', return_value={'running': True}):
            result = Controller(self.path).set_lighting(mode='static', color='#00ffff')
        self.assertFalse(result['live_reload'])
        opened.assert_not_called()

    def test_theme_cli_persists_and_isolated_demo_does_not_replace_it(self):
        code, out, err = self.cli('theme', 'adwaita')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['result']['resolved_theme'], 'adwaita')
        self.cli('--demo', 'theme', 'omarchy')
        self.assertEqual(Controller(self.path).appearance()['theme'], 'adwaita')

    def test_rgb_daemon_start_is_rejected_to_prevent_streaming(self):
        with self.assertRaisesRegex(ControlError, 'have been removed'):
            runtime.start_daemon(self.path, 'rgb')


    def test_appimage_daemon_is_recognized_from_another_mount(self):
        metadata, lock_path, _ = runtime.runtime_paths(self.path)
        atomic_write(metadata, {'pid': os.getpid(), 'ready': True})
        old = self.path.parent / 'old-mount'
        loader = old / 'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
        libs = ':'.join(str(old / p) for p in ('lib', 'usr/lib/x86_64-linux-gnu', 'usr/lib'))
        argv = [str(loader), '--library-path', libs, str(old / 'usr/bin/python3'), '-P',
                '-m', 'redragon', '--config', str(self.path.resolve()), 'daemon', 'run', '--kind', 'remap']
        resolve = Path.resolve
        def resolve_process(path, *args, **kwargs):
            if str(path) == f'/proc/{os.getpid()}/exe':
                return loader
            return resolve(path, *args, **kwargs)
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.dict(os.environ, REDRAGON_APPIMAGE_LAUNCHER='/another-mount/AppRun'), \
                 patch('redragon.runtime.Path.read_bytes', side_effect=lambda: '\0'.join(argv).encode()+b'\0'), \
                 patch.object(Path, 'resolve', resolve_process):
                self.assertTrue(runtime.daemon_status(self.path)['running'])
                argv[-1] = 'rgb'
                self.assertFalse(runtime.daemon_status(self.path)['running'])


    def test_demo_lighting_result_matches_normalized_saved_values(self):
        controller = Controller(self.path, demo=True)
        result = controller.set_lighting(mode='static', color='#00ccbb', brightness=65)
        self.assertEqual(result['lighting'], controller._config()['lighting'])
        self.assertEqual(result['lighting']['color'], '#00ffff')
        self.assertEqual(result['lighting']['brightness'], 75)


if __name__ == "__main__":
    unittest.main()
