# AppImage distribution

Version 0.2.7 provides `dist/Redragon-Control-0.2.7-x86_64.AppImage`.
See the [complete release notes](releases/0.2.7.md).
Make it executable and launch it normally. The first keyboard-detection page
contains **Enable keyboard access**. It authenticates through the host's Polkit
agent and runs only the bundled hardware helper as root. Cancellation and failed
setup are reported without claiming access was enabled. Reconnect the receiver
if the permission recheck still reports missing access.

The helper is staged in a private temporary host directory because root cannot
reliably read a user's FUSE mount. The helper process receives a minimal host
environment, without bundled library or Python paths. The main application and settings window run as the normal user. Flatpak startup
code, distribution recipes and local release bundles have been removed.

Version 0.2.7 now opens the foreground GTK4 settings window directly.
Closing it exits and releases the AppImage mount. Live key/wheel remapping,
AppIndicator and login startup have been removed. Opening the updated app
disables legacy startup entries and stops old workers. Installed AppImages remain unchanged until the user installs an update.

The image includes Python, GTK4, libadwaita and a GNOME 50 userspace with its own
dynamic loader. It no longer builds evdev or AppIndicator dependencies. Cairo
rendering avoids relying on host GPU drivers. Runtime fonts and licenses remain
bundled.

The host still needs Linux x86_64, a graphical session, device access through
udev, Polkit and an authentication agent. FUSE is used by normal AppImage
launching; `--appimage-extract-and-run` is an alternative. The app does not
install an app-menu launcher automatically.

## Switching from Flatpak

Export profiles from the Flatpak, quit its keyboard services, and import them
in the AppImage's first-run setup. AppImage/native preferences use
`~/.config/redragon-control`; Flatpak preferences remain in its private
`~/.var/app/io.github.redragon.Control` directory. Existing host udev rules are
shared, so working keyboard access does not need to be reinstalled.

## Building

The build no longer needs a Redragon Control Flatpak build. It prepares the app layout
with a dependency-only GNOME SDK recipe, then copies the latest app source and
helper. No evdev or AppIndicator libraries are built. The developer build environment still uses
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
For the previously published release, all 159 tests passed from the mounted
image outside the checkout, including
19 GTK integration tests. Real cross-mount daemon status/stop and read-only
K686 model/configuration checks passed on Omarchy. No new lighting or firmware
settings were written. Other distributions have not been physically tested.

## Updates through Gear Lever

Builds embed the GitHub update source for `wfoyt/Redragon-Control`, following
stable releases with the filename pattern `Redragon-Control-*-x86_64.AppImage.zsync`.
[Gear Lever recognizes this embedded metadata](https://github.com/mijorus/gearlever/blob/master/src/models/GithubUpdater.py)
and offers updates without visiting GitHub in a browser. This does not promise
unattended installation: users still control update checking and installation
inside Gear Lever. Background checking is disabled by default in Gear Lever;
users can enable it in Gear Lever's preferences.

For each release:

1. Update the application version and build with `scripts/build-appimage.sh`.
2. Verify `IMAGE --appimage-updateinformation` prints the embedded source above.
   Verify the `.zsync` header's `SHA-1` and `Length` match that exact image, and
   run `sha256sum -c Redragon-Control-VERSION-x86_64.AppImage.sha256` from `dist/`.
3. Attach the AppImage, matching `.AppImage.zsync`, and `.AppImage.sha256` to the
   same GitHub Release. Keep their generated names.
4. Publish it as a stable release and mark it as the latest release. Drafts and
   prereleases are not selected by this update channel.
5. Inspect the published release to confirm all three assets are downloadable.
   A source commit or Git tag alone does not publish AppImage updates.

The builder requires a generated `.zsync` sidecar and fails if it is missing.
Use an appimagetool distribution with bundled `zsyncmake`, or install `zsyncmake`
on the build machine. Always upload the sidecar generated alongside that exact
AppImage; rebuilding changes its hash.

Existing installations without embedded update information can configure
[Gear Lever's GitHub update source](https://gearlever.mijorus.it/docs/github-updates/)
once: repository `wfoyt/Redragon-Control`, release filename
`Redragon-Control-*-x86_64.AppImage`, and prereleases disabled. Alternatively,
install a new build containing the metadata once. Close Redragon Control before replacing it, then relaunch after updating. For
an older tray-based release, use **Quit and stop keyboard services** before
replacing it. Updated source launches disable the old login startup path.
