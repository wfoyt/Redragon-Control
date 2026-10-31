# Bug audit: 0.2.5

Tested on Omarchy on October 31, 2026. The updated executable is
`dist/Redragon-Control-0.2.5-x86_64.AppImage`.

## Fixed

- A malformed appearance JSON file previously raised an exception while the
  window's theme manager was being created. The app now logs the problem and
  uses Automatic without destroying the file; selecting a theme repairs it.
- Closing Settings during a background save or hardware-access operation could
  terminate its worker thread mid-operation. Closing is now deferred by a
  visible message until the operation finishes, and theme monitors remain alive.
- Daemon status/stop checks compared the running service against the caller's
  AppImage mount. Different launches use different mounts. Checks now validate
  the running daemon's full command, executable, configuration and user, allowing
  another AppImage launch to recognize and stop that service.
- Explicit `gui` launches previously bypassed the tray that keeps the AppImage
  mount alive. Both default and explicit real GUI launches now use the tray;
  demo mode and CLI commands retain their direct behavior.
- Demo lighting updates returned the pre-validation values rather than the
  normalized preset and brightness actually stored. Results now match saved state.

## Flatpak retirement

Removed the app's Flatpak manifest, entry point, startup permission gate, obsolete
startup tests and local Flatpak release bundles. The installed 0.2.3 Flatpak
was also uninstalled without deleting its user data. Existing profiles and host
permissions are preserved. Migration instructions remain available.

The AppImage no longer consumes a built Redragon Flatpak. Its separate
`packaging/appimage/dependencies.json` builds only pinned third-party libraries.
The developer build environment obtains the GNOME SDK through Flatpak, but no
installable Redragon Flatpak is produced and users need no Flatpak installation.
Each build starts with a clean AppDir to prevent retired files leaking into it.

## Validation

- All 159 tests passed from the final mounted AppImage outside the checkout,
  including all 19 GTK integration tests.
- Added regression checks for corrupted appearance preferences, closing during
  an operation, cross-mount daemon recognition, AppImage GUI/CLI routing and
  normalized demo results. Existing input, recovery and profile tests passed.
- Started an idle remapper with empty bindings inside the older 0.2.4 image,
  kept its mount alive, and used 0.2.5 in a different mount to identify and stop
  it. Both checks passed with temporary settings, no input grabs and no RGB writes.
- The final AppImage identified the connected K686 MAX (model 0x20), read all ten
  onboard configuration fragments, and validated them without changing settings.
- Shell syntax and whitespace checks passed. A SHA-256 sidecar accompanies the image.

These checks do not establish behavior on every Linux distribution. No new
lighting configuration or firmware was written during this audit.
