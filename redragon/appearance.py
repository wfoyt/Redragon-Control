"""Application appearance preferences, independent of keyboard profiles."""

import json
import logging
import os
from pathlib import Path
import re
import tomllib

from .config import ConfigStore, atomic_write
from .errors import ControlError

THEMES = ('auto', 'adwaita', 'omarchy')
THEME_LABELS = ('Automatic', 'Adwaita', 'Omarchy')
FALLBACK_PALETTE = {
    'background': '#1a1b26', 'foreground': '#c0caf5', 'accent': '#7aa2f7',
    'dark_background': '#13141c', 'lighter_background': '#24283b',
    'red': '#f7768e', 'green': '#9ece6a', 'yellow': '#e0af68',
}


def palette_paths():
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
    state = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state'))
    # Flatpak redirects XDG homes into its sandbox. The host paths are granted
    # read-only access in the manifest. Also support pre-4.0 Omarchy layouts.
    return tuple(dict.fromkeys(root / 'omarchy/current/theme/colors.toml' for root in
                               (state, home / '.local/state', config, home / '.config')))


def is_omarchy():
    for path in (Path('/etc/os-release'), Path('/run/host/os-release'), Path('/run/host/etc/os-release')):
        try:
            values = dict(line.split('=', 1) for line in path.read_text().splitlines()
                          if '=' in line and not line.startswith('#'))
            if any(values.get(key, '').strip('"\'').lower() == 'omarchy' for key in ('ID', 'VARIANT_ID')):
                return True
        except OSError:
            pass
    roots = [Path('/usr/share/omarchy')]
    if os.environ.get('OMARCHY_PATH'):
        roots.append(Path(os.environ['OMARCHY_PATH']))
    # Theme files can be copied to other distributions for an explicit
    # Omarchy appearance; their presence alone must not change Automatic.
    return any((root / 'bin/omarchy-theme-set').is_file() for root in roots)


def resolve_theme(choice):
    return ('omarchy' if is_omarchy() else 'adwaita') if choice == 'auto' else choice


def load_palette():
    for path in palette_paths():
        try:
            value = tomllib.loads(path.read_text())
            # A half-written or malformed palette must not inject arbitrary CSS.
            if not all(isinstance(value.get(key), str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value[key])
                       for key in ('background', 'foreground', 'accent')):
                continue
            palette = dict(FALLBACK_PALETTE)
            palette.update({key: color for key, color in value.items()
                            if key in palette and isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color)})
            # Minimal third-party palettes may omit surface variants. Use
            # their background instead of mixing light and dark surfaces.
            for key in ('dark_background', 'lighter_background'):
                if key not in value or not isinstance(value[key], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value[key]):
                    palette[key] = palette['background']
            palette['mode'] = value.get('mode')
            return palette
        except (OSError, ValueError):
            continue
    return dict(FALLBACK_PALETTE, mode='dark')


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))


def palette_is_dark(palette):
    if palette.get('mode') in ('light', 'dark'):
        return palette['mode'] == 'dark'
    return luminance(palette['background']) < .179


def omarchy_css(palette, *, variables=True):
    bg, fg, accent = (palette[key] for key in ('background', 'foreground', 'accent'))
    view, card = palette['dark_background'], palette['lighter_background']
    accent_fg = '#000000' if luminance(accent) > .179 else '#ffffff'
    colors = dict(window_bg_color=bg, window_fg_color=fg, view_bg_color=view, view_fg_color=fg,
                  headerbar_bg_color=bg, headerbar_fg_color=fg, headerbar_backdrop_color=bg,
                  sidebar_bg_color=view, sidebar_fg_color=fg, sidebar_backdrop_color=view,
                  card_bg_color=card, card_fg_color=fg, dialog_bg_color=card, dialog_fg_color=fg,
                  popover_bg_color=card, popover_fg_color=fg, accent_bg_color=accent,
                  accent_fg_color=accent_fg, accent_color=accent,
                  success_color=palette['green'], warning_color=palette['yellow'], error_color=palette['red'])
    css = '\n'.join(f'@define-color {name} {color};' for name, color in colors.items())
    if variables:
        css += '\n:root {\n' + '\n'.join(f'  --{name.replace("_", "-")}: {color};' for name, color in colors.items()) + '\n}'
    css += '\n.hero-card { border-radius: 6px; }\n.note-card { border-radius: 6px; }'
    return css


class AppearanceStore:
    def __init__(self, config_path):
        config_path = Path(config_path)
        self.path = config_path.with_name(config_path.stem + '.appearance.json')
        self.lock = ConfigStore(self.path).lock

    def read(self):
        if not self.path.exists():
            return {'theme': 'auto'}
        try:
            value = json.loads(self.path.read_text())
            if not isinstance(value, dict) or set(value) != {'theme'} or value['theme'] not in THEMES:
                raise ValueError('Expected an auto, adwaita or omarchy theme')
            return value
        except (OSError, ValueError, TypeError) as exc:
            logging.getLogger(__name__).warning('Cannot read appearance settings at %s; using Automatic: %s', self.path, exc)
            return {'theme': 'auto'}

    def set(self, theme):
        if theme not in THEMES:
            raise ControlError('Choose Automatic, Adwaita or Omarchy.')
        with self.lock():
            atomic_write(self.path, {'theme': theme})

