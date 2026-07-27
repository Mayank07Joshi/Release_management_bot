"""
Seed p_planning_gates with dummy data for Planning tab visualisation testing.
No ADO writes. Local DB only. Safe to re-run.
"""

import random
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from data.loader import engine
from sqlalchemy import text

GATES = ["claude_screens", "text_written", "our_screens", "html_screens", "sn_signoff"]

_MONTH_ORDER = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}

# Current: 2026-07
_NOW_YEAR, _NOW_MONTH = 2026, 7

def _months_away(release_label: str) -> int:
    if not release_label:
        return 18
    parts = release_label.split()
    try:
        year = int(parts[0])
        month = _MONTH_ORDER.get(parts[1], 6)
        return (year - _NOW_YEAR) * 12 + (month - _NOW_MONTH)
    except Exception:
        return 18


# weights[0..5] = probability of that many gates being done
# keyed by (months_away bucket, priority)
_WEIGHTS = {
    # imminent (0-2 months): most stories should be well along
    "near_p1": [0.05, 0.05, 0.10, 0.20, 0.25, 0.35],
    "near_p2": [0.10, 0.10, 0.15, 0.20, 0.25, 0.20],
    "near_p3": [0.20, 0.15, 0.20, 0.20, 0.15, 0.10],
    # mid (3-6 months): mix of started/in-progress
    "mid_p1":  [0.15, 0.15, 0.20, 0.20, 0.20, 0.10],
    "mid_p2":  [0.25, 0.20, 0.20, 0.15, 0.12, 0.08],
    "mid_p3":  [0.35, 0.25, 0.18, 0.12, 0.07, 0.03],
    # far (7+ months): mostly not started
    "far_p1":  [0.35, 0.25, 0.20, 0.10, 0.07, 0.03],
    "far_p2":  [0.55, 0.20, 0.12, 0.07, 0.04, 0.02],
    "far_p3":  [0.70, 0.15, 0.08, 0.04, 0.02, 0.01],
}

def _pick_gates(months: int, priority: int, rng: random.Random) -> tuple[int, bool]:
    bucket = "near" if months <= 2 else "mid" if months <= 6 else "far"
    p_str  = "p1" if priority == 1 else "p2" if priority == 2 else "p3"
    key    = f"{bucket}_{p_str}"
    weights = _WEIGHTS[key]
    gates_done = rng.choices(range(6), weights=weights, k=1)[0]
    # WIP on the next gate (only if not all done and not zero)
    has_wip = gates_done < 5 and rng.random() < 0.4
    return gates_done, has_wip


def main():
    rng = random.Random(42)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT w.work_item_id,
                   COALESCE(NULLIF(TRIM(w.release_date), ''), '') AS release_label,
                   COALESCE(NULLIF(TRIM(w.priority::TEXT), ''), '3') AS priority
            FROM work_items_main w
            WHERE w.work_item_type = 'Enhancement'
              AND w.state NOT IN (
                  'Done','Closed','Not an issue','Not Required',
                  'Userstory Update','No Customer Response','Resolved','Not Specified'
              )
              AND (
                  w.release_date   ~ '^202[6-9] [A-Za-z]'
                  OR w.iteration_path ~ 'Iteration 202[6-9]'
              )
        """)).fetchall()

    print(f"Active stories found: {len(rows)}")

    upserts = []
    for r in rows:
        try:
            pri = int(r.priority)
        except Exception:
            pri = 3
        months = _months_away(r.release_label)
        gates_done, has_wip = _pick_gates(months, pri, rng)

        row = {"work_item_id": r.work_item_id}
        for i, g in enumerate(GATES):
            row[g]          = i < gates_done
            row[g + "_wip"] = (i == gates_done) and has_wip
        upserts.append(row)

    done_all    = sum(1 for r in upserts if all(r[g] for g in GATES))
    in_prog     = sum(1 for r in upserts if any(r[g] for g in GATES) and not all(r[g] for g in GATES))
    not_started = sum(1 for r in upserts if not any(r[g] for g in GATES))
    print(f"  All 5 done : {done_all}")
    print(f"  In progress: {in_prog}")
    print(f"  Not started: {not_started}")

    upsert_sql = text("""
        INSERT INTO p_planning_gates (
            work_item_id,
            claude_screens, text_written, our_screens, html_screens, sn_signoff,
            claude_screens_wip, text_written_wip, our_screens_wip,
            html_screens_wip, sn_signoff_wip
        ) VALUES (
            :work_item_id,
            :claude_screens, :text_written, :our_screens, :html_screens, :sn_signoff,
            :claude_screens_wip, :text_written_wip, :our_screens_wip,
            :html_screens_wip, :sn_signoff_wip
        )
        ON CONFLICT (work_item_id) DO UPDATE SET
            claude_screens     = EXCLUDED.claude_screens,
            text_written       = EXCLUDED.text_written,
            our_screens        = EXCLUDED.our_screens,
            html_screens       = EXCLUDED.html_screens,
            sn_signoff         = EXCLUDED.sn_signoff,
            claude_screens_wip = EXCLUDED.claude_screens_wip,
            text_written_wip   = EXCLUDED.text_written_wip,
            our_screens_wip    = EXCLUDED.our_screens_wip,
            html_screens_wip   = EXCLUDED.html_screens_wip,
            sn_signoff_wip     = EXCLUDED.sn_signoff_wip
    """)

    with engine.begin() as conn:
        for row in upserts:
            conn.execute(upsert_sql, row)

    print("Done — p_planning_gates seeded.")


if __name__ == "__main__":
    main()
