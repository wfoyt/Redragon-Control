from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from redragon.devices import ConnectionStore, DeviceSelectionError, resolve_config_device
from redragon.errors import ControlError
from redragon.lighting import LightingBackend, _FeatureDevice, wireless_frames, wireless_packet


WIRELESS = {"id": "3554:fa09@receiver", "vendor_id": 0x3554, "product_id": 0xfa09,
            "physical_path": "usb-port3", "hidraw_paths": ["/dev/hidraw1"]}
WIRED = {"id": "258a:010c@keyboard", "vendor_id": 0x258a, "product_id": 0x010c}
SETTINGS = {"mode": "static", "color": "#00ccbb", "brightness": 65, "speed": 50}


class WirelessTests(unittest.TestCase):
    def test_stream_preserves_all_led_indices_and_never_writes_configuration(self):
        frames = wireless_frames(SETTINGS)
        self.assertEqual(len(frames), 9)
        data = bytearray()
        for sequence, frame in enumerate(frames):
            self.assertEqual(len(frame), 20)
            self.assertEqual(frame[:4], bytes((0x13, 0x88, 9, sequence)))
            self.assertEqual(frame[-1], sum(frame[:-1]) & 255)
            data.extend(frame[5:5 + frame[4] - 0x10])
        self.assertEqual(data[:4], bytes((0, 133, 122, 113)))
        self.assertEqual(data[4:], bytes(range(113)))

    def test_zero_and_off_use_documented_black_idle_report(self):
        for settings in ({**SETTINGS, 'mode': 'off'}, {**SETTINGS, 'brightness': 0}):
            self.assertEqual(wireless_frames(settings), [wireless_packet(0x88, 1, 0, b'\x23')])

    def test_receiver_must_identify_the_exact_k686_max(self):
        device = _FeatureDevice('/dev/hidraw1')
        device.fd = 7
        reply = wireless_packet(5, 1, 0, bytes.fromhex('0a 03 00 00 00 01 20 00'))
        with patch.object(device, 'send_output') as send, patch('redragon.lighting.select.select', return_value=([7], [], [])), \
             patch('redragon.lighting.os.read', return_value=reply):
            self.assertEqual(device.wireless_model(), 0x20)
            send.assert_called_once_with(wireless_packet(5))
        wrong = wireless_packet(5, 1, 0, bytes.fromhex('0a 03 00 00 00 01 58 00'))
        with patch.object(device, 'send_output'), patch('redragon.lighting.select.select', return_value=([7], [], [])), \
             patch('redragon.lighting.os.read', return_value=wrong), self.assertRaisesRegex(ControlError, 'verified K686'):
            device.wireless_model()

    def test_corrupt_model_reply_is_rejected(self):
        device = _FeatureDevice('/dev/hidraw1')
        device.fd = 7
        reply = bytearray(wireless_packet(5, 1, 0, bytes.fromhex('0a 03 00 00 00 01 20 00')))
        reply[-1] ^= 1
        with patch.object(device, 'send_output'), patch('redragon.lighting.select.select', return_value=([7], [], [])), \
             patch('redragon.lighting.os.read', return_value=reply), self.assertRaisesRegex(ControlError, 'checksum'):
            device.wireless_model()

    def test_unknown_paired_model_never_receives_rgb(self):
        backend = LightingBackend(WIRELESS)
        hid = MagicMock()
        hid.identity.return_value = {"bus": 3, "vendor_id": 0x3554, "product_id": 0xfa09,
                                     "physical_path": "usb-port3/input1"}
        hid.wireless_model.side_effect = ControlError('Unknown keyboard')
        with patch('redragon.lighting._output_report_size', return_value=20), \
             patch('redragon.lighting._FeatureDevice', return_value=hid), self.assertRaises(ControlError):
            backend.apply(SETTINGS)
        hid.send_output.assert_not_called()
        hid.__exit__.assert_called_once()

    def test_wireless_stream_uses_verified_handle_without_requerying_each_frame(self):
        backend = LightingBackend(WIRELESS)
        hid = MagicMock()
        hid.identity.return_value = {"bus": 3, "vendor_id": 0x3554, "product_id": 0xfa09,
                                     "physical_path": "usb-port3/input1"}
        hid.wireless_model.return_value = 32
        with patch('redragon.lighting._output_report_size', return_value=20), patch('redragon.lighting._FeatureDevice', return_value=hid):
            backend.apply(SETTINGS)
            backend.apply(SETTINGS)
        hid.wireless_model.assert_called_once()
        self.assertEqual(hid.send_output.call_count, 18)
        hid.send.assert_not_called()
        backend.close()


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'config.json'
        self.links = ConnectionStore(self.path)

    def test_saved_wired_selection_follows_only_explicitly_linked_receiver(self):
        with self.assertRaises(DeviceSelectionError):
            resolve_config_device(self.path, WIRED['id'], [WIRELESS])
        self.links.link(WIRED['id'], WIRELESS['id'])
        self.assertEqual(resolve_config_device(self.path, WIRED['id'], [WIRELESS]), WIRELESS)
        self.assertEqual(resolve_config_device(self.path, WIRELESS['id'], [WIRED]), WIRED)

    def test_other_receiver_with_same_chipset_is_never_used(self):
        self.links.link(WIRED['id'], WIRELESS['id'])
        other = {**WIRELESS, 'id': '3554:fa09@different'}
        with self.assertRaises(DeviceSelectionError):
            resolve_config_device(self.path, WIRED['id'], [other])

    def test_explicit_selection_wins_when_both_connections_are_present(self):
        self.links.link(WIRED['id'], WIRELESS['id'])
        self.assertEqual(resolve_config_device(self.path, WIRED['id'], [WIRELESS, WIRED]), WIRED)


if __name__ == '__main__':
    unittest.main()
