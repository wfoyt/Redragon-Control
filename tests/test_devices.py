import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from redragon import devices


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "input"
        self.hidraw = self.root / "hidraw"
        self.input.mkdir()
        self.hidraw.mkdir()
        for name, value in (("SYS_CLASS_INPUT", self.input), ("SYS_CLASS_HIDRAW", self.hidraw), ("DEV_ROOT", self.root / "dev")):
            patcher = patch.object(devices, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def event(self, number, name="CX Wireless Receiver", vid=0x3554, pid=0xFA09,
              phys="usb-port3/input0", bus=3):
        path = self.input / f"event{number}" / "device"
        (path / "id").mkdir(parents=True)
        for field, value in (("name", name), ("phys", phys), ("id/vendor", f"{vid:04x}"),
                             ("id/product", f"{pid:04x}"), ("id/bustype", f"{bus:04x}")):
            (path / field).write_text(value)

    def hid(self, number, phys="usb-port3/input0", vid=0x3554, pid=0xFA09):
        path = self.hidraw / f"hidraw{number}" / "device"
        path.mkdir(parents=True)
        (path / "uevent").write_text(
            f"HID_ID=0003:{vid:08X}:{pid:08X}\nHID_NAME=CX Wireless Receiver\nHID_PHYS={phys}\n")

    def test_composite_keyboard_grouped_without_other_receiver(self):
        self.event(2)
        self.event(17, name="CX Wireless Receiver Consumer Control", phys="usb-port3/input1")
        self.hid(0)
        self.hid(1, phys="usb-port3/input1")
        self.event(4, name="Other Mouse", vid=0x046D, pid=0x4074, phys="usb-port4/input2:1")
        with patch.object(devices.os, "access", return_value=True):
            found = devices.discover_devices()
        selected = devices.resolve_device("3554:fa09", found)
        self.assertEqual(selected["physical_path"], "usb-port3")
        self.assertEqual(selected["name"], "CX Wireless Receiver")
        self.assertEqual(len(selected["event_paths"]), 2)
        self.assertEqual(len(selected["hidraw_paths"]), 2)
        self.assertTrue(selected["input_accessible"])
        self.assertTrue(selected["hidraw_accessible"])
        self.assertTrue(all("event4" not in path for path in selected["event_paths"]))

    def test_stable_family_id_and_ambiguous_bare_id(self):
        self.event(2)
        original = devices.discover_devices()[0]["id"]
        self.event(20, phys="usb-port4/input0")
        found = devices.discover_devices()
        self.assertEqual(len(found), 2)
        self.assertIn(original, [item["id"] for item in found])
        self.assertEqual(devices.resolve_device(original, found)["physical_path"], "usb-port3")
        with self.assertRaisesRegex(devices.DeviceSelectionError, "ambiguous"):
            devices.resolve_device("3554:fa09", found)

    def test_excludes_virtual_self_and_non_hid_inputs(self):
        self.event(2)
        self.event(3, name="Redragon Control virtual keyboard", phys="redragon-control/3554:fa09")
        self.event(4, name="Power Button", bus=0)
        self.event(5, name="Other virtual", bus=6)
        self.assertEqual(len(devices.discover_devices()), 1)

    def test_absent_or_disconnected_selection_fails(self):
        with self.assertRaisesRegex(devices.DeviceSelectionError, "Select a device"):
            devices.resolve_device(None, [])
        with self.assertRaisesRegex(devices.DeviceSelectionError, "disconnected"):
            devices.resolve_device("3554:fa09@missing", [])

    def test_inaccessible_nodes_still_listed(self):
        self.event(2)
        self.hid(0)
        with patch.object(devices.os, "access", return_value=False):
            found = devices.discover_devices()
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["accessible"])

    def test_receiver_children_keep_slot_identity(self):
        self.assertEqual(devices.physical_family("usb-port4/input2:1"), "usb-port4/input2:1")
        self.assertEqual(devices.physical_family("usb-port4/input1"), "usb-port4")


if __name__ == "__main__":
    unittest.main()
