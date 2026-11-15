#!/bin/bash
# Builds the ledhost firmware for the Keychron K8 Pro (ANSI RGB) -> dist/k8_pro_ansi_rgb_ledhost.bin
#
# Fetches Keychron's QMK fork at a pinned commit, applies k8_pro.patch, drops in the ledhost keymap and
# compiles. Needs: git, python3, and the ARM toolchain (brew install osx-cross/arm/arm-gcc-bin@13).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
QMK="${QMK_DIR:-$HERE/qmk_firmware}"
QMK_COMMIT=618127a725a1773e85f13455602cf6f72ab4de17   # Keychron/qmk_firmware, branch bluetooth_playground
KEYMAP_DIR="$QMK/keyboards/keychron/k8_pro/ansi/rgb/keymaps/ledhost"

for p in /opt/homebrew/opt/arm-gcc-bin@13/bin /usr/local/opt/arm-gcc-bin@13/bin; do
  [[ -d "$p" ]] && export PATH="$p:$PATH"
done
command -v arm-none-eabi-gcc >/dev/null || {
  echo "ARM toolchain missing. Install it with:"
  echo "  brew tap osx-cross/arm && brew install osx-cross/arm/arm-gcc-bin@13"
  exit 1
}

if [[ ! -d "$QMK/.git" ]]; then
  echo "Fetching Keychron QMK @ ${QMK_COMMIT:0:10}..."
  git init -q "$QMK"
  git -C "$QMK" remote add origin https://github.com/Keychron/qmk_firmware.git
  git -C "$QMK" fetch -q --depth 1 origin "$QMK_COMMIT"
  git -C "$QMK" checkout -q FETCH_HEAD
fi
git -C "$QMK" submodule update --init --depth 1 lib/chibios lib/chibios-contrib lib/printf lib/lufa lib/vusb

# Apply the board hook (idempotent)
if git -C "$QMK" apply --check "$HERE/k8_pro.patch" 2>/dev/null; then
  git -C "$QMK" apply "$HERE/k8_pro.patch"
elif ! git -C "$QMK" apply -R --check "$HERE/k8_pro.patch" 2>/dev/null; then
  echo "k8_pro.patch doesn't apply to $QMK"; exit 1
fi
rm -rf "$KEYMAP_DIR" && cp -R "$HERE/ledhost" "$KEYMAP_DIR"

# QMK's build calls its Python CLI
if [[ ! -x "$HERE/.venv/bin/qmk" ]]; then
  python3 -m venv "$HERE/.venv"
  "$HERE/.venv/bin/pip" install -q qmk appdirs argcomplete colorama dotty-dict hid hjson "jsonschema>=4" "milc>=1.4.2" pygments pyserial pyusb pillow
fi
export PATH="$HERE/.venv/bin:$PATH"

make -C "$QMK" SKIP_GIT=yes keychron/k8_pro/ansi/rgb:ledhost
mkdir -p "$REPO/dist"
cp "$QMK/keychron_k8_pro_ansi_rgb_ledhost.bin" "$REPO/dist/k8_pro_ansi_rgb_ledhost.bin"
echo "Built dist/k8_pro_ansi_rgb_ledhost.bin"
