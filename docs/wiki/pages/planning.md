# Planning Tool (Story Readiness)

- **Route / entry point**: `/planning` — registered via
  `dash.register_page(__name__, path="/planning", name="Planning Tool")`
  (`pages_dash/enhancements/planning.py:19`). The `name=` Dash gives the page
  ("Planning Tool") is not what users see in the sidebar — the nav label is
  set independently in `app.py`, see below.
- **Backing file(s)**: `pages_dash/enhancements/planning.py` only — **5,485
  lines** (`wc -l`), the single largest page file in the codebase (master.md
  §7 names it "the extreme case" of the monolithic-page-file problem). No
  helper module of its own; everything (layout, five sub-dashboards, raw
  SQL, ~45 callbacks) lives in this one file. It does, however, reach into
  two other pages' modules at render time — see "Known issues" §3.
- **Nav location**: `app.py`'s `_NAV_TREE`, ENHANCEMENTS section, label
  **"Story Readiness"**, `built = True` (`app.py:105`):
  `("Story Readiness", "/planning", "✓", True)`.

## What it does

From a PM/BA point of view, this is the day-to-day console for the "1+2"
sprint-planning model (current sprint = **M0**, next = **M1**, sprint after
= **M2**) plus long-horizon pipeline health:

- **Story Readiness** (the only sub-dashboard actually reachable in the UI
  today — see Known issues §2):
  - A **BA Sign-Off** table, one row per open 2026 Enhancement/Issue for the
    selected month, with five click-to-toggle gate pills per story —
    Claude screens → Text written → Our screens → HTML screens → SN
    sign-off (`_GATE_FIELDS`, `planning.py:60`). Unchecking a gate cascades
    to clear every gate after it in the sequence (`planning.py:3560-3566`),
    enforcing that gates complete in order. Each toggle writes to Postgres
    via `db.planning.upsert_gate()` and appends a row to the sign-off log
    (`planning.py:3576-3585`).
  - Three top-line KPIs computed live from the loaded stories
    (`planning.py:2794-2814`): **KPI-01** — this month's (M1) Ready rate;
    **KPI-02** — next month's (M2) Draft-started coverage; **KPI-03** —
    Long-Horizon Pipeline Health (P1/P2 or Big/Medium items due Jul–Dec with
    a story at least started). An alert strip surfaces plain-English
    warnings when any KPI is behind (`planning.py:2817-2840`).
  - A **By Developer** matrix (dev × M0..Dec, cell = count + worst readiness
    state) and a **By Story** matrix (M0/M1/M2 stories × month, cell =
    assigned dev + readiness state), both filterable by BA/dev/type/size and
    clickable to open a slide-out panel of the underlying stories
    (`planning.py:897-1046`, `4451-4627`).
  - A per-story **lifecycle tracker** (📋 button) — the full 6-gate /
    14-phase / 70-step checklist from `config/lifecycle.py`, opened in a
    modal, with a running "N/70 steps complete" counter and per-gate
    progress dots (`planning.py:5133-5439`). Explicitly **not** synced with
    the 5-gate BA sign-off above — see Known issues §9.
  - A per-story **sign-off history** ("🕐 History" button) and a page-wide
    sign-off log modal, both reading `db.planning.get_log()`.
- **Unestimated Items, Developer Capacity, Delivery Timeline (Gantt), and
  BA Team Brief** are all fully built as additional "main tab" sections in
  this same file (own KPI cards, matrices, a self-contained HTML/CSS Gantt
  chart, and static BA role-brief content) — but as of this reading there is
  no nav control that can reach any of them. See Known issues §2 for exactly
  why.

## Why it exists

Azure DevOps has no native concept of "is this story ready for a developer
to pick up." This page is the enforcement mechanism for the BA/PO process
that decides that: a story can't be picked up by a developer until its
gates are green, and PMs/BAs use the KPI strip and alert strip to see, at a
glance, whether the *next* two sprints are on track to be ready before they
start — which is the whole point of planning one sprint ahead of where
developers are building (the same principle spelled out in the embedded,
currently-unreachable BA Team Brief content at `planning.py:1049-1215`,
e.g. role R-02 "M1 Story Delivery... zero exceptions").

## How it works

Everything below is one file, referenced by section:

- **Module setup** (`1-119`): imports (`data.loader.load_data` — imported
  but never called, see Known issues §8; `config.team_mapping.TEAM_MAPPING`;
  `config.settings.ADO_BASE_URL`; `config.lifecycle.{LIFECYCLE, STEP_INDEX,
  STEP_LABELS, TOTAL_STEPS}`), color tokens, the 5-field `_GATE_FIELDS` /
  `_GATE_LABELS`, the hardcoded `STORY_OWNER_MAP` (two BAs — see Known issues
  §10), and `MATRIX_MONTHS` column order.
- **Data loading** (`120-483`): `_load_unestimated_data()`,
  `_load_bug_data()`, `_load_planning_data()` — all read `agg_story_estimation`
  (joined to `work_items_main` for `release_date`) directly through
  `data.loader.engine`, per the "read agg_* tables, don't recompute" house
  convention. Gate state is layered on top from `db.planning.load_all_gates()`
  and is **always fetched fresh**, never cached; everything else (the story
  list, the dev/story matrices) sits in a hand-rolled 5-minute
  `_planning_cache` / `_bug_cache` (module-level dicts, TTL matching
  `data/loader.py`'s own cache but managed independently — see Known issues
  §13).
- **Helpers & reusable components** (`485-1315`): status/color mapping,
  gate-pill and status-badge builders, KPI/BA cards, matrix-cell renderers,
  story/bug table row builders, pagination bar, and the dev-matrix /
  story-matrix `<table>` builders (`_build_dev_matrix`, `_build_story_matrix`).
- **BA Team Brief content** (`1049-1215`): a static 3-role brief (Backlog
  Steward / Story Writer M1-M2 / Pipeline & Horizon Owner) plus placeholder
  "KPI Scorecard" and "Operating Principles" sub-tabs — built in full but
  currently unreachable (Known issues §2).
- **Static components / modals** (`1218-1420`): the sign-off log modal,
  ticket-history modal, lifecycle-tracker modal, the capacity-matrix
  slide-out panel shell, and the filter/side-panel style constants shared
  by several drawers.
- **Unestimated-items tab builder** (`1362-1729`): `_build_unest_tab()` —
  KPI cards, a dev × month estimated/unestimated matrix, and a
  priority-breakdown-by-developer table, all sourced from
  `_load_unestimated_data()`.
- **Delivery Timeline / Gantt helpers** (`1730-2742`): `_gantt_window()`,
  `_parse_release_date()`, `_build_gantt_html()` (the HTML/CSS
  Developer ▸ Function ▸ Item ▸ Task Gantt that is actually wired up to the
  render callback, reading `agg_gantt_items` / `agg_gantt_tasks` through a
  module-level 5-minute `_GANTT_CACHE`), and `_build_gantt_fig()` — a
  ~250-line **Plotly-based** alternative Gantt builder that is defined but
  never called anywhere in the file (dead code — Known issues §7).
- **`layout()` / `_build_full_layout()`** (`2747-3404`): `layout()` returns
  an empty shell with a `dcc.Store`; the `_init_plan` callback
  (`3411-3416`) immediately calls `_build_full_layout()`, which assembles
  the KPI strip, alert strip, month tabs, BA/dev/show/gate filter chips, and
  the five main sections (`readiness` / `unest` / `devcap` / `gantt` /
  `bateam`). This is also where the two live cross-page embeds happen —
  see Known issues §3.
- **Callbacks** (`3407-5485`, ~45 `@callback` blocks): grouped roughly as
  tab switching (`3419-3494`), month selection / gate toggling / story+bug
  table rendering & pagination (`3498-3945`), BA/dev/type/tier/size filter
  chips (`3949-4267`), live dev/story matrix re-render on gate change
  (`4269-4335`), sign-off log + per-ticket history modals (`4338-5131`),
  unestimated-items KPI-card and matrix side panels (`4744-5031`), lifecycle
  tracker open/step-toggle/render (`5133-5439`), and Gantt window/type/
  priority filtering plus render (`5441-5485`, with one clientside callback
  at `5452-5459` delegating expand/collapse to `assets/gantt_toggle.js`).

**Cross-references**: `db/planning.py` (BA sign-off gates + lifecycle
tracker persistence — `load_all_gates`, `upsert_gate`, `get_log`,
`load_tracker_state`, `toggle_tracker_step`), `config/lifecycle.py` (the
6-gate/14-phase/70-step checklist definition), `config/team_mapping.py`
(dev → team → role), `config/dev_capacity.py` (only `DEFAULT_CAPACITY_H`,
for the sprint-info strip text), `db/aggregations.py` +
`sync/aggregator.py` (populate `agg_story_estimation`, `agg_gantt_items`,
`agg_gantt_tasks`), and — at render time only —
`pages_dash/enhancements/capacity_planner.py` and
`pages_dash/trends/focus.py` (see next section).

## Known issues / quirks

1. **File size.** 5,485 lines is the largest page file in the repo by a
   wide margin and is explicitly called out in `master.md` §7 as the
   extreme case of the "monolithic page file" cross-cutting issue. Layout,
   five sub-dashboards' worth of markup, raw SQL, and ~45 callbacks are all
   in one module with no local helper file.

2. **Four of the five "main tab" sections are built but currently
   unreachable through the UI.** `_switch_main_tab` (`planning.py:3463-3494`)
   is written to show/hide five sections — `readiness`, `unest`, `devcap`,
   `gantt`, `bateam` — driven by clicking a `{"type": "plan-main-tab-btn",
   "tab": ...}` pattern-matched button. But the "Main tab navigation" block
   that renders those buttons (`planning.py:3028-3044`) hardcodes **exactly
   one** button, for `"readiness"`. There is no button anywhere in the file
   for `unest`/`devcap`/`gantt`/`bateam`, so `_switch_main_tab` can never
   actually navigate to any of them — the Unestimated Items, Developer
   Capacity, Delivery Timeline, and BA Team Brief sections sit permanently
   `style={"display": "none"}` (`planning.py:3218-3297`). Despite being
   unreachable, their data loads still run on **every** page visit inside
   `_build_full_layout()`: `_load_unestimated_data()`, `_load_bug_data()`,
   and — most expensively — a full call into another page's `layout()`
   function (see §3 below). Similarly, the Sign-Off Log modal's only
   trigger, `signoff-log-btn` (`planning.py:2930`), is rendered with
   `style={"display": "none"}` and no text label, so that modal is also
   unreachable by a user, even though its callback (`_toggle_log`,
   `planning.py:4348-4448`) is fully implemented.

3. **The Developer Capacity "duplication" is real, but not a copy-paste —
   it's a live cross-module call via `sys.modules`.** At
   `planning.py:2982-2985`:
   ```python
   _fm  = _sys.modules.get("pages_dash.trends.focus")
   _cm  = _sys.modules.get("pages_dash.enhancements.capacity_planner")
   _focus_section  = _fm.focus_tab_content()  if _fm  else html.Div("VSTS Focus Area loading…", ...)
   _devcap_section = _cm.layout()  if _cm  else html.Div("Developer Capacity loading…", ...)
   ```
   `_devcap_section` is the actual, live output of
   `capacity_planner.layout()` (the real `/dev-capacity` page), rendered
   into the (currently unreachable, see §2) `main-sec-devcap` div
   (`planning.py:3221-3223`). This is not literally the same code
   duplicated inline — it's a runtime lookup of an already-imported module,
   presumably to avoid the double-callback-registration problem the
   "don't import one page from another at top level" convention
   (master.md §6) warns about. But it is still a fragile pattern: it
   depends on `capacity_planner` already being present in `sys.modules`
   when `_build_full_layout()` runs (true in practice, since Dash's page
   scanner imports every file under `pages_dash/` at startup, but nothing
   in this file enforces or documents that ordering) and it silently
   degrades to a placeholder `html.Div` with no error if the module isn't
   found. `focus.py` gets the same treatment but via the documented
   pattern (calling the shared function `focus_tab_content()`, not the
   whole module) — the capacity-planner case is the one that actually
   pulls in a full page's `layout()`.

4. **Debug print left in production code.** Line 20:
   `print(">>> [planning.py] LOADED — panel=680px card=#252548")` fires on
   every process import of this module (i.e. once per app startup, not per
   request) — a bare `print()`, against the logging convention in
   master.md §6, and the stale-sounding "panel=680px" doesn't match the
   `matrix_panel`'s actual current width (`760px`, `planning.py:1279`).

5. **`_build_gantt_fig()` is dead code.** A full ~250-line Plotly-based
   Gantt builder (`planning.py:2494-2742`) is defined but never called —
   the Gantt tab actually renders through the separate, HTML/CSS-based
   `_build_gantt_html()` (`planning.py:1781`, wired up at `5476`).

6. **Hardcoded year `2026` appears 19 times**, including in regex parsing
   of ADO iteration paths (`r"Iteration 2026 \d{2}-"` at
   `planning.py:2511`, `2515`, `2542-2543`) and the hardcoded release-cutoff
   calendar `_RELEASES = {"R1": date(2026,3,31), ..., "R4": date(2026,12,18)}`
   (`planning.py:1901-1906`). Nothing about this is parameterized off
   `date.today().year` — once ADO iteration paths roll over to `2027 NN-`,
   the Gantt's enhancement filter (`_build_gantt_fig`, moot since it's dead
   — but also `_build_gantt_html`'s underlying `agg_gantt_items` table
   doesn't share this problem) and the release-cutoff overlay will need a
   manual code change to keep working.

7. **Two gate systems for the same story, no longer kept in sync.** The
   5-field "BA sign-off" gates (`_GATE_FIELDS`) and the lifecycle tracker's
   6-gate/14-phase/70-step checklist (`config/lifecycle.py`) are both
   editable from this page for the same work item, but
   `_derive_planning_gates()` (`planning.py:5137-5139`) is a no-op stub
   ("BA sign-off gates are manual-only; no auto-derive from lifecycle
   steps"), and the tracker's step-toggle callback explicitly comments
   "BA sign-off gates are now manual-only; tracker no longer auto-syncs
   them" (`planning.py:5403`). This implies the two were once linked and
   the link was deliberately removed — the two checklists can now disagree
   about a story's readiness with nothing to reconcile them.

8. **DB/UI gate mismatch.** Per `db.md` §4, the live `p_planning_gates`
   table has 12 boolean columns (`dor, story_written, estimation, in_dev,
   in_qa, ready_to_ship, delivery, claude_screens, text_written,
   our_screens, html_screens, sn_signoff`). This page's `_GATE_FIELDS`
   (`planning.py:60`) only reads/writes 5 of them
   (`claude_screens, text_written, our_screens, html_screens, sn_signoff`).
   The other 7 columns exist in the DB but are never touched from this
   file.

9. **Unused import.** `from data.loader import load_data`
   (`planning.py:14`) is imported but never called anywhere in the file —
   all data access goes through `data.loader.engine` and raw SQL against
   `agg_*` tables instead (the correct pattern per house convention; the
   import itself is just dead weight).

10. **Hardcoded, incomplete BA directory.** `STORY_OWNER_MAP`
    (`planning.py:86-90`) hardcodes exactly two BAs — `"Geetika"` →
    Geetika Khanna, `"Chhavi"` → Chhavi Bhardwaj — keyed on the ADO field
    `Custom.Userstoryowner`'s short-name value. Any other value (a new BA,
    a typo, a departed BA) falls through to `BA_DEFAULT` ("Unassigned",
    "SO-00"), silently miscategorizing that story's owner rather than
    erroring.

11. **Developer filter chips are capped at 20.** `dev_first_names =
    sorted({...})[:20]` (`planning.py:2875`) — the BA-filter side panel's
    developer chip strip only ever shows the first 20 developer first
    names alphabetically; any developer whose name sorts after the 20th
    gets no filter chip (their stories are still visible in the
    unfiltered table/matrix views, just not filterable by that chip UI).

12. **Independent, hand-rolled caches.** `_planning_cache`, `_bug_cache`
    (both 5-minute TTL, `planning.py:126-129`) and `_GANTT_CACHE`
    (5-minute TTL, `planning.py:23-24`) are three more module-level dict
    caches layered on top of — and managed completely independently from
    — `data/loader.py`'s own 15-minute DataFrame cache, consistent with
    there being no single caching story across the app (see `db.md` §6).
