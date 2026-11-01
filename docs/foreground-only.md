# Foreground lighting only (0.2.7)

- Remove live key/wheel remapping and input observation, which require input
  interception and can cause missed or repeated key presses.
- Remove the system tray indicator, background retry/reconnect and login
  startup. Desktop and AppImage launchers open the settings window directly;
  closing the last window ends the app.
- Disable legacy login entries, remove only the app-managed Omarchy hook, and
  stop old tray/remap/RGB workers before opening the real GUI or saving lighting.
- Keep lighting writes as explicit one-shot onboard transactions, always closing
  the hardware connection afterward. Idle status/preview never opens hardware.
- Keep older profiles readable; stored key bindings are inert. Remove evdev,
  AppIndicator builds, input-event permissions and uinput setup requirements.

Version 0.2.7 is built locally in `dist/` with matching zsync and SHA-256 files.
The installed/system copy is untouched. Releases include all matching assets
as described in
[the release checklist](appimage.md#updates-through-gear-lever).
