from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from redragon.background import BackgroundStore, retire
from redragon.cli import main
from redragon.core import Controller
from redragon import runtime
from runtime_helpers import python_command


class BackgroundRemovalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'config.json'
        self.preferences = BackgroundStore(self.path)

    def test_upgrade_disables_both_workers_even_with_corrupt_preferences(self):
        for contents in ('{"remap": true, "rgb": true}', 'broken'):
            self.preferences.path.write_text(contents)
            with patch('redragon.runtime.stop_daemon') as stop:
                retire(Controller(self.path))
                self.assertEqual(self.preferences.read(), {'remap': False, 'rgb': False})
            self.assertEqual(stop.call_args_list[0].args, (self.path, 'remap'))
            self.assertEqual(stop.call_args_list[1].args, (self.path, 'rgb'))

    def test_cleanup_stops_tray_before_workers_to_prevent_restarts(self):
        order = []
        with patch('redragon.runtime.stop_legacy_trays', side_effect=lambda *_: order.append('tray')), \
             patch('redragon.background.retire', side_effect=lambda *_: order.append('workers')):
            Controller(self.path).retire_background()
        self.assertEqual(order, ['tray', 'workers'])

    def test_old_commands_cannot_start_or_observe_input(self):
        for command in (['daemon', 'start'], ['daemon', 'run'],
                        ['daemon', 'start', '--kind', 'rgb'],
                        ['bind', 'KEY_MUTE', 'KEY_PLAYPAUSE'], ['unbind', 'KEY_MUTE'], ['observe']):
            error = io.StringIO()
            with redirect_stderr(error), patch('redragon.lighting._FeatureDevice') as opened:
                self.assertEqual(main(['--config', str(self.path)] + command), 1)
            self.assertIn('removed', json.loads(error.getvalue())['error'])
            opened.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_legacy_tray_launcher_exits_and_open_settings_uses_same_process(self):
        from redragon.tray import run
        with patch('redragon.core.Controller.retire_background') as retire:
            self.assertEqual(run(self.path), 0)
            retire.assert_called_once()
        gui = Mock()
        gui.run.return_value = 0
        with patch('redragon.core.Controller.retire_background'), \
             patch.dict('sys.modules', {'redragon.gui': gui}):
            self.assertEqual(run(self.path, open_settings=True), 0)
        gui.run.assert_called_once_with(config_path=self.path)

    def test_legacy_tray_identity_rejects_other_configs_and_unrelated_processes(self):
        process = Mock()
        process.name = '12345'
        process.stat.return_value = SimpleNamespace(st_uid=os.getuid())
        cmdline = Mock()
        process.__truediv__ = Mock(return_value=cmdline)
        for arguments, matches in ((['python3', '-m', 'redragon', '--config', str(self.path), 'tray'], True),
                                   (['python3', '-m', 'redragon', '--config', str(self.path), 'tray', '--open-settings'], True),
                                   (['python3', '-m', 'redragon', '--config', '/other/config.json', 'tray'], False),
                                   (['python3', '-m', 'redragon', '--config', str(self.path), 'gui'], False),
                                   (['python3', '-c', 'redragon tray'], False),
                                   (['sh', '-m', 'redragon', '--config', str(self.path), 'tray'], False)):
            cmdline.read_bytes.return_value = ('\0'.join(arguments) + '\0').encode()
            self.assertEqual(runtime._legacy_tray(process, self.path), matches)
        process.stat.return_value = SimpleNamespace(st_uid=os.getuid() + 1)
        self.assertFalse(runtime._legacy_tray(process, self.path))

    def test_old_appimage_gui_route_is_stopped_but_new_foreground_instance_is_preserved(self):
        process = Mock()
        process.name = '12345'
        process.stat.return_value = SimpleNamespace(st_uid=os.getuid())
        root = self.path.parent / 'old-mount'
        loader = root / 'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
        libs = ':'.join(str(root / p) for p in ('lib', 'usr/lib/x86_64-linux-gnu', 'usr/lib'))
        cmdline = Mock()
        cmdline.read_bytes.return_value = ('\0'.join([str(loader), '--library-path', libs,
            str(root / 'usr/bin/python3'), '-P', '-m', 'redragon.appimage_entry',
            '--config', str(self.path), 'gui']) + '\0').encode()
        executable = Mock()
        executable.resolve.return_value = loader
        process.__truediv__ = Mock(side_effect=lambda key: cmdline if key == 'cmdline' else executable)
        for entry, matches in (("arguments = ['tray', '--open-settings']", True),
                               ('return cli.main(arguments)', False)):
            with patch.object(Path, 'read_text', return_value=entry):
                self.assertEqual(runtime._legacy_tray(process, self.path), matches)

    def test_status_refresh_never_opens_keyboard(self):
        device = {'id': '3554:fa09@receiver', 'vendor_id': 0x3554, 'product_id': 0xfa09,
                  'event_paths': ['/dev/input/event1'], 'hidraw_paths': ['/dev/hidraw1']}
        controller = Controller(self.path)
        with patch.object(controller, '_device', return_value=device), \
             patch.object(controller, '_devices', return_value=[device]), \
             patch('redragon.lighting._FeatureDevice') as opened:
            for _ in range(3):
                state = controller.status()
        self.assertFalse(state['capabilities']['remap'])
        opened.assert_not_called()

    def test_explicit_lighting_save_closes_hardware_on_success_and_failure(self):
        controller = Controller(self.path)
        for failure in (None, OSError('unplugged')):
            backend = Mock()
            backend.capabilities.return_value = {'rgb': True}
            backend.apply_native.return_value = {'saved_on_keyboard': True}
            backend.apply_native.side_effect = failure
            with patch.object(controller, '_lighting', return_value=backend), patch.object(controller, 'stop_lighting'):
                if failure:
                    with self.assertRaises(OSError):
                        controller.apply_lighting()
                else:
                    controller.apply_lighting()
            backend.close.assert_called_once()

    def test_upgrade_stops_real_legacy_processes_without_touching_hardware(self):
        import subprocess
        import sys
        import time
        package = self.path.parent / 'redragon'
        package.mkdir()
        (package / '__init__.py').touch()
        (package / '__main__.py').write_text('''
import fcntl, json, os, pathlib, signal, sys, threading
config = pathlib.Path(sys.argv[sys.argv.index('--config') + 1])
stopped = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stopped.set())
if 'daemon' in sys.argv:
    lock = config.with_name('config.remap.daemon.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX)
    config.with_name('config.remap.daemon.json').write_text(json.dumps({'pid': os.getpid(), 'ready': True}))
else:
    config.with_name('tray-ready').touch()
stopped.wait(15)
''')
        env = {**os.environ, 'PYTHONPATH': str(self.path.parent)}
        children = []
        try:
            for command in (['tray'], ['daemon', 'run', '--kind', 'remap']):
                children.append(subprocess.Popen(python_command() + ['-m', 'redragon', '--config', str(self.path)] + command,
                                                  cwd=self.path.parent, env=env))
            deadline = time.monotonic() + 3
            while not ((self.path.parent / 'tray-ready').exists() and runtime.daemon_status(self.path)['running']):
                self.assertLess(time.monotonic(), deadline, 'test workers did not become ready')
                time.sleep(.02)
            self.preferences.set('remap', True)
            Controller(self.path).retire_background()
            for child in children:
                self.assertEqual(child.wait(timeout=2), 0)
            self.assertFalse(runtime.daemon_status(self.path)['running'])
            self.assertEqual(self.preferences.read(), {'remap': False, 'rgb': False})
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=3)

    def test_failed_tray_shutdown_still_disables_intent_and_stops_workers(self):
        from redragon.errors import ControlError
        self.preferences.set('remap', True)
        with patch('redragon.runtime.stop_legacy_trays', side_effect=ControlError('tray stuck')), \
             patch('redragon.runtime.stop_daemon') as stop:
            with self.assertRaisesRegex(ControlError, 'tray stuck'):
                Controller(self.path).retire_background()
        self.assertEqual(stop.call_count, 2)
        self.assertFalse(self.preferences.read()['remap'])

    def test_failed_remapper_shutdown_does_not_skip_lighting_cleanup(self):
        from redragon.errors import ControlError
        with patch('redragon.runtime.stop_daemon', side_effect=[ControlError('remap stuck'), None]) as stop:
            with self.assertRaisesRegex(ControlError, 'remap stuck'):
                retire(Controller(self.path))
        self.assertEqual(stop.call_args_list[-1].args, (self.path, 'rgb'))

    def test_reset_recovers_corrupt_legacy_background_preferences(self):
        self.preferences.path.write_text('broken')
        with patch('redragon.runtime.stop_legacy_trays'), patch('redragon.runtime.stop_daemon'):
            Controller(self.path).reset_app()
        self.assertEqual(self.preferences.read(), {'remap': False, 'rgb': False})
