"""Identify and stop legacy keyboard workers. Never start input interception."""

import fcntl
import json
import os
from pathlib import Path
import signal
import time

from .errors import ControlError


def runtime_paths(config_path, kind="remap"):
    parent = Path(config_path).parent
    stem = Path(config_path).stem + "." + kind
    return parent / f"{stem}.daemon.json", parent / f"{stem}.daemon.lock", parent / f"{stem}.daemon.log"


def daemon_status(config_path, kind="remap"):
    metadata, lock_path, log = runtime_paths(config_path, kind)
    if not lock_path.exists():
        return {"running": False, "log": str(log)}
    try:
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return {"running": False, "log": str(log)}
            except BlockingIOError:
                pass
        value = json.loads(metadata.read_text())
        # Only accept the lock owner recorded for this config and this user.
        pid = int(value["pid"])
        process = Path(f"/proc/{pid}")
        argv = (process / "cmdline").read_bytes().decode().rstrip("\x00").split("\x00")
        expected = str(Path(config_path).resolve())
        signature = ["-m", "redragon", "--config", expected, "daemon", "run", "--kind", kind]
        matches = argv[1:] == signature
        if len(argv) == len(signature) + 5 and Path(argv[0]).name == 'ld-linux-x86-64.so.2':
            # Each AppImage launch has a different mount. Validate the running
            # daemon's complete launcher rather than this caller's mount path.
            root = Path(argv[0]).parents[3]
            loader = root / 'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
            libraries = ':'.join(str(root / path) for path in ('lib', 'usr/lib/x86_64-linux-gnu', 'usr/lib'))
            prefix = [str(loader), '--library-path', libraries, str(root / 'usr/bin/python3'), '-P']
            matches = argv == prefix + signature and (process / 'exe').resolve() == loader.resolve()
        if process.stat().st_uid != os.getuid() or not matches:
            return {"running": False, "log": str(log)}
        return {"running": True, "pid": pid, "ready": value.get("ready", False), "log": str(log)}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {"running": False, "log": str(log)}


def stop_daemon(config_path, kind="remap"):
    current = daemon_status(config_path, kind)
    if not current["running"]:
        return {"running": False}
    try:
        os.kill(current["pid"], signal.SIGTERM)
    except ProcessLookupError:
        return {"running": False}
    deadline = time.monotonic() + (10 if kind == 'rgb' else 4)
    while time.monotonic() < deadline:
        if not daemon_status(config_path, kind)["running"]:
            return {"running": False}
        time.sleep(0.05)
    raise ControlError(f"Remapper PID {current['pid']} did not stop; inspect its log before retrying.")


def lighting_frame(settings, elapsed):
    """Compatibility alias for the UI preview renderer; not sent to hardware."""
    from .lighting import render_frame
    return render_frame(settings, elapsed)


def start_daemon(config_path, kind="remap"):
    raise ControlError("Background keyboard services and input remapping have been removed. Use rgb --apply to save lighting once.")


def run_daemon(config_path, kind="remap"):
    return start_daemon(config_path, kind)


def _legacy_tray(process, config_path):
    """Match only this user's old Python/module launcher for this configuration."""
    if process.name == str(os.getpid()) or process.stat().st_uid != os.getuid():
        return False
    argv = (process / 'cmdline').read_bytes().decode().rstrip('\x00').split('\x00')
    if not argv:
        return False
    legacy_gui_routing = False
    if Path(argv[0]).name == 'ld-linux-x86-64.so.2':
        root = Path(argv[0]).parents[3]
        libs = ':'.join(str(root / p) for p in ('lib', 'usr/lib/x86_64-linux-gnu', 'usr/lib'))
        prefix = [str(root / 'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'),
                  '--library-path', libs, str(root / 'usr/bin/python3'), '-P']
        if argv[:5] != prefix or (process / 'exe').resolve() != Path(argv[0]).resolve():
            return False
        arguments = argv[5:]
        # A second launch of the new foreground app must activate its window,
        # not terminate it. Only old mounted entry points rewrote GUI to tray.
        entry = root / 'lib/redragon-control/redragon/appimage_entry.py'
        legacy_gui_routing = "['tray', '--open-settings']" in entry.read_text()
    elif Path(argv[0]).name.startswith('python'):
        arguments = argv[1:]
    else:
        return False
    from .config import default_path
    tails = [['--config', str(Path(config_path).resolve()), 'tray']]
    configurations = [['--config', str(Path(config_path).resolve())]]
    if Path(config_path).resolve() == default_path().resolve():
        tails.append(['tray'])
        configurations.append([])
    # Older AppImages routed their original GUI argv to the tray internally.
    if legacy_gui_routing and any(arguments == ['-m', 'redragon.appimage_entry'] + config + command
           for config in configurations for command in ([], ['gui'])):
        return True
    return any(arguments == ['-m', module] + tail + suffix
               for module in ('redragon', 'redragon.appimage_entry')
               for tail in tails for suffix in ([], ['--open-settings']))


def stop_legacy_trays(config_path):
    pending = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if _legacy_tray(process, config_path):
                os.kill(int(process.name), signal.SIGTERM)
                pending.append(process)
        except (OSError, ValueError, IndexError):
            continue
    deadline = time.monotonic() + 6
    while pending:
        remaining = []
        for process in pending:
            try:
                if _legacy_tray(process, config_path):
                    remaining.append(process)
            except (OSError, ValueError, IndexError):
                pass
        if not remaining:
            return
        if time.monotonic() >= deadline:
            raise ControlError('An older tray is still running. Quit it with “Quit and stop keyboard services”, then reopen this app.')
        pending = remaining
        time.sleep(0.05)
