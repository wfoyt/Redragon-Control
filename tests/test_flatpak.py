"""Packaging startup must never launch the real app after a failed check."""

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from redragon import flatpak_entry, flatpak_support


class FlatpakStartupTests(unittest.TestCase):
    def test_failed_or_closed_setup_does_not_launch_app(self):
        for command in ([], ["gui"], ["tray"]):
            with self.subTest(command=command), patch.object(sys, "argv", ["redragon-control", *command]), \
                 patch.object(flatpak_entry, "ensure_ready", return_value=False), \
                 patch.object(flatpak_entry.os, "execv") as execute:
                self.assertEqual(flatpak_entry.main(), 1)
                execute.assert_not_called()

    def test_unexpected_setup_error_also_blocks_app_with_actionable_output(self):
        with patch.object(sys, "argv", ["redragon-control", "gui"]), \
             patch.object(flatpak_entry, "ensure_ready", side_effect=RuntimeError("private detail")), \
             patch.object(flatpak_entry.os, "execv") as execute, redirect_stderr(StringIO()) as output:
            self.assertEqual(flatpak_entry.main(), 1)
            execute.assert_not_called()
            self.assertIn("flatpak update", output.getvalue())
            self.assertNotIn("private detail", output.getvalue())

    def test_successful_gui_launch_routes_to_tray_session(self):
        with patch.object(sys, "argv", ["redragon-control", "gui"]), \
             patch.object(flatpak_entry, "ensure_ready", return_value=True), \
             patch.object(flatpak_entry.os, "execv", side_effect=SystemExit) as execute:
            with self.assertRaises(SystemExit):
                flatpak_entry.main()
            self.assertEqual(execute.call_args.args[1][-2:], ["tray", "--open-settings"])

    def test_uinput_denial_explains_one_time_setup(self):
        with patch.object(flatpak_support.os, "access", return_value=False):
            self.assertIn("sudo", flatpak_support.hardware_problem())

    def test_connected_keyboard_permission_denial_blocks_startup(self):
        keyboard = {"vendor_id": 0x3554, "product_id": 0xfa09,
                    "input_accessible": False, "hidraw_accessible": True}
        with patch.object(flatpak_support.os, "access", return_value=True), \
             patch("redragon.devices.discover_devices", return_value=[keyboard]):
            self.assertIn("blocking access", flatpak_support.hardware_problem())

    def test_unrelated_keyboard_does_not_satisfy_connection_check(self):
        with patch.object(flatpak_support.os, "access", return_value=True), \
             patch("redragon.devices.discover_devices", return_value=[{"vendor_id": 1, "product_id": 2}]):
            self.assertIn("Connect your Redragon", flatpak_support.hardware_problem())

    def test_ready_keyboard_does_not_need_host_gtk_packages(self):
        keyboard = {"vendor_id": 0x3554, "product_id": 0xfa09,
                    "input_accessible": True, "hidraw_accessible": True}
        with patch.object(flatpak_support.os, "access", return_value=True), \
             patch("redragon.devices.discover_devices", return_value=[keyboard]):
            self.assertIsNone(flatpak_support.hardware_problem())

    def test_standalone_script_has_exact_device_rules(self):
        root = Path(__file__).resolve().parent.parent
        script = (root / "scripts/setup-hardware.sh").read_text()
        self.assertIn((root / "data/70-redragon-control.rules").read_text(), script)
        subprocess.run(["bash", "-n", str(root / "scripts/setup-hardware.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
