#!/usr/bin/env python3
"""Lay out the A2 poster from the same data the site is built from.

    python3 tools/poster.py --art static/hero-art.svg -o /tmp/poster/poster.html

Writes one HTML file with the formula art inlined, ready for Chrome to print to
a vector PDF at 426 x 600 mm — A2 with 3 mm of bleed on every side.

Why generate it rather than draw it. The programme is the part of a poster that
changes: a speaker withdraws, a session moves, an affiliation is wrong. Reading
data/program.yml means the sheet cannot disagree with the website, and a new
version is one command rather than an afternoon of retyping into a layout.

The art is inlined rather than referenced. A CSS mask or a linked image is
rasterised on the way to PDF — measured, Chrome baked it at 863 px across a
426 mm sheet, about 51 dpi — while paths in the page stay paths.
"""

import argparse
import base64
import html
import io
import re
import sys
from pathlib import Path

try:
    import segno
    import yaml
    from PIL import Image, ImageEnhance, ImageOps
except ModuleNotFoundError as exc:  # pragma: no cover
    sys.exit(f"missing dependency '{exc.name}'\n  pip install pyyaml segno")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# The site's own palette: one cool family, near-white for the headline, the
# coral accent kept for labels. `art` is the colour baked into the formula SVG,
# and is deliberately a step below the headline — the field is enormous and at
# the headline's brightness it competes with the name.
PALETTE = {
    "ground": "#0f1826",
    "ground2": "#0b111c",
    "art_ink": "#b9cbe4",
    "ink": "#f5f5f7",
    "ink_dim": "#a8b8cd",
    "cool": "#93a2b8",
    "cool_dim": "#6d7f96",
    "hot": "#ff8a75",
    "gold": "#f2cda0",  # the warm line an academic sheet puts its dates in
    "band": "#0b1523",
    # The light-ground layouts. Ink on paper rather than light on a dark field,
    # which reverses what the artwork has to do — see formula-art.py --invert.
    "paper": "#f4f1ea",
    "paper2": "#ffffff",
    "carbon": "#1b1b1b",
    "carbon2": "#5a5a5a",
    "accent": "#e8503a",
    "sky": "#4ec3e0",
    "rule": "rgba(255,255,255,.18)",
    # The veil, as five stops down the sheet. It exists to hold a photograph
    # back from the type on a dark ground; a scheme that puts a flat field in
    # the sky and a plate under the campus wants far less of it, or the veil
    # simply repaints the whole sheet in the ground colour. Palette values, so
    # a scheme can set them without a second template.
    "veil1": ".72", "veil2": ".50", "veil3": ".62", "veil4": ".90", "veil5": ".985",
    # How strongly the formulas themselves are drawn. On the dark sheet they
    # are the picture and run at full strength; a scheme that also lays a solid
    # plate under the campus wants them quieter, or the two together bury the
    # title.
    "art_alpha": "1",
    "chip": "rgba(255,255,255,.34)",
}


def esc(s):
    return html.escape(str(s), quote=False)


def photo_svg(source, shadow, highlight, width, height, contrast=0.92):
    """The photograph itself, in two tones, wrapped so a layout can drop it in
    wherever it would have put the formulas.

    Same reduction the website's backdrop uses: luminance, stretched to its own
    range, then mapped onto a ramp between two colours of the sheet. A poster
    that is one ink wants its picture in that ink.

    It is wrapped in an SVG because every layout here places its artwork by
    inlining one — this way the plain-photograph variants need no separate code
    path, only a different file.

    One thing to know before printing it. The source is 1280px across; an A2
    sheet at 300 dpi wants about 5000. Enlarged that far the photograph is
    noticeably soft, which is the objection that made a vector picture worth
    building in the first place. At normal viewing distance for a poster it is
    acceptable; held at arm's length it is not.
    """
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    im = ImageOps.fit(im, (width, height), Image.LANCZOS, centering=(0.5, 0.45))
    grey = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=(1, 2))
    grey = ImageEnhance.Contrast(grey).enhance(contrast)
    a = tuple(int(shadow.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(highlight.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    ramp = []
    for ch in range(3):
        ramp += [round(a[ch] + (b[ch] - a[ch]) * (v / 255)) for v in range(256)]
    toned = grey.convert("RGB").point(ramp)
    buf = io.BytesIO()
    toned.save(buf, "JPEG", quality=88, optimize=True, progressive=True)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid slice">'
        f'<image x="0" y="0" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid slice" href="data:image/jpeg;base64,{data}"/></svg>'
    )


def logo_row(names, colour, height=54):
    """The host marks, recoloured to one flat tone and embedded.

    Logos arrive in their own brand colours, which on a sheet built from one
    ink is three palettes fighting. The alpha channel carries the shape, so the
    art is discarded and the silhouette refilled — that also sidesteps the
    reproduction rules both universities publish, which govern the mark in its
    own colours, not a monotone courtesy credit.
    """
    out = []
    for name in names:
        f = ROOT / "static" / "logos" / f"{name.lower()}.png"
        if not f.exists():
            continue
        im = ImageOps.exif_transpose(Image.open(f)).convert("RGBA")
        rgb = tuple(int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        flat = Image.new("RGBA", im.size, rgb + (0,))
        flat.putalpha(im.getchannel("A"))
        if im.height > height * 4:
            flat.thumbnail((im.width, height * 4), Image.LANCZOS)
        buf = io.BytesIO()
        flat.save(buf, "PNG", optimize=True)
        data = base64.b64encode(buf.getvalue()).decode("ascii")
        out.append(f'<img alt="{esc(name)}" src="data:image/png;base64,{data}">')
    return "".join(out)


def cutout_svg(source, shadow, highlight, width, height, contrast=0.95):
    """The buildings with the sky already gone, toned to the sheet's ink.

    Two differences from the plain photograph, and both matter. It keeps its
    alpha, so it is saved as a PNG rather than a JPEG — a JPEG would fill the
    sky back in with black. And it is fitted rather than cropped, aligned to
    the foot of its box: a cut-out has a silhouette, and cropping one throws
    away the part that makes it read as a building rather than as a texture.
    """
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGBA")
    im.thumbnail((width * 2, width * 2), Image.LANCZOS)
    rgb, alpha = im.convert("RGB"), im.getchannel("A")
    grey = ImageOps.autocontrast(ImageOps.grayscale(rgb), cutoff=(1, 2))
    grey = ImageEnhance.Contrast(grey).enhance(contrast)
    a = tuple(int(shadow.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(highlight.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    ramp = []
    for ch in range(3):
        ramp += [round(a[ch] + (b[ch] - a[ch]) * (v / 255)) for v in range(256)]
    toned = grey.convert("RGB").point(ramp)
    toned.putalpha(alpha)
    buf = io.BytesIO()
    toned.save(buf, "PNG", optimize=True)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    # The box keeps the container's proportion and the building is laid into it
    # at full width, standing on the bottom edge. Fitting it instead would put
    # it in the middle of a tall box with air above and below; slicing it would
    # crop the silhouette, which is the whole of what a cut-out has. Whatever
    # overflows the top is sky, and sky is transparent now.
    img_h = round(width * toned.height / toned.width)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" preserveAspectRatio="xMidYMax slice">'
        f'<image x="0" y="{height - img_h}" width="{width}" height="{img_h}" '
        f'href="data:image/png;base64,{data}"/></svg>'
    )


def acronym_html(full_name, mark):
    """The full name with the letters that make the acronym picked out.

    KOLT is spelled Korean workshop On Learning Theory — the lowercase w is not
    a slip, it is what makes the O of "On" the second letter. Setting the name
    in capitals, which is what the sheets were doing, throws that away: it
    becomes four words in caps and the acronym is a coincidence again. In mixed
    case with the four letters in the accent, the name shows its own working.
    """
    want = list(mark.upper())
    out = []
    for word in full_name.split():
        if want and word[:1].upper() == want[0]:
            out.append(f'<b>{esc(word[0])}</b>{esc(word[1:])}')
            want.pop(0)
        else:
            out.append(esc(word))
    return " ".join(out)


def qr_svg(url, dark, light=None):
    """The site address as an SVG QR, sized by CSS rather than by pixels.

    Error correction at H, the highest of the four levels: a poster gets rained
    on, taped over a corner and photographed at an angle, and H can lose almost
    a third of the symbol and still decode. It costs a denser grid, which at
    30 mm square is still far above what a phone camera needs.

    Drawn as vector so it prints at the press's own resolution — a QR is the one
    element on the sheet where a soft edge actually costs something, since the
    decoder is looking for hard transitions.
    """
    qr = segno.make(url, error="h")
    buf = io.BytesIO()  # segno writes bytes even for SVG
    qr.save(buf, kind="svg", xmldecl=False, svgns=True, dark=dark, light=light,
            border=2, unit="", svgclass=None, lineclass=None)
    svg = buf.getvalue().decode("utf-8")
    # segno writes fixed width/height and no viewBox, and an SVG without a
    # viewBox does not scale — asked to fill a 30 mm plate it drew itself at its
    # natural size in one corner instead. Trade them for a viewBox so the plate
    # decides how big the code is.
    m = re.search(r'<svg[^>]*?width="([\d.]+)"[^>]*?height="([\d.]+)"', svg)
    if m:
        w, h = m.group(1), m.group(2)
        head = svg[: svg.index(">") + 1]
        fixed = re.sub(r'\s(width|height)="[\d.]+"', "", head)
        fixed = fixed[:-1] + f' viewBox="0 0 {w} {h}">'
        svg = fixed + svg[svg.index(">") + 1 :]
    return svg


def sessions(program):
    """Talk sessions with their speakers, day by day."""
    out = []
    for day in program["days"]:
        blocks = []
        for e in day["events"]:
            if e.get("type") not in ("block", "tutorial", "keynote"):
                continue
            people = [s for s in e.get("speakers", []) if s.get("name") and s["name"] != "TBD"]
            if not people:
                continue
            blocks.append(
                {
                    "title": e["title"],
                    "start": e.get("start", ""),
                    "end": e.get("end", ""),
                    "people": people,
                }
            )
        out.append({"label": day.get("label", ""), "theme": day.get("theme"), "blocks": blocks})
    return out


def programme_html(program, affils):
    cols = []
    for day in sessions(program):
        rows = []
        for b in day["blocks"]:
            people = "".join(
                f'<li><b>{esc(p["name"])}</b> <span class="aff">{esc(p.get("affil", ""))}</span>'
                + (f'<i>{esc(p["topic"])}</i>' if p.get("topic") else "")
                + "</li>"
                for p in b["people"]
            )
            rows.append(
                f'<div class="sess"><h4>{esc(b["title"])}'
                f'<span class="clock">{esc(b["start"])}–{esc(b["end"])}</span></h4>'
                f"<ul>{people}</ul></div>"
            )
        head = esc(day["label"])
        sub = f'<p class="daysub">{esc(day["theme"])}</p>' if day.get("theme") else ""
        cols.append(f'<div class="day"><h3>{head}</h3>{sub}{"".join(rows)}</div>')
    return "".join(cols)


TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster</title>
<style>
  /* A2 plus 3 mm of bleed all round. No trim marks: the printer sets those. */
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink};
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The art is given the top of the sheet and nothing else. Type over a field
     this busy has to be either very large or somewhere else; the programme is
     small, so it goes somewhere else. */
  .art {{ position:absolute; inset:0; overflow:hidden; }}
  .art svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* Only where the type actually is. */
  .fade {{ position:absolute; left:0; right:0; top:150mm; bottom:0; }}
  .fade svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .wrap {{ position:absolute; inset:0; padding:20mm 20mm 15mm; display:flex; flex-direction:column; }}
  .eyebrow {{
    font-family:"JetBrains Mono",monospace; font-size:3.9mm; font-weight:500;
    letter-spacing:.2em; text-transform:uppercase; color:{hot};
    border:.3mm solid rgba(255,138,117,.42); border-radius:99mm; padding:1.9mm 4.4mm;
    align-self:flex-start; background:rgba(11,17,28,.62);
  }}
  .mid {{ margin-top:auto; }}
  h1 {{
    font-family:"Jost",sans-serif; font-weight:500; font-size:58mm; line-height:.88;
    letter-spacing:-.022em; margin:0 0 3.5mm; color:{ink};
  }}
  h1 b {{ font-weight:700; color:{hot}; }}
  h1 .year {{ font-weight:300; color:{ink}; opacity:.86; }}
  .acronym {{
    font-family:"JetBrains Mono",monospace; font-size:5.1mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{cool}; margin:0 0 3.5mm;
  }}
  .theme {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:6.6mm; font-weight:500;
    color:{ink}; margin:0 0 3.5mm; opacity:.9;
  }}
  .theme b {{ font-weight:700; }}
  .facts {{
    display:flex; gap:12mm; font-family:"JetBrains Mono",monospace;
    font-size:4.6mm; font-weight:500; color:{ink}; margin:0 0 4.5mm;
  }}
  .facts span {{ color:{cool}; }}
  .rule {{ height:.3mm; background:{rule}; margin:0 0 3.5mm; }}
  /* The programme. Four columns of small type at the foot, the way a season
     card does it — the poster has to survive being read from a metre away for
     the name and from arm's length for the schedule. */
  .prog {{ display:grid; grid-template-columns:1fr 1fr; gap:10mm; align-items:start; }}
  .day h3 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:9.4mm; font-weight:700;
    color:{ink}; margin:0 0 1mm;
  }}
  .daysub {{
    font-family:"JetBrains Mono",monospace; font-size:4.6mm; letter-spacing:.12em;
    text-transform:uppercase; color:{hot}; margin:0 0 6.5mm;
  }}
  .sess {{ margin:0 0 4.4mm; break-inside:avoid; }}
  .sess h4 {{
    font-family:"JetBrains Mono",monospace; font-size:4mm; font-weight:500;
    letter-spacing:.14em; text-transform:uppercase; color:{hot};
    margin:0 0 1.8mm; display:flex; justify-content:space-between; gap:4mm;
  }}
  .clock {{ color:{cool}; letter-spacing:.06em; opacity:.8; }}
  .sess ul {{ margin:0; padding:0; list-style:none; }}
  .sess li {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:9.4mm; color:{ink};
    line-height:1.1; margin:0 0 2.1mm;
  }}
  .sess li b {{ font-weight:700; }}
  .aff {{ color:{cool}; font-weight:500; font-size:6.4mm; }}
  /* The topic lines are gone. Eight of them under the names is a third column
     of grey the sheet did not need, and taking them out is most of what moves
     the title down the page. */
  .sess li i {{ display:none; }}
  .tail {{
    display:flex; justify-content:space-between; align-items:baseline; margin-top:6mm;
    font-family:"JetBrains Mono",monospace; font-size:3.9mm; letter-spacing:.1em;
    text-transform:uppercase; color:{cool}; gap:10mm;
  }}
  .tail b {{ color:{ink}; font-weight:500; }}
  /* The QR sits on its own light patch. A code drawn light-on-dark decodes on
     most phones but not all — the quiet zone and the polarity are the two
     things cheap decoders are strict about, so both are given properly. */
  .qr-card {{ grid-column:2; display:flex; align-items:center; gap:5mm; margin-top:0; }}
  .qr {{ display:flex; align-items:flex-end; gap:5mm; }}
  .qr-plate {{ width:34mm; height:34mm; flex:none; background:{art_ink}; padding:1.6mm; border-radius:1mm; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .qr-say {{ text-align:left; }}
  .qr-say b {{ display:block; font-size:5.2mm; color:{ink}; letter-spacing:.06em; }}
  .qr-say span {{ display:block; font-size:4mm; color:{cool}; margin-top:1.2mm; text-transform:none; letter-spacing:.02em; }}
</style>
<div class="sheet">
  <div class="art">{art}</div>
  <div class="fade"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 100" preserveAspectRatio="none">
    <defs><linearGradient id="f" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ground}" stop-opacity="0"/>
      <stop offset=".28" stop-color="{ground}" stop-opacity=".72"/>
      <stop offset=".46" stop-color="{ground}" stop-opacity=".94"/>
      <stop offset="1" stop-color="{ground}" stop-opacity="1"/>
    </linearGradient></defs>
    <rect width="10" height="100" fill="url(#f)"/>
  </svg></div>
  <div class="wrap">
    <p class="eyebrow">{eyebrow}</p>
    <div class="mid">
      <h1><b>{mark}</b> <span class="year">{year}</span></h1>
      <p class="acronym">{full_name}</p>
      <p class="theme">{theme_label} · <b>{theme}</b></p>
      <div class="facts">{facts}</div>
      <div class="rule"></div>
      <div class="prog">{prog}
        <div class="qr-card">
          <div class="qr-plate">{qr}</div>
          <div class="qr-say"><b>{cta}</b><span>{url}</span></div>
        </div>
      </div>
      <div class="tail"><span>{hosts}</span><span>{venue_short}</span></div>
    </div>
  </div>
</div>
"""


LISTING = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, ruled</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  /* One ink on one ground, and every division drawn as a hairline rule. The
     layout is a stack of boxes with nothing between them, so the sheet has no
     margins in the usual sense — the rules are the margins. */
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{art_ink}; box-sizing:border-box; padding:10mm;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
    font-family:"Satoshi","Helvetica Neue",sans-serif;
  }}
  .frame {{
    height:100%; box-sizing:border-box; border:.45mm solid {art_ink};
    display:flex; flex-direction:column;
  }}
  .row {{ display:flex; border-bottom:.45mm solid {art_ink}; }}
  .row:last-child {{ border-bottom:0; }}
  .cell {{ padding:7mm 8mm; box-sizing:border-box; }}
  .cell + .cell {{ border-left:.45mm solid {art_ink}; }}
  /* The listing. Day-of-month, then what happens, then when — the rhythm the
     reference gets its texture from. */
  .list {{ flex:1; }}
  .list ul {{ margin:0; padding:0; list-style:none; }}
  .list li {{
    font-size:8.8mm; line-height:1.26; font-weight:500; margin:0 0 2.2mm;
    display:flex; gap:3.5mm; align-items:baseline;
  }}
  .list .d {{ font-family:"JetBrains Mono",monospace; font-weight:600; flex:none; }}
  .list .who {{ flex:1; }}
  .list .who b {{ font-weight:700; }}
  .list .t {{ font-family:"JetBrains Mono",monospace; font-size:6.2mm; flex:none; opacity:.72; }}
  /* The month, big, with the diagonal above it. */
  .month {{ width:118mm; display:flex; flex-direction:column; }}
  .slash {{ height:52mm; }}
  .slash svg {{ display:block; width:100%; height:100%; }}
  .month h2 {{
    font-family:"Jost",sans-serif; font-weight:300; font-size:26mm;
    margin:auto 0 0; letter-spacing:-.01em; text-align:right; line-height:1;
  }}
  /* The picture, in its own box. */
  .plate {{ flex:1; position:relative; overflow:hidden; border-bottom:.45mm solid {art_ink}; }}
  .plate svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .stamp {{
    font-family:"Jost",sans-serif; font-weight:300; font-size:24mm;
    letter-spacing:.01em; line-height:1; padding:6mm 8mm;
  }}
  .foot {{ align-items:stretch; }}
  .name {{ flex:1; }}
  .name h1 {{
    font-family:"Jost",sans-serif; font-weight:400; font-size:26mm; line-height:1.02;
    margin:0; letter-spacing:-.012em;
  }}
  .name h1 b {{ font-weight:600; }}
  .name p {{
    font-family:"JetBrains Mono",monospace; font-size:4.2mm; letter-spacing:.14em;
    text-transform:uppercase; margin:4mm 0 0; opacity:.8;
  }}
  .badge {{ width:118mm; display:flex; flex-direction:column; justify-content:space-between; }}
  .qr-plate {{ width:34mm; height:34mm; background:{art_ink}; padding:1.8mm; box-sizing:border-box; align-self:flex-end; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .badge address {{
    font-style:normal; font-family:"JetBrains Mono",monospace; font-size:4mm;
    line-height:1.5; text-align:right; margin-top:5mm; opacity:.82;
  }}
</style>
<div class="sheet"><div class="frame">
  <div class="row">
    <div class="cell list"><ul>{listing}</ul></div>
    <div class="cell month">
      <div class="slash"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none">
        <line x1="8" y1="92" x2="92" y2="8" stroke="{art_ink}" stroke-width="1.1" vector-effect="non-scaling-stroke"/>
      </svg></div>
      <h2>{month}</h2>
    </div>
  </div>
  <div class="row" style="flex:1"><div class="cell plate" style="flex:1;padding:0;border-bottom:0">{art}</div></div>
  <div class="row"><div class="cell stamp">{stamp}</div></div>
  <div class="row foot">
    <div class="cell name">
      <h1><b>{mark}</b> {year}</h1>
      <p>{full_name}</p>
    </div>
    <div class="cell badge">
      <div class="qr-plate">{qr}</div>
      <address>{venue_name}<br>{venue_addr}<br>{url}</address>
    </div>
  </div>
</div></div>
"""


FESTIVAL = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, festival</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi","Helvetica Neue",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .art {{ position:absolute; inset:0; overflow:hidden; opacity:{art_alpha}; }}
  .art svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .ghost {{ position:absolute; inset:0; overflow:hidden; opacity:.3; }}
  .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* Held well back. In the reference the ground is a soft bloom that the type
     sits on without contest; ours is a field of small marks, which is busier,
     so it is dimmed further than a photograph would need to be. */
  .veil {{ position:absolute; inset:0; }}
  .veil svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* The sheet is 426x600: A2 plus 3mm of bleed all round, so 20mm here is
     17mm from the trim. The bottom was 16mm, which is 13mm trimmed — four
     millimetres shy of the other three sides, and a poster whose content sits
     lower than its own margin reads as sliding off the bottom edge. */
  .wrap {{ position:absolute; inset:0; padding:20mm; display:flex; flex-direction:column; }}
  .top {{ display:flex; justify-content:space-between; align-items:flex-start; }}
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:32mm;
    line-height:1; color:{hot}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .stamps {{ color:{hot}; text-align:right; line-height:1.7; }}
  /* Mixed case, and the four letters of the acronym in the accent — the name
     is written so that K, O, L and T fall where they do, and capitals would
     hide it. */
  /* One quiet line under the mark, in the mono the sheet names its fields
     with. Set in the text face it was a second, smaller statement competing
     with the first; in the mono and in capitals it reads as a caption on the
     mark rather than as a line of its own, which is what it is — the mark
     spelled out. Held closer to the title and fainter for the same reason.

     6.5mm, which is the size at which the line ends where the mark ends. KOLT
     2026 sets 155mm; at 8mm this ran 190mm and overhung it by 35, so the two
     lines had no relationship at either end. Now they share both.

     The optical indent stays optical but the number changes with the face and
     the size: JetBrains Mono's sidebearing is 0.080 of the em against Jost's
     0.0738, so against a 32mm mark and a 6.5mm line the correction is 1.4mm. */
  .longname {{
    font-family:"JetBrains Mono",monospace; font-weight:600; font-size:6.5mm;
    letter-spacing:.1em; text-transform:uppercase; color:{ink};
    opacity:.46; margin:1.6mm 0 0 1.4mm;
  }}
  .cols h4 {{
    font-family:"JetBrains Mono",monospace; font-size:3.4mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{hot}; margin:7mm 0 2mm;
  }}
  /* Names in one column, affiliations in another, the way the programme sets
     them. As plain lines each affiliation began wherever its name ended, so
     six of them made a ragged edge down the middle of the block. */
  .orgs {{
    display:inline-grid; grid-template-columns:auto auto; column-gap:4mm;
    row-gap:0; align-items:baseline;
  }}
  .orgs b {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm; font-weight:700;
    color:{ink}; line-height:1.5; white-space:nowrap;
  }}
  /* Ranged right inside their column, so the affiliations make an edge of
     their own instead of six lines each ending wherever its name let it. */
  .orgs span {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm; font-weight:400;
    color:{cool}; line-height:1.5; white-space:nowrap; text-align:right;
  }}
  .cols .theme {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:5mm; font-weight:700;
    color:{ink}; margin:0; line-height:1.3;
  }}
  /* The two rotated blocks down the left edge. */
  /* 4.5mm between the two, not 9. A rail line's own box is 11.9mm across and
     the space between them was 9.8mm — nearly a line's width of nothing, so
     the venue and the theme read as two separate marks rather than as the pair
     they are. Less than half the line box holds them together. */
  /* Not pinned to a measurement. The rails are the only thing between the
     title and the programme, so they take the space between them and sit in
     the middle of it: auto margins above and below share the free height
     equally, and the panel below keeps its place because the column is a fixed
     height and there is nothing left for it to move into. Fixed at 118mm the
     gap above and the gap below were whatever the two blocks happened to
     leave. */
  .rails {{ display:flex; gap:4.5mm; margin:auto 0; }}
  .rail {{
    writing-mode:vertical-rl; transform:rotate(180deg);
    font-family:"Satoshi","Helvetica Neue",sans-serif; color:{hot};
  }}
  /* One line, sizes the other way round: the field name small, the thing
     itself large. Venue and Theme are the words a reader can
     supply for themselves — what they cannot is which venue and which theme,
     and that is what the edge should be saying at a distance.

     So everything the label had — the size, the accent, the weight — moves to
     the particular in one piece, and the label takes what the particular had:
     the small mono the sheet uses everywhere else to name a field, set quiet
     in the paper colour. Moving the size alone left the emphasis where it was
     and only made the loud thing small.

     A proportional face rather than the mono it started in: a monospaced face
     at this size sets 33 characters over 165mm and the rails would have run
     into the programme. 9mm rather than 10, for the same reason — Geist is
     wider than the Inter Tight this replaced, 177.7mm against 161.6mm on the
     venue line, which was 4mm past where the programme begins.

     The paper colour rather than the cool grey the sheet uses for a second
     voice elsewhere: these lines sit over the drawing rather than over flat
     ground, and a mid grey on a mottled mid ground is the one pairing that
     does not survive being printed.

     The field name is given a box of its own so both rails start their large
     text at the same point. VENUE measures 15.2mm and THEME 2026 measures
     30.4mm; set next to their own words the two would have begun 15mm apart
     and the edge would read as two unrelated lines rather than as a list.
     34mm is the longer of the two plus a word space. As inline-size, not
     width: the rails are turned, and the axis this has to hold is the one the
     text runs along, whichever way that ends up pointing. */
  /* Field names — VENUE, THEME, HOMEPAGE, ORGANISERS, the stamps at the top —
     all speak in the mono at one size. They were set at 4mm, 3.8mm and, in the
     case of Organisers, at whatever a browser gives an unstyled h4, which was
     16px. Nothing was gained by any of the differences. */
  .rail b, .side h4, .stamps, .prog-grid i u small {{
    font-family:"JetBrains Mono",monospace; font-size:3.8mm; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase;
  }}
  /* Right-aligned in its box, so the label ends against the line it opens
     instead of floating a word's width away from it. text-align is resolved on
     the inline axis, which these rails have turned and one of them has turned
     again, so it is set logically. */
  .rail b {{
    display:inline-block; inline-size:32mm; vertical-align:baseline;
    text-align:end; padding-inline-end:2.6mm; box-sizing:border-box;
    color:{ink}; opacity:.72;
  }}
  .side h4 {{ color:{ink}; opacity:.72; margin:7mm 0 2.5mm; }}
  .rail span {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:9mm;
    font-weight:700; letter-spacing:-.014em; color:{hot};
  }}
  /* A third rail on the opposite edge. It is a member of the same flex row
     rather than its own absolute block, which is what makes the alignment
     hold: the row stretches all three to one height, and since each is flipped
     within its own box the three labels finish on the same line. Given its own
     top it would have started level with the others but ended wherever its
     shorter text ran out, and the labels — the part the eye actually lines up
     — would have sat at three different heights.

     On the same 20mm column as everything else on that edge. It was pushed out
     to 8mm to stay clear of the programme, which does reach the column's right
     edge — but 100mm lower down, and the rail ends well above it. The only
     thing 8mm bought was a rail that did not line up with the schedule, the
     code or the sheet's own margin. */
  .rail-right {{ margin-left:auto; }}
  /* One thin line, not a statement. An address is a single fact and the left
     edge is where the sheet makes its statements; at the display size on the
     opposite edge it would have been a second shout for a URL. */
  .rail-right b {{
    inline-size:auto; margin-inline-end:2.4mm; color:{hot}; opacity:1;
  }}
  .rail-right span {{
    font-family:"JetBrains Mono",monospace; font-size:4.6mm; font-weight:400;
    letter-spacing:.06em; color:{ink}; opacity:.82;
  }}
  /* Including its label. The size on .rail em is the display size the left
     edge is set at, and it reaches here too — this rail is one of the rails.
     The whole line is small, which is the point of it. */
  /* The programme, against one right edge. */
  .panel {{ margin-top:0; }}
  .bill {{ margin:0 0 0 auto; text-align:right; }}

  /* The rule and the space between sessions live on the label, because a
     display:contents element cannot carry either. */

  .slot ul {{ margin:0; padding:0; list-style:none; }}
  /* Three columns, one grid, shared by the whole programme: the date, the
     name, the affiliation. The session titles and the hours are gone — a
     poster is read standing up and what it has to deliver is who is speaking;
     the schedule belongs on the page the QR leads to. */
  .prog-grid {{
    display:inline-grid; grid-template-columns:auto auto auto;
    column-gap:4mm; row-gap:0; justify-items:end; align-items:baseline;
    text-align:right;
  }}
  /* The session names range left. Everything to their right — the speakers,
     the affiliations, the days — is set against the sheet's right edge, so
     ranging these right too pushed them up against the names they label and
     left a ragged edge on the outside of the block, where the eye first meets
     it. The dayrow keeps its own alignment; it is a heading, not a label. */
  .prog-grid i {{
    font-style:normal; white-space:nowrap; align-self:baseline;
    justify-self:start; text-align:left;
  }}
  /* The break between the two days. It measured 18.8mm against names that sit
     flush against each other inside a day, and about half of that was the
     day's own label — the rest was 10.3mm of air around a 0.4mm rule, which
     read as a gap in the list rather than as a division of it. Halved. */
  /* The day gets the whole width and sits at the right edge, over the
     affiliations rather than out beyond the session labels. It is the heading
     of the block under it, and a heading belongs on the side the block is set
     against — this one is set right. */
  .prog-grid i.dayrow {{
    grid-column:1 / -1; justify-self:end; text-align:right; padding-top:2.2mm;
  }}
  .prog-grid em {{
    font-style:normal; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:8.6mm;
    font-weight:700; line-height:1.34; letter-spacing:-.012em; color:{ink};
    white-space:nowrap;
  }}
  .prog-grid span {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:5.6mm; font-weight:400;
    color:{cool}; white-space:nowrap;
  }}
  /* The session, named once over the people in it. No hour with it: the title
     says what the block is, which is what a reader standing in front of the
     sheet wants; the times are on the page the code leads to. */
  .prog-grid i b {{
    display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm;
    font-weight:700; letter-spacing:0; color:{hot};
  }}
  .prog-grid i u {{
    display:block; text-decoration:none; font-family:"Jost",sans-serif;
    font-size:7.6mm; font-weight:500; letter-spacing:-.01em; color:{ink};
  }}
  .prog-grid i u small {{
    display:block; font-weight:400; color:{cool}; margin-top:.8mm;
  }}
  .prog-grid i b {{ margin-bottom:0; }}
  .dayrule {{
    grid-column:1 / -1; width:100%; height:0; margin:2.2mm 0 1.6mm;
    border:0; border-top:.4mm solid rgba(255,255,255,.34);
  }}
  .dates {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16mm; margin:0; }}

  /* The date keeps Inter Tight, the face it was set in before the sheet moved
     to Satoshi. It is the one block here that is pure figures, and Inter Tight
     is drawn narrow — at 23mm over three lines that reads as a stack rather
     than as three separate numbers, which is the whole of the effect. */
  .stack {{
    margin-bottom:1mm;
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:23mm;
    line-height:1.02; letter-spacing:-.03em; color:{hot};
  }}
  /* The venue lives in the rail; the country is the one thing neither the rail
     nor the stack says, so it goes with the day. */
  .datesub {{ display:none; }}
  .side {{ flex:none; }}
  .side h4 {{ margin-top:7mm; }}
  /* The name once more along the bottom, at the size the theme used to sit at
     there. The mark states it in full at the top; down here it is the line
     that signs the sheet off, so it takes the theme's size, not its own. */
  /* Centred on the sheet rather than in the gap between the marks and the
     code. In the flex row it sat wherever those two left it, which is not the
     middle of anything; taken out of the flow it lands on the paper's centre
     line, which is what a line signing the sheet off should do. */
  .footname {{
    position:absolute; left:50%; transform:translateX(-50%); bottom:20mm;
    margin:0;
    font-family:"JetBrains Mono",monospace; font-size:4.4mm; font-weight:500;
    letter-spacing:.1em; text-transform:uppercase; color:{ink}; opacity:.46;
  }}
  .cols h4 {{
    font-family:"JetBrains Mono",monospace; font-size:3.6mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{hot}; margin:0 0 3mm;
  }}
  .cols ul {{ margin:0; padding:0; list-style:none; }}
  .cols li {{
    font-size:5.2mm; font-weight:700; line-height:1.42; color:{ink};
    text-transform:uppercase; letter-spacing:.02em;
  }}
  .cols li span {{ font-weight:400; color:{cool}; text-transform:none; letter-spacing:0; }}
  .mid {{ text-align:center; }}
  .mid ul li {{ text-transform:none; font-weight:500; }}
  .r {{ text-align:right; }}
  .marks {{ display:flex; align-items:flex-end; gap:9mm; }}
  .marks img {{ height:9mm; width:auto; display:block; opacity:.72; }}
  .foot {{
    display:flex; justify-content:space-between; align-items:flex-end; margin-top:9mm; gap:10mm;
    font-family:"JetBrains Mono",monospace; font-size:3.8mm; letter-spacing:.14em;
    text-transform:uppercase; color:{cool};
  }}
  .qr-plate {{ width:32mm; height:32mm; background:{art_ink}; padding:1.6mm; box-sizing:border-box; }}
  .foot .cta {{ text-align:right; }}
  .foot .cta b {{ display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm;
                  font-weight:700; color:{hot}; margin-bottom:2.5mm; letter-spacing:0;
                  text-transform:none; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style>
<div class="sheet">
  {ghost}<div class="art">{art}</div>
  <div class="veil"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 100" preserveAspectRatio="none">
    <defs><linearGradient id="v" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ground}" stop-opacity="{veil1}"/>
      <stop offset=".22" stop-color="{ground}" stop-opacity="{veil2}"/>
      <stop offset=".52" stop-color="{ground}" stop-opacity="{veil3}"/>
      <stop offset=".70" stop-color="{ground}" stop-opacity="{veil4}"/>
      <stop offset="1" stop-color="{ground}" stop-opacity="{veil5}"/>
    </linearGradient></defs>
    <rect width="10" height="100" fill="url(#v)"/>
  </svg></div>
  <div class="wrap">
    <div class="top">
      <div><h1 class="mark">{mark} <span>{year}</span></h1>
        <p class="longname">{long_name}</p></div>
      <div class="stamps">{eyebrow}</div>
    </div>
    <div class="rails">
      <div class="rail"><b>Venue</b><span>{venue_name}, {city}</span></div>
      <div class="rail"><b>Theme {year}</b><span>{theme}</span></div>
      <div class="rail rail-right"><b>Homepage</b><span>{url}</span></div>
    </div>
    <div class="panel">
      <div class="dates">
        <div class="side">
          <div class="stack">{yyyy}.<br>{md1}–<br>{md2}</div>
          <h4>Organisers</h4>
          <div class="orgs">{organisers}</div>
        </div>
        <div class="bill"><div class="prog-grid">{programme}</div></div>
      </div>
      <div class="foot">
        <span class="marks">{logos}</span>
        <p class="footname">{long_name}</p>
        <div class="cta"><b>{cta_short}</b><div class="qr-plate">{qr}</div></div>
      </div>
    </div>
  </div>
</div>
"""


# ─────────────────────────────────────────────────────────────
# The two large-format pieces, in the sheet's own language: the
# coral mark in Jost, everything else in Satoshi, field names in
# the mono, the campus written out in formulas behind a veil.
#
# What changes is the reading distance. A poster is read at arm's
# length and can carry a programme; a banner is read across a
# room or a courtyard and can carry a name, a date and a place.
# Anything more is decoration at that size, so there is nothing
# more on either of them.
# ─────────────────────────────────────────────────────────────

BANNER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>KOLT 2026 — banner, 5000x900mm</title>
<style>
  @page {{ size: 5000mm 900mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:5000mm; height:900mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .ghost {{ position:absolute; inset:0; overflow:hidden; opacity:.3; }}
  .art, .ghost svg {{ position:absolute; inset:0; }}
  .art {{ overflow:hidden; }}
  .art svg, .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .veil {{ position:absolute; inset:0; }}
  .veil svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* A banner is hung, and the top and bottom 60mm go into the hem or round a
     pole. Nothing that has to be read lives there. */
  /* The same keyline the X-banner and the square set carry, inset to the line
     the type is set to. It is what stops a dark field dissolving into whatever
     wall or crowd is behind it. */
  .frame {{
    position:absolute; inset:56mm; border:1.4mm solid rgba(245,245,247,.30);
    pointer-events:none;
  }}
  .wrap {{
    position:absolute; inset:56mm; padding:70mm 120mm;
    display:flex; align-items:center; justify-content:space-between; gap:120mm;
  }}
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:290mm;
    line-height:.92; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .longname {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:62mm;
    letter-spacing:-.01em; color:{ink}; opacity:.58; margin:26mm 0 0 13mm;
  }}
  .right {{ text-align:right; flex:none; }}
  .stack {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:150mm;
  /* The accent goes on the small type, not the large. The mark is white here
     and the date is the biggest thing on the piece; painting that the accent
     colour too left the loudest element carrying the colour while the name of
     the workshop stayed quiet, which is the hierarchy upside down. The accent
     is worth more on a field name that would otherwise disappear.
     The sheet does it the other way round because there the mark is the accent
     and the largest thing on the page. */
    line-height:1.02; letter-spacing:-.03em; color:{ink}; margin:0;
  }}
  .field {{
    font-family:"JetBrains Mono",monospace; font-size:34mm; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase; color:{hot};
    margin:34mm 0 8mm;
  }}
  .where {{
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:66mm;
    letter-spacing:-.014em; color:{ink}; margin:0;
  }}
  .marks {{ display:flex; justify-content:flex-end; gap:70mm; margin-top:40mm; }}
  .marks img {{ height:66mm; width:auto; display:block; opacity:.72; }}
</style></head><body>
<div class="sheet">
  {ghost}<div class="art">{art}</div>
  <div class="veil"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 10" preserveAspectRatio="none">
    <defs><linearGradient id="v" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{ground}" stop-opacity=".93"/>
      <stop offset=".34" stop-color="{ground}" stop-opacity=".62"/>
      <stop offset=".66" stop-color="{ground}" stop-opacity=".70"/>
      <stop offset="1" stop-color="{ground}" stop-opacity=".93"/>
    </linearGradient></defs>
    <rect width="100" height="10" fill="url(#v)"/>
  </svg></div>
  <div class="frame"></div>
  <div class="wrap">
    <div>
      <h1 class="mark">{mark} <span>{year}</span></h1>
      <p class="longname">{long_name}</p>
    </div>
    <div class="right">
      <p class="stack">{yyyy}.{md1}–{md2}</p>
      <p class="field">Venue</p>
      <p class="where">{venue_name}, {city}</p>
      <span class="marks">{logos}</span>
    </div>
  </div>
</div>
</body></html>
"""


XBANNER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>KOLT 2026 — X-banner, 600x1800mm</title>
<style>
  @page {{ size: 600mm 1800mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:600mm; height:1800mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .ghost {{ position:absolute; inset:0; overflow:hidden; opacity:.3; }}
  .art {{ position:absolute; inset:0; overflow:hidden; }}
  .art svg, .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .veil {{ position:absolute; inset:0; }}
  .veil svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* An X-banner hangs from four corner eyelets and stands on the floor. The
     lower 250mm is below the knee of anyone reading it and is usually behind
     the frame's foot, so it carries the marks and nothing that must be read. */
  /* A keyline, as the square set has, inset to the line the type is set to.
     A banner is seen against a wall, a window and a crowd, and an edge is what
     stops it dissolving into whichever one is behind it. */
  .frame {{
    position:absolute; inset:46mm; border:1.2mm solid rgba(245,245,247,.30);
    pointer-events:none;
  }}
  .wrap {{
    position:absolute; inset:46mm; padding:80mm 44mm 60mm;
    display:flex; flex-direction:column;
  }}
  /* The three facts, evenly spaced between the title and the foot, each opened
     by a rule its label sits on. Centred as one block they left a third of the
     banner empty under them and the spacing read as an accident; distributed,
     the same air is divided into equal parts and reads as a measure. */
  .facts {{ flex:1; display:flex; flex-direction:column; justify-content:space-evenly; margin:0; }}
  .fact {{ padding-top:12mm; border-top:.8mm solid rgba(245,245,247,.22); }}
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:132mm;
    line-height:.94; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  /* 22mm. At 33 the name ran 565mm inside what was then a 474mm column and
     broke over two lines under a mark that is already two; the keyline since
     took the column to 414mm, and 24mm would clear it by three millimetres,
     which is not a margin. At 22 it sets 377mm and stays whole. */
  .longname {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:22mm;
    letter-spacing:-.01em; color:{ink}; opacity:.58; margin:14mm 0 0 6mm;
  }}
  .field {{
    font-family:"JetBrains Mono",monospace; font-size:15mm; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase; color:{hot};
    margin:0 0 6mm;
  }}
  /* 30mm is the largest size at which both of the two lines this sets — the
     venue and the theme — stay whole in the 420mm column the keyline leaves:
     the venue 355mm with the city under it, the theme 407mm on one line. At
     40mm the venue broke into three and the theme into two, and a banner read
     from across a hall wants each fact in one piece. */
  .line {{
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:27mm;
    letter-spacing:-.014em; color:{ink}; margin:0;
  }}
  .stack {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:96mm;
    line-height:1.02; letter-spacing:-.03em; color:{ink}; margin:0;
  }}
  .foot {{
    display:flex; align-items:flex-end; justify-content:space-between; gap:30mm;
    padding-top:16mm; border-top:.8mm solid rgba(245,245,247,.22);
  }}
  /* 22mm, not 34. At 34 the two marks measured 386mm and the foot needed
     386 + 30 of gap + 110 of code = 526mm inside a 420mm column, so the code
     hung 62mm off the edge of the banner. */
  .marks {{ display:flex; align-items:flex-end; gap:24mm; }}
  .marks img {{ height:22mm; width:auto; display:block; opacity:.72; }}
  .cta {{ text-align:right; }}
  .cta b {{
    display:block; font-family:"Satoshi",sans-serif; font-size:16mm;
    font-weight:700; color:{hot}; margin-bottom:8mm;
  }}
  .qr-plate {{ width:110mm; height:110mm; background:{art_ink}; padding:5mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style></head><body>
<div class="sheet">
  {ghost}<div class="art">{art}</div>
  <div class="veil"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 100" preserveAspectRatio="none">
    <defs><linearGradient id="v" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ground}" stop-opacity=".80"/>
      <stop offset=".26" stop-color="{ground}" stop-opacity=".52"/>
      <stop offset=".58" stop-color="{ground}" stop-opacity=".66"/>
      <stop offset="1" stop-color="{ground}" stop-opacity=".97"/>
    </linearGradient></defs>
    <rect width="10" height="100" fill="url(#v)"/>
  </svg></div>
  <div class="frame"></div>
  <div class="wrap">
    <div>
      <h1 class="mark">{mark}<br><span>{year}</span></h1>
      <p class="longname">{long_name}</p>
    </div>
    <div class="facts">
      <div class="fact">
        <p class="field">Venue</p>
        <p class="line">{venue_name}<br>{city}</p>
      </div>
      <div class="fact">
        <p class="field">Theme {year}</p>
        <p class="line">{theme}</p>
      </div>
      <div class="fact">
        <p class="field">Dates</p>
        <p class="stack">{yyyy}.<br>{md1}–{md2}</p>
      </div>
    </div>
    <div class="foot">
      <span class="marks">{logos}</span>
      <div class="cta"><b>{cta_short}</b><div class="qr-plate">{qr}</div></div>
    </div>
  </div>
</div>
</body></html>
"""


# ─────────────────────────────────────────────────────────────
# The square set, for a carousel. Six slides of 1080x1080 in one
# document, one under the other; tools/poster.py --layout social
# writes the page and the export slices it into six files.
#
# A phone holds it at arm's length for a second and a half, so
# each slide carries one thing. The cover is the only one with
# the drawing at full strength — behind a list of names it makes
# them unreadable, and a carousel that cannot be read in the
# first second is not read at all.
# ─────────────────────────────────────────────────────────────

SOCIAL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>KOLT 2026 — square set</title>
<style>
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; background:#000; }}
  .card {{
    position:relative; width:1080px; height:1080px; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
  }}
  .art, .ghost {{ position:absolute; inset:0; overflow:hidden; }}
  .ghost {{ opacity:.26; }}
  .art svg, .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* Every slide but the cover holds the drawing well down: it is the same
     picture doing the same job, but a list of names over it at this size is a
     list nobody reads. */
  .card.quiet .art {{ opacity:.42; }}
  .card.quiet .ghost {{ opacity:.20; }}
  .veil {{ position:absolute; inset:0;
    background:linear-gradient(180deg,
      rgba(15,24,38,.62) 0%, rgba(15,24,38,.42) 34%,
      rgba(15,24,38,.70) 72%, rgba(15,24,38,.96) 100%); }}
  .card.quiet .veil {{ background:linear-gradient(180deg,
      rgba(15,24,38,.90) 0%, rgba(15,24,38,.86) 50%, rgba(15,24,38,.96) 100%); }}
  /* A keyline inset from the edge. A carousel is shown on a white feed and a
     black one, and a dark square with no edge bleeds into the first and
     vanishes into the second; the rule gives every slide the same frame and
     makes the set read as a set. It is also the margin the type is set to, so
     it is doing two jobs. */
  .frame {{
    position:absolute; inset:44px; border:1.5px solid rgba(245,245,247,.34);
    border-radius:6px; pointer-events:none;
  }}
  .pad {{ position:absolute; inset:44px; padding:52px 54px 48px; display:flex; flex-direction:column; }}
  .head {{ display:flex; align-items:baseline; justify-content:space-between; gap:24px; }}
  .kicker {{
    font-family:"JetBrains Mono",monospace; font-size:22px; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase; color:{ink}; opacity:.72; margin:0;
  }}
  .kicker.hot {{ color:{hot}; opacity:1; }}
  .num {{ font-family:"JetBrains Mono",monospace; font-size:22px; letter-spacing:.16em;
          color:{ink}; opacity:.45; }}
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:176px;
    line-height:.94; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .longname {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:38px;
    letter-spacing:-.01em; color:{ink}; opacity:.6; margin:14px 0 0 7px;
  }}
  h2 {{
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:74px;
    line-height:1.1; letter-spacing:-.02em; color:{ink}; margin:0;
  }}
  h2.ink {{ color:{ink}; }}
  .stack {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:118px;
    line-height:1.02; letter-spacing:-.03em; color:{ink}; margin:0;
  }}
  .body {{ font-size:32px; font-weight:400; line-height:1.45; color:{ink}; opacity:.82; margin:22px 0 0; }}
  /* The foot is the same on every slide: a rule, the address, and one fact
     that belongs to that slide. A single screenshot of any one of them still
     says where to go. */
  .foot {{
    margin-top:auto; padding-top:22px; border-top:1px solid rgba(245,245,247,.20);
    display:flex; align-items:baseline; justify-content:space-between; gap:24px;
    font-family:"JetBrains Mono",monospace; font-size:21px; letter-spacing:.1em;
    text-transform:uppercase; color:{ink}; opacity:.6;
  }}
  .foot b {{ color:{hot}; font-weight:400; opacity:1; }}
  .mid {{ margin:auto 0; }}
  .facts {{ font-family:"JetBrains Mono",monospace; font-size:26px; letter-spacing:.1em;
            text-transform:uppercase; color:{ink}; opacity:.78; line-height:2; margin:0; }}
  .facts b {{ color:{hot}; font-weight:400; }}
  /* Speakers, grouped under the session that holds them. Two columns so the
     affiliations make an edge, the way they do on the sheet. */
  /* The timetable. A row per session, opened by its hour and closed by a rule
     — the shape a printed programme has had for a century, and the reason it
     survives is that the eye can find one row in it without reading the rest.
     The hour is the column that makes that possible, and the earlier version
     of these slides left it out entirely. */
  .when-head {{ display:flex; align-items:baseline; justify-content:space-between;
                gap:24px; margin:0 0 6px; }}
  .when-head p {{ font-family:"Inter Tight",sans-serif; font-weight:700; font-size:56px;
                  letter-spacing:-.03em; color:{ink}; margin:0; }}
  .when-head p.hot {{ color:{ink}; }}
  .tags {{ display:flex; align-items:center; gap:14px; }}
  .tag {{
    font-family:"JetBrains Mono",monospace; font-size:20px; font-weight:500;
    letter-spacing:.14em; text-transform:uppercase; color:{hot};
    border:1.5px solid {hot}; border-radius:999px; padding:7px 16px;
  }}
  .tag.plain {{ color:{ink}; border-color:rgba(245,245,247,.42); opacity:.8; }}
  .rows {{ margin-top:6px; }}
  .row {{
    display:grid; grid-template-columns:150px 1fr; column-gap:24px;
    padding:20px 0 18px; border-top:1.5px solid rgba(245,245,247,.26);
  }}
  .hour {{ font-family:"JetBrains Mono",monospace; font-size:28px; letter-spacing:.04em;
           color:{ink}; opacity:.72; margin:0; }}
  .what {{ font-family:"Satoshi",sans-serif; font-weight:700; font-size:38px;
           letter-spacing:-.014em; color:{ink}; margin:0 0 6px; line-height:1.16; }}
  .whom {{ font-family:"Satoshi",sans-serif; font-weight:400; font-size:29px;
           color:{ink}; opacity:.78; margin:0; line-height:1.4; }}
  .whom i {{ font-style:normal; font-size:24px; color:{cool}; }}
  .people {{ display:grid; grid-template-columns:auto auto; column-gap:22px; row-gap:0;
             align-items:baseline; justify-content:start; }}
  .people b {{ font-size:40px; font-weight:700; letter-spacing:-.014em; color:{ink};
               line-height:1.36; white-space:nowrap; }}
  .people span {{ font-size:28px; font-weight:400; color:{cool}; text-align:right; white-space:nowrap; }}
  .orgs2 {{ display:grid; grid-template-columns:auto auto; column-gap:22px;
            align-items:baseline; justify-content:start; }}
  .orgs2 b {{ font-size:36px; font-weight:700; color:{ink}; line-height:1.52; white-space:nowrap; }}
  .orgs2 span {{ font-size:28px; font-weight:400; color:{cool}; text-align:right; white-space:nowrap; }}
  .marks {{ display:flex; align-items:flex-end; gap:38px; }}
  .marks img {{ height:42px; width:auto; display:block; opacity:.72; }}
  .qr-plate {{ width:186px; height:186px; background:{art_ink}; padding:9px; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .join {{ display:flex; align-items:flex-end; justify-content:space-between; gap:30px; margin-top:34px; }}
</style></head><body>

<div class="card">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker hot">{eyebrow}</p><span class="num">1/6</span></div>
    <div class="mid"></div>
    <div>
      <h1 class="mark">{mark} <span>{year}</span></h1>
      <p class="longname">{long_name}</p>
    </div>
    <div class="foot"><span><b>{yyyy}.{md1}–{md2}</b></span><span>{venue_name}, {city}</span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">What it is</p><span class="num">2/6</span></div>
    <div class="mid">
      <p class="kicker hot" style="margin-bottom:14px">Theme {year}</p>
      <h2>{theme}</h2>
      <p class="body">{blurb}</p>
    </div>
    <div class="foot"><span>kolt-workshop.github.io/{year}</span><span><b>Free to attend</b></span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">When &amp; where</p><span class="num">3/6</span></div>
    <div class="mid">
      <p class="stack">{yyyy}.<br>{md1}–{md2}</p>
      <h2 class="ink" style="font-size:48px;margin-top:32px">{venue_name}</h2>
      <p class="body" style="font-size:28px;margin-top:8px">{venue_addr}</p>
      <p class="facts" style="margin-top:26px">{rooms}</p>
    </div>
    <div class="foot"><span>2 days · Korean</span><span><b>Details are tentative</b></span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">Programme</p><span class="num">4/6</span></div>
    <div class="when-head">
      <p class="hot">{day1_date}</p><p>{day1_span}</p>
    </div>
    <div class="tags"><span class="tag">{day1_label}</span><span class="tag plain">{room}</span></div>
    <div class="rows mid">{day1_rows}</div>
    <div class="foot"><span>Day 1 of 2</span><span>Programme subject to change</span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">Programme</p><span class="num">5/6</span></div>
    <div class="when-head">
      <p class="hot">{day2_date}</p><p>{day2_span}</p>
    </div>
    <div class="tags"><span class="tag">{day2_label}</span><span class="tag plain">{room}</span></div>
    <div class="rows mid">{day2_rows}</div>
    <div class="foot"><span>Day 2 of 2</span><span>Programme subject to change</span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">Organisers</p><span class="num">6/6</span></div>
    <div class="mid">
      <div class="orgs2">{organisers}</div>
      <div class="join">
        <div>
          <p class="kicker hot" style="margin-bottom:12px">Registration {reg_note}</p>
          <p class="body" style="font-size:30px;margin:0 0 24px">kolt-workshop.github.io/{year}</p>
          <span class="marks">{logos}</span>
        </div>
        <div class="qr-plate">{qr}</div>
      </div>
    </div>
    <div class="foot"><span>{mark} {year}</span><span><b>See you in {city}</b></span></div>
  </div>
</div>

</body></html>
"""
# ─────────────────────────────────────────────────────────────
# Name badges, 90x130mm — the usual insert for a lanyard holder.
# One card per page, so a print shop can take the file as it is.
#
# A badge is read across a handshake, which is about a metre, and
# what is read is the name. Everything else is for the second
# look: the affiliation to place the person, the role to say why
# they are on the programme, the mark so a badge left on a table
# still says which workshop it belongs to.
# ─────────────────────────────────────────────────────────────

BADGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>KOLT 2026 — name badges, 90x130mm</title>
<style>
  @page {{ size: 90mm 130mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; background:#000; }}
  .card {{
    position:relative; width:90mm; height:130mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
    page-break-after:always; break-after:page;
  }}
  .card:last-child {{ page-break-after:auto; break-after:auto; }}
  /* The drawing is carried once, in the stylesheet, and the twenty-one cards
     reference it. Inlined into each card the document came to 21MB and Chrome
     would not finish printing it; as one data URI behind a background-image it
     is stored once and painted twenty-one times.

     Held right down either way. It is why the badge belongs to this workshop
     and not another, and it is the one thing on the card that must not compete
     with a name read across a handshake. */
  .art, .ghost {{ position:absolute; inset:0; background-position:center;
                  background-size:cover; background-repeat:no-repeat; }}
  .art {{ background-image:url("{art_url}"); opacity:.34; }}
  .ghost {{ background-image:url("{ghost_url}"); opacity:.16; }}
  .veil {{ position:absolute; inset:0;
    background:linear-gradient(180deg,
      rgba(15,24,38,.72) 0%, rgba(15,24,38,.88) 46%, rgba(15,24,38,.97) 100%); }}
  .pad {{ position:absolute; inset:0; padding:9mm 8mm 8mm; display:flex; flex-direction:column; }}
  .top {{ display:flex; align-items:baseline; justify-content:space-between; gap:4mm; }}
  /* 9mm and unbreakable. At 11 the mark measured 53mm of the 74mm the card
     has, the date column took the rest, and KOLT 2026 wrapped onto two lines —
     a wordmark split across a line break stops being a wordmark. */
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:9mm; white-space:nowrap;
    line-height:1; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .when {{
    font-family:"JetBrains Mono",monospace; font-size:2.8mm; letter-spacing:.1em;
    text-transform:uppercase; color:{ink}; opacity:.5; text-align:right; line-height:1.5;
  }}
  /* The name sits above centre, not on it: a lanyard holder curls forward at
     the bottom and a card worn on a chest is read from above. */
  .who {{ margin-top:13mm; }}
  .role {{
    display:inline-block; font-family:"JetBrains Mono",monospace; font-size:2.9mm;
    font-weight:500; letter-spacing:.16em; text-transform:uppercase; color:{hot};
    border:.3mm solid {hot}; border-radius:1.6mm; padding:1.4mm 2.6mm; margin:0 0 4mm;
  }}
  .role.plain {{ color:{ink}; border-color:rgba(245,245,247,.42); opacity:.7; }}
  .name {{
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:11mm;
    line-height:1.12; letter-spacing:-.016em; color:{ink}; margin:0;
  }}
  .name-ko {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:5.4mm;
    color:{ink}; opacity:.62; margin:1.6mm 0 0;
  }}
  .affil {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:5mm;
    color:{cool}; margin:3.4mm 0 0;
  }}
  /* Ruled space instead of a printed name, for anyone registering on the day.
     The rule is what tells a person there is something to write. */
  .write {{ margin-top:6mm; }}
  .write i {{ display:block; height:.35mm; background:rgba(245,245,247,.30); margin-bottom:9mm; }}
  .foot {{
    margin-top:auto; padding-top:4mm; border-top:.3mm solid rgba(245,245,247,.20);
    display:flex; align-items:flex-end; justify-content:space-between; gap:4mm;
    font-family:"JetBrains Mono",monospace; font-size:2.7mm; letter-spacing:.1em;
    text-transform:uppercase; color:{ink}; opacity:.55;
  }}
  .foot .longname {{ margin:0; max-width:44mm; line-height:1.5; }}
  .qr-plate {{ width:16mm; height:16mm; background:{art_ink}; padding:.8mm; box-sizing:border-box; flex:none; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style></head><body>
{badges}
</body></html>
"""


def listing_html(program):
    """One line per session: day of the month, who, and when."""
    out = []
    for day in program["days"]:
        dom = str(day["date"]).split("-")[-1]
        for e in day["events"]:
            if e.get("type") not in ("block", "tutorial", "keynote"):
                continue
            people = [s["name"] for s in e.get("speakers", []) if s.get("name") and s["name"] != "TBD"]
            if not people:
                continue
            out.append(
                f'<li><span class="d">{esc(dom)}</span>'
                f'<span class="who"><b>{esc(e["title"])}</b> &middot; {esc(", ".join(people))}</span>'
                f'<span class="t">{esc(e.get("start", ""))}</span></li>'
            )
    return "".join(out)


ACADEMIC = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, academic</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi","Helvetica Neue",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The picture is an accent here, not a field. In the sheet this follows, a
     wireframe surface runs down the right edge and into the corners and the
     type sits on plain ground; the formulas do the same job, held right back
     and masked away from the column the names occupy. */
  .art {{ position:absolute; inset:0; overflow:hidden; opacity:.62; }}
  .art svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .art {{
    -webkit-mask-image: radial-gradient(115% 78% at 108% 30%, #000 12%, transparent 62%),
                        radial-gradient(85% 55% at -8% 88%, #000 8%, transparent 60%);
    mask-image: radial-gradient(115% 78% at 108% 30%, #000 12%, transparent 62%),
                radial-gradient(85% 55% at -8% 88%, #000 8%, transparent 60%);
  }}
  .wrap {{ position:absolute; inset:0; padding:26mm 24mm 0; display:flex; flex-direction:column; }}
  h1 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:24mm;
    line-height:1.05; letter-spacing:-.02em; margin:0 0 10mm; color:#fff;
  }}
  .when {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:11mm;
    line-height:1.36; color:{gold}; margin:0 0 14mm;
  }}
  .when span {{ display:block; }}
  .when .thm {{ color:{ink}; font-weight:500; font-size:8.6mm; margin-top:3mm; }}
  .bill {{ display:grid; grid-template-columns:1fr 1fr; gap:9mm 12mm; margin:0; padding:0; }}
  .bill li {{ list-style:none; margin:0 0 9mm; }}
  .bill b {{
    display:block; font-size:13mm; font-weight:700; line-height:1.1;
    letter-spacing:-.014em; color:#fff;
  }}
  .bill span {{
    display:block; font-size:7.6mm; font-weight:400; line-height:1.2;
    color:{cool}; margin-top:1.2mm;
  }}
  /* The strip along the foot, a shade darker than the sheet. */
  .band {{
    position:absolute; left:0; right:0; bottom:0; height:118mm;
    background:{band}; border-top:.4mm solid rgba(255,255,255,.10);
    padding:14mm 24mm; box-sizing:border-box; display:flex; gap:14mm; align-items:flex-start;
  }}
  .band h4 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:7mm; font-weight:700;
    color:{gold}; margin:0 0 4.5mm;
  }}
  .orgs {{ flex:1; }}
  .orgs ul {{ margin:0; padding:0; list-style:none; }}
  .orgs li {{ font-size:7mm; font-weight:700; color:#fff; line-height:1.52; }}
  .orgs li span {{ font-weight:400; color:{cool}; }}
  .cta {{ text-align:center; }}
  .qr-plate {{ width:44mm; height:44mm; background:#fff; padding:2mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .cta b {{
    display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:6.4mm;
    font-weight:700; color:{gold}; margin-top:3.5mm;
  }}
  .site {{
    position:absolute; left:24mm; right:24mm; bottom:9mm;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:5.6mm; font-weight:500;
    color:#fff; display:flex; justify-content:space-between; align-items:baseline;
  }}
  .site span {{ color:{cool}; font-size:4.6mm; }}
</style>
<div class="sheet">
  <div class="art">{art}</div>
  <div class="wrap">
    <h1>{mark} {year}<br>{full_title}</h1>
    <p class="when"><span>{dates_long}</span><span>{venue_name}, {city}, {country}</span><span class="thm">{theme}</span></p>
    <ul class="bill">{bill_academic}</ul>
  </div>
  <div class="band">
    <div class="orgs">
      <h4>Organisers</h4>
      <ul>{organisers}</ul>
    </div>
    <div class="cta">
      <div class="qr-plate">{qr}</div>
      <b>{cta_short}</b>
    </div>
  </div>
  <div class="site"><span>{hosts}</span><b>{url}</b></div>
</div>
"""


CIVIC = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, civic</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter"; font-weight:400 700; src:url("fonts/inter-latin.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{paper2}; color:{carbon}; font-family:"Inter",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The chevron. One flat shape, cut from the ground, that the rest of the
     sheet is arranged around — the whole device of the poster this follows. */
  .shape {{ position:absolute; inset:0; }}
  .shape svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* And the picture as a band along the foot, in ink rather than light. */
  .band {{ position:absolute; left:0; right:0; bottom:0; height:170mm; overflow:hidden; }}
  .band svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .rail {{
    position:absolute; right:34mm; top:34mm; height:250mm;
    border:1.2mm solid {sky}; padding:9mm 7mm; box-sizing:border-box;
  }}
  .rail h1 {{
    writing-mode:vertical-rl; margin:0; font-family:"Satoshi","Helvetica Neue",sans-serif;
    font-weight:700; font-size:19mm; letter-spacing:.06em; line-height:1;
    text-transform:uppercase; color:{carbon};
  }}
  .rail2 {{
    position:absolute; right:12mm; top:34mm;
    writing-mode:vertical-rl; font-family:"Satoshi","Helvetica Neue",sans-serif;
    font-weight:700; font-size:11mm; letter-spacing:.1em; text-transform:uppercase;
    color:{carbon};
  }}
  .blurb {{
    position:absolute; right:14mm; top:300mm; width:60mm;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:7mm;
    line-height:1.3; color:{carbon};
  }}
  .left {{ position:absolute; left:26mm; top:104mm; width:146mm; }}
  .kicker {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:6.4mm;
    letter-spacing:.06em; text-transform:uppercase; margin:0 0 6mm; line-height:1.24;
  }}
  .when {{ font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:9mm; line-height:1.18; margin:0 0 3mm; }}
  .where {{ font-size:4.8mm; line-height:1.4; color:{carbon2}; margin:0 0 14mm; }}
  .grp {{ margin:0 0 9mm; }}
  .grp h4 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:500; font-size:4.2mm;
    letter-spacing:.1em; text-transform:uppercase; color:{carbon2}; margin:0 0 2.5mm;
  }}
  .grp ul {{ margin:0; padding:0; list-style:none; }}
  .grp li {{ margin:0 0 3.4mm; }}
  .grp b {{ display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:8mm; line-height:1.1; }}
  .grp span {{ display:block; font-size:4.4mm; color:{carbon2}; line-height:1.34; margin-top:.8mm; }}
  .side {{ position:absolute; right:14mm; top:336mm; width:104mm; font-size:4.8mm; line-height:1.46; color:{carbon}; }}
  .cols h4 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:500; font-size:4mm;
    letter-spacing:.1em; text-transform:uppercase; color:{carbon2}; margin:0 0 2mm;
  }}
  .side ul {{ margin:0 0 8mm; padding:0; list-style:none; }}
  .side a {{ color:{carbon}; font-weight:700; }}
  .qr-plate {{ position:absolute; left:26mm; bottom:22mm; width:36mm; height:36mm; background:#fff; padding:1.8mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style>
<div class="sheet">
  <div class="shape"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 426 600" preserveAspectRatio="none">
    <path d="M196 322 L300 246 L300 322 L404 246 L404 486 L300 486 L300 412 L196 486 Z" fill="{sky}"/>
  </svg></div>
  <div class="band">{art}</div>
  <div class="rail"><h1>{mark} {year}</h1></div>
  <div class="rail2">{full_name}</div>
  <p class="blurb">{theme}</p>
  <div class="left">
    <p class="kicker">{eyebrow}</p>
    <p class="when">{dates_long}</p>
    <p class="where">{venue_name}<br>{city}, {country}</p>
    <div class="grp"><h4>Day 1 · {d1}</h4><ul>{day1}</ul></div>
    <div class="grp"><h4>Day 2 · {d2}</h4><ul>{day2}</ul></div>
  </div>
  <div class="side">
    <h4>Organisers</h4><ul>{organisers}</ul>
    <p>Programme and registration<br><a>{url}</a></p>
  </div>
  <div class="qr-plate">{qr}</div>
</div>
"""


BAUHAUS = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, bauhaus</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter"; font-weight:400 700; src:url("fonts/inter-latin.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{paper}; color:{carbon}; font-family:"Inter",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .hair {{ position:absolute; background:rgba(27,27,27,.22); }}
  .vline {{ left:212mm; top:0; bottom:0; width:.25mm; }}
  /* The disc, half behind the picture. */
  .disc {{ position:absolute; left:96mm; top:214mm; width:150mm; height:150mm; border-radius:50%; background:{accent}; }}
  .plate {{ position:absolute; left:212mm; top:214mm; right:0; height:290mm; overflow:hidden; }}
  .plate svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  h1 {{
    position:absolute; left:24mm; top:26mm; margin:0;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:78mm;
    line-height:.86; letter-spacing:-.045em; text-transform:lowercase;
  }}
  .motto {{
    position:absolute; left:24mm; top:246mm; margin:0; width:64mm;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:11mm;
    line-height:1.18; letter-spacing:-.02em; text-transform:lowercase;
  }}
  .motto i {{ font-style:normal; color:{accent}; }}
  .meta {{ position:absolute; left:228mm; top:30mm; width:110mm; font-size:6.4mm; line-height:1.44; text-transform:lowercase; }}
  .meta .lead {{ color:{carbon2}; margin:0 0 6mm; }}
  .meta .big {{ font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:8mm; line-height:1.24; margin:0 0 5mm; }}
  .meta .red {{ color:{accent}; font-weight:700; margin:0 0 8mm; }}
  .meta .hours {{ color:{carbon2}; margin:0; }}
  .dates {{
    position:absolute; right:22mm; top:26mm; text-align:right;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:19mm; line-height:1.1;
  }}
  .dates hr {{ border:0; border-top:.4mm solid {carbon}; margin:3mm 0; }}
  .dates small {{ display:block; font-size:11mm; font-weight:500; }}
  .names {{
    position:absolute; left:24mm; top:398mm; width:172mm; margin:0; padding:0; list-style:none;
    font-size:6.4mm; line-height:1.66; text-transform:lowercase;
    columns:2; column-gap:10mm;
  }}
  .tickets {{
    position:absolute; left:24mm; bottom:44mm; font-size:6mm; line-height:1.5; text-transform:lowercase;
  }}
  .tickets b {{ display:block; color:{accent}; font-weight:700; }}
  .swatch {{ position:absolute; left:24mm; bottom:20mm; width:12mm; height:12mm; background:{accent}; }}
  .dots {{ position:absolute; right:24mm; bottom:26mm; display:grid; grid-template-columns:repeat(5,5mm); gap:4mm; }}
  .dots i {{ width:2.6mm; height:2.6mm; border-radius:50%; background:{paper}; display:block; }}
  .credit {{
    position:absolute; right:6mm; bottom:26mm; writing-mode:vertical-rl;
    font-size:3.4mm; color:{carbon2};
  }}
  .qr-plate {{ position:absolute; right:22mm; top:150mm; width:34mm; height:34mm; background:{paper}; padding:1.6mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style>
<div class="sheet">
  <div class="hair vline"></div>
  <div class="disc"></div>
  <div class="plate">{art}</div>
  <h1>{mark}<br>{year}</h1>
  <p class="motto">theory<br>follows<br>practice<i>.</i></p>
  <div class="meta">
    <p class="lead">{eyebrow}</p>
    <p class="big">{venue_name}<br>{city}, {country}</p>
    <p class="red">{theme}</p>
    <p class="hours">{full_name}<br>{days_long}</p>
  </div>
  <div class="dates">{d1}<hr>{d2}<small>{yyyy}</small></div>
  <ul class="names">{names_flat}</ul>
  <div class="qr-plate">{qr}</div>
  <p class="tickets">programme &amp; registration<br><b>{url}</b></p>
  <div class="swatch"></div>
  <div class="dots">{dots}</div>
  <div class="credit">{hosts}</div>
</div>
"""


def festival_bits(program, organizers, site):
    """The pieces the festival sheet needs that the others do not."""
    bill, sess = [], []
    for day in program["days"]:
        for e in day["events"]:
            if e.get("type") not in ("block", "tutorial", "keynote"):
                continue
            people = [s for s in e.get("speakers", []) if s.get("name") and s["name"] != "TBD"]
            if not people:
                continue
            sess.append(f"<li>{esc(e['title'])}</li>")
            for p in people:
                bill.append(
                    f'<li>{esc(p["name"])}<sup>{esc(p.get("affil", ""))}</sup></li>'
                )
    # Two cells per person, not one line each: the affiliations then form a
    # column of their own instead of starting wherever the name happens to end.
    orgs = "".join(
        f'<b>{esc(m["name"])}</b><span>{esc(m.get("affil", ""))}</span>'
        for m in organizers["members"]
    )
    days = " ".join(str(d["date"]).split("-")[-1] for d in program["days"])
    return "".join(bill), "".join(sess), orgs, days


# The pixel size the photographic layers are generated at, per layout. Not the
# print size — this is the raster the duotone is computed on, and it only has to
# match the shape of the piece so nothing is cropped into or stretched across.
ART_FIT = {
    # The banner's drawing is made from a band cut out of the photograph at the
    # banner's own shape, so there is nothing left to crop and nothing to
    # squash. The band is chosen so the clock tower is whole inside it: its cap
    # sits at 2% of the frame and the skyline at 11%; the band is 24% tall and
    # cut from 30%, which is where the tower is whole and the buildings fill it.
    "banner": "xMidYMid slice",
}

GHOST_SIZE = {
    "civic": (1700, 820),
    "listing": (1700, 1520),
    "bauhaus": (1000, 1360),
    "banner": (3400, 612),      # 5000 x 900mm, from the pre-cut band
    "xbanner": (900, 2700),     # 600 x 1800mm
    "social": (1400, 1400),     # 1080 x 1080 square
    "badge": (900, 1300),       # 90 x 130mm
}


def main(art_path, out_path, layout="stack", photo=None, cutout=None, duotone=None,
         ghost=None, silhouette=None):
    site = yaml.safe_load((DATA / "site.yml").read_text(encoding="utf-8"))
    program = yaml.safe_load((DATA / "program.yml").read_text(encoding="utf-8"))
    venue = yaml.safe_load((DATA / "venue.yml").read_text(encoding="utf-8"))

    ghost_layer = ""
    if silhouette:
        # A flat plate in the shape of the subject, under the formulas. The
        # drawing alone is thin strokes, and at any distance a field of thin
        # strokes reads as a tint rather than as a thing; the plate gives it a
        # mass and the formulas become the texture on it. Written as a mask on
        # a coloured box rather than as a coloured image, so the plate follows
        # whatever art_ink the scheme sets.
        data = base64.b64encode(Path(silhouette).read_bytes()).decode("ascii")
        url = f"data:image/png;base64,{data}"
        ghost_layer = (
            f'<div style="position:absolute;inset:0;background:{PALETTE["art_ink"]};'
            f'-webkit-mask:url({url}) 0 0/100% 100% no-repeat;'
            f'mask:url({url}) 0 0/100% 100% no-repeat;opacity:.9"></div>')
    elif ghost:
        # The same two layers the website's hero uses. The formulas alone are a
        # drawing of the photograph; the photograph faintly behind them is what
        # holds the shape together between the marks, and it is the reason the
        # hero reads as a place rather than as a texture. Held right down — it
        # is there to be felt, not seen.
        light_ground = layout in ("civic", "bauhaus")
        gw, gh = GHOST_SIZE.get(layout, (1700, 2398))
        ghost_layer = (
            '<div class="ghost">'
            + photo_svg(ghost,
                        PALETTE["paper"] if light_ground else "#0a111d",
                        PALETTE["carbon"] if light_ground else PALETTE["art_ink"],
                        gw, gh)
            + "</div>")

    if cutout:
        light_ground = layout in ("civic", "bauhaus")
        w, h = GHOST_SIZE.get(layout, (1700, 2398))
        art = cutout_svg(
            cutout,
            PALETTE["paper"] if light_ground else "#24374f",
            PALETTE["carbon"] if light_ground else "#e4edfa",
            w, h,
        )
    elif photo:
        # Light grounds want ink on paper; dark ones want light on the field.
        light_ground = layout in ("civic", "bauhaus")
        w, h = GHOST_SIZE.get(layout, (1700, 2398))
        shadow, highlight = (
            duotone.split(",") if duotone else
            ((PALETTE["paper"], PALETTE["carbon"]) if light_ground
             else ("#0a111d", PALETTE["art_ink"]))
        )
        art = photo_svg(photo, shadow, highlight, w, h)
    else:
        art = Path(art_path).read_text(encoding="utf-8")
        # How the drawing is fitted to a box that is not its shape. Slicing
        # crops; it never squashes, which is what a wide banner would otherwise
        # do to a photograph taken in 4:3. The anchor says which part survives
        # the crop, and for the banner that is the top — the clock tower is the
        # thing on this campus a passer-by recognises, and a centred crop cuts
        # its head off.
        fit = ART_FIT.get(layout, "xMidYMid slice")
        if "preserveAspectRatio" in art.split(">", 1)[0]:
            art = re.sub(r'preserveAspectRatio="[^"]*"', f'preserveAspectRatio="{fit}"', art, count=1)
        else:
            art = art.replace("<svg ", f'<svg preserveAspectRatio="{fit}" ', 1)

    name = site["name"]
    mark, year = (name.rsplit(" ", 1) + [""])[:2] if " " in name else (name, "")
    facts = " ".join(
        f"<div>{esc(v)}<span> · {esc(n)}</span></div>" if n else f"<div>{esc(v)}</div>"
        for v, n in [
            (site["dates"], None),
            (venue["name"], f"{site['venue']}, {site['city']}"),
        ]
    )
    tpl = {"listing": LISTING, "festival": FESTIVAL, "academic": ACADEMIC,
           "civic": CIVIC, "bauhaus": BAUHAUS,
           "banner": BANNER, "xbanner": XBANNER,
           "social": SOCIAL, "badge": BADGE}.get(layout, TEMPLATE)
    organizers = yaml.safe_load((DATA / "organizers.yml").read_text(encoding="utf-8"))
    bill, sessions_list, organisers, days = festival_bits(program, organizers, site)
    day_people = []
    for d in sessions(program):
        day_people.append("".join(
            f'<li><b>{esc(p["name"])}</b><span>{esc(p.get("affil", ""))}'
            + (f' &middot; {esc(p["topic"])}' if p.get("topic") else "")
            + "</span></li>"
            for b in d["blocks"] for p in b["people"]))
    slots = []
    for d in sessions(program):
        if slots:
            slots.append('<hr class="dayrule">')
        # The date only on the first line of its day: repeated down every row it
        # would read as a stamp rather than as the thing that opens the group.
        # "Day 1 · Oct 7 (Wed)" -> "Oct 7" with the weekday on its own line.
        raw = d["label"].split("·")[-1].strip() if "·" in d["label"] else d["label"]
        day, _, wd = raw.partition("(")
        label = esc(day.strip()) + (f"<small>{esc(wd.rstrip(')'))}</small>" if wd else "")
        first = True
        for b in d["blocks"]:
            for k, p2 in enumerate(b["people"]):
                if k == 0 and first:
                    slots.append(f'<i class="dayrow"><u>{label}</u></i>')
                    first = False
                key = f'<b>{esc(b["title"])}</b>' if k == 0 else ""
                slots.append(
                    f"<i>{key}</i>"
                    f'<em>{esc(p2["name"])}</em>'
                    f'<span>{esc(p2.get("affil", ""))}</span>')
    programme_block = "".join(slots)
    names_flat = "".join(
        f'<li>{esc(p["name"].lower())}</li>'
        for d in sessions(program) for b in d["blocks"] for p in b["people"])
    month = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"][
        int(str(program["days"][0]["date"]).split("-")[1]) - 1]
    d0 = str(program["days"][0]["date"]).split("-")
    # Pieces only the square set needs: a day's speakers as grid cells, the
    # rooms as one mono block, and the day's own label.
    # The day slides are a timetable, not a list of names: a row per session,
    # opened by its hour and separated by a rule. The hour is what a reader
    # actually wants from a programme, and it was the one thing the earlier
    # version left out.
    day_rows, day_spans = [], []
    for day in program["days"]:
        talks = [e for e in day["events"]
                 if e.get("type") in ("block", "tutorial", "keynote") and e.get("speakers")]
        rows = []
        for e in talks:
            people = " · ".join(
                f'{esc(s["name"])} <i>{esc(s.get("affil", ""))}</i>'
                for s in e["speakers"] if s.get("name") and s["name"] != "TBD")
            rows.append(
                f'<div class="row">'
                f'<p class="hour">{esc(e.get("start", ""))}</p>'
                f'<div><p class="what">{esc(e["title"])}</p>'
                f'<p class="whom">{people}</p></div></div>')
        day_rows.append("".join(rows))
        first, last = day["events"][0], day["events"][-1]
        day_spans.append(f'{first.get("start", "")} – {last.get("end", "")}')

    day_grids, day_labels = [], []
    for d in sessions(program):
        # Grouped under the session that holds them rather than run together:
        # fourteen names in one column say who is coming, and nothing about
        # what the two days are made of.
        groups = []
        for b in d["blocks"]:
            people = "".join(
                f'<b>{esc(p["name"])}</b><span>{esc(p.get("affil", ""))}</span>'
                for p in b["people"])
            groups.append(f'<p class="sess">{esc(b["title"])}</p>'
                          f'<div class="people">{people}</div>')
        day_grids.append("".join(groups))
        raw = d["label"].split("·")[-1].strip() if "·" in d["label"] else d["label"]
        day_labels.append(esc(raw.replace("(", "· ").rstrip(")")))
    # One card per person the programme already names, then a run of blanks for
    # whoever registers on the day. Speakers before organisers, and a speaker
    # who is also an organiser is billed as a speaker — that is the reason they
    # are on the programme, and two cards for one person is a card wasted.
    # "October 7-8, 2026" is three lines in the badge's corner and the month is
    # the least of what it says; the short form is one.
    short_dates = re.sub(r"^(\w{3})\w*", lambda m: m.group(1), site["dates"])
    as_url = lambda svg: "data:image/svg+xml;base64," + base64.b64encode(
        svg.encode("utf-8")).decode("ascii")
    art_url = as_url(art)
    ghost_url = as_url(ghost_layer[len('<div class="ghost">'):-len("</div>")]) if ghost_layer else ""

    def badge_card(role, hot, name="", name_ko="", affil=""):
        who = (f'<p class="name">{esc(name)}</p>'
               + (f'<p class="name-ko">{esc(name_ko)}</p>' if name_ko else "")
               + (f'<p class="affil">{esc(affil)}</p>' if affil else "")) if name else (
               '<div class="write"><i></i><i></i></div>')
        return (
            '<div class="card"><div class="ghost"></div><div class="art"></div>'
            '<div class="veil"></div><div class="pad">'
            f'<div class="top"><h1 class="mark">{esc(mark)} <span>{esc(year)}</span></h1>'
            f'<div class="when">{esc(short_dates)}<br>{esc(site["venue"])}, {esc(site["city"])}</div></div>'
            f'<div class="who"><span class="role{"" if hot else " plain"}">{esc(role)}</span>{who}</div>'
            '<div class="foot">'
            f'<p class="longname">{esc(site["full_name"].upper())}</p>'
            f'<div class="qr-plate">{qr_svg(site["url"], dark=PALETTE["ground2"], light=None)}</div>'
            "</div></div></div>")

    speaker_names = set()
    badge_cards = []
    for d in sessions(program):
        for b in d["blocks"]:
            for person in b["people"]:
                if person["name"] in speaker_names:
                    continue
                speaker_names.add(person["name"])
                badge_cards.append(badge_card(
                    "Speaker", True, person["name"],
                    person.get("name_ko", ""), person.get("affil", "")))
    for mbr in organizers["members"]:
        if mbr["name"] in speaker_names:
            continue
        badge_cards.append(badge_card(
            "Organiser", True, mbr["name"], mbr.get("name_ko", ""), mbr.get("affil", "")))
    badge_cards += [badge_card("Participant", False) for _ in range(4)]
    badges = "".join(badge_cards)

    rooms = "<br>".join(
        f'<b>{esc(r["label"])}</b> {esc(r["name"])}'
        for r in venue.get("rooms", [])) or esc(venue.get("address", ""))

    doc = tpl.format(
        art=art,
        name=esc(name),
        mark=esc(mark),
        year=esc(year),
        full_name=esc(site["full_name"]),
        theme_label=f"{site['year']} Theme",
        theme=esc(site["theme"]),
        eyebrow=esc(site.get("eyebrow") or ""),
        facts=facts,
        prog=programme_html(program, site.get("affiliations", {})),
        url=esc(site["url"].split("//")[-1].rstrip("/")),
        cta="Programme &amp; registration",
        qr=qr_svg(site["url"], dark=PALETTE["ground2"], light=None),
        hosts=esc(" · ".join(h["name"] for h in site["hosts"]["logos"])) if site.get("hosts") else "",
        listing=listing_html(program),
        month=month,
        stamp=f"{d0[1]}.{d0[0]}",
        venue_name=esc(venue["name"]),
        venue_addr=esc(venue.get("address", "")),
        venue_short=esc(f"{site['venue']}, {site['city']}"),
        bill=bill,
        sessions_list=sessions_list,
        organisers=organisers,
        days=esc(days),
        days_range=esc('–'.join(str(d['date']).split('-')[-1] for d in program['days'])),
        bill_academic=bill.replace("<sup>", "<span>(").replace("</sup>", ")</span>")
                          .replace("<li>", "<li><b>").replace("<span>(", "</b><span>("),
        dates_long=esc(site["dates"]),
        city=esc(site["city"]),
        country=esc(site["country"]),
        cta_short="Register",
        logos=logo_row([h["name"] for h in site["hosts"]["logos"]], PALETTE["cool"])
              if site.get("hosts") else "",
        acronym_name=acronym_html(site["full_name"], mark),
        # site.yml spells it "Korean workshop On Learning Theory" so the four
        # letters of the acronym can be picked out; set as a plain line that
        # casing reads as a typo, so it is normalised back here.
        long_name=esc(site["full_name"].title().replace(" On ", " on ")),
        ghost=ghost_layer,
        d1=esc(str(program["days"][0]["date"]).split("-")[-1]),
        d2=esc(str(program["days"][-1]["date"]).split("-")[-1]),
        yyyy=esc(str(program["days"][0]["date"]).split("-")[0]),
        mon3=month[:3].upper(),
        md1=".".join(str(program["days"][0]["date"]).split("-")[1:]).lstrip("0").replace(".0", "."),
        md2=".".join(str(program["days"][-1]["date"]).split("-")[1:]).lstrip("0").replace(".0", "."),
        days_long=esc(site["dates"]),
        day1=day_people[0],
        day2=day_people[1] if len(day_people) > 1 else "",
        names_flat=names_flat,
        programme=programme_block,
        dots="<i></i>" * 15,
        full_title=esc(" ".join(
            w if w.isupper() and len(w) > 1
            else w.lower() if w.lower() in ("on", "of", "and", "the", "for", "in")
            else w.capitalize()
            for w in site["full_name"].split())),
        reg_note=esc((site["hero_actions"][0].get("note") or "Opens soon")),
        badges=badges,
        art_url=art_url,
        ghost_url=ghost_url,
        blurb=esc(site.get("blurb", "")),
        rooms=rooms,
        day1_label=day_labels[0] if day_labels else "",
        day2_label=day_labels[1] if len(day_labels) > 1 else "",
        day1_grid=day_grids[0] if day_grids else "",
        day2_grid=day_grids[1] if len(day_grids) > 1 else "",
        day1_rows=day_rows[0] if day_rows else "",
        day2_rows=day_rows[1] if len(day_rows) > 1 else "",
        day1_span=esc(day_spans[0]) if day_spans else "",
        day2_span=esc(day_spans[1]) if len(day_spans) > 1 else "",
        day1_date=esc(str(program["days"][0]["date"]).replace("-", ".")[2:]),
        day2_date=esc(str(program["days"][-1]["date"]).replace("-", ".")[2:]),
        room=esc(venue["rooms"][0]["name"]) if venue.get("rooms") else esc(venue["name"]),
        **PALETTE,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    n = sum(len(b["people"]) for d in sessions(program) for b in d["blocks"])
    print(f"  {n} speakers across {sum(len(d['blocks']) for d in sessions(program))} sessions")
    print(f"  -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", help="the formula art SVG to inline")
    ap.add_argument("--photo", help="use a two-tone photograph instead of the formulas")
    ap.add_argument("--cutout", help="use a sky-removed PNG (see tools/cut-sky.py)")
    ap.add_argument("--ghost", metavar="IMAGE",
                    help="a faint photograph behind the formulas, as the website has")
    ap.add_argument("--duotone", metavar="SHADOW,HIGHLIGHT",
                    help="two colours for the photograph, e.g. '#1b2a4a,#ff8a75'")
    ap.add_argument("--silhouette", metavar="PNG",
                    help="a cut-out PNG whose alpha is filled flat in art_ink, "
                         "laid under the formulas so the subject reads as a mass")
    ap.add_argument("--palette", metavar="JSON",
                    help="override palette entries, e.g. '{\"ground\":\"#101010\"}'. "
                         "The artwork's own ink is recoloured to match art_ink.")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--layout",
                    choices=("stack", "listing", "festival", "academic", "civic",
                             "bauhaus", "banner", "xbanner", "social", "badge"),
                    default="stack",
                    help="a poster layout, or banner (5000x900mm) / xbanner (600x1800mm)")
    args = ap.parse_args()
    if args.palette:
        import json
        override = json.loads(args.palette)
        # The drawing carries its ink colour inside the file, so a new palette
        # has to reach in and change it too or the formulas keep the old one.
        OLD_ART_INK = PALETTE["art_ink"]
        PALETTE.update(override)
        if "art_ink" in override and args.art:
            src = Path(args.art)
            patched = src.with_name(src.stem + "__tinted.svg")
            patched.write_text(src.read_text(encoding="utf-8")
                               .replace(OLD_ART_INK, override["art_ink"]), encoding="utf-8")
            args.art = str(patched)
    main(args.art, args.out, args.layout, args.photo, args.cutout, args.duotone,
         args.ghost, args.silhouette)
