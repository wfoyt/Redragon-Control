#!/usr/bin/env bash
# SDK build environment only: no installable Flatpak app is produced.
set -euo pipefail
cd "$(dirname "$0")/.."
flatpak run --filesystem="$PWD" org.flatpak.Builder --user --disable-rofiles-fuse \
  --force-clean --build-only build/appimage-deps packaging/appimage/dependencies.json
