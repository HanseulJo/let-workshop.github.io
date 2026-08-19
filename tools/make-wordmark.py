#!/usr/bin/env python3
"""Bake the LET wordmark from the display font into SVG paths.

    python3 tools/make-wordmark.py

Writes templates/wordmark.svg (letters only, inherits colour), and
static/let-logo.svg + static/favicon.svg (navy rounded square).

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
WORD = "LET"
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

    def boxed(glyph_paths, bbox, target):
        gx0, gy0, gx1, gy1 = bbox
        gw, gh = gx1 - gx0, gy1 - gy0
        scale = target / max(gw, gh)
        tx = (64 - gw * scale) / 2 - gx0 * scale
        ty = (64 - gh * scale) / 2 - gy0 * scale
        inner = "\n    ".join(f'<path d="{p}"/>' for p in glyph_paths)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="{WORD}">\n'
            f'  <rect x="2" y="2" width="60" height="60" rx="14" fill="{NAVY}"/>\n'
            f"  <!-- Baked outlines — no font needed. Regenerate: tools/make-wordmark.py -->\n"
            f'  <g transform="translate({tx:.3f} {ty:.3f}) scale({scale:.5f})" fill="#ffffff">\n'
            f"    {inner}\n  </g>\n</svg>\n"
        )

    (ROOT / "static" / "let-logo.svg").write_text(boxed(paths, (x0, y0, x1, y1), 46), encoding="utf-8")

    # The favicon keeps the first letter — a whole word is illegible at 16px.
    k_paths, k_bounds = draw(WORD[0])
    (ROOT / "static" / "favicon.svg").write_text(boxed(k_paths, k_bounds, 30), encoding="utf-8")

    print(f"wordmark {w:.0f}x{h:.0f} units -> templates/wordmark.svg, static/let-logo.svg, static/favicon.svg")


if __name__ == "__main__":
    main()
