# Sync Engine

The `sync/` package is the only path in or out of Azure DevOps. Four modules,
each with a single job: `ado_sync.py` pulls ADO work items into
`work_items_main` (+ history/bug side tables) and kicks off everything
downstream; `ado_write.py` pushes local edits back to ADO; `aggregator.py`
turns the raw mirror into the precomputed `agg_*` tables every page actually
reads (see `db.md` §3); `task_classifier.py` runs a rules+LLM pass over
unparented Tasks to bucket them into overhead categories. All four are wired
together at the bottom of `ado_sync.py::run_sync()`, which is the function
the scheduler and the manual "Sync" buttons in `app.py` actually call.

See `master.md` §6 for the conventions this module follows (field-routing
rule, task-based-hours rule, error-handling pattern) and `db.md` §1–§3 for the
table shapes these modules read and write.

## 1. `ado_sync.py` — the sync cycle

**Trigger points** (all defined in `app.py`, not in this module — `ado_sync.py`
only exposes `run_sync()`):

- `app.py:588` — APScheduler `BackgroundScheduler` job `ado_sync`, interval
  15 minutes, incremental (`run_sync()` / `full=False`).
- `app.py:590-604` — three `cron` jobs, `ado_sync_full_am`/`_full`/`_pm`, at
  00:00, 06:00, and 16:00, each calling `run_sync(full=True)`.
- `app.py:608` — a one-off incremental sync fired in a background thread at
  process startup (`threading.Thread(target=run_sync, ...)`), so the cache
  isn't stale while waiting for the first 15-minute tick.
- Manual buttons: `sync-now-btn` and `fullsync-now-btn` in `app.py` (around
  line 219/227), wired to `_do_sync()` / `_do_full_sync()` (`app.py:17-33`),
  each spawning a `threading.Thread` that calls `run_sync()` /
  `run_sync(full=True)` respectively — same function the scheduler uses, just
  triggered on click instead of on a timer.

**Incremental vs. full** (`ado_sync.py:636-764`): `full=False` computes
`since = _get_last_sync_time(engine)` — `MAX(changed_date)` from
`work_items_main` minus a 1-hour safety buffer, falling back to
2023-01-01 if the table is empty or unreadable (`ado_sync.py:101-118`).
`full=True` always uses 2023-01-01, i.e. re-fetches every in-scope work item.
Typical runtime per the module docstring: 5-30s incremental, 5-10min full.

**Always re-fetch all open tasks** (`ado_sync.py:141-168`, called at
`ado_sync.py:680-682`): on every incremental run, after computing the
changed-since ID list, the sync unions in the IDs of *every open Task created
since 2026-01-01* regardless of `ChangedDate`, then dedupes. This exists
because ADO does not bump `System.ChangedDate` when a work item's
parent-child link is added or removed — a Task re-parented in ADO would
otherwise never show up in an incremental `WHERE ChangedDate >= since` query,
and `parent_id` in `work_items_main` (which many rollups key off of) would
silently drift out of sync. The comment at `ado_sync.py:144-148` calls this
"cheap (bounded set)" — see Known issues for why that bound isn't fixed.

**Column migration guard** (`ado_sync.py:656-668`): before every sync,
`run_sync()` runs five `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
against `work_items_main` (`activity`, `activated_date`, `story_size`,
`story_status`, `story_owner`) — this is the module's share of the
no-migration-tool pattern described in `db.md` §1/§7; failures here are
logged as warnings, not raised.

**Fetch → transform → upsert** (`ado_sync.py:171-269`): `_fetch_details()`
batches ADO's `get_work_items` call 200 IDs at a time (the API limit).
`_transform()` maps the 29 ADO fields in `_FIELDS` (`ado_sync.py:38-69`) onto
the `work_items_main` column names, normalizes priority (`float` → string
int, default `"4"`), and strips timezone info off every datetime column so
Postgres's tz-naive columns don't choke. `_upsert()` (`ado_sync.py:251-269`)
is a delete-then-insert inside one transaction, keyed on `work_item_id` — see
`db.md` §7 for the crash-window caveat that implies.

**Sub-steps run at the end of every sync** (`ado_sync.py:699-742`), each
independently `try/except`-wrapped per the error-handling convention in
`master.md` §6 — one failing must never abort the rest of `run_sync()`:

1. `_sync_sprint_iteration_history()` (`ado_sync.py:310-439`) — backfills
   `p_sprint_item_history` for every 2026 sprint iteration path present in
   `work_items_main` but not yet tracked. Resolution order for "when did this
   item enter this sprint": `created_date` if it falls inside the sprint
   month → most recent `item_state_history` revision inside that iteration
   path → fall back to the sprint's first day (item was carried over from a
   prior sprint). Entirely DB-driven, no per-item ADO calls, and per its own
   docstring runs in under a second regardless of sprint size.
2. `_sync_state_history()` (`ado_sync.py:444-519`) — for each item ID, calls
   ADO's `get_updates()` revision API and persists `System.State` transitions
   into `item_state_history`, throttled to ~90 req/min (`time.sleep(0.67)`
   between items) to stay inside ADO's rate limit. `ON CONFLICT
   (work_item_id, revision) DO NOTHING` makes it idempotent. Incremental runs
   cap this to the **first 150** changed IDs per cycle (`ids[:150]` at
   `ado_sync.py:707`); full runs process every changed item. This is also
   documented in `db.md` §1.
3. `_sync_production_bugs()` (`ado_sync.py:532-629`) — upserts
   Bug/Bug_UI/Bug_Text rows from `work_items_main` into `p_bugs` when
   priority is `'1'` or `tags` contains `production`/`hotfix`/`customer`
   (case-insensitive). Lazily adds `p_bugs.ado_id` and its unique index if
   missing (`ado_sync.py:592-602` — this is the "added inline, not in
   `db/`" case `db.md` §4 calls out), then `ON CONFLICT (ado_id) ... DO
   UPDATE` on title/state/severity/found_in_iteration. This is the one place
   the *sync* engine, not the platform UI, writes into a `p_*` table.
4. Loader cache bust (`_bust_loader_cache()`, `ado_sync.py:272-278` /
   called at line 717) — reaches into `data.loader` and nulls its module
   global `_DATA_CACHE` directly (not via `data.loader.bust_loader_cache()`)
   so the next dashboard read re-queries Postgres.
5. `run_classifier()` from `task_classifier.py` (§4 below), then a prune step
   (`ado_sync.py:725-736`) that deletes any `standalone_task_classifications`
   row whose `task_id` is no longer a Task in `work_items_main` (covers
   Tasks that were deleted, closed-and-purged, or reparented away from
   standalone).
6. `run_aggregations()` from `aggregator.py` (§3 below) — always the last
   step, so every rebuild in this list runs before the read-only `agg_*`
   tables are refreshed.

`run_sync()` returns (and caches in the module-global `_last_sync_result`,
readable via `get_last_sync_result()`) a status dict with `status`,
`timestamp`, `count`, `elapsed_s`, `mode`, or `error` on failure — this is
what the sync-status UI in `app.py` polls.

## 2. `ado_write.py` — write-back to ADO

Every local edit that should round-trip to ADO goes through this module.
Per the write-back convention (`master.md` §6): the page updates the local
Postgres row first, then calls `write_fields()` — never the other order.

**Fire-and-forget vs. sync** (`ado_write.py:177-218`): `write_fields()`
submits the write to a 3-worker `ThreadPoolExecutor` (`_executor`,
`ado_write.py:74`) and returns immediately; the caller never blocks and never
learns whether the ADO PATCH succeeded. `write_fields_sync()` calls the same
patch-building/PATCH logic inline and returns `(ok, error_msg)` — used only
where the caller must confirm success before proceeding, e.g.
`create_work_item()` for a brand-new ADO item.

**`FIELD_MAP`** (`ado_write.py:47-65`) is the only place platform field
names (`main_developer`, `iteration`, `original_estimate`, ...) are mapped to
ADO field paths for writing. It intentionally mirrors the read-side typo:
`"main_developer": "Custom.MainDevevloper"` (`ado_write.py:57`, comment
`# intentional typo — matches ADO field`) — this must match the identical
typo in `ado_sync.py:52`'s `_FIELDS` list, since it's a real ADO custom
field name, not a bug in this codebase. See Known issues.

**Retry/backoff** (`patch_work_item()`, `ado_write.py:94-149`): up to 3
attempts by default, exponential backoff `2.0 ** (attempt-1)` seconds between
tries. 4xx responses return immediately as a permanent failure (bad
request/permissions, retrying won't help); 5xx, timeouts, and network
exceptions retry. `create_work_item()` (`ado_write.py:300-360`) follows the
identical retry shape for item creation.

**Failure/success queues for UI toasts** (`ado_write.py:69-71`,
`189-240`): every background write, success or failure, is appended to one
of two capped `deque`s (`_failures` maxlen 50, `_successes` maxlen 20) guarded
by `_failures_lock`. `get_pending_failures()` / `get_pending_successes()`
drain-and-clear these on read. `app.py`'s `_ado_failure_toast()` callback
(`app.py:308-313`) polls both on an interval and renders whatever it finds as
toasts — this is the only consumer of the queues, and since they're drained
on read, a toast that's missed (e.g. tab closed) is gone for good.

**Creating new ADO items** (`ado_write.py:300-417`): `create_work_item()`
POSTs (as a PATCH to a `$<type>` URL, ADO's creation convention) a new work
item and returns its ID; platform states are translated through `_STATE_MAP`
(`ado_write.py:279-293`) since the in-house Epic/Release/Feature/Bug states
don't line up 1:1 with ADO's. `create_and_link_async()`
(`ado_write.py:363-393`) fires this in the background thread pool and, on
success, calls `_link_ado_id()` (`ado_write.py:396-417`) to write the new
`ado_id` back into the originating `p_features`/`p_bugs`/`p_epics`/`p_tasks`
row — on failure it queues a failure dict with `ado_id: None` instead.

**Convenience wrappers** (`write_state`, `write_assignee`, `write_iteration`,
`write_estimate`, `ado_write.py:245-265`) are thin single-field callers of
`write_fields()`, kept mainly so calling pages don't have to build a dict for
the common one-field case.

## 3. `aggregator.py` — precomputed rollups

Runs as the final step of every `run_sync()` cycle (`ado_sync.py:738-742`),
never on its own schedule and never at page-render time. Per its own
docstring, the goal is **zero runtime computation on read**: every `agg_*`
table it writes is a table pages query directly. See `db.md` §3 for the
full `agg_*` table list and what each backs in the UI; this section covers
how they get built.

`run_aggregations()` (`aggregator.py:706-785`) loads one shared DataFrame
from `work_items_main` (activity since 2025-01-01, `aggregator.py:717-734`),
normalizes types once, then runs each table builder inside its own
`conn.begin_nested()` savepoint so one builder's failure doesn't roll back
the ones that already succeeded or block the ones still to come (still
logged as a `warning`, matching the error-handling convention):

- `_build_item_month_keys` → `agg_item_month_keys` — parses `iteration_path`
  into month number/label/key once via `_ITER_RE` (`Iteration 2026 (\d{2})-(\w+)`)
  so every other builder can join on it cheaply.
- `_build_gantt_items` / `_build_gantt_tasks` → `agg_gantt_items` /
  `agg_gantt_tasks` — Delivery Timeline rows and their Task sub-rows, with
  resolved bar start/end dates and a rollup `%` complete from either summed
  Task hours or the story's own `completed_work`/`remaining_work`.
- `_build_story_estimation` → `agg_story_estimation` — per-Enhancement
  `estimated` / `estimated_via_tasks` / `partial` / `unestimated` status,
  using the "original estimate if set, else Task-derived" logic also used by
  the Estimation Status page.
- `_build_dev_monthly_capacity` → `agg_dev_monthly_capacity` — developer ×
  month × item-type counts/hours, with `capacity_hours = working_days * 9.0`
  (a fixed 9-hour workday assumption baked into the aggregator, not
  configurable per developer).
- `_build_sprint_daily_activity` → `agg_sprint_daily_activity` — daily
  added/closed counts for the current sprint month only; other months' rows
  are preserved (`DELETE ... WHERE ym_str = :ym`, not a `TRUNCATE`).
- `_build_standalone_overhead` → `agg_standalone_overhead` — standalone-task
  hours by developer/month/category, read from
  `standalone_task_classifications` (§4) joined to `work_items_main`.
- `_build_qa_rework` → `agg_qa_rework` — QA-rework cycle counts per story,
  computed straight from `item_state_history` transitions (QA state → dev
  state = a rework). This table is created ad hoc inside `aggregator.py`
  itself (`aggregator.py:652-659`) rather than in `db/aggregations.py` like
  every other `agg_*` table — `db.md` §3 flags this as the one exception.

After all builders run, `run_aggregations()` calls
`data.loader.bust_ui_cache()` (`aggregator.py:780-784`) so any page-level
render cache picks up the new aggregates immediately rather than waiting out
its own TTL.

## 4. `task_classifier.py` — standalone task classification

Classifies parentless (`parent_id IS NULL`) Tasks into one of seven
overhead categories (`CATEGORIES`, `task_classifier.py:22-30`: Meetings &
Calls, Dev Overhead, Research & Spikes, Design & Docs, Testing & QA,
Operations, Other) so Dev Capacity / Team Pulse can report non-project
overhead per developer. Persisted to `standalone_task_classifications`
(owned by `db/standalone.py`, per `db.md` §2) and rolled up into
`agg_standalone_overhead` by the aggregator (§3).

**Scope**: explicitly limited to team members whose `TEAM_MAPPING` team is
`"Development"` or `"Mobile"` (`DEV_TEAMS`, `task_classifier.py:20`,
`187`) — the module's own docstring calls this out as a **"CEO directive —
scale to full team later"** (`task_classifier.py:6`), i.e. a deliberate,
temporary scope limit rather than an oversight.

**Two-stage pipeline** (`run_classifier()`, `task_classifier.py:169-226`):

1. **Rules** (`_classify_rules`, `task_classifier.py:89-98`): lowercase the
   Task title and check it against an ordered list of
   `(category, keyword-list)` pairs (`_KEYWORD_RULES`,
   `task_classifier.py:33-76`) — first match wins, confidence `"high"`. If no
   keyword hits, it falls back to the ADO `Activity` field via
   `_ACTIVITY_FALLBACK` (`task_classifier.py:79-86`, e.g. `"testing"` →
   `"Testing & QA"`), confidence `"medium"`. Only if both miss does the task
   go to stage 2.
2. **Ollama** (`_classify_ollama_batch`, `task_classifier.py:101-154`): every
   task the rules stage couldn't place is sent one-at-a-time to a local
   Ollama server running `llama3.2:3b`, asking for a JSON
   `{"category", "confidence", "reasoning"}` reply. The category is
   validated against `CATEGORIES` and coerced to `"Other"` if the model
   returns anything else; unparseable replies also fall back to `"Other"` /
   `"low"` confidence via `_fallback()` (`task_classifier.py:157-166`).

**Fallback if Ollama is unavailable**: `_classify_ollama_batch` catches
`ImportError` on `import ollama` up front and returns `_fallback()` for every
queued task without attempting a call (`task_classifier.py:103-107`); a
per-task exception during the actual `ollama.chat()` call is caught the same
way (`task_classifier.py:150-152`). Either path lands the task as category
`"Other"`, confidence `"low"` — there is no retry and no queue for
reclassification later; the task is just marked classified with a low-value
label. Also incremental by construction:
`get_unclassified_standalone_tasks()` only returns tasks not already present
in `standalone_task_classifications`, and `run_classifier()`'s caller in
`ado_sync.py` prunes rows for tasks that no longer exist (§1, step 5) — but
nothing re-attempts a stale `"Other"`/low-confidence row once Ollama comes
back up.

## Known issues / quirks

- **Hardcoded `DB_PASSWORD` fallback `"1234"`, duplicated.** `ado_sync.py:32`
  (`os.getenv("DB_PASSWORD", "1234")`) and `data/loader.py:14`
  (`os.getenv("DB_PASSWORD", "1234")`) independently fall back to the same
  weak default if `.env` doesn't set it — two places to keep in sync, and a
  live security default worth fixing centrally (see `master.md` §7, which
  flags this alongside the `SECRET_KEY` default).
- **Fire-and-forget write-back has no reconciliation path.** `write_fields()`
  updates local Postgres first, then the ADO PATCH runs in a background
  thread that may fail (`ado_write.py:189-218`). On failure, the only trace
  is an entry in the capped `_failures` deque (max 50, drained on read by
  `app.py`'s toast callback) — there is no retry, no re-queue, and no
  automatic reversion of the local row. If the failure toast is missed (page
  navigated away, browser closed) or 50 more writes happen before anyone
  checks, the local DB and ADO silently disagree on that field until either
  a human notices and re-saves, or the next full sync happens to pull the
  ADO-side value back down and overwrite the local one anyway.
- **`Custom.MainDevevloper` typo is a duplicated, refactor-hazardous
  constant.** The misspelled ADO field name appears in two independent
  places — `ado_sync.py:52` (`_FIELDS`, read path) and `ado_write.py:57`
  (`FIELD_MAP`, write path) — both commented as intentional, but there is no
  shared constant tying them together. A future "fix the typo" edit to only
  one of the two would silently break either reads or writes for
  `main_developer` without raising an error (ADO would just return/accept an
  empty value for the now-wrong field path). No automated test would catch
  this — see `master.md` §7.
- **Incremental sync cost scales with total open-task count, not with
  what actually changed.** `_fetch_all_open_task_ids()` (`ado_sync.py:141-168`)
  re-fetches *every* open Task created since 2026-01-01 on every 15-minute
  cycle, regardless of whether any of them changed. The code comments this
  as "cheap (bounded set)," but the bound is "however many open Tasks the
  team currently has," which only grows over the life of the 2026 program —
  there's no ceiling or pagination beyond the 200-item batching in
  `_fetch_details()`. This is the direct workaround for ADO not bumping
  `System.ChangedDate` on parent-link changes; it trades sync-cycle cost for
  correctness of `parent_id`.
- **Ollama is an optional runtime dependency with a silent low-confidence
  fallback.** `requirements.txt` pins `ollama==0.6.1`, which is only the
  Python client — it does not install or guarantee a local Ollama server is
  running with `llama3.2:3b` pulled. If the server is down, unreachable, or
  missing the model, every task that fails the rules stage silently becomes
  `"Other"` / `"low"` confidence (`task_classifier.py:103-107`, `150-152`)
  with no error surfaced anywhere outside the log — `run_classifier()`'s
  caller in `run_sync()` treats classifier failures as non-fatal by design
  (`ado_sync.py:719-723`), so a persistently-unreachable Ollama server would
  never show up as a sync failure, just as a slow accumulation of
  low-confidence `"Other"` rows in `agg_standalone_overhead`.
- **`_build_dev_monthly_capacity`'s 9-hour workday is a hardcoded constant**
  (`capacity_hours = wd * 9.0`, `aggregator.py:489`) — not sourced from
  `p_admin_sprint_config` or any other per-sprint capacity override table
  (`db.md` §2 lists `db/admin_hours.py` as owning exactly this kind of
  override), so this aggregate and the Admin Hours page can disagree about
  what a "full" month of capacity means for the same developer.
- **`p_bugs.ado_id`'s unique index is created lazily inside the sync engine**
  (`_sync_production_bugs()`, `ado_sync.py:592-602`), not in `db/schema.sql`
  or `db/aggregations.py` — consistent with the schema-drift pattern
  `db.md` §4 already documents, but worth noting that a sync module, not a
  `db/` module, is one of the places that shapes this table.
