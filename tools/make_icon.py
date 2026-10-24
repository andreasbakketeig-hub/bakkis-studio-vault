"""Draw the app icon (a vault card on a stack of snapshots) and build the macOS .icns.

    python tools/make_icon.py

Writes assets/icon/icon-1024.png and assets/icon/AppIcon.icns (needs macOS `iconutil`).
Same family as BAKKIS MUSIC SORTER's icon: dark gradient body on Apple's icon grid
(824 px rounded body on a 1024 px canvas, soft shadow), a light card tilted 9° with a
teal glow, a translucent card behind it, teal as the one accent. Here the card is a
vault door (dial and handle) and two cards behind it stand for snapshots over time.
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
GRAY = (150, 155, 163)
DARK = (28, 31, 36)


def vertical_gradient(top: tuple, bottom: tuple) -> Image.Image:
    col = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return col.resize((S, S)).convert("RGBA")


def rounded(w: int, h: int, fill: tuple) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w - 1, h - 1], int(h * 0.12), fill=fill)
    return img


def vault_card(cw: int, ch: int) -> Image.Image:
    card = rounded(cw, ch, (242, 243, 245, 255))
    d = ImageDraw.Draw(card)
    cx, cy = int(cw * 0.42), ch // 2
    r = int(ch * 0.34)

    # Dial: dark face, tick marks (teal at the quarters), teal handle with three spokes
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DARK)
    for k in range(24):
        a = 2 * math.pi * k / 24
        major = k % 6 == 0
        r1, r2 = r * (0.70 if major else 0.78), r * 0.88
        d.line([(cx + r1 * math.cos(a), cy + r1 * math.sin(a)), (cx + r2 * math.cos(a), cy + r2 * math.sin(a))],
               fill=TEAL if major else GRAY, width=int(r * (0.07 if major else 0.04)))
    for k in range(3):
        a = 2 * math.pi * k / 3 - math.pi / 2
        d.line([(cx, cy), (cx + r * 0.55 * math.cos(a), cy + r * 0.55 * math.sin(a))], fill=TEAL, width=int(r * 0.15))
    hub = int(r * 0.22)
    d.ellipse([cx - hub, cy - hub, cx + hub, cy + hub], fill=TEAL)
    d.ellipse([cx - hub // 2, cy - hub // 2, cx + hub // 2, cy + hub // 2], fill=DARK)

    # Door handle and hinges, gray like the unplayed waveform on the Sorter card
    hx = int(cw * 0.80)
    d.rounded_rectangle([hx, cy - int(ch * 0.20), hx + int(cw * 0.05), cy + int(ch * 0.20)], int(cw * 0.025), fill=GRAY)
    for hy in (int(ch * 0.22), int(ch * 0.78)):
        d.rounded_rectangle([int(cw * 0.04), hy - int(ch * 0.06), int(cw * 0.075), hy + int(ch * 0.06)],
                            int(cw * 0.015), fill=GRAY)
    return card


def draw() -> Image.Image:
    art = vertical_gradient((28, 31, 36), (9, 10, 12))
    cw, ch = int(BODY * 0.66), int(BODY * 0.46)

    # Earlier snapshots, left behind
    for angle, dx, dy, alpha in ((-8, -0.05, 0.27, 150), (-4, -0.025, 0.30, 255)):
        ghost = rounded(cw, ch, (46, 50, 56, alpha)).rotate(angle, resample=Image.BICUBIC, expand=True)
        art.alpha_composite(ghost, ((S - ghost.width) // 2 + int(S * dx), int(S * dy)))

    # The vault, tilted like the Sorter's track card
    card = vault_card(cw, ch).rotate(9, resample=Image.BICUBIC, expand=True)
    pos = ((S - card.width) // 2 + int(S * 0.06), int(S * 0.26))

    glow_mask = Image.new("L", (S, S), 0)
    glow_mask.paste(card.getchannel("A"), pos)
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow.paste(TEAL + (120,), (0, 0), glow_mask.filter(ImageFilter.GaussianBlur(S * 0.03)))
    art = Image.alpha_composite(art, glow)
    art.alpha_composite(card, pos)

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
