#!/usr/bin/env bash
# Package "CRE Underwriting.app" as a drag-to-install disk image: opening the
# DMG shows the app next to an Applications shortcut; drag one onto the other.
# Called by build_mac.sh (unsigned builds) and sign_mac.sh (signed builds, so
# the image holds the signed, stapled app).
#
#   APP=".../CRE Underwriting.app" DMG=".../CRE-Underwriting-mac.dmg" desktop/make_dmg.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${APP:-$REPO/desktop/dist/CRE Underwriting.app}"
DMG="${DMG:-$REPO/desktop/dist/CRE-Underwriting-mac.dmg}"

if [[ ! -d "$APP" ]]; then
  echo "No app at $APP — build it first (desktop/build_mac.sh)." >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
# ditto keeps the bundle's symlinks, extended attributes and signature.
ditto "$APP" "$STAGE/CRE Underwriting.app"
ln -s /Applications "$STAGE/Applications"

rm -f "$DMG"
# hdiutil is occasionally "Resource busy" on CI runners; retry a few times.
for attempt in 1 2 3; do
  if hdiutil create -volname "CRE Underwriting" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG"; then
    break
  fi
  if [[ $attempt == 3 ]]; then
    echo "hdiutil create failed three times." >&2
    exit 1
  fi
  sleep 5
done
hdiutil verify "$DMG"
echo "Disk image: $DMG ($(du -h "$DMG" | cut -f1))"
