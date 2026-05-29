"""
Leave management persistence.

Tables
------
  p_company_holidays  — public / company-wide holidays
  p_dev_leaves        — individual developer leaves (one row per day)

Public API
----------
  init_leave_tables()
  add_holiday(holiday_date, name, created_by)  -> int  (rows inserted)
  delete_holiday(holiday_id)
  get_holidays(year=None)                       -> list[dict]

  add_dev_leave(developer_name, dates, leave_type, hours, created_by) -> int
  delete_dev_leave(leave_id)
  get_dev_leaves(developer_name=None, ym_str=None) -> list[dict]

  get_leave_capacity(yms)
    -> {"leaves": {(dev, ym): hours}, "holidays": {ym: hours}}
    Full-month totals used by capacity grid.

  get_leave_capacity_remaining(yms)
    -> same shape but only dates >= today (for LIVE M0 view).
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

from sqlalchemy import text
from data.loader import engine

# ── DDL ───────────────────────────────────────────────────────────────────────
_CREATE_HOLIDAYS = """
CREATE TABLE IF NOT EXISTS p_company_holidays (
    id           SERIAL PRIMARY KEY,
    holiday_date DATE   NOT NULL,
    name         TEXT   NOT NULL,
    created_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_holiday_date UNIQUE (holiday_date)
)
"""

_CREATE_LEAVES = """
CREATE TABLE IF NOT EXISTS p_dev_leaves (
    id               SERIAL PRIMARY KEY,
    developer_name   TEXT   NOT NULL,
    leave_date       DATE   NOT NULL,
    leave_type       TEXT   NOT NULL DEFAULT 'planned',  -- planned | sick
    hours            NUMERIC(4,1) NOT NULL DEFAULT 9.0,  -- 9.0 full / 4.5 half
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dev_leave UNIQUE (developer_name, leave_date)
)
"""

_IDX_LEAVES_DEV  = "CREATE INDEX IF NOT EXISTS idx_devleaves_dev  ON p_dev_leaves (developer_name)"
_IDX_LEAVES_DATE = "CREATE INDEX IF NOT EXISTS idx_devleaves_date ON p_dev_leaves (leave_date)"
_IDX_HOL_DATE    = "CREATE INDEX IF NOT EXISTS idx_holidays_date  ON p_company_holidays (holiday_date)"


def init_leave_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text(_CREATE_HOLIDAYS))
        conn.execute(text(_CREATE_LEAVES))
        conn.execute(text(_IDX_LEAVES_DEV))
        conn.execute(text(_IDX_LEAVES_DATE))
        conn.execute(text(_IDX_HOL_DATE))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workdays_in_range(start: date, end: date, skip_holidays: set[date] | None = None) -> list[date]:
    """Return all weekdays between start and end (inclusive), skipping holiday dates."""
    skip = skip_holidays or set()
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5 and cur not in skip:
            out.append(cur)
        from datetime import timedelta
        cur = cur + timedelta(days=1)
    return out


def _holiday_set() -> set[date]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT holiday_date FROM p_company_holidays")).fetchall()
    return {r[0] for r in rows}


# ── Company holidays ──────────────────────────────────────────────────────────

def add_holiday(holiday_date: date, name: str, created_by: str = "system") -> int:
    """Insert a single holiday. Returns 1 on insert, 0 if date already exists."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO p_company_holidays (holiday_date, name, created_by)
                VALUES (:d, :n, :by)
                ON CONFLICT (holiday_date) DO NOTHING
            """), {"d": holiday_date, "n": name, "by": created_by})
        return 1
    except Exception:
        return 0


def delete_holiday(holiday_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM p_company_holidays WHERE id = :id"), {"id": holiday_id})


def get_holidays(year: int | None = None) -> list[dict]:
    where = "WHERE EXTRACT(YEAR FROM holiday_date) = :y" if year else ""
    params = {"y": year} if year else {}
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, holiday_date, name, created_by, created_at
            FROM p_company_holidays
            {where}
            ORDER BY holiday_date
        """), params).fetchall()
    return [{"id": r.id, "date": r.holiday_date, "name": r.name,
             "created_by": r.created_by, "created_at": r.created_at} for r in rows]


# ── Developer leaves ──────────────────────────────────────────────────────────

def add_dev_leave(
    developer_name: str,
    dates: list[date],          # pre-expanded list of individual dates
    leave_type: str,            # "planned" | "sick"
    hours: float,               # 9.0 or 4.5
    created_by: str = "system",
) -> int:
    """Upsert one row per date. Returns count of rows inserted/updated."""
    if not dates:
        return 0
    rows = [
        {"dev": developer_name, "d": d, "lt": leave_type,
         "h": hours, "by": created_by}
        for d in dates
    ]
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_dev_leaves (developer_name, leave_date, leave_type, hours, created_by)
            VALUES (:dev, :d, :lt, :h, :by)
            ON CONFLICT (developer_name, leave_date)
            DO UPDATE SET leave_type = EXCLUDED.leave_type,
                          hours      = EXCLUDED.hours,
                          created_by = EXCLUDED.created_by,
                          created_at = NOW()
        """), rows)
    return len(rows)


def delete_dev_leave(leave_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM p_dev_leaves WHERE id = :id"), {"id": leave_id})


def get_dev_leaves(
    developer_name: str | None = None,
    ym_str: str | None = None,          # e.g. "2026-06"
) -> list[dict]:
    conditions, params = [], {}
    if developer_name:
        conditions.append("developer_name = :dev")
        params["dev"] = developer_name
    if ym_str:
        conditions.append("TO_CHAR(leave_date, 'YYYY-MM') = :ym")
        params["ym"] = ym_str
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, developer_name, leave_date, leave_type, hours, created_by, created_at
            FROM p_dev_leaves
            {where}
            ORDER BY leave_date DESC, developer_name
        """), params).fetchall()
    return [
        {"id": r.id, "developer": r.developer_name, "date": r.leave_date,
         "type": r.leave_type, "hours": float(r.hours),
         "created_by": r.created_by, "created_at": r.created_at}
        for r in rows
    ]


# ── Capacity impact queries ───────────────────────────────────────────────────

def get_leave_capacity(yms: list[str], today_floor: date | None = None) -> dict:
    """
    Returns hours lost to leave/holidays per dev per month.

    Result:
      {
        "leaves":   {(developer_name, ym_str): float},   # dev-specific
        "holidays": {ym_str: float},                      # applies to all devs
      }

    If today_floor is set, only dates >= today_floor are counted
    (used for the LIVE remaining-hours view).
    """
    if not yms:
        return {"leaves": {}, "holidays": {}}

    ym_list = ", ".join(f"'{y}'" for y in yms)
    date_filter = "AND leave_date >= :floor" if today_floor else ""
    hol_filter  = "AND holiday_date >= :floor" if today_floor else ""
    params: dict = {}
    if today_floor:
        params["floor"] = today_floor

    with engine.connect() as conn:
        # Dev leaves
        leave_rows = conn.execute(text(f"""
            SELECT developer_name,
                   TO_CHAR(leave_date, 'YYYY-MM') AS ym,
                   SUM(hours) AS total_h
            FROM p_dev_leaves
            WHERE TO_CHAR(leave_date, 'YYYY-MM') IN ({ym_list})
            {date_filter}
            GROUP BY developer_name, TO_CHAR(leave_date, 'YYYY-MM')
        """), params).fetchall()

        # Company holidays (count per month × 9h per day)
        hol_rows = conn.execute(text(f"""
            SELECT TO_CHAR(holiday_date, 'YYYY-MM') AS ym,
                   COUNT(*) * 9.0 AS total_h
            FROM p_company_holidays
            WHERE TO_CHAR(holiday_date, 'YYYY-MM') IN ({ym_list})
            {hol_filter}
            GROUP BY TO_CHAR(holiday_date, 'YYYY-MM')
        """), params).fetchall()

    leaves   = {(r.developer_name, r.ym): float(r.total_h) for r in leave_rows}
    holidays = {r.ym: float(r.total_h) for r in hol_rows}
    return {"leaves": leaves, "holidays": holidays}
