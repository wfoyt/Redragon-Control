"""Desktop login startup shared by native, source and AppImage launches."""

import configparser
import os
from pathlib import Path
import shlex
import sys

APP_ID = 'io.github.redragon.Control'


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))


def entry_path():
    return config_home() / 'autostart' / f'{APP_ID}.desktop'


def enabled():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(entry_path())
    section = parser['Desktop Entry'] if parser.has_section('Desktop Entry') else {}
    return bool(section) and section.get('Hidden', 'false').lower() != 'true' and section.get('X-GNOME-Autostart-enabled', 'true').lower() != 'false'


def launch_command():
    # APPIMAGE is the original file; AppRun normally lives in a temporary mount.
    image = os.environ.get('APPIMAGE')
    if image:
        return [str(Path(image).resolve())]
    app_run = os.environ.get('REDRAGON_APPIMAGE_LAUNCHER')
    if app_run:
        return [str(Path(app_run).resolve())]
    source = Path(__file__).resolve().parent.parent / 'run.sh'
    if source.is_file():
        return [str(source)]
    return [sys.executable, '-m', 'redragon']


def desktop_arg(value):
    # Exec argument quoting followed by desktop-entry string escaping.
    quoted = '"' + ''.join('\\' + c if c in '\\"`$' else c for c in value.replace('%', '%%')) + '"'
    return quoted.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')


def install(command=None, *, active=True):
    command = list(command or launch_command())
    entry = entry_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        '[Desktop Entry]\nType=Application\nName=Redragon Control\n'
        'Comment=Keep keyboard remapping active after signing in\n'
        'Exec=' + ' '.join(desktop_arg(arg) for arg in command + ['tray']) + '\n'
        f'Icon={APP_ID}\nTerminal=false\nStartupNotify=false\n'
        f'Hidden={str(not active).lower()}\n'
        f'X-GNOME-Autostart-enabled={str(active).lower()}\n')
    # Omarchy exposes a post-boot hook rather than guaranteeing XDG startup.
    # Keep this hook independent of Hyprland's Lua/legacy conf syntax.
    hook = config_home() / 'omarchy/hooks/post-boot.d/redragon-control'
    if hook.exists() or (config_home() / 'omarchy').is_dir() or Path('/usr/share/omarchy').is_dir():
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text('#!/bin/sh\n# Managed by Redragon Control.\n' +
                        shlex.join(command + ['autostart', 'run']) + ' >/dev/null 2>&1 &\n')
        hook.chmod(0o755)
    marker = config_home() / 'redragon-control/autostart-registered'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    return {'enabled': active, 'path': str(entry)}


def ensure():
    """Register on first use, update moved images, and preserve user opt-outs."""
    entry = entry_path()
    if not entry.exists() and (config_home() / 'redragon-control/autostart-registered').exists():
        return
    install(active=enabled() if entry.exists() else True)


def set_enabled(active):
    return install(active=active)
