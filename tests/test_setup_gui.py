"""Optional GTK integration checks: REDRAGON_GUI_TESTS=1 on a test display."""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('REDRAGON_GUI_TESTS') == '1', 'requires an isolated GTK display')
class SetupGuiTests(unittest.TestCase):
    def setUp(self):
        from redragon.gui import ControlApplication, GLib
        self.context = GLib.MainContext.default()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'config.json'
        self.app = ControlApplication(self.path, demo=True)
        self.app.register(None)
        self.app.activate()
        self.window = self.app.window
        self.assertIsNotNone(self.window)
        self.addCleanup(self.window.close)
        self.settle()

    def settle(self):
        started = time.monotonic()
        deadline = started + 5
        # Frame-clock sources may always be pending while a preview animates.
        while self.window._busy or time.monotonic() < started + .1:
            self.assertLess(time.monotonic(), deadline, 'GUI operation did not finish')
            for _ in range(100):
                if not self.context.pending():
                    break
                self.context.iteration(False)
            time.sleep(.005)

    def test_next_discards_unapplied_edits_and_finish_restores_main_controls(self):
        window = self.window
        self.assertEqual(window._setup_step, 0)
        window._advance_setup(); self.settle()
        self.assertEqual(window._setup_step, 1)
        window.color_entry.set_text('#00ff00')
        with patch.object(window.controller, 'set_lighting') as lighting:
            window._advance_setup()
        lighting.assert_not_called()
        self.assertEqual(window._setup_step, 2)
        window._binding_editors['KEY_MUTE'].set_active_id('KEY_PLAYPAUSE')
        window._setup_bindings['KEY_A'] = 'KEY_B'
        window._advance_setup()
        self.assertEqual(window._setup_step, 3)
        self.assertEqual(window.controller._config()['bindings'], {})
        self.assertEqual(window._binding_editors['KEY_MUTE'].get_active_id(), 'default')
        window._advance_setup(); self.settle()
        self.assertFalse(window._in_setup)
        self.assertEqual(window.root_stack.get_visible_child_name(), 'control')
        self.assertIsNotNone(window.stack.get_child_by_name('lighting'))
        self.assertIsNotNone(window.stack.get_child_by_name('buttons'))
        self.assertEqual([page.get_name() for page in window.stack.get_pages()],
                         ['lighting', 'buttons', 'recovery'])
        self.assertFalse(window.setup_store.completed(), 'demo must not save completion')
        self.assertFalse(self.path.exists(), 'demo must not write settings')

    def test_save_combines_wheel_and_custom_keys_and_starts_remapping(self):
        window = self.window
        window._show_setup_step(2)
        window._setup_bindings['KEY_A'] = 'KEY_B'
        window._binding_editors['KEY_MUTE'].set_active_id('KEY_PLAYPAUSE')
        window._apply_setup(); self.settle()
        self.assertEqual(window._setup_step, 2)
        self.assertEqual(window.controller._config()['bindings'],
                         {'KEY_A': 'KEY_B', 'KEY_MUTE': 'KEY_PLAYPAUSE'})
        self.assertTrue(window.controller._demo_running)
        window._advance_setup()
        self.assertEqual(window._setup_step, 3)

    def test_apply_lighting_stays_on_page_until_next(self):
        window = self.window
        window._show_setup_step(1)
        window.color_entry.set_text('#00ff00')
        self.assertEqual(window.setup_apply.get_label(), 'Apply')
        self.assertEqual(window.setup_next.get_label(), 'Next')
        window._apply_setup(); self.settle()
        self.assertEqual(window._setup_step, 1)
        self.assertEqual(window.controller._config()['lighting']['color'], '#00ff00')
        window.color_entry.set_text('#0000ff')
        window._advance_setup()
        self.assertEqual(window._setup_step, 2)
        self.assertEqual(window.controller._config()['lighting']['color'], '#00ff00')

    def test_next_works_when_lighting_cannot_be_applied(self):
        window = self.window
        window._show_setup_step(1)
        window.state['device'] = None
        window._update_setup_navigation()
        self.assertFalse(window.setup_apply.get_sensitive())
        self.assertTrue(window.setup_next.get_sensitive())
        window._advance_setup()
        self.assertEqual(window._setup_step, 2)

    def test_import_button_opens_profile_picker(self):
        window = self.window
        with patch.object(window, '_file_dialog') as picker:
            window.setup_import.emit('clicked')
        picker.assert_called_once_with(False, window._load_setup_profile, window._setup_import_closed)
        self.assertTrue(window._setup_import_pending)
        with patch.object(window.controller, 'detect_keyboard') as detect:
            window._setup_scan()
        detect.assert_not_called()
        window._setup_import_closed()
        self.assertFalse(window._setup_import_pending)

    def test_profile_import_skips_to_welcome_without_completing_setup(self):
        from copy import deepcopy
        from redragon.config import DEFAULTS, atomic_write
        window = self.window
        profile = deepcopy(DEFAULTS)
        profile['device_id'] = '3554:fa09@different'
        profile['lighting']['color'] = '#00ff00'
        profile['bindings'] = {'KEY_MUTE': 'KEY_PLAYPAUSE'}
        source = self.path.parent / 'import.json'
        atomic_write(source, profile)
        selected = window.controller._config()['device_id']
        with patch.object(window.controller, 'apply_lighting') as lighting, \
             patch.object(window.controller, 'start_daemon') as remap:
            window._load_setup_profile(source); self.settle()
        self.assertEqual(window._setup_step, 3)
        self.assertTrue(window._in_setup)
        self.assertFalse(window.setup_store.completed())
        self.assertEqual(window.controller._config()['device_id'], selected)
        self.assertEqual(window.controller._config()['lighting'], profile['lighting'])
        self.assertEqual(window.controller._config()['bindings'], profile['bindings'])
        self.assertIn('Profile imported', window.setup_summary.get_text())
        lighting.assert_not_called()
        remap.assert_not_called()
        window._setup_go_back()
        self.assertEqual(window._setup_step, 0)

    def test_invalid_import_stays_on_detection_page_and_preserves_settings(self):
        window = self.window
        before = window.controller._config()
        source = self.path.parent / 'invalid.json'
        source.write_text('{"lighting": "invalid"}')
        with patch.object(window, '_error') as error:
            window._load_setup_profile(source); self.settle()
        error.assert_called_once()
        self.assertEqual(window._setup_step, 0)
        self.assertFalse(window._setup_profile_imported)
        self.assertEqual(window.controller._config(), before)

    def test_real_completion_is_saved_and_reenables_profile_actions(self):
        window = self.window
        window._show_setup_step(3)
        state = dict(window.state, demo=False)
        # Use the real completion file, with hardware status isolated.
        window.controller.demo = False
        with patch.object(window.controller, 'status', return_value=state):
            window._advance_setup(); self.settle()
        self.assertTrue(window.setup_store.completed())
        for name in ('save-profile', 'load-profile', 'import-profile', 'export-profile'):
            self.assertTrue(window.lookup_action(name).get_enabled())


if __name__ == '__main__':
    unittest.main()
