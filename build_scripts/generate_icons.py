"""
HBCE — Hybrid Controls Editor
build_scripts/generate_icons.py

Regenerates all icon assets from scratch.
Run this any time the logo SVG changes.

Usage:
    python build_scripts/generate_icons.py

Output:
    assets/icons/hbce_icon_256.png
    assets/icons/hbce_icon_128.png
    assets/icons/hbce_icon_64.png
    assets/icons/hbce_icon_32.png
    assets/icons/hbce_icon_16.png
    assets/icons/hbce_icon.ico   ← used by PyInstaller for .exe icon

Requirements:
    pip install Pillow
    (cairosvg is optional — used for higher-fidelity SVG rendering if available)
"""

import math
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: Pillow not installed. Run: pip install Pillow")
    sys.exit(1)

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
os.makedirs(OUT, exist_ok=True)


def draw_hex_vortex(size: int) -> Image.Image:
    """Draw the HBCE Hex Vortex logo at any square pixel size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    R  = size * 0.82 / 2

    def hex_pts(cx, cy, r):
        return [(cx + r * math.cos(math.radians(a)),
                 cy + r * math.sin(math.radians(a)))
                for a in [270, 330, 30, 90, 150, 210]]

    outer = hex_pts(cx, cy, R)

    # Hex background
    d.polygon(outer, fill=(16, 16, 30, 255))
    for i in range(len(outer)):
        d.line([outer[i], outer[(i+1) % 6]],
               fill=(58, 58, 92, 255), width=max(1, size // 80))

    # Fan blades — alternating hot/cold
    br = R * 0.72
    blades = [
        (330, 30,  (192, 72,  40,  230), (242, 166, 35, 60)),   # top-right:    hot
        (30,  90,  (12,  68,  124, 230), (59,  139, 212, 60)),   # bottom-right: cold
        (150, 210, (192, 72,  40,  230), (242, 166, 35, 60)),    # bottom-left:  hot
        (210, 270, (12,  68,  124, 230), (59,  139, 212, 60)),   # top-left:     cold
    ]
    for a1, a2, base_col, over_col in blades:
        pts = [(cx, cy)]
        for i in range(25):
            t = i / 24
            ang = math.radians(a1 + (a2 - a1) * t)
            pts.append((cx + br * math.cos(ang), cy + br * math.sin(ang)))
        d.polygon(pts, fill=base_col)
        d.polygon(pts, fill=over_col)

    # Air fin accent lines (only at 32px+)
    if size >= 32:
        lw = max(1, size // 80)
        for y_frac, w_frac in [(-0.82, 0.72), (-0.68, 0.90)]:
            y = cy + R * y_frac
            w = R * w_frac
            d.line([(cx - w, y), (cx + w, y)], fill=(255, 255, 255, 70), width=lw)
        for y_frac, w_frac in [(0.68, 0.90), (0.82, 0.72)]:
            y = cy + R * y_frac
            w = R * w_frac
            d.line([(cx - w, y), (cx + w, y)], fill=(255, 255, 255, 70), width=lw)

    # Hub outer ring
    hub_r  = R * 0.30
    hub2_r = R * 0.19
    d.ellipse([cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r],
              fill=(16, 16, 30, 255), outline=(80, 80, 80, 255),
              width=max(1, size // 100))
    d.ellipse([cx - hub2_r, cy - hub2_r, cx + hub2_r, cy + hub2_r],
              fill=(26, 26, 46, 255))

    # Hub split: hot (top) / cold (bottom)
    d.chord([cx - hub2_r, cy - hub2_r, cx + hub2_r, cy + hub2_r],
            180, 0, fill=(232, 93, 36, 255))
    d.chord([cx - hub2_r, cy - hub2_r, cx + hub2_r, cy + hub2_r],
            0, 180, fill=(24, 95, 165, 255))

    # Corner accent dots (only at 32px+)
    if size >= 32:
        dot_r  = max(2, int(R * 0.06))
        corners = hex_pts(cx, cy, R)
        dot_colors = [
            (242, 166, 35,  255),  # top
            (232, 93,  36,  255),  # top-right
            (59,  139, 212, 255),  # bottom-right
            (24,  95,  165, 255),  # bottom
            (59,  139, 212, 255),  # bottom-left
            (232, 93,  36,  255),  # top-left
        ]
        for (px, py), col in zip(corners, dot_colors):
            d.ellipse([px - dot_r, py - dot_r, px + dot_r, py + dot_r], fill=col)

    # Hex border overlay
    lw = max(1, size // 150)
    for i in range(6):
        d.line([outer[i], outer[(i + 1) % 6]],
               fill=(255, 255, 255, 46), width=lw)

    return img


def main():
    print("HBCE Icon Generator — Hex Vortex")
    print(f"Output: {os.path.abspath(OUT)}")
    print()

    sizes  = [256, 128, 64, 32, 16]
    images = {}

    for sz in sizes:
        img  = draw_hex_vortex(sz)
        path = os.path.join(OUT, f"hbce_icon_{sz}.png")
        img.save(path, "PNG")
        images[sz] = img
        print(f"  Generated: hbce_icon_{sz}.png")

    # Build multi-resolution .ico
    img48  = images[64].resize((48, 48), Image.LANCZOS)
    ico_sizes = [(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)]
    ico_imgs  = [images[256], images[128], images[64],
                 img48, images[32], images[16]]

    ico_path = os.path.join(OUT, "hbce_icon.ico")
    ico_imgs[0].save(ico_path, format="ICO",
                     sizes=ico_sizes,
                     append_images=ico_imgs[1:])
    print(f"  Generated: hbce_icon.ico  ({len(ico_sizes)} sizes embedded)")
    print()
    print("Done. All icon assets up to date.")


if __name__ == "__main__":
    main()
