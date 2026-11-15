RGB_MATRIX_EFFECT(host_direct)
RGB_MATRIX_EFFECT(saved_layout)

#ifdef RGB_MATRIX_CUSTOM_EFFECT_IMPLS

#    include "ledhost.h"

/* Frame streamed from the Mac app, scaled by the keyboard's brightness setting. */
static bool host_direct(effect_params_t* params) {
    RGB_MATRIX_USE_LIMITS(led_min, led_max);
    uint8_t v = rgb_matrix_config.hsv.v;
    for (uint8_t i = led_min; i < led_max; i++) {
        RGB_MATRIX_TEST_LED_FLAGS();
        rgb_matrix_set_color(i, scale8(ledhost_front[i][0], v), scale8(ledhost_front[i][1], v), scale8(ledhost_front[i][2], v));
    }
    return rgb_matrix_check_finished_leds(led_max);
}

/* How strongly LED i is lit by recent key presses (0..255). */
static uint8_t ledhost_fx_amount(uint8_t fx, uint8_t i, uint8_t speed, uint8_t* hue_shift) {
    uint8_t amt = 0;
    uint8_t cnt = g_last_hit_tracker.count;

    if (fx == LH_FX_FLASH) {
        for (int8_t j = cnt - 1; j >= 0; j--) {
            if (g_last_hit_tracker.index[j] == i) {
                uint16_t off = scale16by8(g_last_hit_tracker.tick[j], qadd8(speed, 1));
                amt          = off > 255 ? 0 : 255 - off;
                *hue_shift   = off;
                break;
            }
        }
        return amt;
    }

    for (uint8_t j = 0; j < cnt; j++) {
        int16_t  dx   = g_led_config.point[i].x - g_last_hit_tracker.x[j];
        int16_t  dy   = g_led_config.point[i].y - g_last_hit_tracker.y[j];
        uint8_t  dist = sqrt16(dx * dx + dy * dy);
        uint16_t tick = scale16by8(g_last_hit_tracker.tick[j], qadd8(speed, 1));
        uint16_t effect;
        switch (fx) {
            case LH_FX_GLOW:
                effect = tick + dist * 5;
                break;
            case LH_FX_RIPPLE: {
                /* bright ring front with a short tail, travelling outward and fading with age */
                int32_t d = (int32_t)tick - dist;
                int32_t a = (d >= 0 && d < 24) ? 255 - d * 10 : 0;
                if (a > 0 && tick > 150) a -= ((int32_t)tick - 150) * 2;
                effect = a > 0 ? 255 - a : 255;
                break;
            }
            case LH_FX_CROSS:
                effect = tick - dist;
                if (dist > 72) effect = 255;
                if ((dx > 8 || dx < -8) && (dy > 8 || dy < -8)) effect = 255;
                break;
            default:
                effect = 255;
        }
        if (effect > 255) effect = 255;
        uint8_t a = 255 - effect;
        if (a > amt) {
            amt        = a;
            *hue_shift = dist + (tick >> 1);
        }
    }
    return amt;
}

/* Per-key colours saved in EEPROM plus a click effect. Works over Bluetooth with no app running. */
static bool saved_layout(effect_params_t* params) {
    RGB_MATRIX_USE_LIMITS(led_min, led_max);
    uint8_t v       = rgb_matrix_config.hsv.v;
    uint8_t fx      = ledhost_saved.fx & 0x0F;
    bool    rainbow = ledhost_saved.fx & LH_FX_RAINBOW;
    uint8_t speed   = ledhost_saved.speed;

    for (uint8_t i = led_min; i < led_max; i++) {
        RGB_MATRIX_TEST_LED_FLAGS();
        uint8_t r = ledhost_saved.leds[i][0], g = ledhost_saved.leds[i][1], b = ledhost_saved.leds[i][2];
        if (fx) {
            uint8_t hs  = 0;
            uint8_t amt = ledhost_fx_amount(fx, i, speed, &hs);
            if (amt) {
                RGB c;
                if (rainbow) {
                    HSV hsv = {(uint8_t)(rgb_matrix_config.hsv.h + hs), 255, 255};
                    c       = hsv_to_rgb(hsv);
                } else {
                    c.r = ledhost_saved.fx_r;
                    c.g = ledhost_saved.fx_g;
                    c.b = ledhost_saved.fx_b;
                }
                r = blend8(r, c.r, amt);
                g = blend8(g, c.g, amt);
                b = blend8(b, c.b, amt);
            }
        }
        rgb_matrix_set_color(i, scale8(r, v), scale8(g, v), scale8(b, v));
    }
    return rgb_matrix_check_finished_leds(led_max);
}

#endif
