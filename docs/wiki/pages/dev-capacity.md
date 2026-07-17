# Developer Capacity & Work Allocation

- **Route / entry point**: `/dev-capacity`
- **Backing file(s)**: `pages_dash/enhancements/capacity_planner.py` (~2,065 lines).
  Its `layout()` function is also called directly from
  `pages_dash/enhancements/planning.py` to embed this entire page inside the
  Story Readiness page (`/planning`) — see "How it works" and "Known issues"
  below.
- **Nav location**: CAPACITY section, label "Developer Capacity", built flag
  `True` in `app.py`'s `_NAV_TREE` (`app.py:116`).

## What it does

Gives PMs/EMs a forward-looking view of developer load: a grid of every
developer (rows) × month (columns) showing, per cell, hours committed to
Enhancements, Issues (bugs), and standalone/admin overhead against that
developer's monthly capacity (default 180h), plus a "Remaining" bar and an
over/under-100% badge.

The grid has two sub-tabs:
- **"1+2 Planning · M0/M1/M2"** — current sprint month + next two, with a
  live "hours left this month" calculation for M0 (`_render_m012_grid`,
  `capacity_planner.py:716`).
- **"Rest of 2026"** — a flatter %-only grid for the remaining fiscal months
  (`_render_rest_grid`, `capacity_planner.py:864`).

A top toolbar filters the whole page by work type (All Work / Enhancements /
Issues) and by `Customer` vs `Internal` item type. Clicking any grid cell
opens a right-hand Offcanvas detail panel (`capacity_planner.py:1699`,
`_panel_body`) listing that developer's open items for that month, split into
Enhancements / Issues / a collapsed "Completed" bucket / a collapsed "Needs
Estimation" bucket, plus that developer's standalone-task overhead for the
month — each with its own priority filter + sort control
(`_ctrl_bar_dcap`, `capacity_planner.py:166`).

Below the grid: a Gantt-style row of Big/Medium 2026 enhancements by release
month (`_render_gantt`, `capacity_planner.py:923`), a "Standalone Task
Overhead" breakdown card by developer and category
(`_render_overhead_section`, `capacity_planner.py:483`), and a "Function
Delivery Timeline" showing enhancement density per product function per month
(`_render_function_timeline`, `capacity_planner.py:1081`).

## Why it exists

Team Pulse (`/team-pulse`) answers "what is each developer doing right now."
This page answers the planning question one level up: "is anyone over- or
under-committed for the current sprint and the next two, and what does the
rest of the year look like." It's the tool PMs use to decide whether new work
can be assigned to a given developer/month, to spot standalone-overhead drag
eating into feature capacity, and to see Big/Medium enhancement delivery
spread across the year before committing to release dates.

## How it works

**Data sources actually read by this file** (confirmed by import/grep, not
assumed from the candidate list):

- `work_items_main` — read via raw SQL through `data.loader.engine` (imported
  locally per-function, not at module top). This is the *primary* source for
  the live grid: `_load_task_dev_data` (`capacity_planner.py:362`) attributes
  hours to a developer via **task assignments** (`t.main_developer`,
  `t.remaining_work` / `original_estimate − completed_work`), rolled up to
  the parent Enhancement/Bug — consistent with the task-based-hours
  convention (master.md §6). The detail-panel query in `_panel_body`
  (`capacity_planner.py:1734`) does the same task-based attribution again,
  independently, with its own copy of the same state-exclusion list and
  `LIKE '%Iteration 2026 %'` filter.
- `agg_standalone_overhead` — read by `_load_standalone_data`
  (`capacity_planner.py:237`), called live from the main render callback.
  Feeds the "Admin Overhead" bar in each cell and the overhead section.
- `agg_gantt_items` — read by `_render_gantt` (`capacity_planner.py:936`) and
  `_render_function_timeline` (`capacity_planner.py:1094`) for the
  Gantt/timeline rows. Also read by `_load_top_items`
  (`capacity_planner.py:329`), but that function is **dead** — see Known
  issues.
- `db/leaves.py::get_leave_capacity(yms)` — called live at
  `capacity_planner.py:1559` to net company holidays and individual leave
  days out of each developer's effective capacity for the M0/M1/M2 grid.
- `db/standalone.py::load_all_classifications()` — called live inside
  `_panel_body` (`capacity_planner.py:1816`) to list a developer's
  category-classified standalone tasks for the selected month in the detail
  panel.
- `config/dev_capacity.py` — imports `DEVELOPERS` and `DEV_MAP`
  (`capacity_planner.py:12`), i.e. the `ALL_STAFF`-derived roster filtered to
  `team in ("Development", "Mobile")`. **This file does not import
  `config/team_mapping.py`'s `TEAM_MAPPING` at all** — see Known issues for
  why that matters.
- `config/settings.py::ADO_BASE_URL` — used only to build ADO deep-links on
  item cards in the detail panel.

**Not used, despite being plausible candidates**: `db/admin_hours.py` (no
import anywhere in the file — per-developer admin-hours overrides from that
module play no part in this page's overhead math, which comes entirely from
`agg_standalone_overhead`/`load_all_classifications`), `data/loader.py`'s
`load_data()` DataFrame cache (this page never calls it — it only imports
`get_ui_cache_bust()` for its own render cache key, `capacity_planner.py:1537`),
and `db/aggregations.py`'s `agg_dev_monthly_capacity` (only referenced from
the dead `_load_cap_agg` function, `capacity_planner.py:266`).

**Callback groups** (all module-level `@callback`, registered once at import
time by `dash.register_page`, `capacity_planner.py:28`):

- **Toolbar toggles** — `_set_view` (All Work/Enhancements/Issues,
  `capacity_planner.py:1449`), `_set_tab` (M012 vs Rest-of-2026 sub-tab,
  `capacity_planner.py:1467`), `_toggle_gantt` (show-all-sizes flag,
  `capacity_planner.py:1482`), and the function-timeline size filter
  (`_set_func_size` / `_render_func_timeline`, `capacity_planner.py:1498`
  and `:1517`). These only write to `dcc.Store`s; the actual re-render is
  driven by the next group reacting to those stores.
- **Main grid render** — `_render` (`capacity_planner.py:1532`), the biggest
  callback in the file. Takes `view`/`tab`/`show_all`/`cust_filter` as
  Inputs, loads all data (`_load_task_dev_data`, `_load_standalone_data`,
  `get_leave_capacity`), computes the KPI row, and renders the grid + Gantt +
  subtitle + overhead section in one shot. Front-ended by a manual
  process-global memo cache (`_RENDER_CACHE`, `capacity_planner.py:20`),
  keyed on `(view, tab, show_all, cust_key, bust)` where `bust` comes from
  `get_ui_cache_bust()` — a hand-rolled cache layered *on top of* the
  existing `data/loader.py` cache described in master.md §6/db.md §6, not a
  use of it.
- **Detail panel** — `_open_panel` (pattern-matched cell click →
  opens the Offcanvas, `capacity_planner.py:1623`), `_panel_body` (renders
  the panel content from a fresh SQL query, `capacity_planner.py:1707`), and
  `_dcap_update_flt` (the panel's own priority-filter/sort-order control,
  `capacity_planner.py:2054`).

**Reuse by `planning.py`**: `pages_dash/enhancements/planning.py:2983`
does `_cm = sys.modules.get("pages_dash.enhancements.capacity_planner")` and
then `_cm.layout()` (`planning.py:2985`) to render this page's entire layout
inside its own "Story Readiness" page. This is *not* a normal top-level
`import` — it's a runtime lookup into `sys.modules`, deliberately avoiding
the double-callback-registration error Dash would raise if `planning.py`
imported this module directly at load time (the exact hazard master.md §6
calls out and says other pages avoid by duplicating small style blocks
instead). It only works because Dash's page-discovery mechanism has already
imported `capacity_planner.py` (and therefore already run its
`@callback`/`register_page` decorators) by the time `planning.py`'s layout
function runs. From this file's side there is no explicit export list or
`__all__`, no "public" vs "internal" naming convention for this purpose
(`layout()` is the same function driving both `/dev-capacity` directly and
the embedded copy in `/planning`), and `tests/perf_pages.py:131` separately
reaches into four underscore-prefixed "private" helpers
(`_load_cap_agg`, `_load_top_items`, `_load_standalone_data`, `_months012`)
for perf probing — two of which (`_load_cap_agg`, `_load_top_items`) are
dead in the actual page. So: this file was not written as a standalone,
self-contained page in isolation — it's actively depended on by at least two
other files via non-standard access paths (`sys.modules` lookup, and direct
import of "private" helpers), with no formal interface protecting either.

## Known issues / quirks

- **File size / maintainability**: ~2,065 lines mixing layout, six render
  functions, and nine callbacks in one file — not the extreme case cited in
  master.md §7 (`planning.py` at ~5,500 lines), but on the same spectrum, and
  its `layout()` gets rendered *again* inside `planning.py`, so a bug here
  shows up on two routes at once.
- **~140 lines of dead code from a pre-task-based implementation**:
  `_prep` (`capacity_planner.py:107`), `_eff_hours` (`:129`),
  `_dev_month_items` (`:190`), and `_parse_release_ym` (`:58`) are all
  defined but never called anywhere in this file. They operate on a
  DataFrame (`_prep`) and attribute hours via `main_developer` directly
  (`_eff_hours`) — the story-level attribution style the task-based-hours
  convention (master.md §6) explicitly moved away from. Likewise
  `_load_cap_agg` (`:266`) and `_load_top_items` (`:329`), which read the
  precomputed `agg_dev_monthly_capacity` / `agg_gantt_items` tables, are
  fully superseded by `_load_task_dev_data` (`:362`) in the live render path
  and are now called only from `tests/perf_pages.py:131` — i.e. a perf
  benchmark is exercising code paths the running page no longer uses. A
  stray unused local, `done_items: list[dict] = []` (`:1812`), is a smaller
  instance of the same pattern.
- **Bypasses the "read `agg_*`, don't recompute" convention it inherited**:
  master.md §6 says pages should read `agg_*` tables rather than
  recomputing rollups at render time. This page's *live* path does the
  opposite on purpose — `_load_task_dev_data` (`:362`) and the panel query
  (`:1734`) run hand-written joins/aggregations over `work_items_main` on
  every render, because the precomputed `agg_dev_monthly_capacity` table is
  keyed on story-level `main_developer`, which can't express task-based
  attribution. That's arguably the right tradeoff given the task-based-hours
  rule, but it means `agg_dev_monthly_capacity` (per db.md §3, "Developer ×
  month × item-type counts/hours for the capacity grid") is stale
  documentation for this page — the capacity grid no longer reads it at all.
- **Two-staff-directory drift risk (master.md §7)**: this page's roster
  (`devs = DEVELOPERS` in `_render`, `capacity_planner.py:1548`) comes from
  `config/dev_capacity.py`'s `ALL_STAFF`-derived `DEVELOPERS`/`DEV_MAP`
  (`capacity_planner.py:12`), **not** `config/team_mapping.py`'s
  `TEAM_MAPPING`. `ALL_STAFF` includes Mobile-team members
  (`config/dev_capacity.py:15,18`, "Suraj Gupta", "Nishtha Arora") that
  master.md §7 confirms are absent from `TEAM_MAPPING`. Any other page or
  report that attributes the same developers' hours via `TEAM_MAPPING`
  instead of `ALL_STAFF`/`DEV_MAP` will silently disagree with this page's
  numbers for those people — this file doesn't cause the drift, but it is
  one of the two divergent sources in active use.
- **Hardcoded fiscal year and hours assumptions throughout**: `2026` is
  baked directly into query strings and literal ranges — e.g.
  `range(4, 13)` for Gantt/timeline months (`:927`, `:1085`), `range(7, 13)`
  for the "Rest of 2026" grid (`:866`), the `iteration_path LIKE '%Iteration
  2026 %'` filters (`:407`, `:430`), and the `'2026-' || LPAD(...)`
  string-building in the (dead) `_load_top_items` (`:343`). None of this
  rolls over automatically at year-end; someone has to hand-edit every one
  of these literals in January. Separately, `_HOURS_PER_DAY = 10.0`
  (`:80`) — used only for the M0 "remaining workday hours" countdown — is a
  different number from the `180h/mo` (~9h/weekday over ~20 workdays)
  default capacity used everywhere else in the same file, and the `180`
  default itself is re-hardcoded as a fallback in several places (e.g.
  `dev.get("capacity_h", 180)` at `:511`, the `DEV_MAP.get(...)` fallback at
  `:1714`) instead of importing `config.dev_capacity.DEFAULT_CAPACITY_H`.
- **Inconsistent SQL parameterization inside the same file**: the
  Customer/Internal branch of `_load_cap_agg` (`:281`–`:308`) and all of
  `_load_task_dev_data` (`:362`–`:436`) build SQL by f-string-interpolating
  `cust_filter` and `ym` values directly into the query text, while
  `_panel_body`'s query (`:1734`) uses bound parameters (`:dev`, `:pat`) for
  the equivalent inputs. The interpolated values are internally generated
  (`yms` from `_months012()`, `cust_filter` from a fixed 3-value radio), not
  raw user input, so the practical injection risk is low today — but it's an
  inconsistent pattern in the same module, and a future edit that threads a
  user-supplied string through either f-string path would have no
  bound-parameter guard rail.
- **Fragile inter-page dependency via `sys.modules`**: as described above,
  `planning.py` embeds this file's `layout()` by reaching into
  `sys.modules` rather than importing it, specifically to dodge Dash's
  duplicate-callback-registration error. That only works given Dash's page
  auto-discovery import order; there's no explicit contract (docstring,
  `__all__`, or otherwise) marking `layout()` as a reuse point, so it's easy
  to change this file's `layout()` signature or side effects without
  realizing `planning.py` depends on the exact current behavior.
- **Manual UI render-cache duplicates existing cache-busting machinery**:
  `_RENDER_CACHE`/`_prune()` (`:20`–`:26`) is a module-global dict keyed on
  `get_ui_cache_bust()`, layered on top of the loader's own cache-bust
  counter rather than using it directly for TTL — same "not safe across
  multiple worker processes" caveat that applies to `data/loader.py`'s
  caches (db.md §6) applies here too, and doubly so since this is a second,
  page-local cache with its own pruning logic to maintain.
