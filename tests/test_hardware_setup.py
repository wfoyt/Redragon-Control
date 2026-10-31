from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch
from redragon.hardware_setup import enable_keyboard_access
from redragon.errors import ControlError


class HardwareSetupTests(unittest.TestCase):
    def test_only_helper_runs_as_root_with_clean_environment(self):
        def run(argv, **kwargs):
            self.assertEqual(argv[:2], ['/usr/bin/pkexec', '/usr/bin/bash'])
            script = Path(argv[2])
            self.assertIn('70-redragon-control.rules', script.read_text())
            self.assertEqual(script.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('LD_LIBRARY_PATH', kwargs['env'])
            self.assertNotIn('PYTHONPATH', kwargs['env'])
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch('redragon.hardware_setup.shutil.which', return_value='/usr/bin/pkexec'), \
             patch('redragon.hardware_setup.subprocess.run', side_effect=run):
            self.assertTrue(enable_keyboard_access()['enabled'])

    def test_cancellation_is_not_reported_as_success(self):
        with patch('redragon.hardware_setup.shutil.which', return_value='/usr/bin/pkexec'), \
             patch('redragon.hardware_setup.subprocess.run', return_value=SimpleNamespace(returncode=126)):
            with self.assertRaisesRegex(ControlError, 'cancelled'):
                enable_keyboard_access()

    def test_missing_polkit_has_actionable_error(self):
        with patch('redragon.hardware_setup.shutil.which', return_value=None):
            with self.assertRaisesRegex(ControlError, 'polkit'):
                enable_keyboard_access()

    def test_failed_helper_does_not_claim_access_was_granted(self):
        with patch('redragon.hardware_setup.shutil.which', return_value='/usr/bin/pkexec'), \
             patch('redragon.hardware_setup.subprocess.run', return_value=SimpleNamespace(returncode=1, stderr='modprobe failed', stdout='')):
            with self.assertRaisesRegex(ControlError, 'modprobe failed'):
                enable_keyboard_access()

    def test_helper_contains_the_packaged_device_rules_and_valid_shell(self):
        root = Path(__file__).resolve().parent.parent
        script = root / 'scripts/setup-hardware.sh'
        self.assertIn((root / 'data/70-redragon-control.rules').read_text(), script.read_text())
        subprocess.run(['bash', '-n', str(script)], check=True)
