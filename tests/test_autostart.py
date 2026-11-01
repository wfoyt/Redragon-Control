import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from redragon import autostart
from redragon.cli import main
from redragon.errors import ControlError


class AutostartTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def test_fresh_launch_does_not_create_login_entries(self):
        autostart.ensure()
        self.assertFalse(autostart.enabled())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_upgrade_disables_xdg_entry_and_removes_managed_omarchy_hook(self):
        entry = autostart.entry_path()
        entry.parent.mkdir()
        entry.write_text('[Desktop Entry]\nExec=/old.AppImage tray\nHidden=false\n')
        hook = self.home / 'omarchy/hooks/post-boot.d/redragon-control'
        hook.parent.mkdir(parents=True)
        hook.write_text('#!/bin/sh\n# Managed by Redragon Control.\n/old.AppImage autostart run &\n')
        marker = self.home / 'redragon-control/autostart-registered'
        marker.parent.mkdir()
        marker.touch()
        autostart.ensure()
        self.assertIn('Hidden=true', entry.read_text())
        self.assertNotIn('Exec=', entry.read_text())
        self.assertFalse(hook.exists())
        self.assertFalse(marker.exists())
        autostart.ensure()  # Migration remains safe on subsequent launches.

    def test_custom_hook_is_preserved(self):
        hook = self.home / 'omarchy/hooks/post-boot.d/redragon-control'
        hook.parent.mkdir(parents=True)
        hook.write_text('#!/bin/sh\necho user managed\n')
        autostart.disable()
        self.assertEqual(hook.read_text(), '#!/bin/sh\necho user managed\n')

    def test_startup_cannot_be_reenabled(self):
        with self.assertRaisesRegex(ControlError, 'removed'):
            autostart.install(['/old.AppImage'])
        with patch('builtins.print') as output:
            self.assertEqual(main(['autostart', 'enable']), 1)
        self.assertFalse(json.loads(output.call_args.args[0])['ok'])
        self.assertFalse(autostart.entry_path().exists())

    def test_legacy_login_command_exits_without_opening_window(self):
        with patch('redragon.core.Controller.retire_background') as retire, \
             patch.dict(sys.modules, {'redragon.gui': Mock(), 'redragon.tray': Mock()}):
            self.assertEqual(main(['autostart', 'run']), 0)
            retire.assert_called_once()
            sys.modules['redragon.gui'].run.assert_not_called()
            sys.modules['redragon.tray'].run.assert_not_called()

    def test_foreground_gui_migrates_before_launch_and_custom_config_leaves_login_alone(self):
        for prefix in ([], ['--config', str(self.home / 'custom.json')]):
            gui = Mock()
            gui.run.return_value = 0
            with patch('redragon.autostart.disable') as disable, \
                 patch('redragon.core.Controller.retire_background') as retire, \
                 patch.dict(sys.modules, {'redragon.gui': gui}):
                self.assertEqual(main(prefix + ['gui']), 0)
                retire.assert_called_once()
                self.assertEqual(disable.call_count, 0 if prefix else 1)
                gui.run.assert_called_once()

    def test_demo_never_changes_startup_or_legacy_workers(self):
        gui = Mock()
        gui.run.return_value = 0
        with patch('redragon.autostart.disable') as disable, \
             patch('redragon.core.Controller.retire_background') as retire, \
             patch.dict(sys.modules, {'redragon.gui': gui}):
            self.assertEqual(main(['--demo', 'gui']), 0)
        disable.assert_not_called()
        retire.assert_not_called()

    def test_desktop_escaping_handles_reserved_characters(self):
        value = '/apps/a\\b"c`d$e%f.AppImage'
        decoded = autostart.desktop_arg(value).replace('\\\\', '\\')
        self.assertEqual(decoded, '"/apps/a\\\\b\\"c\\`d\\$e%%f.AppImage"')
