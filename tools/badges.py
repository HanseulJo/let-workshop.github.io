#!/usr/bin/env python3
"""Print a name badge for everyone on the roster, in Python.

    python3 tools/badges.py
    python3 tools/badges.py --sort name --blanks 12

Writes, into --out (default ~/Downloads/let-badges):

    let-2026-badges.pdf     one card per page, 90 x 130mm, vector
    roster.txt              who is on which card, for the desk

Why this draws the cards itself rather than going through poster.py. That route
lays a card out in CSS and photographs it, which is right for one sheet of
twenty-one: the badge is then the same document as the poster and cannot drift
from it. It stops being right at a hundred and nine. The sheet becomes 53,000
CSS pixels tall — past what Chrome will rasterise in one screenshot, and its
print-to-pdf gives up on the page entirely — so it has to be cut into chunks,
rendered seven times, and stitched back, and what comes out is a 16MB bag of
photographs of text. Here the text is text: the file is a tenth of the size,
every name is selectable and searchable, and a card can be reprinted for
someone who arrives late without rendering anything else.

The price is that this is a second description of the same design. It is kept
honest where it can be: the colours are imported from poster.py rather than
copied, so a change to the scheme reaches both, and the roles come from
tools/roster.py, which is also what poster.py uses.

Needs reportlab and segno.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster as roster_mod                                    # noqa: E402
from poster import PALETTE, SCHEMES                            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "static" / "fonts"

# A lanyard insert. 90 x 130mm is the usual holder; the card is read across a
# handshake, which is about a metre.
W_MM, H_MM = 90.0, 130.0
MARGIN = 9.0

# Korean is not in Jost or Satoshi. The page does not pick a Korean face for
# it either — style.css says so: "Korean has no coverage in Inter, so Hangul
# falls through to the platform's UI face and keeps its own metrics." So the
# badge falls through to the same one and to nothing else. A second candidate
# here would be a different Korean face on the cards than on the screen, which
# is a change of typeface dressed up as a fallback.
CJK = ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 0)


def palette(scheme="light"):
    p = dict(PALETTE)
    p.update(SCHEMES.get(scheme, {}))
    return p


def rgb(hex_or_none):
    from reportlab.lib.colors import HexColor
    return HexColor(hex_or_none)


def cjk_as_truetype(path, index, tmp):
    """The same face, with its curves rewritten as quadratics.

    Apple SD Gothic Neo is a .ttc of PostScript outlines, and reportlab embeds
    TrueType only — so it is converted rather than replaced. Cubic Béziers
    become quadratics, which is what every OpenType-to-TrueType conversion
    does; the error is bounded at a thousandth of an em and nothing at badge
    size can show it. The typeface on the card is still the typeface on the
    screen, which is the point: the page does not choose a Korean font either,
    it falls through to this one.

    Note for whoever sends this to a printer: the PDF now carries a subset of
    a system font. That is fine for a file printed in-house and worth checking
    before it is published anywhere.
    """
    from fontTools.ttLib import TTFont as FTFont
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    out = tmp / "cjk-truetype.ttf"
    if out.exists():
        return out
    f = FTFont(path, fontNumber=index)
    if "glyf" in f:                       # already TrueType on some systems
        f.save(str(out)); return out

    glyphs = f.getGlyphSet()
    pen_glyphs = {}
    for name in f.getGlyphOrder():
        pen = TTGlyphPen(pen_glyphs)
        glyphs[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        pen_glyphs[name] = pen.glyph()

    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables._g_l_y_f import table__g_l_y_f
    glyf = table__g_l_y_f()
    glyf.glyphs = pen_glyphs
    glyf.glyphOrder = f.getGlyphOrder()
    f["glyf"] = glyf
    # glyf compiles into loca, but only if there is a loca to compile into.
    # Without this the file saves happily and reportlab rejects it for a
    # missing location table — the failure is one table away from the cause.
    f["loca"] = newTable("loca")
    # A TrueType font is described by tables a CFF one does not carry, and is
    # not allowed to carry the ones it does.
    f["head"].indexToLocFormat = 0
    f["maxp"].tableVersion = 0x00010000
    f["maxp"].maxZones = 1
    for attr in ("maxTwilightPoints", "maxStorage", "maxFunctionDefs",
                 "maxInstructionDefs", "maxStackElements",
                 "maxSizeOfInstructions", "maxComponentElements",
                 "maxComponentDepth"):
        setattr(f["maxp"], attr, 0)
    f["maxp"].maxComponentDepth = 1
    for tag in ("CFF ", "CFF2", "VORG"):
        if tag in f:
            del f[tag]
    f.sfntVersion = "\x00\x01\x00\x00"
    f.save(str(out))
    return out


def register_fonts(WORK):
    """Our faces, unpacked from the woff2 the site serves, plus a CJK fallback.

    woff2 is a compressed wrapper around the same outlines reportlab wants, so
    fontTools unwraps rather than converts: the glyphs are untouched and the
    badge is set in the face the poster is set in, not in an approximation of
    it fetched from somewhere else.
    """
    from fontTools.ttLib import TTFont
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as RLFont

    wanted = {
        "Jost-Bold": "jost-latin.woff2",          # the mark
        "Mono": "jetbrains-mono-latin.woff2",     # field names and dates
        "Sans": "satoshi-500.woff2",              # affiliation
        "Sans-Bold": "satoshi-700.woff2",         # the name
    }
    tmp = Path(WORK); tmp.mkdir(parents=True, exist_ok=True)
    got = {}
    for name, filename in wanted.items():
        src = FONTS / filename
        if not src.exists():
            continue
        ttf = tmp / (src.stem + ".ttf")
        if not ttf.exists():
            f = TTFont(str(src))                  # fontTools reads woff2 directly
            f.flavor = None
            f.save(str(ttf))
        pdfmetrics.registerFont(RLFont(name, str(ttf)))
        got[name] = True

    path, index = CJK
    if not Path(path).exists():
        sys.exit(f"the platform's Korean face is not at {path} — see CJK in this file")
    pdfmetrics.registerFont(RLFont("CJK", str(cjk_as_truetype(path, index, tmp))))
    return got, path


def qr_matrix(url):
    """The code as a grid of booleans, drawn later as vector squares.

    Error correction H, the same as every other piece: a badge is handled, and
    a code that survives a thumbprint is worth the extra modules.
    """
    import segno
    code = segno.make(url, error="h")
    return [[bool(c) for c in row] for row in code.matrix]


def draw_card(c, p, person, site, cjk):
    """One badge, in millimetres from the bottom-left as reportlab counts."""
    from reportlab.lib.units import mm

    hot = person["role"] in roster_mod.HOT
    ink, accent, cool = p["ink"], p["hot"], p["cool"]
    name_font = "Sans-Bold"
    ko_font = "CJK" if cjk else "Sans"

    c.setFillColor(rgb(p["ground"]))
    c.rect(0, 0, W_MM * mm, H_MM * mm, stroke=0, fill=1)

    x = MARGIN * mm
    inner = (W_MM - 2 * MARGIN) * mm

    # --- the mark, top left ------------------------------------------------
    mark, year = (site["name"].rsplit(" ", 1) + [""])[:2]
    top = (H_MM - MARGIN - 6.4) * mm
    c.setFillColor(rgb(accent))
    c.setFont("Jost-Bold", 8.6 * mm)
    c.drawString(x, top, mark)
    wmark = c.stringWidth(mark, "Jost-Bold", 8.6 * mm)
    c.setFont("Jost-Bold", 8.6 * mm)
    c.setFillColor(rgb(accent))
    c.drawString(x + wmark + 1.8 * mm, top, year)

    # when and where, ranged right against the mark's own line
    c.setFillColor(rgb(cool))
    c.setFont("Mono", 2.5 * mm)
    for i, line in enumerate((f'OCT {site["dates"].split()[1].rstrip(",")}, {site["year"]}',
                              f'{site["venue"]}, {site["city"]}'.upper())):
        c.drawRightString(x + inner, top + (2.4 - i * 3.4) * mm, line)

    # --- the role, and who ---------------------------------------------------
    chip_y = (H_MM - MARGIN - 27) * mm
    label = person["role"].upper()
    c.setFont("Mono", 2.7 * mm)
    tw = c.stringWidth(label, "Mono", 2.7 * mm)
    c.setStrokeColor(rgb(accent if hot else cool))
    c.setFillColor(rgb(p["ground"]))
    c.setLineWidth(0.3 * mm)
    c.roundRect(x, chip_y, tw + 6 * mm, 7 * mm, 3.5 * mm, stroke=1, fill=0)
    c.setFillColor(rgb(accent if hot else cool))
    c.drawString(x + 3 * mm, chip_y + 2.4 * mm, label)

    if person["name"]:
        # The name is the whole point of the card, so it takes whatever size
        # fits the width rather than a size chosen in advance and hoped for.
        size, name = 11.0 * mm, person["name"]
        has_cjk = any(ord(ch) > 0x2E80 for ch in name)
        font = ko_font if has_cjk else name_font
        while size > 5 * mm and c.stringWidth(name, font, size) > inner:
            size -= 0.25 * mm
        c.setFillColor(rgb(ink))
        c.setFont(font, size)
        y = (H_MM - MARGIN - 45) * mm
        c.drawString(x, y, name)

        if person["name_ko"]:
            c.setFont(ko_font, 5.4 * mm)
            c.setFillColor(rgb(cool))
            y -= 8.5 * mm
            c.drawString(x, y, person["name_ko"])

        if person["affil"]:
            affil, size = person["affil"], 4.6 * mm
            font = ko_font if any(ord(ch) > 0x2E80 for ch in affil) else "Sans"
            while size > 2.6 * mm and c.stringWidth(affil, font, size) > inner:
                size -= 0.15 * mm
            c.setFont(font, size)
            c.setFillColor(rgb(ink))
            c.drawString(x, y - 10 * mm, affil)
    else:
        # Two rules to write on. A blank badge with a pen beats no badge.
        c.setStrokeColor(rgb(cool))
        c.setLineWidth(0.25 * mm)
        for k in range(2):
            yy = (H_MM - MARGIN - 50 - k * 12) * mm
            c.line(x, yy, x + inner, yy)

    # --- the foot -------------------------------------------------------------
    foot = (MARGIN + 20) * mm
    c.setStrokeColor(rgb(cool))
    c.setLineWidth(0.15 * mm)
    c.line(x, foot, x + inner, foot)

    c.setFillColor(rgb(cool))
    c.setFont("Mono", 2.4 * mm)
    c.drawString(x, foot - 6 * mm, site["full_name"].upper())

    grid = qr_matrix(site["url"])
    side = 16.0 * mm
    cell = side / len(grid)
    qx, qy = x + inner - side, MARGIN * mm
    c.setFillColor(rgb(p["ground2"] if hot else ink))
    for r, row in enumerate(grid):
        for cidx, on in enumerate(row):
            if on:
                c.rect(qx + cidx * cell, qy + side - (r + 1) * cell,
                       cell, cell, stroke=0, fill=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roster", default=str(ROOT / "data/roster.tsv"))
    ap.add_argument("--scheme", default="light", choices=sorted(SCHEMES) + ["dark"])
    ap.add_argument("--sort", choices=("role", "name"), default="role")
    ap.add_argument("--blanks", type=int, default=6)
    ap.add_argument("--out", default=str(Path.home() / "Downloads/let-badges"))
    args = ap.parse_args()

    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError:
        sys.exit("needs reportlab:  pip install reportlab segno")

    import yaml
    site = yaml.safe_load((ROOT / "data/site.yml").read_text(encoding="utf-8"))
    p = palette(args.scheme if args.scheme != "dark" else None)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    got, cjk = register_fonts(out / "_fonts")
    missing = {"Jost-Bold", "Mono", "Sans", "Sans-Bold"} - set(got)
    if missing:
        sys.exit(f"missing fonts in static/fonts: {', '.join(sorted(missing))}")
    if not cjk:
        print("  no Korean face found — Korean names will not draw", file=sys.stderr)

    people = roster_mod.ordered(roster_mod.read(args.roster), args.sort)
    cards = list(people) + [{"role": "Attendee", "name": "", "name_ko": "",
                             "affil": "", "email": ""} for _ in range(args.blanks)]

    pdf = out / "let-2026-badges.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(W_MM * mm, H_MM * mm))
    c.setTitle("LeT Workshop 2026 — name badges")
    for person in cards:
        draw_card(c, p, person, site, cjk)
        c.showPage()
    c.save()

    lines = [f'{i:3d}  {q["role"]:9} {q["name"]}'
             + (f'  ({q["name_ko"]})' if q["name_ko"] else "")
             + (f'  — {q["affil"]}' if q["affil"] else "")
             for i, q in enumerate(people, 1)]
    (out / "roster.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  {len(cards)} cards -> {pdf}  ({pdf.stat().st_size / 1e6:.1f}MB)")
    for r in roster_mod.ROLES:
        print(f"    {r:9} {sum(1 for q in people if q['role'] == r):3d}")
    print(f"    {'blank':9} {args.blanks:3d}")


if __name__ == "__main__":
    main()
