# Delivery Timeline

- **Route / entry point**: `/delivery-timeline`
- **Backing file(s)**: `pages_dash/enhancements/delivery_timeline.py` (~710 lines)
- **Nav location**: ENHANCEMENTS → Delivery Timeline. Built (`✅`, `_NAV_TREE` entry
  `("Delivery Timeline", "/delivery-timeline", "▦", True)` in `app.py`) — not
  flagged placeholder.

## What it does

One page, two tabs, switched by a client-side-feeling (but server-rendered) tab
row at the top:

- **Month Grid** (default tab) — CEO-facing view. One row per active 2026
  Enhancement, one chip per row placed in whatever month it's due to be
  *delivered* (released), not when dev work starts. The chip shows a
  size abbreviation (B/M/S/VS) colour-coded by story size. Left-hand fixed
  columns show story title/ID/area, size, story owner, and developer. A footer
  row totals story count per month. Clicking a chip opens a right-hand detail
  panel (size, platform, owner, developer, dev iteration month, release month).
  A "today" column is highlighted.
- **Gantt** — developer/function bar chart, entirely delegated to
  `pages_dash/enhancements/planning.py`'s `_build_gantt_html()` (see "How it
  works"). Has its own rolling-window dropdown (0-12M / 12-24M / 24M+) and a
  work-type filter (All / Enhancements / Bugs).

A filter bar above the Month Grid offers: rolling window (3/6/12 months), story
size (multi-select pills, defaults to Big+Medium), platform (All/Mobile/Web),
story owner (hardcoded pills — see Known issues), and a free-text search box
(title, ID, owner, developer).

## Why it exists

Gives leadership a release-month-oriented view of what's shipping when,
independent of the developer/sprint-oriented Gantt used for capacity/sequencing
conversations. Two audiences, one page, one dataset — avoids maintaining two
separate routes for what is fundamentally the same underlying Enhancement set.

## How it works

**Data source (Month Grid)**: `_load_dt()` (`delivery_timeline.py:52-77`) reads
`agg_gantt_items` (see `db.md` §3 — "Delivery Timeline / Gantt rows... one row
per active 2026 Enhancement/Bug") filtered to `item_type = 'enh'`, left-joined
to `work_items_main` for `story_size`/`story_owner`/`area`. Delivery date is
`COALESCE(release_date, bar_end, bar_start)`. Cached process-wide for 300s
(`_DT_CACHE`, `_DT_TTL`, line 47-48) — a shorter, page-local cache layered on
top of `data/loader.py`'s 15-minute cache, since this page reads `agg_gantt_items`
directly via its own `engine.connect()`, not through `data/loader.load_data()`.
A second cache, `_GRID_RENDER_CACHE` (line 49), memoizes the fully-built grid
HTML per filter combination so re-rendering the same filter state is free.

**Data source (Gantt tab)**: does *not* query `agg_gantt_items`/`agg_gantt_tasks`
directly. `_render_gantt()` (line 683-709) lazily imports
`_build_gantt_html` and `_gantt_window` from
`pages_dash/enhancements/planning.py` *inside the callback body* — this is a
deliberate exception to the "avoid importing one page module from another at
top level" convention in `master.md` §6: importing lazily, inside the callback
rather than at module top level, is exactly how this file dodges the
Dash double-registered-callback problem that convention warns about. Once
inside `planning.py`, `_build_gantt_html()` (`planning.py:1781`) is the one
that actually queries `agg_gantt_items` and `agg_gantt_tasks` (`planning.py:1805,
1809`) — so the docstring's claim ("Gantt Chart: developer/function bar chart
from planning.py") is accurate on both counts: the chart's *code* comes from
`planning.py`, and that code's *data* is the `agg_gantt_items`/`agg_gantt_tasks`
pair documented in `db.md` §3. The whole call is wrapped in `try/except`, so if
`planning.py` fails to import or throws, the tab shows "Gantt unavailable: {e}"
instead of crashing the page.

**Callbacks** — split into three independent callbacks specifically to keep
the expensive grid rebuild off the hot path:
1. `_render_header` (line 614) — filter bar + subtitle text, fires on every
   filter/search change, cheap.
2. `_render_grid_only` (line 635) — the actual grid HTML, same inputs as #1
   but deliberately does *not* depend on panel state, and is memoized via
   `_GRID_RENDER_CACHE`.
3. `_render_panel_only` (line 664) — the side detail panel, fires only on row
   click / close, never on filter changes. Falls back to an unfiltered lookup
   in `_load_dt()` if the selected item is outside the current filter window
   (line 673-676), so the panel can still show a row that filters would
   otherwise hide.

Filter and tab state live in `dcc.Store`s (`dt-rolling`, `dt-sizes`, `dt-owner`,
`dt-platform`, `dt-panel-wid`, `dt-view-tab`, `dt-gantt-view`, `dt-gantt-type`,
`gantt-expanded`), updated by pattern-matching (`ALL`) pill/tab-button
callbacks (`_switch_tab`, `_update_filters`, `_select_cell`, `_close_panel`).
`gantt-expanded` is explicitly commented as "shared with gantt_toggle.js"
(line 416) — the Gantt's row-expand state is driven by a client-side JS asset,
not a Python callback.

## Known issues / quirks

- **Owner filter pills are hardcoded and out of sync with the config source of
  truth.** `_build_filter_bar()` (line 188) hardcodes
  `("All owners", "Chhavi", "Geetika", "Sunil")` inline rather than importing
  `STORY_OWNER_NAMES` from `config/dev_capacity.py`, which lists **four** names
  — `["Geetika", "Chhavi", "Sunil", "Vineeta"]`. "Vineeta" cannot be filtered
  for on this page even though she's a valid story owner elsewhere (e.g.
  `designer_planning.py` does import and use `STORY_OWNER_NAMES` correctly).
- **Nav "built" flag is accurate, not stale.** Unlike Designer Planning and a
  few other ENHANCEMENTS-section routes, `_NAV_TREE` in `app.py` marks this
  route `True` (no amber placeholder dot), and `master.md` §5 lists it `✅`.
  That matches what's actually in the file — two fully wired tabs, live DB
  reads, working filters and detail panel. Nothing to flag as stale here.
- **Two overlapping cache layers with different TTLs.** `_load_dt()`'s 300s
  cache sits on top of `data/loader.py`'s 15-minute cache indirectly (via the
  shared `engine`), but this page bypasses `data/loader.load_data()` entirely
  and queries `agg_gantt_items` directly — so `bust_loader_cache()` (the
  documented invalidation hook per `master.md` §6) has no effect here. A write
  that updates `agg_gantt_items` (i.e. the next full sync) won't be visible on
  this page until the page's own 300s TTL expires, independent of any manual
  cache-bust elsewhere.
- **Reaches into another page module's private (underscore-prefixed) API.**
  `_build_gantt_html` and `_gantt_window` are module-private in `planning.py`
  (leading underscore), imported directly by `delivery_timeline.py`. Functional
  today, but it's an implicit contract — a refactor of those two functions'
  signatures in `planning.py` (a ~5,500-line file per `master.md` §7) would
  silently break this page's Gantt tab with no import-time error, only the
  caught exception's "Gantt unavailable" fallback at runtime.
- **`_ALL_SIZES` excludes falsy/blank sizes by construction.** Rows with no
  parseable `story_size` normalize to `"—"` (`_normalize_size`, line 115-122)
  and are never selectable via the size pills (which only offer Big/Medium/
  Small/Very Small), so stories with a missing/unrecognized size are silently
  dropped from the Month Grid regardless of filter selection — there is no
  "unsized" pill to bring them back into view.
