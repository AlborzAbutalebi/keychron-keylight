#!/bin/bash
# Flash a Keychron K8 Pro (ANSI RGB) over USB.
#   firmware/flash.sh                    flash dist/k8_pro_ansi_rgb_ledhost.bin
#   firmware/flash.sh path/to/file.bin   flash a specific file
#   firmware/flash.sh --stock            restore Keychron's original firmware (downloaded from Keychron's GitHub)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
STOCK_URL="https://raw.githubusercontent.com/Keychron/qmk_firmware/618127a725a1773e85f13455602cf6f72ab4de17/keyboards/keychron/k8_pro/firmware/keychron_k8_pro_ansi_rgb_via.bin"

case "${1:-}" in
  --stock)
    FW="$REPO/dist/k8_pro_ansi_rgb_STOCK.bin"
    if [[ ! -f "$FW" ]]; then
      mkdir -p "$REPO/dist"
      echo "Downloading Keychron stock firmware..."
      curl -fsSL "$STOCK_URL" -o "$FW"
    fi ;;
  "") FW="$REPO/dist/k8_pro_ansi_rgb_ledhost.bin" ;;
  *)  FW="$1" ;;
esac
[[ -f "$FW" ]] || { echo "Firmware not found: $FW"; echo "Download it from the GitHub release or run firmware/build.sh"; exit 1; }
command -v dfu-util >/dev/null || { echo "dfu-util missing: brew install dfu-util"; exit 1; }

cat <<MSG
Flashing: $FW

Put the keyboard in bootloader mode:
  1. Plug the K8 Pro into the Mac with the USB cable.
  2. Slide the mode switch on the back to OFF.
  3. Hold down Esc (or the reset button under the space bar).
  4. While holding it, slide the switch to CABLE. The backlight stays off.
  5. Let go of Esc.

Waiting for the bootloader (Ctrl-C to cancel)...
MSG
until dfu-util -l 2>/dev/null | grep -qi "0483:df11"; do sleep 0.5; done
echo "Bootloader found, flashing..."
# STM32 often reports an error after ':leave' even though the flash succeeded.
dfu-util -a 0 -d 0483:df11 -s 0x08000000:leave -D "$FW" || echo "(dfu-util reported an error on exit; if the keyboard restarts and types, it worked)"
echo "Done. Unplug and replug the keyboard if it doesn't restart by itself."
