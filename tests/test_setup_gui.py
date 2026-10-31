"""Optional GTK integration checks: REDRAGON_GUI_TESTS=1 on a test display."""

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('REDRAGON_GUI_TESTS') == '1', 'requires an isolated GTK display')
class SetupGuiTests(unittest.TestCase):
    def setUp(self):
        from redragon.gui import ControlApplication, GLib, Gtk
        self.context = GLib.MainContext.default()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'config.json'
        self.app = ControlApplication(self.path, demo=True)
        self.app.register(None)
        # Test the settled page state independently of compositor timing and
        # ViewStack crossfades, which can pause on a headless display.
        settings = Gtk.Settings.get_default()
        animations = settings.get_property('gtk-enable-animations')
        settings.set_property('gtk-enable-animations', False)
        self.addCleanup(settings.set_property, 'gtk-enable-animations', animations)
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

    def test_close_while_busy_does_not_destroy_the_window_or_theme(self):
        self.window._busy = True
        try:
            with patch.object(self.window, '_toast') as toast:
                self.assertTrue(self.window.emit('close-request'))
            toast.assert_called_once()
            self.assertFalse(self.window.theme_manager.closed)
        finally:
            self.window._busy = False

    def test_first_page_has_access_button_disabled_in_demo(self):
        self.assertEqual(self.window.hardware_access_button.get_label(), 'Enable keyboard access')
        self.assertFalse(self.window.hardware_access_button.get_sensitive())
        with patch('redragon.hardware_setup.enable_keyboard_access') as enable:
            self.window._enable_keyboard_access()
        enable.assert_not_called()

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

    def test_preview_is_only_mapped_on_lighting_in_setup_and_main(self):
        window = self.window
        self.assertFalse(window.preview.get_mapped())
        window._show_setup_step(1); self.settle()
        self.assertTrue(window.preview.get_mapped())
        window._show_setup_step(2); self.settle()
        self.assertFalse(window.preview.get_mapped())
        window._finish_setup(); self.settle()
        self.assertTrue(window.preview.get_mapped())
        # Broadway can pause its frame clock when its browser is hidden. Run
        # GTK's allocation at the real window size before checking geometry.
        window.allocate(window.get_width(), window.get_height(), -1, None)
        selector_ok, selector = window.device_dropdown.compute_bounds(window)
        preview_ok, preview = window.preview.compute_bounds(window)
        self.assertTrue(selector_ok and preview_ok)
        self.assertLessEqual(selector.get_y() + selector.get_height(), preview.get_y())
        for name in ('buttons', 'recovery'):
            window.stack.set_visible_child_name(name); self.settle()
            self.assertFalse(window.preview.get_mapped())
            self.assertTrue(window.device_dropdown.get_mapped())
        window.stack.set_visible_child_name('lighting'); self.settle()
        self.assertTrue(window.preview.get_mapped())

    def test_static_color_uses_only_onboard_presets(self):
        window = self.window
        self.assertFalse(window.color_entry.get_editable())
        self.assertTrue(window.native_color_dropdown.get_visible())
        window.native_color_dropdown.set_selected(5)
        self.assertEqual(window.color_entry.get_text(), '#00ffff')
        window.brightness_scale.set_value(62)
        self.assertEqual(window.brightness_scale.get_value(), 50)

    def test_appearance_switches_between_adwaita_and_omarchy_without_restart(self):
        window = self.window
        window._finish_setup(); self.settle()
        window._appearance(); self.settle()
        self.addCleanup(window.appearance_dialog.close)
        window.appearance_row.set_selected(1); self.settle()
        self.assertEqual(window.controller.appearance()['theme'], 'adwaita')
        self.assertEqual(window.theme_manager.signature[0], '')
        window.appearance_row.set_selected(2); self.settle()
        self.assertEqual(window.controller.appearance()['theme'], 'omarchy')
        self.assertIn('--window-bg-color:', window.theme_manager.signature[0])
        self.assertFalse(self.path.exists(), 'demo appearance must not write keyboard settings')

    def test_omarchy_palette_changes_reload_without_polling_or_hardware(self):
        from redragon import appearance, ui_theme
        palette = self.path.parent / 'theme/colors.toml'
        palette.parent.mkdir()
        colors = 'background = "#17121e"\nforeground = "#ffffff"\naccent = "#ff9d45"\n'
        palette.write_text(colors)
        with patch.object(appearance, 'palette_paths', return_value=[palette]), \
             patch.object(ui_theme, 'palette_paths', return_value=[palette]):
            self.window.controller.set_theme('omarchy')
            self.window.theme_manager.reload()
            replacement = palette.with_suffix('.new')
            replacement.write_text(colors.replace('#ff9d45', '#00ffff'))
            replacement.replace(palette)
            deadline = time.monotonic() + 3
            while '#00ffff' not in self.window.theme_manager.signature[0]:
                self.assertLess(time.monotonic(), deadline, 'theme file change was not applied')
                self.context.iteration(False)
                time.sleep(.005)


    def test_lighting_save_preserves_unsaved_wheel_actions(self):
        window = self.window
        window._finish_setup(); self.settle()
        editor = window._binding_editors['KEY_MUTE']
        editor.set_active_id('KEY_PLAYPAUSE')
        window.color_entry.set_text('#00ff00')
        window._save_lighting(); self.settle()
        self.assertEqual(window.controller._config()['lighting']['color'], '#00ff00')
        self.assertEqual(editor.get_active_id(), 'KEY_PLAYPAUSE')
        self.assertEqual(window.controller._config()['bindings'], {})

    def test_binding_and_runtime_changes_preserve_unsaved_edits(self):
        window = self.window
        window._finish_setup(); self.settle()
        editor = window._binding_editors['KEY_MUTE']
        editor.set_active_id('KEY_PLAYPAUSE')
        window.color_entry.set_text('#00ff00')
        window._run(lambda: window.controller.set_binding('KEY_A', 'KEY_B')); self.settle()
        self.assertEqual(editor.get_active_id(), 'KEY_PLAYPAUSE')
        window._save_wheel(); self.settle()
        self.assertEqual(window.controller._config()['bindings'],
                         {'KEY_A': 'KEY_B', 'KEY_MUTE': 'KEY_PLAYPAUSE'})
        window._toggle_remapper(); self.settle()
        self.assertEqual(window.color_entry.get_text(), '#00ff00')
        self.assertNotEqual(window.controller._config()['lighting']['color'], '#00ff00')

    def test_importing_same_profile_discards_unsaved_edits(self):
        from redragon.config import atomic_write
        window = self.window
        window._finish_setup(); self.settle()
        saved = window.controller._config()
        profile = self.path.parent / 'saved.json'
        atomic_write(profile, saved)
        window.color_entry.set_text('#00ff00')
        window._binding_editors['KEY_MUTE'].set_active_id('KEY_PLAYPAUSE')
        with patch.object(window, '_file_dialog', side_effect=lambda save, callback: callback(profile)):
            window._import_profile(); self.settle()
        self.assertEqual(window.color_entry.get_text(), saved['lighting']['color'])
        self.assertEqual(window._binding_editors['KEY_MUTE'].get_active_id(), 'default')

    def test_adding_wheel_binding_in_setup_updates_editor_and_saves(self):
        from redragon.gui import Adw
        window = self.window
        window._show_setup_step(2)
        dialogs = []
        with patch.object(Adw.AlertDialog, 'present', new=lambda dialog, parent: dialogs.append(dialog)):
            window._add_binding()
        dialog = dialogs[0]
        source = dialog.get_extra_child().get_first_child()
        source.set_text('KEY_MUTE')
        source.get_next_sibling().set_text('KEY_PLAYPAUSE')
        dialog.emit('response', 'save')
        self.assertEqual(window._binding_editors['KEY_MUTE'].get_active_id(), 'KEY_PLAYPAUSE')
        window._apply_setup(); self.settle()
        self.assertEqual(window.controller._config()['bindings'], {'KEY_MUTE': 'KEY_PLAYPAUSE'})

    def test_editors_are_disabled_during_an_operation_and_restored_on_failure(self):
        window = self.window
        window._finish_setup(); self.settle()
        release = threading.Event()
        self.addCleanup(release.set)
        def operation():
            release.wait(2)
            raise RuntimeError('Simulated operation failure')
        with patch.object(window, '_error') as error:
            window._run(operation)
            self.assertFalse(window.device_dropdown.is_sensitive())
            self.assertFalse(window.color_entry.is_sensitive())
            release.set()
            self.settle()
        error.assert_called_once()
        self.assertTrue(window.color_entry.is_sensitive())


if __name__ == '__main__':
    unittest.main()
