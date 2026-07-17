# Database Layer

Single Postgres database, `vsts_analytics`, `localhost:5432`. No migration tool
(Alembic etc.) is used anywhere — every table is created via idempotent
`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
statements run from Python at startup or on first use. See §7 for what that
costs.

Connection is built in two independent places with the same recipe
(`postgresql+psycopg2://postgres:<pass>@localhost:5432/vsts_analytics`):
`data/loader.py` (`engine`, pool_size=10) and `sync/ado_sync.py` (its own
`_get_engine()`, pool_size=5). Almost everything imports `data.loader.engine`;
the sync module keeps a separate one because it needs to run standalone
(e.g. from a scheduler thread) without pulling in the whole loader module.

There are three distinct table families, with different owners and lifecycles.

## 1. The ADO mirror — `work_items_main` + friends

`work_items_main`, `work_items_relations`, and `item_state_history` hold the
local copy of Azure DevOps work items (User Story, Bug, Bug_UI, Bug_Text, Task,
Enhancement). They are the input to almost every dashboard page.

**`work_items_main`** — one row per ADO work item. Inferred columns (from
`sync/ado_sync.py`'s `_transform()` and `data/loader.py`'s `_COLUMNS`):
`work_item_id` (PK, unique), `title`, `assigned_to`, `state`, `work_item_type`,
`priority`, `severity`, `original_estimate`, `completed_work`,
`remaining_work`, `function`, `iteration_path`, `main_developer`,
`main_designer`, `created_date`, `closed_date`, `changed_date`, `release_date`,
`area`, `tags`, `type`, `stage`, `story_owner`, `parent_id`, `activity`,
`activated_date`, `story_size`, `story_status`. Written exclusively by
`sync/ado_sync.py::_upsert()` — delete-then-insert per synced batch, inside one
transaction, keyed on `work_item_id`.

**`work_items_relations`** — link-type relations between work items (used by
`data/loader.py::_load_rel_map()` to patch `parent_id` for Tasks linked via
`System.LinkTypes.Related` instead of a formal parent/child link — some Tasks
are only ever linked "Related" in ADO, and the dashboards need a `parent_id`
to roll them up).

**`item_state_history`** — one row per (work_item_id, revision) state
transition, populated by `sync/ado_sync.py::_sync_state_history()` from ADO's
update-revision API. Throttled to ~90 req/min; incremental syncs cap this to
the first 150 changed items per cycle (full syncs process everything). Used
for sprint-history backfill (§3) and quality-audit pages.

**None of these three tables have a `CREATE TABLE` anywhere in this
repository.** See §4.

## 2. Platform-native tables — `p_*`

Entities the in-house planning layer owns that ADO doesn't model well, or that
should never round-trip through a full ADO resync (which deletes and
reinserts every row of `work_items_main`). Defined across two places:

- **`db/schema.sql`** — run exactly once, by hand, via `python
  db/init_platform.py` (§5). Defines the original shape of `p_ref_counters`,
  `p_users`, `p_epics`, `p_releases`, `p_features`, `p_bugs`, `p_audit_log`,
  `p_tasks`, `p_iteration_capacity`, `p_planning_gates`, `p_planning_log`.
- **Per-module `init_*_tables()` functions**, each called from `app.py`'s
  `__main__` block on every process start (wrapped in its own try/except so
  one failing doesn't block the others):

  | Module | Tables | Purpose |
  |---|---|---|
  | `db/planning.py` | `p_planning_gates`, `p_planning_log`, `p_tracker_steps`, `p_tracker_log` | BA/PO sign-off gates per work item (now 12 boolean gates, not the 3 in `schema.sql` — see §4) + full product-lifecycle step tracker (6 gates → 14 phases → 70 steps, from `config/lifecycle.py`) |
  | `db/standalone.py` | `standalone_task_classifications` | Rules+Ollama category per unparented Task (see `sync.md` §4) |
  | `db/focus.py` | `p_sprint_item_history` | When each item entered each sprint iteration — backfilled from `created_date`/`item_state_history`, not from a live ADO call |
  | `db/leaves.py` | `p_company_holidays`, `p_dev_leaves` | Company holidays + individual leave days, feeds capacity math |
  | `db/admin_hours.py` | `p_admin_hours`, `p_admin_sprint_config` | Per-developer non-project overhead hours per sprint, and per-sprint capacity override |
  | `db/report_requests.py` | `report_requests` | Queue for the LLM-driven custom-report pipeline (`agents/pipeline.py`, see `reports.md`) |
  | `db/aggregations.py` | `agg_*` (see §3) | Precomputed rollups |
  | `db/issue_planning.py` | `issue_caps`, `issue_dev_config` | Per-priority bug intake caps + per-developer P1-eligibility/ordering config for Issue Planning |
  | `pages_dash/misc/release_status.py` | `p_release_rows`, `p_release_stages` | Per-story release pipeline stage tracking (created inline in the page module, not in `db/`) |

`p_bugs` also gets written by the *sync* engine, not just the platform UI —
see `sync.md` §5 (production-bug promotion from `work_items_main`).

## 3. Aggregate tables — `agg_*`

Defined and created in `db/aggregations.py::init_aggregation_tables()`, but
populated exclusively by `sync/aggregator.py::run_aggregations()`, which runs
as the last step of every `run_sync()` cycle (see `sync.md` §3). The intent,
per the module docstring, is **zero runtime computation on read** — every page
that used to do a groupby/CTE over `work_items_main` at render time should
instead read one of these:

| Table | Rebuilt for |
|---|---|
| `agg_item_month_keys` | Parses `iteration_path` → month number/label/key once, so every other aggregate can join on it cheaply |
| `agg_gantt_items` | Delivery Timeline / Gantt rows — one row per active 2026 Enhancement/Bug, with resolved bar start/end and % complete |
| `agg_gantt_tasks` | Task sub-rows for the Gantt's collapsible expand, keyed by `parent_id` |
| `agg_story_estimation` | Estimation status per 2026 Enhancement **and Bug type** (`estimated` / `estimated_via_tasks` / `partial` / `unestimated`) — despite the name, `sync/aggregator.py`'s item-type filter includes Bug/Bug_UI/Bug_Text alongside Enhancement, backing both `/unestimated` and `/bugs-unestimated` |
| `agg_dev_monthly_capacity` | Developer × month × item-type counts/hours for the capacity grid |
| `agg_sprint_daily_activity` | Daily added/closed counts for the sprint activity chart |
| `agg_standalone_overhead` | Standalone-task hours by developer/month/category, from `standalone_task_classifications` |
| `agg_qa_rework` | (created ad hoc inside `sync/aggregator.py`, not in `db/aggregations.py` — see `sync.md`) |

## 4. Schema drift — `schema.sql` is not the source of truth

`db/schema.sql` is only ever executed once, by hand, via `db/init_platform.py`
(§5) — it is **not** re-run on app startup. Every table it defines has since
been altered by its owning module's `init_*_tables()` function, which *is* run
on every startup. The two can and do disagree:

- `schema.sql`'s `p_planning_gates` has 3 boolean columns (`written`,
  `ac_locked`, `estimated`). The live table — per `db/planning.py`'s
  `_MIGRATE_GATES` list, applied every startup — actually has **12**:
  `dor`, `story_written`, `estimation`, `in_dev`, `in_qa`, `ready_to_ship`,
  `delivery`, `claude_screens`, `text_written`, `our_screens`,
  `html_screens`, `sn_signoff`. Reading `schema.sql` alone gives you the
  wrong mental model of this table.
- `p_bugs.ado_id` gets its `UNIQUE` index added lazily inside
  `sync/ado_sync.py::_sync_production_bugs()` (`ALTER TABLE ... ADD COLUMN IF
  NOT EXISTS`), not in `schema.sql` or `db/aggregations.py`.

**Practical rule**: to know a `p_*` table's actual current shape, read the
owning module in `db/` (or `pages_dash/misc/release_status.py` for
`p_release_rows`/`p_release_stages`), not `db/schema.sql`. Treat `schema.sql`
as "what the table looked like the day it was first created," nothing more.

## 5. Bootstrap — `db/init_platform.py`

One-time, manual: `python db/init_platform.py`. Executes `schema.sql`
statement-by-statement (split on `;` — fragile if any DDL ever needs an
embedded semicolon, e.g. inside a function body) and seeds a single admin user:

```python
ADMIN_USER = {
    "username": "mayank", "password": "admin123", "role": "admin", ...
}
```

The password is hardcoded, printed to stdout on creation
(`Default password: admin123`), and — since the seed is `INSERT ... skip if
exists` — will silently never rotate on subsequent runs. If this script is
ever re-run against a fresh DB without someone manually changing that
password immediately after, `mayank`/`admin123` is a standing admin credential.

## 6. Caching layer on top

`data/loader.py::load_data()` is the read path almost every page goes through:
one process-wide pandas DataFrame, refreshed from `work_items_main` (filtered
to activity since 2025-01-01) with a 15-minute TTL matching the sync interval.
A second cache (`_REL_MAP_CACHE`, 30-min TTL) holds the Related-link parent
map. Both are plain module globals — **not** safe across multiple app
processes (e.g. behind a multi-worker WSGI setup); each worker would rebuild
its own copy independently. Currently fine since the app runs as a single
Waitress process with `threads=8`, not multiple processes.

`bust_loader_cache()` / `bust_ui_cache()` invalidate these on demand — called
after syncs and after local writes that should show up immediately.

## 7. Known issues

- **No versioned DDL for the most important tables.** `work_items_main`,
  `work_items_relations`, and `item_state_history` — the tables literally
  everything else reads from — have no `CREATE TABLE` anywhere in source
  control. If the Postgres instance were lost, there is no way to rebuild
  the schema from this repo; someone would have to reverse-engineer it from
  `_transform()`'s output columns and hope nothing else depended on a column
  that isn't inserted (e.g. anything referenced only by raw SQL elsewhere).
- **`schema.sql` is stale and can actively mislead** (§4) — it's read once at
  bootstrap and never again, while the real schema is defined by ~9 different
  Python modules each doing their own `ALTER TABLE ADD COLUMN IF NOT EXISTS`.
  There's no single file you can open to see "the current schema."
- **No migration history.** Every schema change is an `IF NOT EXISTS` /
  `ADD COLUMN IF NOT EXISTS` guard baked directly into application code —
  there's no record of *when* a column was added, why, or what to do if a
  column needs to be renamed or dropped (this pattern can only add, never
  safely remove).
- **Hardcoded default admin credential** (`mayank` / `admin123`), printed to
  stdout, in a script that's safe to accidentally re-run.
- **Delete-then-insert upsert on `work_items_main`** is transactional but
  means a crash mid-sync (after delete, before insert completes) drops rows
  for that batch until the next sync run succeeds.
- **Fragile SQL-splitting** in `db/init_platform.py` (`sql.split(";")`) would
  break silently if `schema.sql` ever needed a semicolon inside a statement
  body (e.g. a trigger function) — not an issue today since there's no such
  statement, but worth knowing before adding one.
