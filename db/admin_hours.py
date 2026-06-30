"""DB layer for admin hours per developer per sprint."""
from sqlalchemy import text
from data.loader import engine


def init_admin_hours_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS p_admin_hours (
                id          SERIAL PRIMARY KEY,
                developer   TEXT NOT NULL,
                sprint_key  TEXT NOT NULL,
                meetings    NUMERIC(5,1) NOT NULL DEFAULT 0,
                ceremonies  NUMERIC(5,1) NOT NULL DEFAULT 0,
                support     NUMERIC(5,1) NOT NULL DEFAULT 0,
                code_review NUMERIC(5,1) NOT NULL DEFAULT 0,
                interviews  NUMERIC(5,1) NOT NULL DEFAULT 0,
                training    NUMERIC(5,1) NOT NULL DEFAULT 0,
                other       NUMERIC(5,1) NOT NULL DEFAULT 0,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (developer, sprint_key)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS p_admin_sprint_config (
                sprint_key TEXT PRIMARY KEY,
                capacity_h NUMERIC(5,1) NOT NULL DEFAULT 180,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))


def get_admin_hours(sprint_key: str) -> dict[str, dict]:
    """Returns {developer: {col: float}} for all rows in the sprint."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT developer, meetings, ceremonies, support,
                   code_review, interviews, training, other
            FROM p_admin_hours
            WHERE sprint_key = :sk
        """), {"sk": sprint_key}).fetchall()
    return {
        r.developer: {
            "meetings":    float(r.meetings),
            "ceremonies":  float(r.ceremonies),
            "support":     float(r.support),
            "code_review": float(r.code_review),
            "interviews":  float(r.interviews),
            "training":    float(r.training),
            "other":       float(r.other),
        }
        for r in rows
    }


def upsert_admin_row(developer: str, sprint_key: str,
                     meetings: float, ceremonies: float, support: float,
                     code_review: float, interviews: float,
                     training: float, other: float) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_admin_hours
                (developer, sprint_key, meetings, ceremonies, support,
                 code_review, interviews, training, other, updated_at)
            VALUES
                (:dev, :sk, :meetings, :ceremonies, :support,
                 :code_review, :interviews, :training, :other, NOW())
            ON CONFLICT (developer, sprint_key) DO UPDATE SET
                meetings    = EXCLUDED.meetings,
                ceremonies  = EXCLUDED.ceremonies,
                support     = EXCLUDED.support,
                code_review = EXCLUDED.code_review,
                interviews  = EXCLUDED.interviews,
                training    = EXCLUDED.training,
                other       = EXCLUDED.other,
                updated_at  = NOW()
        """), {
            "dev": developer, "sk": sprint_key,
            "meetings": meetings, "ceremonies": ceremonies, "support": support,
            "code_review": code_review, "interviews": interviews,
            "training": training, "other": other,
        })


def get_sprint_capacity(sprint_key: str) -> float:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT capacity_h FROM p_admin_sprint_config WHERE sprint_key = :sk
        """), {"sk": sprint_key}).fetchone()
    return float(row.capacity_h) if row else 180.0


def set_sprint_capacity(sprint_key: str, capacity_h: float) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_admin_sprint_config (sprint_key, capacity_h)
            VALUES (:sk, :cap)
            ON CONFLICT (sprint_key) DO UPDATE SET
                capacity_h = EXCLUDED.capacity_h,
                updated_at = NOW()
        """), {"sk": sprint_key, "cap": capacity_h})
