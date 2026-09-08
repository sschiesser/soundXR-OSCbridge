#!/usr/bin/env bash
# Sign, notarise and staple the macOS app, then wrap it in a DMG.
#
# Needs, in the environment:
#   SIGN_IDENTITY   "Developer ID Application: Name (TEAMID)"
#   APPLE_ID        the Apple account email
#   APPLE_TEAM_ID   the 10-character team id
#   APPLE_PASSWORD  an app-specific password (not the account password)
# The certificate must already be in the default keychain.
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="SoundxR-OSC-Bridge"
APP="dist/${NAME}.app"
DMG="${NAME}-macos-$(uname -m).dmg"
[ -d "$APP" ] || { echo "no $APP — build first"; exit 1; }

echo "==> signing every binary inside the bundle"
# Sign inner Mach-O files first, outermost last: --deep alone is unreliable for
# PyInstaller bundles because it skips nested frameworks' own signatures.
find "$APP" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -111 \) -print0 |
  while IFS= read -r -d '' f; do
    if file "$f" | grep -q "Mach-O"; then
      codesign --force --timestamp --options runtime \
        --entitlements packaging/entitlements.plist \
        --sign "$SIGN_IDENTITY" "$f" >/dev/null 2>&1 || true
    fi
  done

echo "==> signing the bundle"
codesign --force --timestamp --options runtime \
  --entitlements packaging/entitlements.plist \
  --sign "$SIGN_IDENTITY" "$APP"
codesign --verify --strict --verbose=2 "$APP"

echo "==> building $DMG"
rm -f "$DMG"
hdiutil create -volname "$NAME" -srcfolder "$APP" -ov -format UDZO "$DMG"
codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG"

echo "==> notarising (this waits for Apple)"
xcrun notarytool submit "$DMG" \
  --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_PASSWORD" \
  --wait --timeout 30m

echo "==> stapling"
xcrun stapler staple "$DMG"
xcrun stapler staple "$APP" || true
spctl --assess --type open --context context:primary-signature -vv "$DMG" || true
echo "==> done: $DMG"
