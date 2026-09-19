#!/usr/bin/env bash
# Build "CRE Underwriting.app" (macOS, current architecture).
#
# Prerequisites (one-time):
#   brew install node python@3.12
#   /opt/homebrew/bin/python3.12 -m venv desktop/.venv
#   desktop/.venv/bin/pip install -r backend/requirements.txt -r desktop/requirements.txt
#
# Output:
#   desktop/dist/CRE Underwriting.app
#   desktop/dist/CRE-Underwriting-mac.zip   (what you hand to a colleague)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$REPO/desktop/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing desktop/.venv — see the prerequisites at the top of this script." >&2
  exit 1
fi

echo "==> Desktop shell tests"
"$VENV_PY" -m pytest "$REPO/desktop/tests" -q -p no:cacheprovider

echo "==> Building frontend"
(cd "$REPO/frontend" && npm ci --no-audit --no-fund && npm run build)

echo "==> Building app bundle"
"$VENV_PY" -m PyInstaller --noconfirm --clean \
  --distpath "$REPO/desktop/dist" \
  --workpath "$REPO/desktop/build" \
  "$REPO/desktop/cre_underwriting.spec"

APP="$REPO/desktop/dist/CRE Underwriting.app"
ZIP="$REPO/desktop/dist/CRE-Underwriting-mac.zip"

echo "==> Self-test of the built app (frozen dependencies, no window)"
"$APP/Contents/MacOS/CRE Underwriting" --self-test

echo "==> Packaging zip"
rm -f "$ZIP"
# ditto preserves the bundle's symlinks and signatures; plain zip does not.
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

# Roadmap #31: sign (and notarize) when an identity is given — see
# desktop/sign_mac.sh. Unsigned builds are unchanged.
if [[ -n "${SIGN_IDENTITY:-}" ]]; then
  APP="$APP" ZIP="$ZIP" "$REPO/desktop/sign_mac.sh"
fi

echo
echo "Built: $APP"
echo "       $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "App size: $(du -sh "$APP" | cut -f1)"
