#!/usr/bin/env python3
"""Render the KOLT site from data/*.yml + content/*.md.

    python3 build.py            # build every variant into _site/
    python3 build.py public     # just the page that gets deployed
    python3 build.py --out dist # somewhere else

Output is generated and gitignored: change the YAML, re-run, never hand-edit
the HTML. CI builds `public` only, so the invite and internal pages that carry
unpublished information cannot reach the live site.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

try:
    import markdown as md
    import yaml
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from markupsafe import Markup, escape
except ModuleNotFoundError as exc:  # pragma: no cover - setup hint
    sys.exit(f"missing dependency '{exc.name}'\n  pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
CALENDAR_FILE = "programme.ics"

EN_DASH = "–"


# ---------------------------------------------------------------- helpers


def load(name: str) -> dict:
    with (DATA / name).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def deployed_url(fallback: str) -> str:
    """Where this build will actually be served from.

    canonical and the og: tags carry an absolute URL, so hardcoding one means
    every deployment target needs its own commit — the staging repo and the
    live repo could never hold the same tree. In CI the answer is already in
    the environment, so take it from there and keep one history for both.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return fallback  # local build: whatever site.yml says
    owner, name = repo.split("/", 1)
    root = f"https://{owner.lower()}.github.io/"
    if name.lower() != f"{owner.lower()}.github.io":
        root += f"{name}/"
    # The page itself lives under the edition directory.
    return root + fallback.rstrip("/").rsplit("/", 1)[-1] + "/"


def minutes(hhmm: str) -> int:
    """'09:30' -> 570."""
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (AttributeError, ValueError):
        raise SystemExit(f"bad time {hhmm!r}: expected \"HH:MM\"") from None


def clock(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def human_span(total: int) -> str:
    """90 -> '1 h 30 min', 40 -> '40 min'."""
    hours, mins = divmod(total, 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    return f"{hours} h" if hours else f"{mins} min"


# ---------------------------------------------------------------- colours

# How far each accent colour is blended toward white to make the box fill.
# 0.88 reproduces the Material "50" tints the palette was originally built from.
TINT = 0.88

# Hues (degrees) handed out to types that don't name a colour, ordered so that
# consecutive additions stay far apart on the wheel.
AUTO_HUES = [200, 340, 100, 40, 265, 165, 15, 300, 70, 230]


def hsl_hex(hue: float, sat: float = 0.55, light: float = 0.40) -> str:
    c = (1 - abs(2 * light - 1)) * sat
    x = c * (1 - abs((hue / 60) % 2 - 1))
    m = light - c / 2
    rgb = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(hue // 60) % 6]
    return "#" + "".join(f"{round((v + m) * 255):02x}" for v in rgb)


def tint(color: str, amount: float = TINT) -> str:
    """Blend a hex colour toward white — the pale fill behind an event box."""
    h = color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise SystemExit(f"bad colour {color!r}: expected #rgb or #rrggbb")
    channels = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(v + (255 - v) * amount):02x}" for v in channels)


def shade(color: str, amount: float) -> str:
    """Darken a hex colour — readable badge text on top of its own tint."""
    h = color.lstrip("#")
    channels = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(v * (1 - amount)):02x}" for v in channels)


def toward(color: str, target: str, amount: float) -> str:
    """Blend a hex colour toward another. The dark theme's fills are the accent
    carried most of the way to the page ground, which keeps each type's hue
    identifiable without the pale tint that would glare on black."""
    a = color.lstrip("#")
    b = target.lstrip("#")
    pairs = zip((int(a[i : i + 2], 16) for i in (0, 2, 4)), (int(b[i : i + 2], 16) for i in (0, 2, 4)))
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in pairs)


def lift(color: str, amount: float) -> str:
    """Lighten toward white — a badge label legible on a dark fill."""
    return tint(color, amount)


def resolve_colors(program: dict) -> None:
    """Every type gets an accent and a derived fill; unnamed ones get a hue."""
    types = program["types"]
    unnamed = [key for key, t in types.items() if not t.get("color")]
    for i, key in enumerate(unnamed):
        types[key]["color"] = hsl_hex(AUTO_HUES[i % len(AUTO_HUES)])
    for t in types.values():
        t.setdefault("short", t["label"])
        t.setdefault("emoji", None)
        t["fill"] = tint(t["color"])  # event box background
        t["wash"] = tint(t["color"], 0.94)  # agenda row background
        t["badge"] = tint(t["color"], 0.80)  # badge background
        t["deep"] = shade(t["color"], 0.35)  # badge text
        # Dark counterparts. Tinting toward white is what makes the light fills
        # readable; on black the same move blinds, so they blend toward the
        # page ground instead and the text lifts rather than darkens.
        t["fill_dark"] = toward(t["color"], "#000000", 0.80)
        t["wash_dark"] = toward(t["color"], "#000000", 0.88)
        t["badge_dark"] = toward(t["color"], "#000000", 0.72)
        t["deep_dark"] = lift(t["color"], 0.55)

    used = {e["type"] for day in program["days"] for e in day["events"]}
    unknown = sorted(used - set(types))
    if unknown:
        raise SystemExit(
            f"event type(s) not declared under `types:` in program.yml: {', '.join(unknown)}"
        )


# ---------------------------------------------------------------- about


def outbound(html: str) -> str:
    """Every link in the prose points off-site."""
    return html.replace('<a href="http', '<a target="_blank" rel="noopener" href="http')


def render_about(about: dict, links: dict) -> dict:
    """Markdown -> a lead, a set of `###` blocks, and the topic chips.

    Splitting on the headings is what lets the page give each idea its own
    card instead of running the whole argument together as one wall of prose.
    """
    refs = "\n\n" + "\n".join(f"[{key}]: {url}" for key, url in links.items()) + "\n"
    codes = []

    for lang in about["languages"]:
        source = (CONTENT / lang["file"]).read_text(encoding="utf-8")
        head, *rest = re.split(r"^### +(.+)$", source, flags=re.M)

        intro = [p.strip() for p in head.strip().split("\n\n") if p.strip()]
        lang["lead"] = Markup(outbound(md.markdown(intro[0] + refs))) if intro else None
        lang["standfirst"] = Markup(outbound(md.markdown(intro[1] + refs))) if len(intro) > 1 else None

        blocks = []
        for heading, body in zip(rest[0::2], rest[1::2]):
            # A bullet list in a block becomes chips, not prose.
            prose, bullets = [], []
            for line in body.strip().splitlines():
                (bullets if line.lstrip().startswith("- ") else prose).append(line)
            blocks.append(
                {
                    "heading": heading.strip(),
                    "html": Markup(outbound(md.markdown("\n".join(prose) + refs))),
                    "chips": [line.strip()[2:].strip() for line in bullets],
                }
            )

        # The block carrying the topic chips runs full width; the rest are cards.
        lang["pillars"] = [b for b in blocks if not b["chips"]]
        lang["wide"] = [b for b in blocks if b["chips"]]
        codes.append(lang["code"])

    about["codes"] = codes
    return about


# ---------------------------------------------------------------- i18n


def bilingual(value, ko=None) -> Markup:
    """Emit both languages so the global toggle can swap them with CSS alone.

    Anything without a `_ko` sibling is rendered once and shows in both — which
    is the right default for names, times and affiliations.
    """
    if not ko:
        return escape(value)
    return Markup('<span class="t-en">%s</span><span class="t-ko">%s</span>') % (value, ko)


# ---------------------------------------------------------------- program


def speaker_line(s: dict) -> Markup:
    # Names carry a Korean form where we have one; bilingual() emits both and
    # the language toggle picks. Without `name_ko` it renders once and shows in
    # either language, which is the right default for a romanisation.
    shown = bilingual(s["name"], s.get("name_ko"))
    if s.get("home"):
        name = Markup('<a href="%s" target="_blank" rel="noopener">%s</a>') % (s["home"], shown)
    else:
        name = shown
    line = Markup("<b>%s</b> <em>%s</em>") % (name, bilingual(s.get("affil", ""), s.get("affil_ko")))
    if s.get("topic"):
        line += Markup(" · %s") % s["topic"]
    return line


def note_line(text: str) -> Markup:
    return Markup("<em>%s</em>") % text


def session_track(event: dict) -> str:
    """The subject a session belongs to, for grouping the speaker roster.

    "Bandits I" and "Bandits II" are one subject, so the part number comes off
    the title. Set `track:` on the event where that reading is wrong — a title
    that carries no subject, or two differently-named sessions that belong
    together.
    """
    if event.get("track"):
        return event["track"]
    return re.sub(r"\s+[IVX]+$", "", event["title"]).strip()


def anon_line(event: dict) -> Markup | None:
    """What replaces the speaker names in an anonymised build."""
    if event.get("anon_note"):
        return note_line(event["anon_note"])
    speakers = event.get("speakers") or []
    if not speakers:
        return None
    each = (minutes(event["end"]) - minutes(event["start"])) // len(speakers)
    return note_line(f"{len(speakers)} talks · {each} min each")


def fill_defaults(bundle: dict) -> None:
    """Give every optional key a value so the template can stay StrictUndefined.

    A missing key is then always a typo, never a shrug.
    """
    # Optional Korean siblings — absent means "same in both languages".
    bundle["about"].setdefault("title_ko", None)
    bundle["about"].setdefault("subtitle", None)
    bundle["about"].setdefault("subtitle_ko", None)
    bundle["venue"].setdefault("title_ko", None)
    bundle["venue"].setdefault("subtitle", None)
    bundle["venue"].setdefault("subtitle_ko", None)
    bundle["program"].setdefault("title_ko", None)
    # No eyebrow at all is a legitimate hero — the pill simply disappears.
    bundle["site"].setdefault("eyebrow", None)
    bundle["site"].setdefault("eyebrow_ko", None)
    if bundle["site"].get("nav_cta"):
        bundle["site"]["nav_cta"].setdefault("label_ko", None)
    for item in bundle["site"]["nav"]:
        item.setdefault("label_ko", None)
    bundle["site"].setdefault("hero_actions", [])
    for act in bundle["site"]["hero_actions"]:
        for key in ("label_ko", "href", "note", "note_ko"):
            act.setdefault(key, None)
        act.setdefault("primary", False)
    for cell in bundle["site"]["infobar"]:
        cell.setdefault("note", None)
        # A cell with no Korean sibling shows its one form in both languages,
        # which is right for anything that is already the same in both.
        for key in ("key_ko", "value_ko", "note_ko"):
            cell.setdefault(key, None)
        cell.setdefault("href", None)
        cell.setdefault("countdown", False)
        cell.setdefault("icon", None)
        cell.setdefault("mono", False)
    bundle["site"].setdefault("hosts", None)
    # A logo entry with no file on disk would render a broken image.
    if bundle["site"]["hosts"]:
        present = [h for h in bundle["site"]["hosts"]["logos"] if (STATIC / "logos" / h["file"]).exists()]
        missing = [h["name"] for h in bundle["site"]["hosts"]["logos"] if h not in present]
        if missing:
            print(f"  note: no logo file yet for {', '.join(missing)} — strip hidden")
        bundle["site"]["hosts"] = {**bundle["site"]["hosts"], "logos": present} if present else None

    # Affiliations get their Korean form from the one lookup in site.yml.
    korean = bundle["site"].get("affiliations") or {}

    def localise(person: dict) -> None:
        person["affil_ko"] = korean.get(person.get("affil"))

    for day in bundle["program"]["days"]:
        for event in day["events"]:
            for speaker in event.get("speakers") or []:
                localise(speaker)
    for member in bundle["organizers"]["members"]:
        localise(member)
    for person in bundle["candidates"]["people"]:
        localise(person)

    for member in bundle["organizers"]["members"]:
        # No default role: the card only carries one when it distinguishes the
        # person from everyone else under the same heading.
        member.setdefault("name_ko", None)
        member.setdefault("role", None)
        member.setdefault("role_ko", None)
        member.setdefault("photo", None)
        member.setdefault("links", None)
        member["initials"] = "".join(part[0] for part in member["name"].split()[:2]).upper()
    for person in bundle["candidates"]["people"]:
        person.setdefault("topic", "TBD")
    types = bundle["program"]["types"]
    for day in bundle["program"]["days"]:
        day.setdefault("theme", None)
        day.setdefault("short", day["label"].split("·")[0].strip())
        for e in day["events"]:
            e.setdefault("calendar", True)
            for key in ("chair", "density", "time_label", "anon_note"):
                e.setdefault(key, None)
            for key in ("bare", "time_in_title"):
                e.setdefault(key, False)
            for key in ("speakers", "notes"):
                e.setdefault(key, [])
            # The event's own mark wins; otherwise the type's.
            if not e.get("emoji"):
                e["emoji"] = types.get(e["type"], {}).get("emoji")


def offset_minutes(utc_offset: str) -> int:
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", utc_offset)
    if not m:
        raise SystemExit(f"bad utc_offset {utc_offset!r}: expected \"+09:00\"")
    sign, hh, mm = m.groups()
    return (1 if sign == "+" else -1) * (int(hh) * 60 + int(mm))


def local_dt(day: dict, hhmm: str, offset: int) -> datetime:
    """A venue-local clock time as an absolute instant."""
    h, m = (int(part) for part in hhmm.split(":"))
    tz = timezone(timedelta(minutes=offset))
    return datetime.combine(day["date"], time(h, m), tzinfo=tz)


def talk_entries(event: dict, ident: str, notes: bool) -> list[dict]:
    """Per-speaker rows for the list view, each with its own abstract."""
    talks = []
    for i, s in enumerate(event["speakers"]):
        talks.append(
            {
                "line": speaker_line(s),
                "talk": s.get("talk"),
                "abstract": Markup(md.markdown(s["abstract"])) if s.get("abstract") else None,
                "slides": s.get("slides"),
                "note": s.get("note") if notes else None,
                "id": f"{ident}-{i}",
            }
        )
    return talks


def place_events(program: dict, anonymize: bool, notes: bool = False) -> None:
    """Resolve every event's CSS grid row/span and its rendered text lines."""
    grid = program["grid"]
    slot = grid["slot_minutes"]
    origin = minutes(grid["day_start"])
    first_row = grid["header_rows"] + 1
    day_end = minutes(grid["day_end"])

    offset = offset_minutes(program["utc_offset"])

    for d, day in enumerate(program["days"], start=1):
        for n, e in enumerate(day["events"], start=1):
            start, end = minutes(e["start"]), minutes(e["end"])
            if start < origin or end > day_end:
                raise SystemExit(
                    f"{day['label']}: {e['title']} ({e['start']}{EN_DASH}{e['end']}) "
                    f"falls outside the grid ({grid['day_start']}{EN_DASH}{grid['day_end']})"
                )
            if (start - origin) % slot or (end - start) % slot:
                raise SystemExit(
                    f"{day['label']}: {e['title']} is not aligned to the {slot}-minute grid"
                )

            e["row"] = first_row + (start - origin) // slot
            e["span"] = (end - start) // slot
            e["id"] = f"d{d}e{n}"
            if not e["time_label"]:
                e["time_label"] = f"{e['start']} {EN_DASH} {e['end']}"

            # Absolute instants, so "Now" and the .ics are right in any timezone.
            e["begins"] = local_dt(day, e["start"], offset)
            e["ends"] = local_dt(day, e["end"], offset)
            e["begins_iso"] = e["begins"].isoformat()
            e["ends_iso"] = e["ends"].isoformat()

            if anonymize:
                line = anon_line(e)
                e["lines"] = [line] if line else []
                e["talks"] = []
            else:
                e["lines"] = [speaker_line(s) for s in e["speakers"]]
                e["lines"] += [note_line(n) for n in e["notes"]]
                e["talks"] = talk_entries(e, e["id"], notes)


# ---------------------------------------------------------------- calendar


def ics_text(value: str) -> str:
    for old, new in (("\\", "\\\\"), (";", "\\;"), (",", "\\,"), ("\n", "\\n")):
        value = value.replace(old, new)
    return value


def ics_fold(line: str) -> str:
    """RFC 5545 caps a content line at 75 octets; continuations start with a space."""
    out, chunk, width = [], [], 0
    for ch in line:
        size = len(ch.encode("utf-8"))
        if width + size > 73:
            out.append("".join(chunk))
            chunk, width = [], 1  # the leading space of the next line
        chunk.append(ch)
        width += size
    out.append("".join(chunk))
    return "\r\n ".join(out)


def ics_stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def calendar(site: dict, program: dict) -> str:
    """The whole programme as one .ics, straight off the same events."""
    host = site["url"].split("//", 1)[-1].split("/", 1)[0]
    now = ics_stamp(datetime.now(timezone.utc))
    location = ics_text(f"{site['venue']}, {site['city']}")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{site['name']}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_text(site['name'])}",
        f"X-WR-TIMEZONE:{program['timezone']}",
    ]

    for day in program["days"]:
        for e in day["events"]:
            if e["calendar"] is False:
                continue
            description = []
            for s in e["speakers"]:
                who = s["name"] + (f" ({s['affil']})" if s.get("affil") else "")
                description.append(f"{who} — {s['talk']}" if s.get("talk") else who)
            if e["chair"]:
                description.append(f"Chair: {e['chair']}")

            lines += [
                "BEGIN:VEVENT",
                f"UID:{e['id']}-{day['date']}@{host}",
                f"DTSTAMP:{now}",
                f"DTSTART:{ics_stamp(e['begins'])}",
                f"DTEND:{ics_stamp(e['ends'])}",
                f"SUMMARY:{ics_text(e['title'])}",
                f"LOCATION:{location}",
                f"URL:{site['url']}",
            ]
            if description:
                lines.append("DESCRIPTION:" + ics_text("\n".join(description)))
            lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(line) for line in lines) + "\r\n"


# ---------------------------------------------------------------- venue


def resolve_venue(venue: dict) -> dict:
    """Settle on a map provider we can actually draw.

    Kakao is the better map for a Korean audience but every route to it needs a
    credential only the organisers can create, so fall through until something
    is configured rather than rendering an empty box.
    """
    conf = venue["map"]
    rough = conf["kakao_roughmap"]
    chosen = conf["provider"]

    # Google needs no credential — assemble the embed URL Google itself
    # redirects to, skipping the 301 that carries x-frame-options.
    if conf.get("google_embed_pb"):
        conf["google_url"] = "https://www.google.com/maps/embed?pb=" + conf["google_embed_pb"]
    elif conf.get("google_api_key"):
        # Official Embed API — free, no usage cap, and it labels the place.
        query = quote_plus(f"{venue['name_ko']} {venue['name']}")
        conf["google_url"] = (
            "https://www.google.com/maps/embed/v1/place"
            f"?key={conf['google_api_key']}&q={query}&zoom={conf['zoom']}&language=ko"
        )
    else:
        # Neither is set. The coordinate-only pb renders a static preview you
        # cannot pan or zoom, which is worse than a map that works, so hand off
        # to Leaflet instead.
        conf["google_url"] = None

    if chosen == "google" and not conf["google_url"]:
        chosen = "kakao"
    if chosen == "kakao" and not conf["kakao_app_key"]:
        chosen = "kakao_roughmap"
    if chosen == "kakao_roughmap" and not (rough["timestamp"] and rough["key"]):
        chosen = "leaflet"

    if chosen != conf["provider"]:
        print(f"  note: venue map falls back to {chosen} — {conf['provider']} is not configured")
    conf["resolved"] = chosen
    for link in venue["map_links"]:
        link["url"] = link["url"].format(lat=venue["lat"], lon=venue["lon"])
        link.setdefault("icon", "naver")
    return venue


def formula_manifest() -> list[dict]:
    """Ids and aspect ratios of the baked formulas, or nothing if the sprite has
    not been generated. The hero simply has no maths in that case."""
    path = STATIC / "formulas.json"
    if not path.exists():
        return []
    import json as _json

    return _json.loads(path.read_text(encoding="utf-8"))


def time_axis(grid: dict) -> list[dict]:
    origin = minutes(grid["day_start"])
    first_row = grid["header_rows"] + 1
    step = grid["axis_step_minutes"]
    slot = grid["slot_minutes"]

    ticks = []
    t = minutes(grid["axis_from"])
    while t <= minutes(grid["axis_to"]):
        ticks.append(
            {"label": clock(t), "row": first_row + (t - origin) // slot, "span": step // slot}
        )
        t += step
    return ticks


# ---------------------------------------------------------------- build


def build(name: str, variant: dict, bundle: dict, env: Environment) -> tuple[str, str]:
    program = deepcopy(bundle["program"])  # place_events() mutates it
    # Availability notes are organiser-only; `candidates` marks the same build.
    place_events(program, variant["anonymize"], notes=variant["candidates"])

    ics = calendar(bundle["site"], program)
    types = program["types"]

    # The speaker roster is derived from the programme, never listed twice —
    # a name added to a session appears here, and cannot disagree with it.
    # It is grouped by subject, so the section answers "who works on bandits"
    # rather than only "who is speaking".
    roster, seen_names = [], set()
    if not variant["anonymize"]:
        for day in program["days"]:
            for e in day["events"]:
                if not e["speakers"]:
                    continue
                for s in e["speakers"]:
                    # Anyone speaking twice gets one card, linked to their
                    # first session.
                    if s["name"] == "TBD" or s["name"] in seen_names:
                        continue
                    seen_names.add(s["name"])
                    roster.append(
                        {
                            "talk": None,
                            "topic": None,
                            "affil": None,
                            "affil_ko": None,
                            "name_ko": None,
                            "role": None,
                            "role_ko": None,
                            **s,
                            "session": e["title"],
                            "track": session_track(e),
                            "type": e["type"],
                            "day": day["short"],
                            "time": f"{e['start']} {EN_DASH} {e['end']}",
                            "event_id": e["id"],
                            "photo": f"speakers/{s['photo']}" if s.get("photo") else None,
                            "initials": "".join(p[0] for p in s["name"].split()[:2]).upper(),
                        }
                    )
        # Subjects keep programme order — Day 1 before Day 2 — because that is
        # the order the reader will meet them in. Within a subject there is no
        # such order to borrow, so it sorts by family name, the last token in
        # these romanisations.
        roster.sort(key=lambda s: (s["name"].split()[-1].lower(), s["name"].lower()))
    detail = [
        {
            "id": e["id"],
            "day": day["label"],
            "dayShort": day["short"],
            "title": e["title"],
            # The mark travels with the event everywhere it is drawn in script.
            # Not into the .ics: a calendar entry is plain text in someone
            # else's app, and an emoji in SUMMARY is noise there.
            "emoji": e.get("emoji"),
            "time": f"{e['start']} {EN_DASH} {e['end']}",
            "duration": human_span(minutes(e["end"]) - minutes(e["start"])),
            "begins": e["begins_iso"],
            "ends": e["ends_iso"],
            "type": e["type"],
            "typeLabel": types[e["type"]]["short"],
            "chair": e["chair"],
            "speakers": [
                {
                    "name": s["name"],
                    "nameHtml": str(bilingual(s["name"], s.get("name_ko"))),
                    "affilHtml": str(bilingual(s.get("affil") or "", s.get("affil_ko"))),
                    "affil": s.get("affil"),
                    "topic": s.get("topic"),
                    "talk": s.get("talk"),
                    "abstract": md.markdown(s["abstract"]) if s.get("abstract") else None,
                    "bio": md.markdown(s["bio"]) if s.get("bio") else None,
                    "photo": f"speakers/{s['photo']}" if s.get("photo") else None,
                    "slides": s.get("slides"),
                    "home": s.get("home"),
                }
                for s in (e["speakers"] if not variant["anonymize"] else [])
            ],
            "notes": e["notes"] if not variant["anonymize"] else [],
        }
        for day in program["days"]
        for e in day["events"]
    ]
    html = env.get_template("main.html.j2").render(
        variant=variant,
        variant_name=name,
        site=bundle["site"],
        about=bundle["about"],
        organizers=bundle["organizers"],
        candidates=bundle["candidates"],
        venue=bundle["venue"],
        program=program,
        types=program["types"],
        grid=program["grid"],
        axis=time_axis(program["grid"]),
        ics_file=CALENDAR_FILE,
        detail=detail,
        formulas=formula_manifest(),
        roster=roster,
    )
    return html, ics


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("variants", nargs="*", help="variant names (default: all)")
    ap.add_argument("--out", default="_site", help="build directory (default: _site)")
    args = ap.parse_args()

    out_dir = ROOT / args.out
    site = load("site.yml")
    site["url"] = deployed_url(site["url"])
    bundle = {
        "site": site,
        "about": render_about(load("about.yml"), load("links.yml")),
        "organizers": load("organizers.yml"),
        "candidates": load("candidates.yml"),
        "venue": resolve_venue(load("venue.yml")),
        "program": load("program.yml"),
    }
    fill_defaults(bundle)
    resolve_colors(bundle["program"])

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.globals["t"] = bilingual

    wanted = args.variants or list(site["variants"])
    unknown = [v for v in wanted if v not in site["variants"]]
    if unknown:
        return _fail(f"unknown variant(s): {', '.join(unknown)}\n"
                     f"available: {', '.join(site['variants'])}")

    for name in wanted:
        variant = site["variants"][name]
        html, ics = build(name, variant, bundle, env)
        page = Path(variant["output"])
        write(out_dir / page, html)
        write(out_dir / page.parent / CALENDAR_FILE, ics)
        print(f"  {name:9s} -> {args.out}/{page}  (+ {CALENDAR_FILE})")

    # Redirect stubs stand in for the server-side redirects Pages doesn't have.
    for r in site["redirects"]:
        write(out_dir / r["output"], env.get_template("redirect.html.j2").render(r=r))
        print(f"  redirect  -> {args.out}/{r['output']}  ({r['to']})")

    # Anything in static/ ships next to the page (favicon, images…) and at the
    # site root as well, so the redirect stub gets the same tab icon.
    if STATIC.is_dir():
        edition_dir = out_dir / Path(site["variants"]["public"]["output"]).parent
        for target in {out_dir, edition_dir}:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(STATIC, target, dirs_exist_ok=True)
        print(f"  static    -> {args.out}/ and {args.out}/{edition_dir.relative_to(out_dir)}/")

    write(out_dir / ".nojekyll", "")  # serve the artifact verbatim
    return 0


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
