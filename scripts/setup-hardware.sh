#!/usr/bin/env bash
# Standalone host setup, bundled in the AppImage. Never run the app as root.
set -Eeuo pipefail
task_step='starting hardware setup'
trap 'echo "Redragon setup could not finish while $task_step. Nothing is ready yet. Fix the problem shown above, then run this script again with sudo. The app will check access before opening." >&2' ERR
if [[ "${EUID}" -ne 0 ]]; then
    echo 'Administrator permission is needed once to let your keyboard work.' >&2
    echo 'Open Terminal in the folder containing this file and run:' >&2
    echo "sudo bash $(printf '%q' "$0")" >&2
    exit 1
fi
if [[ -e /.flatpak-info ]]; then
    echo 'Run this saved script in your normal desktop Terminal, outside Flatpak.' >&2
    exit 1
fi
for task_command in install udevadm; do
    if ! command -v "$task_command" >/dev/null 2>&1; then
        echo "Setup needs $task_command, which is missing." >&2
        echo 'Install the udev (systemd-udev on Fedora) packages using your Software app or package manager, then run this script again with sudo.' >&2
        exit 1
    fi
done
task_step='saving keyboard permissions'
install -d -m 0755 /etc/udev/rules.d
cat > /etc/udev/rules.d/70-redragon-control.rules <<'RULES'
# Only the USB IDs declared by Redragon's official K686/MAX driver.
# uaccess grants access to the active local seat; no world-writable devices.
ACTION=="add|change", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="258a", ATTRS{idProduct}=="010c", TAG+="uaccess"
ACTION=="add|change", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3554", ATTRS{idProduct}=="fa09", TAG+="uaccess"
RULES
chmod 0644 /etc/udev/rules.d/70-redragon-control.rules
# Retire only this app’s former virtual-input startup configuration.
rm -f /etc/modules-load.d/redragon-control.conf
task_step='activating keyboard permissions'
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=hidraw
udevadm settle --timeout=10
echo 'Hardware setup finished. Unplug and reconnect your keyboard or receiver.'
echo 'Open Redragon Control as your normal user and select Check again. If access is still blocked, sign out and back in.'
