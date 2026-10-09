"""Flatpak entry point; exec separates the GTK4 preflight from the GTK3 tray."""

import os
import sys

from .flatpak_support import ensure_ready


def main():
    from .cli import parser
    args = parser().parse_args()
    desktop = args.command in (None, "gui", "tray")
    if desktop and not args.demo:
        try:
            if not ensure_ready():
                return 1
        except Exception:
            print("Redragon Control could not complete startup checks. Run 'flatpak update' "
                  "in Terminal to repair or update its runtime, then try again.", file=sys.stderr)
            return 1
        if args.command != "tray":
            # Repeated launches ask the existing tray to open settings. Its
            # children share its Flatpak process namespace and daemon locks.
            arguments = ["--config", args.config] if args.config else []
            os.execv(sys.executable, [sys.executable, "-m", "redragon",
                                     *arguments, "tray", "--open-settings"])
    os.execv(sys.executable, [sys.executable, "-m", "redragon", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
