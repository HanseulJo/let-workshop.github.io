# What to edit where

Nothing on the site is written in HTML. Change a file here, run
`python3 build.py`, and the page follows. Full detail is in
[../CONTRIBUTING.md](../CONTRIBUTING.md).

## Files

| File | Controls | Typical edit |
| --- | --- | --- |
| [site.yml](site.yml) | Name, dates, `<meta>` copy, hero, info bar, nav tabs, logo strip, build variants, redirects | Change the date; rename a tab; publish next year's edition |
| [program.yml](program.yml) | The whole schedule — days, sessions, times, speakers, event types and their colours | Move a talk; swap a speaker; add a session |
| [venue.yml](venue.yml) | Building, booked rooms, address, map pin and map provider | Fill in the room; move the pin; switch to Kakao Map |
| [organizers.yml](organizers.yml) | Organizing committee: names, affiliations, photos, homepage/Scholar links, contact address | Add a member; add someone's homepage |
| [about.yml](about.yml) | Overview section heading and which language tabs exist | Add a third language |
| [links.yml](links.yml) | URLs the Overview prose refers to by key | Fix a link that moved |
| [candidates.yml](candidates.yml) | Shortlist of possible additional speakers | Add a name under consideration |
| [../content/about.en.md](../content/about.en.md) · [about.ko.md](../content/about.ko.md) | The Overview prose itself, in Markdown | Reword the purpose; add a topic |

## Things that are easy to get wrong

**Times drive everything.** In `program.yml` an event's position on the grid,
its row in the list, the "Now" button and the calendar export all come from
`start` and `end`. Never write a grid row by hand. Times must be on the
5-minute grid and inside `grid.day_start … day_end`, or the build stops and
names the offending event.

**Three pages are built, one is published.** `public` → the live page,
`invite` → speakers hidden, `internal` → adds the candidate shortlist and each
speaker's `note:`. CI builds `public` only, so anything in a `note:` or in
`candidates.yml` cannot reach the live site.

**Colours are generated.** Give an event type one `color:` in `program.yml` and
the box fill, border, legend swatch, list-view row and badge all follow. Using
a type that isn't declared fails the build rather than rendering a blank box.

**Images live in `../static/`, not here.** Institution logos go in
`static/logos/`. Portraits go in `static/organizers/` or `static/speakers/`
depending on which card shows them, and are made with:

```sh
python3 tools/prep-photos.py ~/Downloads/juho-lee.png juho-lee --to speakers
```

The `photo:` value is just the filename — `organizers.yml` looks in
`static/organizers/`, and a speaker's `photo:` in `program.yml` looks in
`static/speakers/`. Someone who both speaks and organises needs the file in
both places, so pass `--to speakers organizers` for them. Leave `photo:` out
and the card falls back to the person's initials.
