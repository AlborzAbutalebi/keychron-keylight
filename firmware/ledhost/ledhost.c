#include QMK_KEYBOARD_H

/* ------------------------------------------------------------------------- */
/* ledhost: per-key LED control from the Mac app. Protocol in ledhost.h.      */
/* ------------------------------------------------------------------------- */
#include <string.h>
#include "raw_hid.h"
#include "usb_main.h"
#include "ledhost.h"

_Static_assert(sizeof(ledhost_saved_t) == EECONFIG_USER_DATA_SIZE, "EECONFIG_USER_DATA_SIZE mismatch");
_Static_assert(RGB_MATRIX_LED_COUNT == LEDHOST_LEDS, "LED count mismatch");

uint8_t         ledhost_front[LEDHOST_LEDS][3];
ledhost_saved_t ledhost_saved;

static uint8_t  back[LEDHOST_LEDS][3];
static bool     direct_active = false;
static uint32_t direct_timer  = 0;
static uint8_t  prev_mode     = RGB_MATRIX_CUSTOM_saved_layout;

static void saved_defaults(void) {
    memset(&ledhost_saved, 0, sizeof(ledhost_saved));
    ledhost_saved.magic = LEDHOST_MAGIC;
    ledhost_saved.fx    = LH_FX_RIPPLE;
    ledhost_saved.fx_r  = 255;
    ledhost_saved.fx_g  = 255;
    ledhost_saved.fx_b  = 255;
    ledhost_saved.speed = 128;
    for (uint8_t i = 0; i < LEDHOST_LEDS; i++) {
        /* default: cyan -> magenta gradient left to right */
        uint8_t x                = g_led_config.point[i].x;
        ledhost_saved.leds[i][0] = x;
        ledhost_saved.leds[i][1] = 255 - x;
        ledhost_saved.leds[i][2] = 255;
    }
}

void keyboard_post_init_user(void) {
    eeconfig_read_user_datablock(&ledhost_saved);
    if (ledhost_saved.magic != LEDHOST_MAGIC) saved_defaults();
}

static void direct_enter(void) {
    if (!direct_active) {
        uint8_t m = rgb_matrix_get_mode();
        prev_mode = (m == RGB_MATRIX_CUSTOM_host_direct) ? RGB_MATRIX_CUSTOM_saved_layout : m;
        direct_active = true;
    }
    if (rgb_matrix_get_mode() != RGB_MATRIX_CUSTOM_host_direct) rgb_matrix_mode_noeeprom(RGB_MATRIX_CUSTOM_host_direct);
    direct_timer = timer_read32();
}

static void direct_exit(void) {
    if (!direct_active) return;
    direct_active = false;
    if (rgb_matrix_get_mode() == RGB_MATRIX_CUSTOM_host_direct) rgb_matrix_mode_noeeprom(prev_mode);
}

static void copy_leds(uint8_t (*dst)[3], const uint8_t *data) {
    uint8_t start = data[2];
    uint8_t n     = data[3] & 0x7F;
    if (n > 9) n = 9;
    for (uint8_t k = 0; k < n; k++) {
        uint8_t i = start + k;
        if (i >= LEDHOST_LEDS) break;
        memcpy(dst[i], &data[4 + k * 3], 3);
    }
}

bool ledhost_raw_hid(uint8_t *data, uint8_t length) {
    if (data[0] != LEDHOST_CMD || length < 32) return false;

    uint8_t reply[32] = {LEDHOST_CMD, data[1]};
    bool    send      = false;

    switch (data[1]) {
        case 0x00: /* hello */
            reply[2] = LEDHOST_VERSION;
            reply[3] = LEDHOST_LEDS;
            reply[4] = MATRIX_ROWS;
            reply[5] = MATRIX_COLS;
            reply[6] = direct_active;
            reply[7] = rgb_matrix_get_val();
            send     = true;
            break;
        case 0x01: /* direct frame chunk */
            copy_leds(back, data);
            if (data[3] & 0x80) memcpy(ledhost_front, back, sizeof(back));
            direct_enter();
            break;
        case 0x02:
            direct_exit();
            break;
        case 0x03:
            copy_leds(ledhost_saved.leds, data);
            break;
        case 0x04:
            ledhost_saved.magic = LEDHOST_MAGIC;
            eeconfig_update_user_datablock(&ledhost_saved);
            reply[2] = 1;
            send     = true;
            break;
        case 0x05:
            ledhost_saved.fx    = data[2];
            ledhost_saved.fx_r  = data[3];
            ledhost_saved.fx_g  = data[4];
            ledhost_saved.fx_b  = data[5];
            ledhost_saved.speed = data[6];
            break;
        case 0x06:
            if (direct_active) {
                prev_mode = RGB_MATRIX_CUSTOM_saved_layout;
                direct_exit();
            }
            rgb_matrix_mode(RGB_MATRIX_CUSTOM_saved_layout);
            break;
        case 0x07: {
            uint8_t start = data[2];
            reply[2]      = start;
            reply[3]      = 9;
            for (uint8_t k = 0; k < 9 && start + k < LEDHOST_LEDS; k++) memcpy(&reply[4 + k * 3], ledhost_saved.leds[start + k], 3);
            send = true;
            break;
        }
        case 0x08:
            reply[2] = ledhost_saved.fx;
            reply[3] = ledhost_saved.fx_r;
            reply[4] = ledhost_saved.fx_g;
            reply[5] = ledhost_saved.fx_b;
            reply[6] = ledhost_saved.speed;
            send     = true;
            break;
        default:
            return false;
    }
    if (send) raw_hid_send(reply, sizeof(reply));
    return true;
}

void matrix_scan_user(void) {
    if (direct_active && timer_elapsed32(direct_timer) > LEDHOST_TIMEOUT_MS) direct_exit();
}

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    /* Report key events to the app for click effects. Only while the app is streaming over an
     * active USB link: raw_hid_send blocks if nobody is reading the endpoint. */
    if (direct_active && USB_DRIVER.state == USB_ACTIVE && IS_KEYEVENT(record->event)) {
        uint8_t row = record->event.key.row, col = record->event.key.col;
        if (row < MATRIX_ROWS && col < MATRIX_COLS) {
            uint8_t evt[32] = {LEDHOST_EVT, row, col, record->event.pressed, g_led_config.matrix_co[row][col]};
            raw_hid_send(evt, sizeof(evt));
        }
    }
    return true;
}
