"""Run only the bundled, narrowly scoped host hardware setup with Polkit."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .errors import ControlError


def enable_keyboard_access():
    pkexec = shutil.which('pkexec', path='/usr/bin:/bin')
    if not pkexec:
        raise ControlError('Install polkit and enable your desktop authentication agent, then try again.')
    root = Path(__file__).resolve().parent.parent
    candidates = (root / 'scripts/setup-hardware.sh', root.parent.parent / 'share/redragon-control/setup-hardware.sh')
    script = next((p for p in candidates if p.is_file()), None)
    if script is None:
        raise ControlError('The bundled hardware setup helper is missing. Reinstall Redragon Control.')
    # Root cannot reliably read a user-mounted AppImage's FUSE filesystem.
    # Stage the bundled helper in a private host directory for authentication.
    with tempfile.TemporaryDirectory(prefix='redragon-setup-') as directory:
        staged = Path(directory) / 'setup-hardware.sh'
        staged.write_bytes(script.read_bytes())
        staged.chmod(0o600)
        env = {key: value for key, value in os.environ.items()
               if key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'LANG', 'HOME', 'USER')}
        env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
        try:
            result = subprocess.run([pkexec, '/usr/bin/bash', str(staged)], env=env,
                                    capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise ControlError('Keyboard setup timed out. Close any authentication prompt and try again.') from exc
    if result.returncode in (126, 127):
        raise ControlError('Keyboard access was not enabled. Authentication was cancelled or unavailable.')
    if result.returncode:
        raise ControlError((result.stderr or result.stdout).strip()[-2000:] or 'Hardware setup failed.')
    return {'enabled': True, 'message': 'Keyboard access enabled. Reconnect your keyboard or receiver if access is still blocked.'}
