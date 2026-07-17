# Team Pulse

- **Route / entry point**: `/team-pulse`
- **Backing file(s)**: `pages_dash/capacity/team_pulse.py` (2,553 lines)
- **Nav location**: CAPACITY → "Team Pulse" (`app.py:115`, icon `⊡`, built ✅) — first item in the CAPACITY section, ahead of Developer Capacity, Leave Management, Admin Hours (`app.py:114-119`)

## What it does

A rolling 12-month capacity grid showing, for every team and every developer,
how much open work is on the books and how it's spread across time. The
module docstring calls it "rolling 12-month capacity grid across all teams"
(`pages_dash/capacity/team_pulse.py:1`).

The page has two halves:

1. **The grid** (`_build_grid`, `pages_dash/capacity/team_pulse.py:1195-1535`) —
   one table with a column per rolling month (`_rolling_months(12)`,
   `team_pulse.py:88-97`, always "this month + next 11", not a fixed calendar
   window) and:
   - an **Issues** section broken down by priority (P1/P2/P3/Others)
   - an **Enhancements** section broken down by size band (Big/Medium/Small/
     Very small/Unsized, derived from estimate hours — `_classify_size`,
     `team_pulse.py:71-76`)
   - grand totals per month
   - one 3-row block per developer (Hours / Issues / Enhancements), sorted by
     team order (`_dev_sort_key`, `team_pulse.py:1341-1344`)
   - a small "Items by Platform" (Mobile vs Web) mini-table above the grid
     (`_build_platform_table`, `team_pulse.py:1147-1191`)
2. **A drill-down panel** — clicking any grid cell opens a fixed right-hand
   overlay (760px wide, `team_pulse.py:1687-1703`) listing the underlying work
   items, with:
   - priority filter + sort controls (hours / priority / release date)
   - multi-select + bulk "Move Items" to another iteration month, or bulk-set
     a release date, which write back to ADO
   - a per-item "Edit" view (`_build_item_detail_content`, `team_pulse.py:451-632`)
     for changing priority, source (Customer/Internal), story size, developer,
     designer, story owner, iteration, and release date in place, Designer
     Planning-style toggle buttons

Filters across the top: team pill bar (All / Web Dev / Mobile Dev / Design /
QA / Story Writers), a rolling horizon selector (30/90/180/365 days,
`_hpill`, `team_pulse.py:1612-1625`, default 365), a Customer/Internal source
filter, and a Mobile/Web platform filter. All four combine with AND semantics
before the grid is built.

## Why it exists

Gives PMs/EMs one screen to see workload distribution across the whole
delivery org — not just "is this developer overloaded this sprint" but
"how does load trend over the next year, and which priority/size buckets is
it concentrated in." The drill-down + inline edit + bulk move lets a PM
rebalance load (move items to a lighter month, reassign source/size/dev)
without leaving the page or opening ADO directly.

## How it works

**Data sources** — everything is queried directly against `work_items_main`
via `data.loader.engine` (`team_pulse.py:12`), with **no use of
`data/loader.py::load_data()`'s cached DataFrame at all**. Every filter click
or panel open issues a fresh `engine.connect()` query:

- `_load_items()` (`team_pulse.py:119-174`) — one row per open Enhancement/
  User Story/Issue/Bug/Bug_UI/Bug_Text with a `main_developer` set, joined to
  `agg_story_estimation` for `est_status`. This is the "taskless" fallback
  layer (hours from `original_estimate` when a story/bug has no child tasks).
- `_load_task_hours()` (`team_pulse.py:178-228`) — one row per **active Task**
  under one of those parent types, `INNER JOIN`ed to its parent
  (`team_pulse.py:195`), hours from `remaining_work` falling back to
  `original_estimate - completed_work`. This is what actually drives the
  grid's per-developer Hours/Issues/Enhancements rows
  (`team_pulse.py:1282-1330` overlays this onto `_load_items()`'s taskless
  rows).
- `_dev_panel_load()` (`team_pulse.py:232-318`) and `_panel_load()`
  (`team_pulse.py:322-404`) — separate, slightly different queries that back
  the drill-down panel, one for dev-cell clicks (grouped by task assignee)
  and one for team/priority/size-cell clicks (grouped by story iteration).
- `agg_story_estimation` (db.md §3) is the only aggregate table this page
  reads. It does **not** touch `agg_dev_monthly_capacity` or
  `agg_standalone_overhead` — both exist in the schema and both look like a
  natural fit for a "capacity grid" page, but this one recomputes everything
  from `work_items_main` at click time instead of reading either.
- **No leave/holiday tables** (`p_dev_leaves`, `p_company_holidays`) are read
  anywhere in this file — confirmed by grep, zero matches. Hours shown are
  raw remaining-work sums with no leave/holiday adjustment.
- **No `standalone_task_classifications`** — confirmed by grep, zero matches
  for "standalone" anywhere in the file.

**Team roster / config dependency** — imports only from
`config/dev_capacity.py`: `DEVELOPERS`, `DEV_NAMES`, `DESIGNER_NAMES`,
`STORY_OWNER_NAMES` (`team_pulse.py:11`). It does **not** import anything
from `config/team_mapping.py` — confirmed by grep, no reference to
`TEAM_MAPPING`, `TEAMS_LIST`, or `TEAM_TYPES` anywhere in the file. So this
page sits entirely on the `ALL_STAFF`/`config/dev_capacity.py` side of the
drift documented in master.md §7, not the `TEAM_MAPPING` side.

The page then builds its **own third roster**, `_TEAM_MAP`
(`team_pulse.py:34-47`): it starts from `DEVELOPERS` (mapping Mobile→"Mobile
Dev", everyone else on `DEVELOPERS`→"Web Dev"), then hardcodes six more
name→team entries on top — `Furquan Nayyar`, `Kaushik Awasthi`,
`Gagandeep Kaur` → "Design"; `Sunil`, `Vineeta`, `Varun T` → "QA"; `Chhavi
Bhardwaj`, `Geetika Khanna` → "Story Writers". **`Varun T` appears in neither
`config/team_mapping.py::TEAM_MAPPING` nor `config/dev_capacity.py::ALL_STAFF`**
(confirmed by repo-wide grep — the only hit for "Varun" in the whole codebase
is this line) — a third, page-local roster fork on top of the two
already-drifted directories from master.md §7. Also note `Sunil` and
`Vineeta` here are bare first names, while `ALL_STAFF` lists them as `Sunil
Nigam` / `Vineeta Arora` — if `main_developer` in ADO is ever the full name,
this hardcoded partial-name key silently fails to match and the person falls
into the `"Other"` bucket instead of "QA".

**Write-back** — bulk move (`_panel_move`, `team_pulse.py:2146-2197`) and the
per-item Save (`_commit_tp_changes`, `team_pulse.py:2444-2523`) both write the
local Postgres row first, then call ADO write functions
(`sync.ado_write.write_iteration` / `write_fields`), matching the write-back
convention in master.md §6. Two deviations from that convention:

- The per-item ADO write is wrapped in a bare `try/except Exception: pass`
  (`team_pulse.py:2509-2513`) with **no logging at all** — the file never
  imports `logging` (grep confirms zero matches) — and the success toast
  ("Saved #wid to ADO", `team_pulse.py:2521-2523`) fires unconditionally, so a
  silently-failed ADO write still shows the user a success message.
- Neither write path calls `bust_loader_cache()` / `bust_ui_cache()`
  afterward (grep confirms zero matches for either). This is low-impact for
  *this* page, since it never reads through the cache to begin with, but any
  other page reading the same rows through `data/loader.py`'s 15-minute cache
  won't see the change until the next sync or cache expiry.

**Bypasses the Related-link parent-id patch** — `data/loader.py::_load_rel_map()`
(see db.md §1) exists specifically to patch `parent_id` for Tasks linked to
their parent only via `System.LinkTypes.Related` rather than a formal
parent/child link. Because this page never calls `load_data()` and instead
joins on `work_items_main.parent_id` directly (`team_pulse.py:195, 261, 272,
345, 356`), any Task in that Related-only state is invisible to the grid's
hour totals — it has no formal `parent_id`, so it never survives the `INNER
JOIN`/`GROUP BY parent_id` in `_load_task_hours`, `_dev_panel_load`, or
`_panel_load`.

## Task-based hours logic — verified against master.md §6

The convention states Team Pulse computes hours/counts from task assignments
(not `main_developer` on the story), that "Dev Complete" counts as active,
and that "Standalone" means `parent_id IS NULL` only. Checked against the
code:

- **Task-based, not story-based**: confirmed. `_load_task_hours()`
  (`team_pulse.py:178-228`) is the primary hours source, keyed on
  `t.main_developer` (the Task's own assignee) and `t.iteration_path` (the
  Task's own sprint), overlaid onto the grid in `team_pulse.py:1279-1330`
  with an explicit comment: *"Hours and issue/enh counts for task-having
  items use each task's own iteration_path so they land in the month the
  developer is actually working."* Only items with **no** child tasks at all
  fall back to the story's own `original_estimate`/`main_developer`
  (`team_pulse.py:1266-1277`, the `has_tasks` flag).
- **"Dev Complete" counts as active — true in the grid, false in one panel**:
  `_load_task_hours()`'s state filter (`team_pulse.py:197-199`) excludes only
  `Closed, Resolved, Not Required, Not an issue` — `Dev Complete` tasks are
  counted, matching the convention. `_dev_panel_load()`'s equivalent subquery
  (`team_pulse.py:267-270`) matches this. **However**, `_panel_load()` — used
  for the team/priority/size drill-down panels, not the dev-cell ones — has
  its own two subqueries (`tk`, `ar`) that add `'Dev Complete'` to the
  exclusion list (`team_pulse.py:349-351` and `team_pulse.py:360-362`). So a
  Task in "Dev Complete" state is counted as active hours in the grid cell
  you clicked, but excluded from the fallback `task_est` figure inside the
  panel that opens for that same cell (for `issue_pri`/`enh_size` kinds) —
  the two numbers can disagree for exactly this reason.
- **Standalone (`parent_id IS NULL`) doesn't apply here — by design, not by
  omission**: this page has no concept of "standalone" tasks at all (zero
  hits for the word). `_load_task_hours()` uses an `INNER JOIN` on
  `t.parent_id = w.work_item_id` (`team_pulse.py:195`), which structurally
  excludes any Task with a null `parent_id` — those are exactly the
  "standalone" tasks that `standalone_task_classifications` /
  `agg_standalone_overhead` exist to track (db.md §2-3), and that Developer
  Capacity's `capacity_planner.py:240-251` folds into its own hours via
  `agg_standalone_overhead`. Team Pulse's per-developer Hours row is
  therefore parent-scoped work only — a developer's admin/overhead/standalone
  task time is invisible here even though it's visible on Developer
  Capacity. Anyone comparing the two pages' hour totals for the same
  developer should expect Team Pulse's number to run lower.

## Known issues / quirks

- **File size**: 2,553 lines, the second-largest page file in the codebase
  after `enhancements/planning.py` (5,485 lines) — see master.md §7's
  "Monolithic page files" note. Layout, ~30 callbacks, and 5 near-duplicate
  SQL query functions (`_load_items`, `_load_task_hours`, `_dev_panel_load`,
  `_panel_load`, plus the item-detail query in
  `_build_item_detail_content`) all live in one file with no extraction.
- **Three drifted staff rosters, not two**: on top of the `TEAM_MAPPING` vs
  `ALL_STAFF` drift already flagged in master.md §7, this file adds its own
  `_TEAM_MAP` (`team_pulse.py:34-47`) with a name (`Varun T`) that appears in
  neither upstream config. Bare first-name keys (`Sunil`, `Vineeta`) also
  risk silently miscategorizing anyone whose `main_developer` value is the
  full name — they'd fall into the catch-all `"Other"` team bucket
  (`team_pulse.py:155`, `_TEAM_MAP.get(r.main_developer, "Other")`) with no
  visible error.
- **`Dev Complete` handling disagrees with itself**: the grid counts
  `Dev Complete` tasks as active hours; the drill-down panel opened from an
  `issue_pri`/`enh_size` cell (via `_panel_load`'s `tk`/`ar` subqueries,
  `team_pulse.py:349-362`) does not. A user drilling into a cell can see a
  different hours figure than what's implied by the cell they clicked.
- **No leave/holiday or per-developer capacity awareness**: despite being
  branded a "capacity grid," the page never reads `p_dev_leaves` or
  `p_company_holidays`, and never reads each developer's `capacity_h` from
  `ALL_STAFF` (which is 180 for everyone anyway, so it wouldn't differentiate
  much even if used). The red/amber thresholds that color cells are flat
  hardcoded numbers with no connection to actual staffed capacity:
  `_hours_cell` turns amber above 60h and red above 120h for every developer
  regardless of role or team (`team_pulse.py:1094`); `_num_cell`'s
  count thresholds default to amber≥25/red≥32 (`team_pulse.py:1076`) and are
  overridden to 24/32 for the grand-total row (`team_pulse.py:1427`) — the
  1-point difference between 24 and 25 for otherwise-identical-looking
  thresholds looks like it could be an unintentional inconsistency rather
  than a deliberate choice.
- **No standalone-task overhead**: by construction (`INNER JOIN` on
  `parent_id`, `team_pulse.py:195`), a developer's standalone/admin task time
  never shows up in this grid, unlike Developer Capacity
  (`capacity_planner.py:240-251`, `agg_standalone_overhead`). Not a bug, but
  a real discrepancy anyone cross-referencing the two capacity pages should
  know about.
- **Bypasses `data/loader.py` entirely**: every callback re-queries
  `work_items_main` directly (5 separate query functions, each opening its
  own `engine.connect()`), rather than reading through the shared 15-minute
  DataFrame cache the rest of the app uses (db.md §6). Consequence: this page
  always reflects the current DB state (no 15-min staleness window), at the
  cost of hitting Postgres on every single filter click, team-pill click, or
  panel open — there is no caching layer at all here, in either direction.
  It also means Tasks linked to their parent only via a `Related` ADO link
  (not a formal parent/child link) are invisible to this page's hour totals,
  because `data/loader.py::_load_rel_map()`'s patch for that case
  (db.md §1) is never applied — see "How it works" above.
- **Silent ADO write failures**: `_commit_tp_changes`
  (`team_pulse.py:2444-2523`) wraps its `write_fields()` call in a bare
  `except Exception: pass` with no logging (the file imports no `logging`
  module at all), and unconditionally shows a "Saved #wid to ADO" success
  toast regardless of whether the ADO call actually succeeded
  (`team_pulse.py:2509-2523`). A transient ADO API failure would leave the
  local Postgres row updated but ADO unchanged, with the user told it worked.
- **No `bust_loader_cache()` / `bust_ui_cache()` calls**: neither write path
  (`_panel_move`, `_bulk_set_release_date`, `_commit_tp_changes`) invalidates
  the shared loader cache after writing. Low-impact for this page (it doesn't
  read through that cache), but other pages reading the same rows via
  `data/loader.py` won't see the change until the cache's 15-minute TTL
  expires or the next sync runs.
- **Month columns are iteration months, not release dates** — the page says
  so itself in a small italic note in the header (`team_pulse.py:1719-1721`:
  *"Month columns = iteration months (sprint cadence), not release dates."*),
  but it's easy to misread the grid as a release-date-based delivery
  forecast, especially since the drill-down panel separately supports moving
  an item's *release date* independent of its iteration month.
