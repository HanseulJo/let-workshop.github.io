#!/usr/bin/env python3
"""Bake a formula drawing into a PNG the browser can use as a mask.

    python3 tools/rasterise-mask.py static/hero-art.svg -o static/hero-art.png

The drawing is a still picture that never changes once it is generated, but as
an SVG the browser has to do the work of drawing it on every visit: nearly six
thousand <use> elements, each a reference into a symbol table of eight hundred
glyph outlines, parsed and rasterised before the hero can paint — and again
whenever the mask's box changes size. A PNG is the same picture with the
drawing already done.

The output is an alpha mask, not a picture. Only coverage matters: the colour
comes from the layer underneath, which is the photograph. So the PNG is written
with the ink opaque and the gaps transparent, which is what CSS mask-image reads
by default, and the colour channels are flattened to white — they are never
seen, and a constant channel compresses to nothing.

Resolution is the one judgement here. Too little and the formulas turn to grey
mush at the sizes the hero is actually shown at; too much and the file is worse
than the SVG it replaces. --width is the pixel width to bake at; the height
follows the drawing's own aspect.

Needs Chrome and Pillow. Local tool only — the site build does not run this.
"""

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svg")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--width", type=int, default=2400, help="pixel width to bake at")
    ap.add_argument("--crop", metavar="X,Y,W,H",
                    help="a region of the drawing's own coordinates to bake "
                         "instead of the whole of it")
    ap.add_argument("--port", type=int, default=8993)
    args = ap.parse_args()

    try:
        from PIL import Image
    except ModuleNotFoundError:
        sys.exit("needs Pillow:  pip install pillow")

    svg = Path(args.svg)
    markup = svg.read_text(encoding="utf-8")
    box = re.search(r'viewBox="([\d.\s-]+)"', markup)
    if not box:
        sys.exit(f"{svg} has no viewBox, so its aspect is unknown")
    vw, vh = (float(x) for x in box.group(1).split()[2:])
    if args.crop:
        # A phone shows a tall slice of a wide drawing, and asking it to draw
        # the whole width in order to look at a fifth of it is the difference
        # between an 11MB mask surface and a 64MB one. The slice is taken here
        # instead, by moving the viewBox rather than by clipping — the paths
        # outside it are never asked for.
        x, y, vw, vh = (float(v) for v in args.crop.split(","))
        markup = markup.replace(box.group(0), f'viewBox="{x} {y} {vw} {vh}"', 1)
    height = round(args.width * vh / vw)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / svg.name).write_text(markup, encoding="utf-8")
        # An <img> would rasterise it too, but an inline <svg> sized to the page
        # avoids a second layer of scaling decisions.
        (work / "page.html").write_text(
            "<style>html,body{margin:0;background:transparent}"
            f"svg{{display:block;width:{args.width}px;height:{height}px}}</style>"
            + markup, encoding="utf-8")
        server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)],
                                  cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.5)
            shot = work / "shot.png"
            subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                 # Transparent, so what lands in the alpha channel is the ink
                 # and nothing else.
                 "--default-background-color=00000000",
                 f"--window-size={args.width},{height}",
                 "--virtual-time-budget=60000", f"--screenshot={shot}",
                 f"http://localhost:{args.port}/page.html"],
                capture_output=True, timeout=180)
            if not shot.exists():
                sys.exit("Chrome produced no image")
            im = Image.open(shot).convert("RGBA")
        finally:
            server.terminate()

    # The colour channels are never read — a mask is its alpha. Flattening them
    # to one value costs nothing to look at and a great deal less to store.
    alpha = im.getchannel("A")
    flat = Image.new("RGBA", im.size, (255, 255, 255, 255))
    flat.putalpha(alpha)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    flat.save(out, optimize=True)
    before = svg.stat().st_size
    after = out.stat().st_size
    print(f"  {svg.name} {before/1024:.0f} KB  ->  {out.name} {after/1024:.0f} KB "
          f"({after/before:.0%})  {flat.size[0]}x{flat.size[1]}")
    ink = sum(alpha.histogram()[8:]) / (flat.size[0] * flat.size[1])
    print(f"  {ink:.1%} of the frame carries ink")


if __name__ == "__main__":
    main()
