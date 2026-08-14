#!/usr/bin/env python3
"""Render data/formulas.yml into the sprite the hero drifts across itself.

    python3 tools/prep-formulas.py

Writes static/formulas.svg: one <symbol> per formula, plus a manifest of ids
and aspect ratios at static/formulas.json for the page to lay them out.

Why bake them. Rendering LaTeX in the browser means shipping KaTeX or MathJax
— a few hundred KB of script and webfonts — for something purely decorative
that nobody reads. matplotlib's mathtext draws the same glyphs to vector paths
here, once, and the page ships one small SVG with no maths runtime at all.

Paths, not text: no font has to be present on the reader's machine, and the
result is identical everywhere. Needs matplotlib and PyYAML, both local tool
dependencies — the site build itself does not touch this.
"""

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

try:
    import matplotlib
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover
    sys.exit(f"missing dependency '{exc.name}'\n  pip install matplotlib pyyaml")

matplotlib.use("Agg")
# Computer Modern — the face TeX itself sets maths in. matplotlib defaults to
# DejaVu Sans, which is legible but reads as a plot label rather than as a
# paper; on a decorative field of formulas that difference is the whole point.
matplotlib.rcParams["mathtext.fontset"] = "cm"
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402
from matplotlib.textpath import TextPath  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "formulas.yml"
SPRITE = ROOT / "static" / "formulas.svg"
MANIFEST = ROOT / "static" / "formulas.json"

FONTSIZE = 48  # path coordinate scale only; rounded to integers, so keep it large


def to_path_data(vertices, codes) -> str:
    """MplPath vertices/codes -> an SVG `d` string.

    Relative commands, and every number rounded to an integer first so the
    deltas are exact. Absolute coordinates run to three and four digits at this
    font size; the step from one control point to the next is usually one or
    two, and on a sheet of ~100 formulas that difference is most of the file.
    Rounding before differencing matters — rounding the deltas instead lets the
    error accumulate along a contour until the glyph visibly drifts.
    """
    pts = [(round(x), round(y)) for x, y in vertices]
    out, i = [], 0
    cx = cy = 0  # current point, in the same rounded integer space
    start = (0, 0)

    def emit(letter, idx, n):
        # Every offset in a relative command is measured from the point the
        # command *started* at, not from the previous control point — chaining
        # them scatters the curves.
        nonlocal cx, cy
        nums = ["%d %d" % (pts[idx + k][0] - cx, pts[idx + k][1] - cy) for k in range(n)]
        cx, cy = pts[idx + n - 1]
        out.append(letter + ",".join(nums))

    while i < len(codes):
        code = codes[i]
        if code == MplPath.MOVETO:
            emit("m", i, 1); start = (cx, cy); i += 1
        elif code == MplPath.LINETO:
            emit("l", i, 1); i += 1
        elif code == MplPath.CURVE3:
            emit("q", i, 2); i += 2
        elif code == MplPath.CURVE4:
            emit("c", i, 3); i += 3
        elif code == MplPath.CLOSEPOLY:
            out.append("z"); cx, cy = start; i += 1
        else:  # pragma: no cover
            i += 1
    return "".join(out)


def main() -> None:
    formulas = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["formulas"]
    prop = FontProperties(size=FONTSIZE)
    symbols, manifest, failed = [], [], []

    for i, tex in enumerate(formulas):
        try:
            # TextPath renders mathtext straight to one outline — no per-glyph
            # bookkeeping, and no font needed at the other end.
            tp = TextPath((0, 0), f"${tex}$", size=FONTSIZE, prop=prop)
        except Exception as exc:
            failed.append((tex, " ".join(str(exc).split())[-90:]))
            continue

        verts, codes = tp.vertices, tp.codes
        if len(verts) == 0:
            failed.append((tex, "rendered empty"))
            continue

        xs, ys = verts[:, 0], verts[:, 1]
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        w, h = max(x1 - x0, 0.1), max(y1 - y0, 0.1)
        # SVG's y runs down, matplotlib's runs up; flip and shift to the origin
        shifted = [(x - x0, y1 - y) for x, y in verts]

        ident = f"fx{i}"
        symbols.append(
            '<symbol id="%s" viewBox="0 0 %.2f %.2f"><path d="%s"/></symbol>'
            % (ident, w, h, to_path_data(shifted, codes))
        )
        # w and h are in path units at a single shared FONTSIZE, so scaling every
        # formula by one constant gives them all the same glyph size — which
        # fitting each to a fixed box does not.
        manifest.append({"id": ident, "w": round(float(w), 1), "h": round(float(h), 1),
                         "ratio": round(float(w / h), 3)})

    if failed:
        print(f"  {len(failed)} formula(s) did not render and were skipped:")
        for tex, err in failed:
            print(f"    {tex[:60]}\n      {err}")

    SPRITE.parent.mkdir(parents=True, exist_ok=True)
    SPRITE.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">'
        + "".join(symbols)
        + "</svg>",
        encoding="utf-8",
    )
    MANIFEST.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(manifest)} formulas -> {SPRITE.relative_to(ROOT)} ({SPRITE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
