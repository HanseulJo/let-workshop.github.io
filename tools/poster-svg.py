#!/usr/bin/env python3
"""Turn a rendered poster page into one SVG that Illustrator can edit.

    python3 tools/poster-svg.py poster/festival.html -o kolt-a2.svg

Why this exists. The PDF Chrome prints is vector throughout, but it embeds
every webfont as a Type 3 font — each glyph as a little drawing procedure.
Illustrator opens that as paths. The geometry is editable, the words are not:
you cannot retype a name or change a size. Only fonts the system already had
survive as text (`pdffonts` on the sheet shows 21 Type 3 against 2 CID
TrueType, and the two are the one line set in Avenir Next).

So the text has to be handed over as text. The layout, though, is CSS — a flex
column, a shared grid, two writing modes, a baseline-aligned programme — and
none of that has an SVG equivalent. Reimplementing it would mean maintaining
the poster twice and having the two drift.

Instead the browser lays the page out as it always does, and this reads the
answer back: every text run's painted box, its computed font, its colour. Then
each run is written as an <text> at the position the browser put it. The
layout engine stays the only thing that does layout; the output is a flat list
of positioned words, which is exactly what a drawing program wants anyway.

What comes across:

  text     <text>, live and editable, one element per rendered line
  drawing  the formula art and the ghost photograph, inlined as nested <svg>
  logos    <image>, already data URIs on the page
  fills    any element painting a background, as <rect>
  rules    a border-top on its own, as <rect> one line thick

What does not: the fonts themselves. Illustrator will substitute unless Jost,
Inter Tight and JetBrains Mono are installed — they are in static/fonts as
woff2 and any converter will make OTFs. Everything else is self-contained.

Needs Chrome. Local tool only.
"""

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# The page is laid out in CSS pixels; A2 is 420x594mm, and 1mm is 96/25.4 px.
PX_PER_MM = 96.0 / 25.4

# Walks the laid-out page and reports what is painted where. Runs in the page
# because only the page knows where anything ended up.
PROBE = r"""
(() => {
  const out = {svgs: [], images: [], rects: [], texts: []};
  const seen = new Set();
  // The walk is in document order, which is the order the page paints in. SVG
  // has no z-index and paints in document order too, so carrying a counter
  // across all four kinds is what keeps a white QR plate under its code and a
  // rule on top of the drawing instead of beneath it.
  let seq = 0;
  const px = v => Math.round(v * 1000) / 1000;

  // A colour is worth painting if it is neither absent nor fully clear.
  const solid = c => c && c !== "transparent" && !/^rgba\(.*,\s*0\)$/.test(c);

  // Opacity is inherited multiplicatively down the tree, and it is usually set
  // on a wrapper rather than on the thing that paints — the photograph is held
  // down by .ghost{opacity:.3} around it, not by the <svg> itself. A flat list
  // of shapes has no ancestors to inherit from, so it is resolved here.
  const alpha = (el) => {
    let a = 1, p = el;
    while (p && p !== document.documentElement) {
      a *= parseFloat(getComputedStyle(p).opacity); p = p.parentElement;
    }
    return Math.round(a * 1000) / 1000;
  };

  const walk = (node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node, cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") return;
      const r = el.getBoundingClientRect();

      // An <svg> is already the thing we want; take it whole and stop, or its
      // thousands of formula <use> elements get walked one at a time.
      if (el.tagName.toLowerCase() === "svg" && !seen.has(el)) {
        seen.add(el);
        out.svgs.push({x: px(r.x), y: px(r.y), w: px(r.width), h: px(r.height),
                       op: alpha(el), markup: el.outerHTML, seq: seq++});
        return;
      }
      if (el.tagName.toLowerCase() === "img") {
        out.images.push({x: px(r.x), y: px(r.y), w: px(r.width), h: px(r.height),
                         src: el.src, op: alpha(el), seq: seq++});
        return;
      }
      if (solid(cs.backgroundColor) && r.width > 0 && r.height > 0) {
        out.rects.push({x: px(r.x), y: px(r.y), w: px(r.width), h: px(r.height),
                        fill: cs.backgroundColor, op: alpha(el), seq: seq++});
      }
      // A rule drawn as a border rather than as an element of its own.
      const bt = parseFloat(cs.borderTopWidth);
      if (bt > 0 && solid(cs.borderTopColor) && r.width > 0) {
        out.rects.push({x: px(r.x), y: px(r.y), w: px(r.width), h: px(bt),
                        fill: cs.borderTopColor, op: alpha(el), seq: seq++});
      }
      for (const c of el.childNodes) walk(c);
      return;
    }
    if (node.nodeType !== Node.TEXT_NODE) return;
    const text = node.nodeValue;
    if (!/\S/.test(text)) return;

    const el = node.parentElement, cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return;

    const op = alpha(el);

    const vertical = cs.writingMode.startsWith("vertical");
    // 180deg on a vertical run is what makes it read upward; anything else is
    // left alone.
    const flipped = /matrix\(-1,\s*0,\s*0,\s*-1/.test(cs.transform);

    // Where the baseline sits inside the box. The ink ascent varies with the
    // letters; the font's own ascent does not, which is what a baseline is.
    const m = document.createElement("canvas").getContext("2d");
    m.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const asc = m.measureText("Hxg").fontBoundingBoxAscent;

    // One run per painted line: a wrapped paragraph reports one rect per line,
    // and each needs its own <text> at its own position.
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    if (!rects.length) return;

    const shown = cs.textTransform === "uppercase" ? text.toUpperCase()
                : cs.textTransform === "lowercase" ? text.toLowerCase() : text;
    const words = shown.trim();

    // Splitting a wrapped run back into its lines needs the character offsets;
    // one rect is the common case and needs none of that.
    let parts = [words];
    if (rects.length > 1) {
      parts = [];
      let start = 0;
      for (let i = 1; i <= text.length; i++) {
        range.setStart(node, start); range.setEnd(node, i);
        if (range.getClientRects().length > parts.length + 1 || i === text.length) {
          parts.push(text.slice(start, i).trim()); start = i;
        }
      }
      parts = parts.filter(s => s.length);
      if (parts.length !== rects.length) parts = [words];   // give up, keep it whole
    }

    rects.forEach((r, i) => {
      const t = parts[i] !== undefined ? parts[i] : words;
      if (!t) return;
      out.texts.push({
        x: px(r.x), y: px(r.y), w: px(r.width), h: px(r.height),
        cx: px(r.x + r.width / 2), cy: px(r.y + r.height / 2),
        base: px(r.y + asc), text: t, vertical, flipped,
        family: cs.fontFamily, size: cs.fontSize, weight: cs.fontWeight,
        style: cs.fontStyle, track: cs.letterSpacing, fill: cs.color,
        op, seq: seq++,
      });
    });
  };

  walk(document.body);
  return JSON.stringify(out);
})()
"""


def probe(page_url, work):
    """Run the page in Chrome and read back what it painted."""
    # --dump-dom is the only channel out of headless Chrome here, so the probe
    # writes its answer into the document and the answer is parsed out of it.
    driver = work / "probe.html"
    driver.write_text(
        f'<iframe src="{page_url}" style="width:1587.4px;height:2245.04px;border:0"></iframe>'
    )
    inject = work / "inject.js"
    inject.write_text(PROBE)

    # Simpler: load the page itself and append a script that stashes the JSON.
    script = f"<script>window.addEventListener('load',()=>{{setTimeout(()=>{{" \
             f"const d=document.createElement('pre');d.id='__probe';" \
             f"d.textContent={PROBE};document.body.appendChild(d);}},1200);}});</script>"
    return script


def run_chrome(html_path, work):
    """Append the probe to a copy of the page and read the JSON back out."""
    src = Path(html_path).read_text(encoding="utf-8")
    script = ("<script>window.__probe = () => " + PROBE + ";</script>"
              "<script>window.addEventListener('load', () => setTimeout(() => {"
              "const p = document.createElement('pre'); p.id = '__out';"
              "p.textContent = window.__probe(); document.body.appendChild(p);"
              "}, 1500));</script>")
    probe_page = Path(html_path).with_name("__probe__.html")
    probe_page.write_text(src + script, encoding="utf-8")
    try:
        url = "http://localhost:%d/%s" % (PORT, probe_page.name)
        res = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--window-size=1610,2268", "--virtual-time-budget=60000",
             "--dump-dom", url],
            capture_output=True, text=True, timeout=180)
        dom = res.stdout
        m = re.search(r'<pre id="__out">(.*?)</pre>', dom, re.S)
        if not m:
            sys.exit("the probe did not report; is the page served on port %d?" % PORT)
        raw = (m.group(1).replace("&amp;", "&").replace("&lt;", "<")
               .replace("&gt;", ">").replace("&quot;", '"'))
        return json.loads(raw)
    finally:
        probe_page.unlink(missing_ok=True)


PORT = 8997


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fam(css_family):
    """First family in the stack, unquoted — what Illustrator will look for."""
    first = css_family.split(",")[0].strip()
    return first.strip("'\"")


def to_svg(data, out_path, title):
    W, H = 420 * PX_PER_MM, 594 * PX_PER_MM
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="420mm" height="594mm" viewBox="0 0 {W:.2f} {H:.2f}">',
        f"<title>{esc(title)}</title>",
    ]

    def op_attr(v):
        v = float(v)
        return "" if v >= 0.999 else f' opacity="{v:.3f}"'

    def rect_el(r):
        return (f'<rect x="{r["x"]}" y="{r["y"]}" width="{r["w"]}" height="{r["h"]}" '
                f'fill="{r["fill"]}"{op_attr(r["op"])}/>')

    def svg_el(s):
        markup = s["markup"]
        # Give the nested drawing an explicit box, replacing whatever box it
        # carried: on the page its size came from CSS, and the width and height
        # attributes still on the tag are the ones CSS overrode. Left in place
        # they are duplicates, and a duplicate attribute is not well-formed XML
        # — the file loads in a browser and fails everywhere stricter.
        head_end = markup.index(">")
        head = re.sub(r'\s(?:width|height|x|y)="[^"]*"', "", markup[:head_end])
        markup = (f'{head} x="{s["x"]}" y="{s["y"]}" '
                  f'width="{s["w"]}" height="{s["h"]}"' + markup[head_end:])
        if float(s["op"]) < 0.999:
            markup = f'<g opacity="{float(s["op"]):.3f}">{markup}</g>'
        return markup

    def image_el(im):
        return (f'<image x="{im["x"]}" y="{im["y"]}" width="{im["w"]}" height="{im["h"]}" '
                f'xlink:href="{im["src"]}"{op_attr(im["op"])} '
                f'preserveAspectRatio="xMidYMid meet"/>')

    def text_el(t):
        track = t["track"]
        track = "" if track in ("normal", "0px") else f' letter-spacing="{track}"'
        weight = f' font-weight="{t["weight"]}"' if t["weight"] not in ("400", "normal") else ""
        style = ' font-style="italic"' if t["style"] == "italic" else ""
        common = (f'font-family="{esc(fam(t["family"]))}" font-size="{t["size"]}"'
                  f'{weight}{style}{track} fill="{t["fill"]}"{op_attr(t["op"])}')
        if t["vertical"]:
            # Set horizontally and turned, which is what the type is: a rail
            # reading upward is a line rotated a quarter turn anticlockwise.
            # Anchored at the box's centre so the turn does not move it.
            deg = -90 if t["flipped"] else 90
            return (f'<text transform="translate({t["cx"]},{t["cy"]}) rotate({deg})" '
                    f'text-anchor="middle" dominant-baseline="central" {common}>'
                    f'{esc(t["text"])}</text>')
        return f'<text x="{t["x"]}" y="{t["base"]}" {common}>{esc(t["text"])}</text>'

    everything = ([(r["seq"], rect_el, r) for r in data["rects"]]
                  + [(s["seq"], svg_el, s) for s in data["svgs"]]
                  + [(i["seq"], image_el, i) for i in data["images"]]
                  + [(t["seq"], text_el, t) for t in data["texts"]])
    for _, render, item in sorted(everything, key=lambda e: e[0]):
        parts.append(render(item))

    parts.append("</svg>")
    Path(out_path).write_text("\n".join(parts), encoding="utf-8")
    return len(data["texts"]), len(data["svgs"]), len(data["images"]), len(data["rects"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("page", help="a rendered poster .html, in a directory served on port %d" % PORT)
    ap.add_argument("-o", "--out", default="poster.svg")
    ap.add_argument("--title", default="KOLT 2026 — A2 poster")
    args = ap.parse_args()

    if not Path(CHROME).exists():
        sys.exit("Chrome not found at %s" % CHROME)
    with tempfile.TemporaryDirectory() as work:
        data = run_chrome(args.page, Path(work))
    n = to_svg(data, args.out, args.title)
    size = Path(args.out).stat().st_size
    print(f"  {n[0]} text runs, {n[1]} drawings, {n[2]} images, {n[3]} fills")
    print(f"  -> {args.out} ({size // 1024} KB)")


if __name__ == "__main__":
    main()
