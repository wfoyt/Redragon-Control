#!/usr/bin/env bash
# Build standalone AppImage dependencies in the GNOME SDK. No app Flatpak needed.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${APPIMAGETOOL:?Set APPIMAGETOOL to the official appimagetool executable}"
if [[ -z "${APPIMAGE_DEPS_DIR:-}" ]]; then
  ./scripts/build-appimage-deps.sh
fi
task_deps="${APPIMAGE_DEPS_DIR:-$PWD/build/appimage-deps/files}"
task_runtime="$(flatpak info --show-location org.gnome.Platform//50)/files"
task_appdir="$PWD/build/Redragon-Control.AppDir"
# A fresh AppDir prevents removed files or old entry points leaking into a release.
rm -rf "$task_appdir"
mkdir -p "$task_appdir/usr" dist
cp -a "$task_runtime/." "$task_appdir/usr/"
# Drop architecture extensions and debug data; keep runtime libraries and licenses.
rm -rf "$task_appdir/usr/lib/debug" "$task_appdir/usr/lib/i386-linux-gnu" "$task_appdir/usr/lib/extensions"
cp -a "$task_deps/." "$task_appdir/"
rm -rf "$task_appdir/lib/redragon-control/redragon"
cp -r redragon "$task_appdir/lib/redragon-control/"
cp -r data "$task_appdir/lib/redragon-control/"
find "$task_appdir/lib/redragon-control/redragon" -type d -name __pycache__ -prune -exec rm -rf {} +
install -Dm644 scripts/setup-hardware.sh "$task_appdir/share/redragon-control/setup-hardware.sh"
install -m755 packaging/appimage/AppRun "$task_appdir/AppRun"
sed 's|@LAUNCHER@|AppRun|; s|Exec=AppRun tray|Exec=AppRun tray --open-settings|' data/io.github.redragon.Control.desktop.in > "$task_appdir/io.github.redragon.Control.desktop"
cp data/io.github.redragon.Control.svg "$task_appdir/"
rsvg-convert -w 256 -h 256 data/io.github.redragon.Control.svg -o "$task_appdir/io.github.redragon.Control.png"
ln -sf io.github.redragon.Control.png "$task_appdir/.DirIcon"
cp packaging/appimage/fonts.conf "$task_appdir/fonts.conf"
install -Dm644 packaging/io.github.redragon.Control.metainfo.xml "$task_appdir/usr/share/metainfo/io.github.redragon.Control.appdata.xml"
install -Dm644 packaging/io.github.redragon.Control.metainfo.xml "$task_appdir/share/metainfo/io.github.redragon.Control.metainfo.xml"
chmod -R a+rX "$task_appdir"
task_version="$(python3 -c 'from redragon import __version__; print(__version__)')"
task_runtime_args=()
if [[ -n "${APPIMAGE_RUNTIME_FILE:-}" ]]; then task_runtime_args=(--runtime-file "$APPIMAGE_RUNTIME_FILE"); fi
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" "${task_runtime_args[@]}" --no-appstream --comp zstd "$task_appdir" "$PWD/dist/Redragon-Control-$task_version-x86_64.AppImage"
