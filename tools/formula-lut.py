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


def calibrate(paths, boxes, cell, row_h, scale, levels, max_stroke, sample=18):
    """Stroke widths that step through *coverage* evenly, not through width.

    Ink does not grow linearly with the stroke: the first fraction of a pixel
    added to a hairline outline is worth far more than the last, because heavy
    strokes start filling counters and closing up gaps that were already dark.
    A ladder of evenly spaced widths therefore bunches most of its rungs at the
    dark end and leaves the midtones — where a photograph spends most of its
    time — with almost nothing to choose between. So the curve is measured on a
    sample of the set and then inverted: pick the widths that land on evenly
    spaced coverages.
    """
    picks = [i for i, p in enumerate(paths) if p is not None]
    picks = picks[:: max(1, len(picks) // sample)][:sample]
    sweep = np.linspace(0.0, max_stroke, 21)
    curve = []
    for s in sweep:
        vals = []
        for i in picks:
            w, h = boxes[i]
            units = max(1, int(round(w * scale / cell)))
            vals.append(raster(paths[i], w, h, units * cell, row_h, scale, s).mean())
        curve.append(float(np.median(vals)))
    curve = np.array(curve)
    # The curve is monotone in principle; enforce it so the inversion is safe.
    curve = np.maximum.accumulate(curve)
    wanted = np.linspace(curve[0], curve[-1], levels)
    return [round(float(x), 3) for x in np.interp(wanted, curve, sweep)]


def main(cell, row_h, bands, strokes, target_h, levels, max_stroke, sizes) -> None:
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

    if levels:
        strokes = calibrate(paths, boxes, cell, row_h, scale, levels, max_stroke)
        print(f"  calibrated {levels} weights: {strokes}")

    # Size is the third axis, after which formula and how heavily it is stroked.
    # The same formula set larger fills more of its row and so reads darker; set
    # smaller it reads lighter, and it also spans fewer cells, which gives the
    # row solver more ways to partition itself. Both effects are wanted. The
    # cost is that the glyphs are no longer all one size — for a picture that is
    # the point, but it is the opposite of what the drifting field wants, which
    # is why the two have separate tables.
    entries = []
    for i, (path, box) in enumerate(zip(paths, boxes)):
        if path is None:
            continue
        w, h = box
        for size in sizes:
            s_scale = scale * size
            units = max(1, int(round(w * s_scale / cell)))
            box_w, box_h = units * cell, row_h
            for si, stroke in enumerate(strokes):
                # The stroke is in path units, so it has to shrink with the
                # glyph or a small formula would be drawn in a heavier pen than
                # a large one at the same nominal weight.
                cov = raster(path, w, h, box_w, box_h, s_scale, stroke * size)
                sig = signature(cov, bands, units)
                entries.append(
                    {
                        "id": f"fx{i}",
                        "weight": si,
                        "size": round(size, 3),
                        "stroke": round(stroke * size, 3),
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
        "sizes": sizes,
        "coverage": {"min": round(means[0], 4), "max": round(means[-1], 4)},
        "entries": entries,
    }
    OUT.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(
        f"  {len(entries)} entries ({len(strokes)} weights x {len(sizes)} sizes)"
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
    ap.add_argument("--levels", type=int, default=12,
                    help="number of weights, spaced evenly in coverage (0 to use --strokes)")
    ap.add_argument("--sizes", type=float, nargs="+", default=[1.0],
                    help="glyph size multipliers; more sizes is finer control of tone")
    ap.add_argument("--max-stroke", type=float, default=11.0,
                    help="heaviest outline to calibrate against, in path units")
    ap.add_argument("--strokes", type=float, nargs="+", default=[0.0, 1.2, 2.6, 4.4],
                    help="explicit outline widths, used only when --levels 0")
    args = ap.parse_args()
    main(args.cell, args.row, args.bands, args.strokes, args.target_height,
         args.levels, args.max_stroke, args.sizes)
