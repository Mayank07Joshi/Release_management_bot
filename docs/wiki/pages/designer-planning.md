# Designer Planning

- **Route / entry point**: `/designer-planning`
- **Backing file(s)**: `pages_dash/enhancements/designer_planning.py` (~1,655 lines)
- **Nav location**: ENHANCEMENTS → Designer Planning. Flagged placeholder
  (`⚠`, `_NAV_TREE` entry `("Designer Planning", "/designer-planning", "∖",
  False)` in `app.py`) — see Known issues for whether that flag looks accurate.

## What it does

A monthly design-schedule and design-load tracker for Enhancements/User
Stories, per its own docstring. Renders as:

- **KPI bar** — Design Due This Month, Overdue, Designer Unassigned, Complete
  (with %), Total Stories (`_build_kpis`, line 249).
- **Monthly design load table** — count of stories per size (Big/Medium/Small/
  Very Small) per design-start month, plus a weighted "load pts" row
  (Big=8, Medium=5, Small=3, Very Small=1), and a per-designer load panel next
  to it (`_build_summary_panels`, line 284).
- **Story table** — one sticky-header, sticky-first-two-columns table with a
  column per rolling plan month (12 months starting this month), each cell
  colour-coded by status (complete/overdue/due now/scheduled) and showing the
  assigned designer's first name. Clicking a row opens a full edit panel.
- **Side panel** (`_render_panel`, line 1022) — per-story editor: designer,
  priority, type (Customer/Internal), iteration month (dropdown), release
  month (dropdown), story size, developer, story owner, and a read-only
  "Design Progress" gate badge (`_story_status_badge`, line 99, reading
  `p_planning_gates`). Edits are staged in a `dp-pending` store and committed
  together via a single "Save Changes" button (`_commit_all_changes`,
  line 1535), which fires both an ADO write-back and a local DB update.
- **Balance Designers panel** (`_build_balance_panel`, line 437) — a
  dedicated view for rebalancing incomplete-design load across designers:
  a target-line bar per designer (target ≈ 20 load pts), and per-story
  one-click reassign/unassign buttons.

## Why it exists

"Designers start one month before the planned dev month" is a hardcoded
process rule this page encodes directly (`_des_ym`, line 88-91, and the
banner text on line 903) — the page exists to make that one-month design lead
time visible and actionable: who's behind, who's overloaded, and who's
unassigned, without anyone having to compute "dev month minus one" by hand
against ADO's iteration picker.

## How it works

**Config dependencies**: imports `DEV_NAMES`, `DESIGNER_NAMES`,
`STORY_OWNER_NAMES` from `config/dev_capacity.py` (line 12) — **not**
`config/team_mapping.py`. `DESIGNER_NAMES` is derived from `ALL_STAFF` entries
where `team == "Design/Video"` (currently 5 people: Furquan Nayyar, Kaushik
Awasthi, Akarsh Bahl, Gagandeep Kaur, Neeraj Kumar — `config/dev_capacity.py`
lines 29-34, 46, 53). Since `master.md` §7 already flags `ALL_STAFF` and
`TEAM_MAPPING` as two independently-hardcoded, drifted staff directories, this
page inherits whichever drift exists in `ALL_STAFF` specifically.

**"In design" / active-dev definition**: `_DEV_STATES = frozenset(["Active",
"Dev InProgress", "Dev Review", "Dev Complete"])` (line 19) — this is the
page's own state set, separate from (but consistent in spirit with) the
Team Pulse / Dev Capacity convention noted in project memory that "Dev
Complete counts as active work." A story only becomes "not_in_dev" /
"Planned" status if its `state` falls outside this set.

**"Design done" definition**: a story counts as design-complete when **both**
`p_planning_gates.our_screens` and `p_planning_gates.html_screens` are true
(`_load_data`, line 192; `_render_panel`, line 1064) — a narrower bar than the
5-gate `_story_status_badge` display (`claude_screens`, `text_written`,
`our_screens`, `html_screens`, `sn_signoff`, line 104-109), which shows all 5
gates but only the 2 (`our_screens`/`html_screens`) actually drive this page's
completion/status logic and KPI counts.

**Data source**: `_load_data()` (line 154) reads `work_items_main` directly
(not an `agg_*` table) filtered to `work_item_type IN ('Enhancement','User
Story')`, excluding a hardcoded closed-state list, and requiring
`iteration_path` to match `Iteration [0-9]{4} [0-9]{2}-` — left-joined to
`p_planning_gates`. No caching layer of its own; every page load and every
panel re-render (e.g. `_render_panel`, `_open_balance_panel`) re-queries the
DB directly via `engine.connect()`/`engine.begin()`.

**Write-back**: every edit in the side panel and the Balance Designers panel
follows the documented pattern from `master.md` §6 — local `work_items_main`
UPDATE first, then fire-and-forget `sync.ado_write.write_fields()` (e.g.
`_commit_all_changes` line 1587-1594, `_reassign_designer` line 1625-1629,
`_unassign_designer` line 1648-1652, `_change_dev_month` line 1385-1389).

**Cross-reference**: "Design Progress" badge text explicitly says "Driven by
Story Readiness gates. Set gates there to update." (line 1292) — i.e. the
gate booleans themselves are edited on the `/planning` (Story Readiness) page,
not here; this page only reads and displays them.

## Known issues / quirks

- **"Designer load" panel likely always shows zero for every real designer.**
  `_build_summary_panels()`'s designer-load block (line 352-368) buckets
  stories by `dev = s.get("developer")` (i.e. `main_developer`) and checks
  `if dev in _DESIGNERS` — but `_DESIGNERS` is `DESIGNER_NAMES`
  (Design/Video team), and `developer` is populated from `main_developer`,
  which is a Development/Mobile-team person per `config/dev_capacity.py`. The
  two name lists don't overlap, so this condition is essentially always
  false, and virtually every in-plan story falls into `unassigned_counts`
  instead of a named designer's row. Contrast with `_build_balance_panel()`
  (line 444), a few hundred lines later, which correctly keys off
  `s.get("designer")` (`main_designer`). This looks like a copy/paste bug —
  one panel uses the right field, the other doesn't.
- **Dead callback wired to IDs that don't exist in the rendered layout.**
  `_change_dev_month()` (line 1365-1390) has `Input("dp-devmon-minus",
  "n_clicks")`, `Input("dp-devmon-plus", "n_clicks")`, and
  `Output("dp-devmon-display", "children")`. None of `dp-devmon-minus`,
  `dp-devmon-plus`, or `dp-devmon-display` appear anywhere in `_render_panel()`
  or `layout()` — only `dp-devmon-value` (a bare `dcc.Store`, line 1256) is
  actually rendered. As written, this callback can never fire; the only way
  to change a story's dev month today is the "Iteration" dropdown
  (`dp-iter-dropdown`), which has its own separate callback
  (`_select_iteration_dd`, line 1468) that stages the change into `dp-pending`
  rather than writing immediately like `_change_dev_month` does. Worth
  deciding whether to finish wiring the +/- buttons into the panel or delete
  the orphaned callback.
- **Nav "placeholder" flag looks stale given the depth of what's actually
  built.** At ~1,655 lines this is a fully wired page: live ADO write-back,
  a staged-edit-then-commit pattern, a dedicated load-balancing sub-view, and
  KPI/status logic tied into the shared `p_planning_gates` table — comparable
  in scope to several `✅`-flagged pages. `master.md` §5 already flags this
  discrepancy generally ("the amber dot may just mean 'not yet signed off for
  general use'"); nothing observed in the code itself explains *why* it's
  still marked placeholder (no `TODO`/`FIXME`/incomplete-feature markers
  found), which is consistent with "not yet signed off" rather than "unbuilt."
- **`_ITER_RE`'s escaped backslashes assume a specific ADO iteration-path
  shape.** `_ITER_RE = re.compile(r'\\(\d{4})\\Iteration \d{4} (\d{2})-')`
  (line 66) only matches paths containing a literal `\<year>\Iteration <year>
  <month>-...` segment. Any story whose `iteration_path` doesn't follow that
  exact shape (e.g. mid-migration data, a differently-named root iteration)
  is silently dropped from `_load_data()` — `_parse_iter()` returns `None`
  and the row is skipped (line 187-189) with no visible warning that data
  was excluded.
- **No caching.** Unlike `delivery_timeline.py` (page-local 300s cache) or
  the `agg_*`-table convention described in `db.md` §3 ("zero runtime
  computation on read"), every render here — including opening the side
  panel or the Balance Designers panel — re-runs a fresh SQL query against
  `work_items_main`/`p_planning_gates`. Fine at current data volume, but a
  departure from the pattern the rest of the codebase is converging on.
- **Hardcoded design-lead-time and load-target constants.** The "one month
  before dev month" offset (`_des_ym`) and the `_TARGET_PTS = 20` per-designer
  target (line 49) are both bare constants in the module, not sourced from
  any config file — changing either requires an in-file edit, unlike e.g.
  `STORY_OWNER_NAMES`/`DESIGNER_NAMES` which at least come from
  `config/dev_capacity.py`.
