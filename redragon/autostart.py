"""Retire desktop login startup left by previous versions."""

import os
from pathlib import Path
from .errors import ControlError

APP_ID = 'io.github.redragon.Control'


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))


def entry_path():
    return config_home() / 'autostart' / f'{APP_ID}.desktop'


def enabled():
    return False


def desktop_arg(value):
    # Exec argument quoting followed by desktop-entry string escaping.
    quoted = '"' + ''.join('\\' + c if c in '\\"`$' else c for c in value.replace('%', '%%')) + '"'
    return quoted.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')


def disable():
    entry = entry_path()
    if entry.exists():
        entry.write_text('[Desktop Entry]\nType=Application\nName=Redragon Control\nHidden=true\nX-GNOME-Autostart-enabled=false\n')
    hook = config_home() / 'omarchy/hooks/post-boot.d/redragon-control'
    if hook.is_file() and '# Managed by Redragon Control.' in hook.read_text():
        hook.unlink()
    marker = config_home() / 'redragon-control/autostart-registered'
    marker.unlink(missing_ok=True)
    return {'enabled': False, 'path': str(entry)}


def ensure():
    return disable()


def install(command=None, *, active=True):
    if active:
        raise ControlError('Automatic startup has been removed. Open the app to change lighting, then close it to quit.')
    return disable()


def set_enabled(active):
    return install(active=active)
