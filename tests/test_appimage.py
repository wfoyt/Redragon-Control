import unittest
from unittest.mock import patch
from redragon.appimage_entry import main


class AppImageLaunchTests(unittest.TestCase):
    def test_default_and_explicit_gui_keep_the_tray_alive(self):
        for arguments in ([], ['gui']):
            with patch('redragon.appimage_entry.cli.main', return_value=0) as launch:
                self.assertEqual(main(arguments), 0)
            launch.assert_called_once_with(['tray', '--open-settings'])

    def test_config_path_with_spaces_survives_routing(self):
        with patch('redragon.appimage_entry.cli.main', return_value=0) as launch:
            main(['--config', '/tmp/some directory/config.json', 'gui'])
        launch.assert_called_once_with(['--config', '/tmp/some directory/config.json', 'tray', '--open-settings'])

    def test_demo_and_cli_do_not_start_tray(self):
        for arguments in (['--demo'], ['--demo', 'gui'], ['status'], ['theme', 'adwaita']):
            with patch('redragon.appimage_entry.cli.main', return_value=0) as launch:
                main(arguments)
            launch.assert_called_once_with(arguments)
