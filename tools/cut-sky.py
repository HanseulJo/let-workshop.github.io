#!/usr/bin/env python3
"""Cut the sky out of the campus photograph, leaving the buildings.

    python3 tools/cut-sky.py ~/Downloads/postech.jpg -o static/campus-cut.png

Writes a PNG with an alpha channel: everything that is sky is transparent, so
the buildings can be set on any ground the poster happens to have.

How it decides. Sky here is two things at once — blue where it is open and
white where it is cloud — and the building is a light warm grey that a
brightness threshold alone would take with it. Two tests are used instead:

  blue-ness   B - R, which is strongly positive for open sky, near zero for
              concrete, and negative for the warm stone of the facade
  luminance   for the cloud, which has no blue-ness left in it

and then the answer is restricted to the region connected to the top edge. That
last step is what keeps the pale plaza, the white car and the sunlit roof — all
of which pass the colour tests — because none of them touch the sky.

The edge is feathered by a pixel or so afterwards. A hard alpha edge on a
photograph reads as a cut-out even at poster size, and the halo of sky left in
the feather is darkened rather than left bright, so the fringe does not glow
against a dark ground.

Needs Pillow, NumPy and SciPy. Local tool only.
"""

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageFilter, ImageOps
    from scipy import ndimage as ndi
except ModuleNotFoundError as exc:  # pragma: no cover
    sys.exit(f"missing dependency '{exc.name}'\n  pip install pillow numpy scipy")


def sky_mask(rgb, blue_strong, blue_weak, bright, top_band, speck):
    """True where the pixel belongs to the sky.

    Neither test works alone, and the numbers say why. Sampled from this
    photograph: open sky at its deepest is B-R +146 but only luminance 150,
    which is darker than the plaza at 201; the building's upper floors are B-R
    +30, which is as blue as the pale sky above them. So one test catches the
    blue, and a second catches the cloud — which has no blue left in it but is
    brighter than anything on the ground.
    """
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b

    looks_like_sky = ((b - r) >= blue_strong) | (((b - r) >= blue_weak) & (lum >= bright))

    # Only what the sky can actually reach. The plaza is as bright as the cloud
    # and the roof is as pale as the haze; neither is joined to the top of the
    # frame, and that is the whole difference.
    h = rgb.shape[0]
    seeds = np.zeros(looks_like_sky.shape, bool)
    seeds[: max(1, int(h * top_band))] = True
    labels, n = ndi.label(looks_like_sky)
    if not n:
        return looks_like_sky
    keep = set(np.unique(labels[seeds & looks_like_sky]))
    keep.discard(0)
    mask = np.isin(labels, list(keep))

    # Close the small holes the cloud edges leave, then drop specks.
    mask = ndi.binary_closing(mask, np.ones((5, 5), bool))
    mask = ndi.binary_opening(mask, np.ones((3, 3), bool))

    # Cloud interiors that the darker edge of their own cloud cut off from the
    # rest of the sky are left behind as bright islands floating in it. Anything
    # small and entirely surrounded by sky is one of those: the subject reaches
    # the bottom of the frame, so it is never enclosed.
    holes, hn = ndi.label(~mask)
    if hn:
        border = set(np.unique(np.concatenate([holes[0], holes[-1], holes[:, 0], holes[:, -1]])))
        sizes = ndi.sum(~mask, holes, range(1, hn + 1))
        for i, size in enumerate(sizes, start=1):
            if i not in border and size <= speck:
                mask[holes == i] = True
    return mask


def main(source, out_path, blue_strong, blue_weak, bright, top_band, feather, keep_largest, speck):
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    rgb = np.asarray(im)
    mask = sky_mask(rgb, blue_strong, blue_weak, bright, top_band, speck)

    alpha = np.where(mask, 0, 255).astype(np.uint8)
    if keep_largest:
        # The subject is one connected mass; anything else that survived is a
        # scrap of foliage floating in the sky.
        labels, n = ndi.label(alpha > 0)
        if n > 1:
            sizes = ndi.sum(alpha > 0, labels, range(1, n + 1))
            alpha = np.where(labels == (int(np.argmax(sizes)) + 1), 255, 0).astype(np.uint8)

    a = Image.fromarray(alpha, "L")
    if feather > 0:
        a = a.filter(ImageFilter.GaussianBlur(feather))

    # Darken what is left of the sky inside the feather, so the fringe does not
    # glow when the cut-out is placed on something dark.
    edge = (np.asarray(a, np.float64) / 255.0)[:, :, None]
    inner = np.asarray(im.filter(ImageFilter.GaussianBlur(2)), np.float64)
    flat = rgb * edge + inner * (1 - edge) * 0.55
    out = Image.fromarray(np.clip(flat, 0, 255).astype(np.uint8), "RGB")
    out.putalpha(a)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path)
    cut = float((alpha == 0).mean())
    print(f"  sky removed: {cut * 100:.1f}% of the frame")
    print(f"  -> {out_path} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("-o", "--out", default="static/campus-cut.png")
    ap.add_argument("--blue-strong", type=int, default=60,
                    help="B-R above which a pixel is open sky whatever its brightness")
    ap.add_argument("--speck", type=int, default=9000,
                    help="largest island of sky-locked cloud to absorb, in pixels")
    ap.add_argument("--blue-weak", type=int, default=0,
                    help="B-R a bright pixel needs to count as cloud")
    ap.add_argument("--bright", type=int, default=172, help="luminance at which cloud counts as sky")
    ap.add_argument("--top", type=float, default=0.06, help="fraction of the frame seeded as sky")
    ap.add_argument("--feather", type=float, default=1.1, help="softening of the cut, in pixels")
    ap.add_argument("--keep-largest", action="store_true", help="keep only the main mass")
    args = ap.parse_args()
    main(args.source, args.out, args.blue_strong, args.blue_weak, args.bright, args.top,
         args.feather, args.keep_largest, args.speck)
