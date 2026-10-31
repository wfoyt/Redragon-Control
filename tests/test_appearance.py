from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from redragon import appearance
from redragon.config import ConfigStore, DEFAULTS
from redragon.core import Controller
from redragon.errors import ControlError


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'config.json'

    def test_auto_selects_omarchy_only_on_omarchy_and_explicit_choices_win(self):
        for installed in (True, False):
            with patch.object(appearance, 'is_omarchy', return_value=installed):
                self.assertEqual(appearance.resolve_theme('auto'), 'omarchy' if installed else 'adwaita')
                self.assertEqual(appearance.resolve_theme('adwaita'), 'adwaita')
                self.assertEqual(appearance.resolve_theme('omarchy'), 'omarchy')

    def test_host_os_release_is_used_inside_flatpak(self):
        def read(path, *_, **__):
            return 'ID=org.gnome.Platform\n' if str(path) == '/etc/os-release' else 'ID="omarchy"\nID_LIKE=arch\n'
        with patch.object(Path, 'read_text', read):
            self.assertTrue(appearance.is_omarchy())

    def test_arch_alone_does_not_count_as_omarchy(self):
        with patch.object(Path, 'read_text', return_value='ID=arch\n'), \
             patch.object(Path, 'is_file', return_value=False):
            self.assertFalse(appearance.is_omarchy())

    def test_copied_omarchy_palette_does_not_change_default_on_other_distros(self):
        with patch.object(Path, 'read_text', return_value='ID=fedora\n'), \
             patch.object(Path, 'is_file', lambda path: path.name == 'colors.toml'):
            self.assertEqual(appearance.resolve_theme('auto'), 'adwaita')

    def test_settings_persist_separately_and_profiles_do_not_override_them(self):
        controller = Controller(self.path)
        controller.set_theme('adwaita')
        self.assertEqual(Controller(self.path).appearance()['theme'], 'adwaita')
        ConfigStore(self.path).replace(deepcopy(DEFAULTS))
        profile = self.path.parent / 'profile.json'
        controller.export_profile(profile)
        controller.import_profile(profile)
        self.assertEqual(controller.appearance()['theme'], 'adwaita')
        self.assertEqual(set(json.loads(profile.read_text())), set(DEFAULTS))

    def test_demo_theme_never_writes_files(self):
        controller = Controller(self.path, demo=True)
        controller.set_theme('omarchy')
        self.assertEqual(controller.appearance()['theme'], 'omarchy')
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_invalid_preference_is_rejected_without_replacing_previous_choice(self):
        store = appearance.AppearanceStore(self.path)
        store.set('adwaita')
        with self.assertRaises(ControlError):
            store.set('invalid')
        self.assertEqual(store.read()['theme'], 'adwaita')

    def test_palette_supports_light_and_dark_and_rejects_css_injection(self):
        palette_path = self.path.parent / 'colors.toml'
        with patch.object(appearance, 'palette_paths', return_value=[palette_path]):
            palette_path.write_text('background = "#ffffff"\nforeground = "#111111"\naccent = "#0000ff"\nmode = "light"\n')
            self.assertFalse(appearance.palette_is_dark(appearance.load_palette()))
            palette_path.write_text('background = "#111111"\nforeground = "#ffffff"\naccent = "#00ffff"\n')
            self.assertTrue(appearance.palette_is_dark(appearance.load_palette()))
            palette_path.write_text('background = "#111111"\nforeground = "#ffffff"\naccent = "red; } button { opacity: 0"\n')
            self.assertEqual(appearance.load_palette()['accent'], appearance.FALLBACK_PALETTE['accent'])
            palette_path.write_text('invalid = [')
            self.assertEqual(appearance.load_palette()['background'], appearance.FALLBACK_PALETTE['background'])

    def test_legacy_custom_static_color_migrates_without_changing_profile_input(self):
        from redragon.config import validate_config
        value = deepcopy(DEFAULTS)
        value['lighting']['color'] = '#00ccbb'
        self.assertEqual(validate_config(value)['lighting']['color'], '#00ffff')
        self.assertEqual(value['lighting']['color'], '#00ccbb')

    def test_corrupt_preferences_fall_back_without_destroying_the_file(self):
        store = appearance.AppearanceStore(self.path)
        for content in ('{broken', '{"theme": "unknown"}', 'null'):
            store.path.write_text(content)
            with self.assertLogs('redragon.appearance', level='WARNING'):
                self.assertEqual(store.read(), {'theme': 'auto'})
            self.assertEqual(store.path.read_text(), content)
        store.set('adwaita')
        self.assertEqual(store.read(), {'theme': 'adwaita'})
