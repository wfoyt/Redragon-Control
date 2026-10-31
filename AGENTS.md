# Repository instructions

## AppImage releases

Read [docs/appimage.md](docs/appimage.md), including its release checklist, before
building or publishing any release. Preserve Gear Lever update support in every
release; it must not depend on users configuring an update URL manually.

- Build with `scripts/build-appimage.sh`. Do not publish an older image from
  `dist/` after changing application source or packaging.
- Keep the embedded update information exactly:
  `gh-releases-zsync|wfoyt|Redragon-Control|latest|Redragon-Control-*-x86_64.AppImage.zsync`.
- Every release must include the generated AppImage, its matching `.AppImage.zsync`,
  and `.AppImage.sha256` as assets on the same GitHub Release. These ignored build
  outputs belong in release assets, not Git history.
- Verify embedded metadata with `--appimage-updateinformation`, verify the zsync
  header's SHA-1 and Length against the exact image, and verify the SHA-256 file.
  Rebuilding requires regenerating and uploading all three files together.
- Use versioned names `Redragon-Control-VERSION-x86_64.AppImage` and matching
  sidecar names. Increment the application version for a new release and keep
  package metadata and release tag consistent.
- The update channel follows the latest stable GitHub Release. Mark stable
  releases as latest; drafts and prereleases do not update stable users.
- Inspect the published release assets after upload. Do not claim updates are
  available until the matching assets are present on GitHub.
- Explain user behavior accurately: Gear Lever discovers the embedded source and
  offers updates. Users control update checking and installation; this is not
  guaranteed unattended installation. Older images without metadata need one
  manual update or one-time update-source configuration.
- Leave the user's installed/system copy alone when rebuilding repository assets.
