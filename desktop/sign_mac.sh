#!/usr/bin/env bash
# Sign (and optionally notarize) "CRE Underwriting.app" and its DMG — roadmap #31.
#
#   SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
#   NOTARY_PROFILE=cre-notary ./desktop/sign_mac.sh
#
# SIGN_IDENTITY  a Developer ID Application identity in your keychain
#                (`security find-identity -v -p codesigning` lists them), or
#                "-" for a local ad-hoc signature that tests the hardened
#                runtime without an Apple account (not distributable).
# NOTARY_PROFILE optional: a notarytool keychain profile, created once with
#                `xcrun notarytool store-credentials cre-notary --apple-id …
#                --team-id … --password <app-specific password>`. When set,
#                the app is submitted to Apple, waited on, and stapled.
#
# Signs every nested binary first, then the bundle (Apple advises against
# --deep), with the hardened runtime and a secure timestamp, verifies the
# result, runs the frozen self-test again, and re-zips. Then builds the DMG
# from the signed (and, with NOTARY_PROFILE, stapled) app, signs the DMG, and
# notarizes + staples it too.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="${APP:-$REPO/desktop/dist/CRE Underwriting.app}"
ZIP="${ZIP:-$REPO/desktop/dist/CRE-Underwriting-mac.zip}"
DMG="${DMG:-$REPO/desktop/dist/CRE-Underwriting-mac.dmg}"
IDENTITY="${SIGN_IDENTITY:?Set SIGN_IDENTITY (a Developer ID Application identity, or - for ad-hoc)}"

if [[ ! -d "$APP" ]]; then
  echo "No app at $APP — build it first (desktop/build_mac.sh)." >&2
  exit 1
fi

if [[ "$IDENTITY" == "-" ]]; then
  ENTITLEMENTS="$REPO/desktop/entitlements-adhoc.plist"
  TIMESTAMP=(--timestamp=none)
  echo "==> Ad-hoc signing (local test only — not distributable)"
else
  ENTITLEMENTS="$REPO/desktop/entitlements.plist"
  TIMESTAMP=(--timestamp)
  echo "==> Signing with: $IDENTITY"
fi
SIGN=(codesign --force --options runtime "${TIMESTAMP[@]}" --entitlements "$ENTITLEMENTS" --sign "$IDENTITY")

# Inside out: libraries and executables first, deepest paths first.
count=0
while IFS= read -r -d '' file; do
  if file -b "$file" | grep -q "Mach-O"; then
    "${SIGN[@]}" "$file" 2>/dev/null
    count=$((count + 1))
  fi
done < <(find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) -print0 | sort -rz)
echo "    signed $count nested binaries"
"${SIGN[@]}" "$APP"

echo "==> Verifying the signature"
codesign --verify --strict --deep --verbose=1 "$APP"
codesign --display --verbose=2 "$APP" 2>&1 | grep -E "Authority|TeamIdentifier|flags|Signature=" || true

echo "==> Self-test of the signed app"
"$APP/Contents/MacOS/CRE Underwriting" --self-test

rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

if [[ -n "${NOTARY_PROFILE:-}" && "$IDENTITY" != "-" ]]; then
  echo "==> Notarizing (this waits for Apple, usually a few minutes)"
  xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
  spctl --assess --type execute --verbose "$APP"
  # Re-zip so the download carries the stapled ticket.
  rm -f "$ZIP"
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
elif [[ "$IDENTITY" != "-" ]]; then
  echo "(NOTARY_PROFILE not set — signed but not notarized; Gatekeeper will still warn on other Macs.)"
fi

echo "==> Disk image"
APP="$APP" DMG="$DMG" bash "$REPO/desktop/make_dmg.sh"
# A DMG takes a plain signature (no hardened runtime / entitlements).
codesign --force "${TIMESTAMP[@]}" --sign "$IDENTITY" "$DMG"
codesign --verify --verbose=1 "$DMG"
if [[ -n "${NOTARY_PROFILE:-}" && "$IDENTITY" != "-" ]]; then
  echo "==> Notarizing the disk image"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
fi

echo
echo "Signed: $APP"
echo "        $DMG ($(du -h "$DMG" | cut -f1))"
echo "        $ZIP ($(du -h "$ZIP" | cut -f1))"
