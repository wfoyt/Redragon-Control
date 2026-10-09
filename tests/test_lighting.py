import unittest
from unittest.mock import patch

from redragon.errors import ControlError
from redragon.lighting import LightingBackend, direct_packet, frame


class FakeHid:
    sent = []
    model = 0x20
    physical = "usb-test-1/input1"
    vendor = 0x258A

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def send(self, packet):
        self.sent.append(packet)

    def receive(self):
        result = bytearray(520)
        result[0] = 6
        result[13] = self.model
        return bytes(result)

    def identity(self):
        return {"bus": 3, "vendor_id": self.vendor, "product_id": 0x010C,
                "physical_path": self.physical, "sysfs_device": "/sys/devices/test"}


class LightingTests(unittest.TestCase):
    def setUp(self):
        FakeHid.sent = []
        FakeHid.model = 0x20
        FakeHid.physical = "usb-test-1/input1"
        FakeHid.vendor = 0x258A
        self.device = {"vendor_id": 0x258A, "product_id": 0x010C,
                       "hidraw_paths": ["/dev/hidraw8"], "physical_path": "usb-test-1"}

    def test_direct_packet_layout_and_brightness(self):
        packet = direct_packet({"mode": "static", "color": "#ff8040", "brightness": 50})
        self.assertEqual(len(packet), 520)
        self.assertEqual(packet[:8], bytes.fromhex("06 08 00 00 01 00 7a 01"))
        self.assertEqual(packet[8:347], bytes((128, 64, 32)) * 113)
        self.assertEqual(packet[347:], bytes(173))

    def test_off_sends_black_and_no_reset_command(self):
        packet = direct_packet({"mode": "off"})
        self.assertEqual(packet[8:], bytes(512))

    def test_unrecognized_device_never_opens(self):
        with patch("redragon.lighting._FeatureDevice") as opened:
            with self.assertRaises(ControlError):
                LightingBackend({"vendor_id": 0x3554, "product_id": 0xFA09}).apply({"mode": "static"})
            opened.assert_not_called()

    @patch("redragon.lighting._feature_report_size", return_value=520)
    @patch("redragon.lighting._FeatureDevice", FakeHid)
    def test_verified_model_is_queried_before_rgb(self, _):
        result = LightingBackend(self.device).apply({"mode": "static"})
        self.assertEqual(len(FakeHid.sent), 2)
        self.assertEqual(FakeHid.sent[0][:7], bytes.fromhex("06 82 01 00 01 00 06"))
        self.assertEqual(FakeHid.sent[1][1], 8)
        self.assertTrue(result["transient"])

    @patch("redragon.lighting._feature_report_size", return_value=520)
    @patch("redragon.lighting._FeatureDevice", FakeHid)
    def test_other_sinowealth_models_never_receive_rgb(self, _):
        FakeHid.model = 0xCD
        with self.assertRaisesRegex(ControlError, "Refusing RGB writes"):
            LightingBackend(self.device).apply({"mode": "static"})
        self.assertEqual(len(FakeHid.sent), 1)
        self.assertEqual(FakeHid.sent[0][1], 0x82)

    @patch("redragon.lighting._feature_report_size", return_value=520)
    @patch("redragon.lighting._FeatureDevice", FakeHid)
    def test_keepalive_reuses_only_the_same_opened_device(self, _):
        backend = LightingBackend(self.device)
        backend.apply({"mode": "static"})
        backend.apply({"mode": "off"})
        self.assertEqual([packet[1] for packet in FakeHid.sent], [0x82, 0x08, 0x08])
        backend.close()
        FakeHid.model = 0xCD
        with self.assertRaises(ControlError):
            backend.apply({"mode": "static"})
        self.assertEqual([packet[1] for packet in FakeHid.sent], [0x82, 0x08, 0x08, 0x82])

    @patch("redragon.lighting._feature_report_size", return_value=9)
    def test_unrelated_hid_interfaces_are_never_opened(self, _):
        with patch("redragon.lighting._FeatureDevice") as opened:
            with self.assertRaisesRegex(ControlError, "No compatible"):
                LightingBackend(self.device).apply({"mode": "static"})
            opened.assert_not_called()

    @patch("redragon.lighting._feature_report_size", return_value=520)
    @patch("redragon.lighting._FeatureDevice", FakeHid)
    def test_recycled_path_never_receives_even_a_model_query(self, _):
        for attribute, value in (("vendor", 0x1234), ("physical", "usb-another-port/input1")):
            with self.subTest(attribute=attribute):
                FakeHid.vendor = 0x258A
                FakeHid.physical = "usb-test-1/input1"
                setattr(FakeHid, attribute, value)
                with self.assertRaises(ControlError):
                    LightingBackend(self.device).apply({"mode": "static"})
                self.assertEqual(FakeHid.sent, [])

    @patch("redragon.lighting._feature_report_size", return_value=520)
    @patch("redragon.lighting._FeatureDevice", FakeHid)
    def test_probe_never_changes_lighting_even_for_an_unrecognized_model(self, _):
        for model in (0x20, 0xCD):
            with self.subTest(model=model):
                FakeHid.sent = []
                FakeHid.model = model
                backend = LightingBackend(self.device)
                result = backend.probe()
                self.assertEqual(result["supported"], model == 0x20)
                self.assertEqual(result["model_id"], model)
                self.assertFalse(result["lighting_written"])
                self.assertEqual([packet[1] for packet in FakeHid.sent], [0x82])
                backend.close()

    def test_captured_k686_wired_descriptor_selects_only_configuration_interface(self):
        from redragon.lighting import _feature_report_size
        # Sysfs descriptor captured read-only from the user's K686 MAX. Report
        # ID 6 has a seven-byte Input item and a 519-byte Feature item.
        descriptor = bytes.fromhex("0600ff0901a1018506150026ff007508950709028100150026ff00190129027508960702b102c0")
        with patch("redragon.lighting.Path.read_bytes", return_value=descriptor):
            self.assertEqual(_feature_report_size("/dev/hidraw8", 6), 520)
        keyboard_only = bytes.fromhex("05010906a101050719e029e71500250195087501810295017508810395067508150026ff00050719002aff0081002501950575010508190129059102950175039103c0")
        with patch("redragon.lighting.Path.read_bytes", return_value=keyboard_only):
            self.assertEqual(_feature_report_size("/dev/hidraw4", 6), 0)

    def test_invalid_colour_never_opens(self):
        with patch("redragon.lighting._FeatureDevice") as opened:
            with self.assertRaises(ControlError):
                LightingBackend(self.device).apply({"color": "red"})
            opened.assert_not_called()

    def test_software_effects_become_valid_direct_frames(self):
        for mode in ("breathing", "rainbow"):
            settings = {"mode": mode, "color": "#ff0000", "brightness": 70, "speed": 50}
            for elapsed in (0, 1, 4, 100):
                rendered = frame(settings, elapsed)
                self.assertEqual(rendered["mode"], "static")
                self.assertEqual(len(direct_packet(rendered)), 520)
            self.assertEqual(settings["mode"], mode)

    def test_breathing_keeps_full_rgb_precision_between_whole_percent_steps(self):
        settings = {"mode": "breathing", "color": "#00ccbb", "brightness": 65, "speed": 50}
        levels = {direct_packet(frame(settings, i * 2.25 / 300))[9] for i in range(301)}
        self.assertGreater(len(levels), 100)
        self.assertEqual(min(levels), 0)
        self.assertEqual(max(levels), 133)

    def test_reset_is_honestly_unsupported(self):
        with self.assertRaisesRegex(ControlError, "Fn \\+ Esc"):
            LightingBackend(self.device).factory_reset()


if __name__ == "__main__":
    unittest.main()
