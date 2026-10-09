from copy import deepcopy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from redragon.config import ConfigStore, DEFAULTS, atomic_write, read_json, validate_config
from redragon.errors import ControlError


def _concurrent_binding(path, source, event):
    event.wait(5)
    ConfigStore(path).update(lambda config: config["bindings"].update({source: "KEY_MUTE"}))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.json"
        self.store = ConfigStore(self.path)

    def test_default_read_does_not_create_files_or_return_shared_state(self):
        first = self.store.read()
        first["lighting"]["color"] = "#000000"
        self.assertEqual(self.store.read(), DEFAULTS)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_profiles_require_complete_schema_and_integer_version(self):
        missing = deepcopy(DEFAULTS)
        missing.pop("device_id")
        malformed = [missing]
        for version in (True, 1.0, "1", 2):
            profile = deepcopy(DEFAULTS)
            profile["version"] = version
            malformed.append(profile)
        for profile in malformed:
            with self.subTest(profile=profile), self.assertRaises(ControlError):
                validate_config(profile)

    def test_import_rejects_unsupported_or_executable_binding_payloads(self):
        bad_profiles = []
        for target in ("$(touch /tmp/unsafe)", "KEY_A+KEY_A", "KEY_LEFTCTRL+invalid", ["KEY_A"]):
            value = deepcopy(DEFAULTS)
            value["bindings"] = {"KEY_A": target}
            bad_profiles.append(value)
        for brightness in (-1, 101, True, 10.5):
            value = deepcopy(DEFAULTS)
            value["lighting"]["brightness"] = brightness
            bad_profiles.append(value)
        value = deepcopy(DEFAULTS)
        value["firmware_command"] = "reset"
        bad_profiles.append(value)
        for value in bad_profiles:
            with self.subTest(value=value):
                self.path.write_text(json.dumps(value))
                with self.assertRaises(ControlError):
                    read_json(self.path)

    def test_rejected_update_keeps_previous_file(self):
        self.store.replace(deepcopy(DEFAULTS))
        previous = self.path.read_bytes()
        with self.assertRaises(ControlError):
            self.store.update(lambda config: config["lighting"].update(brightness=101))
        self.assertEqual(self.path.read_bytes(), previous)

    def test_failed_atomic_replace_preserves_old_file_and_removes_temporary(self):
        atomic_write(self.path, DEFAULTS)
        previous = self.path.read_bytes()
        with patch("redragon.config.os.replace", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(ControlError):
                atomic_write(self.path, {"replacement": True})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_parallel_updates_do_not_lose_other_bindings(self):
        self.store.replace(deepcopy(DEFAULTS))
        context = multiprocessing.get_context("fork")
        event = context.Event()
        sources = [f"KEY_{letter}" for letter in "ABCDEFGHIJKL"]
        workers = [context.Process(target=_concurrent_binding, args=(str(self.path), source, event)) for source in sources]
        for worker in workers:
            worker.start()
        event.set()
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join(2)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(self.store.read()["bindings"], {source: "KEY_MUTE" for source in sources})

    def test_profile_size_limit(self):
        self.path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ControlError, "size limit"):
            read_json(self.path)


if __name__ == "__main__":
    unittest.main()
