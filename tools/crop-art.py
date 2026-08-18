#!/usr/bin/env python3
"""Cut the tall slice of the formula drawing that a phone actually shows.

    python3 tools/crop-art.py static/hero-art.svg -o static/hero-art-narrow.svg

The drawing is 2628x896 — nearly three to one — and the hero on a phone is
414x777, which is taller than it is wide. The mask is sized `cover`, so to fill
that box the browser draws the whole drawing at 2280x777 CSS pixels and then
looks at 414 of them. At a device ratio of 3 that is a 16 megapixel alpha
surface, 64MB, painted from five to seven thousand <use> elements, to show a
fifth of it. It is the largest single thing the page asks a phone to do, and on
iOS it is enough to have the tab killed and reloaded.

This writes the slice out as its own drawing: the viewBox moves to the region
that is shown and every glyph outside it is dropped, along with any symbol left
unreferenced. The slice is close to the hero's own proportions, so `cover`
scales it to about the size of the box instead of three times its width — the
same picture, an eighth of the memory, and still vector.

Wider than the strictly visible window, because the window moves: the mask sits
at 62% across, and how much of it shows depends on how wide and how tall the
phone is. The default takes the visible slice at 390px and half again.

Local tool only — the site build does not run this.
"""

import argparse
import re
import sys
from pathlib import Path

# x, y, width, height in the drawing's own units. Centred on what a 390px
# phone shows, which is x 1334 to 1812.
CROP = (1290, 0, 570, 896)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svg")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--crop", metavar="X,Y,W,H", default=",".join(str(v) for v in CROP))
    args = ap.parse_args()

    cx, cy, cw, ch = (float(v) for v in args.crop.split(","))
    src = Path(args.svg)
    t = src.read_text(encoding="utf-8")

    box = re.search(r'viewBox="([\d.\s-]+)"', t)
    if not box:
        sys.exit(f"{src} has no viewBox")

    kept, dropped, used = [], 0, set()

    def sift(m):
        nonlocal dropped
        tag = m.group(0)
        x = float(re.search(r'\bx="([-\d.]+)"', tag).group(1))
        w = float(re.search(r'\bwidth="([-\d.]+)"', tag).group(1) or 0)
        # Kept if the glyph's own box touches the slice at all: a letter half
        # inside the edge still draws the half that is inside.
        if x + w < cx or x > cx + cw:
            dropped += 1
            return ""
        used.add(re.search(r'href="#([^"]+)"', tag).group(1))
        kept.append(tag)
        return tag

    body = re.sub(r"<use\b[^>]*/>", sift, t)

    # Symbols nothing points at any more. They are the bulk of the file — each
    # is a full glyph outline — so dropping them is most of what makes the
    # slice small as well as cheap.
    gone = 0

    def sift_symbol(m):
        nonlocal gone
        if re.search(r'id="([^"]+)"', m.group(0)).group(1) in used:
            return m.group(0)
        gone += 1
        return ""

    body = re.sub(r"<symbol\b.*?</symbol>", sift_symbol, body, flags=re.S)

    # No coordinate is rewritten: the viewBox moves instead, so the glyphs keep
    # the positions the solver gave them.
    body = body.replace(box.group(0), f'viewBox="{cx:g} {cy:g} {cw:g} {ch:g}"', 1)
    body = re.sub(r'\swidth="[\d.]+"\sheight="[\d.]+"(?=\srole=)',
                  f' width="{cw:g}" height="{ch:g}"', body, count=1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    before, after = src.stat().st_size, out.stat().st_size
    print(f"  {src.name} -> {out.name}   {before / 1024:.0f} KB -> {after / 1024:.0f} KB "
          f"({after / before:.0%})   kept {len(kept)} of {len(kept) + dropped} glyphs, "
          f"dropped {gone} symbols")


if __name__ == "__main__":
    main()
