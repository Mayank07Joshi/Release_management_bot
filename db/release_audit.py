"""
db/release_audit.py
────────────────────
Data layer for the Release Audit page.

Options  → sourced from p_releases (seeded by scripts/seed_releases.py).
Metrics  → enhancements by ado_label tag; bugs by created_date window.
Trend    → one row per release from p_releases, all with date windows.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text

from data.loader import engine

log = logging.getLogger(__name__)

_CLOSED_STATES = frozenset({
    "Closed", "Not an issue", "Not Required",
    "Userstory Update", "No Customer Response", "Resolved",
})


# ── Options ───────────────────────────────────────────────────────────────────

def get_release_options() -> list[dict]:
    """
    Return releases from p_releases as dcc.Dropdown options.
    value = release_id (int), label = title.
    Falls back to distinct release_date tags if p_releases is empty.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT release_id, title, start_date, status
                FROM p_releases
                ORDER BY COALESCE(start_date, '1900-01-01') DESC
            """)).fetchall()

        if rows:
            return [
                {
                    "label": f"{r.title}{' ●' if r.status == 'In Progress' else ''}",
                    "value": r.release_id,
                }
                for r in rows
            ]
    except Exception as exc:
        log.warning("get_release_options p_releases: %s — falling back", exc)

    # Fallback: distinct release_date tags from work_items_main
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT release_date
                FROM work_items_main
                WHERE release_date IS NOT NULL AND release_date NOT IN ('', 'Not Specified')
                ORDER BY release_date
            """)).fetchall()
        return [{"label": r[0], "value": r[0]} for r in rows if r[0]]
    except Exception as exc2:
        log.error("get_release_options fallback: %s", exc2)
        return []


# ── Main audit data ───────────────────────────────────────────────────────────

def get_release_audit_data(release_key) -> dict:
    """
    Pull all metrics for a release.

    release_key — either an int (p_releases.release_id, preferred)
                  or a str (ado_label / release_date tag, legacy fallback).
    """
    today = date.today()
    try:
        with engine.connect() as conn:
            meta, data = _fetch(conn, release_key)
    except Exception as exc:
        log.error("get_release_audit_data(%s): %s", release_key, exc)
        meta = {"title": str(release_key), "start_date": None, "target_date": None}
        data = _empty()

    data.update({
        "release_title":  meta.get("title", str(release_key)),
        "release_start":  str(meta.get("start_date") or ""),
        "release_end":    str(meta.get("target_date") or ""),
        "generated":      today.strftime("%d %B %Y"),
    })
    return data


def _fetch(conn, key) -> tuple[dict, dict]:
    # ── Look up release metadata ───────────────────────────────────────────────
    if isinstance(key, int):
        row = conn.execute(text("""
            SELECT release_id, title, start_date, target_date, ado_label, ado_id
            FROM p_releases WHERE release_id = :id
        """), {"id": key}).fetchone()
    else:
        # Legacy: key is the ado_label string
        row = conn.execute(text("""
            SELECT release_id, title, start_date, target_date, ado_label, ado_id
            FROM p_releases WHERE ado_label = :lbl LIMIT 1
        """), {"lbl": key}).fetchone()

    if row:
        meta      = dict(row._mapping)
        ado_label = row.ado_label
        start     = row.start_date
        end       = row.target_date
    else:
        # No p_releases row — treat key as a raw ado_label tag
        meta      = {"title": str(key)}
        ado_label = str(key)
        start     = None
        end       = None

    # ── Fetch the NEXT release start date for bug window upper bound ───────────
    if start:
        nxt = conn.execute(text("""
            SELECT start_date FROM p_releases
            WHERE start_date > :s AND start_date IS NOT NULL
            ORDER BY start_date ASC LIMIT 1
        """), {"s": start}).scalar()
        window_end = nxt or date.today()
    else:
        window_end = date.today()

    # ── Enhancements — by ado_label tag ───────────────────────────────────────
    if ado_label:
        enh_rows = conn.execute(text("""
            SELECT work_item_id, state, priority, area, function
            FROM work_items_main
            WHERE work_item_type IN ('Enhancement', 'User Story')
              AND release_date = :lbl
        """), {"lbl": ado_label}).fetchall()
    else:
        enh_rows = []

    # ── Bugs — by created_date window (more accurate than tag) ────────────────
    if start:
        bug_rows = conn.execute(text("""
            SELECT work_item_id, work_item_type, state, priority, area, stage
            FROM work_items_main
            WHERE work_item_type IN ('Bug', 'Bug_UI', 'Bug_Text')
              AND created_date >= :s
              AND created_date <  :e
        """), {"s": start, "e": window_end}).fetchall()
    elif ado_label:
        # Fallback: use tag
        bug_rows = conn.execute(text("""
            SELECT work_item_id, work_item_type, state, priority, area, stage
            FROM work_items_main
            WHERE work_item_type IN ('Bug', 'Bug_UI', 'Bug_Text')
              AND release_date = :lbl
        """), {"lbl": ado_label}).fetchall()
    else:
        bug_rows = []

    # ── Bugs Fixed — closed_date falls inside the release window ─────────────
    # closed_date is stored as text in PG — pass params as ISO strings to match
    if start:
        bugs_fixed_rows = conn.execute(text("""
            SELECT work_item_id, work_item_type, state, priority, area, stage
            FROM work_items_main
            WHERE work_item_type IN ('Bug', 'Bug_UI', 'Bug_Text')
              AND closed_date >= :s
              AND closed_date <  :e
              AND state IN ('Closed','Not an issue','Not Required',
                            'Userstory Update','No Customer Response','Resolved')
        """), {"s": str(start), "e": str(window_end)}).fetchall()
    elif ado_label:
        bugs_fixed_rows = conn.execute(text("""
            SELECT work_item_id, work_item_type, state, priority, area, stage
            FROM work_items_main
            WHERE work_item_type IN ('Bug', 'Bug_UI', 'Bug_Text')
              AND release_date = :lbl
              AND state IN ('Closed','Not an issue','Not Required',
                            'Userstory Update','No Customer Response','Resolved')
        """), {"lbl": ado_label}).fetchall()
    else:
        bugs_fixed_rows = []

    return meta, _crunch(enh_rows, bug_rows, bugs_fixed_rows)


def _crunch(enh_rows, bug_rows, bugs_fixed_rows=None) -> dict:
    # ── Enhancements ──────────────────────────────────────────────────────────
    enh_total  = len(enh_rows)
    enh_closed = sum(1 for r in enh_rows if (r.state or "") in _CLOSED_STATES)
    enh_open   = enh_total - enh_closed
    delivery_pct = round(enh_closed / enh_total * 100) if enh_total else 0

    enh_states   = {}
    enh_priority = {1: 0, 2: 0, 3: 0, 4: 0}
    enh_area     = {}
    enh_function = {}

    for r in enh_rows:
        st = r.state or "Unknown"
        enh_states[st] = enh_states.get(st, 0) + 1
        try:
            p = max(1, min(4, int(r.priority or 4)))
        except (ValueError, TypeError):
            p = 4
        enh_priority[p] += 1
        enh_area[r.area or "Unassigned"] = enh_area.get(r.area or "Unassigned", 0) + 1
        enh_function[r.function or "General"] = enh_function.get(r.function or "General", 0) + 1

    # ── Bugs ──────────────────────────────────────────────────────────────────
    bug_total  = len(bug_rows)
    bug_closed = sum(1 for r in bug_rows if (r.state or "") in _CLOSED_STATES)
    bug_open   = bug_total - bug_closed
    bug_close_pct = round(bug_closed / bug_total * 100) if bug_total else 0

    bug_priority = {1: 0, 2: 0, 3: 0, 4: 0}
    bug_area     = {}
    bug_stage    = {}
    bug_type     = {}
    bug_states   = {}
    p1_open      = 0

    for r in bug_rows:
        try:
            p = max(1, min(4, int(r.priority or 4)))
        except (ValueError, TypeError):
            p = 4
        bug_priority[p] += 1
        if p == 1 and (r.state or "") not in _CLOSED_STATES:
            p1_open += 1
        bug_area[r.area or "Unassigned"]  = bug_area.get(r.area or "Unassigned", 0) + 1
        bug_stage[r.stage or "Unassigned"] = bug_stage.get(r.stage or "Unassigned", 0) + 1
        t = r.work_item_type or "Bug"
        bug_type[t] = bug_type.get(t, 0) + 1
        st = r.state or "Unknown"
        bug_states[st] = bug_states.get(st, 0) + 1

    # ── Bugs Fixed ────────────────────────────────────────────────────────────
    fixed = bugs_fixed_rows or []
    bugs_fixed_total    = len(fixed)
    bugs_fixed_priority = {1: 0, 2: 0, 3: 0, 4: 0}
    bugs_fixed_area:  dict = {}
    bugs_fixed_stage: dict = {}
    bugs_fixed_type:  dict = {}

    for r in fixed:
        try:
            p = max(1, min(4, int(r.priority or 4)))
        except (ValueError, TypeError):
            p = 4
        bugs_fixed_priority[p] += 1
        bugs_fixed_area[r.area or "Unassigned"]  = bugs_fixed_area.get(r.area or "Unassigned", 0) + 1
        bugs_fixed_stage[r.stage or "Unassigned"] = bugs_fixed_stage.get(r.stage or "Unassigned", 0) + 1
        t = r.work_item_type or "Bug"
        bugs_fixed_type[t] = bugs_fixed_type.get(t, 0) + 1

    # ── Verdict ───────────────────────────────────────────────────────────────
    if enh_total == 0 and bug_total == 0:
        verdict = "UNKNOWN"
    elif p1_open > 0 or (enh_total > 0 and delivery_pct < 50):
        verdict = "RED"
    elif (enh_total > 0 and delivery_pct < 80) or bug_open > 5:
        verdict = "AMBER"
    else:
        verdict = "GREEN"

    return {
        "total_items":   enh_total + bug_total,
        "verdict":       verdict,
        "enh_total":     enh_total,
        "enh_closed":    enh_closed,
        "enh_open":      enh_open,
        "delivery_pct":  delivery_pct,
        "enh_states":    dict(sorted(enh_states.items(),   key=lambda x: -x[1])),
        "enh_priority":  enh_priority,
        "enh_area":      dict(sorted(enh_area.items(),     key=lambda x: -x[1])),
        "enh_function":  dict(sorted(enh_function.items(), key=lambda x: -x[1])),
        "bug_total":     bug_total,
        "bug_closed":    bug_closed,
        "bug_open":      bug_open,
        "bug_close_pct": bug_close_pct,
        "p1_open":       p1_open,
        "bug_priority":  bug_priority,
        "bug_area":      dict(sorted(bug_area.items(),   key=lambda x: -x[1])),
        "bug_stage":     dict(sorted(bug_stage.items(),  key=lambda x: -x[1])),
        "bug_type":      dict(sorted(bug_type.items(),   key=lambda x: -x[1])),
        "bug_states":    dict(sorted(bug_states.items(), key=lambda x: -x[1])),
        # Fixed
        "bugs_fixed_total":    bugs_fixed_total,
        "bugs_fixed_priority": bugs_fixed_priority,
        "bugs_fixed_area":     dict(sorted(bugs_fixed_area.items(),  key=lambda x: -x[1])),
        "bugs_fixed_stage":    dict(sorted(bugs_fixed_stage.items(), key=lambda x: -x[1])),
        "bugs_fixed_type":     dict(sorted(bugs_fixed_type.items(),  key=lambda x: -x[1])),
    }


# ── Trend data ────────────────────────────────────────────────────────────────

def get_release_trend() -> list[dict]:
    """
    Return one summary row per release in p_releases, ordered newest first.
    Used by the trend table on the audit page.
    """
    try:
        with engine.connect() as conn:
            releases = conn.execute(text("""
                SELECT release_id, title, start_date, target_date, ado_label, status
                FROM p_releases
                WHERE start_date IS NOT NULL
                ORDER BY start_date DESC
            """)).fetchall()

            if not releases:
                return []

            rows = []
            for i, r in enumerate(releases):
                # Bug window: this release start → next release start
                window_end = releases[i - 1].start_date if i > 0 else date.today()

                # Enhancement count by label
                enh_n = p1_n = p2_n = bug_n = 0

                if r.ado_label:
                    enh_n = conn.execute(text("""
                        SELECT COUNT(*) FROM work_items_main
                        WHERE work_item_type IN ('Enhancement', 'User Story')
                          AND release_date = :lbl
                    """), {"lbl": r.ado_label}).scalar() or 0

                    enh_closed = conn.execute(text("""
                        SELECT COUNT(*) FROM work_items_main
                        WHERE work_item_type IN ('Enhancement', 'User Story')
                          AND release_date = :lbl
                          AND state IN (
                              'Closed','Not an issue','Not Required',
                              'Userstory Update','No Customer Response','Resolved'
                          )
                    """), {"lbl": r.ado_label}).scalar() or 0
                else:
                    enh_closed = 0

                bug_row = conn.execute(text("""
                    SELECT
                        COUNT(*)                                        AS total,
                        COUNT(*) FILTER (WHERE priority::text = '1')   AS p1,
                        COUNT(*) FILTER (WHERE priority::text = '2')   AS p2
                    FROM work_items_main
                    WHERE work_item_type IN ('Bug', 'Bug_UI', 'Bug_Text')
                      AND created_date >= :s
                      AND created_date <  :e
                """), {"s": r.start_date, "e": window_end}).fetchone()

                bug_n = bug_row.total if bug_row else 0
                p1_n  = bug_row.p1    if bug_row else 0
                p2_n  = bug_row.p2    if bug_row else 0
                del_pct = round(enh_closed / enh_n * 100) if enh_n else None

                rows.append({
                    "release_id":  r.release_id,
                    "title":       r.title,
                    "start_date":  str(r.start_date),
                    "target_date": str(r.target_date) if r.target_date else "—",
                    "status":      r.status,
                    "enh_total":   enh_n,
                    "enh_closed":  enh_closed,
                    "delivery_pct": del_pct,
                    "bug_total":   bug_n,
                    "p1_bugs":     p1_n,
                    "p2_bugs":     p2_n,
                })
            return rows

    except Exception as exc:
        log.error("get_release_trend: %s", exc)
        return []


def _empty() -> dict:
    z4 = {1: 0, 2: 0, 3: 0, 4: 0}
    return {
        "total_items": 0, "verdict": "UNKNOWN",
        "enh_total": 0, "enh_closed": 0, "enh_open": 0, "delivery_pct": 0,
        "enh_states": {}, "enh_priority": dict(z4), "enh_area": {}, "enh_function": {},
        "bug_total": 0, "bug_closed": 0, "bug_open": 0, "bug_close_pct": 0,
        "p1_open": 0, "bug_priority": dict(z4),
        "bug_area": {}, "bug_stage": {}, "bug_type": {}, "bug_states": {},
        "bugs_fixed_total": 0, "bugs_fixed_priority": dict(z4),
        "bugs_fixed_area": {}, "bugs_fixed_stage": {}, "bugs_fixed_type": {},
    }
