"""
scripts/seed_releases.py
─────────────────────────
One-time script: adds start_date + ado_label columns to p_releases,
then inserts all known release epics from the CSV shared on 2026-07-21.

Run once:
    python scripts/seed_releases.py

Safe to re-run — uses ON CONFLICT (ado_id) DO UPDATE.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from data.loader import engine

# ── Release data (from "Release Epics.csv") ──────────────────────────────────
# (title, ado_epic_id, start_date, target_date, status, ado_label)
# ado_label = the release_date tag used on work items (best guess; NULL if uncertain)
# Sorted chronologically by start_date → REL-001 ... REL-018
_RELEASES: list[tuple] = [
    (
        "2025 June Release",
        34864,
        date(2025, 6, 2), date(2025, 6, 25),
        "Released", "2025 June",
    ),
    (
        "2025 July Release",
        35112,
        date(2025, 6, 27), date(2025, 7, 29),
        "Released", "2025 July",
    ),
    (
        "2025 July 2nd Release",
        35496,
        date(2025, 7, 21), date(2025, 8, 22),
        "Released", None,       # tag uncertain — update after checking ADO
    ),
    (
        "2025 September Release",
        35830,
        date(2025, 8, 25), date(2025, 9, 30),
        "Released", "2025 September",
    ),
    (
        "2025 September Hotfix Release",
        36447,
        date(2025, 9, 1), date(2025, 10, 6),
        "Released", None,
    ),
    (
        "2025 October Release",
        36528,
        date(2025, 9, 10), date(2025, 11, 3),
        "Released", "2025 October",
    ),
    (
        "2025 November Release",
        37141,
        date(2025, 11, 14), date(2025, 12, 9),
        "Released", "2025 November",
    ),
    (
        "2025 December + January Release",
        37839,
        date(2025, 12, 10), None,
        "Released", None,
    ),
    (
        "2026 Jan 2 Release",
        38551,
        date(2026, 1, 16), date(2026, 2, 27),
        "Released", None,
    ),
    (
        "2026 January Hotfix Release",
        38552,
        date(2026, 1, 30), date(2026, 3, 3),
        "Released", None,
    ),
    (
        "2026 Jan 3 Release",
        38553,
        date(2026, 2, 2), date(2026, 2, 23),
        "Released", None,
    ),
    (
        "2026 February Hotfix Release",
        39016,
        date(2026, 2, 23), date(2026, 3, 9),
        "Released", None,
    ),
    (
        "2026 March Release",
        39015,
        date(2026, 3, 2), date(2026, 3, 25),
        "Released", "2026 March",
    ),
    (
        "2026 April Release",
        39910,
        date(2026, 4, 1), date(2026, 3, 23),  # target < start in ADO — kept as-is
        "Released", "2026 April",
    ),
    (
        "2026 May Release",
        40558,
        date(2026, 5, 1), date(2026, 5, 21),
        "Released", "2026 May",
    ),
    (
        "2026 June Release",
        42118,
        date(2026, 6, 1), date(2026, 6, 30),
        "Released", "2026 June",
    ),
    (
        "2026 July Release",
        42124,
        date(2026, 7, 1), date(2026, 7, 20),
        "Released", "2026 July",
    ),
    (
        "2026 July Onboarding Release",
        42836,
        date(2026, 7, 21), None,
        "In Progress", None,
    ),
]


def _add_columns(conn) -> None:
    """Add new columns to p_releases if they don't exist yet."""
    for ddl in [
        "ALTER TABLE p_releases ADD COLUMN IF NOT EXISTS start_date DATE",
        "ALTER TABLE p_releases ADD COLUMN IF NOT EXISTS ado_label TEXT",
        "ALTER TABLE p_releases ADD COLUMN IF NOT EXISTS actual_deploy_date DATE",
    ]:
        conn.execute(text(ddl))
    conn.commit()
    print("  columns: start_date, ado_label, actual_deploy_date ensured.")


def _insert_releases(conn) -> None:
    # Build a temporary unique constraint on ado_id for upsert
    # (ado_id is nullable in the schema so we work around with a SELECT guard)
    inserted = updated = 0
    for seq, (title, ado_id, start, target, status, label) in enumerate(_RELEASES, 1):
        ref = f"REL-{seq:03d}"
        result = conn.execute(text("""
            INSERT INTO p_releases
                (release_ref, title, start_date, target_date, status, ado_id, ado_label)
            VALUES
                (:ref, :title, :start, :target, :status, :ado_id, :label)
            ON CONFLICT (release_ref) DO UPDATE
               SET title       = EXCLUDED.title,
                   start_date  = EXCLUDED.start_date,
                   target_date = EXCLUDED.target_date,
                   status      = EXCLUDED.status,
                   ado_id      = EXCLUDED.ado_id,
                   ado_label   = EXCLUDED.ado_label,
                   updated_at  = NOW()
            RETURNING (xmax = 0) AS was_insert
        """), {"ref": ref, "title": title, "start": start, "target": target,
               "status": status, "ado_id": ado_id, "label": label})
        row = result.fetchone()
        if row and row[0]:
            print(f"  inserted {ref}  {title}")
            inserted += 1
        else:
            print(f"  updated  {ref}  {title}")
            updated += 1

    conn.execute(text("""
        UPDATE p_ref_counters SET last_seq = :n WHERE entity_type = 'release'
    """), {"n": len(_RELEASES)})
    conn.commit()
    print(f"  done — {inserted} inserted, {updated} updated.")


def main() -> None:
    print("seed_releases: connecting …")
    with engine.connect() as conn:
        print("  adding columns …")
        _add_columns(conn)
        print("  seeding releases …")
        _insert_releases(conn)
    print("seed_releases: complete.")


if __name__ == "__main__":
    main()
