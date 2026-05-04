"""
Planning sign-off gate persistence.

Tables
------
  p_planning_gates   — 7-gate planning state per work item
  p_planning_log     — audit trail for planning gate toggles
  p_tracker_steps    — full lifecycle tracker: one row per (item, step)
  p_tracker_log      — audit trail for lifecycle step checks

Public API — planning gates
  init_planning_tables()
  load_all_gates()
  upsert_gate(...)
  get_log(work_item_id, month_key, limit)

Public API — lifecycle tracker
  init_tracker_tables()
  load_tracker_state(work_item_id)         → {step_key: bool}
  toggle_tracker_step(work_item_id, step_key, phase_key, gate_key,
                      checked, performed_by, step_label)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from data.loader import engine

# ── DDL ──────────────────────────────────────────────────────────────────────

_CREATE_GATES = """
CREATE TABLE IF NOT EXISTS p_planning_gates (
    work_item_id  INTEGER PRIMARY KEY,
    written       BOOLEAN NOT NULL DEFAULT FALSE,
    ac_locked     BOOLEAN NOT NULL DEFAULT FALSE,
    estimated     BOOLEAN NOT NULL DEFAULT FALSE,
    dor           BOOLEAN NOT NULL DEFAULT FALSE,
    story_written BOOLEAN NOT NULL DEFAULT FALSE,
    estimation    BOOLEAN NOT NULL DEFAULT FALSE,
    in_dev        BOOLEAN NOT NULL DEFAULT FALSE,
    in_qa         BOOLEAN NOT NULL DEFAULT FALSE,
    ready_to_ship BOOLEAN NOT NULL DEFAULT FALSE,
    delivery      BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by    TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# Migration: add new columns if the table was created before this schema version
_MIGRATE_GATES = [
    "ALTER TABLE p_planning_gates ADD COLUMN IF NOT EXISTS dor           BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE p_planning_gates ADD COLUMN IF NOT EXISTS story_written BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE p_planning_gates ADD COLUMN IF NOT EXISTS estimation    BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE p_planning_gates ADD COLUMN IF NOT EXISTS in_dev        BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE p_planning_gates ADD COLUMN IF NOT EXISTS in_qa         BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE p_planning_gates ADD COLUMN IF NOT EXISTS ready_to_ship BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE p_planning_gates ADD COLUMN IF NOT EXISTS delivery      BOOLEAN NOT NULL DEFAULT FALSE",
]

_CREATE_LOG = """
CREATE TABLE IF NOT EXISTS p_planning_log (
    log_id        SERIAL PRIMARY KEY,
    work_item_id  INTEGER NOT NULL,
    title         TEXT,
    gate          TEXT NOT NULL,
    action        TEXT NOT NULL,
    performed_by  TEXT NOT NULL DEFAULT 'system',
    performed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ba            TEXT,
    dev_name      TEXT,
    month_key     TEXT,
    priority      TEXT,
    new_status    TEXT
)
"""

_CREATE_LOG_IDX_ITEM = (
    "CREATE INDEX IF NOT EXISTS idx_planning_log_item "
    "ON p_planning_log (work_item_id)"
)

_CREATE_LOG_IDX_MONTH = (
    "CREATE INDEX IF NOT EXISTS idx_planning_log_month "
    "ON p_planning_log (month_key)"
)


def init_planning_tables() -> None:
    """Create planning tables if they don't exist. Safe to call on every startup."""
    with engine.begin() as conn:
        for ddl in (_CREATE_GATES, _CREATE_LOG, _CREATE_LOG_IDX_ITEM, _CREATE_LOG_IDX_MONTH):
            conn.execute(text(ddl))
        for ddl in _MIGRATE_GATES:
            conn.execute(text(ddl))
    init_tracker_tables()


# ── Lifecycle tracker DDL ─────────────────────────────────────────────────────

_CREATE_TRACKER_STEPS = """
CREATE TABLE IF NOT EXISTS p_tracker_steps (
    work_item_id  INTEGER  NOT NULL,
    step_key      TEXT     NOT NULL,
    phase_key     TEXT     NOT NULL,
    gate_key      TEXT     NOT NULL,
    checked       BOOLEAN  NOT NULL DEFAULT FALSE,
    updated_by    TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (work_item_id, step_key)
)
"""

_CREATE_TRACKER_LOG = """
CREATE TABLE IF NOT EXISTS p_tracker_log (
    log_id        SERIAL PRIMARY KEY,
    work_item_id  INTEGER  NOT NULL,
    step_key      TEXT     NOT NULL,
    phase_key     TEXT     NOT NULL,
    gate_key      TEXT     NOT NULL,
    step_label    TEXT,
    action        TEXT     NOT NULL,
    performed_by  TEXT     NOT NULL DEFAULT 'system',
    performed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CREATE_TRACKER_IDX     = ("CREATE INDEX IF NOT EXISTS idx_tracker_steps_item "
                            "ON p_tracker_steps (work_item_id)")
_CREATE_TRACKER_LOG_IDX = ("CREATE INDEX IF NOT EXISTS idx_tracker_log_item "
                            "ON p_tracker_log (work_item_id)")


def init_tracker_tables() -> None:
    """Create lifecycle tracker tables if they don't exist."""
    with engine.begin() as conn:
        for ddl in (_CREATE_TRACKER_STEPS, _CREATE_TRACKER_LOG,
                    _CREATE_TRACKER_IDX, _CREATE_TRACKER_LOG_IDX):
            conn.execute(text(ddl))


# ── Lifecycle tracker read ────────────────────────────────────────────────────

def load_tracker_state(work_item_id: int) -> dict[str, bool]:
    """
    Return {step_key: checked} for every persisted step of a work item.
    Steps that have never been touched are absent (treat as False).
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT step_key, checked FROM p_tracker_steps "
                     "WHERE work_item_id = :wid"),
                {"wid": work_item_id},
            ).fetchall()
        return {r.step_key: bool(r.checked) for r in rows}
    except Exception:
        return {}


# ── Lifecycle tracker write ───────────────────────────────────────────────────

def toggle_tracker_step(
    work_item_id: int,
    step_key:     str,
    phase_key:    str,
    gate_key:     str,
    checked:      bool,
    performed_by: str,
    step_label:   str = "",
) -> None:
    """Upsert a single step state and append an audit log entry."""
    action = "Checked" if checked else "Unchecked"
    now    = datetime.now(timezone.utc)

    upsert_sql = """
        INSERT INTO p_tracker_steps
            (work_item_id, step_key, phase_key, gate_key, checked, updated_by, updated_at)
        VALUES (:wid, :sk, :pk, :gk, :checked, :by, :now)
        ON CONFLICT (work_item_id, step_key) DO UPDATE
        SET checked = :checked, updated_by = :by, updated_at = :now
    """
    log_sql = """
        INSERT INTO p_tracker_log
            (work_item_id, step_key, phase_key, gate_key,
             step_label, action, performed_by, performed_at)
        VALUES (:wid, :sk, :pk, :gk, :lbl, :action, :by, :now)
    """
    params = {
        "wid": work_item_id, "sk": step_key, "pk": phase_key, "gk": gate_key,
        "checked": checked, "by": performed_by, "now": now,
    }
    with engine.begin() as conn:
        conn.execute(text(upsert_sql), params)
        conn.execute(text(log_sql), {**params, "action": action, "lbl": step_label or step_key})


# ── Read ──────────────────────────────────────────────────────────────────────

def load_all_gates() -> dict[int, dict]:
    """
    Return every row in p_planning_gates as a 7-field dict per work item.
    Returns empty dict on any error.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT work_item_id,
                           dor, story_written, estimation,
                           in_dev, in_qa, ready_to_ship, delivery
                    FROM p_planning_gates
                """)
            ).fetchall()
        return {
            r.work_item_id: {
                "dor":           bool(r.dor),
                "story_written": bool(r.story_written),
                "estimation":    bool(r.estimation),
                "in_dev":        bool(r.in_dev),
                "in_qa":         bool(r.in_qa),
                "ready_to_ship": bool(r.ready_to_ship),
                "delivery":      bool(r.delivery),
            }
            for r in rows
        }
    except Exception:
        return {}


def get_log(
    work_item_id: Optional[int] = None,
    month_key: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """
    Query p_planning_log, newest first.

    Filters:
        work_item_id — restrict to one item
        month_key    — restrict to one month bucket (e.g. "M1", "Apr")
    """
    conditions = []
    params: dict = {"lim": limit}

    if work_item_id is not None:
        conditions.append("work_item_id = :wid")
        params["wid"] = work_item_id
    if month_key is not None:
        conditions.append("month_key = :mkey")
        params["mkey"] = month_key

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT log_id, work_item_id, title, gate, action,
               performed_by, performed_at, ba, dev_name,
               month_key, priority, new_status
        FROM   p_planning_log
        {where}
        ORDER  BY performed_at DESC
        LIMIT  :lim
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


# ── Write ─────────────────────────────────────────────────────────────────────

# Logical gate name → column name in p_planning_gates
_GATE_COL = {
    "dor":           "dor",
    "story_written": "story_written",
    "estimation":    "estimation",
    "in_dev":        "in_dev",
    "in_qa":         "in_qa",
    "ready_to_ship": "ready_to_ship",
    "delivery":      "delivery",
}

# Cascade clear: clearing a gate also clears everything downstream
_CASCADE_CLEAR = {
    "dor":           ("story_written", "estimation", "in_dev", "in_qa", "ready_to_ship", "delivery"),
    "story_written": ("estimation", "in_dev", "in_qa", "ready_to_ship", "delivery"),
    "estimation":    ("in_dev", "in_qa", "ready_to_ship", "delivery"),
    "in_dev":        ("in_qa", "ready_to_ship", "delivery"),
    "in_qa":         ("ready_to_ship", "delivery"),
    "ready_to_ship": ("delivery",),
    "delivery":      (),
}


def upsert_gate(
    work_item_id: int,
    gate: str,
    value: bool,
    performed_by: str,
    *,
    title: str = "",
    ba: str = "",
    dev_name: str = "",
    month_key: str = "",
    priority: str = "",
) -> None:
    """
    Atomically update gate state and insert an audit log entry.

    gate must be one of the 7 gate names in _GATE_COL.
    Clearing a gate cascades to all downstream gates.
    """
    if gate not in _GATE_COL:
        raise ValueError(f"Unknown gate '{gate}'. Must be one of: {list(_GATE_COL)}")

    action = "Confirmed" if value else "Cleared"
    now = datetime.now(timezone.utc)

    # Build the SET clause — handle cascade clears
    set_parts: dict[str, bool] = {gate: value}
    if not value:
        for downstream in _CASCADE_CLEAR.get(gate, ()):
            set_parts[downstream] = False

    # Map logical names → column names
    col_assignments = ", ".join(
        f"{_GATE_COL[k]} = :{k}_val" for k in set_parts
    )
    set_params = {f"{k}_val": v for k, v in set_parts.items()}
    set_params.update({
        "wid":        work_item_id,
        "updated_by": performed_by,
        "updated_at": now,
    })

    col_list = ", ".join(_GATE_COL[k] for k in set_parts)
    val_list = ", ".join(f":{k}_val" for k in set_parts)

    upsert_sql = f"""
        INSERT INTO p_planning_gates (work_item_id, {col_list}, updated_by, updated_at)
        VALUES (:wid, {val_list}, :updated_by, :updated_at)
        ON CONFLICT (work_item_id) DO UPDATE
        SET {col_assignments},
            updated_by = :updated_by,
            updated_at = :updated_at
    """

    new_status = _status_label(gate, value)

    log_sql = """
        INSERT INTO p_planning_log
            (work_item_id, title, gate, action, performed_by, performed_at,
             ba, dev_name, month_key, priority, new_status)
        VALUES
            (:wid, :title, :gate, :action, :performed_by, :performed_at,
             :ba, :dev_name, :month_key, :priority, :new_status)
    """
    log_params = {
        "wid":          work_item_id,
        "title":        title,
        "gate":         gate,
        "action":       action,
        "performed_by": performed_by,
        "performed_at": now,
        "ba":           ba or None,
        "dev_name":     dev_name or None,
        "month_key":    month_key or None,
        "priority":     priority or None,
        "new_status":   new_status,
    }

    with engine.begin() as conn:
        conn.execute(text(upsert_sql), set_params)
        conn.execute(text(log_sql), log_params)


def _status_label(gate: str, value: bool) -> str:
    labels = {
        ("dor",           True):  "DoR Gate ✓",
        ("dor",           False): "DoR Gate ✗",
        ("story_written", True):  "Story Written ✓",
        ("story_written", False): "Story Written ✗",
        ("estimation",    True):  "Estimation ✓",
        ("estimation",    False): "Estimation ✗",
        ("in_dev",        True):  "In Dev →",
        ("in_dev",        False): "In Dev Cleared",
        ("in_qa",         True):  "In QA →",
        ("in_qa",         False): "In QA Cleared",
        ("ready_to_ship", True):  "Ready to Ship ✓",
        ("ready_to_ship", False): "Ready to Ship ✗",
        ("delivery",      True):  "Shipped ✓",
        ("delivery",      False): "Shipped ✗",
    }
    return labels.get((gate, value), f"{gate}={'on' if value else 'off'}")
