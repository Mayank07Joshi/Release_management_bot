"""
Sprint iteration history — DB persistence layer.

Table: p_sprint_item_history
  One row per (work_item_id, iteration_path) pair.
  added_to_iteration_at = when the item last entered that iteration.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from data.loader import engine

_CREATE_SPRINT_HISTORY = """
CREATE TABLE IF NOT EXISTS p_sprint_item_history (
    work_item_id          INTEGER  NOT NULL,
    iteration_path        TEXT     NOT NULL,
    added_to_iteration_at TIMESTAMPTZ,
    synced_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (work_item_id, iteration_path)
)
"""

_CREATE_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_sprint_history_path "
    "ON p_sprint_item_history (iteration_path)"
)


def init_sprint_history_table() -> None:
    """Create table + index if absent. Safe to call on every startup."""
    with engine.begin() as conn:
        conn.execute(text(_CREATE_SPRINT_HISTORY))
        conn.execute(text(_CREATE_IDX))


def load_sprint_history(iteration_path: str) -> dict[int, datetime | None]:
    """
    Return {work_item_id: added_to_iteration_at} for every item
    stored under the given iteration_path.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT work_item_id, added_to_iteration_at "
                    "FROM p_sprint_item_history "
                    "WHERE iteration_path = :path"
                ),
                {"path": iteration_path},
            ).fetchall()
        return {r.work_item_id: r.added_to_iteration_at for r in rows}
    except Exception:
        return {}


def bulk_upsert_sprint_history(records: list[dict]) -> None:
    """
    Upsert rows into p_sprint_item_history.
    Each record: {work_item_id, iteration_path, added_at}.

    COALESCE ensures a None added_at never overwrites an existing timestamp —
    preserves accurate revision-history dates on re-runs where the fallback
    would only produce None.
    """
    if not records:
        return
    sql = """
        INSERT INTO p_sprint_item_history
            (work_item_id, iteration_path, added_to_iteration_at, synced_at)
        VALUES (:wid, :path, :added_at, :now)
        ON CONFLICT (work_item_id, iteration_path) DO UPDATE
        SET added_to_iteration_at =
                CASE
                    WHEN :added_at IS NOT NULL
                    THEN :added_at
                    WHEN EXTRACT(YEAR FROM p_sprint_item_history.added_to_iteration_at) < 9000
                    THEN p_sprint_item_history.added_to_iteration_at
                    ELSE NULL
                END,
            synced_at = :now
    """
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for rec in records:
            raw_dt = rec.get("added_at")
            # Reject far-future sentinel dates (ADO uses 9999-01-01 for open items)
            if raw_dt is not None:
                try:
                    if datetime.fromisoformat(str(raw_dt)[:10]).year >= 9000:
                        raw_dt = None
                except Exception:
                    pass
            conn.execute(text(sql), {
                "wid":      rec["work_item_id"],
                "path":     rec["iteration_path"],
                "added_at": raw_dt,
                "now":      now,
            })
