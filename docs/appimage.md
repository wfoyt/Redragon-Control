# AppImage distribution

Version 0.2.5 provides `dist/Redragon-Control-0.2.5-x86_64.AppImage`.
Make it executable and launch it normally. The first keyboard-detection page
contains **Enable keyboard access**. It authenticates through the host's Polkit
agent and runs only the bundled hardware helper as root. Cancellation and failed
setup are reported without claiming access was enabled. Reconnect the receiver
if the permission recheck still reports missing access.

The helper is staged in a private temporary host directory because root cannot
reliably read a user's FUSE mount. The helper process receives a minimal host
environment, without bundled library or Python paths. The main application,
input remapper and settings window run as the normal user. Flatpak startup
code, distribution recipes and local release bundles have been removed.

Normal AppImage startup launches the tray and opens Settings. This keeps the
AppImage mount alive for background remapping after Settings closes. The
bundled Python launcher is also used for daemon and settings child processes;
daemon ownership checks validate its complete loader command and executable.
The image includes Python, GTK 3/4, libadwaita, evdev, AppIndicator libraries and
a GNOME 50 userspace, including its own dynamic loader. Cairo rendering avoids
relying on the host's GPU drivers. The full runtime makes this initial image
roughly 343 MB. Runtime libraries, fonts and license files remain bundled.

The host still needs Linux x86_64, a graphical session, device access through
udev, uinput, Polkit and an authentication agent. FUSE is used by normal AppImage
launching; `--appimage-extract-and-run` is an alternative. The first normal launch enables login autostart for GNOME, KDE Plasma, and
Omarchy. Disable it with **Launch at login** in the tray menu or the image's
`autostart disable` command. The app does not install an app-menu launcher automatically.

## Switching from Flatpak

Export profiles from the Flatpak, quit its keyboard services, and import them
in the AppImage's first-run setup. AppImage/native preferences use
`~/.config/redragon-control`; Flatpak preferences remain in its private
`~/.var/app/io.github.redragon.Control` directory. Existing host udev rules are
shared, so working keyboard access does not need to be reinstalled.

## Building

The build no longer needs a Redragon Control Flatpak build. It builds evdev
and AppIndicator libraries with a dependency-only GNOME SDK recipe, then copies
the latest app source and helper. The developer build environment still uses
Flatpak to obtain and isolate the GNOME SDK; AppImage users do not need Flatpak.

Install the build environment once:

```bash
flatpak install --user flathub org.flatpak.Builder org.gnome.Sdk//50 org.gnome.Platform//50
```

Install `rsvg-convert` and
obtain official [appimagetool](https://github.com/AppImage/appimagetool/releases)
and [type-2 runtime](https://github.com/AppImage/type2-runtime/releases) binaries.

```bash
APPIMAGETOOL=/path/to/appimagetool-x86_64.AppImage \
APPIMAGE_RUNTIME_FILE=/path/to/runtime-x86_64 \
./scripts/build-appimage.sh
```

The builder uses the installed `org.gnome.Platform//50` runtime and writes an
AppDir under `build/` and an executable image under `dist/`. The official tools
can be extracted/run without FUSE during packaging. See the
[AppImage packaging guide](https://docs.appimage.org/packaging-guide/manual.html).

## Validation

See [the 0.2.5 bug audit](bug-audit-0.2.5.md) for fixes and test evidence.
All 159 tests passed from the mounted image outside the checkout, including
19 GTK integration tests. Real cross-mount daemon status/stop and read-only
K686 model/configuration checks passed on Omarchy. No new lighting or firmware
settings were written. Other distributions have not been physically tested.
