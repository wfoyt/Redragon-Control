"""Stable JSON command line interface for users and automation."""

import argparse
import json
import sys

from . import __version__
from .config import MODES
from .errors import ControlError


def parser():
    root = argparse.ArgumentParser(prog="redragonctl", description="Manage Redragon keyboards on GNOME/Linux. Outputs JSON by default.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--config", help="Use a separate settings file")
    root.add_argument("--demo", action="store_true", help="Explore the UI without hardware or saved changes")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("gui", help="Open the native libadwaita app")
    commands.add_parser("tray", help="Run the GNOME tray indicator without opening a settings window")
    commands.add_parser("devices", help="List USB/HID device families without writing to them")
    commands.add_parser("status", help="Show settings, device capabilities and remapper status")
    commands.add_parser("doctor", help="Check dependencies and device permissions")
    select = commands.add_parser("select", help="Explicitly select a keyboard")
    select.add_argument("device_id", help="ID from devices; VID:PID accepted if unique")
    link = commands.add_parser("link", help="Link the selected keyboard to its other USB/2.4 GHz connection")
    link.add_argument("device_id")
    rgb = commands.add_parser("rgb", help="Save lighting settings; use --apply to send supported RGB")
    rgb.add_argument("--mode", choices=MODES)
    rgb.add_argument("--color", help="Hex color, e.g. '#00ff88'")
    rgb.add_argument("--brightness", type=int)
    rgb.add_argument("--speed", type=int)
    rgb.add_argument("--apply", action="store_true", help="Apply supported lighting and keep it active")
    bindings = commands.add_parser("bind", help="Remap a Linux input key or wheel direction")
    bindings.add_argument("source")
    bindings.add_argument("target", help="KEY_A, KEY_LEFTCTRL+KEY_C, scroll-up, disabled or default")
    unbind = commands.add_parser("unbind", help="Restore original behavior for one input")
    unbind.add_argument("source")
    observe = commands.add_parser("observe", help="Read events without grabbing; operate the wheel/buttons to identify them")
    observe.add_argument("--limit", type=int, default=30)
    observe.add_argument("--timeout", type=float, default=15)
    daemon = commands.add_parser("daemon", help="Start, stop or inspect the remapping/lighting services")
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
    checks = {"evdev": importlib.util.find_spec("evdev") is not None,
              "pygobject": importlib.util.find_spec("gi") is not None,
              "uinput_writable": os.access("/dev/uinput", os.W_OK),
              "selected_device_connected": selected is not None}
    nodes = (selected["event_paths"] + selected["hidraw_paths"]) if selected else []
    permissions = [{"path": p, "exists": Path(p).exists(), "readable": os.access(p, os.R_OK), "writable": os.access(p, os.W_OK)} for p in nodes]
    return {"checks": checks, "permissions": permissions, "rgb": state["capabilities"],
            "help": "See README.md for Fedora dependencies and the narrowly scoped udev rules. Run the app as your normal user."}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command in (None, "gui"):
            from .gui import run
            return run(config_path=args.config, demo=args.demo) or 0
        if args.command == "tray":
            if args.demo:
                raise ControlError("Tray mode requires real saved settings.")
            from .tray import run
            return run(config_path=args.config) or 0
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
            result = controller.set_lighting(mode=args.mode, color=args.color, brightness=args.brightness, speed=args.speed, apply=args.apply)
        elif args.command == "bind":
            result = controller.set_binding(args.source, args.target)
        elif args.command == "unbind":
            result = controller.remove_binding(args.source)
        elif args.command == "observe":
            from .remap import observe_events
            active_device = controller.status()["device"]
            if not active_device:
                raise ControlError("Connect the selected keyboard first.")
            device_id = active_device["id"]
            if args.demo:
                raise ControlError("Event observation requires a real selected keyboard.")
            if not 1 <= args.limit <= 10000 or not 0 < args.timeout <= 3600:
                raise ControlError("Use --limit 1–10000 and --timeout above 0, up to 3600 seconds.")
            for event in observe_events(device_id, args.limit, args.timeout):
                print(json.dumps(event), flush=True)
            return 0
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
                result = controller.start_daemon() if args.kind == "remap" else controller.apply_lighting() if args.kind == "rgb" else {"remap": controller.start_daemon(), "rgb": controller.apply_lighting()}
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
