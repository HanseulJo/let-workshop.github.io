#!/usr/bin/env python3
"""Bake the light hero's filter chain into the picture it is applied to.

    python3 tools/bake-hero-ink.py

Reads static/hero-paper-ink.jpg and writes the two plates the light hero
actually paints — one for a wide screen, one for a phone — with contrast,
brightness and the ink floor already in them. The stylesheet then asks for no
filter at all.

Why. The floor is a per-channel linear transfer, out = slope*in + intercept,
which raises the black point without flattening the range and turns it blue on
the way up. CSS has no filter for that, so it was an SVG one: filter:
url(#ink-floor). On a phone that layer is 414x777 CSS pixels, which at a
device ratio of 3 is an 11.6MB surface, and WebKit takes SVG filter references
down a software path that needs a source, an intermediate and a result buffer
for it — re-run on every scroll and every resize. It is the most expensive
thing on the page and it is computing a fixed result from a fixed image.

The arithmetic is the same either way. CSS filter functions and this filter
both work on non-linear sRGB — the filter says so with
color-interpolation-filters="sRGB" — so the chain reproduces exactly here,
which is what makes the swap invisible.

Needs Pillow. Local tool only; the site build does not run this.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "static" / "hero-paper-ink.jpg"

# The floor, matching #ink-floor in templates/main.html.j2. Blue is lifted
# furthest, which is what keeps the densest formulas a colour rather than a
# hole; the 49 points between red and blue are the whole point of it.
FLOOR = ((0.66, 0.31), (0.67, 0.37), (0.70, 0.50))

# What each screen's chain was, in the order CSS applied it.
PLATES = {
    "hero-ink.jpg": dict(contrast=1.32, brightness=0.92),
    "hero-ink-narrow.jpg": dict(contrast=1.15, brightness=1.02),
}


def chain(contrast: float, brightness: float):
    """One 256-entry lookup per channel, for the whole chain in CSS order."""
    tables = []
    for slope, intercept in FLOOR:
        row = []
        for v in range(256):
            x = v / 255
            x = (x - 0.5) * contrast + 0.5      # contrast()
            x = x * brightness                   # brightness()
            x = slope * x + intercept            # url(#ink-floor)
            row.append(round(max(0.0, min(1.0, x)) * 255))
        tables += row
    return tables


def main():
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    try:
        from PIL import Image
    except ModuleNotFoundError:
        sys.exit("needs Pillow:  pip install pillow")

    if not MASTER.exists():
        sys.exit(f"no master at {MASTER}")
    im = Image.open(MASTER).convert("RGB")
    for name, chainspec in PLATES.items():
        out = MASTER.parent / name
        baked = im.point(chain(**chainspec))
        baked.save(out, quality=86, optimize=True, progressive=True)
        px = baked.getpixel((0, 0))
        floor = tuple(round(255 * i) for _, i in FLOOR)
        print(f"  {name:22} {out.stat().st_size / 1e3:5.0f} KB   "
              f"black maps to rgb{floor}   corner {px}")


if __name__ == "__main__":
    main()
