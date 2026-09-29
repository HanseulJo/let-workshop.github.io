#!/usr/bin/env python3
"""Print a name badge for everyone on the roster.

    python3 tools/badges.py --art art/badge-light.svg
    python3 tools/badges.py --art art/badge-light.svg --sort name --blanks 12

Writes, into --out (default ~/Downloads/let-badges):

    let-2026-badges.pdf     one card per page, 90 x 130mm
    roster.txt              who is on which card, for the desk

The card is the one in poster.py's BADGE layout and nothing else — same formula
drawing, same photograph behind it, same veil, same type at the same sizes, the
name above centre because a lanyard curls forward at the bottom. This script
changes whose names are on it and gets a PDF out. There is no second
description of the card here that could drift from the first, which is the
whole reason it is done this way round rather than redrawn.

Two things have to be handled to get from that page to a printable file.

A hundred and nine cards is 53,000 CSS pixels of document. Chrome's
print-to-pdf runs for two minutes on that and produces nothing at all, so the
roster is cut into chunks, each printed on its own, and the PDFs joined. The
seam is invisible: every card is the same template at the same size and nothing
spans two of them.

And the drawing has to be rasterised first. The badge puts it in a CSS
`background-image`, and Chrome re-embeds a vector background once per page — 20
cards came to 129MB, which is 700MB for the roster, at 35 seconds a chunk. The
same drawing as a PNG at 300 DPI is embedded once and shared: 1.2MB for 20
cards, in 4 seconds. It is a picture held at 34% opacity behind a name, and
nothing about it at that size is vector in any way anyone can see.

The four roles and how someone gets one are in tools/roster.py.
"""

import argparse
import base64
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster as roster_mod                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# 90 x 130mm at 300 DPI, which is what the drawing is rasterised at.
CARD_PX = (1063, 1535)
ART_RE = r'\.art \{ background-image:url\("([^"]+)"\)'


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"{Path(str(cmd[0])).name} failed:\n{(r.stderr or r.stdout)[-2000:]}")
    return r.stdout


def chrome(*args):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", *[str(a) for a in args]],
                   capture_output=True, text=True)


def rasterise_art(work, port, page):
    """The drawing as it is actually drawn, once, as a PNG.

    Taken out of the page rather than off disk. poster.py tints the artwork to
    whichever scheme was asked for before inlining it, so the file in art/ is
    not necessarily what the badge shows; the data URI in the page is.

    It comes out black with the picture in its alpha channel, which is correct
    and not a bug to chase: the SVG fills with `currentColor`, and a background
    image has no colour to inherit, so this is what the badge has always drawn.
    """
    png = work / "art.png"
    if png.exists():
        return png
    url = re.search(ART_RE, page.read_text()).group(1)
    svg = base64.b64decode(url.split(",", 1)[1]).decode("utf-8")
    (work / "art.svg").write_text(svg, encoding="utf-8")
    (work / "art.html").write_text(
        '<!doctype html><meta charset="utf-8">'
        "<style>html,body{margin:0;padding:0}"
        f"img{{display:block;width:{CARD_PX[0]}px;height:{CARD_PX[1]}px}}</style>"
        '<img src="art.svg">', encoding="utf-8")
    chrome("--hide-scrollbars", "--default-background-color=00000000",
           f"--window-size={CARD_PX[0]},{CARD_PX[1]}", "--virtual-time-budget=60000",
           f"--screenshot={png}", f"http://localhost:{port}/art.html")
    if not png.exists():
        sys.exit("  could not rasterise the drawing")
    return png


def with_raster_art(page, png):
    """The same page, with the vector background swapped for the raster one."""
    url = "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")
    out = page.with_name(page.stem + "-r.html")
    text, n = re.subn(ART_RE, '.art { background-image:url("%s")' % url,
                      page.read_text(), count=1)
    if not n:
        sys.exit("  the badge page has no .art background to replace")
    out.write_text(text, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", required=True, help="the badge-shaped formula art SVG")
    ap.add_argument("--ghost", default=str(ROOT / "art/campus.jpg"))
    ap.add_argument("--scheme", default="light")
    ap.add_argument("--roster", default=str(ROOT / "data/roster.tsv"))
    ap.add_argument("--sort", choices=("role", "name"), default="role")
    ap.add_argument("--blanks", type=int, default=6)
    ap.add_argument("--chunk", type=int, default=20,
                    help="cards per PDF before they are joined (default 20)")
    ap.add_argument("--out", default=str(Path.home() / "Downloads/let-badges"))
    ap.add_argument("--port", type=int, default=8996)
    args = ap.parse_args()

    from pypdf import PdfWriter

    if not Path(CHROME).exists():
        sys.exit(f"Chrome not at {CHROME}")
    people = roster_mod.ordered(roster_mod.read(args.roster), args.sort)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"; work.mkdir(exist_ok=True)
    (work / "fonts").mkdir(exist_ok=True)
    for f in (ROOT / "static/fonts").glob("*.woff2"):
        (work / "fonts" / f.name).write_bytes(f.read_bytes())

    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)],
                              cwd=work, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    pdfs, png = [], None
    try:
        time.sleep(2)
        batches = [people[i:i + args.chunk] for i in range(0, len(people), args.chunk)]
        if args.blanks:
            batches.append([])          # the spares, drawn by the same template
        for n, batch in enumerate(batches):
            blanks = args.blanks if not batch else 0
            tsv = work / f"chunk-{n}.tsv"
            roster_mod.write(tsv, batch)
            page = work / f"badges-{n}.html"
            run(sys.executable, ROOT / "tools/poster.py", "--art", args.art,
                "--ghost", args.ghost, "--layout", "badge", "--scheme", args.scheme,
                "--roster", tsv, "--roster-sort", "file",   # the order was chosen above
                "--roster-blanks", str(blanks), "-o", page, cwd=ROOT)
            png = png or rasterise_art(work, args.port, page)
            page = with_raster_art(page, png)
            pdf = work / f"badges-{n}.pdf"
            pdf.unlink(missing_ok=True)
            chrome("--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                   "--virtual-time-budget=120000",
                   f"http://localhost:{args.port}/{page.name}")
            if not pdf.exists():
                sys.exit(f"  Chrome produced no PDF for chunk {n}")
            pdfs.append(pdf)
            print(f"  {len(batch) or blanks:3d} cards  ->  {pdf.name}")
    finally:
        server.terminate()

    merged = out / "let-2026-badges.pdf"
    writer = PdfWriter()
    for pdf in pdfs:
        writer.append(str(pdf))
    with merged.open("wb") as fh:
        writer.write(fh)

    lines = [f'{i:3d}  {p["role"]:9} {p["name"]}'
             + (f'  ({p["name_sub"]})' if p["name_sub"] else "")
             + (f'  — {p["affil"]}' if p["affil"] else "")
             for i, p in enumerate(people, 1)]
    (out / "roster.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n  {len(writer.pages)} pages -> {merged}"
          f"  ({merged.stat().st_size / 1e6:.1f}MB)")
    for r in roster_mod.ROLES:
        print(f"    {r:9} {sum(1 for p in people if p['role'] == r):3d}")
    print(f"    {'blank':9} {args.blanks:3d}")


if __name__ == "__main__":
    main()
