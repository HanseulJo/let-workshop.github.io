#!/usr/bin/env python3
"""Make every published copy of the A2 sheet, from the sources it is made of.

    python3 tools/export-poster.py

Two sheets — the dark one and the light one — each written out as a PDF for
print, a 300dpi PNG, an editable SVG with live text, and the four sizes the
website shows and offers for download. Nothing to remember and nothing to type,
which is the whole point of it.

Why this exists. Every part of the sheet already came from data/ — a speaker
withdraws, a room changes, and poster.py picks it up. What did not come from
anywhere was the command: which artwork, which photograph, which palette, at
what scale, cropped by how much. That lived in a shell history, so each time
the sheet needed re-exporting it was reconstructed from memory, and twice it
was not re-exported at all — the code changed, the pictures on the site did
not, and the sheet quietly disagreed with the page for a week. Once, poster.py
had stopped running altogether: a key the travel card no longer wrote, which
would have been a crash on the first line of an export nobody ran.

    art/a2-dark.svg    the campus written in formulas, light ink
    art/a2-light.svg   the same drawing inverted, for ink on paper
    art/campus.jpg     the photograph the dark sheet is ghosted with

The light sheet takes its colours from poster.py's own `light` scheme rather
than from a palette spelled out here, so the two places that describe a pale
sheet cannot drift apart.

Needs Chrome and Pillow. Local tool only — the site build does not run this.
"""

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# What the sheet must be set in. Checked on the rendered page rather than taken
# on trust: a face that fails to load is not an error, it is a substitution,
# and a substitution looks like a poster right up until someone reads it.
FACES = ("Satoshi", "JetBrains Mono", "Jost", "Inter Tight")

FONT_PROBE = """<script>
document.fonts.ready.then(() => {
  const got = new Set([...document.fonts].filter(f => f.status === 'loaded')
                                         .map(f => f.family));
  const p = document.createElement('pre');
  p.id = '__fonts'; p.textContent = [...got].join('|');
  document.body.appendChild(p);
});
</script>"""

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = Path(__file__).resolve().parent.parent

# A2 and 3mm of bleed on every side, in CSS pixels at 96dpi. Chrome lays the
# page out at this size and the scale factor does the rest.
PAGE = (1610, 2268)
BLEED_MM, SHEET_MM = 3, (426, 600)
DPI300 = 3.125  # 96 * 3.125 = 300

SHEETS = [
    # name           artwork            extra poster.py arguments
    ("poster-2026", "art/a2-dark.svg", ["--ghost", "art/campus.jpg"]),
    ("poster-2026-light", "art/a2-light.svg", ["--scheme", "light",
                                               "--ghost", "art/campus.jpg"]),
]

PRINT_NAMES = {
    "poster-2026": ("kolt-2026-a2-festival", "poster"),
    "poster-2026-light": ("kolt-2026-a2-poster-light", "poster-light"),
}


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"{cmd[0]} failed:\n{r.stderr[-2000:]}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(Path.home() / "Downloads/kolt-poster-a2"),
                    help="where the print files go")
    ap.add_argument("--port", type=int, default=8992)
    ap.add_argument("--only", choices=[s[0] for s in SHEETS], help="just one sheet")
    args = ap.parse_args()

    try:
        from PIL import Image
    except ModuleNotFoundError:
        sys.exit("needs Pillow:  pip install pillow")

    work = ROOT / "_poster"
    work.mkdir(exist_ok=True)
    out = Path(args.out)
    sheets = [s for s in SHEETS if not args.only or s[0] == args.only]

    # The sheet asks for its faces by relative path, so they have to sit beside
    # it. A missing fonts/ is not an error anyone sees: Chrome falls back to a
    # system face, the export succeeds, and the poster is simply set in the
    # wrong type. It happened, so the files are copied and then checked.
    shutil.copytree(ROOT / "static/fonts", work / "fonts", dirs_exist_ok=True)

    for name, art, extra in sheets:
        print(f"  {name}")
        run(sys.executable, ROOT / "tools/poster.py", "--art", ROOT / art,
            *[str(ROOT / e) if e.startswith("art/") else e for e in extra],
            "--layout", "festival", "-o", work / f"{name}.html", cwd=ROOT)
        page = (work / f"{name}.html").read_text(encoding="utf-8")
        missing = sorted({u for u in re.findall(r'url\("((?!data:)[^"]+)"\)', page)
                          if not (work / u).exists()})
        if missing:
            sys.exit(f"  {name} asks for files that are not beside it:\n    "
                     + "\n    ".join(missing))

    # Two servers on the same directory. Chrome is told which port to use;
    # poster-svg.py has 8997 written into it and reaches for the page itself.
    servers = [subprocess.Popen([sys.executable, "-m", "http.server", str(p)], cwd=work,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
               for p in dict.fromkeys((args.port, 8997))]
    try:
        time.sleep(2)
        for name, _, _ in sheets:
            # The print names are the ones already handed to a printer and
            # written down in mail; the site's names are the ones already in
            # data/site.yml. Neither is worth renaming for the sake of the
            # other, so the pairing is simply stated.
            stem, folder = PRINT_NAMES[name]
            folder = out / folder
            folder.mkdir(parents=True, exist_ok=True)
            url = f"http://localhost:{args.port}/{name}.html"

            probe = work / f"{name}--fonts.html"
            probe.write_text((work / f"{name}.html").read_text(encoding="utf-8")
                             + FONT_PROBE, encoding="utf-8")
            dom = run(CHROME, "--headless=new", "--disable-gpu",
                      "--window-size=1610,2268", "--virtual-time-budget=40000",
                      "--dump-dom", f"http://localhost:{args.port}/{probe.name}")
            probe.unlink()
            m = re.search(r'<pre id="__fonts">(.*?)</pre>', dom, re.S)
            loaded = set(m.group(1).split("|")) if m else set()
            if not set(FACES) <= loaded:
                sys.exit(f"  {name} fell back to system type — did not load: "
                         + ", ".join(sorted(set(FACES) - loaded)))

            run(CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={folder / (stem + '.pdf')}",
                "--virtual-time-budget=60000", url)
            shot = folder / f"{stem}-300dpi.png"
            run(CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                f"--force-device-scale-factor={DPI300}",
                f"--window-size={PAGE[0]},{PAGE[1]}",
                "--virtual-time-budget=60000", f"--screenshot={shot}", url)
            shutil.copy(work / f"{name}.html", folder / f"{stem}-source.html")
            print(run(sys.executable, ROOT / "tools/poster-svg.py", work / f"{name}.html",
                      "-o", folder / f"{stem}.svg",
                      "--title", "KOLT 2026 — A2 poster").strip().splitlines()[-1])

            # The website's copies, trimmed to the sheet: the bleed is for a
            # guillotine, and on screen it is 3mm of ground past the edge of
            # the design.
            im = Image.open(shot).convert("RGB")
            w, h = im.size
            bx, by = round(w * BLEED_MM / SHEET_MM[0]), round(h * BLEED_MM / SHEET_MM[1])
            im = im.crop((bx, by, w - bx, h - by))
            wide = lambda px: im.resize((px, round(im.height * px / im.width)), Image.LANCZOS)
            st = ROOT / "static"
            wide(1200).save(st / f"{name}.png", optimize=True)
            wide(2800).save(st / f"{name}-large.png", optimize=True)
            wide(1200).save(st / f"{name}.webp", format="WEBP", quality=92, method=6)
            wide(1400).save(st / f"{name}-small.jpg", quality=88, optimize=True,
                            progressive=True)
            sizes = "  ".join(
                f"{p.name} {p.stat().st_size / 1e6:.1f}MB"
                for p in (st / f"{name}-large.png", st / f"{name}-small.jpg"))
            print(f"    {sizes}")
    finally:
        for s in servers:
            s.terminate()

    print(f"\n  print files in {out}, site copies in static/ — "
          f"run build.py to stamp them")


if __name__ == "__main__":
    main()
