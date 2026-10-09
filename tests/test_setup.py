from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from redragon.config import DEFAULTS, ConfigStore
from redragon.core import Controller
from redragon.errors import ControlError
from redragon.setup import SetupStore, keyboard_candidates


class SetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'config.json'
        self.setup = SetupStore(self.path)
        self.controller = Controller(self.path)

    def test_completion_is_separate_from_profiles_and_survives_restart(self):
        self.assertFalse(self.setup.completed())
        ConfigStore(self.path).replace(DEFAULTS)
        self.assertFalse(self.setup.completed())
        self.setup.finish()
        self.assertTrue(SetupStore(self.path).completed())
        ConfigStore(self.path).replace(DEFAULTS)
        self.assertTrue(self.setup.completed())

    def test_missing_or_invalid_marker_restarts_setup(self):
        for value in ('broken', '{}', '{"completed": false}'):
            self.setup.path.write_text(value)
            self.assertFalse(self.setup.completed())

    def test_only_a_single_keyboard_is_automatically_selected(self):
        device = {'id': '258a:010c@keyboard'}
        for devices, selected in (([], False), ([device], True),
                                  ([device, {'id': '3554:fa09@other'}], False)):
            state = {'device': None, 'devices': devices}
            with patch.object(self.controller, 'status', return_value=state), \
                 patch.object(self.controller, 'select_device') as select:
                self.controller.detect_keyboard()
            if selected:
                select.assert_called_once_with(device['id'])
            else:
                select.assert_not_called()

    def test_detection_preserves_connected_selection(self):
        state = {'device': {'id': '258a:010c@keyboard'}, 'devices': [{'id': '258a:010c@keyboard'}]}
        with patch.object(self.controller, 'status', return_value=state), \
             patch.object(self.controller, 'select_device') as select:
            self.controller.detect_keyboard()
        select.assert_not_called()

    def test_detection_ignores_mice_and_other_hid_devices(self):
        keyboard = {'id': '3554:fa09@receiver'}
        state = {'device': None, 'devices': [keyboard, {'id': '046d:c539@mouse'},
                                           {'id': '0b05:19af@led'}]}
        self.assertEqual(keyboard_candidates(state['devices']), [keyboard])
        with patch.object(self.controller, 'status', return_value=deepcopy(state)), \
             patch.object(self.controller, 'select_device') as select:
            self.controller.detect_keyboard()
        select.assert_called_once_with(keyboard['id'])

    def test_invalid_binding_does_not_partially_save_setup(self):
        value = deepcopy(DEFAULTS)
        value['bindings'] = {'KEY_MUTE': 'KEY_PLAYPAUSE'}
        ConfigStore(self.path).replace(value)
        with self.assertRaises(ControlError):
            self.controller.set_bindings({'KEY_A': 'KEY_B', 'KEY_C': 'invalid'})
        self.assertEqual(ConfigStore(self.path).read(), value)


if __name__ == '__main__':
    unittest.main()
