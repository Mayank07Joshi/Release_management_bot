# Master Reference — Release Analytics / EOD Planning Platform

This is the entry point to the internal documentation set for this repo. Read this
file first — it defines the system at a glance, the conventions every module and
page follows (or is supposed to), and links out to the detailed docs.

> **Wiki index**
> - [`db.md`](db.md) — database layer: table families, sync, aggregation
> - [`sync.md`](sync.md) — ADO sync engine, write-back, aggregator, task classifier
> - [`auth.md`](auth.md) — login, sessions, roles/permissions
> - [`reports.md`](reports.md) — PPT/Word generation, recommendation engine, LLM report pipeline
> - `pages/*.md` — one file per dashboard page (route, purpose, data, callbacks, known issues)

---

## 1. What this system is

A Dash/Flask web app ("Release Analytics", branded internally as "EOD · PLANNING")
that does two jobs at once:

1. **Mirrors Azure DevOps (ADO)** work items (User Story / Bug / Bug_UI / Bug_Text /
   Task / Enhancement) into Postgres, then renders ~20 analytics dashboards on top
   (estimation status, delivery timelines, team capacity, bug tracking, sprint
   activity, etc.) for the ExpenseOnDemand product team.
2. **Runs a lightweight in-house PM layer** (Epics/Releases/Features/Bugs/Tasks in
   `p_*` tables) that ADO doesn't natively support well — capacity planning,
   BA/PO sign-off gates, leave management — and can create/link/write back to ADO
   work items when needed.

Primary consumers: PMs, BAs, QA leads, and engineering managers who need a single
place to see estimation gaps, delivery risk, and team load without living inside
ADO's own UI.

## 2. Architecture at a glance

```
Azure DevOps (ADO)
      │  WIQL query + REST PATCH
      ▼
sync/ado_sync.py  ──────────────► Postgres: work_items_main, work_items_relations,
      │  (every 15 min + full        item_state_history   (ADO mirror — see db.md)
      │   resync 00:00/06:00/16:00)
      ▼
sync/aggregator.py ─────────────► Postgres: agg_* tables (precomputed rollups,
      │                                       zero runtime computation on read)
      ▼
data/loader.py  ── 15-min in-process DataFrame cache ──► pages_dash/*.py (Dash pages)
      ▲                                                          │
      │                                                          │ user edits
      └─────────────── sync/ado_write.py (fire-and-forget PATCH) ┘
                              │
                              ▼
                        Azure DevOps (write-back)

p_* tables (platform-native: epics, releases, features, bugs, tasks,
capacity config, planning gates, leaves, admin hours) sit alongside
work_items_main and are never touched by an ADO sync — see db.md §2.
```

Entry point is `app.py`: builds the Dash app, sidebar nav, auth gate, sync
scheduler (APScheduler), and background cache warm-up on startup.

## 3. Tech stack

| Layer | Choice |
|---|---|
| Web framework | Dash 4 (Flask under the hood) + `dash-bootstrap-components` |
| Server | Flask dev server (debug) locally, Waitress when `PRODUCTION=true` |
| DB | PostgreSQL (`vsts_analytics`), accessed via SQLAlchemy Core (`text()` queries) + pandas `read_sql`/`to_sql` |
| ADO integration | `azure-devops` SDK (read) + raw `requests` PATCH calls (write) |
| Auth | Flask-Login, `p_users` table, `werkzeug.security` password hashing |
| Scheduling | APScheduler `BackgroundScheduler` (in-process, not a separate worker) |
| Charts | Plotly (custom `midnight` dark template registered in `app.py`) |
| LLM (optional) | Ollama, local models (`llama3.2:3b`, `deepseek-r1:7b`) for task classification and the report-request pipeline |
| Reports | `python-pptx`, `python-docx`, `xlsxwriter` |

## 4. Repo layout

| Path | Purpose |
|---|---|
| `app.py` | Dash app entry point, sidebar nav, sync scheduler, top-level callbacks |
| `pages_dash/` | One file per route, grouped by nav section (`trends/`, `enhancements/`, `bugs/`, `capacity/`, `misc/`) — see `pages/*.md` |
| `sync/` | ADO ⇄ Postgres sync engine, write-back, aggregation, task classification — see `sync.md` |
| `db/` | DDL + query helpers for the platform-native (`p_*`) and aggregate (`agg_*`) tables — see `db.md` |
| `data/` | `loader.py` (the DataFrame cache + query layer everything reads through), `ado_api.py` |
| `auth/` | Flask-Login wiring, `User` model, role permissions, `/login`/`/logout` routes — see `auth.md` |
| `config/` | Static config: team/staff directories, dashboard settings, product lifecycle checklist |
| `reports/` | Report generation (PPT/Word/HTML) and the recommendation engine — see `reports.md` |
| `agents/` | `pipeline.py` — local-LLM multi-agent pipeline behind the Reports page's "custom analysis request" feature |
| `components/` | Small shared chart/table builders (e.g. `matrix.py`) |
| `scripts/` | One-off/maintenance scripts (test-case uploads, PPT generation, KPI validation, sync validation) |
| `docs/` | This wiki, plus product briefs/PRDs and generated presentations |
| `tests/` | ADO upload scripts and perf probes — **not** an automated test suite (see §7) |

## 5. Page map (nav → route → file)

Sidebar nav is defined in `app.py` (`_NAV_TREE`). "Built" reflects the amber-dot
flag in that list at the time this doc was written — cross-check against the app
if it matters, since flags can go stale (see §7).

| Section | Label | Route | File | Nav "built"? |
|---|---|---|---|---|
| — | Home | `/` | `pages_dash/home.py` | (not in nav; default landing page) |
| — | Overview | `/overview` | `pages_dash/trends/overview.py` | ✅ |
| TRENDS | Addition & Deletion | `/addition-deletion` | `pages_dash/trends/addition_deletion.py` | ✅ |
| ENHANCEMENTS | Estimation Status | `/unestimated` | `pages_dash/enhancements/unestimated.py` | ✅ |
| ENHANCEMENTS | Story Readiness | `/planning` | `pages_dash/enhancements/planning.py` | ✅ |
| ENHANCEMENTS | Delivery Timeline | `/delivery-timeline` | `pages_dash/enhancements/delivery_timeline.py` | ✅ |
| ENHANCEMENTS | Designer Planning | `/designer-planning` | `pages_dash/enhancements/designer_planning.py` | ⚠ flagged placeholder in nav |
| ENHANCEMENTS | Release Status | `/release-status` | `pages_dash/misc/release_status.py` | ⚠ flagged placeholder in nav |
| BUGS & ISSUES | Estimation Status | `/bugs-unestimated` | `pages_dash/bugs/bugs_unestimated.py` | ✅ |
| BUGS & ISSUES | Issue Planning | `/issue-planning` | `pages_dash/bugs/issue_planning.py` | ✅ |
| CAPACITY | Team Pulse | `/team-pulse` | `pages_dash/capacity/team_pulse.py` | ✅ |
| CAPACITY | Developer Capacity | `/dev-capacity` | `pages_dash/enhancements/capacity_planner.py` | ✅ |
| CAPACITY | Leave Management | `/leave-management` | `pages_dash/capacity/leave_management.py` | ✅ |
| CAPACITY | Admin Hours | `/admin-hours` | `pages_dash/capacity/admin_hours.py` | ⚠ flagged placeholder in nav |
| REFERENCE | VSTS Focus Area | `/summary` | `pages_dash/trends/summary.py` (renders shared `trends/focus.py`) | ✅ |
| REFERENCE | BA Team Brief | `/ba-brief` | `pages_dash/misc/ba_brief.py` | ⚠ flagged placeholder in nav |
| *(not in sidebar)* | Iteration Audit | `/iteration-audit` | `pages_dash/misc/iteration_audit.py` | orphan route — no nav link |
| *(not in sidebar)* | Reports | `/reports` | `pages_dash/misc/reports.py` | orphan route — no nav link |

Several routes flagged "placeholder" in the nav (`designer-planning`, `release-status`,
`admin-hours`, `ba-brief`) back onto files with real, substantial implementations
(1000+ lines in some cases) — the amber dot may just mean "not yet signed off for
general use" rather than "unbuilt." Verify against current app state before trusting
the flag either way.

## 6. Conventions & standards (apply these everywhere)

These are the patterns the codebase already follows in most places. Follow them
in new code; if you're refactoring old code, converging on these is the direction,
not away from it.

- **DB access**: always through SQLAlchemy's `engine` from `data/loader.py` (or a
  module-local engine built the same way) with `text()` for raw SQL. Don't open ad
  hoc `psycopg2.connect()` calls except the documented `get_db_connection()`
  fallback in `loader.py`.
- **Field routing rule**: if a field exists on the ADO work item, it belongs in
  `work_items_main` and flows through `sync/ado_sync.py` (read) and
  `sync/ado_write.py` (write) — never invent a shadow copy in a `p_*` table.
  If a field is app-only (capacity config, sign-off gates, leave records), it
  belongs in a `p_*` table and must **never** be written into `work_items_main`,
  since a full resync deletes and reinserts every row there.
- **Task-based hours**: Team Pulse and Developer Capacity compute hours/counts
  from **task assignments**, not from a story's `main_developer`. "Dev Complete"
  counts as active work; "Standalone" means `parent_id IS NULL` only — don't
  infer standalone status any other way.
- **Page file shape**: one file per route, `dash.register_page(__name__, path=...,
  name=...)` near the top, module-level style constants (`_TX`/`_MT`/`_BD` or
  `TXT`/`MT`/`BD` for text/muted-text/border) referencing CSS variables
  (`var(--text-primary)`, `var(--bg-elevated)`, etc.) so pages respect the
  light/dark theme toggle. Avoid importing one page module from another at
  top level purely for layout reuse — Dash double-registers callbacks when you
  do (`unestimated.py`/`bugs_unestimated.py` intentionally duplicate small style
  blocks instead, per their own comments).
- **Shared tab content**: when two routes render the same underlying view (e.g.
  `/summary` and `/addition-deletion` both call `focus_tab_content()` from
  `trends/focus.py`), put the shared logic in a plain function in one module and
  import *that function*, not the whole page module.
- **Caching**: `data/loader.py` holds one process-wide DataFrame with a 15-minute
  TTL (matches the ADO sync interval). Call `bust_loader_cache()` after any write
  that should be visible immediately; call `bust_ui_cache()` if a page also caches
  rendered HTML/components. Aggregate (`agg_*`) tables are rebuilt by
  `sync/aggregator.py` after every sync — pages should read them directly rather
  than recomputing rollups at render time.
- **Write-back**: UI-triggered edits update the local Postgres row first, then
  call `sync.ado_write.write_fields()` (fire-and-forget) so the page never blocks
  on ADO's API. Use `write_fields_sync()` only when the caller genuinely needs to
  confirm success before proceeding (e.g. creating a new linked work item).
- **Error handling**: optional/non-critical steps (table init, history sync,
  classifier runs) are wrapped in `try/except` and logged as `warning`, not
  raised — a failure in one sync sub-step must not abort the whole sync cycle.
  Follow this pattern for new sync sub-steps; don't let one growing failure mode
  take down the whole `run_sync()` call.
- **Auth/permissions**: roles are plain strings (`admin`, `pm`, `developer`, `qa`,
  `designer`, `viewer`) checked via `current_user.can("action_name")` against the
  `ROLE_PERMISSIONS` dict in `auth/models.py`. Add new actions there, not as
  scattered `if current_user.role == "admin"` checks in page code.
- **Logging**: `log = logging.getLogger(__name__)` per module, configured once in
  `app.py`. Don't use bare `print()` for anything beyond quick local debugging
  (several existing `print()` calls in the loader/page modules are legacy —
  don't copy that pattern forward).

### Documentation template (for every file in `pages/*.md`, and module docs)

```markdown
# <Page/Module name>

- **Route / entry point**: ...
- **Backing file(s)**: ...
- **Nav location**: ... (or "not in nav")

## What it does
(functional description, from a user's point of view)

## Why it exists
(the business/process reason — what decision or workflow this supports)

## How it works
(data sources / tables read-written, key callbacks, notable logic,
 cross-references to other pages or modules)

## Known issues / quirks
(anything inline in the code or observed behavior worth flagging —
 leave empty / "None observed" rather than omitting the section)
```

## 7. Cross-cutting known issues

These aren't page-specific — they show up across the whole system and are worth
fixing centrally rather than per-file:

- **`work_items_main`, `work_items_relations`, and `item_state_history` have no
  `CREATE TABLE` anywhere in this repo.** Every other table (`p_*`, `agg_*`) is
  defined in versioned DDL; these three — the core ADO mirror everything else
  depends on — exist only in the live Postgres instance. See `db.md` §4.
- **Three independent hardcoded staff directories that have drifted apart** —
  worse than first scoped. `config/team_mapping.py` (`TEAM_MAPPING`) and
  `config/dev_capacity.py` (`ALL_STAFF`) both hardcode name → team, but list
  *different people* (e.g. `ALL_STAFF` includes "Suraj Gupta", "Nishtha
  Arora", "Sunil Nigam", "Siddharth Nigam", "Sunita Nigam" — none of whom
  appear in `TEAM_MAPPING`). `pages_dash/capacity/team_pulse.py` then builds
  a *third*, page-local roster (`_TEAM_MAP`) containing a name — "Varun T" —
  that exists in **neither** of the other two (see `pages/team-pulse.md`).
  Anything keyed off one but not another will silently miscategorize those
  people. This should be one source of truth, not three.
- **ADO write-back failures are silently swallowed while a success toast
  still fires anyway** — a pattern seen independently on at least two pages
  (`bugs/issue_planning.py` and `capacity/team_pulse.py`, both wrap the write
  call in a bare `except Exception: pass`). Since `sync/ado_write.py` already
  provides a proper failure queue (`get_pending_failures()`) that `app.py`
  polls for toasts, these pages are bypassing it rather than using it — the
  user sees "✓ ADO synced" even when the write never reached ADO. Worth an
  audit across all write-capable pages, not just the two found so far.
- **Security defaults are unsafe out of the box**: `app.py`'s `SECRET_KEY` and
  `data/loader.py`/`sync/ado_sync.py`'s `DB_PASSWORD` both fall back to hardcoded
  values (`"dev-secret-change-in-prod-!@#$%"`, `"1234"`) if missing from `.env`;
  `SECRET_KEY` is in fact **not** set in the current `.env`. Default run mode
  (`PRODUCTION` unset) launches Flask with `debug=True` on `0.0.0.0`. See
  `auth.md` §5.
- **No automated test suite.** `tests/` holds ADO upload scripts and perf probes,
  not unit/integration tests — nothing verifies sync transforms, aggregator SQL,
  or the write-back field map (which includes an intentional-typo field,
  `Custom.MainDevevloper`, that's easy to "fix" by accident).
- **Monolithic page files**: several pages exceed 1,500–5,500 lines mixing
  layout, callbacks, and SQL in one file (`enhancements/planning.py` is the
  extreme case at ~5,500 lines). New work in these files should extract shared
  pieces rather than add another few hundred lines inline.
- **Nav "placeholder" flags may be stale** — see §5. Don't take the amber dot as
  proof a page is unbuilt without checking the file. The reverse also
  happens: `ba-brief.md` documents a route flagged placeholder that really is
  an empty stub, right next to `release-status.md`'s ~1,100-line fully
  working page carrying the identical flag — the flag doesn't distinguish
  the two cases at all.
- **The recommendation engine is logic-complete but UI-orphaned.** Prior
  team notes mark this project "COMPLETE" (logic + display + wiring across
  5 boards). The logic (`reports/recommendations.py`) and display
  (`reports/rec_display.py`) are real and match that plan closely — but the
  wiring step never happened against this codebase: no page under
  `pages_dash/` imports either module, and the board files the old plan
  names don't correspond to any file that exists today. A second,
  independent, equally-unwired implementation of the same idea
  (`reports/summarizer.py` + `reports/formatter.py`) also exists, with its
  own separate thresholds. See `reports.md` §1–2 for the full picture before
  assuming this feature is live anywhere.
- **`enhancements/planning.py` has four fully-built major sections that are
  permanently unreachable.** The page renders five tab sections
  (Unestimated Items, Developer Capacity, Delivery Timeline/Gantt, BA Team
  Brief, Story Readiness), but the tab-button row only renders a button for
  "Story Readiness" — the other four have live callbacks and pay their full
  data-load cost on every page visit with no way for a user to ever see
  them. See `pages/planning.md` §6.

See `db.md`, `sync.md`, `auth.md`, and `reports.md` for the detail behind each of these.
