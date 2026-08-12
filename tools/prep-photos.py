#!/usr/bin/env python3
"""Turn a raw headshot into the square avatar the cards expect.

    python3 tools/prep-photos.py ~/Downloads/organizer-1.png junghyun-lee
    python3 tools/prep-photos.py ~/Downloads/juho-lee.png juho-lee --to speakers

Writes static/<organizers|speakers>/<slug>.jpg: centre-cropped to a square,
biased upward so a portrait keeps the head rather than the chin, resized to
512px and saved as JPEG. Needs Pillow, which is a local tool dependency only —
the site build doesn't touch images.

Someone who both speaks and organises needs the file in both folders, since the
two card templates look in their own directory:

    python3 tools/prep-photos.py src.jpg chulhee-yun --to speakers organizers
"""

import argparse
from pathlib import Path

from PIL import Image, ImageOps

# The card photo fills the card's width — around 150 CSS px, so 300 device px
# on a retina screen. 256 was cut for a 60px thumbnail and is fractionally short
# of that; 512 clears it with room for wider cards later.
SIZE = 512
STATIC = Path(__file__).resolve().parent.parent / "static"
FOLDERS = ("organizers", "speakers")


def square(im: Image.Image) -> Image.Image:
    side = min(im.size)
    w, h = im.size
    left = (w - side) // 2
    # Faces sit above centre in a portrait; take the crop from higher up.
    top = int((h - side) * (0.25 if h > w else 0.5))
    return im.crop((left, top, left + side, top + side))


def main(source: str, slug: str, folders: list[str]) -> None:
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    face = square(im).resize((SIZE, SIZE), Image.LANCZOS)
    if min(im.size) < SIZE:
        print(f"  note: {Path(source).name} is only {im.size[0]}x{im.size[1]} — upscaled")
    for folder in folders:
        out = STATIC / folder / f"{slug}.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        face.save(out, "JPEG", quality=85, optimize=True)
        print(f"{Path(source).name} -> {out.relative_to(STATIC.parent)}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("slug")
    ap.add_argument("--to", nargs="+", choices=FOLDERS, default=["organizers"])
    args = ap.parse_args()
    main(args.source, args.slug, args.to)
