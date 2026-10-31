from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from redragon.config import DEFAULTS, validate_config
from redragon.errors import ControlError
from redragon.native_lighting import NativeLighting, breathing_frames, effect_frames, validate_frames
from redragon.effects import NATIVE_EFFECTS, MODES
from redragon.devices import ConnectionStore
from redragon.lighting import LightingBackend, wireless_packet


def original_frames():
    frames = []
    for sequence in range(10):
        frame = bytearray(20)
        frame[:5] = bytes((0x13, 0x44, 10, sequence, 14 if sequence < 9 else 2))
        if sequence == 9:
            frame[5:7] = b'\x5a\xa5'
        frame[-1] = sum(frame[:-1]) & 255
        frames.append(bytes(frame))
    return frames


SETTINGS = {'mode': 'smooth-breathing', 'color': '#00ffff', 'brightness': 75, 'speed': 50}


class NativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / 'config.json'
        self.native = NativeLighting(Mock(), '3554:fa09@receiver', self.config)
        self.original = original_frames()

    def test_only_documented_breathing_fields_change(self):
        changed = breathing_frames(self.original, SETTINGS)
        validate_frames(changed)
        differences = {(i, j) for i in range(10) for j in range(19)
                       if self.original[i][j] != changed[i][j]}
        self.assertEqual(differences, {(0, 15), (4, 9), (4, 10)})
        self.assertEqual(changed[0][15], 2)
        self.assertEqual(changed[4][9:11], bytes((3, 0x25)))

    def test_all_official_effects_use_correct_pairs_and_preserve_other_fields(self):
        locations = [(4, i) for i in range(9, 18, 2)] + [(5, i) for i in range(5, 18, 2)] + [(6, i) for i in range(5, 14, 2)]
        self.assertEqual([pair[0] for pair in NATIVE_EFFECTS.values()], list(range(2, 19)))
        for (mode, (effect_id, _)), (page, offset) in zip(NATIVE_EFFECTS.items(), locations):
            with self.subTest(mode=mode):
                original = [bytearray(r) for r in self.original]
                original[page][offset + 1] = 0x47
                original[page][-1] = sum(original[page][:-1]) & 255
                original = [bytes(r) for r in original]
                changed = effect_frames(original, {**SETTINGS, 'mode':mode})
                differences = {(i,j) for i in range(10) for j in range(19) if original[i][j] != changed[i][j]}
                self.assertEqual(differences, {(0,15),(page,offset),(page,offset+1)})
                self.assertEqual(changed[0][15], effect_id)
                self.assertEqual(changed[page][offset], 3)
                self.assertEqual(changed[page][offset+1], 0x25 if mode == 'smooth-breathing' else 0x27)
                validate_frames(changed)

    def test_legacy_breathing_profile_migrates_and_is_not_a_cli_choice(self):
        config = deepcopy(DEFAULTS)
        config['lighting'].update(mode='breathing',color='#00ccbb')
        migrated = validate_config(config)
        self.assertEqual(migrated['lighting']['mode'], 'smooth-breathing')
        self.assertEqual(migrated['lighting']['color'], '#00ffff')
        self.assertEqual(config['lighting']['mode'], 'breathing')
        self.assertNotIn('breathing', MODES)

    def test_rejects_unsupported_color_and_corrupt_layout(self):
        with self.assertRaises(ControlError):
            breathing_frames(self.original, {**SETTINGS, 'color': '#00ccbb'})
        broken = self.original.copy()
        broken[0] = bytes(20)
        with self.assertRaises(ControlError):
            breathing_frames(broken, SETTINGS)
        config = deepcopy(DEFAULTS)
        config['lighting'] = {**SETTINGS, 'color': '#00ccbb'}
        with self.assertRaises(ControlError):
            validate_config(config)

    def test_backup_precedes_write_and_unchanged_settings_do_not_rewrite(self):
        def check_write(_):
            self.assertTrue(self.native.path.exists())
            self.assertEqual(self.native._original(), self.original)
        with patch.object(self.native, 'read', return_value=self.original), \
             patch.object(self.native, 'write', side_effect=check_write) as write:
            self.native.apply(SETTINGS)
            self.native.apply(SETTINGS)
            self.assertEqual(write.call_count, 1)
            self.native.apply({**SETTINGS, 'mode':'rainbow'})
            self.assertEqual(write.call_count, 2)
            self.native.restore()
            self.assertEqual(write.call_args.args[0], self.original)
            self.assertFalse(self.native.path.exists())

    def test_failed_apply_restores_original(self):
        with patch.object(self.native, 'read', return_value=self.original), \
             patch.object(self.native, 'write', side_effect=[ControlError('Failed'), None]) as write:
            with self.assertRaises(ControlError):
                self.native.apply(SETTINGS)
            self.assertEqual(write.call_args.args[0], self.original)
            self.assertFalse(self.native.path.exists())

    def test_failed_restore_retains_backup_for_next_connection(self):
        with patch.object(self.native, 'read', return_value=self.original), \
             patch.object(self.native, 'write'):
            self.native.apply(SETTINGS)
        with patch.object(self.native, 'write', side_effect=OSError('Disconnected')):
            with self.assertRaises(OSError):
                self.native.restore()
        self.assertEqual(self.native._original(), self.original)
        other = NativeLighting(Mock(), '3554:fa09@other', self.config)
        with self.assertRaises(ControlError):
            other._original()

    def test_write_requires_verified_readback_even_after_echoes(self):
        with patch.object(self.native, '_send_acknowledged'), \
             patch.object(self.native, 'read', return_value=self.original):
            with self.assertRaises(ControlError):
                self.native.write(breathing_frames(self.original, SETTINGS))

    def test_missing_fragment_echo_retries_idempotent_fragment(self):
        packet = wireless_packet(4,10,0,b'\x0e')
        self.native.hid.fd = 7
        with patch('redragon.native_lighting.select.select', side_effect=[([],[],[]),([7],[],[])]), \
             patch('redragon.native_lighting.os.read', return_value=packet):
            self.native._send_acknowledged(packet)
        self.assertEqual(self.native.hid.send_output.call_count,2)

    def test_wired_native_writes_are_blocked_before_hardware_access(self):
        backend = LightingBackend({'id':'258a:010c@wired','vendor_id':0x258a,'product_id':0x010c})
        self.assertEqual(backend.capabilities()['modes'],[])
        with patch.object(backend,'_open_verified') as opened:
            with self.assertRaises(ControlError):
                backend.apply_native(SETTINGS,self.config)
            opened.assert_not_called()

    def test_recovery_accepts_only_explicitly_linked_alternate_connection(self):
        with patch.object(self.native,'read',return_value=self.original), patch.object(self.native,'write'):
            self.native.apply(SETTINGS)
        alternate = NativeLighting(Mock(),'258a:010c@wired',self.config)
        with self.assertRaises(ControlError): alternate._original()
        ConnectionStore(self.config).link('3554:fa09@receiver','258a:010c@wired')
        self.assertEqual(alternate._original(),self.original)

    def test_static_and_off_only_change_known_lighting_fields(self):
        for mode, color, brightness in (('static', '#00ffff', 75), ('off', '#ff0000', 100)):
            changed = effect_frames(self.original, {**SETTINGS, 'mode': mode, 'color': color, 'brightness': brightness})
            validate_frames(changed)
            differences = {(i, j) for i in range(10) for j in range(19)
                           if self.original[i][j] != changed[i][j]}
            self.assertLessEqual(differences, {(0, 15), (4, 7), (4, 8)})
            self.assertEqual(changed[0][15], 1)
            self.assertEqual(changed[4][7], 3 if mode == 'static' else 0)
            self.assertEqual(changed[4][8] >> 4, self.original[4][8] >> 4)
            self.assertEqual(changed[4][8] & 15, 5 if mode == 'static' else self.original[4][8] & 15)

    def test_completed_save_survives_close_and_next_session(self):
        from redragon.lighting import LightingBackend
        with patch.object(self.native, 'read', return_value=self.original), patch.object(self.native, 'write'):
            self.native.apply(SETTINGS)
        backend = LightingBackend({'vendor_id': 0x3554, 'product_id': 0xfa09})
        backend._native = self.native
        backend._session = MagicMock()
        with patch.object(self.native, 'restore') as restore:
            backend.close()
            self.native.recover()
            restore.assert_not_called()
        self.assertTrue(self.native.path.exists())

    def test_unchanged_hardware_is_not_rewritten_across_sessions(self):
        current = effect_frames(self.original, SETTINGS)
        with patch.object(self.native, 'read', return_value=current), patch.object(self.native, 'write') as write:
            self.native.apply(SETTINGS)
            self.native.last_settings = None
            self.native.apply(SETTINGS)
        write.assert_not_called()

    def test_interrupted_save_is_recovered_before_another_apply(self):
        from redragon.config import atomic_write
        atomic_write(self.native.path, {'device_id': self.native.device_id, 'frames': [r.hex() for r in self.original]})
        with patch.object(self.native, 'write') as write:
            self.native.recover()
        write.assert_called_once_with(self.original)
        self.assertFalse(self.native.path.exists())

    def test_saved_lighting_preserves_current_unrelated_keyboard_settings(self):
        with patch.object(self.native, 'read', return_value=self.original), patch.object(self.native, 'write'):
            self.native.apply(SETTINGS)
        current = [bytearray(frame) for frame in self.original]
        current[0][7] ^= 1
        current[0][-1] = sum(current[0][:-1]) & 255
        current = [bytes(frame) for frame in current]
        with patch.object(self.native, 'read', return_value=current), patch.object(self.native, 'write') as write:
            self.native.apply({**SETTINGS, 'mode': 'rainbow'})
        self.assertEqual(write.call_args.args[0][0][7], current[0][7])

    def test_failed_change_keeps_last_successful_save_and_original_backup(self):
        current = effect_frames(self.original, SETTINGS)
        with patch.object(self.native, 'read', return_value=self.original), patch.object(self.native, 'write'):
            self.native.apply(SETTINGS)
        with patch.object(self.native, 'read', return_value=current), \
             patch.object(self.native, 'write', side_effect=[ControlError('Failed'), None]) as write:
            with self.assertRaises(ControlError):
                self.native.apply({**SETTINGS, 'mode': 'rainbow'})
        self.assertEqual(write.call_args.args[0], current)
        self.assertEqual(self.native._original(), self.original)
        with patch.object(self.native, 'write') as write:
            self.native.recover()
            write.assert_not_called()

    def test_failed_explicit_restore_is_marked_for_recovery(self):
        with patch.object(self.native, 'read', return_value=self.original), patch.object(self.native, 'write'):
            self.native.apply(SETTINGS)
        with patch.object(self.native, 'write', side_effect=OSError('Disconnected')):
            with self.assertRaises(OSError):
                self.native.restore()
        with patch.object(self.native, 'write') as write:
            self.native.recover()
        write.assert_called_once_with(self.original)
        self.assertFalse(self.native.path.exists())


if __name__ == '__main__':
    unittest.main()
