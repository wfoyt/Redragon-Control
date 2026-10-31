import configparser
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from redragon import autostart
from redragon.cli import main


class AutostartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home)}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        (self.home / 'omarchy').mkdir()

    def entry(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(autostart.entry_path())
        return parser['Desktop Entry']

    def test_cross_desktop_entry_and_omarchy_hook(self):
        command = ['/opt/Keyboard tools/Redragon.AppImage']
        autostart.install(command)
        entry = self.entry()
        self.assertTrue(autostart.enabled())
        self.assertEqual(entry['Exec'], '"/opt/Keyboard tools/Redragon.AppImage" "tray"')
        self.assertNotIn('OnlyShowIn', entry)
        self.assertNotIn('NotShowIn', entry)
        hook = self.home / 'omarchy/hooks/post-boot.d/redragon-control'
        self.assertIn("'/opt/Keyboard tools/Redragon.AppImage' autostart run", hook.read_text())
        self.assertEqual(subprocess.run(['sh', '-n', str(hook)]).returncode, 0)
        self.assertTrue(os.access(hook, os.X_OK))

    def test_appimage_uses_permanent_file_not_mount(self):
        with patch.dict(os.environ, {'APPIMAGE': '/home/user/My app.AppImage',
                                    'REDRAGON_APPIMAGE_LAUNCHER': '/tmp/.mount_xyz/AppRun'}):
            autostart.ensure()
        self.assertIn('/home/user/My app.AppImage', self.entry()['Exec'])
        self.assertNotIn('.mount', self.entry()['Exec'])

    def test_relocation_preserves_disabled_preference(self):
        autostart.install(['/old.AppImage'], active=False)
        with patch.dict(os.environ, {'APPIMAGE': '/new.AppImage'}):
            autostart.ensure()
        self.assertFalse(autostart.enabled())
        self.assertIn('/new.AppImage', self.entry()['Exec'])

    def test_gnome_and_kde_opt_out_is_preserved(self):
        for key in ('Hidden=true', 'X-GNOME-Autostart-enabled=false'):
            autostart.install()
            autostart.entry_path().write_text('[Desktop Entry]\nType=Application\n' + key + '\n')
            autostart.ensure()
            self.assertFalse(autostart.enabled())

    def test_removed_entry_is_not_recreated_on_next_launch(self):
        autostart.ensure()
        autostart.entry_path().unlink()
        autostart.ensure()
        self.assertFalse(autostart.entry_path().exists())

    def test_desktop_escaping_handles_reserved_characters(self):
        # Desktop string decoding happens before Exec argument decoding.
        value = '/apps/a\\b"c`d$e%f.AppImage'
        encoded = autostart.desktop_arg(value)
        decoded = encoded.replace('\\\\', '\\')
        self.assertEqual(decoded, '"/apps/a\\\\b\\"c\\`d\\$e%%f.AppImage"')

    def test_hook_does_not_start_tray_when_disabled(self):
        autostart.install(active=False)
        tray = Mock()
        with patch.dict(sys.modules, {'redragon.tray': tray}):
            self.assertEqual(main(['autostart', 'run']), 0)
        tray.run.assert_not_called()

    def test_cli_enable_disable_and_run(self):
        with patch('builtins.print') as output:
            self.assertEqual(main(['autostart', 'enable']), 0)
            self.assertTrue(json.loads(output.call_args.args[0])['result']['enabled'])
        tray = Mock()
        tray.run.return_value = 0
        with patch.dict(sys.modules, {'redragon.tray': tray}):
            self.assertEqual(main(['autostart', 'run']), 0)
        tray.run.assert_called_once_with(config_path=None)
        with patch('builtins.print'):
            self.assertEqual(main(['autostart', 'disable']), 0)
        self.assertFalse(autostart.enabled())

    def test_normal_gui_and_tray_register_but_custom_config_does_not(self):
        for command in ('gui', 'tray'):
            module = Mock()
            module.run.return_value = 0
            with patch('redragon.autostart.ensure') as ensure, patch.dict(sys.modules, {'redragon.' + command: module}):
                self.assertEqual(main([command]), 0)
                ensure.assert_called_once_with()
            with patch('redragon.autostart.ensure') as ensure, patch.dict(sys.modules, {'redragon.' + command: module}):
                self.assertEqual(main(['--config', '/tmp/custom.json', command]), 0)
                ensure.assert_not_called()

    def test_demo_does_not_register_startup(self):
        gui = Mock()
        gui.run.return_value = 0
        with patch('redragon.autostart.ensure') as ensure, patch.dict(sys.modules, {'redragon.gui': gui}):
            self.assertEqual(main(['--demo', 'gui']), 0)
        ensure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
