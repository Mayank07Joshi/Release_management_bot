# Admin Hours

- **Route / entry point**: `/admin-hours` (`pages_dash/capacity/admin_hours.py:16`, `dash.register_page`)
- **Backing file(s)**: `db/admin_hours.py` (`p_admin_hours`, `p_admin_sprint_config`); also reads `db/leaves.py`'s `get_leave_capacity()`
- **Nav location**: CAPACITY → "Admin Hours" (`app.py:118`, built flag `False` — see Known issues)

## What it does

A per-developer, per-sprint overhead-tracking grid. For each tracked person it
shows one editable row with number inputs across seven categories —
**Meetings, Ceremonies, Support, Code Review, Interviews, Training, Other**
(`admin_hours.py:47-55`) — plus three read-only computed columns: **Leave H**
(pulled from Leave Management), **Admin H** (sum of the seven inputs), **% Cap**,
and **For Stories** (`capacity_h − admin_h − leave_h`, per the module
docstring at `admin_hours.py:1-4` and implemented at `admin_hours.py:181`).
Every cell edit saves immediately on blur/Enter (`debounce=True`) and
recomputes that row's derived columns plus four team-level KPI cards
(Team Admin Hours, Avg Per Person, % of Capacity, Available for Stories)
without a full page reload. A sprint dropdown (actually a calendar month,
formatted `"%b-%y"`, e.g. `Jul-26`) switches which sprint's data is shown, and
a single "Capacity per person" input overrides the per-sprint capacity used in
every row's math.

## Why it exists

Developer Capacity and Team Pulse compute available story-delivery hours from
task assignments, but neither accounts for time that never shows up as an ADO
task at all — meetings, ceremonies, interviews, training, etc. This page is
where that overhead gets logged per person per sprint so the "hours actually
available for stories" figure factors it in, alongside leave (pulled live from
Leave Management) and a configurable per-sprint base capacity.

## How it works

- **Staff source**: imports `DEVELOPERS`, `STAFF_MAP`, `DEFAULT_CAPACITY_H`
  from `config/dev_capacity.py` (`admin_hours.py:9`). In that module,
  `ALL_STAFF` is the master list of 29 staff records (`name`, `role`, `team`,
  `capacity_h`); `DEVELOPERS` is the subset filtered to
  `team in ("Development", "Mobile")` (`config/dev_capacity.py:44`, 13
  people); `STAFF_MAP` is a `name → record` dict over *all* of `ALL_STAFF`
  (`config/dev_capacity.py:49`); `DEFAULT_CAPACITY_H` is a standalone constant
  (`180`, `config/dev_capacity.py:58`) — not derived from any individual
  staff record's own `capacity_h` field (which also happens to be `180` for
  every entry today, but the two numbers are unrelated in code).
- **Roster shown on this page**: `_PLAN_DEVS = DEVELOPERS + [STAFF_MAP["Chhavi Bhardwaj"], STAFF_MAP["Geetika Khanna"]]`
  (`admin_hours.py:40-43`) — the 13 Development/Mobile devs plus two
  hand-picked QA/Management staff, re-labeled "Story Owner" via `_ROLE_LABEL`
  (`admin_hours.py:33-38`, which maps team `"QA"` and `"Management"` both to
  that display label). No other QA, Design/Video, or Management staff from
  `ALL_STAFF` (e.g. `Satyarth Singh`, `Furquan Nayyar`, `Sunil Nigam`) appear
  on this page at all.
- **DB access** — confirmed imports at `admin_hours.py:10-14`:
  - `db.admin_hours.get_admin_hours(sprint_key)` / `upsert_admin_row(...)` —
    read/write `p_admin_hours` (one row per developer × sprint, the seven
    overhead columns).
  - `db.admin_hours.get_sprint_capacity(sprint_key)` / `set_sprint_capacity(...)`
    — read/write `p_admin_sprint_config` (one row per sprint, single
    `capacity_h` shared by every developer that sprint — there is no
    per-person override even though `ALL_STAFF` models a per-person
    `capacity_h`).
  - `db.leaves.get_leave_capacity([ym])` — read-only, converts the sprint key
    to a `YYYY-MM` string (`_sprint_to_ym()`, `admin_hours.py:75-76`) and sums
    `p_dev_leaves` + `p_company_holidays` for that month per developer
    (`_load_leave_hours()`, `admin_hours.py:79-88`).
- **`init_admin_hours_tables()`** is called once from `app.py`'s startup block
  (`app.py:563-567`, same try/except-and-log pattern as every other `p_*`
  table init) — never called from the page module itself.
- **Callbacks**: sprint dropdown → `ah-sprint` store → full table + KPI
  reload (`_load_sprint`, `admin_hours.py:406-423`); capacity input → saves
  via `set_sprint_capacity()` and recomputes everything for the current sprint
  (`_update_capacity`, `admin_hours.py:427-449`); any of the pattern-matched
  `{"type": "ah-cell", "dev": ALL, "col": ALL}` number inputs → saves just the
  changed developer's row via `upsert_admin_row()` and recomputes only that
  row's three derived spans plus the four KPIs, without re-rendering the whole
  table (`_save_and_recompute`, `admin_hours.py:453-530`).
- No `bust_ui_cache()` / `bust_loader_cache()` calls anywhere in this file —
  every callback above reloads its own data straight from Postgres on the
  next trigger, so there's no cache to invalidate.

## Known issues / quirks

- **Nav "placeholder" flag looks stale.** `app.py:118` flags `/admin-hours`
  as not built (`False`), but the file is a fully wired ~550-line CRUD page:
  persistent per-cell editing with debounced saves, a working sprint
  selector, a capacity override that persists, and four live-recomputed KPI
  cards — not a stub or "coming soon" page. This matches the pattern
  master.md §5/§7 already calls out for `designer-planning`,
  `release-status`, and `ba-brief`: the amber dot most likely means "not yet
  signed off for general rollout" rather than "unbuilt," and should not be
  trusted as a proxy for how complete the page actually is.
- **Leave hours will read as zero for the two non-Development/Mobile staff on
  this page.** `Chhavi Bhardwaj` and `Geetika Khanna` are in `_PLAN_DEVS` here
  and their leave hours are looked up via `get_leave_capacity()`
  (`admin_hours.py:79-88`), but Leave Management's developer dropdown only
  offers `DEVELOPERS` (Development/Mobile team) — see
  `docs/wiki/pages/leave-management.md` — so there is currently no UI path to
  ever record a leave day for either of them. Their "LEAVE H" column here
  will always show "—"/0 regardless of actual leave taken.
- **Two-directory staff drift is directly relevant here.** Per master.md §7,
  `config/team_mapping.py` (`TEAM_MAPPING`) and `config/dev_capacity.py`
  (`ALL_STAFF`) list different people. This page reads `ALL_STAFF` exclusively
  (via `DEVELOPERS`/`STAFF_MAP`), so anyone present in `TEAM_MAPPING` but
  missing from `ALL_STAFF` (or vice versa) would silently never appear on
  this page no matter what team they're actually on — there's no error, just
  a missing row.
- **Manual two-person whitelist is brittle.** Extending "Story Owner" tracking
  to a third QA/Management person requires editing the hardcoded list at
  `admin_hours.py:40-43` — there's no config-driven way to say "also include
  this person" without a code change.
- **"Sprint" is actually a calendar month.** `_current_sprint()`
  (`admin_hours.py:59-60`) and `_sprint_options()` both operate in
  `"%b-%y"` month buckets, and `_sprint_to_ym()` maps that straight to a
  `YYYY-MM` string for the leave-capacity lookup — there's no relationship to
  ADO iteration/sprint paths (`work_items_main.iteration_path`) anywhere in
  this file. The UI label "sprint" is really "month" throughout.
- **Duplicate hardcoded default capacity.** `DEFAULT_CAPACITY_H = 180` in
  `config/dev_capacity.py:58` and the literal fallback `180.0` in
  `db/admin_hours.py:90` (`get_sprint_capacity`'s `if not row` branch) encode
  the same default in two places; `DEFAULT_CAPACITY_H` is only actually
  referenced once in `admin_hours.py` (line 472, inside
  `_save_and_recompute`'s fallback), not used by `get_sprint_capacity`
  itself — if the org-wide default sprint capacity ever changes, both
  constants need updating by hand.
- **`_load_leave_hours()` swallows all exceptions and returns all-zero leave
  hours** (`admin_hours.py:87-88`, bare `except Exception`) — a real DB
  failure looks identical to "nobody took leave this sprint," which could
  mask a genuine capacity miscalculation.
