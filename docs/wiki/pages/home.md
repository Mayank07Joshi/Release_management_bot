# Home

- **Route / entry point**: `/`
- **Backing file(s)**: `pages_dash/home.py`
- **Nav location**: not in nav — default landing page (see `app.py`'s `_NAV_TREE`,
  which has no entry for `/`; `master.md` §5 documents this as "(not in nav;
  default landing page)")

## What it does

Renders a static landing screen: a page title/subtitle ("Release Analytics" /
"Centralised analytics for Release Management…") followed by a row of large
clickable cards. Today there are exactly two cards — **Summary** (→ `/summary`)
and **Planning Tool** (→ `/planning`) — each an icon, a title, and a one-line
description. Clicking a card navigates to that route.

## Why it exists

Gives users landing on `/` (the app's root URL) somewhere useful to go instead
of a blank page, and puts the two heaviest-traffic destinations — sprint/data
health (`/summary`) and story planning (`/planning`) — one click away without
needing the sidebar.

## How it works

Pure presentation, no data access:

- `home.py:9-24` — `CARDS`, a hardcoded list of two dicts (`icon`, `title`,
  `desc`, `href`, `group`).
- `home.py:26-28` — `CARD_GROUPS`, a list of `{"label": ..., "cards": ...}`
  wrapping `CARDS` in a single group with `label=None`.
- `home.py:38-51` — `_card()` builds one card as an `html.A` (the whole card is
  the link) with CSS classes `home-card` / `home-card-icon` / `home-card-title`
  / `home-card-desc`, defined in `assets/style.css:712-737` (plus light-theme
  overrides at `assets/style.css:1403-1412`) — no inline color styling, so it
  follows the theme-toggle convention in `master.md` §6.
- `home.py:54-72` — `layout()` iterates `CARD_GROUPS`, skips empty groups, emits
  a group-label `html.Div` only when `group["label"]` is truthy, then a
  `dbc.Row` of cards.

No callbacks, no DB reads, no `dash.register_page` name collision concerns —
this is the simplest page in the app.

## Known issues / quirks

- **Unused grouping machinery.** `CARD_GROUPS` (`home.py:26-28`) and the
  group-label branch in `layout()` (`home.py:59-60`) exist to support multiple
  labeled card groups, but there is currently exactly one group and its
  `label` is `None` — so that branch, and the `_GROUP_LABEL_STYLE` constant
  (`home.py:31-35`) it feeds, never execute. Dead flexibility, not dead code
  per se; harmless unless someone forgets it's there and duplicates the
  pattern elsewhere.
- **Only two of the app's ~18 routes are surfaced here.** `/overview` (the
  "Monday-morning glance" KPI page, arguably the more natural landing view)
  isn't linked from Home at all, nor are any CAPACITY or BUGS & ISSUES pages.
  Not a bug, but worth knowing if Home is meant to be a hub rather than a
  two-item shortcut list.
- **`group` key on each card dict (`home.py:15, 22`) is set but never read.**
  `_card()` doesn't reference `c["group"]`; grouping is driven entirely by
  `CARD_GROUPS`' structure, not by this field.
