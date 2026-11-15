"""Draws the Keylight app icon (glowing RGB keycaps) and writes Keylight.icns.

Usage: python make_icon.py <out_dir>
"""
import colorsys
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024


def rounded_mask(size, box, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius, fill=255)
    return m


def draw_icon():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # macOS icon grid: 824px body with ~100px margin
    body = (100, 100, 924, 924)
    bg = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):  # vertical gradient
        t = y / S
        d.line([(0, y), (S, y)], fill=(int(24 + 8 * t), int(26 + 4 * t), int(38 - 10 * t), 255))
    img.paste(bg, (0, 0), rounded_mask((S, S), body, 185))

    # 4 x 3 keycaps with a diagonal rainbow
    cols, rows, gap = 4, 3, 26
    x0, y0, x1, y1 = 190, 250, 834, 774
    kw = (x1 - x0 - gap * (cols - 1)) / cols
    kh = (y1 - y0 - gap * (rows - 1)) / rows
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    caps = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shine = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd, cd, sd = ImageDraw.Draw(glow), ImageDraw.Draw(caps), ImageDraw.Draw(shine)
    for r in range(rows):
        for c in range(cols):
            h = (0.83 - (c / (cols - 1)) * 0.38 - (r / (rows - 1)) * 0.17) % 1.0
            rgb = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(h, 0.85, 1.0))
            bx = x0 + c * (kw + gap)
            by = y0 + r * (kh + gap)
            box = (bx, by, bx + kw, by + kh)
            gd.rounded_rectangle(box, 34, fill=rgb + (255,))
            cd.rounded_rectangle(box, 34, fill=tuple(int(v * 0.55 + 20) for v in rgb) + (255,))
            # lit keycap top
            cd.rounded_rectangle((bx + 12, by + 10, bx + kw - 12, by + kh - 22), 26, fill=rgb + (255,))
            sd.rounded_rectangle((bx + 12, by + 10, bx + kw - 12, by + kh * 0.45), 26, fill=(255, 255, 255, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(38))
    layer = Image.alpha_composite(Image.alpha_composite(glow, caps), shine)
    clip = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    clip.paste(layer, (0, 0), rounded_mask((S, S), body, 185))
    return Image.alpha_composite(img, clip)


def main(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.save(out_dir / "icon.png")
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Keylight.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out_dir / "Keylight.icns")], check=True)
    print("wrote", out_dir / "Keylight.icns")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
