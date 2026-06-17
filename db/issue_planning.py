"""
db/issue_planning.py
────────────────────
Persistence for Issue Planning page.

Tables
------
  issue_caps       — global cap per priority (P1/P2/P3/Other), applies to every dev
  issue_dev_config — per-dev priority order + which priorities they can receive
"""
from __future__ import annotations

from sqlalchemy import text
from data.loader import engine
from config.dev_capacity import DEV_NAMES

_PRIORITIES   = ("P1", "P2", "P3", "Other")
_DEFAULT_CAP  = 4


# ── Init ──────────────────────────────────────────────────────────────────────

def init_issue_planning_tables() -> None:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS issue_caps (
                priority  TEXT    PRIMARY KEY,
                cap_value INTEGER NOT NULL DEFAULT 4
            )
        """))
        for p in _PRIORITIES:
            conn.execute(text(
                "INSERT INTO issue_caps (priority, cap_value)"
                " VALUES (:p, :v) ON CONFLICT (priority) DO NOTHING"
            ), {"p": p, "v": _DEFAULT_CAP})

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS issue_dev_config (
                developer      TEXT    PRIMARY KEY,
                priority_order INTEGER NOT NULL DEFAULT 99,
                can_p1         BOOLEAN NOT NULL DEFAULT TRUE,
                can_p2         BOOLEAN NOT NULL DEFAULT TRUE,
                can_p3         BOOLEAN NOT NULL DEFAULT TRUE,
                can_other      BOOLEAN NOT NULL DEFAULT TRUE
            )
        """))
        for i, dev in enumerate(DEV_NAMES, 1):
            conn.execute(text(
                "INSERT INTO issue_dev_config (developer, priority_order)"
                " VALUES (:d, :o) ON CONFLICT (developer) DO NOTHING"
            ), {"d": dev, "o": i})

        conn.commit()


# ── Caps ──────────────────────────────────────────────────────────────────────

def load_caps() -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT priority, cap_value FROM issue_caps"
        )).fetchall()
    return {r.priority: int(r.cap_value) for r in rows}


def save_cap(priority: str, value: int) -> None:
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE issue_caps SET cap_value = :v WHERE priority = :p"
        ), {"v": value, "p": priority})
        conn.commit()


# ── Dev config ────────────────────────────────────────────────────────────────

def load_dev_config() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT developer, priority_order, can_p1, can_p2, can_p3, can_other"
            " FROM issue_dev_config ORDER BY priority_order, developer"
        )).fetchall()
    return [dict(r._mapping) for r in rows]


def save_dev_field(developer: str, **fields) -> None:
    allowed = {"priority_order", "can_p1", "can_p2", "can_p3", "can_other"}
    fields  = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    with engine.connect() as conn:
        conn.execute(text(
            f"UPDATE issue_dev_config SET {sets} WHERE developer = :developer"
        ), {"developer": developer, **fields})
        conn.commit()


def move_dev(developer: str, direction: str) -> None:
    """Move a dev up (-1) or down (+1) in priority order."""
    cfg  = load_dev_config()
    devs = [d["developer"] for d in cfg]
    if developer not in devs:
        return
    idx = devs.index(developer)
    swap = idx - 1 if direction == "up" else idx + 1
    if swap < 0 or swap >= len(devs):
        return
    oa = cfg[idx]["priority_order"]
    ob = cfg[swap]["priority_order"]
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE issue_dev_config SET priority_order = :o WHERE developer = :d"
        ), {"o": ob, "d": developer})
        conn.execute(text(
            "UPDATE issue_dev_config SET priority_order = :o WHERE developer = :d"
        ), {"o": oa, "d": devs[swap]})
        conn.commit()
