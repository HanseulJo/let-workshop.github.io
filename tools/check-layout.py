#!/usr/bin/env python3
"""Assert the page's edges, at every width that matters.

    python3 build.py && python3 tools/check-layout.py

Two things go wrong on this page and neither is visible in a screenshot taken
at one size. Both are the same kind of mistake — a measurement written down in
one place that belongs to something else — and both come back the moment
someone changes the thing it was copied from. So they are checked rather than
remembered.

  no dead space below the end
      The tab bar is fixed over the bottom of the viewport on narrow screens,
      so the page carries padding underneath to keep its last line clear of it.
      That padding must be exactly the bar's height: short and the footer hides
      behind the bar, long and the page scrolls into emptiness. Where the bar is
      not shown the padding must be nothing at all. The page now measures the
      bar and follows it, and this is what proves it still does.

  nothing off the side
      Anything wider than the viewport gives the whole page a horizontal
      scrollbar, which on a phone reads as the layout being broken. A long
      unbroken word, a table, a fixed width in a media query that stopped
      matching — they all do it, and none of them announce themselves.

Widths are the breakpoints and the far side of each of them, plus the two
phones the page is actually read on.

Exit status is 1 if anything fails, so it can gate a deploy.

Needs Chrome. Local tool only.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = Path(__file__).resolve().parent.parent

# The breakpoints in style.css, each with the width just past it, and the two
# handsets. 780 and 720 are where the tab bar and the grid change.
WIDTHS = [1440, 1024, 900, 820, 781, 780, 721, 720, 430, 390, 360]

PROBE = """
<style>html,body{margin:0}iframe{border:0;display:block}</style>
<iframe id=f></iframe>
<script>
const widths = %s, page = %s, out = [];
const f = document.getElementById('f');
let i = 0;
function run() {
  if (i >= widths.length) {
    const p = document.createElement('pre');
    p.id = '__out'; p.textContent = JSON.stringify(out);
    document.body.appendChild(p);
    return;
  }
  const w = widths[i];
  f.style.width = w + 'px';
  f.style.height = '900px';
  // A fresh query string each time, so the load event fires for every width.
  f.src = page + '?probe=' + w;
  f.onload = () => setTimeout(() => {
    const win = f.contentWindow, d = f.contentDocument, de = d.documentElement;
    const foot = d.querySelector('footer');
    const footBottom = Math.round(foot.getBoundingClientRect().bottom + win.scrollY);
    const bar = d.querySelector('.tabs-mobile');
    const barShown = bar && getComputedStyle(bar).display !== 'none';
    const barH = barShown ? Math.round(bar.getBoundingClientRect().height) : 0;

    // Whether the page scrolls sideways is the browser's own answer, and it
    // is the only one worth asserting: plenty of elements are wider than the
    // viewport on purpose — a decorative layer bled past the edge, the tab
    // bar's list, a map's tiles — and every one of them is clipped by an
    // ancestor. Testing each element's box instead reports all of those and
    // then needs a growing list of exceptions to stay quiet.
    const wide = [];
    if (de.scrollWidth > w + 1) {
      // It really does. Now find what is doing it: an element wider than the
      // viewport with nothing above it that clips.
      d.querySelectorAll('*').forEach(e => {
        const r = e.getBoundingClientRect();
        if (r.width === 0 || (r.right <= w + 1 && r.left >= -1)) return;
        for (let a = e.parentElement; a; a = a.parentElement) {
          const cs = getComputedStyle(a);
          if (cs.overflowX !== 'visible' || cs.position === 'fixed') return;
        }
        wide.push({ tag: e.tagName, cls: (e.className || '').toString().slice(0, 40),
                    left: Math.round(r.left), right: Math.round(r.right) });
      });
    }

    out.push({ width: w, slack: de.scrollHeight - footBottom, barH,
               scrollWidth: de.scrollWidth, wide: wide.slice(0, 5) });
    i++; run();
  }, 1500);
}
run();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=str(ROOT / "_site"), help="the built site")
    ap.add_argument("--page", default="/2026/", help="page to check, as a path")
    ap.add_argument("--port", type=int, default=8994)
    args = ap.parse_args()

    site = Path(args.site)
    if not (site / args.page.strip("/") / "index.html").exists():
        sys.exit(f"no built page at {site}{args.page} — run build.py first")

    probe = site / "__check_layout__.html"
    probe.write_text(PROBE % (json.dumps(WIDTHS), json.dumps(args.page)), encoding="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)],
                              cwd=site, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2)
        budget = 4000 + 1800 * len(WIDTHS)
        dom = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--window-size=1600,1000",
             f"--virtual-time-budget={budget}",
             "--dump-dom", f"http://localhost:{args.port}/__check_layout__.html"],
            capture_output=True, text=True, timeout=budget / 1000 + 90).stdout
    finally:
        server.terminate()
        probe.unlink(missing_ok=True)

    m = re.search(r'<pre id="__out">(.*?)</pre>', dom, re.S)
    if not m:
        sys.exit("the probe did not report — is Chrome where this expects it?")
    rows = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&")
                      .replace("&lt;", "<").replace("&gt;", ">"))

    failures = []
    print(f"  {'width':>6}  {'below the end':>14}  {'bar':>5}  {'side':>6}")
    for r in rows:
        # The page may end exactly at the bar and nowhere else.
        slack_ok = r["slack"] == r["barH"]
        side_ok = not r["wide"] and r["scrollWidth"] <= r["width"] + 1
        print(f"  {r['width']:>6}  {r['slack']:>10}px {'ok' if slack_ok else 'BAD':>3}"
              f"  {r['barH']:>4}  {'ok' if side_ok else 'BAD':>6}")
        if not slack_ok:
            failures.append(f"{r['width']}px: {r['slack']}px below the footer, "
                            f"but the bar is {r['barH']}px — "
                            + ("dead space" if r["slack"] > r["barH"] else "content hidden behind the bar"))
        for w in r["wide"]:
            failures.append(f"{r['width']}px: <{w['tag'].lower()} class=\"{w['cls']}\"> "
                            f"runs {w['left']}..{w['right']}")

    if failures:
        print("\n  FAILED")
        for f in failures:
            print("   ", f)
        sys.exit(1)
    print(f"\n  {len(rows)} widths, no dead space and nothing off the side")


if __name__ == "__main__":
    main()
