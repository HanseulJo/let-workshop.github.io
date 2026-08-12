#!/usr/bin/env python3
"""Render the link-preview card from the page's own hero.

    python3 build.py public && python3 tools/make-og.py

Writes static/og.jpg at 1200x630, the size Open Graph and X both crop to.

The card is a screenshot of the real hero rather than a separately designed
image, so the preview cannot drift from the site: same wordmark, same campus
plate, same dates. It needs Chrome, and it reads _site/2026/index.html — build
first, then run this, then build again so the file is copied into _site.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "_site" / "2026" / "index.html"
OUT = ROOT / "static" / "og.jpg"
W, H = 1200, 630

CHROME = next(
    (
        p
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            shutil.which("google-chrome") or "",
            shutil.which("chromium") or "",
        )
        if p and Path(p).exists()
    ),
    None,
)

# The hero is normally as tall as its content; here it is pinned to the card and
# the page chrome around it is taken out. Everything below the info bar goes:
# a preview is read at thumbnail size, so it carries the name and the facts.
SHOT_CSS = """
  .topbar, .hero-actions, footer, .band { display: none !important; }
  html, body { margin: 0 !important; padding: 0 !important; overflow: hidden !important; }
  .hero { min-height: %dpx; display: flex; align-items: center; padding: 0 !important; }
  .hero .wrap { max-width: none; padding: 0 64px; }
  .hero h1 { font-size: 88px !important; }
  .hero-meta { gap: 18px 34px !important; }
""" % H


def main() -> None:
    if CHROME is None:
        sys.exit("no Chrome found — install Google Chrome or Chromium")
    if not PAGE.exists():
        sys.exit(f"{PAGE.relative_to(ROOT)} not found — run `python3 build.py public` first")

    html = PAGE.read_text(encoding="utf-8")
    # The language toggle runs on load and would pick the browser's locale;
    # pin the card to English so the preview does not depend on who built it.
    html = html.replace("<head>", '<head><script>try{localStorage.setItem("kolt-lang","en");'
                                  'localStorage.setItem("kolt-theme","dark")}catch(e){}</script>', 1)
    html = html.replace("</head>", f"<style>{SHOT_CSS}</style></head>", 1)

    with tempfile.TemporaryDirectory() as tmp:
        shot_page = PAGE.parent / "_og-tmp.html"   # beside the page, so relative assets resolve
        shot_page.write_text(html, encoding="utf-8")
        png = Path(tmp) / "og.png"
        try:
            subprocess.run(
                [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                 f"--window-size={W},{H}", "--virtual-time-budget=8000",
                 f"--screenshot={png}", shot_page.as_uri()],
                check=True, capture_output=True,
            )
        finally:
            shot_page.unlink(missing_ok=True)
        if not png.exists():
            sys.exit("Chrome produced no screenshot")
        try:
            from PIL import Image
        except ModuleNotFoundError:
            sys.exit("needs Pillow: pip install pillow")
        Image.open(png).convert("RGB").save(OUT, "JPEG", quality=88, optimize=True, progressive=True)

    print(f"{OUT.relative_to(ROOT)}  {W}x{H}  ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
