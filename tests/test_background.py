from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from redragon.background import BackgroundStore, BackgroundSupervisor
from redragon.config import ConfigStore, DEFAULTS
from redragon.core import Controller


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'config.json'
        self.preferences = BackgroundStore(self.path)
        self.preferences.set('remap', True)
        self.controller = Mock()
        self.controller.store.path = self.path
        self.state = {'device': {'id': 'keyboard'}, 'daemon': {'running': False},
                      'lighting_daemon': {'running': False}}
        self.controller.status.side_effect = lambda: deepcopy(self.state)
        self.supervisor = BackgroundSupervisor(self.controller)

    def test_login_enables_remapping_without_enabling_unrequested_rgb(self):
        with patch('redragon.background.runtime.start_daemon') as start:
            self.supervisor.tick()
        start.assert_called_once_with(self.path, 'remap')

    def test_fresh_install_does_not_enable_services_before_setup(self):
        self.preferences.path.unlink()
        with patch('redragon.background.runtime.start_daemon') as start:
            self.supervisor.tick()
        start.assert_not_called()
        self.assertEqual(self.preferences.read(), {'remap': False, 'rgb': False})

    def test_keyboard_not_ready_at_login_is_retried_when_it_connects(self):
        with patch('redragon.background.runtime.start_daemon') as start:
            self.state['device'] = None
            self.supervisor.tick()
            start.assert_not_called()
            self.state['device'] = {'id': 'keyboard'}
            self.supervisor.tick()
            start.assert_called_once()

    def test_disconnected_service_restarts_without_duplicate_running_service(self):
        self.preferences.set('rgb', True)
        self.state['daemon']['running'] = True
        with patch('redragon.background.runtime.start_daemon') as start:
            self.supervisor.tick()
        start.assert_called_once_with(self.path, 'rgb')

    def test_pause_persists_and_stops_running_service(self):
        self.preferences.set('remap', False)
        self.state['daemon']['running'] = True
        with patch('redragon.background.runtime.start_daemon') as start, \
             patch('redragon.background.runtime.stop_daemon') as stop:
            self.supervisor.tick()
        start.assert_not_called()
        stop.assert_called_once_with(self.path, 'remap')
        self.assertFalse(BackgroundStore(self.path).read()['remap'])

    def test_pause_during_start_cannot_leave_new_daemon_running(self):
        def pause(*_):
            self.preferences.set('remap', False)
        with patch('redragon.background.runtime.start_daemon', side_effect=pause), \
             patch('redragon.background.runtime.stop_daemon') as stop:
            self.supervisor.tick()
        stop.assert_called_once_with(self.path, 'remap')

    def test_gui_or_cli_stop_updates_background_intent(self):
        ConfigStore(self.path).replace(DEFAULTS)
        with patch('redragon.core.runtime.stop_daemon', return_value={'running': False}):
            Controller(self.path).stop_all()
        self.assertEqual(self.preferences.read(), {'remap': False, 'rgb': False})

    def test_failed_start_is_throttled_and_retried_later(self):
        from redragon.errors import ControlError
        with patch('redragon.background.time.monotonic', return_value=100), \
             patch('redragon.background.runtime.start_daemon', side_effect=ControlError('not ready')) as start:
            self.supervisor.tick()
            self.supervisor.tick()
            self.assertEqual(start.call_count, 1)
            self.assertIn('remap', self.supervisor.errors)
        with patch('redragon.background.time.monotonic', return_value=111), \
             patch('redragon.background.runtime.start_daemon') as start:
            self.supervisor.tick()
            start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
