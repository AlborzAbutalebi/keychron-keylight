"""Physical layout of the Keychron K8 Pro (ANSI, TKL), in LED index order.

LED indices follow g_led_config in keyboards/keychron/k8_pro/ansi/rgb/rgb.c (row-major, skipping NO_LED).
Positions are in key units (1u = one alpha key); x/y is the key's top-left corner.
"""

# (label, x, y, w, h)
_ROWS = [
    # Row 0: function row (16 LEDs)
    [("esc", 0, 1), ("F1", 2, 1), ("F2", 3, 1), ("F3", 4, 1), ("F4", 5, 1),
     ("F5", 6.5, 1), ("F6", 7.5, 1), ("F7", 8.5, 1), ("F8", 9.5, 1),
     ("F9", 11, 1), ("F10", 12, 1), ("F11", 13, 1), ("F12", 14, 1),
     ("⎙", 15.25, 1), ("◉", 16.25, 1), ("☀", 17.25, 1)],
    # Row 1: numbers (17)
    [("`", 0, 1), ("1", 1, 1), ("2", 2, 1), ("3", 3, 1), ("4", 4, 1), ("5", 5, 1), ("6", 6, 1),
     ("7", 7, 1), ("8", 8, 1), ("9", 9, 1), ("0", 10, 1), ("-", 11, 1), ("=", 12, 1),
     ("delete", 13, 2), ("ins", 15.25, 1), ("home", 16.25, 1), ("pg↑", 17.25, 1)],
    # Row 2: QWERTY (17)
    [("tab", 0, 1.5), ("Q", 1.5, 1), ("W", 2.5, 1), ("E", 3.5, 1), ("R", 4.5, 1), ("T", 5.5, 1),
     ("Y", 6.5, 1), ("U", 7.5, 1), ("I", 8.5, 1), ("O", 9.5, 1), ("P", 10.5, 1), ("[", 11.5, 1),
     ("]", 12.5, 1), ("\\", 13.5, 1.5), ("del", 15.25, 1), ("end", 16.25, 1), ("pg↓", 17.25, 1)],
    # Row 3: home row (13)
    [("caps", 0, 1.75), ("A", 1.75, 1), ("S", 2.75, 1), ("D", 3.75, 1), ("F", 4.75, 1), ("G", 5.75, 1),
     ("H", 6.75, 1), ("J", 7.75, 1), ("K", 8.75, 1), ("L", 9.75, 1), (";", 10.75, 1), ("'", 11.75, 1),
     ("return", 12.75, 2.25)],
    # Row 4: shift row (13)
    [("shift", 0, 2.25), ("Z", 2.25, 1), ("X", 3.25, 1), ("C", 4.25, 1), ("V", 5.25, 1), ("B", 6.25, 1),
     ("N", 7.25, 1), ("M", 8.25, 1), (",", 9.25, 1), (".", 10.25, 1), ("/", 11.25, 1),
     ("shift", 12.25, 2.75), ("↑", 16.25, 1)],
    # Row 5: bottom row (11)
    [("ctrl", 0, 1.25), ("opt", 1.25, 1.25), ("cmd", 2.5, 1.25), ("", 3.75, 6.25),
     ("cmd", 10, 1.25), ("opt", 11.25, 1.25), ("fn", 12.5, 1.25), ("ctrl", 13.75, 1.25),
     ("←", 15.25, 1), ("↓", 16.25, 1), ("→", 17.25, 1)],
]
_ROW_Y = [0, 1.25, 2.25, 3.25, 4.25, 5.25]

KEYS = []
for row, keys in enumerate(_ROWS):
    for label, x, w in keys:
        KEYS.append({"label": label, "x": x, "y": _ROW_Y[row], "w": w, "h": 1.0, "row": row})

WIDTH = 18.25
HEIGHT = 6.25
LED_COUNT = len(KEYS)
assert LED_COUNT == 87, LED_COUNT

# Key centres, in key units
CENTERS = [(k["x"] + k["w"] / 2, k["y"] + k["h"] / 2) for k in KEYS]
