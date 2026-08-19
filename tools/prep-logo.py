#!/usr/bin/env python3
"""Normalise an institution logo, in the two sizes the page shows it at.

    python3 tools/prep-logo.py ~/Downloads/some-logo.png postech

Writes static/logos/<slug>.webp and <slug>-sm.webp: near-white knocked out to
transparent, empty margins trimmed, and scaled to a common cap height so logos
of different proportions sit on the same optical baseline beside each other.

Two sizes because the page shows them at two. The hosts section at the foot
draws them at 44px, so it wants 132; the hero draws them at 22 beside the
buttons, and 132 there would be six times what is on screen — and that one is
above the fold, where a logo is decoration and the bytes are not.

WebP rather than PNG. These are flat wordmarks with a soft gradient in one of
them, and PNG spends most of its size on the gradient: the pair comes to 99KB
as PNG and 59KB as WebP at the same dimensions, with nothing to see between
them at 44px.

Knocking out the white matters — a logo saved on an opaque white background
reads as a pale rectangle, which is what gives a sponsor row that "pasted on"
look. A source that already has an alpha channel keeps it; the knockout only
ever removes what is already white. Needs Pillow, local tooling only; the site
build never touches images.
"""

import sys
from pathlib import Path

from PIL import Image

# 3x what each is drawn at, so both stay crisp on a phone.
HEIGHTS = {"": 132, "-sm": 66}
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

    OUT.mkdir(parents=True, exist_ok=True)
    w, h = im.size
    for suffix, height in HEIGHTS.items():
        one = im.resize((round(w * height / h), height), Image.LANCZOS)
        out = OUT / f"{slug}{suffix}.webp"
        one.save(out, "WEBP", quality=90, method=6)
        print(f"{source} -> {out.relative_to(OUT.parent.parent)}  {one.size}  "
              f"({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
