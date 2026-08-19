#!/usr/bin/env python3
"""Normalise an institution logo, in the two sizes the page shows it at.

    python3 tools/prep-logo.py ~/Downloads/some-logo.png postech

Writes static/logos/<slug>.webp and <slug>-sm.webp: near-white knocked out to
transparent, empty margins trimmed, and scaled to a common cap height so logos
of different proportions sit on the same optical baseline beside each other.

Two sizes because the page shows them at two. The sponsors section
draws them at 44px, so it wants 132; the hero draws them at 22 beside the
buttons, and 132 there would be six times what is on screen — and that one is
above the fold, where a logo is decoration and the bytes are not.

WebP rather than PNG. These are flat wordmarks with a soft gradient in one of
them, and PNG spends most of its size on the gradient: the pair comes to 99KB
as PNG and 59KB as WebP at the same dimensions, with nothing to see between
them at 44px.

Knocking out the white matters — a logo saved on an opaque white background
reads as a pale rectangle, which is what gives a sponsor row that "pasted on"
look. A source that already has an alpha channel keeps it; the knockout only
ever removes what is already white. Needs Pillow, local tooling only; the site
build never touches images.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 3x what each is drawn at, so both stay crisp on a phone.
HEIGHTS = {"": 132, "-sm": 66}
WHITE_CUTOFF = 238  # anything lighter than this in all channels becomes clear
OUT = Path(__file__).resolve().parent.parent / "static" / "logos"


def knockout_white(im: Image.Image) -> Image.Image:
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and r >= WHITE_CUTOFF and g >= WHITE_CUTOFF and b >= WHITE_CUTOFF:
                px[x, y] = (r, g, b, 0)
    return im


def rasterise(svg: Path) -> Path:
    """An SVG through Chrome, at a size the largest output can be cut from.

    Marks arrive as vector as often as not, and PIL does not read SVG. Rendered
    four times the tallest size this writes, so the crop and the two resizes
    downsample rather than guess.
    """
    box = re.search(r'viewBox="[\d.\s-]*?([\d.]+)\s+([\d.]+)"', svg.read_text(encoding="utf-8"))
    ratio = float(box.group(1)) / float(box.group(2)) if box else 3.0
    height = max(HEIGHTS.values()) * 4
    width = round(height * ratio)
    tmp = Path(tempfile.mkdtemp())
    (tmp / svg.name).write_bytes(svg.read_bytes())
    (tmp / "page.html").write_text(
        "<style>html,body{margin:0;background:transparent}"
        f"img{{display:block;width:{width}px;height:{height}px}}</style>"
        f'<img src="{svg.name}">', encoding="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "http.server", "8987"], cwd=tmp,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time
        time.sleep(1.5)
        shot = tmp / "shot.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000",
                        f"--window-size={width},{height}", "--virtual-time-budget=20000",
                        f"--screenshot={shot}", "http://localhost:8987/page.html"],
                       capture_output=True, timeout=120)
    finally:
        server.terminate()
    if not shot.exists():
        sys.exit(f"could not render {svg}")
    return shot


def main(source: str, slug: str) -> None:
    src = Path(source)
    if src.suffix.lower() == ".svg":
        src = rasterise(src)
    im = knockout_white(Image.open(src).convert("RGBA"))

    box = im.getbbox()  # bbox of the non-transparent pixels
    if box:
        im = im.crop(box)

    OUT.mkdir(parents=True, exist_ok=True)
    w, h = im.size
    for suffix, height in HEIGHTS.items():
        one = im.resize((round(w * height / h), height), Image.LANCZOS)
        out = OUT / f"{slug}{suffix}.webp"
        one.save(out, "WEBP", quality=90, method=6)
        print(f"{source} -> {out.relative_to(OUT.parent.parent)}  {one.size}  "
              f"({out.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
