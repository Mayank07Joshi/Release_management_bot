# Estimation Status (Enhancements)

- **Route / entry point**: `/unestimated`
- **Backing file(s)**: `pages_dash/enhancements/unestimated.py` (thin page shell);
  logic and markup delegated to `pages_dash/enhancements/planning.py`'s
  `_load_unestimated_data()` (line 132) and `_build_unest_tab()` (line 1423),
  plus that module's callbacks (roughly lines 4749–5014)
- **Nav location**: ENHANCEMENTS → "Estimation Status" (`app.py` `_NAV_TREE`,
  line 104) — nav "built" flag is `True` (no amber placeholder dot)

## What it does

Shows which **2026 Enhancements** are missing estimates, broken down by
developer and month. The page opens with a KPI strip (Total Unestimated, P1
Items, Enhancements, Devs with P1 Gap — the "Issues" card is suppressed on
this page, see below), a Developer × Month matrix where every cell shows an
estimated count (green) and unestimated count (red/amber depending on
priority mix), and a Priority Breakdown table (P1–P4 counts per developer,
with a HIGH/MEDIUM/LOW risk tag). Clicking a KPI card expands an inline
sortable/filterable table under the strip; clicking a matrix cell opens a
760px slide-in side panel listing the actual items (title, priority,
estimate status, release date, task-completeness note), each linking out to
the ADO work item.

## Why it exists

Gives PMs/BAs a single place to see estimation gaps for Enhancements without
querying ADO directly — the KPI cards surface "how bad is it" (P1 gap count,
total unestimated), the matrix surfaces "who owns the gap and when is it
due," and the side panel gives the actual actionable list to chase down.
This is the Enhancements-only view of a matrix/panel first built for the
Story Readiness (`/planning`) page's own "Unestimated Items" tab; this route
exists so the same view can be linked to / landed on directly from the
sidebar instead of requiring a click into `/planning`.

## How it works

**Data source**: `agg_story_estimation` (see `db.md` §3), joined to
`work_items_main` for `release_date`. `_load_unestimated_data()`
(`pages_dash/enhancements/planning.py:132`) runs:

```sql
SELECT e.work_item_id, e.title, e.work_item_type, e.main_developer, e.story_owner,
       e.month_key, e.est_status, e.task_count, e.task_missing_count, e.task_est_sum, e.priority,
       COALESCE(w.release_date, '') AS release_date
FROM agg_story_estimation e
LEFT JOIN work_items_main w ON w.work_item_id = e.work_item_id
WHERE e.month_key IS NOT NULL
ORDER BY e.month_key NULLS LAST, e.priority NULLS LAST, e.work_item_id
```

This pulls **all** `est_status` values (`estimated`, `estimated_via_tasks`,
`partial`, `unestimated`) — not just unestimated rows — because the
Developer × Month matrix needs to show estimated counts alongside
unestimated ones. `unestimated.py`'s `layout()` (line 36–41) then filters the
result down to `type == "Enhancement"` (the loader buckets every
non-Enhancement `agg_story_estimation` row, i.e. `Bug`/`Bug_UI`/`Bug_Text`,
into a synthetic `"Issue"` type — see line 156 of `planning.py`) before
handing it to `_build_unest_tab(unest_items, hide_cards={"issues"})`.
`_build_unest_tab()` itself re-filters to `est_status in ("unestimated",
"partial")` for the KPI counts and Priority Breakdown table, but keeps every
row (including `estimated`/`estimated_via_tasks`) for the matrix.

**`hide_cards={"issues"}`**: since this page's item set is Enhancement-only,
the generic `_build_unest_tab()` KPI strip suppresses the "Issues" card
(would always read 0%) and keeps "Enhancements" — the inverse of what
`bugs_unestimated.py` (`docs/wiki/pages/bugs-unestimated.md`) does.

**Key callbacks** — all registered in `planning.py`, not in
`unestimated.py` itself (see "Known issues / quirks"):
- `_unest_card_click` (`planning.py:4763`) — KPI card click → inline table
  under the strip, toggles active-card highlighting, populates the
  developer filter dropdown for that card's subset.
- `_unest_update_flt` (`planning.py:4814`) — inline table's sort/dev dropdowns.
- `_unest_matrix_toggle` (`planning.py:4833`) — matrix cell click / panel
  close / backdrop click → sets or clears `unest-panel-filter` store
  (`{dev, month, est_type}`).
- `_unest_matrix_panel` (`planning.py:4959`) — renders the slide-in panel
  body from that store (grouped by raw ADO type, e.g. would split
  Bug/Bug_UI/Bug_Text sections if any were present).
- `_unest_sp_update_flt` (`planning.py:5002`) — side panel's own sort/type
  dropdowns re-filter the already-open panel.

All of these target component IDs (`unest-kcard`, `unest-matrix-cell`,
`unest-panel-filter`, `unest-side-panel`, etc.) that appear identically in
`unestimated.py`'s layout, `bugs_unestimated.py`'s layout, and `planning.py`'s
own "Unestimated Items" tab — see below for why one registration serves all
three.

## Known issues / quirks

- **Deliberate no-top-level-import pattern.** `unestimated.py`'s own comment
  (lines 7–8, repeated at line 37) states: "avoids importing planning.py at
  module level (top-level cross-page imports cause Dash to double-register
  planning.py callbacks)." This checks out: `planning.py` is itself a
  `dash.register_page`'d module (path `/planning`), so Dash's page-discovery
  mechanism imports it once at app startup, executing every `@callback`
  decorator in the file and registering `unest-kcard`/`unest-matrix-cell`/etc.
  against the app's single global callback registry. `unestimated.py` only
  needs the two *functions* `_load_unestimated_data()` and
  `_build_unest_tab()` to build its layout markup — it does not need to
  re-register any callback, because the callbacks planning.py already
  registered fire for whichever page is currently mounted in the DOM (Dash
  multi-page apps swap page content into one container; only one page's
  component IDs exist in the DOM at a time, so there's no ID collision at
  runtime). Deferring the import into `layout()` (called per-request, after
  page discovery has already imported `planning.py` once) means the import
  is served from `sys.modules` and never re-executes `planning.py`'s
  module-level code, so no callback is registered twice. This matches
  master.md §6's "Shared tab content" convention (import the specific
  function, not the whole page module) and its side note that
  `unestimated.py`/`bugs_unestimated.py` duplicate small style-constant
  blocks (`_TX`/`_MT`/`_BD`/the panel style dicts, lines 9–33) rather than
  importing them, for the same reason.
- **Dead filter option on this page.** The side panel's Type dropdown
  (`unest-sp-type-ctrl`, options "All Types"/"Bug"/"Bug UI"/"Bug Text",
  `unestimated.py:85–91`) is copy-pasted verbatim from the Bugs version, but
  every item on `/unestimated` has `raw_type == "Enhancement"` — selecting
  any Bug/Bug UI/Bug Text option will always produce "No unestimated items
  for this cell" in the panel. Harmless (no error), but a confusing no-op
  control that should probably be hidden or relabeled for this page.
- **`agg_story_estimation` covers more than Enhancements.** `db.md` §3
  describes the table as "Estimation status per 2026 Enhancement," but
  `sync/aggregator.py`'s `_ITEM_TYPES` (line 33) is `{"Enhancement"} |
  _BUG_TYPES`, so the table also carries Bug/Bug_UI/Bug_Text rows — which is
  exactly what `bugs_unestimated.py` relies on. Worth knowing when reading
  `db.md` in isolation.
- **KPI numbers and matrix can disagree at a glance.** The Priority Breakdown
  table and KPI strip counts are scoped to `est_status in ("unestimated",
  "partial")` only, while the matrix's "est" (green) cells and per-developer
  "+N est" total include `estimated`/`estimated_via_tasks` rows too — by
  design (per the `_load_unestimated_data()` docstring), but easy to
  misread as an inconsistency if you don't know the split.
