#!/bin/bash
# Builds dist/Keylight.app (and dist/Keylight-macOS.zip) with PyInstaller.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${VERSION:-1.0.0}"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt pyinstaller

.venv/bin/python packaging/make_icon.py build/icon

.venv/bin/pyinstaller --noconfirm --clean --windowed \
  --name Keylight \
  --icon "$PWD/build/icon/Keylight.icns" \
  --osx-bundle-identifier io.github.alborzabutalebi.keylight \
  --add-data "$PWD/app/static:static" \
  --paths "$PWD/app" \
  --distpath dist --workpath build/pyinstaller --specpath build \
  app/mac_main.py

PLIST=dist/Keylight.app/Contents/Info.plist
plist_set() {  # key value
  /usr/libexec/PlistBuddy -c "Set :$1 $2" "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :$1 string $2" "$PLIST"
}
plist_set CFBundleShortVersionString "$VERSION"
plist_set CFBundleVersion "$VERSION"
plist_set NSHumanReadableCopyright "GPL-2.0-or-later"
plist_set LSMinimumSystemVersion "12.0"
codesign --force --deep --sign - dist/Keylight.app   # ad-hoc signature (not notarized)

(cd dist && rm -f Keylight-macOS.zip && ditto -c -k --keepParent Keylight.app Keylight-macOS.zip)
echo "Built dist/Keylight.app and dist/Keylight-macOS.zip"
