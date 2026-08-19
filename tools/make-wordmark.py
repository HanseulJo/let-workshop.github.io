#!/usr/bin/env python3
"""Bake the LET wordmark from the display font into SVG paths.

    python3 tools/make-wordmark.py

Writes templates/wordmark.svg (letters only, inherits colour), and
static/let-logo.svg (LET WS in a navy rounded square, for a profile
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
WORD = "LET"
# What the square mark says. The wordmark is the name as it is set in running
# text; this is the name as it has to survive being 40px wide next to somebody
# else's avatar, where three letters on their own could be anything.
SQUARE = ("LET", "WS")
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

    def stacked(words, target):
        """Two words on two rows, at one scale, centred as a block.

        The square mark says LET WS, not LET: on a profile the acronym on its
        own is three letters that could be anything, and "workshop" is what
        turns them into the name of a thing. Set on one line those six
        characters would be a third the height they are here — a square wants
        its content square, and two rows of three is the shape that fills it.

        One scale for both rows rather than each fitted to the width, or LET
        and WS would be set in two different sizes and read as two marks.
        """
        drawn = [draw(w) for w in words]
        widths = [b[2] - b[0] for _, b in drawn]
        heights = [b[3] - b[1] for _, b in drawn]
        gap = max(heights) * 0.22
        scale = min(target / max(widths), target / (sum(heights) + gap))
        block_h = sum(heights) * scale + gap * scale
        rows, y = [], (64 - block_h) / 2
        for (gpaths, (bx0, by0, bx1, by1)), gw, gh in zip(drawn, widths, heights):
            tx = (64 - gw * scale) / 2 - bx0 * scale
            ty = y - by0 * scale
            inner = "\n      ".join(f'<path d="{q}"/>' for q in gpaths)
            rows.append(f'<g transform="translate({tx:.3f} {ty:.3f}) scale({scale:.5f})">'
                        f"\n      {inner}\n    </g>")
            y += gh * scale + gap * scale
        body = "\n    ".join(rows)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" '
            f'aria-label="{" ".join(words)}">\n'
            f'  <rect x="2" y="2" width="60" height="60" rx="14" fill="{NAVY}"/>\n'
            f"  <!-- Baked outlines — no font needed. Regenerate: tools/make-wordmark.py -->\n"
            f'  <g fill="#ffffff">\n    {body}\n  </g>\n</svg>\n'
        )

    (ROOT / "static" / "let-logo.svg").write_text(stacked(SQUARE, 40), encoding="utf-8")

    # The favicon keeps the first letter — a whole word is illegible at 16px.
    k_paths, k_bounds = draw(WORD[0])
    (ROOT / "static" / "favicon.svg").write_text(boxed(k_paths, k_bounds, 30), encoding="utf-8")

    print(f"wordmark {w:.0f}x{h:.0f} units -> templates/wordmark.svg, static/let-logo.svg, static/favicon.svg")


if __name__ == "__main__":
    main()
