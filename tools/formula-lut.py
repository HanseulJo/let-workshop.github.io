#!/usr/bin/env python3
"""Measure every formula as a block of ink, so an image can be spelled in them.

    python3 tools/formula-lut.py

Reads data/formulas.yml, renders each entry at a range of stroke weights, and
writes data/formula-lut.json: for every (formula, weight) pair, how wide it is
in cells and how much ink it puts in each part of the cells it covers.

Why a table and not a brightness number. A formula is not a pixel — it is a
long, thin, structured mark. `\\sum_{t=1}^T` is dark at the left and empty at
the right; `w_{t+1} = w_t - \\eta \\nabla f(w_t)` is an even grey; a fraction
is dark in the middle band and light above and below. Reducing each to one
average throws away exactly the property that makes them useful as tiles, so
the entry records a small grid instead: BANDS rows tall by however many cells
wide the formula runs. tools/formula-art.py then matches those grids against
the picture rather than matching averages.

Weights are the other axis. The same formula stroked more heavily covers more
of its box without changing what it says, which is what gives the set a range
of darkness to work with — a database of a hundred formulas is a hundred
patterns but only a narrow band of tones, and a picture needs tones.

The geometry here (cell size, row height, scale) is baked into the signatures,
so formula-art.py reads it back out of the file rather than being told again.
Needs matplotlib, PyYAML and NumPy — all local tool dependencies; the site
build does not touch this.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import matplotlib
    import numpy as np
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover
    sys.exit(f"missing dependency '{exc.name}'\n  pip install matplotlib pyyaml numpy")

matplotlib.use("Agg")
# Computer Modern, the face TeX sets maths in — the same choice as
# tools/prep-formulas.py, and for the same reason.
matplotlib.rcParams["mathtext.fontset"] = "cm"
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402
from matplotlib.textpath import TextPath  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "formulas.yml"
OUT = ROOT / "data" / "formula-lut.json"

FONTSIZE = 48  # path coordinate scale; matches prep-formulas.py so ids line up
DPI = 100  # only relates matplotlib's points to our pixels


def raster(path, w, h, box_w, box_h, scale, stroke):
    """Draw one formula centred in a box_w x box_h pixel cell.

    Returns coverage in [0, 1], row 0 at the top. `scale` is pixels per path
    unit and `stroke` is the extra outline width in path units — stroking the
    filled outline is what thickens the glyphs.
    """
    fig = Figure(figsize=(box_w / DPI, box_h / DPI), dpi=DPI)
    FigureCanvasAgg(fig)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_facecolor("white")
    # matplotlib linewidths are points; ours are path units.
    lw = stroke * scale * 72 / DPI
    ax.add_patch(PathPatch(path, facecolor="black", edgecolor="black", linewidth=lw,
                           joinstyle="round", capstyle="round"))
    # The path is in SVG orientation (y down), so the y axis is inverted to
    # match — which also puts buffer row 0 at the top of the glyph.
    ax.set_xlim(w / 2 - box_w / (2 * scale), w / 2 + box_w / (2 * scale))
    ax.set_ylim(h / 2 + box_h / (2 * scale), h / 2 - box_h / (2 * scale))
    fig.canvas.draw()
    rgba = np.asarray(fig.canvas.buffer_rgba())
    grey = rgba[:, :, :3].mean(axis=2) / 255.0
    return 1.0 - grey  # ink coverage


def signature(cov, bands, units):
    """Mean coverage over a bands x units grid."""
    h, w = cov.shape
    ys = np.linspace(0, h, bands + 1).round().astype(int)
    xs = np.linspace(0, w, units + 1).round().astype(int)
    out = np.empty((bands, units))
    for r in range(bands):
        for c in range(units):
            block = cov[ys[r] : ys[r + 1], xs[c] : xs[c + 1]]
            out[r, c] = block.mean() if block.size else 0.0
    return out


def main(cell, row_h, bands, strokes, target_h) -> None:
    formulas = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["formulas"]
    prop = FontProperties(size=FONTSIZE)

    # One scale for the whole set, from the median formula height: it makes the
    # glyphs a consistent size, which is the only reason a stroke width means
    # the same thing in every entry. Fitting each formula to the row instead
    # would make a fraction and a one-line identity render at wildly different
    # type sizes, and the art would read as a ransom note.
    paths, boxes = [], []
    for i, tex in enumerate(formulas):
        try:
            tp = TextPath((0, 0), f"${tex}$", size=FONTSIZE, prop=prop)
        except Exception as exc:
            print(f"  skipped fx{i}: {' '.join(str(exc).split())[-70:]}")
            paths.append(None)
            boxes.append(None)
            continue
        v = tp.vertices
        if not len(v):
            paths.append(None)
            boxes.append(None)
            continue
        x0, x1 = v[:, 0].min(), v[:, 0].max()
        y0, y1 = v[:, 1].min(), v[:, 1].max()
        w, h = max(x1 - x0, 0.1), max(y1 - y0, 0.1)
        # Same normalisation as prep-formulas.py: origin at the top left, y down.
        shifted = np.column_stack([v[:, 0] - x0, y1 - v[:, 1]])
        paths.append(MplPath(shifted, tp.codes))
        boxes.append((float(w), float(h)))

    heights = sorted(b[1] for b in boxes if b)
    median_h = heights[len(heights) // 2]
    scale = target_h * row_h / median_h

    entries = []
    for i, (path, box) in enumerate(zip(paths, boxes)):
        if path is None:
            continue
        w, h = box
        units = max(1, int(round(w * scale / cell)))
        box_w, box_h = units * cell, row_h
        for si, stroke in enumerate(strokes):
            cov = raster(path, w, h, box_w, box_h, scale, stroke)
            sig = signature(cov, bands, units)
            entries.append(
                {
                    "id": f"fx{i}",
                    "weight": si,
                    "stroke": round(stroke, 3),
                    "units": units,
                    "w": round(w, 1),
                    "h": round(h, 1),
                    "mean": round(float(cov.mean()), 4),
                    "sig": [[round(float(x), 4) for x in row] for row in sig],
                }
            )

    means = sorted(e["mean"] for e in entries)
    doc = {
        "cell": cell,
        "row_h": row_h,
        "bands": bands,
        "scale": round(scale, 5),
        "strokes": strokes,
        "coverage": {"min": round(means[0], 4), "max": round(means[-1], 4)},
        "entries": entries,
    }
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(
        f"  {len(entries)} entries ({len(entries) // len(strokes)} formulas x {len(strokes)} weights)"
        f" -> {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)"
    )
    print(f"  scale {scale:.4f} px/unit, cell {cell}x{row_h}px, widths "
          f"{min(e['units'] for e in entries)}-{max(e['units'] for e in entries)} cells")
    print(f"  coverage {means[0]:.3f} - {means[-1]:.3f}  (the tonal range the set can reach)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", type=int, default=10, help="width of one cell in px (default 10)")
    ap.add_argument("--row", type=int, default=26, help="height of one row in px (default 26)")
    ap.add_argument("--bands", type=int, default=3, help="horizontal bands per cell (default 3)")
    ap.add_argument("--target-height", type=float, default=0.5,
                    help="median formula height as a fraction of the row (default 0.5)")
    ap.add_argument("--strokes", type=float, nargs="+", default=[0.0, 1.2, 2.6, 4.4],
                    help="outline widths in path units; more of them is more tones")
    args = ap.parse_args()
    main(args.cell, args.row, args.bands, args.strokes, args.target_height)
