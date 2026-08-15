#!/usr/bin/env python3
"""Spell a photograph out in formulas.

    python3 tools/formula-art.py ~/Downloads/postech.jpg -o static/hero-art.svg

Reads the table written by tools/formula-lut.py and the glyph outlines from
static/formulas.svg, and writes an SVG in which every mark is a real formula,
chosen so that the ink it puts down reproduces the picture.

How it chooses. The picture is cut into rows the height of one formula and
columns one cell wide, and each cell is reduced to BANDS numbers — the mean
brightness of its top, middle and bottom third. A formula spanning n cells
therefore has to match a 3 x n patch of the picture, and the table says what
its own 3 x n patch looks like. That is the whole matching problem: it is not
"how dark is this square", it is "which formula, at which weight, has the shape
of ink this strip of the picture has".

Why dynamic programming rather than greedy. Formulas are not all the same
width, so filling a row is a partition problem: a slightly worse formula here
may leave a span that a much better one fits exactly there. Greedy takes the
local best and then has to jam whatever is left into the gap, which shows up as
a ragged, mismatched right edge on every row. The row is short enough (a few
hundred cells, a few hundred candidates) that solving it exactly costs
milliseconds, so there is no reason to approximate.

Two costs are added to the match. Reuse, counted across the whole picture, so
one conveniently mid-grey formula does not end up tiling half the sky; and
immediate repetition, weighted far more heavily, because the same mark twice in
a row reads as a mistake rather than as texture.

Needs NumPy and Pillow. Local tool only — the site build does not run this.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageEnhance, ImageOps
except ModuleNotFoundError as exc:  # pragma: no cover
    sys.exit(f"missing dependency '{exc.name}'\n  pip install numpy pillow")

ROOT = Path(__file__).resolve().parent.parent
LUT = ROOT / "data" / "formula-lut.json"
SPRITE = ROOT / "static" / "formulas.svg"

SYMBOL = re.compile(r'<symbol id="(fx\d+)" viewBox="([^"]+)"><path d="([^"]+)"/></symbol>')


def load_paths():
    """id -> (path data, viewBox) from the sprite prep-formulas.py writes."""
    text = SPRITE.read_text(encoding="utf-8")
    return {m.group(1): (m.group(3), m.group(2)) for m in SYMBOL.finditer(text)}


def picture(source, cols, rows, cell, row_h, bands, gamma, lo_pct, hi_pct):
    """The image as a (rows, bands, cols) array of target coverage in [0, 1]."""
    im = ImageOps.exif_transpose(Image.open(source)).convert("L")
    # Crop to the art's aspect first, the way the hero's own photograph is
    # covered rather than stretched.
    im = ImageOps.fit(im, (cols * cell, rows * row_h), Image.LANCZOS, centering=(0.5, 0.45))
    # BOX is an exact area average, so resizing straight to the grid *is* the
    # block mean — no reshaping, and it does not care whether the row height
    # divides by the number of bands.
    small = im.resize((cols, rows * bands), Image.BOX)
    a = np.asarray(small, dtype=np.float64).reshape(rows, bands, cols) / 255.0

    # Stretch the picture's own range rather than the nominal 0-255: a hero
    # photograph that has already been toned down occupies very little of it,
    # and mapping that straight onto the formulas' range wastes most of them.
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    a = np.clip((a - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    return a**gamma


def tint_map(source, cols, rows, cell, row_h, base, strength, boost, lift):
    """One colour per cell, taken from the picture and pulled towards `base`.

    Density alone asks the eye to read a photograph through one variable, and a
    building and a tree at the same brightness become the same thing. Giving
    each formula the colour of the ground it stands on adds a second variable,
    and it costs nothing in print: the colour is a solid fill on a path, so the
    sheet stays vector and the photograph's own resolution never enters into it.

    `strength` is how far towards the photograph each fill travels. All the way
    is a colour halftone that no longer belongs to the poster; a little way is
    a monochrome field that happens to warm and cool with the subject.
    """
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    im = ImageOps.fit(im, (cols, rows), Image.BOX, centering=(0.5, 0.45))
    if boost != 1.0:
        im = ImageEnhance.Color(im).enhance(boost)

    b = np.array([int(base[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64)
    base_v = float(np.asarray(Image.new("RGB", (1, 1), tuple(int(x) for x in b)).convert("HSV"))[0, 0, 2])

    # `lift` decides how much of the picture's brightness the fill is allowed to
    # carry. It matters because the density is already carrying it: where the
    # formulas are sparse, painting them near the colour of the ground as well
    # loses the area completely — which is exactly what "some parts show nothing"
    # is. At 1 the fill keeps only hue and saturation and every tile has the
    # same weight of ink; at 0 it is the photograph untouched.
    hsv = np.asarray(im.convert("HSV"), dtype=np.float64)
    hsv[:, :, 2] = hsv[:, :, 2] * (1.0 - lift) + base_v * lift
    a = np.asarray(Image.fromarray(np.clip(hsv, 0, 255).astype(np.uint8), "HSV").convert("RGB"),
                   dtype=np.float64)
    if strength >= 1.0:
        return np.clip(a, 0, 255).astype(np.uint8)
    return np.clip(b + (a - b) * strength, 0, 255).astype(np.uint8)


def group_by_width(entries):
    """Entries stacked by width, so a whole width can be scored in one go.

    The inner loop compares one column against every candidate; done one
    formula at a time in Python it is a few million array calls per picture, and
    the run goes from seconds to minutes. Stacking each width into a single
    (candidates, bands, units) array turns that into one subtraction per width
    per column.
    """
    groups = {}
    for e in entries:
        groups.setdefault(e["units"], []).append(e)
    out = {}
    for units, group in groups.items():
        out[units] = {
            "entries": group,
            "sig": np.stack([e["arr"] for e in group]),
            "ids": np.array([e["id"] for e in group]),
        }
    return out


def solve_row(target, groups, cols, usage, reuse_w, repeat_w, prev_row):
    """Cheapest partition of one row into formulas. Returns [(col, entry)]."""
    cost = np.full(cols + 1, math.inf)
    pick = [None] * (cols + 1)
    cost[cols] = 0.0

    reuse = {u: reuse_w * np.array([usage.get(i, 0) for i in g["ids"]], dtype=float)
             for u, g in groups.items()}

    for c in range(cols - 1, -1, -1):
        room = cols - c
        best, best_e = math.inf, None
        for units, g in groups.items():
            span = min(units, room)
            rest = cost[c + span]
            if not math.isfinite(rest):
                continue
            tgt = target[:, c : c + span]
            d = ((g["sig"][:, :, :span] - tgt) ** 2).mean(axis=(1, 2)) + reuse[units]
            if prev_row is not None and prev_row[c] is not None:
                # The row above, at this column: the same formula stacked reads
                # as a column of duplicates even though neither row repeats.
                d = d + repeat_w * (g["ids"] == prev_row[c])
            k = int(d.argmin())
            v = d[k] + rest
            if v < best:
                best, best_e = v, g["entries"][k]
        cost[c], pick[c] = best, best_e

    out, c = [], 0
    while c < cols and pick[c] is not None:
        e = pick[c]
        out.append((c, e))
        c += min(e["units"], cols - c)
    return out


def flat_target(rows, bands, cols, level, wobble, seed=7):
    """A target with no picture in it — one even tone, gently disturbed.

    For a field that is going to move, the picture must not be in the field.
    Density that encodes an image and then slides across the hero drags a ghost
    of that image with it, and two copies of the campus at different offsets
    read as a double exposure rather than as one photograph. So the moving layer
    is asked for an even tone and carries only the things that make the
    technique visible — the mixture of sizes, the weight ladder, the tight
    partition of every row — while the picture is left to the fixed layer
    underneath it.

    The wobble is what keeps it from degenerating: an exactly flat target has
    one cheapest answer and the solver will use it everywhere.
    """
    rng = np.random.default_rng(seed)
    base = np.full((rows, bands, cols), float(level))
    return np.clip(base + rng.normal(0.0, wobble, base.shape), 0.0, 1.0)


def main(source, out_path, width, height, gamma, reuse_w, repeat_w, lo_pct, hi_pct, colour,
         diffuse, flat, wobble, standalone, tint, tint_boost, flatten, tint_lift, invert):
    if flat is None and not source:
        sys.exit("give an image, or --flat TONE for a field with no picture in it")
    lut = json.loads(LUT.read_text(encoding="utf-8"))
    cell, row_h, bands = lut["cell"], lut["row_h"], lut["bands"]
    scale = lut["scale"]
    paths = load_paths()

    cols = max(1, width // cell)
    rows = max(1, height // row_h)
    width, height = cols * cell, rows * row_h

    entries = [e for e in lut["entries"] if e["id"] in paths]
    if not entries:
        sys.exit("no formulas in common between the table and the sprite — re-run prep-formulas.py")
    for e in entries:
        e["arr"] = np.asarray(e["sig"], dtype=np.float64)

    pool = np.concatenate([e["arr"].ravel() for e in entries])
    # With the fills taking the photograph's own colour, density no longer has
    # to carry the tone by itself — and it should not, because the two together
    # double it and the shadows close up. Pulling the density target towards its
    # own mean keeps formulas everywhere and lets the colour say what is dark.
    if flat is not None:
        target = flat_target(rows, bands, cols, flat, wobble)
    else:
        target = picture(source, cols, rows, cell, row_h, bands, gamma, lo_pct, hi_pct)

    # On white paper the sense of the picture reverses: ink is what makes a
    # thing dark, so the density has to follow the photograph's shadows rather
    # than its highlights. Everything downstream is unchanged — only what the
    # solver is asked for.
    if invert:
        target = 1.0 - target

    if flatten > 0:
        target = target.mean() + (target - target.mean()) * (1.0 - flatten)

    # Then the picture is pushed through the set's own distribution of ink.
    # Linear stretching is not enough and the difference is stark: formulas are
    # mostly whitespace, so their coverages pile up near zero, while a stretched
    # photograph is spread evenly across its range. Ask for tones two thirds of
    # the way up that range and nothing can supply them, so every light area
    # saturates onto the same few heaviest formulas and the picture's whole
    # subject — a white building against a grey sky — flattens into one tone.
    # Matching the histograms asks only for tones the set can actually make,
    # and because the mapping is monotone it costs no contrast: what was
    # lighter stays lighter.
    order = np.sort(pool)
    target = np.interp(target, np.linspace(0.0, 1.0, len(order)), order)

    # Common scale for the comparison, now that both sides live on the same
    # distribution — and this matters more than it looks. Coverage differences
    # between two formulas are in the hundredths, so squared they are in the
    # ten-thousandths: leave them there and the reuse and repetition penalties
    # are an order of magnitude larger than the picture, and the result is a
    # nicely varied field of formulas resembling nothing at all. Percentiles
    # rather than the extremes, so one outlier tile does not compress the rest
    # into the middle.
    sig_lo, sig_hi = np.percentile(pool, [1, 99])
    span = max(sig_hi - sig_lo, 1e-6)
    for e in entries:
        e["arr"] = np.clip((e["arr"] - sig_lo) / span, 0.0, 1.0)
    target = np.clip((target - sig_lo) / span, 0.0, 1.0)

    groups = group_by_width(entries)
    tints = None
    if tint > 0 and source:
        tints = tint_map(source, cols, rows, cell, row_h, colour if colour.startswith("#") else "#ffffff",
                         tint, tint_boost, tint_lift)

    usage, uses = {}, []
    prev_row = None
    placed = 0
    # What one row could not say, the next one is asked to say instead. A
    # formula covers a dozen cells at once, so a row can only ever approximate
    # its strip — and left alone those approximations are biased the same way
    # everywhere, which is what turns a gradient into a flat band. Carrying the
    # shortfall downward is the same trick that makes dithering work: the error
    # is not removed, it is spread until it falls below what the eye resolves.
    carry = np.zeros((bands, cols))
    for r in range(rows):
        want = np.clip(target[r] + carry, 0.0, 1.0)
        row = solve_row(want, groups, cols, usage, reuse_w, repeat_w, prev_row)
        got = np.zeros((bands, cols))
        for c, e in row:
            n = min(e["units"], cols - c)
            got[:, c : c + n] = e["arr"][:, :n]
        # Capped: an area the set simply cannot reach would otherwise build up
        # a debt it never pays off, and drag every row beneath it dark.
        carry = np.clip((want - got) * diffuse, -0.3, 0.3)
        row_ids = [None] * cols
        for c, e in row:
            usage[e["id"]] = usage.get(e["id"], 0) + 1
            for k in range(c, min(c + e["units"], cols)):
                row_ids[k] = e["id"]
            # Scaled uniformly so the span is exact; the rounding to whole cells
            # is at most half a cell on a formula many cells wide, so the glyph
            # size stays within a few percent across the whole picture.
            span_px = min(e["units"], cols - c) * cell
            w_px = e["units"] * cell
            h_px = e["h"] * scale * (w_px / (e["w"] * scale))
            uses.append(
                (
                    e["id"],
                    c * cell,
                    r * row_h + (row_h - h_px) / 2,
                    w_px,
                    h_px,
                    # Symbol units, not pixels: stroke-width on a <use> is read
                    # in the symbol's own coordinate system and then scaled by
                    # the viewBox transform, so converting it to pixels here
                    # scaled it twice and every weight rendered at about a sixth
                    # of its width. The sprite stores coordinates at a finer
                    # precision than the table measures in, so the width is
                    # taken from the viewBox rather than assumed.
                    e["stroke"] * (float(paths[e["id"]][1].split()[2]) / e["w"]),
                    span_px,
                    None if tints is None else "#%02x%02x%02x" % tuple(
                        tints[r, min(c + e["units"] // 2, cols - 1)]),
                )
            )
            placed += 1
        prev_row = row_ids

    if standalone:
        # One <path> per placement, transform baked in, no <defs> and no <use>.
        # Illustrator and most drawing programs will open a <use> tree, but they
        # expand it into linked copies that are awkward to select and to outline,
        # and some drop the stroke-width that the <use> carried. Written out
        # flat, every formula arrives as an ordinary path with its own stroke —
        # which is what you need if you are going to edit it by hand. The file
        # is several times larger; that does not matter for a working file.
        parts = []
        for i, x, y, w, h, sw, _, _ in uses:
            d, vb = paths[i]
            vb_w, vb_h = float(vb.split()[2]), float(vb.split()[3])
            k = w / vb_w  # the symbol's units are finer than a pixel; see prep-formulas.py
            stroke = f' stroke-width="{sw:.3f}"' if sw > 0.005 else ' stroke="none"'
            paint = f' fill="{tc}" stroke="{tc}"' if tc else ""
            parts.append(
                f'<path transform="translate({x:.1f} {y:.1f}) scale({k:.5f})" d="{d}"{stroke}{paint}/>'
            )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}">'
            f'<g fill="{colour}" stroke="{colour}" stroke-linejoin="round" stroke-linecap="round">'
            + "".join(parts)
            + "</g></svg>"
        )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(svg, encoding="utf-8")
        print(f"  {len(parts)} paths, flattened for hand editing")
        print(f"  -> {out_path} ({out_path.stat().st_size // 1024} KB)")
        return

    used_ids = sorted({u[0] for u in uses}, key=lambda s: int(s[2:]))
    defs = "".join(
        f'<symbol id="{i}" viewBox="{paths[i][1]}" overflow="visible"><path d="{paths[i][0]}"/></symbol>'
        for i in used_ids
    )
    body = "".join(
        f'<use href="#{i}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}"'
        + (f' stroke-width="{sw:.2f}"' if sw > 0.005 else "")
        # Its own colour, sampled from the picture where it stands. A solid fill
        # on a path, so the sheet is still vector and the photograph's own
        # resolution never enters into it.
        + (f' fill="{tc}" stroke="{tc}"' if tc else "")
        + "/>"
        for i, x, y, w, h, sw, _, tc in uses
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-hidden="true" '
        # Cover, not stretch — the same thing the hero's photograph does. A
        # background is asked to fill boxes of every shape, and squashing the
        # picture also squashes the glyphs out of proportion.
        f'preserveAspectRatio="xMidYMid slice">'
        f"<defs>{defs}</defs>"
        f'<g fill="{colour}" stroke="{colour}" stroke-linejoin="round" stroke-linecap="round">'
        f"{body}</g></svg>"
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")

    spread = sorted(usage.values(), reverse=True)
    print(f"  {width}x{height}px, {cols}x{rows} cells, {placed} formulas placed")
    print(f"  {len(used_ids)} of {len(paths)} distinct formulas used; "
          f"the most-used appears {spread[0]} times, the median {spread[len(spread) // 2]}")
    print(f"  signatures normalised over {sig_lo:.3f}-{sig_hi:.3f} coverage")
    print(f"  -> {out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path} "
          f"({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="image to spell out; omit with --flat")
    ap.add_argument("-o", "--out", default="static/hero-art.svg")
    ap.add_argument("--width", type=int, default=1800)
    ap.add_argument("--height", type=int, default=620)
    ap.add_argument("--gamma", type=float, default=1.0, help=">1 darkens the midtones, <1 lifts them")
    ap.add_argument("--lo", type=float, default=2.0, help="black point percentile")
    ap.add_argument("--hi", type=float, default=98.0, help="white point percentile")
    ap.add_argument("--reuse", type=float, default=0.0006, help="cost per previous use of a formula")
    ap.add_argument("--repeat", type=float, default=0.02, help="cost for the formula directly above")
    ap.add_argument("--diffuse", type=float, default=0.55,
                    help="how much of a row's shortfall is carried into the next (0 disables)")
    ap.add_argument("--flat", type=float, default=None, metavar="TONE",
                    help="no picture: fill with one even tone in 0-1, for a field meant to move")
    ap.add_argument("--wobble", type=float, default=0.12,
                    help="disturbance on a flat target, so the solver does not repeat one answer")
    ap.add_argument("--standalone", action="store_true",
                    help="flat <path> per formula, no <use> — for Illustrator and the like")
    ap.add_argument("--flatten", type=float, default=0.0, metavar="0-1",
                    help="even out the density, for when colour is carrying the tone")
    ap.add_argument("--tint", type=float, default=0.0, metavar="0-1",
                    help="pull each formula towards the picture's own colour there")
    ap.add_argument("--tint-boost", type=float, default=1.0,
                    help="saturation applied before tinting; 1 leaves the photograph alone")
    ap.add_argument("--tint-lift", type=float, default=0.0, metavar="0-1",
                    help="how much of the fill's brightness comes from the ink rather than the photo")
    ap.add_argument("--invert", action="store_true",
                    help="ink follows the shadows, for a light ground")
    ap.add_argument("--colour", default="currentColor")
    args = ap.parse_args()
    main(args.source, args.out, args.width, args.height, args.gamma,
         args.reuse, args.repeat, args.lo, args.hi, args.colour, args.diffuse,
         args.flat, args.wobble, args.standalone, args.tint, args.tint_boost, args.flatten,
         args.tint_lift, args.invert)
