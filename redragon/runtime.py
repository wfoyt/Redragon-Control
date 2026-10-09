"""Supervision of the unprivileged, recoverable input remapping process."""

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from .config import atomic_write, ConfigStore
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
        if process.stat().st_uid != os.getuid() or argv[1:] != signature:
            return {"running": False, "log": str(log)}
        return {"running": True, "pid": pid, "ready": value.get("ready", False), "log": str(log)}
    except (OSError, ValueError, KeyError, TypeError):
        return {"running": False, "log": str(log)}


def start_daemon(config_path, kind="remap"):
    config_path = Path(config_path).resolve()
    current = daemon_status(config_path, kind)
    if current["running"]:
        return current
    store = ConfigStore(config_path)
    config = store.read()
    if not config["device_id"]:
        raise ControlError("Select your keyboard before starting remapping.")
    # Materialize default settings so the service always has a file to watch.
    if not store.path.exists():
        store.replace(config)
    metadata, lock, log = runtime_paths(config_path, kind)
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = package_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    with log.open("a") as output:
        os.chmod(log, 0o600)
        process = subprocess.Popen(
            [sys.executable, "-m", "redragon", "--config", str(config_path), "daemon", "run", "--kind", kind],
            stdin=subprocess.DEVNULL, stdout=output, stderr=output, env=env, start_new_session=True,
        )
    deadline = time.monotonic() + (15 if kind == 'rgb' else 5)
    while time.monotonic() < deadline:
        current = daemon_status(config_path, kind)
        if current.get("ready"):
            return current
        if process.poll() is not None:
            detail = log.read_text(errors="replace")[-2000:].strip()
            raise ControlError(f"Remapper could not start. {detail}")
        time.sleep(0.05)
    stop_daemon(config_path, kind)
    raise ControlError(f"Remapper did not become ready; see {log}.")


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


def run_daemon(config_path, kind="remap"):
    from .remap import RemapDaemon

    config_path = Path(config_path).resolve()
    metadata, lock_path, log = runtime_paths(config_path, kind)
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ControlError("The remapper is already running for this configuration.") from exc
        atomic_write(metadata, {"pid": os.getpid(), "ready": False})
        try:
            def ready():
                atomic_write(metadata, {"pid": os.getpid(), "ready": True})
            if kind == "rgb":
                run_lighting(config_path, stopped, ready)
            else:
                RemapDaemon(config_path, stopped, on_ready=ready).run()
        finally:
            metadata.unlink(missing_ok=True)


def lighting_frame(settings, elapsed):
    """Compatibility alias for the UI preview renderer; not sent to hardware."""
    from .lighting import render_frame
    return render_frame(settings, elapsed)


def run_lighting(config_path, stopped, ready):
    from .devices import resolve_config_device
    from .lighting import LightingBackend
    from .effects import NATIVE_EFFECTS

    store = ConfigStore(config_path)
    backend = None
    selected = None
    announced = False
    try:
        while not stopped.is_set():
            frame_started = time.monotonic()
            config = store.read()
            if not config["device_id"]:
                raise ControlError("Lighting stopped: no keyboard selected.")
            active_device = resolve_config_device(store.path, config['device_id'])
            if selected != active_device['id']:
                if backend and hasattr(backend, "close"):
                    try:
                        backend.close()
                    except (ControlError, OSError):
                        # Recovery remains durable and can run through the
                        # explicitly linked cable/receiver that is now active.
                        pass
                backend = LightingBackend(active_device)
                backend.recover_native(store.path)
                selected = active_device['id']
            native = config['lighting']['mode'] in NATIVE_EFFECTS
            if native:
                backend.apply_native(config['lighting'], store.path)
            else:
                backend.apply(config['lighting'])
            if not announced:
                ready()
                announced = True
            interval = 0.25 if native else 0.05 if backend.capabilities().get('wireless') else 0.5
            stopped.wait(max(0, interval - (time.monotonic() - frame_started)))
    finally:
        if backend and hasattr(backend, "close"):
            backend.close()
