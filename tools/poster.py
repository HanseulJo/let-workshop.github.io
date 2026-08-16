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
  @font-face {{ font-family:"Inter Tight"; font-weight:500 700; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
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
    font-family:"Inter Tight",sans-serif; font-size:6.6mm; font-weight:500;
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
    font-family:"Inter Tight",sans-serif; font-size:9.4mm; font-weight:700;
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
    font-family:"Inter Tight",sans-serif; font-size:9.4mm; color:{ink};
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
  @font-face {{ font-family:"Inter Tight"; font-weight:500 700; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  /* One ink on one ground, and every division drawn as a hairline rule. The
     layout is a stack of boxes with nothing between them, so the sheet has no
     margins in the usual sense — the rules are the margins. */
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{art_ink}; box-sizing:border-box; padding:10mm;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
    font-family:"Inter Tight",sans-serif;
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
  @font-face {{ font-family:"Inter Tight"; font-weight:500 700; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Inter Tight",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .art {{ position:absolute; inset:0; overflow:hidden; }}
  .art svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .ghost {{ position:absolute; inset:0; overflow:hidden; opacity:.3; }}
  .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* Held well back. In the reference the ground is a soft bloom that the type
     sits on without contest; ours is a field of small marks, which is busier,
     so it is dimmed further than a photograph would need to be. */
  .veil {{ position:absolute; inset:0; }}
  .veil svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .wrap {{ position:absolute; inset:0; padding:20mm 20mm 16mm; display:flex; flex-direction:column; }}
  .top {{ display:flex; justify-content:space-between; align-items:flex-start; }}
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:32mm;
    line-height:1; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .stamps {{
    font-family:"JetBrains Mono",monospace; font-size:3.8mm; letter-spacing:.16em;
    text-transform:uppercase; color:{hot}; text-align:right; line-height:1.7;
  }}
  /* Mixed case, and the four letters of the acronym in the accent — the name
     is written so that K, O, L and T fall where they do, and capitals would
     hide it. */
  /* One quiet line under the mark. Picking the acronym's letters out in the
     accent explained where KOLT comes from and looked like it was explaining
     it; all caps, light and held back says the same thing without pointing. */
  .longname {{
    font-family:"Jost",sans-serif; font-weight:400; font-size:6.2mm;
    letter-spacing:.16em; text-transform:uppercase; color:{ink};
    opacity:.62; margin:4.5mm 0 0;
  }}
  .cols h4 {{
    font-family:"JetBrains Mono",monospace; font-size:3.4mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{hot}; margin:7mm 0 2mm;
  }}
  .orgs {{ margin:0; padding:0; list-style:none; }}
  .orgs li {{
    font-family:"Inter Tight",sans-serif; font-size:4.6mm; font-weight:600;
    color:{ink}; line-height:1.5;
  }}
  .orgs li span {{ font-weight:400; color:{cool}; }}
  .cols .theme {{
    font-family:"Inter Tight",sans-serif; font-size:5mm; font-weight:600;
    color:{ink}; margin:0; line-height:1.3;
  }}
  /* The two rotated blocks down the left edge. */
  .rails {{ position:absolute; left:20mm; top:118mm; display:flex; gap:9mm; }}
  .rail {{
    writing-mode:vertical-rl; transform:rotate(180deg);
    font-family:"Inter Tight",sans-serif; color:{hot};
  }}
  .rail b {{ display:block; font-size:10mm; font-weight:700; letter-spacing:-.012em; }}
  .rail span {{
    display:block; font-family:"JetBrains Mono",monospace; font-size:4.6mm;
    letter-spacing:.06em; margin-right:3mm;
  }}
  /* The programme, against one right edge. */
  .bill {{ margin:auto 0 12mm auto; text-align:right; }}

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
  .prog-grid i {{ font-style:normal; white-space:nowrap; align-self:baseline; }}
  .prog-grid i.dayrow {{ padding-top:5mm; }}
  .prog-grid em {{
    font-style:normal; font-family:"Inter Tight",sans-serif; font-size:10.5mm;
    font-weight:600; line-height:1.22; letter-spacing:-.018em; color:{ink};
    white-space:nowrap;
  }}
  .prog-grid span {{
    font-family:"Inter Tight",sans-serif; font-size:6.2mm; font-weight:400;
    color:{cool}; white-space:nowrap;
  }}
  /* The session, named once over the people in it. No hour with it: the title
     says what the block is, which is what a reader standing in front of the
     sheet wants; the times are on the page the code leads to. */
  .prog-grid i b {{
    display:block; font-family:"JetBrains Mono",monospace; font-size:3.8mm;
    font-weight:500; letter-spacing:.14em; text-transform:uppercase;
    color:{hot}; margin-bottom:.8mm;
  }}
  .prog-grid i u {{
    display:block; text-decoration:none; font-family:"Jost",sans-serif;
    font-size:7.6mm; font-weight:600; letter-spacing:-.01em; color:{ink};
  }}
  .prog-grid i b {{ margin-bottom:0; }}
  .dayrule {{
    grid-column:1 / -1; width:100%; height:0; margin:4.5mm 0 3.5mm;
    border:0; border-top:.4mm solid rgba(255,255,255,.34);
  }}
  .dates {{ display:flex; justify-content:space-between; align-items:flex-end; gap:14mm; margin:0; }}
  .month {{
    font-family:"Jost",sans-serif; font-weight:400; font-size:23mm;
    line-height:1; letter-spacing:-.02em; color:{hot};
  }}
  .stack {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:23mm;
    line-height:1.02; letter-spacing:-.03em; color:{hot};
  }}
  /* The venue lives in the rail; the country is the one thing neither the rail
     nor the stack says, so it goes with the day. */
  .datesub {{ display:none; }}
  .cols {{
    display:grid; grid-template-columns:1fr 1fr; gap:14mm; margin-top:8mm;
    font-family:"Inter Tight",sans-serif; align-items:start;
  }}
  .cols h4 {{
    font-family:"JetBrains Mono",monospace; font-size:3.6mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{hot}; margin:0 0 3mm;
  }}
  .cols ul {{ margin:0; padding:0; list-style:none; }}
  .cols li {{
    font-size:5.2mm; font-weight:600; line-height:1.42; color:{ink};
    text-transform:uppercase; letter-spacing:.02em;
  }}
  .cols li span {{ font-weight:400; color:{cool}; text-transform:none; letter-spacing:0; }}
  .mid {{ text-align:center; }}
  .mid ul li {{ text-transform:none; font-weight:500; }}
  .r {{ text-align:right; }}
  .marks {{ display:flex; align-items:flex-end; gap:9mm; }}
  .marks img {{ height:9mm; width:auto; display:block; opacity:.72; }}
  .foot {{
    display:flex; justify-content:space-between; align-items:flex-end; margin-top:8mm;
    font-family:"JetBrains Mono",monospace; font-size:3.8mm; letter-spacing:.14em;
    text-transform:uppercase; color:{cool};
  }}
  .qr-plate {{ width:32mm; height:32mm; background:{art_ink}; padding:1.6mm; box-sizing:border-box; }}
  .foot .cta {{ text-align:right; }}
  .foot .cta b {{ display:block; font-family:"Inter Tight",sans-serif; font-size:4.4mm;
                  font-weight:700; color:{hot}; margin-bottom:2.5mm; letter-spacing:0;
                  text-transform:none; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style>
<div class="sheet">
  {ghost}<div class="art">{art}</div>
  <div class="veil"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 100" preserveAspectRatio="none">
    <defs><linearGradient id="v" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ground}" stop-opacity=".72"/>
      <stop offset=".22" stop-color="{ground}" stop-opacity=".50"/>
      <stop offset=".52" stop-color="{ground}" stop-opacity=".62"/>
      <stop offset=".70" stop-color="{ground}" stop-opacity=".90"/>
      <stop offset="1" stop-color="{ground}" stop-opacity=".985"/>
    </linearGradient></defs>
    <rect width="10" height="100" fill="url(#v)"/>
  </svg></div>
  <div class="rails">
    <div class="rail"><b>{venue_short}</b><span>{venue_name} &middot; {country}</span></div>
    <div class="rail"><b>Registration</b><span>{reg_note} &middot; {url}</span></div>
  </div>
  <div class="wrap">
    <div class="top">
      <div><h1 class="mark">{mark} <span>{year}</span></h1>
        <p class="longname">{long_upper}</p></div>
      <div class="stamps">{eyebrow}</div>
    </div>
    <div class="bill"><div class="prog-grid">{programme}</div></div>
    <div class="panel">
      <div class="dates">
        <div class="stack">{yyyy}.<br>{md1}–<br>{md2}</div>
        <div class="month">{month}</div>
      </div>
      <div class="cols">
        <div><h4>Organisers</h4><ul class="orgs">{organisers}</ul></div>
        <div class="r"><h4>Theme</h4><p class="theme">{theme}</p></div>
      </div>
      <div class="foot"><span class="marks">{logos}</span>
        <div class="cta"><b>{cta_short}</b><div class="qr-plate">{qr}</div></div></div>
    </div>
  </div>
</div>
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
  @font-face {{ font-family:"Inter Tight"; font-weight:500 700; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Inter Tight",sans-serif;
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
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:24mm;
    line-height:1.05; letter-spacing:-.02em; margin:0 0 10mm; color:#fff;
  }}
  .when {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:11mm;
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
    font-family:"Inter Tight",sans-serif; font-size:7mm; font-weight:700;
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
    display:block; font-family:"Inter Tight",sans-serif; font-size:6.4mm;
    font-weight:700; color:{gold}; margin-top:3.5mm;
  }}
  .site {{
    position:absolute; left:24mm; right:24mm; bottom:9mm;
    font-family:"Inter Tight",sans-serif; font-size:5.6mm; font-weight:500;
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
  @font-face {{ font-family:"Inter Tight"; font-weight:500 700; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
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
    writing-mode:vertical-rl; margin:0; font-family:"Inter Tight",sans-serif;
    font-weight:700; font-size:19mm; letter-spacing:.06em; line-height:1;
    text-transform:uppercase; color:{carbon};
  }}
  .rail2 {{
    position:absolute; right:12mm; top:34mm;
    writing-mode:vertical-rl; font-family:"Inter Tight",sans-serif;
    font-weight:700; font-size:11mm; letter-spacing:.1em; text-transform:uppercase;
    color:{carbon};
  }}
  .blurb {{
    position:absolute; right:14mm; top:300mm; width:60mm;
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:7mm;
    line-height:1.3; color:{carbon};
  }}
  .left {{ position:absolute; left:26mm; top:104mm; width:146mm; }}
  .kicker {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:6.4mm;
    letter-spacing:.06em; text-transform:uppercase; margin:0 0 6mm; line-height:1.24;
  }}
  .when {{ font-family:"Inter Tight",sans-serif; font-weight:700; font-size:9mm; line-height:1.18; margin:0 0 3mm; }}
  .where {{ font-size:4.8mm; line-height:1.4; color:{carbon2}; margin:0 0 14mm; }}
  .grp {{ margin:0 0 9mm; }}
  .grp h4 {{
    font-family:"Inter Tight",sans-serif; font-weight:500; font-size:4.2mm;
    letter-spacing:.1em; text-transform:uppercase; color:{carbon2}; margin:0 0 2.5mm;
  }}
  .grp ul {{ margin:0; padding:0; list-style:none; }}
  .grp li {{ margin:0 0 3.4mm; }}
  .grp b {{ display:block; font-family:"Inter Tight",sans-serif; font-weight:700; font-size:8mm; line-height:1.1; }}
  .grp span {{ display:block; font-size:4.4mm; color:{carbon2}; line-height:1.34; margin-top:.8mm; }}
  .side {{ position:absolute; right:14mm; top:336mm; width:104mm; font-size:4.8mm; line-height:1.46; color:{carbon}; }}
  .cols h4 {{
    font-family:"Inter Tight",sans-serif; font-weight:500; font-size:4mm;
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
  @font-face {{ font-family:"Inter Tight"; font-weight:500 700; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
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
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:78mm;
    line-height:.86; letter-spacing:-.045em; text-transform:lowercase;
  }}
  .motto {{
    position:absolute; left:24mm; top:246mm; margin:0; width:64mm;
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:11mm;
    line-height:1.18; letter-spacing:-.02em; text-transform:lowercase;
  }}
  .motto i {{ font-style:normal; color:{accent}; }}
  .meta {{ position:absolute; left:228mm; top:30mm; width:110mm; font-size:6.4mm; line-height:1.44; text-transform:lowercase; }}
  .meta .lead {{ color:{carbon2}; margin:0 0 6mm; }}
  .meta .big {{ font-family:"Inter Tight",sans-serif; font-weight:700; font-size:8mm; line-height:1.24; margin:0 0 5mm; }}
  .meta .red {{ color:{accent}; font-weight:700; margin:0 0 8mm; }}
  .meta .hours {{ color:{carbon2}; margin:0; }}
  .dates {{
    position:absolute; right:22mm; top:26mm; text-align:right;
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:19mm; line-height:1.1;
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
    orgs = "".join(
        f'<li>{esc(m["name"])} <span>{esc(m.get("affil", ""))}</span></li>'
        for m in organizers["members"]
    )
    days = " ".join(str(d["date"]).split("-")[-1] for d in program["days"])
    return "".join(bill), "".join(sess), orgs, days


def main(art_path, out_path, layout="stack", photo=None, cutout=None, duotone=None, ghost=None):
    site = yaml.safe_load((DATA / "site.yml").read_text(encoding="utf-8"))
    program = yaml.safe_load((DATA / "program.yml").read_text(encoding="utf-8"))
    venue = yaml.safe_load((DATA / "venue.yml").read_text(encoding="utf-8"))

    ghost_layer = ""
    if ghost:
        # The same two layers the website's hero uses. The formulas alone are a
        # drawing of the photograph; the photograph faintly behind them is what
        # holds the shape together between the marks, and it is the reason the
        # hero reads as a place rather than as a texture. Held right down — it
        # is there to be felt, not seen.
        light_ground = layout in ("civic", "bauhaus")
        gw, gh = (1700, 820) if layout == "civic" else (1700, 2398)
        if layout == "listing":
            gw, gh = 1700, 1520
        elif layout == "bauhaus":
            gw, gh = 1000, 1360
        ghost_layer = (
            '<div class="ghost">'
            + photo_svg(ghost,
                        PALETTE["paper"] if light_ground else "#0a111d",
                        PALETTE["carbon"] if light_ground else PALETTE["art_ink"],
                        gw, gh)
            + "</div>")

    if cutout:
        light_ground = layout in ("civic", "bauhaus")
        w, h = (1700, 820) if layout == "civic" else (1700, 2398)
        if layout == "listing":
            w, h = 1700, 1520
        elif layout == "bauhaus":
            w, h = 1000, 1360
        art = cutout_svg(
            cutout,
            PALETTE["paper"] if light_ground else "#24374f",
            PALETTE["carbon"] if light_ground else "#e4edfa",
            w, h,
        )
    elif photo:
        # Light grounds want ink on paper; dark ones want light on the field.
        light_ground = layout in ("civic", "bauhaus")
        w, h = (1700, 820) if layout == "civic" else (1700, 2398)
        if layout == "listing":
            w, h = 1700, 1520
        elif layout == "bauhaus":
            w, h = 1000, 1360
        shadow, highlight = (
            duotone.split(",") if duotone else
            ((PALETTE["paper"], PALETTE["carbon"]) if light_ground
             else ("#0a111d", PALETTE["art_ink"]))
        )
        art = photo_svg(photo, shadow, highlight, w, h)
    else:
        art = Path(art_path).read_text(encoding="utf-8")
        if "preserveAspectRatio" not in art.split(">", 1)[0]:
            art = art.replace("<svg ", '<svg preserveAspectRatio="xMidYMid slice" ', 1)

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
           "civic": CIVIC, "bauhaus": BAUHAUS}.get(layout, TEMPLATE)
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
        label = esc(d["label"].split("·")[-1].strip()) if "·" in d["label"] else esc(d["label"])
        first = True
        for b in d["blocks"]:
            for k, p2 in enumerate(b["people"]):
                if k == 0 and first:
                    slots.append(f'<i class="dayrow"><u>{label}</u></i><em></em><span></span>')
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
        long_upper=esc(site["full_name"].upper()),
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
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--layout",
                    choices=("stack", "listing", "festival", "academic", "civic", "bauhaus"),
                    default="stack",
                    help="stack, listing, festival, or academic")
    args = ap.parse_args()
    main(args.art, args.out, args.layout, args.photo, args.cutout, args.duotone, args.ghost)
