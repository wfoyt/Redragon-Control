#!/usr/bin/env bash
# Explicit one-time system setup. Run: sudo ./scripts/setup-hardware.sh
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then
    echo 'Run this hardware setup once with sudo; run the application as your normal user.' >&2
    exit 1
fi
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install -m 0644 "$task_root/data/70-redragon-control.rules" /etc/udev/rules.d/70-redragon-control.rules
printf 'uinput\n' > /etc/modules-load.d/redragon-control.conf
modprobe uinput
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=hidraw
udevadm trigger --action=change --subsystem-match=input
udevadm trigger --action=change --sysname-match=uinput
echo 'Hardware access configured. Reconnect the keyboard, then run ./run.sh doctor as your normal user.'
