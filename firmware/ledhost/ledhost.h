/* ledhost: per-key LED control for the Keychron K8 Pro (ANSI RGB)
 *
 * Raw HID protocol (32-byte reports, USB only). Host -> keyboard, byte 0 = 0xD0:
 *   D0 00                      hello  -> reply D0 00 ver led_count rows cols direct_active brightness
 *   D0 01 start n|0x80? rgb*n  write n (<=9) LEDs into the direct back buffer; bit 7 of n = present frame.
 *                              Enters direct mode. Direct mode exits 2.5 s after the last packet.
 *   D0 02                      leave direct mode now
 *   D0 03 start n rgb*n        write n (<=9) LEDs of the saved layout (RAM only)
 *   D0 04                      commit saved layout + fx to EEPROM -> reply D0 04 01
 *   D0 05 fx r g b speed       set click effect for the saved layout (RAM only)
 *   D0 06                      switch the keyboard to the saved-layout effect (persists)
 *   D0 07 start                read 9 LEDs of the saved layout -> reply D0 07 start 9 rgb*9
 *   D0 08                      read fx config -> reply D0 08 fx r g b speed
 * Keyboard -> host while direct mode is active:
 *   D1 row col pressed led     key event (led = 0xFF if the key has no LED)
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

#define LEDHOST_CMD 0xD0
#define LEDHOST_EVT 0xD1
#define LEDHOST_VERSION 1
#define LEDHOST_MAGIC 0x4C48 /* "LH" */
#define LEDHOST_TIMEOUT_MS 2500
#define LEDHOST_LEDS 87

enum ledhost_fx {
    LH_FX_NONE   = 0,
    LH_FX_FLASH  = 1, /* pressed key lights up and fades */
    LH_FX_GLOW   = 2, /* soft glow spreading from the key */
    LH_FX_RIPPLE = 3, /* expanding ring */
    LH_FX_CROSS  = 4, /* lines shooting along the row and column */
};
#define LH_FX_RAINBOW 0x80 /* flag: effect colour cycles through hues */

typedef struct __attribute__((packed)) {
    uint16_t magic;
    uint8_t  fx;
    uint8_t  fx_r, fx_g, fx_b;
    uint8_t  speed;
    uint8_t  reserved;
    uint8_t  leds[LEDHOST_LEDS][3];
} ledhost_saved_t;

extern uint8_t         ledhost_front[LEDHOST_LEDS][3];
extern ledhost_saved_t ledhost_saved;
