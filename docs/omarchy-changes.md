# Omarchy and onboard-lighting changes

Historical integration notes. For the current release, see the [0.2.6 release notes](releases/0.2.6.md).
Flatpak-specific behavior below describes the retired distribution, not the current app.

Changes made on October 31, 2026.

## Appearance

- Preserved the existing Adwaita appearance and added an Omarchy appearance.
- Automatic mode detects Omarchy, including the host OS inside Flatpak. Other
  distributions default to Adwaita.
- Added **Menu → Appearance** with Automatic, Adwaita and Omarchy choices.
  The CLI equivalents are `theme auto`, `theme adwaita` and `theme omarchy`.
- Omarchy uses the current desktop palette and watches theme file replacement
  for live updates. Current and older theme-directory layouts are supported.
- Added palette validation, fallback colors and system high-contrast handling.
- Stored the choice separately in `config.appearance.json`; keyboard profiles
  cannot override it, and demo mode never writes it.
- Added read-only Flatpak access to the current Omarchy theme directories.
  No desktop configuration, system theme, hook or shell plugin is changed.

## Lighting and typing traffic

- Removed the wireless direct-RGB stream and blocked the old streaming API.
  Static lighting previously sent nine reports at 20 Hz: 180 reports per second.
- All retained lighting uses one saved onboard transaction over the 2.4 GHz
  receiver: static, Off and the existing 17 animations.
- Static and Smooth breathing offer the seven native preset colors. Removed
  arbitrary host-generated colors; older static profiles migrate to the nearest
  preset. Brightness and animation speed use supported 25-point steps.
- Added **Save to keyboard**. Saving local preferences and importing profiles
  do not apply lighting; users apply changes explicitly.
- Closing the app, quitting, stopping services and signing in do not undo or
  repeatedly resend saved lighting. The tray removes old RGB background intent
  and stops legacy lighting workers.
- Wired lighting writes are disabled because a persistent K686 wired protocol
  has not been verified. Wired input remapping remains available.

## Save verification and recovery

- Retained exact-model checks, device-bound backups, fragment acknowledgments
  and full read-back before reporting a successful save.
- Serialized apply/restore operations with a configuration-specific lock.
- Read the current configuration before each change, preserving unrelated
  keyboard settings. Identical settings avoid another EEPROM save.
- Marked completed saves separately from interrupted transactions so closing a
  connection cannot accidentally restore an older configuration.
- Failed changes roll back to the immediately preceding settings. The original
  backup remains available for explicit **Restore previous lighting** or
  `rgb --restore`.
- Interrupted writes and restores retain durable recovery information and
  recover before the next explicit apply. No palette, keymap, factory-reset or
  firmware-write commands were added.

## Input and startup bugs

- Wheel-only remapping grabs only the interfaces exposing its bound controls,
  leaving a separate typing interface on the normal Linux input path.
- Binding reloads preserve each held key's action until release, fixing the
  release/suppression of typing keys and modifiers during a wheel-binding change.
- Input-overflow recovery reconstructs unmapped held keys and modifiers instead
  of suppressing them until release; mapped shortcuts are not fired spuriously.
- Interface selection is rebuilt when a new binding requires another interface.
- Flatpak setup now offers **Continue without automatic startup** when the
  Background portal is unavailable or permission is declined. Hardware access
  is still checked. This allows manual use on Omarchy/Hyprland.
- Fixed preset-selector change handling so an intermediate empty entry cannot
  replace a selected color with white.

## Validation and delivery

All 161 automated tests passed, including the 24 GTK integration checks.
The suite covers theme selection/persistence, palette loading and
replacement, native packet preservation, save/recovery lifecycle, streaming
rejection, input routing, profiles, CLI and Flatpak startup. Both appearances
were rendered and visually inspected in an isolated GTK display.

No physical K686 is exposed to this development session. New static/Off saves,
power-cycle persistence and the reported typing issue still need a physical
confirmation. The application requires successful read-back before claiming a
save succeeded. Historical native-animation hardware checks are documented in
[protocol notes](protocol.md).

The historical 0.2.3 build used Flatpak. That distribution has been retired;
use the current AppImage release instead. Export profiles from the old app and
import them into the AppImage. See [AppImage migration instructions](appimage.md#switching-from-flatpak)
and the [advanced guide](advanced.md) for current installation and build steps.
