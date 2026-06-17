# Data Pipeline — Design Document

## Overview

The dashboard uses a two-stage data pipeline. Raw ADO data lands in `work_items_main` via the sync job. An aggregator then pre-computes all UI-facing summaries into `agg_*` tables. Pages read only from `agg_*` — no computation at render time.

```
Azure DevOps API
      │  every 15 min
      ▼
 run_sync()                    sync/ado_sync.py
      │  writes raw rows
      ▼
 work_items_main               PostgreSQL (raw)
      │  immediately after sync
      ▼
 run_aggregations()            sync/aggregator.py
      │  writes pre-computed rows
      ▼
 agg_* tables                  PostgreSQL (pre-computed)
      │  on every page visit (fast SELECT only)
      ▼
 UI callbacks                  pages_dash/*.py
```

---

## Aggregate Tables

### `agg_item_month_keys`
Parses `iteration_path` once per item at sync time. All other aggregates derive month info from here rather than re-running the regex.

| Column | Type | Notes |
|---|---|---|
| work_item_id | INTEGER PK | |
| iteration_path | TEXT | raw value |
| month_num | SMALLINT | 1–12, NULL if unparseable |
| month_label | TEXT | 'April', 'May', … |
| month_key | TEXT | 'M0', 'M1', 'M2', 'Apr', … |
| ym_str | TEXT | '2026-04' |
| is_2026 | BOOLEAN | TRUE if iteration is a 2026 sprint |
| refreshed_at | TIMESTAMPTZ | |

**M0 rule:** M0 = current calendar month, except after the last working day of the month where it advances to the next month. M1 = M0+1, M2 = M0+2. All other months use their 3-letter abbreviation.

---

### `agg_gantt_items`
One row per active (non-done) Enhancement or Bug in a 2026 iteration. Used directly by the Gantt chart render — no Python filtering or groupby at render time.

| Column | Type | Notes |
|---|---|---|
| work_item_id | INTEGER PK | |
| title | TEXT | |
| work_item_type | TEXT | 'Enhancement', 'Bug', … |
| item_type | TEXT | 'enh' or 'bug' |
| state | TEXT | |
| iteration_path | TEXT | |
| month_num | SMALLINT | |
| month_label | TEXT | 'May', 'June', … |
| main_developer | TEXT | stripped display name |
| assigned_to | TEXT | stripped display name |
| release_date | DATE | parsed from free-text |
| bar_start | DATE | activated_date or iteration month start |
| bar_end | DATE | same as release_date |
| original_estimate | NUMERIC | |
| t_done | NUMERIC | sum of child task completed_work |
| t_rem | NUMERIC | sum of child task remaining_work |
| pct | SMALLINT | 0–100 |
| has_tasks | BOOLEAN | TRUE if any Task has this as parent_id |
| refreshed_at | TIMESTAMPTZ | |

**Excluded:** Done, Watch List, Closed, Resolved, and any other `_DONE_STATES`. Items where `pct >= 100` are also excluded (done by task hours even if state not updated).

---

### `agg_gantt_tasks`
Task sub-rows for the collapsible Gantt expand. Indexed by `parent_id`.

| Column | Type | Notes |
|---|---|---|
| task_id | INTEGER PK | |
| parent_id | INTEGER | FK → agg_gantt_items.work_item_id |
| title | TEXT | |
| state | TEXT | |
| pct | SMALLINT | from completed/remaining work |
| bar_start | DATE | activated_date or iteration month start |
| bar_end | DATE | parent's release_date |
| completed_work | NUMERIC | |
| remaining_work | NUMERIC | |
| refreshed_at | TIMESTAMPTZ | |

---

### `agg_story_estimation`
Estimation status per 2026 Enhancement. Replaces the 3-level CTE that ran on every planning page load.

| Column | Type | Notes |
|---|---|---|
| work_item_id | INTEGER PK | |
| est_status | TEXT | 'estimated' \| 'estimated_via_tasks' \| 'partial' \| 'unestimated' |
| task_count | SMALLINT | number of child tasks |
| task_missing_count | SMALLINT | child tasks with estimate = 0 |
| task_est_sum | NUMERIC | sum of child task estimates |
| month_key | TEXT | M0/M1/M2/Apr/… |
| … | | other fields for display |

**Status logic:**
- `estimated` — `original_estimate > 0`
- `estimated_via_tasks` — no direct estimate, all child tasks have estimates
- `partial` — no direct estimate, some child tasks missing estimates
- `unestimated` — no direct estimate and no child tasks with estimates

---

### `agg_dev_monthly_capacity`
Developer item counts and hours per (developer, month, item_type). Replaces the 18–36 per-cell filter+groupby operations in the capacity grid.

| Column | Type | Notes |
|---|---|---|
| main_developer | TEXT | PK part |
| ym_str | TEXT | '2026-04', PK part |
| item_type | TEXT | 'enhancement' \| 'bug' \| 'watchlist', PK part |
| item_count | SMALLINT | |
| estimated_hours | NUMERIC | sum of original_estimate |
| working_days | SMALLINT | weekdays in that month |
| capacity_hours | NUMERIC | working_days × 9h |
| month_key | TEXT | M0/M1/M2/Apr/… |

**Capacity:** 9h per working day (weekdays only). Company holidays and leaves not yet tracked — `p_iteration_capacity` table is reserved for per-dev overrides in a future leave management feature.

**Buckets:** Watch List items counted separately under 'watchlist' (QA bucket), not against developer capacity.

---

### `agg_sprint_daily_activity`
Daily added/closed counts for the current sprint month. Replaces the O(n) sprint history table scan per chart render.

| Column | Type | Notes |
|---|---|---|
| ym_str | TEXT | '2026-05', PK part |
| day_date | DATE | PK part |
| added_count | SMALLINT | items added to sprint that day |
| closed_count | SMALLINT | items closed that day |
| net_change | SMALLINT | added - closed |

Only the current month is refreshed each cycle. Previous months' rows are preserved.

---

### `agg_standalone_overhead`
Overhead task hours by developer / month / category. Replaces the classification groupby in the capacity overhead section.

| Column | Type | Notes |
|---|---|---|
| assigned_to | TEXT | PK part |
| ym_str | TEXT | PK part |
| category | TEXT | 'Meetings & Calls' \| 'Dev Overhead' \| … , PK part |
| total_hours | NUMERIC | sum of original_estimate |
| task_count | SMALLINT | |

---

## Refresh Schedule

| Event | What runs |
|---|---|
| App startup | `init_aggregation_tables()` — creates tables if missing (idempotent) |
| Each ADO sync (~every 15 min) | `run_aggregations()` — full rebuild of all agg_* tables |
| Manual full sync | Same — full rebuild triggered automatically |

All aggregate builders are non-fatal — if one fails, the others still run and the sync cycle still completes. Failures are logged as warnings.

---

## Adding a New Aggregate

1. Add DDL to `_DDL` list in `db/aggregations.py`
2. Add a `_build_<name>()` function in `sync/aggregator.py`
3. Add it to the `steps` list inside `run_aggregations()`
4. Update this document

---

## Phase Status

| Phase | Description | Status |
|---|---|---|
| Phase 1 | Foundation — schema, aggregator, wiring | ✅ Complete |
| Phase 2 | Wire UI to read from agg_* tables | Pending |
| Phase 3 | Remove dead runtime aggregation code | Pending |
