"""Stable JSON command line interface for users and automation."""

import argparse
import json
import sys

from . import __version__
from .config import MODES
from .errors import ControlError


def parser():
    root = argparse.ArgumentParser(prog="redragonctl", description="Manage Redragon keyboards on Linux. Outputs JSON by default.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--config", help="Use a separate settings file")
    root.add_argument("--demo", action="store_true", help="Explore the UI without hardware or saved changes")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("gui", help="Open the native libadwaita app")
    tray = commands.add_parser("tray", help="Legacy launcher compatibility; tray mode has been removed")
    tray.add_argument("--open-settings", action="store_true", help="Open the foreground settings window")
    startup = commands.add_parser("autostart", help="Inspect or remove legacy desktop startup")
    startup.add_argument("action", choices=("status", "enable", "disable", "run"), default="status", nargs="?")
    commands.add_parser("devices", help="List USB/HID device families without writing to them")
    commands.add_parser("status", help="Show settings and device capabilities")
    commands.add_parser("doctor", help="Check dependencies and device permissions")
    select = commands.add_parser("select", help="Explicitly select a keyboard")
    select.add_argument("device_id", help="ID from devices; VID:PID accepted if unique")
    link = commands.add_parser("link", help="Link the selected keyboard to its other USB/2.4 GHz connection")
    link.add_argument("device_id")
    rgb = commands.add_parser("rgb", help="Save lighting settings; use --apply to send supported RGB")
    rgb.add_argument("--mode", choices=MODES)
    rgb.add_argument("--color", help="Onboard preset hex color; old custom colors are mapped to the nearest preset")
    rgb.add_argument("--brightness", type=int)
    rgb.add_argument("--speed", type=int)
    rgb.add_argument("--apply", action="store_true", help="Save onboard lighting once over 2.4 GHz, without a daemon")
    rgb.add_argument("--restore", action="store_true", help="Restore the previous onboard lighting backup")
    theme = commands.add_parser('theme', help='Read or choose the application theme')
    theme.add_argument('choice', nargs='?', choices=('auto', 'adwaita', 'omarchy'))
    bindings = commands.add_parser("bind", help="Removed: input remapping")
    bindings.add_argument("source")
    bindings.add_argument("target", help="KEY_A, KEY_LEFTCTRL+KEY_C, scroll-up, disabled or default")
    unbind = commands.add_parser("unbind", help="Removed: input remapping")
    unbind.add_argument("source")
    observe = commands.add_parser("observe", help="Removed: live input observation")
    observe.add_argument("--limit", type=int, default=30)
    observe.add_argument("--timeout", type=float, default=15)
    daemon = commands.add_parser("daemon", help="Stop or inspect legacy services; start/run have been removed")
    daemon.add_argument("action", choices=("start", "stop", "status", "run"))
    daemon.add_argument("--kind", choices=("remap", "rgb", "all"), default="remap")
    reset = commands.add_parser("reset", help="Restore app settings or show verified physical factory reset")
    reset.add_argument("scope", choices=("app", "factory"))
    reset.add_argument("--yes", action="store_true", help="Confirm restoring app defaults")
    profile = commands.add_parser("profile", help="Manage reusable profiles")
    profile.add_argument("action", choices=("list", "save", "load", "export", "import"))
    profile.add_argument("name_or_path", nargs="?")
    return root


def doctor(controller):
    import importlib.util
    import os
    from pathlib import Path

    state = controller.status()
    selected = state["device"]
    checks = {"pygobject": importlib.util.find_spec("gi") is not None,
              "selected_device_connected": selected is not None}
    nodes = selected["hidraw_paths"] if selected else []
    permissions = [{"path": p, "exists": Path(p).exists(), "readable": os.access(p, os.R_OK), "writable": os.access(p, os.W_OK)} for p in nodes]
    return {"checks": checks, "permissions": permissions, "rgb": state["capabilities"],
            "help": "See README.md for Fedora dependencies and the narrowly scoped udev rules. Run the app as your normal user."}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "autostart":
            if args.demo:
                raise ControlError("Login startup requires real saved settings.")
            from . import autostart
            if args.action == 'enable':
                raise ControlError('Automatic startup has been removed. Open the app only when changing lighting.')
            result = autostart.disable()
            if args.action == 'run':
                from .core import Controller
                Controller(args.config).retire_background()
                return 0
            print(json.dumps({'ok': True, 'result': result}, indent=2))
            return 0
        if args.command in (None, "gui"):
            if not args.demo:
                from .autostart import disable
                from .core import Controller
                if not args.config:
                    disable()
                Controller(args.config).retire_background()
            from .gui import run
            return run(config_path=args.config, demo=args.demo) or 0
        if args.command == "tray":
            if args.demo:
                raise ControlError("Tray mode requires real saved settings.")
            if not args.config:
                from .autostart import disable
                disable()
            from .tray import run
            return run(config_path=args.config, open_settings=args.open_settings) or 0
        from .core import Controller
        controller = Controller(args.config, args.demo)
        if args.command == "devices":
            result = {"devices": controller.status()["devices"]}
        elif args.command == "status":
            result = controller.status()
        elif args.command == "doctor":
            result = doctor(controller)
        elif args.command == "select":
            result = controller.select_device(args.device_id)
        elif args.command == "link":
            result = controller.link_device(args.device_id)
        elif args.command == "rgb":
            if args.restore:
                if args.apply or any(value is not None for value in (args.mode, args.color, args.brightness, args.speed)):
                    raise ControlError('Use --restore on its own, without lighting changes.')
                result = controller.restore_lighting()
            else:
                result = controller.set_lighting(mode=args.mode, color=args.color, brightness=args.brightness, speed=args.speed, apply=args.apply)
        elif args.command == 'theme':
            result = controller.set_theme(args.choice) if args.choice else controller.appearance()
        elif args.command in ('bind', 'unbind', 'observe'):
            raise ControlError('Live key/wheel remapping and input observation have been removed to avoid missed or repeated keystrokes. Only lighting changes access the keyboard.')
        elif args.command == "daemon":
            from . import runtime
            if args.action == "run":
                if args.demo or args.kind == "all":
                    raise ControlError("Run requires real hardware and one service kind.")
                runtime.run_daemon(controller.store.path, kind=args.kind)
                return 0
            elif args.action == "status":
                result = {"remap": controller.status()["daemon"], "rgb": controller.status()["lighting_daemon"]}
            elif args.action == "stop":
                result = controller.stop_daemon() if args.kind == "remap" else controller.stop_lighting() if args.kind == "rgb" else controller.stop_all()
            else:
                raise ControlError("Background services have been removed. Use rgb --apply to save lighting once.")
        elif args.command == "reset":
            if args.scope == "app" and not args.yes:
                raise ControlError("Reset stops services and clears your saved mappings/preferences. Repeat with reset app --yes.")
            result = controller.reset_app() if args.scope == "app" else controller.factory_reset()
        elif args.command == "profile":
            if args.action == "list":
                result = {"profiles": controller.list_profiles()}
            else:
                if not args.name_or_path:
                    raise ControlError("Provide a profile name or file path.")
                method = {"save": controller.save_profile, "load": controller.load_profile,
                          "export": controller.export_profile, "import": controller.import_profile}[args.action]
                result = method(args.name_or_path)
        print(json.dumps({"ok": True, "result": result}, indent=2, sort_keys=True))
        return 0
    except (ControlError, OSError, ImportError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
