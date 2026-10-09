#!/usr/bin/env bash
# Install only desktop/CLI launchers. System dependencies and udev are separate.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec /usr/bin/python3 - "$task_root" <<'PY'
from pathlib import Path
import os
import shlex
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from redragon.background import BackgroundStore
from redragon.config import ConfigStore, atomic_write
from redragon.runtime import daemon_status
settings_path = ConfigStore().path
background = BackgroundStore(settings_path)
if not background.path.exists():
    atomic_write(background.path, {'remap': daemon_status(settings_path)['running'], 'rgb': daemon_status(settings_path, 'rgb')['running']})
bin_dir = Path.home() / '.local/bin'
data_dir = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
apps = data_dir / 'applications'
icons = data_dir / 'icons/hicolor/scalable/apps'
config_dir = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
autostart = config_dir / 'autostart'
for directory in (bin_dir, apps, icons, autostart):
    directory.mkdir(parents=True, exist_ok=True)
launcher = bin_dir / 'redragonctl'
launcher.write_text('#!/usr/bin/env bash\nexec ' + shlex.quote(str(root / 'run.sh')) + ' "$@"\n')
launcher.chmod(0o755)
# Desktop Exec uses its own escaping, not shell quoting.
desktop_exec = '"' + str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
template = (root / 'data/io.github.redragon.Control.desktop.in').read_text()
(apps / 'io.github.redragon.Control.desktop').write_text(template.replace('@LAUNCHER@', desktop_exec))
(autostart / 'io.github.redragon.Control.desktop').write_text(
    '[Desktop Entry]\nType=Application\nName=Redragon Control\n'
    'Comment=Keep keyboard remapping and lighting active in the tray\n'
    f'Exec={desktop_exec} tray\nIcon=io.github.redragon.Control\n'
    'Terminal=false\nX-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n')
icon = root / 'data/io.github.redragon.Control.svg'
if icon.exists():
    (icons / icon.name).write_bytes(icon.read_bytes())
print(f'Installed {launcher}, GNOME launcher and tray login autostart. Keep project directory at {root}.')
PY
