"""Run subprocess checks under either host Python or the bundled AppImage loader."""
import os
from pathlib import Path
import sys


def python_command():
    launcher = os.environ.get('REDRAGON_APPIMAGE_LAUNCHER')
    if not launcher:
        return [sys.executable]
    root = Path(launcher).parent
    libraries = ':'.join(str(root / p) for p in ('lib', 'usr/lib/x86_64-linux-gnu', 'usr/lib'))
    return [str(root / 'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'),
            '--library-path', libraries, str(root / 'usr/bin/python3'), '-P']
