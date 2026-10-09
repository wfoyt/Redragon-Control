import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from redragon import remap


KEYS = {"KEY_A": 30, "KEY_B": 48, "KEY_C": 46, "KEY_LEFTCTRL": 29,
        "KEY_VOLUMEUP": 115, "KEY_VOLUMEDOWN": 114, "KEY_MUTE": 113,
        "KEY_COFFEE": 152, "KEY_SCREENLOCK": 152,
        "BTN_LEFT": 272, "KEY_MAX": 767, "KEY_CNT": 768}
CODES = SimpleNamespace(EV_SYN=0, EV_KEY=1, EV_REL=2, EV_ABS=3, EV_MSC=4,
    EV_FF=21, EV_FF_STATUS=23, SYN_REPORT=0, SYN_DROPPED=3,
    REL_WHEEL=8, REL_HWHEEL=6, REL_WHEEL_HI_RES=11, REL_HWHEEL_HI_RES=12,
    ecodes=KEYS, bytype={0: {0: "SYN_REPORT", 3: "SYN_DROPPED"},
                        1: {code: key for key, code in KEYS.items()},
                        2: {8: "REL_WHEEL", 6: "REL_HWHEEL", 11: "REL_WHEEL_HI_RES"}},
    **KEYS)


def event(kind, code, value):
    return SimpleNamespace(type=kind, code=code, value=value, timestamp=lambda: 123.5)


class Output:
    def __init__(self):
        self.events = []
        self.closed = False

    def write(self, kind, code, value):
        self.events.append((kind, code, value))

    def write_event(self, value):
        self.write(value.type, value.code, value.value)

    def syn(self):
        self.write(0, 0, 0)

    def close(self):
        self.closed = True


class Device:
    def __init__(self, path, fail_grab=False):
        self.path, self.fail_grab = path, fail_grab
        self.name, self.phys = "CX Receiver", "usb-port3/input0"
        self.info = SimpleNamespace(vendor=0x3554, product=0xFA09)
        self.grabbed = self.ungrabbed = self.closed = False
        self.events = []

    def capabilities(self, absinfo=False):
        return {0: [0], 1: [30, 115], 2: [8, 11], 4: [4], 21: [80]}

    def active_keys(self):
        return []

    def grab(self):
        if self.fail_grab:
            raise OSError("already grabbed")
        self.grabbed = True

    def ungrab(self):
        self.ungrabbed = True

    def close(self):
        self.closed = True

    def read(self):
        values, self.events = self.events, []
        return iter(values)


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.output = Output()

    def mapper(self, bindings):
        return remap.InputMapper(self.output, CODES, bindings)

    def key(self, mapper, code, value, source="keyboard"):
        mapper.process(source, event(1, code, value))

    def test_chord_holds_repeats_and_releases_in_reverse(self):
        mapper = self.mapper({"KEY_VOLUMEUP": "KEY_LEFTCTRL+KEY_C"})
        for value in (1, 2, 0):
            self.key(mapper, 115, value)
        self.assertEqual(self.output.events, [(1, 29, 1), (1, 46, 1), (1, 46, 2), (1, 46, 0), (1, 29, 0)])

    def test_shared_modifier_survives_other_source_release(self):
        mapper = self.mapper({"KEY_VOLUMEUP": "KEY_LEFTCTRL+KEY_C"})
        self.key(mapper, 29, 1)
        self.key(mapper, 115, 1, "consumer")
        self.key(mapper, 115, 0, "consumer")
        self.assertNotIn((1, 29, 0), self.output.events)
        self.key(mapper, 29, 0)
        self.assertEqual(self.output.events[-1], (1, 29, 0))

    def test_disabled_and_default_pass_through(self):
        mapper = self.mapper({"KEY_MUTE": "disabled", "KEY_VOLUMEUP": "default"})
        for code in (113, 115, 30):
            self.key(mapper, code, 1)
            self.key(mapper, code, 0)
        self.assertEqual(self.output.events, [(1, 115, 1), (1, 115, 0), (1, 30, 1), (1, 30, 0)])
        mapper.process("keyboard", event(4, 4, 123))
        mapper.process("keyboard", event(0, 0, 0))
        self.assertEqual(self.output.events[-2:], [(4, 4, 123), (0, 0, 0)])

    def test_wheel_ticks_to_key_chord_without_highres_duplication(self):
        mapper = self.mapper({"REL_WHEEL_UP": "KEY_A"})
        device = Device("keyboard")
        mapper.process("keyboard", event(2, 8, 2), device)
        mapper.process("keyboard", event(2, 11, 240), device)
        self.assertEqual(self.output.events, [(1, 30, 1), (1, 30, 0)] * 2)
        mapper.process("keyboard", event(2, 8, -1), device)
        self.assertEqual(self.output.events[-1], (2, 8, -1))

    def test_highres_only_wheel_accumulates_partial_ticks(self):
        mapper = self.mapper({"REL_WHEEL_UP": "KEY_A"})
        device = Mock()
        device.capabilities.return_value = {2: [11]}
        mapper.process("keyboard", event(2, 11, 60), device)
        self.assertEqual(self.output.events, [])
        mapper.process("keyboard", event(2, 11, 60), device)
        self.assertEqual(self.output.events, [(1, 30, 1), (1, 30, 0)])

    def test_key_to_scroll_with_repeat(self):
        mapper = self.mapper({"KEY_VOLUMEUP": "scroll-left"})
        for value in (1, 2, 0):
            self.key(mapper, 115, value)
        self.assertEqual(self.output.events, [(2, 6, -1), (2, 12, -120)] * 2)

    def test_reload_releases_and_suppresses_old_held_key(self):
        mapper = self.mapper({"KEY_VOLUMEUP": "KEY_A"})
        self.key(mapper, 115, 1)
        mapper.update_bindings({"KEY_VOLUMEUP": "KEY_B"})
        self.key(mapper, 115, 2)
        self.key(mapper, 115, 0)
        self.assertNotIn((1, 48, 1), self.output.events)
        self.key(mapper, 115, 1)
        self.assertEqual(self.output.events[-1], (1, 48, 1))

    def test_invalid_reload_preserves_existing_held_mapping(self):
        mapper = self.mapper({"KEY_VOLUMEUP": "KEY_A"})
        self.key(mapper, 115, 1)
        with self.assertRaises(remap.RemapError):
            mapper.update_bindings({"KEY_VOLUMEUP": "run a shell command"})
        self.assertEqual(mapper.held, {("keyboard", 115): (30,)})

    def test_syn_dropped_releases_and_queries_state_then_ignores_held_keys(self):
        mapper = self.mapper({"KEY_VOLUMEUP": "KEY_A"})
        self.key(mapper, 115, 1)
        mapper.process("keyboard", event(0, 3, 0))
        self.assertIn((1, 30, 0), self.output.events)
        device = Mock()
        device.active_keys.return_value = [115]
        self.key(mapper, 115, 1)
        mapper.process("keyboard", event(0, 0, 0), device)
        device.active_keys.assert_called_once_with()
        before = list(self.output.events)
        self.key(mapper, 115, 2)
        self.key(mapper, 115, 0)
        self.assertEqual(self.output.events, before)
        self.key(mapper, 115, 1)
        self.assertEqual(self.output.events[-1], (1, 30, 1))

    def test_startup_held_keys_are_suppressed_until_released(self):
        mapper = self.mapper({})
        mapper.ignore_initial_keys("keyboard", [30])
        self.key(mapper, 30, 2)
        self.key(mapper, 30, 0)
        self.assertEqual(self.output.events, [])
        self.key(mapper, 30, 1)
        self.assertEqual(self.output.events, [(1, 30, 1)])

    def test_invalid_names_chords_and_values_rejected(self):
        for bindings in ({"REL_X": "KEY_A"}, {"KEY_A": "KEY_UNKNOWN"},
                         {"KEY_A": "KEY_A+KEY_A"}, {"KEY_A": 3}, {"KEY_CNT": "KEY_A"}):
            with self.subTest(bindings=bindings), self.assertRaises(remap.RemapError):
                self.mapper(bindings)

    def test_key_alias_is_resolved_numerically(self):
        mapper = self.mapper({"KEY_COFFEE": "KEY_A"})
        self.key(mapper, 152, 1)
        self.key(mapper, 152, 0)
        self.assertEqual(self.output.events, [(1, 30, 1), (1, 30, 0)])
        with self.assertRaisesRegex(remap.RemapError, "aliases"):
            self.mapper({"KEY_COFFEE": "KEY_A", "KEY_SCREENLOCK": "KEY_B"})

    def test_capabilities_preserve_input_but_do_not_advertise_joysticks(self):
        caps = remap._capabilities([Device("keyboard")], CODES)
        self.assertNotIn(0, caps)
        self.assertNotIn(21, caps)
        self.assertIn(48, caps[1])
        self.assertNotIn(272, caps[1])
        self.assertNotIn(768, caps[1])
        self.assertEqual(caps[4], [4])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "config.json"
        self.write({"KEY_VOLUMEUP": "KEY_A"})
        self.selected = {"id": "3554:fa09@abc", "vendor_id": 0x3554,
                         "product_id": 0xFA09, "physical_path": "usb-port3",
                         "event_paths": ["/dev/input/event2", "/dev/input/event16"]}
        self.devices = [Device(path) for path in self.selected["event_paths"]]
        self.output = Output()
        self.module = SimpleNamespace(ecodes=CODES, InputDevice=Mock(side_effect=self.devices),
                                      UInput=Mock(return_value=self.output))
        for target, value in (("_evdev", self.module), ("resolve_device", self.selected), ("resolve_config_device", self.selected)):
            patcher = patch.object(remap, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, bindings, device_id="3554:fa09@abc"):
        self.path.write_text(json.dumps({"version": 1, "device_id": device_id, "bindings": bindings}))

    def test_partial_grab_failure_releases_every_opened_device(self):
        self.devices[1].fail_grab = True
        with self.assertRaisesRegex(remap.RemapError, "Original input access"):
            remap.RemapDaemon(self.path).run()
        self.assertTrue(self.devices[0].ungrabbed)
        self.assertFalse(self.devices[1].ungrabbed)
        self.assertTrue(all(device.closed for device in self.devices))
        self.assertTrue(self.output.closed)

    def test_recycled_event_node_identity_mismatch_never_grabbed(self):
        self.devices[1].info.product = 0x9999
        with self.assertRaisesRegex(remap.RemapError, "changed identity"):
            remap.RemapDaemon(self.path).run()
        self.assertFalse(any(device.grabbed for device in self.devices))
        self.assertTrue(all(device.closed for device in self.devices))
        self.module.UInput.assert_not_called()

    def test_wrong_physical_family_never_grabbed(self):
        self.devices[0].phys = "usb-another-port/input0"
        with self.assertRaisesRegex(remap.RemapError, "another physical device"):
            remap.RemapDaemon(self.path).run()
        self.assertFalse(self.devices[0].grabbed)
        self.assertTrue(self.devices[0].closed)

    def test_ready_occurs_after_grabs_and_cleanup_follows_stop(self):
        stop = threading.Event()
        observed = []

        def ready():
            observed.append(all(device.grabbed for device in self.devices))
            stop.set()

        remap.RemapDaemon(self.path, stop, ready).run()
        self.assertEqual(observed, [True])
        self.assertTrue(all(device.ungrabbed and device.closed for device in self.devices))
        self.assertTrue(self.output.closed)

    def test_identity_profile_watches_without_input_grabs(self):
        self.write({"KEY_VOLUMEUP": "KEY_VOLUMEUP", "KEY_MUTE": "default"})
        stop = threading.Event()
        ready = Mock(side_effect=stop.set)
        remap.RemapDaemon(self.path, stop, ready).run()
        ready.assert_called_once_with()
        self.module.InputDevice.assert_not_called()
        self.module.UInput.assert_not_called()

    def test_unplug_cleans_up_and_reports_error(self):
        with patch.object(remap.select, "select", side_effect=OSError("No such device")):
            with self.assertRaisesRegex(remap.RemapError, "reconnect the selected keyboard"):
                remap.RemapDaemon(self.path).run()
        self.assertTrue(all(device.ungrabbed and device.closed for device in self.devices))
        self.assertTrue(self.output.closed)

    def test_device_change_returns_new_config_and_ungrabs_old_family(self):
        self.write({"KEY_VOLUMEUP": "KEY_A"}, "3554:fa09@different")
        old = {"version": 1, "device_id": "3554:fa09@abc", "bindings": {"KEY_VOLUMEUP": "KEY_A"}}
        replacement = remap.RemapDaemon(self.path)._session(self.module, old)
        self.assertEqual(replacement["device_id"], "3554:fa09@different")
        self.assertTrue(all(device.ungrabbed and device.closed for device in self.devices))

    def test_reset_identity_returns_to_no_grab_mode(self):
        self.write({})
        old = {"version": 1, "device_id": "3554:fa09@abc", "bindings": {"KEY_VOLUMEUP": "KEY_A"}}
        replacement = remap.RemapDaemon(self.path)._session(self.module, old)
        self.assertEqual(replacement["bindings"], {})
        self.assertTrue(all(device.ungrabbed and device.closed for device in self.devices))

    def test_observer_is_read_only_and_closes_nodes(self):
        self.devices[0].events = [event(1, 115, 1), event(2, 8, -1)]
        with patch.object(remap.select, "select", return_value=([self.devices[0]], [], [])):
            found = list(remap.observe_events(self.selected["id"], limit=2, timeout=1))
        self.assertEqual([item["source"] for item in found], ["KEY_VOLUMEUP", "REL_WHEEL_DOWN"])
        self.assertTrue(all(device.closed for device in self.devices))
        self.assertFalse(any(device.grabbed for device in self.devices))
        self.module.UInput.assert_not_called()

    def test_early_closed_observer_releases_nodes(self):
        self.devices[0].events = [event(1, 115, 1), event(1, 115, 0)]
        with patch.object(remap.select, "select", return_value=([self.devices[0]], [], [])):
            observer = remap.observe_events(self.selected["id"], limit=10, timeout=1)
            next(observer)
            observer.close()
        self.assertTrue(all(device.closed for device in self.devices))

    def test_read_only_preflight_checks_access_without_opening_nodes(self):
        with patch.object(remap.os, "access", return_value=True):
            self.assertEqual(remap.RemapDaemon(self.path).validate_runtime(), self.selected)
        self.module.InputDevice.assert_not_called()
        self.module.UInput.assert_not_called()

    def test_observation_validates_limits(self):
        for limit, timeout in ((0, 1), (True, 1), (2, 0), (2, float("inf"))):
            with self.subTest(limit=limit, timeout=timeout), self.assertRaises(remap.RemapError):
                list(remap.observe_events("3554:fa09", limit, timeout))


class DependencyTests(unittest.TestCase):
    def test_evdev_is_optional_until_runtime_requested(self):
        with patch.object(remap.importlib, "import_module", side_effect=ImportError("missing")):
            with self.assertRaisesRegex(remap.RemapError, "python3-evdev"):
                remap._evdev()


if __name__ == "__main__":
    unittest.main()
