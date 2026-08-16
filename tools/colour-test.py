#!/usr/bin/env python3
"""Render the sheet in a range of colour schemes, to be looked at side by side.

    python3 tools/colour-test.py --art-dark a2-fine.svg --art-light a2-light.svg \
        --ghost ~/Downloads/postech.jpg -o ~/Downloads/kolt-poster-a2/_color_test

Colour on this sheet is four decisions, not one: the ground everything sits on,
the ink the formulas are drawn in, the colour the type is set in, and the one
accent the date and the mark are spent on. Change any of them and the other
three have to be re-chosen — a scheme is the set, which is why these are listed
as sets rather than as a list of accent colours to try against a fixed ground.

Two of them need the drawing regenerated rather than recoloured. A light ground
wants ink on paper, which is the opposite of what the artwork does: it draws
light marks and lets the dark ground show between them. `tools/formula-art.py
--invert` produces the other one, and the schemes below say which they want.

Contrast is checked, not eyeballed. Every scheme reports the ratio of its type
against its ground, and anything under 4.5:1 is printed with a warning — a
poster is read across a room and in whatever light the corridor has.

Needs Chrome. Local tool only.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HERE = Path(__file__).resolve().parent

# ground   what the sheet is printed on
# ground2  the shade behind the QR plate and the darkest stop of the veil
# art_ink  the formulas
# ink      the type
# cool     affiliations and other second-voice text
# hot      the one accent: the mark, the date, the session labels
# band     a darker strip, used by some layouts
# art      which drawing the scheme needs
SCHEMES = [
    # ── where it stands today ─────────────────────────────────────────────
    dict(name="00-current", art="dark", ground="#0f1826", ground2="#0b111c",
         art_ink="#b9cbe4", ink="#f5f5f7", cool="#93a2b8", hot="#ff8a75", band="#0b1523"),

    # ── the same night, other accents ─────────────────────────────────────
    dict(name="01-night-acid", art="dark", ground="#0d1420", ground2="#080d16",
         art_ink="#9fb4d0", ink="#f2f5f2", cool="#8b9bb0", hot="#c6f24f", band="#080d16"),
    dict(name="02-night-cyan", art="dark", ground="#0b1524", ground2="#070f1a",
         art_ink="#a8c4de", ink="#eef6fb", cool="#8aa2ba", hot="#3fd8e8", band="#070f1a"),
    dict(name="03-night-gold", art="dark", ground="#111521", ground2="#0b0e17",
         art_ink="#bcbfd0", ink="#f6f3ec", cool="#9a9aa8", hot="#f0b429", band="#0b0e17"),
    dict(name="04-night-magenta", art="dark", ground="#120f1e", ground2="#0c0a16",
         art_ink="#b3aed2", ink="#f4f1fa", cool="#9a94b8", hot="#ff4d9d", band="#0c0a16"),

    # ── other grounds, still dark ─────────────────────────────────────────
    dict(name="05-forest-sand", art="dark", ground="#0e1c17", ground2="#091310",
         art_ink="#a7c6b7", ink="#f2f4ee", cool="#8ba699", hot="#e8b578", band="#091310"),
    dict(name="06-plum-rose", art="dark", ground="#1a1020", ground2="#120a17",
         art_ink="#c3a8cc", ink="#f7f0f7", cool="#a892ae", hot="#ff7ab6", band="#120a17"),
    dict(name="07-oxblood-cream", art="dark", ground="#2a0f12", ground2="#1d090c",
         art_ink="#d3a9a4", ink="#f7efe6", cool="#bb948f", hot="#f5c86b", band="#1d090c"),
    dict(name="08-klein-white", art="dark", ground="#101a5c", ground2="#0a1244",
         art_ink="#8f9fdc", ink="#ffffff", cool="#a3aee0", hot="#ffd23f", band="#0a1244"),
    dict(name="09-ink-only", art="dark", ground="#141414", ground2="#0d0d0d",
         art_ink="#b8b8b8", ink="#fafafa", cool="#9a9a9a", hot="#fafafa", band="#0d0d0d"),

    # ── light grounds: ink on paper, the drawing inverted ─────────────────
    dict(name="10-paper-red", art="light", ground="#f4f1ea", ground2="#e6e0d4",
         art_ink="#2b3444", ink="#141414", cool="#6b6b6b", hot="#e8503a", band="#e6e0d4"),
    dict(name="11-bone-navy", art="light", ground="#eee9df", ground2="#ddd6c8",
         art_ink="#243352", ink="#16203a", cool="#5f6b82", hot="#f0662a", band="#ddd6c8"),
    dict(name="12-lavender-black", art="light", ground="#c9bdf5", ground2="#b3a4ef",
         art_ink="#2a2340", ink="#100d1a", cool="#4b4266", hot="#100d1a", band="#b3a4ef"),
    dict(name="13-mint-ink", art="light", ground="#d8ece0", ground2="#c3e0d1",
         art_ink="#183a2c", ink="#0e2019", cool="#4a6a5c", hot="#e0452f", band="#c3e0d1"),
    dict(name="14-sun-black", art="light", ground="#f7d94c", ground2="#eccb2f",
         art_ink="#3a3316", ink="#141208", cool="#5c5426", hot="#141208", band="#eccb2f"),
    dict(name="15-sky-navy", art="light", ground="#cfe4f5", ground2="#b5d4ee",
         art_ink="#16324f", ink="#0d2137", cool="#456080", hot="#ff5a36", band="#b5d4ee"),

    # ── the palettes the trade is actually talking about for 2026 ─────────
    # Pantone's Cloud Dancer is a soft white, and the year's advice is that the
    # interest should come from contrast rather than from one colour; the
    # fashion-week brights below are the ones named against those neutrals.
    dict(name="16-cloud-dancer", art="light", ground="#f0eeeb", ground2="#dedbd6",
         art_ink="#3a3a38", ink="#1a1a19", cool="#6e6e6a", hot="#c8553d", band="#dedbd6"),
    dict(name="17-putty-black", art="light", ground="#ddd6ca", ground2="#c9c0b1",
         art_ink="#2e2b26", ink="#141210", cool="#5e584f", hot="#141210", band="#c9c0b1"),
    dict(name="18-lava-falls", art="dark", ground="#1c1210", ground2="#130b0a",
         art_ink="#c9a99c", ink="#f7f1ec", cool="#a8918a", hot="#e2482c", band="#130b0a"),
    dict(name="19-teaberry", art="light", ground="#f2e2e6", ground2="#e6cdd4",
         art_ink="#3d2530", ink="#22141b", cool="#6b4f5b", hot="#e03a6d", band="#e6cdd4"),
    dict(name="20-burnished-lilac", art="dark", ground="#241d2e", ground2="#191322",
         art_ink="#b6a8c8", ink="#f3eef8", cool="#9c8fae", hot="#d9c26b", band="#191322"),
    dict(name="21-pale-banana", art="light", ground="#f4ebb8", ground2="#e6d98f",
         art_ink="#2f2c1a", ink="#191708", cool="#5f5a3c", hot="#2a4bd8", band="#e6d98f"),
    dict(name="22-mandarin", art="dark", ground="#141414", ground2="#0c0c0c",
         art_ink="#b8b0a6", ink="#faf7f2", cool="#98918a", hot="#ff6a13", band="#0c0c0c"),
    dict(name="23-amethyst", art="dark", ground="#171033", ground2="#0f0a24",
         art_ink="#a99ada", ink="#f2eefc", cool="#9184bf", hot="#7cf0c4", band="#0f0a24"),

    # ── the split: the sky one flat field, the campus another ─────────────
    # The drawing is made from the sky-removed PNG itself, alpha and all. The
    # solver has to put something in every cell it is given, so a sky
    # composited onto white still came out under an even wash of the lightest
    # formulas; handed the transparency it drops those cells entirely and the
    # sheet's own colour stands there as a plain field. The building is the only thing drawn, in a colour chosen against
    # that field rather than blended into it. No photograph behind these — a
    # ghost in the sky would fill the very area the split depends on.
    dict(name="30-split-yellow-indigo", art="split", ground="#f7c815", ground2="#e3b400",
         art_ink="#2a2a8f", ink="#1a1a4a", cool="#4a4a9e", hot="#2a2a8f", band="#e3b400"),
    dict(name="31-split-mint-indigo", art="split", ground="#2fd7a8", ground2="#1fbf93",
         art_ink="#231a5c", ink="#14113a", cool="#3d3178", hot="#231a5c", band="#1fbf93"),
    dict(name="32-split-lavender-black", art="split", ground="#c9bdf5", ground2="#b3a4ef",
         art_ink="#16121f", ink="#16121f", cool="#4b4266", hot="#e8503a", band="#b3a4ef"),
    dict(name="33-split-coral-navy", art="split", ground="#ff8a75", ground2="#f0705a",
         art_ink="#0f1826", ink="#0f1826", cool="#3d4c63", hot="#0f1826", band="#f0705a"),
    dict(name="34-split-sky-orange", art="split", ground="#9ed8f5", ground2="#7cc4e8",
         art_ink="#1b2a4a", ink="#0d1a30", cool="#41567a", hot="#ff5a1f", band="#7cc4e8"),
    dict(name="35-split-bone-red", art="split", ground="#efe9dd", ground2="#ddd4c2",
         art_ink="#c1281c", ink="#1a1613", cool="#6b6157", hot="#c1281c", band="#ddd4c2"),
]

# What a split scheme needs on top of its colours. The plate is what makes the
# campus a mass rather than a tint — the formulas alone are thin strokes, and a
# field of thin strokes reads as a tone at any distance. And the veil has to be
# taken almost all the way off at the top or it repaints the flat sky in the
# ground colour; it comes back down the sheet, where the programme has to be
# read off it.
SPLIT_EXTRAS = dict(veil1=".02", veil2=".02", veil3=".44", veil4=".86", veil5=".97")


def luminance(hex_colour):
    c = hex_colour.lstrip("#")
    channels = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art-dark", required=True, help="artwork for dark grounds")
    ap.add_argument("--art-light", required=True, help="artwork for light grounds (--invert)")
    ap.add_argument("--art-split", help="artwork drawn from the sky-removed photograph")
    ap.add_argument("--silhouette", help="alpha PNG of the subject, filled flat under the split drawings")
    ap.add_argument("--ghost", help="the photograph behind the formulas")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--width", type=int, default=900, help="pixel width of each PNG")
    ap.add_argument("--port", type=int, default=8995)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_html"
    work.mkdir(exist_ok=True)
    # The fonts have to sit next to the pages, as they do for every other export.
    fonts = work / "fonts"
    if not fonts.exists():
        fonts.symlink_to((HERE.parent / "static/fonts").resolve())

    print(f"{'scheme':22}{'type/ground':>12}  {'accent/ground':>14}")
    for scheme in SCHEMES:
        art = {"dark": args.art_dark, "light": args.art_light,
               "split": args.art_split or args.art_light}[scheme["art"]]
        palette = {k: v for k, v in scheme.items() if k not in ("name", "art", "ghost")}
        if scheme["art"] == "split":
            palette.update(SPLIT_EXTRAS)
        cmd = [sys.executable, str(HERE / "poster.py"), "--art", art,
               "--layout", "festival", "--palette", json.dumps(palette),
               "-o", str(work / f"{scheme['name']}.html")]
        if scheme["art"] == "split" and args.silhouette:
            cmd += ["--silhouette", args.silhouette]
        elif args.ghost and scheme.get("ghost", True):
            cmd += ["--ghost", args.ghost]
        subprocess.run(cmd, capture_output=True, check=True)
        ct = contrast(scheme["ink"], scheme["ground"])
        ca = contrast(scheme["hot"], scheme["ground"])
        flag = "  <- type under 4.5:1" if ct < 4.5 else ""
        flag += "  <- accent under 3:1" if ca < 3 else ""
        print(f"  {scheme['name']:20}{ct:9.1f}:1  {ca:12.1f}:1{flag}")

    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)],
                              cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import time
        time.sleep(2)
        scale = args.width / 1610
        for scheme in SCHEMES:
            subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                 f"--force-device-scale-factor={scale:.4f}",
                 "--window-size=1610,2268", "--virtual-time-budget=45000",
                 f"--screenshot={out / (scheme['name'] + '.png')}",
                 f"http://localhost:{args.port}/{scheme['name']}.html"],
                capture_output=True)
    finally:
        server.terminate()
    print(f"\n  {len(SCHEMES)} PNGs -> {out}")


if __name__ == "__main__":
    main()
