#!/usr/bin/env python3
"""Turn a photograph into the monotone plate behind the hero.

    python3 tools/prep-hero.py ~/Downloads/postech.png

Writes static/hero.jpg. The image is reduced to luminance and then mapped onto
a ramp between two tones taken from the hero's own gradient, so the result
carries no colour of its own — it is the hero background with the photograph's
shading in it. A photo left in its own colours would fight the coral accent and
put the title on an unpredictable ground.

The ramp is wide enough for the campus to actually read as a photograph. It
used to stop well short of that, on the reasoning that contrast for the type
mattered more than seeing the building — but the type only occupies the left
column, so style.css buys its contrast back with a scrim weighted to that side
instead of taking the range away from the whole frame.

Needs Pillow, a local tool dependency only — the site build doesn't touch
images.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

OUT = Path(__file__).resolve().parent.parent / "static" / "hero.jpg"

# Shadow and highlight of the ramp. --hero-bg is #0f1826 and --hero-bg2
# #16233a; the shadow sits just under that pair and the highlight well above
# it, which is what gives the buildings their shape. Both are on the same blue,
# so the plate still belongs to the hero rather than reading as a pasted photo.
SHADOW = "#0a111d"
HIGHLIGHT = "#5c7ea8"

WIDTH = 2000  # wide enough for a 2x hero on a laptop; it is only a backdrop


def duotone(im: Image.Image, shadow: str, highlight: str) -> Image.Image:
    a = tuple(int(shadow.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(highlight.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    grey = ImageOps.grayscale(im)
    # Stretch to the full range before mapping. A source that has already been
    # toned down can occupy very little of it — this one ran 9–45 out of 255 —
    # and mapping that onto the ramp compresses it again into a flat plate with
    # the building barely visible.
    grey = ImageOps.autocontrast(grey, cutoff=(1, 2))
    # Then pull the contrast back a little, so the sky doesn't blow out.
    grey = ImageEnhance.Contrast(grey).enhance(0.9)
    ramp = []
    for channel in range(3):
        ramp += [round(a[channel] + (b[channel] - a[channel]) * (v / 255)) for v in range(256)]
    return grey.convert("RGB").point(ramp)


def main(source: str) -> None:
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    if im.width > WIDTH:
        im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    duotone(im, SHADOW, HIGHLIGHT).save(OUT, "JPEG", quality=82, optimize=True, progressive=True)
    print(f"{Path(source).name} -> {OUT.relative_to(OUT.parent.parent)}  ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    args = ap.parse_args()
    main(args.source)
