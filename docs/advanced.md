# Redragon Control: advanced guide

[← Back to the README](../README.md)

A native **GTK 4 / libadwaita** application and JSON CLI for Linux and GNOME,
built for the **Redragon K686WBG-RGB-MAX**. No web view or Electron runtime.

![Native application preview](screenshots/lighting.png)

## Install the Flatpak (0.2.0)

Download `Redragon-Control-0.2.0-x86_64.flatpak` from
[GitHub Releases](https://github.com/wfoyt/Redragon-Control/releases).
Redragon Control is not available on Flathub. The Flathub remote below supplies
the shared GNOME runtime only. The bundle includes
the app, evdev and tray libraries, and uses the GNOME 50 Flatpak runtime for
Python, GTK and libadwaita. Host GTK/Python packages are not needed. The bundle
works across Linux distributions on **x86_64** computers with Flatpak, udev,
uinput and a graphical desktop supporting the Background portal (including
GNOME and KDE). Other CPU architectures require a separate build. It does not
run on Windows or macOS, or add support for other Redragon keyboard models.

Install Flatpak using your distribution's Software app or package manager,
then double-click the bundle, or run these commands in its folder:

```bash
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user ./Redragon-Control-0.2.0-x86_64.flatpak
flatpak run io.github.redragon.Control
```

Flatpak downloads the shared GNOME runtime if needed; the single app bundle
does not include that large runtime and is not a complete offline installer.
The local bundle has no hosted update repository; install a newer versioned
bundle to update the app. `flatpak update` updates its shared runtime.

On first launch, connect the keyboard or receiver. If Linux has not granted
keyboard access, the app **blocks startup** and offers **Save hardware setup
script…**. Save it locally (for example in Downloads) and run the exact
`sudo bash …` command displayed in the app, in your normal desktop Terminal.
The standalone script installs device-specific udev rules and enables uinput;
it checks prerequisites and exits with a friendly explanation on failure.
Reconnect the keyboard and choose **Check again**. The app checks actual access;
an unsuccessful script cannot unlock the main application. A computer already
configured with the existing hardware setup does not need to rerun the script.

Allow background activity and automatic startup in your desktop's permission
prompt. Startup is only accepted when the desktop confirms **both** permissions.
If denied or unavailable, the setup window stays open and explains what to
allow or install. This uses the standard
[Background portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Background.html).
Redragon Control then starts automatically **after signing in**, including
after a reboot. It cannot control a user's keyboard before the login screen.
At login it stays in the tray once setup is complete; enabled services resume.
GNOME users need an AppIndicator extension for the tray menu to be visible.
Background services still run without a visible tray; opening the app from
the launcher opens Settings in the running tray's session.

The Flatpak's startup check also runs at login. If the keyboard is disconnected
or access is revoked, it displays the setup window and waits for **Check again**;
it does not start services with incomplete setup. Demo mode and read-only CLI
commands remain available for inspection and troubleshooting.

Device control requires `--device=all` to expose hidraw, input and uinput; the
host's udev permissions still apply. This follows Flatpak's
[device access model](https://docs.flatpak.org/en/latest/sandbox-permissions.html#device-access).
The app has no network permission or unrestricted home/system-bus access.
The hardware helper is bundled inside the app and exported using a file chooser;
the Flatpak cannot silently install host system files or run commands as root.

Flatpak settings live under
`~/.var/app/io.github.redragon.Control/config/redragon-control/`.
Existing native settings remain in `~/.config/redragon-control/`; export/import
profiles to transfer them. The native uninstallation preserves those settings
and the hardware rules so the Flatpak can reuse keyboard access.

### Rebuild without installing the application

Install `flatpak-builder` and the GNOME 50 SDK/runtime, then run from this source
directory (the installed `org.flatpak.Builder` build tool can also be used):

```bash
flatpak install --user flathub org.gnome.Sdk//50 org.gnome.Platform//50
flatpak-builder --user --force-clean --default-branch=stable --repo=packaging/repo packaging/build packaging/io.github.redragon.Control.json
mkdir -p dist
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo packaging/repo dist/Redragon-Control-0.2.0-x86_64.flatpak io.github.redragon.Control stable
```

Dependency recipes are pinned and vendored in `packaging/shared-modules` with
their upstream commit recorded. The bundle includes only distributable sources,
not this checkout's virtual environment, profiles or hardware test artifacts.
Use `flatpak build --runtime packaging/build redragon-control --version` to
inspect the staged app without installing it.

## First launch

Redragon Control opens a four-page setup: keyboard detection, lighting,
wheel and key remapping, then a welcome page. A single supported connected
keyboard is selected automatically; multiple keyboards require a choice.
Detection retries while you connect your keyboard.

The first page also offers **Import a profile**. A successful import restores
saved lighting preferences and key bindings, then goes directly to Welcome.
Importing saves preferences without applying them to hardware; you can apply
them from the main app. Invalid profiles leave you on the first page.

Lighting and remapping both have separate **Apply** and **Next** buttons.
Apply saves and activates the chosen settings while keeping you on the page.
Applying remapping saves wheel and additional key bindings together and starts
remapping when there are custom actions. Next continues without applying,
discarding any edits made since the last Apply. You can change these settings
later in the main app. Next on lighting keeps your current onboard effect
unless you already applied app lighting.

Setup is marked complete when you select **Open Redragon Control** on the
welcome page. Closing earlier starts setup again on the next launch. Completion
is stored separately from portable profiles, so importing a profile does not
skip setup. New installations leave background services off until requested.
Demo mode also previews the full setup without saving completion or changing
hardware. The existing **Reset app settings** command retains named profiles
and keyboard selection; it is separate from a complete removal of user data.

## Current hardware support

| Feature | Support |
| --- | --- |
| Whole-keyboard RGB color, brightness, off | Wired USB and 2.4 GHz, with firmware model verification |
| Built-in animations | 17 native effects over 2.4 GHz; five brightness/speed levels |
| Smooth breathing | Retained native effect with seven preset colors |
| Wheel, wheel press, other keys | Linux input remapping over USB or 2.4 GHz; Bluetooth depends on input access |
| Key chords, media keys, horizontal/vertical scrolling | Supported by the remapping service on GNOME Wayland and X11 |
| Profiles and agent CLI | Implemented; versioned JSON settings and structured results |
| Restore app defaults | Stops both services and clears local lighting preferences and bindings |
| Keyboard factory reset | Guided physical reset: **hold Fn + Esc for 3 seconds** |
| Bluetooth RGB / on-device remapping / USB factory reset | Protocols not verified; not implemented |

Wired and 2.4 GHz RGB were physically verified on this exact MAX keyboard:
the user confirmed steady teal in both connection modes, with the cable
disconnected for the wireless test. Both connections reported firmware model
**0x20**. The input remapping service successfully grabbed this keyboard's
real event nodes in both modes. The app checks the firmware model before
sending lighting commands.
The wireless receiver currently identifies as `3554:fa09`; wired mode should
identify as `258a:010c`. These are shared chipset IDs, so the app also checks
the HID report descriptor and firmware model before sending RGB. The receiver
must additionally report the exact K686 MAX product signature.
See [protocol provenance](protocol.md).

## Run on Fedora

The GUI requires libadwaita 1.5 or newer, GTK 4.10 or newer, Python 3.11 or newer,
PyGObject, and Cairo bindings. The remapper additionally requires python-evdev.

```bash
sudo dnf install python3-gobject python3-cairo gtk4 libadwaita python3-evdev
./run.sh gui
```

Explore without changing hardware or stored settings:

```bash
./run.sh --demo gui
```

The project's `.venv`, when present, takes precedence and can use system GTK
bindings. For another Linux distribution, install its matching GTK/libadwaita,
PyGObject, Cairo and evdev packages. Alternatively use a virtual environment
created with `python3 -m venv --system-site-packages .venv`, then install evdev
there. Building evdev from source also requires Python development headers.

### One-time hardware access

Run the supplied setup once, then reconnect the keyboard:

```bash
sudo ./scripts/setup-hardware.sh
./run.sh doctor
```

This installs device-scoped udev rules for the IDs above, grants the active
local desktop user input/hidraw access, and enables `/dev/uinput` for virtual
input. It does not add you to the broad `input` group or make devices writable
by everyone. Active desktop applications share your user permissions, including
virtual input. Run the app and CLI as your normal user.

To undo system setup, stop the services, remove
`/etc/udev/rules.d/70-redragon-control.rules` and
`/etc/modules-load.d/redragon-control.conf`, reload udev rules, and reconnect.

### GNOME launcher

```bash
./scripts/install-user.sh
```

This adds Redragon Control to GNOME and installs `~/.local/bin/redragonctl`.
Keep this source directory in place; the launcher points to `run.sh` here.

### Start in the GNOME tray at login

The installer also enables a login autostart entry in
`~/.config/autostart/io.github.redragon.Control.desktop`. It runs
`redragonctl tray`, which creates an AppIndicator. Until first-run setup is
complete, it also opens the setup window; subsequent logins stay in the tray.
GNOME's AppIndicator extension must be enabled. The indicator uses GTK3 and
AppIndicator in its own process; settings continue to use GTK4/libadwaita.
Fedora's indicator dependency is `libappindicator-gtk3` (already available on
the development machine); AyatanaAppIndicator3 is also supported.

The tray restores enabled remapping on login and remembers whether lighting control
was enabled. Its menu offers **Open settings**, independent remapping/lighting
toggles, and **Quit and stop keyboard services**. Closing the settings window
leaves the tray and mappings active. Disabled services stay disabled, including
when stopped from the CLI or the settings window. Enabled services are retried
after reconnecting the selected keyboard or a startup permission delay.

Quit stops services for this session while preserving their next-login state.
Use the menu toggles to persistently pause a service. Background preferences
are stored beside settings in `config.background.json`, separate from profiles.
To disable login autostart, remove the autostart desktop file or disable its
entry in your desktop's startup-app settings. Launch manually with
`./run.sh tray`. This runs after signing into GNOME, not before the login screen.

## First use

1. Follow the setup screen to detect your keyboard. The generic **CX 2.4G Wireless
   Receiver** is the current wireless connection. Setup lists known K686
   connections; the main app and CLI also list other HID devices for inspection.
2. For RGB, use USB-C with the mode switch set to **OFF**, or use the receiver
   with the keyboard in **2.4G** mode. Select that connection, save your
   lighting preferences, then Apply lighting.
3. For the wheel, keep the knob in volume mode. Defaults emit `KEY_VOLUMEUP`,
   `KEY_VOLUMEDOWN`, and `KEY_MUTE`. Save new bindings and start the remapper.
4. Use `observe` to identify other buttons. Fn combinations consumed internally
   by the keyboard cannot be remapped unless they emit a Linux input event.

All animations now run on the keyboard itself through the 2.4 GHz receiver.
The Effect selector contains Smooth breathing plus Redragon's Rainbow,
Flash Away, Raindrops, Rainbow Wheel, Ripple Shining, Stars Twinkle,
Shadow Disappear, Retro Snake, Neon Stream, Reaction, Sine Wave,
Retinue Scanning, Rotating Windmill, Colorful Waterfall, Blossoming, and
Rotating Storm. Reactive effects need typing to show their animation.
The former software Breathing effect has been removed and Rainbow now selects
the keyboard's native moving rainbow. No animation frames are streamed.

Static color and Off remain available over USB and 2.4 GHz. Their temporary
direct mode needs refreshes (2 Hz wired, 20 Hz wireless). Use **Use onboard
lighting** to stop the lighting service and restore the original configuration.
Closing Settings leaves the tray and enabled services active.

Choose **Smooth breathing** for a smooth fade generated by the wireless
keyboard itself. Its preset selector offers red, green, blue, yellow, magenta,
cyan, and white; brightness and speed use 25-point steps. The preview animates
with those settings (it illustrates the effect rather than synchronizing with
the keyboard's phase). The other built-in effects preserve their onboard
colors and variants. All native effects use brightness/speed steps of 25.
The keyboard preview now draws colors per key, with distinct waves, rotating
patterns, trails, drops and twinkles for each selection. Reactive previews
replay simulated key presses, identified below the keyboard. These are
illustrations: onboard color variants, direction and timing may differ, and
the preview is not synchronized with live keyboard input or firmware frames.
Static color continues to accept arbitrary RGB colors. Old software Breathing
profiles migrate to Smooth breathing with the nearest preset color.

Built-in animation writes over USB remain unverified, so they are disabled
when the wired connection is selected. Select the receiver and use 2.4G mode
for animations. There is no software animation fallback.

Built-in effects change saved onboard lighting settings. Before the first
write, the service saves the complete original configuration in
`config.native-lighting-backup.json`, checks receiver acknowledgments, and
verifies the result by reading it back. Stopping the lighting service restores
and verifies the original configuration, then removes the recovery backup.
If disconnecting or a forced shutdown interrupts recovery, the backup remains
and the next wireless lighting start restores it before applying preferences.
Keep this file until recovery succeeds. No palette, keymap, or firmware
updates are sent by these modes. Recovery was verified on the user's K686 MAX.

Remapping is applied by an unprivileged input service, not stored in firmware.
It runs after closing the GUI until stopped, you sign out, the machine restarts,
or the device disconnects. Tray mode restores enabled services on login and
retries after reconnects. Live profile changes are reloaded automatically.
The service restores original input by releasing grabs on exit. Reconnect and
restart it after an unplug when running without the tray; it does not select a
different, unlinked device automatically.
Your selection is tied to the USB port/physical input family to avoid grabbing
another keyboard. Link the keyboard's verified cable and receiver connections
with `link` to let the tray restore enabled services when you switch between
them. If both are connected, the selected connection takes priority. Links
live in `config.connections.json`; profiles do not change them. Select or
link again if you move a connection to another USB port.

## CLI for users and AI agents

Every normal command prints `{ "ok": true, "result": ... }` as JSON. Failures
print `{ "ok": false, "error": ... }` on stderr and exit 1. `observe` streams
one JSON event per line. No GUI or desktop session is needed to inspect settings.
Use `--config /absolute/path/config.json` **before** the subcommand to isolate
an agent's settings from your usual configuration.

```bash
./run.sh devices
./run.sh select 3554:fa09
./run.sh observe --timeout 15 --limit 30
./run.sh bind KEY_VOLUMEUP scroll-up
./run.sh bind KEY_VOLUMEDOWN scroll-down
./run.sh bind KEY_MUTE KEY_PLAYPAUSE
./run.sh bind KEY_F12 KEY_LEFTCTRL+KEY_LEFTALT+KEY_T
./run.sh daemon start
./run.sh status
./run.sh unbind KEY_F12
./run.sh daemon stop --kind all

# Static color and Off work through either selected connection
./run.sh select 258a:010c
# With the receiver connected, link it to the selected wired keyboard:
./run.sh link 3554:fa09
./run.sh rgb --mode static --color '#00ff88' --brightness 60 --apply
# Select the receiver while the keyboard is in 2.4G mode for native animations
./run.sh select 3554:fa09
./run.sh rgb --mode rainbow --brightness 75 --speed 50 --apply
./run.sh rgb --mode reaction --brightness 75 --speed 50 --apply
# Smooth wireless breathing (preset colors; levels 0, 25, 50, 75, 100)
./run.sh rgb --mode smooth-breathing --color '#00ffff' --brightness 75 --speed 50 --apply
./run.sh daemon stop --kind rgb

./run.sh profile save Work
./run.sh profile export /tmp/redragon-profile.json
./run.sh profile import /tmp/redragon-profile.json
./run.sh profile load Work
./run.sh reset app --yes
./run.sh reset factory
```

When two devices have the same VID:PID, select their full ID from `devices`
(for example `3554:fa09@de64c78abcfb`); an ambiguous short ID is rejected.
Profile import validates every setting and preserves your currently selected
keyboard. It saves lighting preferences but does not start stopped services.
Bindings accept Linux `KEY_*` names, `+`-joined key chords, `scroll-up`,
`scroll-down`, `scroll-left`, `scroll-right`, `disabled`, or `default`.
Wheel sources can also be `REL_WHEEL_UP`, `REL_WHEEL_DOWN`,
`REL_HWHEEL_LEFT`, and `REL_HWHEEL_RIGHT` when the hardware emits mouse-wheel
events rather than volume keys.

Settings and profiles live in `~/.config/redragon-control/` (or
`$XDG_CONFIG_HOME/redragon-control/`). Writes are locked and atomically replaced.
Service logs and process metadata live beside the selected configuration file.
No telemetry, network service, arbitrary shell command execution, or firmware
flashing is included.

## Recovery

Use **Recovery → Reset app settings** or `./run.sh reset app --yes` to stop
both background services, clear local bindings, and reset lighting preferences.
Named profiles are retained. Stopping software RGB allows the keyboard's own
lighting to resume. Stopping input remapping restores original button events.

For the keyboard's actual factory settings, stop the services and hold
**Fn + Esc for 3 seconds**, as documented in
[Redragon's official manual](https://cdn.shopify.com/s/files/1/0012/4957/4961/files/K686_user_manual.pdf?v=1723515517).
The app includes a factory-reset guidance button. Fn is handled inside the
keyboard; there is no verified USB reset command in this implementation.

If input is ever unusable, unplug and reconnect the keyboard; input grabs are
released when a device disappears. The remapper never modifies firmware.

## Validation

```bash
./run.sh --help
.venv/bin/python -m unittest discover -s tests -v
```

The automated suite exercises packet formatting, firmware-model rejection,
device identity, event routing, chord releases, high-resolution wheel handling,
service cleanup, configuration validation, profile isolation, and JSON CLI
results, all native effect IDs/parameter positions, preservation of other
settings, wireless packet framing, paired-model rejection, and explicit
connection switching. Native UI pages and bright/dim breathing frames have
been rendered and visually checked; GTK frame-clock animation was verified.
Live wired and wireless model probing, static RGB, daemon keepalive and
input-service startup have been verified. The user confirmed smooth native
cyan breathing, the native moving Rainbow, and wireless wheel-press remapping.
All 17 native animation selections passed actual receiver read-back. Native effect read-back,
byte-for-byte stop recovery, restart, and idle operation without continuous
RGB writes were verified on hardware. Event transformation edge cases,
recovery failure paths, and effect generation are covered by automated tests.
