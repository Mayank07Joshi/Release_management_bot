# Summary (VSTS Focus Area)

- **Route / entry point**: `/summary`
- **Backing file(s)**: `pages_dash/trends/summary.py` (thin route wrapper);
  shared logic in `pages_dash/trends/focus.py` (`focus_tab_content()` and
  everything it calls — not registered as its own page, see Known issues)
- **Nav location**: REFERENCE section, label "VSTS Focus Area", built ✅
  (`app.py:120-121`)

## What it does

A two-tab dashboard: **Data Load Summary** and **Addition & Deletion**, with a
shared sticky STATE multi-select filter (`focus-state-dropdown`, default
states: Active/Clarification/Estimated/New/Reopened/Request Estimate) that
applies only to the Summary tab.

- **Data Load Summary tab** (`focus.py::_render_summary`, called via
  `_render` when `tab == "summary"`): four top KPI cards (all items,
  Issues-in-scope, Enhancements-in-scope, Unestimated), then side-by-side
  Issues and Enhancements panels each with three stacked bar rows (By Type,
  By Priority/Size, Estimation split) and a callout card (P1 issue count /
  Big+Medium enhancement count), plus a "Decision Validity Gate" reminder to
  re-pull VSTS data if counts look stale before sprint planning.
- **Addition & Deletion tab** (`focus.py::_render_sprint_adl`): a filterable
  (platform / horizon / source / issue-type chips) monthly bar+line chart of
  items added vs. closed vs. net vs. running open-item total, four KPI cards
  (Open Now, Added, Closed, Net Change), and a click-through side panel
  showing the P1 items added/closed in whichever month bar was clicked.

## Why it exists

Two related but distinct jobs bundled into one nav entry: (1) a sanity check
that the local Postgres mirror of VSTS/ADO actually matches what's really in
VSTS before anyone trusts a planning decision off it ("Decision Validity
Gate", `focus.py:642-662`), and (2) a trend view of whether the backlog is
growing or shrinking, sliceable by platform/source/type, with drill-down to
the actual P1 items behind any given month's movement.

## How it works

- **Entry point**: `summary.py` just calls `focus_tab_content()` with no
  arguments, so `default_tab="summary"` and `tabs_visible=True` — the full
  two-tab UI with the tab strip and STATE filter visible (`focus.py:170,
  183-199`).
- **Data source**: `_render` (`focus.py:371-458`) issues one lightweight query
  against `work_items_main` (7 columns) scoped to activity since 2025-01-01,
  shared by both tabs; `_render_sprint_adl` (`focus.py:710`) and the month
  drill-down panel (`focus.py:1435`) each run their own separate, wider
  `work_items_main` queries (no date filter, since the ADL chart needs full
  history to compute opening backlog).
- **Sprint iteration lookup**: `_get_sprint_path()` (`focus.py:35-53`) guesses
  the current sprint's `iteration_path` by matching `%<year>%<month name>%`
  against `work_items_main.iteration_path` — best-effort, returns `None` if
  nothing matches.
- **Sprint history backfill**: `_load_sprint_history()` (`focus.py:56-68`)
  reads `p_sprint_item_history` (owned by `db/focus.py`, see `db.md` §2) —
  defined but not actually called anywhere in the current render path (see
  Known issues).
- **Callbacks**: tab switch (`_select_tab`, `focus.py:311-324`), four ADL chip
  filters (horizon/source/type/platform, `focus.py:327-361`), STATE dropdown
  sync (`focus.py:363-368`), the main content render (`focus.py:371-458`), and
  the month click → side-panel drill-down pair (`focus.py:1309-1321,
  1424-1581`) that reads `adl-month-running` (the running-open-total dict
  built by `_render_sprint_adl`) to show "Open after" in the panel.
- **Shared with two other routes/pages**: `/addition-deletion`
  (`pages_dash/trends/addition_deletion.py`, see `addition-deletion.md`) calls
  the same `focus_tab_content()`, and the Story Readiness page
  (`pages_dash/enhancements/planning.py:2982-2984`) also embeds it — via
  `sys.modules.get("pages_dash.trends.focus")` rather than a normal import
  (falls back to a "VSTS Focus Area loading…" placeholder if the module isn't
  yet in `sys.modules`). This is three consumers of one shared function, per
  the `master.md` §6 convention of sharing the function, not the page module.

## Known issues / quirks

- **Dead function: `_render_sprint`** (`focus.py:1067-1305`, ~240 lines) is
  fully defined — KPI cards, a daily bar chart, a "last 7 working days"
  table — but is never called anywhere in the codebase (confirmed by search:
  no callers besides its own `def`). The live "sprint" tab instead renders via
  `_render_sprint_adl`, a completely different Addition & Deletion view. This
  looks like a leftover from before the tab was repointed at ADL content.
- **Confusing naming from that same pivot.** The tab's internal `dcc.Store`
  id and callback names still say "sprint" (`focus-tab-sprint-btn`, tab value
  `"sprint"`, function `_render_sprint_adl`) even though the tab now shows
  Addition & Deletion content, not sprint/daily activity — a holdover from
  when `_render_sprint` (now dead, see above) backed that tab.
- **`_load_sprint_history()` is defined but unused** in the current render
  path (`focus.py:56-68`) — `p_sprint_item_history` is queried nowhere in
  `_render`, `_render_sprint_adl`, or the panel callback. Possibly meant to
  feed the dead `_render_sprint` path.
- **`focus.py` has no `dash.register_page` call** — per its own comment
  (`focus.py:14`), it used to be a standalone page and is now purely a shared
  content module. Reading it top-to-bottom without that context could suggest
  a missing registration rather than an intentional refactor.
- **P1-only drill-down panel.** The month click-through side panel
  (`_adl_panel_render`, `focus.py:1424`) only lists P1 items added/closed that
  month (`focus.py:1508-1509`); P2–P4 items are counted in the KPI totals but
  never individually listed, which can make "Added: 40" feel unexplained when
  only 3 P1 rows show.
- **Three independent full/near-full `work_items_main` reads per page
  interaction**: the base `_render` query, the `_render_sprint_adl` query, and
  the panel-drill-down query in `_adl_panel_render` are three separate
  `pd.read_sql` calls with overlapping column sets rather than one shared
  query — each also independently normalizes `created_date`/`closed_date`
  timezone handling (`focus.py:740-742`, `1466-1468`).
- **Sprint-numbering assumption**: `_render_sprint` (dead) and the general
  "Sprint 1" framing elsewhere in the app assume exactly one sprint per
  calendar month; `_get_sprint_path()`'s month-name string match
  (`focus.py:35-53`) would misfire if an iteration path were ever named
  unconventionally.
