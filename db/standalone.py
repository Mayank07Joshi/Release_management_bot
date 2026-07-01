"""
Standalone task classification persistence.

Tables
------
  standalone_task_classifications  — two-agent (rules + Ollama) classified tasks

Public API
----------
  init_standalone_table()
  get_unclassified_standalone_tasks(team_members)  → list[dict]
  save_classifications(records)                     → int
  load_all_classifications()                        → list[dict]
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from data.loader import engine

log = logging.getLogger(__name__)

# Ensure activity column exists on work_items_main (added to sync later)
_ENSURE_ACTIVITY_COL = """
ALTER TABLE work_items_main
ADD COLUMN IF NOT EXISTS activity VARCHAR(100) DEFAULT '';
"""

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS standalone_task_classifications (
    task_id        INTEGER PRIMARY KEY,
    title          TEXT,
    activity       VARCHAR(100),
    category       VARCHAR(60)  NOT NULL,
    confidence     VARCHAR(10),
    method         VARCHAR(20),
    reasoning      TEXT,
    override       VARCHAR(60),
    classified_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);
"""

# Tasks with no parent AND no Related link to an Enhancement/Bug, not yet classified
_UNCLASSIFIED_SQL = """
SELECT t.work_item_id,
       t.title,
       COALESCE(t.activity, '') AS activity,
       t.assigned_to,
       COALESCE(t.original_estimate, 0) AS original_estimate,
       t.iteration_path,
       t.state
FROM work_items_main t
WHERE t.work_item_type = 'Task'
  AND t.parent_id IS NULL
  AND t.assigned_to = ANY(:team_members)
  AND t.work_item_id NOT IN (
      SELECT task_id FROM standalone_task_classifications
  )
  AND t.work_item_id NOT IN (
      SELECT DISTINCT t2.work_item_id
      FROM work_items_main t2
      JOIN work_items_relations rel
          ON rel.relation_type = 'System.LinkTypes.Related'
         AND (rel.source_id = t2.work_item_id OR rel.target_id = t2.work_item_id)
      JOIN work_items_main e
          ON e.work_item_id = CASE
              WHEN rel.source_id = t2.work_item_id THEN rel.target_id
              ELSE rel.source_id END
      WHERE t2.work_item_type = 'Task'
        AND e.work_item_type IN ('Enhancement', 'Bug', 'Bug_UI', 'Bug_Text')
  )
ORDER BY t.work_item_id;
"""

# Open standalone tasks with effective category — for capacity UI
_LOAD_SQL = """
SELECT sc.task_id,
       COALESCE(sc.override, sc.category) AS category,
       sc.method,
       t.assigned_to,
       COALESCE(t.original_estimate, 0) AS original_estimate,
       t.iteration_path,
       t.title,
       t.state
FROM standalone_task_classifications sc
JOIN work_items_main t ON t.work_item_id = sc.task_id
WHERE t.work_item_type = 'Task'
  AND t.parent_id IS NULL
  AND t.state NOT IN (
      'Closed', 'Dev Complete', 'Resolved', 'Not Required', 'Not an issue'
  );
"""


def init_standalone_table() -> None:
    """Create the classifications table and ensure activity column exists."""
    with engine.begin() as conn:
        conn.execute(text(_ENSURE_ACTIVITY_COL))
        conn.execute(text(_CREATE_TABLE))


def get_unclassified_standalone_tasks(team_members: list[str]) -> list[dict]:
    """Return standalone tasks for team_members not yet in the classifications table."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(_UNCLASSIFIED_SQL), {"team_members": team_members}
            ).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        log.warning("get_unclassified_standalone_tasks: %s", e)
        return []


def save_classifications(records: list[dict]) -> int:
    """Upsert classification records. Returns count saved."""
    if not records:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with engine.begin() as conn:
        for r in records:
            conn.execute(text("""
                INSERT INTO standalone_task_classifications
                    (task_id, title, activity, category, confidence, method, reasoning, classified_at)
                VALUES
                    (:task_id, :title, :activity, :category, :confidence, :method, :reasoning, :now)
                ON CONFLICT (task_id) DO UPDATE SET
                    category      = EXCLUDED.category,
                    confidence    = EXCLUDED.confidence,
                    method        = EXCLUDED.method,
                    reasoning     = EXCLUDED.reasoning,
                    classified_at = EXCLUDED.classified_at
            """), {**r, "now": now})
    return len(records)


def load_all_classifications() -> list[dict]:
    """Return open classified standalone tasks for capacity calculations."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(_LOAD_SQL)).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        log.warning("load_all_classifications: %s", e)
        return []
