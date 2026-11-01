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
bin_dir = Path.home() / '.local/bin'
data_dir = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
apps = data_dir / 'applications'
icons = data_dir / 'icons/hicolor/scalable/apps'
for directory in (bin_dir, apps, icons):
    directory.mkdir(parents=True, exist_ok=True)
launcher = bin_dir / 'redragonctl'
launcher.write_text('#!/usr/bin/env bash\nexec ' + shlex.quote(str(root / 'run.sh')) + ' "$@"\n')
launcher.chmod(0o755)
from redragon.autostart import desktop_arg, disable
desktop_exec = desktop_arg(str(launcher))
template = (root / 'data/io.github.redragon.Control.desktop.in').read_text()
(apps / 'io.github.redragon.Control.desktop').write_text(template.replace('@LAUNCHER@', desktop_exec))
disable()
from redragon.core import Controller
Controller().retire_background()
icon = root / 'data/io.github.redragon.Control.svg'
if icon.exists():
    (icons / icon.name).write_bytes(icon.read_bytes())
print(f'Installed {launcher}, desktop launcher; removed legacy login startup. Keep project directory at {root}.')
PY
