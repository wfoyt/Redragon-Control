# Advanced guide

Redragon Control now saves onboard lighting only. Live key/wheel remapping,
input observation, background reconnect/retry, the tray indicator, and login
startup have been removed. Continuous input interception can cause missed or
repeated keystrokes. The wheel and keys retain their default hardware actions.

## Run from source

The GUI requires Python 3.11+, GTK 4.12+, libadwaita 1.5+, PyGObject and Cairo.
There is no evdev or AppIndicator dependency. On Arch/Omarchy:

```bash
sudo pacman -S python-gobject python-cairo gtk4 libadwaita
./run.sh gui
```

On Fedora:

```bash
sudo dnf install python3-gobject python3-cairo gtk4 libadwaita
./run.sh gui
```

Explore without hardware access or saved changes with `./run.sh --demo gui`.
The optional `.venv` takes precedence; create it with `--system-site-packages`
to use the distribution’s GTK bindings.

### One-time hardware access

The setup window’s **Enable keyboard access** authenticates through Polkit.
Alternatively run:

```bash
sudo ./scripts/setup-hardware.sh
./run.sh doctor
```

The helper installs device-scoped HID permissions for `258a:010c` and
`3554:fa09`. It no longer grants input-event access or configures `/dev/uinput`.
It removes this app’s former uinput module-load file when rerun, without
unloading modules used by other apps. Run the app as your normal user.

`./scripts/install-user.sh` installs a desktop launcher and
`~/.local/bin/redragonctl` pointing to this checkout. It disables this app’s
legacy login entry and stops legacy workers. It never enables startup.

## First use

Setup now has three steps: detect a keyboard, choose lighting, and Welcome.
Select the **CX 2.4G Wireless Receiver** and set the keyboard to **2.4G**.
**Apply** saves lighting; **Next** discards unapplied edits. Importing a profile
goes straight to Welcome without applying anything to hardware.

Static and Smooth breathing use seven preset colors (red, green, blue, yellow,
magenta, cyan, white). Brightness and speed use 25-point steps. All 17 animations
run onboard, including reactive effects that respond to typing internally.
The UI preview simulates the effect without observing live keyboard input.
No frames or keepalives are streamed. USB-cable and Bluetooth lighting writes
remain unsupported.

Hardware is opened only for explicit lighting apply/restore transactions. Each
transaction verifies the paired K686 MAX, backs up its configuration, checks
acknowledgments and read-back, and closes the descriptor even on failure.
Unchanged hardware settings do not trigger another save. Failed writes attempt
rollback; interrupted writes recover at the next explicit apply. No keyboard
palette, keymap, reset, or firmware commands are sent. Discovery and status
only read sysfs, permissions, and local settings. Linking connections records
local identifiers; model verification happens when applying lighting.

Closing the window quits the process and leaves saved lighting on the keyboard.
A pending operation must finish before the window can close. There is no
indicator, background service, reconnect retry, or startup option. Opening a
normal non-demo launch disables the old XDG login entry, removes only this
app’s managed Omarchy post-boot hook, and stops old tray/remap/RGB workers.
Custom `--config` launches leave the normal login entry alone and stop workers
only for that configuration.

## CLI for users and AI agents

Normal commands print `{ "ok": true, "result": ... }`; errors print
`{ "ok": false, "error": ... }` to stderr and exit 1. Put `--config PATH`
before the subcommand to isolate settings.

```bash
./run.sh devices
./run.sh select 3554:fa09
./run.sh status
./run.sh doctor
./run.sh rgb --mode static --color '#00ffff' --brightness 75 --apply
./run.sh rgb --mode rainbow --brightness 75 --speed 50 --apply
./run.sh rgb --mode smooth-breathing --color '#00ffff' --brightness 75 --speed 50 --apply
./run.sh rgb --mode off --apply
./run.sh rgb --restore
./run.sh theme auto
./run.sh theme adwaita
./run.sh theme omarchy
./run.sh profile save Work
./run.sh profile export /tmp/redragon-profile.json
./run.sh profile import /tmp/redragon-profile.json
./run.sh profile load Work
./run.sh reset app --yes
./run.sh reset factory
```

Ambiguous short VID:PID selections are rejected; use the full ID from `devices`.
Lighting preferences, selection and profile operations do not open hardware.
Profile import preserves the selected keyboard. Old profile bindings are
retained for compatibility but never activated; live reload is always disabled.
Settings live under `$XDG_CONFIG_HOME/redragon-control`, normally
`~/.config/redragon-control`, with locked atomic writes.

Legacy `bind`, `unbind`, `observe`, and `daemon start/run` commands return an
explanation that the feature was removed. `daemon status` and
`daemon stop --kind all` remain for cleanup. `tray` cleans up and exits;
`tray --open-settings` opens the foreground app in the same process.
`autostart run` cleans up and exits without opening a window.
`autostart disable/status` disable old entries; `autostart enable` is rejected.

## Recovery

**Restore previous lighting** / `rgb --restore` restores and verifies the
original lighting backup. **Recovery → Reset app settings** / `reset app --yes`
stops legacy services and clears local preferences and bindings, preserving
named profiles and applied onboard lighting.

For physical factory defaults, close the app and hold **Fn + Esc for 3 seconds**
as documented in the K686 manual. The app provides guidance rather than sending
an unverified factory-reset command. If an old remapper affects typing, quit
its tray and unplug/reconnect the keyboard.

## Validation

```bash
./run.sh --help
python3 -m unittest discover -s tests -v
# On an isolated GTK display with system PyGObject installed:
REDRAGON_GUI_TESTS=1 /usr/bin/python3 -m unittest discover -s tests -v
```

Tests cover one-shot lighting and descriptor cleanup, native effect packets,
rollback and read-back, profile compatibility, read-only discovery, removal of
input/startup entry points, legacy worker identity checks, and GTK setup.
