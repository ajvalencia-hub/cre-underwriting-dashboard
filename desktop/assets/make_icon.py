"""Generate desktop/assets/AppIcon.icns (run once; the result is committed).

    desktop/.venv/bin/python desktop/assets/make_icon.py

Draws a simple building-and-rising-bars mark in the app's slate/sky palette
with Pillow, renders the sizes macOS expects, and packs them with iconutil.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024
SLATE_900 = (15, 23, 42)
SLATE_700 = (51, 65, 85)
SKY_500 = (14, 165, 233)
EMERALD_500 = (16, 185, 129)
WHITE = (241, 245, 249)


def draw_master() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # macOS icon grid: ~824px rounded square centred on the 1024 canvas.
    inset = 100
    d.rounded_rectangle([inset, inset, SIZE - inset, SIZE - inset], radius=185, fill=SLATE_900)

    # Building silhouette with window grid.
    bx0, by0, bx1, by1 = 250, 330, 520, 780
    d.rectangle([bx0, by0, bx1, by1], fill=SLATE_700)
    for row in range(5):
        for col in range(3):
            x = bx0 + 35 + col * 80
            y = by0 + 40 + row * 80
            d.rectangle([x, y, x + 45, y + 45], fill=WHITE)

    # Rising return bars.
    base = 780
    for i, (h, color) in enumerate([(170, SKY_500), (270, SKY_500), (390, EMERALD_500)]):
        x = 570 + i * 70
        d.rounded_rectangle([x, base - h, x + 50, base], radius=10, fill=color)

    # Ground line.
    d.rounded_rectangle([230, 790, 800, 815], radius=12, fill=WHITE)
    return img


def main() -> None:
    master = draw_master()
    iconset = Path(tempfile.mkdtemp()) / "AppIcon.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        master.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
        master.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
    out = HERE / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    master.resize((256, 256), Image.LANCZOS).save(HERE / "AppIcon-preview.png")
    shutil.rmtree(iconset.parent, ignore_errors=True)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
