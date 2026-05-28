"""
db/aggregations.py
──────────────────
DDL and initialization for the data pipeline aggregate tables.

These tables are written exclusively by sync/aggregator.py after each ADO sync.
The UI reads from them directly — zero runtime computation.

Tables
------
  agg_item_month_keys       iteration_path → month_key / ym_str, parsed once at sync
  agg_gantt_items           Gantt-ready Enhancement/Bug rows (filtered, pct, dates resolved)
  agg_gantt_tasks           Gantt task sub-rows keyed by parent_id
  agg_story_estimation      Estimation status per 2026 Enhancement (estimated / partial / none)
  agg_dev_monthly_capacity  Developer item counts + hours per month, bucketed by item type
  agg_sprint_daily_activity Daily added/closed counts for the sprint activity chart
  agg_standalone_overhead   Overhead task hours by developer / month / category

Public API
----------
  init_aggregation_tables()   Create all tables and indexes. Safe to call repeatedly.
"""
from __future__ import annotations

from sqlalchemy import text

from data.loader import engine

# ── DDL statements ────────────────────────────────────────────────────────────

_DDL: list[str] = [

    # 1 ── Month keys ─────────────────────────────────────────────────────────
    # Parses iteration_path once so every other aggregate can join cheaply.
    """
    CREATE TABLE IF NOT EXISTS agg_item_month_keys (
        work_item_id   INTEGER      PRIMARY KEY,
        iteration_path TEXT,
        month_num      SMALLINT,                    -- 1-12, NULL if unparseable
        month_label    TEXT,                        -- 'April', 'May', …
        month_key      TEXT,                        -- 'M0','M1','M2','Apr','May',…
        ym_str         TEXT,                        -- '2026-04'
        is_2026        BOOLEAN      NOT NULL DEFAULT FALSE,
        refreshed_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,

    # 2 ── Gantt items ─────────────────────────────────────────────────────────
    # One row per active (non-done) Enhancement / Bug in a 2026 iteration.
    """
    CREATE TABLE IF NOT EXISTS agg_gantt_items (
        work_item_id      INTEGER      PRIMARY KEY,
        title             TEXT,
        work_item_type    TEXT,
        item_type         TEXT,                     -- 'enh' | 'bug'
        state             TEXT,
        iteration_path    TEXT,
        month_num         SMALLINT,
        month_label       TEXT,
        main_developer    TEXT,
        assigned_to       TEXT,
        release_date      DATE,
        bar_start         DATE,
        bar_end           DATE,
        original_estimate NUMERIC,
        t_done            NUMERIC,                  -- sum child completed_work
        t_rem             NUMERIC,                  -- sum child remaining_work
        pct               SMALLINT,                 -- 0-100
        has_tasks         BOOLEAN      NOT NULL DEFAULT FALSE,
        function          TEXT,
        priority          SMALLINT,
        refreshed_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agi_month ON agg_gantt_items (month_num)",
    "CREATE INDEX IF NOT EXISTS idx_agi_dev   ON agg_gantt_items (main_developer)",
    "ALTER TABLE agg_gantt_items ADD COLUMN IF NOT EXISTS function TEXT",
    "ALTER TABLE agg_gantt_items ADD COLUMN IF NOT EXISTS priority SMALLINT",

    # 3 ── Gantt tasks ─────────────────────────────────────────────────────────
    # Task sub-rows for the collapsible Gantt expand — keyed by parent_id.
    """
    CREATE TABLE IF NOT EXISTS agg_gantt_tasks (
        task_id         INTEGER      PRIMARY KEY,
        parent_id       INTEGER,
        title           TEXT,
        state           TEXT,
        pct             SMALLINT,
        bar_start       DATE,
        bar_end         DATE,
        completed_work  NUMERIC,
        remaining_work  NUMERIC,
        refreshed_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_agt_parent ON agg_gantt_tasks (parent_id)",

    # 4 ── Story estimation ────────────────────────────────────────────────────
    # Estimation status per 2026 Enhancement — replaces the 3-level CTE.
    """
    CREATE TABLE IF NOT EXISTS agg_story_estimation (
        work_item_id        INTEGER      PRIMARY KEY,
        title               TEXT,
        work_item_type      TEXT,
        state               TEXT,
        iteration_path      TEXT,
        month_key           TEXT,
        main_developer      TEXT,
        story_owner         TEXT,
        team                TEXT,
        original_estimate   NUMERIC,
        priority            SMALLINT,
        function            TEXT,
        task_count          SMALLINT,
        task_missing_count  SMALLINT,
        task_est_sum        NUMERIC,
        est_status          TEXT,        -- 'estimated'|'estimated_via_tasks'|'partial'|'unestimated'
        refreshed_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE agg_story_estimation ADD COLUMN IF NOT EXISTS priority SMALLINT",
    "ALTER TABLE agg_story_estimation ADD COLUMN IF NOT EXISTS function TEXT",
    "ALTER TABLE agg_story_estimation ADD COLUMN IF NOT EXISTS team TEXT",
    "CREATE INDEX IF NOT EXISTS idx_ase_status ON agg_story_estimation (est_status)",
    "CREATE INDEX IF NOT EXISTS idx_ase_month  ON agg_story_estimation (month_key)",

    # 5 ── Dev monthly capacity ────────────────────────────────────────────────
    # One row per (developer, month, item_type) — replaces per-cell groupby in the capacity grid.
    """
    CREATE TABLE IF NOT EXISTS agg_dev_monthly_capacity (
        main_developer  TEXT,
        ym_str          TEXT,
        month_key       TEXT,
        item_type       TEXT,        -- 'enhancement' | 'bug' | 'watchlist'
        item_count      SMALLINT,
        estimated_hours NUMERIC,
        working_days    SMALLINT,
        capacity_hours  NUMERIC,     -- working_days * 9
        refreshed_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        PRIMARY KEY (main_developer, ym_str, item_type)
    )
    """,

    # 6 ── Sprint daily activity ───────────────────────────────────────────────
    # Daily added / closed counts — replaces O(n) table scan per chart render.
    """
    CREATE TABLE IF NOT EXISTS agg_sprint_daily_activity (
        ym_str       TEXT,
        day_date     DATE,
        added_count  SMALLINT    NOT NULL DEFAULT 0,
        closed_count SMALLINT    NOT NULL DEFAULT 0,
        net_change   SMALLINT    NOT NULL DEFAULT 0,
        refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (ym_str, day_date)
    )
    """,

    # 7 ── Standalone overhead ─────────────────────────────────────────────────
    # Overhead hours per (developer, month, category) — replaces classification groupby.
    """
    CREATE TABLE IF NOT EXISTS agg_standalone_overhead (
        assigned_to  TEXT,
        ym_str       TEXT,
        category     TEXT,
        total_hours  NUMERIC     NOT NULL DEFAULT 0,
        task_count   SMALLINT    NOT NULL DEFAULT 0,
        refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (assigned_to, ym_str, category)
    )
    """,
]


# ── Public API ────────────────────────────────────────────────────────────────

def init_aggregation_tables() -> None:
    """Create all aggregate tables and indexes. Idempotent — safe to call on every startup."""
    with engine.begin() as conn:
        for stmt in _DDL:
            conn.execute(text(stmt.strip()))
