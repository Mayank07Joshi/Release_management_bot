# Estimation Status (Bugs & Issues)

- **Route / entry point**: `/bugs-unestimated`
- **Backing file(s)**: `pages_dash/bugs/bugs_unestimated.py` (thin page shell);
  logic and markup delegated to `pages_dash/enhancements/planning.py`'s
  `_load_unestimated_data()` (line 132) and `_build_unest_tab()` (line 1423),
  plus that module's callbacks (roughly lines 4749–5014)
- **Nav location**: BUGS & ISSUES → "Estimation Status" (`app.py` `_NAV_TREE`,
  line 111) — nav "built" flag is `True` (no amber placeholder dot)

## What it does

Shows which **2026 Bugs/Issues** (ADO types `Bug`, `Bug_UI`, `Bug_Text`) are
missing estimates, broken down by developer and month. Structurally identical
to the Enhancements Estimation Status page (`/unestimated`,
`docs/wiki/pages/unestimated.md`): a KPI strip (Total Unestimated, P1 Items,
Issues, Devs with P1 Gap — the "Enhancements" card is suppressed here), a
Developer × Month matrix (green = estimated count, red/amber = unestimated
count colored by whether any P1/P2 items are in that cell), a Priority
Breakdown table with a HIGH/MEDIUM/LOW risk tag per developer, and a 760px
slide-in side panel (opened from a matrix cell) listing individual items —
grouped into Bug/Bug UI/Bug Text sub-sections — each linking out to the ADO
work item.

## Why it exists

Same rationale as `/unestimated`, applied to the bug/issue backlog: gives QA
leads and PMs a fast read on which bugs are sitting unestimated, split by
who owns them and which sprint/month they're targeted for, without a manual
ADO query. It is the Bugs & Issues counterpart of the same underlying
matrix/panel view that `planning.py`'s own "Unestimated Items" tab also
renders (for the combined Enhancement + Bug set).

## How it works

**Data source**: `agg_story_estimation` (see `db.md` §3), joined to
`work_items_main` for `release_date` — exactly the same query as
`/unestimated`, run by the same function,
`_load_unestimated_data()` (`pages_dash/enhancements/planning.py:132`):

```sql
SELECT e.work_item_id, e.title, e.work_item_type, e.main_developer, e.story_owner,
       e.month_key, e.est_status, e.task_count, e.task_missing_count, e.task_est_sum, e.priority,
       COALESCE(w.release_date, '') AS release_date
FROM agg_story_estimation e
LEFT JOIN work_items_main w ON w.work_item_id = e.work_item_id
WHERE e.month_key IS NOT NULL
ORDER BY e.month_key NULLS LAST, e.priority NULLS LAST, e.work_item_id
```

The loader buckets `work_item_type` into `"Enhancement"` or a synthetic
`"Issue"` bucket for everything else (`planning.py:156`) — in practice that
"everything else" is `Bug`/`Bug_UI`/`Bug_Text`, since those are the only
other types `sync/aggregator.py::_build_story_estimation()`'s `_ITEM_TYPES`
(`{"Enhancement"} | _BUG_TYPES`, `sync/aggregator.py:33`) writes into
`agg_story_estimation` in the first place. `bugs_unestimated.py`'s
`layout()` (line 36–41) filters the shared result down to `type ==
"Issue"` before calling `_build_unest_tab(unest_items,
hide_cards={"enhanc"})`. As on `/unestimated`, `_build_unest_tab()`
re-filters to `est_status in ("unestimated", "partial")` for the KPI counts
and Priority Breakdown table, but keeps `estimated`/`estimated_via_tasks`
rows too for the matrix's green cells.

**`hide_cards={"enhanc"}`**: suppresses the "Enhancements" KPI card (would
always read 0% on an Issues-only item set) and keeps "Issues" — the inverse
of `unestimated.py`'s `hide_cards={"issues"}`.

**Key callbacks** — registered once, in `planning.py`, not in
`bugs_unestimated.py` (see "Known issues / quirks" — same mechanism as
`/unestimated`):
- `_unest_card_click` (`planning.py:4763`) — KPI card click → inline table.
- `_unest_update_flt` (`planning.py:4814`) — inline table sort/dev dropdowns.
- `_unest_matrix_toggle` (`planning.py:4833`) — matrix cell / close / backdrop
  click → sets or clears the `unest-panel-filter` store.
- `_unest_matrix_panel` (`planning.py:4959`) — renders the slide-in panel,
  grouping items by `raw_type` into separate Bug / Bug UI / Bug Text
  sections (`_build_sp_body`, `planning.py:4907`) — this is the one place
  the Type dropdown (`unest-sp-type-ctrl`) actually does something useful,
  unlike on `/unestimated`.
- `_unest_sp_update_flt` (`planning.py:5002`) — side panel sort/type
  dropdowns re-filter the open panel.

These callbacks target component IDs (`unest-kcard`, `unest-matrix-cell`,
`unest-panel-filter`, `unest-side-panel`, etc.) that are defined identically
in `bugs_unestimated.py`, `unestimated.py`, and `planning.py`'s own
"Unestimated Items" tab layout. Only one of these three pages is ever mounted
in the DOM at a time, so the shared IDs don't collide at runtime — see the
double-registration note below for why the *callback definitions* still only
exist once.

## Known issues / quirks

- **Deliberate no-top-level-import pattern.** `bugs_unestimated.py`'s own
  comment (lines 7–8, repeated at line 37) states the same rationale as
  `unestimated.py`: importing `planning.py` at module top level would cause
  Dash to double-register its callbacks. This holds up: `planning.py` is a
  `dash.register_page`'d module in its own right (path `/planning`), so
  Dash's page-discovery import at app startup already executes every
  `@callback` decorator in the file exactly once, against the app's single
  global callback registry. `bugs_unestimated.py` only needs the two
  *functions* `_load_unestimated_data()`/`_build_unest_tab()` — deferring
  that import into `layout()` (invoked per page-request, well after startup
  page-discovery has already imported and cached `planning.py` in
  `sys.modules`) means the import is a cache hit, not a re-execution of
  `planning.py`'s module body, so nothing gets registered twice. This is the
  same pattern master.md §6 documents under "Page file shape" /
  "Shared tab content": import the function, not the module; the style
  constants (`_TX`/`_MT`/`_BD`, the panel style dicts at lines 9–33) are
  duplicated verbatim from `unestimated.py` rather than imported, for the
  same reason.
- **Bug/Bug_UI/Bug_Text distinction is real here, unlike on `/unestimated`.**
  The side panel Type filter (`unest-sp-type-ctrl`) and the panel body's
  per-type grouping (`_build_sp_body`, `planning.py:4907`) are meaningful on
  this page since items span all three raw types — worth noting this is the
  one of the two pages where that control isn't a no-op.
- **`agg_story_estimation` naming is slightly misleading.** `db.md` §3
  describes the table as "Estimation status per 2026 Enhancement," but this
  page depends entirely on it also carrying Bug/Bug_UI/Bug_Text rows (per
  `sync/aggregator.py:33`'s `_ITEM_TYPES`). Anyone extending `db.md` from
  memory alone could miss that this page reads from it at all.
- **KPI numbers and matrix can disagree at a glance** — same as
  `/unestimated`: KPI/Priority-Breakdown counts are `unestimated`/`partial`
  only, while the matrix's green "est" cells and per-developer "+N est"
  total also include `estimated`/`estimated_via_tasks` rows, by design.
