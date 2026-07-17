# Overview

- **Route / entry point**: `/overview`
- **Backing file(s)**: `pages_dash/trends/overview.py`
- **Nav location**: top of sidebar, unlabeled section (first entry in
  `app.py`'s `_NAV_TREE`, `section_label=None`) — label "Overview", built ✅
  (`app.py:97-99`)

## What it does

A single-screen "Monday-morning glance" dashboard: a header bar showing a
hardcoded "Built" badge and the current sprint context string (e.g. "Jul 2026 ·
Sprint 1 · Day 16 / 31"), followed by three rows of KPI tiles grouped by
stream — **Enhancements**, **Bugs & Issues**, **Capacity** — each tile a
big number with a label and, where relevant, a colored risk cue (green/amber/
red) and a click-through link to the page that owns that data (`/planning`,
`/issue-planning`, `/dev-capacity`, `/release-status`, `/admin-hours`). No
filters, no callbacks — everything is computed once at page load.

## Why it exists

Gives a PM/EM a single read before drilling into any of the five deeper
dashboards it links out to — "work the screens bottom-up to decide (capacity,
then bugs, then enhancements) and top-down to track," per the page's own copy
(`overview.py:229-234`). It exists specifically so no one has to open five
pages just to see whether anything is on fire.

## How it works

Everything lives in `layout()` (`overview.py:77-266`); each KPI section runs
its own independent, individually `try/except`-wrapped query so one failing
query degrades that section rather than the whole page:

- **Bugs KPIs** (`overview.py:89-107`): reads `work_items_main` filtered to
  `work_item_type IN ('Bug','Bug_UI','Bug_Text')` and an open-state allowlist,
  to compute Open P1 / P2 / Unassigned counts.
- **Enhancements KPIs** (`overview.py:114-127`, `139-145`): reads
  `work_items_main` for `Enhancement`/`User Story` excluding a closed-state
  list, cross-referenced against `p_planning_gates.sn_signoff` (`overview.py:
  130-137`) to compute Stories Ready / Stuck in gates / In release pipeline.
- **Capacity KPIs** (`overview.py:147-179`): reads `agg_dev_monthly_capacity`
  (current month) and `agg_standalone_overhead`, joined against
  `config.dev_capacity.DEVELOPERS`, to compute % of team capacity used, admin
  overhead %, average story hours, and developer headcount. This follows the
  `db.md` §3 convention of reading precomputed `agg_*` tables instead of
  aggregating `work_items_main` at render time.
- Color thresholds (`overview.py:181-191`) recolor the "Stories ready" and
  "Team capacity used" tiles based on simple ratio/percentage cutoffs.

No writes, no `bust_loader_cache()` calls needed — this page is read-only.

## Known issues / quirks

- **Hardcoded open-state list duplicated instead of reused.** The module
  defines `_OPEN_STATES` as a frozenset at `overview.py:17-21`, but the bugs
  query builds its own separate hardcoded string `_OPEN_IN` with the same nine
  states re-typed by hand at `overview.py:84-88` instead of joining
  `_OPEN_STATES`. `_OPEN_STATES` itself is never referenced anywhere in the
  file — dead constant. If the open-state list ever changes, there are two
  places to edit and only one of them does anything.
- **"Built" badge is hardcoded, not derived from `_NAV_TREE`.** `overview.py:
  202-209` always renders a green "Built" pill regardless of the actual
  `is_built` flag for `/overview` in `app.py`'s `_NAV_TREE`. Currently
  consistent (both say built), but if the nav flag ever flips, this badge
  won't follow it.
- **"Sprint 1" is a hardcoded literal**, not derived from any sprint-numbering
  data (`overview.py:81`: `f"{today.strftime('%b %Y')} · Sprint 1 · Day
  {today.day} / {days_in_month}"`). Assumes exactly one sprint per calendar
  month, matching the same assumption made in `trends/focus.py`'s sprint tab.
- **"Design at-risk" KPI is a permanent placeholder** — `overview.py:243`
  renders the literal string `"—"` with no href and no underlying query; it's
  not wired to any data source yet.
- **Four separate `engine.connect()` calls per page load** (one each for bugs,
  enhancements, gates, capacity, overhead), each independently try/excepted.
  Deliberate for fault isolation per section, but means five round trips
  instead of one on every render.
- **`config.dev_capacity.DEVELOPERS`** feeds the capacity KPIs directly; per
  `master.md` §7, this list can drift from `config/team_mapping.py`'s
  `TEAM_MAPPING` — anyone present in one but not the other will silently
  under/over-count here.
