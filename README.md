# Redragon Control

Make your keyboard feel like yours. Customize lighting, give the wheel new actions,
and save your favorite setups in a Linux desktop app built for the
**Redragon K686WBG-RGB-MAX**.

[Download from GitHub Releases](https://github.com/wfoyt/Redragon-Control/releases)
· [Installation](#run-the-appimage)
· [Getting started](#getting-started)
· [Advanced guide](docs/advanced.md)

![Redragon Control in Adwaita with a keyboard preview, onboard color presets, and Save to keyboard](docs/screenshots/lighting.png)

![Redragon Control following the current Omarchy desktop palette](docs/screenshots/lighting-omarchy.png)

*App screenshots show demo mode, so you can explore the interface without changing a keyboard.*

See the [Omarchy and onboard-lighting change report](docs/omarchy-changes.md)
for the complete behavior changes and validation limits.

## What you can do

- **Save lighting on your keyboard.** Pick one of seven static colors, adjust
  brightness, or turn the lights off, without background lighting traffic.
- **Enjoy built-in animations.** Use 17 effects over the 2.4 GHz receiver, including
  Rainbow, Smooth breathing, Raindrops, and reactive effects that respond to typing.
- **Customize the wheel and keys.** Assign media controls, scrolling, keys, or keyboard
  shortcuts to the wheel, wheel press, and other keys.
- **Save your setups.** Create named profiles and import or export your lighting
  preferences and key bindings.
- **Match your desktop.** Automatically use the current Omarchy palette on
  Omarchy and Adwaita elsewhere, or choose either in **Menu → Appearance**.
- **Keep your bindings active.** Run the remapper in the background and resume
  it after signing in. Lighting stays saved even when the app is closed.
- **Find your way back.** Restore onboard lighting, reset app settings, or follow
  the keyboard factory-reset guidance.

## Run the AppImage

Download `Redragon-Control-0.2.6-x86_64.AppImage`, make it executable, and open it:

```bash
chmod +x Redragon-Control-0.2.6-x86_64.AppImage
./Redragon-Control-0.2.6-x86_64.AppImage
```

On the first setup page, select **Enable keyboard access** and authenticate in
your desktop's administrator prompt. The bundled helper installs device-specific
udev rules and enables uinput; the app stays unprivileged. Reconnect the receiver
if prompted. This requires Polkit and a working desktop authentication agent.
No separate script download or terminal setup command is needed.

The x86_64 image bundles Python, GTK, libadwaita, evdev and the tray libraries.
Normal launching keeps the tray available when Settings closes. Saved lighting
works with the app closed; remapping requires the app. Keep the image in a stable
location. On the first normal launch, the app enables automatic startup after
signing in on GNOME, KDE Plasma, and Omarchy. Turn it off with **Launch at login**
in the tray menu, or `./Redragon-Control-0.2.6-x86_64.AppImage autostart disable`.
If FUSE is unavailable, launch with `--appimage-extract-and-run`.

When moving from Flatpak, export your profiles first and import them in the
AppImage. Native/AppImage settings use `~/.config/redragon-control`; Flatpak
settings stay under `~/.var/app/io.github.redragon.Control/`. Quit the previous
app's keyboard services before switching distributions of the app.

AppImage builds support updates through Gear Lever when the image and matching
`.zsync` file are attached to each stable GitHub Release. See the
[Gear Lever update instructions](docs/appimage.md#updates-through-gear-lever).

See [AppImage build and validation notes](docs/appimage.md) and the
[0.2.5 bug audit](docs/bug-audit-0.2.5.md).

## Getting started

1. **Connect your keyboard.** Use the USB cable, or plug in the receiver and switch
   the keyboard to **2.4G**. For wired use, set the keyboard’s mode switch to **OFF**.
2. **Allow keyboard access.** Choose **Enable keyboard access** on the first
   setup page and authenticate in your desktop's administrator prompt. Reconnect
   the keyboard or receiver if access is still blocked.
3. **Keep the app running for remapping.** The tray keeps bindings active when
   Settings closes. Saved lighting works even after quitting the app.
4. **Follow the setup screens.** Select your keyboard, choose lighting and wheel
   actions, then open Redragon Control. You can also import an existing profile.
   Use **Apply** to activate changes during setup; **Next** continues without
   applying unsaved edits.

![First-run setup detecting a Redragon K686 MAX keyboard](docs/screenshots/setup.png)

In the main window, use **Lighting** to choose an effect and select **Save to keyboard**.
Use the **2.4 GHz receiver** to save lighting; USB lighting writes are disabled
because a persistent wired protocol has not been verified for this keyboard.
Under **Buttons & wheel**, save your wheel actions and select **Start remapper**.
Keep the knob in volume mode when remapping its volume controls.
Use the app menu to save, load, import, or export profiles.

![Buttons and wheel screen with controls for wheel up, wheel down, wheel press, and additional key bindings](docs/screenshots/buttons-and-wheel.png)

Closing Settings leaves the remapper running. Use the tray menu to pause it,
or choose **Quit and stop keyboard services** to stop it for the current session.
Lighting remains saved on the keyboard. On GNOME, an AppIndicator extension is
needed to show the tray icon; the remapper can still run without it.

## Supported keyboards and connections

This app supports the **Redragon K686WBG-RGB-MAX**. Other Redragon models are not
currently supported.

| Feature | USB cable | 2.4 GHz receiver | Bluetooth |
| --- | --- | --- | --- |
| Save static preset, brightness, and lights off | Not supported | Yes | Not supported |
| Built-in lighting animations | Not supported | Yes — 17 effects | Not supported |
| Wheel and key remapping | Yes | Yes | Depends on Linux input access |

Key bindings work while the remapper is running on your computer; they are not
saved to the keyboard. Some **Fn** combinations are handled by the keyboard
itself and cannot be remapped. The lighting preview illustrates effects; actual
keyboard colors and timing may differ.

Static and Smooth breathing offer red, green, blue, yellow, magenta, cyan and
white. Brightness and animation speed use five levels. Old custom static colors
migrate to the nearest preset. Modes that require continuous host streaming have
been removed. Applied lighting is backed up and verified by reading it back;
**Restore previous lighting** explicitly restores that backup.

## Need help?

- **Keyboard not detected?** Check the connection and mode switch, reconnect it,
  and retry detection. If access is missing, follow the hardware setup prompt.
- **Animations unavailable?** Select the receiver and use **2.4G** mode.
  Wired USB supports static color and lights off.
- **Want the keyboard’s previous lighting?** Choose **Restore previous lighting**
  with the receiver selected.
- **Want to reset your changes?** Open **Recovery → Reset app settings**.
  Saved named profiles are kept. Export a profile first if you want a backup.
- **Need a keyboard factory reset?** Stop the app’s services, then hold
  **Fn + Esc for 3 seconds**. The Recovery page also provides guidance.

For source installation, command-line controls, AppImage builds, troubleshooting,
and development details, see the [advanced guide](docs/advanced.md).
Hardware protocol details are in [protocol notes](docs/protocol.md).

Independent software, not affiliated with Redragon.
