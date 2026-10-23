"""Draw the app icon (a vault door dial over stacked snapshot cards) and build the macOS .icns.

    python tools/make_icon.py

Writes assets/icon/icon-1024.png and assets/icon/AppIcon.icns (needs macOS `iconutil`).
Follows Apple's icon grid: an 824 px rounded body on a 1024 px canvas, with a soft shadow.
Same look as BAKKIS MUSIC SORTER's icon: dark gradient body, light card, teal accent.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icon"

S = 2048  # drawn at 2x, then downscaled for smooth edges
BODY = S * 824 // 1024
OFF = (S - BODY) // 2
RADIUS = int(BODY * 0.225)
TEAL = (0, 214, 180)
CARD = (242, 243, 245)
STEEL = (150, 155, 163)


def vertical_gradient(top: tuple, bottom: tuple) -> Image.Image:
    col = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return col.resize((S, S)).convert("RGBA")


def draw() -> Image.Image:
    art = vertical_gradient((28, 31, 36), (9, 10, 12))
    d = ImageDraw.Draw(art)
    cx, cy = S // 2 - int(S * 0.04), S // 2 + int(S * 0.04)

    # Two snapshot cards peeking out behind the door: the studio over time.
    cw, ch = int(BODY * 0.70), int(BODY * 0.70)
    for i, shade in enumerate(((40, 44, 50), (58, 63, 70))):
        dx = int(S * 0.045) * (2 - i)
        box = [cx - cw // 2 + dx, cy - ch // 2 - dx, cx + cw // 2 + dx, cy + ch // 2 - dx]
        d.rounded_rectangle(box, int(cw * 0.12), fill=shade)

    # The door: a light card with a dial.
    door = [cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2]
    d.rounded_rectangle(door, int(cw * 0.12), fill=CARD)

    r_outer = int(cw * 0.34)
    r_inner = int(cw * 0.13)
    # Teal glow behind the dial
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], fill=TEAL + (150,))
    art = Image.alpha_composite(art, glow.filter(ImageFilter.GaussianBlur(S * 0.02)))
    d = ImageDraw.Draw(art)
    d.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], fill=(22, 24, 28))
    # Tick marks around the dial
    for k in range(24):
        a = 2 * math.pi * k / 24
        long = k % 6 == 0
        r1 = r_outer * (0.72 if long else 0.80)
        r2 = r_outer * 0.90
        d.line([(cx + r1 * math.cos(a), cy + r1 * math.sin(a)), (cx + r2 * math.cos(a), cy + r2 * math.sin(a))],
               fill=TEAL if long else STEEL, width=int(S * (0.012 if long else 0.007)))
    # Handle spokes and hub
    for k in range(3):
        a = 2 * math.pi * k / 3 - math.pi / 2
        d.line([(cx, cy), (cx + r_outer * 0.62 * math.cos(a), cy + r_outer * 0.62 * math.sin(a))],
               fill=TEAL, width=int(S * 0.028))
    d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], fill=TEAL)
    d.ellipse([cx - r_inner // 2, cy - r_inner // 2, cx + r_inner // 2, cy + r_inner // 2], fill=(22, 24, 28))
    # Hinges
    hx = door[0] + int(cw * 0.04)
    for hy in (cy - int(ch * 0.28), cy + int(ch * 0.28)):
        d.rounded_rectangle([hx - int(S * 0.012), hy - int(S * 0.04), hx + int(S * 0.012), hy + int(S * 0.04)],
                            int(S * 0.01), fill=STEEL)

    # Clip to the rounded body and add the shadow
    body = Image.new("L", (S, S), 0)
    ImageDraw.Draw(body).rounded_rectangle([OFF, OFF, OFF + BODY, OFF + BODY], RADIUS, fill=255)
    art.putalpha(ImageChops.multiply(art.getchannel("A"), body))
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste((0, 0, 0, 110), (0, int(S * 0.012)), body.filter(ImageFilter.GaussianBlur(S * 0.018)))
    icon = Image.alpha_composite(icon, art)
    return icon.resize((1024, 1024), Image.LANCZOS)


def build_icns(png: Image.Image, target: Path) -> bool:
    if shutil.which("iconutil") is None:
        print("iconutil not found (macOS only); skipped AppIcon.icns")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            png.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            png.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
    return True


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw()
    icon.save(OUT / "icon-1024.png", optimize=True)
    build_icns(icon, OUT / "AppIcon.icns")
    print("wrote", ", ".join(p.name for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
