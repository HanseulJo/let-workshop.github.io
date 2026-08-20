# Updating the site

The page used to be one hand-maintained `main.html`. Everything factual now
lives in `data/*.yml` and `content/*.md`, and `build.py` renders a
self-contained, dependency-free static page from it.

```sh
pip install -r requirements.txt
python3 build.py           # all variants -> _site/
python3 build.py public    # just the page that gets deployed
open _site/2026/index.html
```

`_site/` is generated and gitignored. Never hand-edit the HTML.

## Where things live

| Path                  | What lives there                                                      |
| --------------------- | --------------------------------------------------------------------- |
| `data/site.yml`       | Name, dates, `<meta>` copy, hero, info bar, nav, variants, redirects   |
| `data/program.yml`    | The schedule — event types/colours, days, sessions, speakers           |
| `data/venue.yml`      | Building, rooms, address, map pin and provider                        |
| `data/organizers.yml` | Organizing committee, photos, contact address                         |
| `data/candidates.yml` | Shortlist of possible additional speakers (internal build only)       |
| `data/about.yml`      | About section heading + which language tabs exist                     |
| `data/links.yml`      | URLs shared by the About prose, referenced by key                     |
| `content/about.*.md`  | The About prose, one Markdown file per language                       |
| `static/`             | Files copied verbatim next to the page (favicon, images) — optional   |
| `templates/`          | `main.html.j2`, `redirect.html.j2`, `style.css`                       |

## The programme

Events are positioned from their `start`/`end` times. `build.py` computes the
CSS grid row and span, so moving a talk means changing two clock strings:

```yaml
- type: block
  title: Bandits I
  chair: TBD
  start: "11:10"
  end: "12:30"
  speakers:
    - { name: Kwang-Sung Jun, affil: POSTECH }
    - { name: Min-hwan Oh, affil: SNU, topic: contextual bandits }
```

Times must land on the 5-minute grid and inside `grid.day_start … day_end`; the
build fails with the offending event's name if they don't. Adding a third day is
a new entry under `days:` — the column count follows.

`data/program.yml` documents every event key at the top of the file.

### Two views and the toolbar

The same events render twice: the proportional **Grid** and a plain **List**
table, switched by the toggle above the programme. The choice is remembered in
`localStorage`, and screens under 720px start on the list, since the grid needs
horizontal scrolling there. Nothing to maintain — both views come from the same
YAML, and so does everything in the toolbar:

- **Day pills** filter the list to one day. Labels come from each day's `short`
  (derived from `label` if you omit it) and `date`.
- **Now** jumps to the session in progress, or the next one if the workshop
  hasn't started, or says so if it's over.
- **Add to calendar** links to `programme.ics`, generated from the same events.

`Now` and the `.ics` need absolute instants, which is why `program.yml` carries
`utc_offset: "+09:00"` and each day carries a `date:`. Both are correct for a
reader in any timezone. Set `calendar: false` on an event to keep it out of the
`.ics`.

### Abstracts

Give a speaker a `talk` and an `abstract` and the list view grows an Abstract
button that opens a modal:

```yaml
speakers:
  - name: Jaeho Lee
    affil: POSTECH
    topic: theory of KD
    talk: A Statistical Theory of Knowledge Distillation
    abstract: |
      Markdown. Blank lines separate paragraphs; links and emphasis work.
```

Both are optional — without them nothing changes. `talk` also lands in the
`.ics` description. Neither is emitted in the anonymised build.

## Section nav

`nav:` in `data/site.yml` drives the sticky bar. Each entry's `href` is a
section id already on the page (`#about`, `#program`, `#venue`, `#organizers`),
and the link highlights itself as you scroll into that section. Drop `nav_cta`
and the button on the right disappears. On narrow screens the links become a
horizontally scrollable pill strip.

Adding a section means giving it an `id` in `templates/main.html.j2` and a row
in `nav:`.

## Venue and map

`data/venue.yml` holds the building, the booked rooms and one lat/lon pair.
Everything else — the embed, the Google/Kakao/Naver/OSM buttons — is derived
from that pair.

The default is Leaflet on CARTO's Voyager basemap. Leaflet itself is vendored
into `static/vendor/leaflet/` rather than pulled from a CDN, so the only
third-party requests are the tile images. The marker and its label are drawn in
CSS, so no icon images ship either. Scroll-wheel zoom stays off until you click
the map, so scrolling the page doesn't get hijacked.

Kakao Map is also wired up and is the better map for a Korean audience, but it
needs a JavaScript key from developers.kakao.com registered against
the domain the site is served from. Paste it into `map.kakao_app_key`, set
`map.provider: kakao`, and the page switches over; leave the key blank and the
build falls back to Leaflet and says so. Naver works the same way but goes
through NCP, which wants billing details even on the free tier.

To move the pin, look the building up rather than guessing — the current one
came from OpenStreetMap's Overpass API, which has 포스코국제관 at
36.0139836, 129.3209046.

## Organiser photos

`photo:` on an entry in `data/organizers.yml` points at a file in
`static/organizers/`. Make one from any source image:

```sh
python3 tools/prep-photos.py ~/Downloads/some-photo.jpg hanseul-cho
```

That centre-crops to a square biased toward the head, resizes to 256px and
saves JPEG — roughly 15 KB each. Needs Pillow locally; the site build never
touches images. Omit `photo:` and the card falls back to the person's initials.

### Tab icon

`tools/make-wordmark.py` writes all three marks from the display face, as baked
outlines rather than `<text>`, so they render the same wherever they are used:

| file | what it is |
| --- | --- |
| `templates/wordmark.svg` | the letters alone, inheriting colour — the hero and the top bar |
| `static/let-logo.svg` | LeT on one row, full-bleed navy — the profile picture |
| `static/favicon.svg` | one letter, because a word is illegible at 16px |

The square mark says LeT and nothing else. It carried a second row, WS, on the
argument that three letters alone could be anything — but a profile picture is
never seen alone. It sits beside the name it belongs to everywhere GitHub draws
it, so the second row answered a question the line next to it had already
answered, and halved the letters that do the work to do it. On one row they
fill three quarters of the square.

`favicon-32.png`, `favicon-180.png` (apple-touch-icon) and `let-avatar.png` are
rasterised from those SVGs for the places that will not take one — browsers with
no SVG icon support, and GitHub, which wants a raster for an organisation
picture.

The profile picture is the one that fills its square edge to edge and rounds
nothing. Everywhere it is shown, the thing showing it does the rounding —
GitHub masks an organisation's picture at about 9% of the side, and rounds a
person's into a circle — so a mark that rounds its own corners at 22% and keeps
a transparent margin inside them arrives smaller than every other avatar in the
list, sitting in a gap, with corners rounder than the rest of the page. The
letters are kept within 229px of the centre of 512, so a circular crop cannot
reach them either. `favicon.svg` keeps its rounded square, because a favicon is
drawn onto the tab and owns its own shape.

Re-cut them after re-running the tool:

```sh
python3 tools/make-wordmark.py
# then, from a directory holding the SVG:
#   chrome --headless=new --default-background-color=00000000 \
#          --window-size=512,512 --screenshot=out.png page.html
# and resize to 32, 180 and 512.
```

Everything in `static/` is copied both to the site root and next to the page, so
the redirect stub gets the same icon.

### Colours

Event colours are generated. `types:` maps each type to one accent hex; the fill
behind the box, the left border, the legend swatch, the list-view row wash and
the badge all derive from it:

```yaml
types:
  tutorial: { label: Tutorial, color: "#3f51b5" }
  panel: { label: Panel discussion, short: Panel } # no colour -> one is assigned
```

Omit `color` and `build.py` hands out an unused hue. `short` is the badge text
in the list view and falls back to `label`. Using a `type:` that isn't declared
fails the build instead of silently rendering an unstyled white box.

### Anonymised programme

The `invite` build replaces each session's speakers with a summary line —
`anon_note:` if you set one, otherwise a derived `"2 talks · 40 min each"`.

## The About text

Prose is Markdown, one file per language, listed in `data/about.yml`. Adding a
language is a new file plus a row there; the toggle buttons and the JavaScript
follow automatically.

Links use reference syntax against `data/links.yml`:

```markdown
... initiatives such as the [ITA Workshop][ita], [COLT][colt] ...
```

`build.py` appends the definitions before rendering, so a URL that moves is
fixed once for every language. Markdown linters flag these as undefined
references — expected; the definitions only exist at build time.

The first paragraph is styled as the lead, and every `http` link gets
`target="_blank" rel="noopener"`.

## Variants

`data/site.yml` defines three builds off the same data:

| Variant    | Output               | Speaker names | Candidate list | Analytics | Deployed |
| ---------- | -------------------- | ------------- | -------------- | --------- | -------- |
| `public`   | `2026/index.html`    | shown         | no             | yes       | yes      |
| `invite`   | `2026/invite.html`   | hidden        | no             | no        | no       |
| `internal` | `2026/internal.html` | shown         | yes            | no        | no       |

CI builds `public` only, so the invitation page (which must not reveal who else
is confirmed) and the organisers' copy (which carries the candidate shortlist)
cannot reach the live site. This replaces the old trick of parking alternate
versions of a section inside `<template>` tags in the shipped file.

## Deployment

Push to `main`. [`.github/workflows/pages.yml`](.github/workflows/pages.yml)
runs `build.py public` and publishes `_site/` to GitHub Pages:

```text
<host>/        -> redirect stub to the current edition
<host>/2026/   -> the workshop page

The stub's target is relative, so the same build serves from a domain root
(kolt-workshop.github.io) or a project path
(dongyeoplee2.github.io/kolt-page-test-private).
```

Next year: add the new edition's entries to `data/program.yml`, point the
`public` variant at `2027/index.html`, and update the `redirects` entry in
`data/site.yml`. The old edition stays where it is.

## Why YAML, not JSON or TOML

The content is prose written by humans: multi-paragraph Korean and English text,
plus notes explaining what each field is for.

**JSON** has no comments and no multi-line strings — every explanatory note in
`data/` would have to be deleted or smuggled into a fake `"_comment"` key.

**TOML** has comments and multi-line strings, and would be fine for the flat
files. It struggles with `program.yml`, which nests three deep (days → events →
speakers): that becomes `[[days]]` / `[[days.events]]` /
`[[days.events.speakers]]` header soup, and TOML's rule that scalar keys must
precede sub-tables means adding `chair = "TBD"` to a session that already lists
speakers silently binds it to the wrong table. YAML indents.

Machine-generated data would argue the other way; this isn't that. Switching is
contained to `load()` in `build.py`.
