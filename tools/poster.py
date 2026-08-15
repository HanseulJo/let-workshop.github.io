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
import html
import io
import re
import sys
from pathlib import Path

try:
    import segno
    import yaml
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
    "rule": "rgba(255,255,255,.18)",
    "chip": "rgba(255,255,255,.34)",
}


def esc(s):
    return html.escape(str(s), quote=False)


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
  .wrap {{ position:absolute; inset:0; padding:24mm 24mm 20mm; display:flex; flex-direction:column; }}
  .eyebrow {{
    font-family:"JetBrains Mono",monospace; font-size:3.9mm; font-weight:500;
    letter-spacing:.2em; text-transform:uppercase; color:{ink};
    border:.3mm solid {chip}; border-radius:99mm; padding:1.9mm 4.4mm;
    align-self:flex-start; background:rgba(11,17,28,.62);
  }}
  .mid {{ margin-top:auto; }}
  h1 {{
    font-family:"Jost",sans-serif; font-weight:500; font-size:58mm; line-height:.88;
    letter-spacing:-.022em; margin:0 0 5mm; color:{ink};
  }}
  h1 b {{ font-weight:700; }}
  h1 .year {{ font-weight:300; color:{ink_dim}; }}
  .acronym {{
    font-family:"JetBrains Mono",monospace; font-size:5.1mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{cool}; margin:0 0 7mm;
  }}
  .theme {{
    font-family:"Inter Tight",sans-serif; font-size:7.4mm; font-weight:500;
    color:{ink}; margin:0 0 8mm;
  }}
  .theme b {{ font-weight:700; }}
  .facts {{
    display:flex; gap:12mm; font-family:"JetBrains Mono",monospace;
    font-size:4.6mm; font-weight:500; color:{ink}; margin:0 0 9mm;
  }}
  .facts span {{ color:{cool}; }}
  .rule {{ height:.3mm; background:{rule}; margin:0 0 6mm; }}
  /* The programme. Four columns of small type at the foot, the way a season
     card does it — the poster has to survive being read from a metre away for
     the name and from arm's length for the schedule. */
  .prog {{ display:grid; grid-template-columns:1fr 1fr; gap:14mm; }}
  .day h3 {{
    font-family:"Inter Tight",sans-serif; font-size:10mm; font-weight:700;
    color:{ink}; margin:0 0 1.6mm;
  }}
  .daysub {{
    font-family:"JetBrains Mono",monospace; font-size:4.6mm; letter-spacing:.12em;
    text-transform:uppercase; color:{hot}; margin:0 0 6.5mm;
  }}
  .sess {{ margin:0 0 8mm; break-inside:avoid; }}
  .sess h4 {{
    font-family:"JetBrains Mono",monospace; font-size:4.9mm; font-weight:500;
    letter-spacing:.13em; text-transform:uppercase; color:{cool};
    margin:0 0 2.6mm; display:flex; justify-content:space-between; gap:4mm;
  }}
  .clock {{ color:{cool_dim}; letter-spacing:.06em; }}
  .sess ul {{ margin:0; padding:0; list-style:none; }}
  .sess li {{
    font-family:"Inter Tight",sans-serif; font-size:9.4mm; color:{ink};
    line-height:1.14; margin:0 0 3.4mm;
  }}
  .sess li b {{ font-weight:700; }}
  .aff {{ color:{cool}; font-weight:500; font-size:6.4mm; }}
  .sess li i {{
    display:block; font-style:normal; font-family:"JetBrains Mono",monospace;
    font-size:4.6mm; letter-spacing:.06em; color:{cool_dim}; margin-top:.6mm;
  }}
  .tail {{
    display:flex; justify-content:space-between; align-items:flex-end; margin-top:8mm;
    font-family:"JetBrains Mono",monospace; font-size:3.9mm; letter-spacing:.1em;
    text-transform:uppercase; color:{cool}; gap:10mm;
  }}
  .tail b {{ color:{ink}; font-weight:500; }}
  /* The QR sits on its own light patch. A code drawn light-on-dark decodes on
     most phones but not all — the quiet zone and the polarity are the two
     things cheap decoders are strict about, so both are given properly. */
  .qr {{ display:flex; align-items:flex-end; gap:5mm; }}
  .qr-plate {{ width:30mm; height:30mm; background:{art_ink}; padding:1.6mm; border-radius:1mm; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .qr-say {{ text-align:right; }}
  .qr-say b {{ display:block; font-size:4.6mm; color:{ink}; letter-spacing:.06em; }}
  .qr-say span {{ display:block; font-size:3.2mm; color:{cool}; margin-top:1.2mm; text-transform:none; letter-spacing:.02em; }}
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
      <div class="prog">{prog}</div>
      <div class="tail">
        <span>{hosts}</span>
        <div class="qr">
          <div class="qr-say"><b>{cta}</b><span>{url}</span></div>
          <div class="qr-plate">{qr}</div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


def main(art_path, out_path):
    site = yaml.safe_load((DATA / "site.yml").read_text(encoding="utf-8"))
    program = yaml.safe_load((DATA / "program.yml").read_text(encoding="utf-8"))
    venue = yaml.safe_load((DATA / "venue.yml").read_text(encoding="utf-8"))

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
    doc = TEMPLATE.format(
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
    ap.add_argument("--art", required=True, help="the formula art SVG to inline")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    main(args.art, args.out)
