"""Report request queue — stores user queries and agent pipeline state."""
from __future__ import annotations
import logging
from sqlalchemy import text
from data.loader import engine

log = logging.getLogger(__name__)

STATUS_PENDING     = "pending"
STATUS_RUNNING     = "running"
STATUS_CP1         = "cp1"           # spec + query plan ready, awaiting admin approval
STATUS_CP1_OK      = "cp1_approved"  # approved → start research
STATUS_RESEARCHING = "researching"
STATUS_CP2         = "cp2"           # data gathered, awaiting admin approval
STATUS_CP2_OK      = "cp2_approved"  # approved → start build
STATUS_BUILDING    = "building"
STATUS_DONE        = "done"
STATUS_FAILED      = "failed"
STATUS_CANCELLED   = "cancelled"

_LABELS = {
    STATUS_PENDING:     ("Pending",            "#f59e0b"),
    STATUS_RUNNING:     ("Running — Intake",   "#818cf8"),
    STATUS_CP1:         ("Review Spec",        "#fb923c"),
    STATUS_CP1_OK:      ("Approved → Research","#818cf8"),
    STATUS_RESEARCHING: ("Researching",        "#818cf8"),
    STATUS_CP2:         ("Review Data",        "#fb923c"),
    STATUS_CP2_OK:      ("Approved → Build",   "#818cf8"),
    STATUS_BUILDING:    ("Building Report",    "#818cf8"),
    STATUS_DONE:        ("Done",               "#34d399"),
    STATUS_FAILED:      ("Failed",             "#f87171"),
    STATUS_CANCELLED:   ("Cancelled",          "#64748b"),
}

def status_label(status: str) -> tuple[str, str]:
    return _LABELS.get(status, (status, "#94a3b8"))


def init_table() -> None:
    with engine.begin() as c:
        c.execute(text("""
            CREATE TABLE IF NOT EXISTS report_requests (
                id            SERIAL PRIMARY KEY,
                email         TEXT NOT NULL,
                query_text    TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                intake_spec   TEXT,
                query_plan    TEXT,
                data_findings TEXT,
                report_path   TEXT,
                agent_log     TEXT DEFAULT '',
                admin_notes   TEXT DEFAULT '',
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """))
    log.info("report_requests table ready")


def add_request(email: str, query: str) -> int:
    with engine.begin() as c:
        row = c.execute(text(
            "INSERT INTO report_requests (email, query_text) VALUES (:e, :q) RETURNING id"
        ), {"e": email, "q": query}).fetchone()
        return row[0]


def get_request(request_id: int) -> dict | None:
    with engine.connect() as c:
        row = c.execute(text("""
            SELECT id, email, query_text, status, intake_spec, query_plan,
                   data_findings, report_path, agent_log, admin_notes, created_at, updated_at
            FROM report_requests WHERE id = :id
        """), {"id": request_id}).fetchone()
        return dict(row._mapping) if row else None


def get_all_requests(limit: int = 50) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT id, email, query_text, status, intake_spec, query_plan,
                   data_findings, report_path, agent_log, admin_notes, created_at, updated_at
            FROM report_requests ORDER BY created_at DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]


def set_field(request_id: int, **kwargs) -> None:
    allowed = {"status", "intake_spec", "query_plan", "data_findings", "report_path", "admin_notes"}
    parts = ["updated_at = NOW()"]
    params: dict = {"id": request_id}
    for k, v in kwargs.items():
        if k in allowed:
            parts.append(f"{k} = :{k}")
            params[k] = v
    if len(parts) == 1:
        return
    with engine.begin() as c:
        c.execute(text(f"UPDATE report_requests SET {', '.join(parts)} WHERE id = :id"), params)


def append_log(request_id: int, line: str) -> None:
    with engine.begin() as c:
        c.execute(text("""
            UPDATE report_requests
            SET agent_log = COALESCE(agent_log, '') || :ln, updated_at = NOW()
            WHERE id = :id
        """), {"id": request_id, "ln": f"{line}\n"})
