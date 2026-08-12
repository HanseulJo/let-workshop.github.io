#!/usr/bin/env python3
"""Normalise an institution logo for the footer strip.

    python3 tools/prep-logo.py ~/Downloads/some-logo.png postech

Writes static/logos/<slug>.png: near-white knocked out to transparent, empty
margins trimmed, and scaled to a common cap height so logos of different
proportions sit on the same optical baseline in the strip.

Knocking out the white matters — a logo saved on an opaque white background
reads as a pale rectangle on the footer, which is what gives a sponsor row that
"pasted on" look. Needs Pillow, local tooling only; the site build never touches
images.
"""

import sys
from pathlib import Path

from PIL import Image

HEIGHT = 120  # 3x the ~40px the strip displays, so it stays crisp on retina
WHITE_CUTOFF = 238  # anything lighter than this in all channels becomes clear
OUT = Path(__file__).resolve().parent.parent / "static" / "logos"


def knockout_white(im: Image.Image) -> Image.Image:
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and r >= WHITE_CUTOFF and g >= WHITE_CUTOFF and b >= WHITE_CUTOFF:
                px[x, y] = (r, g, b, 0)
    return im


def main(source: str, slug: str) -> None:
    im = knockout_white(Image.open(source).convert("RGBA"))

    box = im.getbbox()  # bbox of the non-transparent pixels
    if box:
        im = im.crop(box)

    w, h = im.size
    im = im.resize((round(w * HEIGHT / h), HEIGHT), Image.LANCZOS)

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{slug}.png"
    im.save(out, "PNG", optimize=True)
    print(f"{source} -> {out.relative_to(OUT.parent.parent)}  {im.size}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
