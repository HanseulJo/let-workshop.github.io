#!/usr/bin/env python3
"""Bake the LeT wordmark from the display font into SVG paths.

    python3 tools/make-wordmark.py

Writes templates/wordmark.svg (letters only, inherits colour), and
static/let-logo.svg (LeT WS in a navy rounded square, for a profile
picture) + static/favicon.svg (one letter, for 16px).

Outlines are baked to paths rather than left as <text font-family="…">, because
these files are used as a favicon, a GitHub avatar and an inline hero mark —
places where a font-family reference is either ignored or resolves to whatever
the renderer happens to have. Paths render identically everywhere.

Re-run after changing the display face in templates/style.css, then rasterise
the PNGs (see CONTRIBUTING.md). Needs fontTools + brotli, local tooling only.
"""

import sys
from pathlib import Path

from fontTools.misc.transform import Transform
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "static" / "fonts" / "jost-latin.woff2"
WORD = "LeT"
# What the square mark says. It said "LeT WS" on two rows, on the argument that
# three letters alone could be anything and the second word is what makes them
# the name of a thing. A profile picture is not read on its own, though — it
# sits beside the name it belongs to, everywhere GitHub draws it — so the
# second row was answering a question the page next to it had already answered,
# at the cost of halving the letters that do the work.
SQUARE = "LeT"
WEIGHT = 900
TRACK = 30  # extra letterspacing in font units — a wordmark wants a little air
NAVY = "#14213d"


def draw(word: str):
    font = instancer.instantiateVariableFont(TTFont(FONT), {"wght": WEIGHT}, inplace=False)
    glyphs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]

    paths, bounds, x = [], BoundsPen(glyphs), 0
    for i, ch in enumerate(word):
        gname = cmap[ord(ch)]
        # Font space is y-up, SVG is y-down.
        flip = Transform(1, 0, 0, -1, x, 0)
        pen = SVGPathPen(glyphs)
        glyphs[gname].draw(TransformPen(pen, flip))
        glyphs[gname].draw(TransformPen(bounds, flip))
        paths.append(pen.getCommands())
        x += hmtx[gname][0] + (TRACK if i < len(word) - 1 else 0)

    return paths, bounds.bounds


def main() -> None:
    if not FONT.exists():
        sys.exit(f"missing {FONT} — see CONTRIBUTING.md")

    paths, (x0, y0, x1, y1) = draw(WORD)
    w, h = x1 - x0, y1 - y0
    body = "\n    ".join(f'<path d="{p}"/>' for p in paths)

    (ROOT / "templates" / "wordmark.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {w:.0f} {h:.0f}"\n'
        f'     role="img" aria-label="{WORD}" fill="currentColor">\n    {body}\n</svg>\n',
        encoding="utf-8",
    )

    def ground(full_bleed):
        """The square under the letters.

        Full-bleed for anything someone else masks. GitHub rounds an
        organisation's picture at about 9% of the side and a person's into a
        circle, then composites it onto the page; a mark that rounds its own
        corners at 22% and keeps a transparent margin inside them arrives
        smaller than every other avatar in the list, in a gap, with corners
        rounder than the interface. A favicon is drawn onto the tab and owns
        its own shape, so that one keeps the rounding.
        """
        return (f'<rect width="64" height="64" fill="{NAVY}"/>' if full_bleed
                else f'<rect x="2" y="2" width="60" height="60" rx="14" fill="{NAVY}"/>')

    def boxed(glyph_paths, bbox, target, full_bleed=False, label=WORD):
        gx0, gy0, gx1, gy1 = bbox
        gw, gh = gx1 - gx0, gy1 - gy0
        scale = target / max(gw, gh)
        tx = (64 - gw * scale) / 2 - gx0 * scale
        ty = (64 - gh * scale) / 2 - gy0 * scale
        inner = "\n    ".join(f'<path d="{p}"/>' for p in glyph_paths)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="{label}">\n'
            f'  {ground(full_bleed)}\n'
            f"  <!-- Baked outlines — no font needed. Regenerate: tools/make-wordmark.py -->\n"
            f'  <g transform="translate({tx:.3f} {ty:.3f}) scale({scale:.5f})" fill="#ffffff">\n'
            f"    {inner}\n  </g>\n</svg>\n"
        )

    # One row, so the width is what fits and 48 of 64 is three quarters of the
    # square. The letters come out about a fifth of the side tall, which at the
    # 40px GitHub usually draws is 12px of Jost 900 — heavy enough to hold. The
    # block's half-diagonal is 25.8 against a radius of 32, so a circular crop
    # cannot reach it either.
    sq_paths, sq_bounds = draw(SQUARE)
    (ROOT / "static" / "let-logo.svg").write_text(
        boxed(sq_paths, sq_bounds, 48, full_bleed=True, label=SQUARE), encoding="utf-8")

    # The favicon keeps the first letter — a whole word is illegible at 16px.
    k_paths, k_bounds = draw(WORD[0])
    (ROOT / "static" / "favicon.svg").write_text(boxed(k_paths, k_bounds, 30), encoding="utf-8")

    print(f"wordmark {w:.0f}x{h:.0f} units -> templates/wordmark.svg, static/let-logo.svg, static/favicon.svg")


if __name__ == "__main__":
    main()
