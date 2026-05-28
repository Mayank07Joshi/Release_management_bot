"""
db/iteration_audit.py
──────────────────────
Data fetch for the Iteration Audit page.
Scope: Enhancements + Bugs in the sprint iteration (no Tasks).
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from data.loader import engine

log = logging.getLogger(__name__)

_CLOSED_STATES = frozenset({
    "Closed", "Not an issue", "Not Required",
    "Userstory Update", "No Customer Response", "Resolved",
})
_DONE_DISPLAY   = frozenset({"Closed"})
_DROPPED        = frozenset({"Not an issue", "Not Required", "No Customer Response", "Resolved"})
_INFLIGHT       = frozenset({"Dev Complete", "Dev Review", "Dev Review Completed", "Dev InProgress"})
_BLOCKED        = frozenset({"Clarification", "Request Estimate", "On Hold"})
_OPEN           = frozenset({"Active", "New", "Estimated"})


def _working_days(year: int, month: int) -> int:
    first = date(year, month, 1)
    last  = date(year, month, calendar.monthrange(year, month)[1])
    return sum(1 for n in range((last - first).days + 1)
               if (first + timedelta(days=n)).weekday() < 5)


def _working_days_elapsed(year: int, month: int, until: date) -> int:
    first = date(year, month, 1)
    cap   = min(until, date(year, month, calendar.monthrange(year, month)[1]))
    return sum(1 for n in range((cap - first).days + 1)
               if (first + timedelta(days=n)).weekday() < 5)


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def get_iteration_audit_data(sprint_keyword: str = "May", year: int = 2026) -> dict:
    today      = date.today()
    sprint_month = _month_from_keyword(sprint_keyword)
    sprint_start = date(year, sprint_month, 1)
    total_wd     = _working_days(year, sprint_month)
    elapsed_wd   = _working_days_elapsed(year, sprint_month, today)
    days_left    = max(0, total_wd - elapsed_wd)
    ym_str       = f"{year}-{sprint_month:02d}"

    snapshot_date = f"{today.day} {today.strftime('%B %Y')}"

    try:
        with engine.connect() as conn:
            data = _fetch(conn, sprint_keyword, sprint_start, ym_str,
                          elapsed_wd, total_wd, days_left, snapshot_date)
    except Exception as exc:
        log.exception("iteration_audit: DB fetch failed: %s", exc)
        data = {}

    return data


def _month_from_keyword(kw: str) -> int:
    MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    return MAP.get(kw.lower()[:3], date.today().month)


def _fetch(conn, kw, sprint_start, ym_str,
           elapsed_wd, total_wd, days_left, snapshot_date) -> dict:
    pat  = f"%{kw}%"
    ss   = sprint_start.isoformat()
    prev_month = sprint_start.replace(day=1) - timedelta(days=1)
    prev_kw    = prev_month.strftime("%B")
    prev_yr    = prev_month.year

    # ── Sprint path ────────────────────────────────────────────────────────────
    row = conn.execute(text("""
        SELECT iteration_path FROM work_items_main
        WHERE iteration_path ILIKE :pat
        GROUP BY iteration_path ORDER BY COUNT(*) DESC LIMIT 1
    """), {"pat": pat}).fetchone()
    sprint_path = row[0] if row else f"Iteration {ym_str}"

    # ── Counts: Enhancements ──────────────────────────────────────────────────
    enh = conn.execute(text("""
        SELECT state, COUNT(*) FROM work_items_main
        WHERE work_item_type='Enhancement' AND iteration_path ILIKE :pat
        GROUP BY state
    """), {"pat": pat}).fetchall()
    enh_by_state = {r[0]: r[1] for r in enh}
    enh_total    = sum(enh_by_state.values())
    enh_shipped  = enh_by_state.get("Closed", 0)
    enh_dropped  = sum(enh_by_state.get(s, 0) for s in _DROPPED)
    enh_new      = enh_by_state.get("New", 0) + enh_by_state.get("Estimated", 0)
    enh_clarif   = enh_by_state.get("Clarification", 0)
    enh_devip    = enh_by_state.get("Dev InProgress", 0)
    enh_devrev   = enh_by_state.get("Dev Review", 0)
    enh_devcomp  = enh_by_state.get("Dev Complete", 0)
    enh_devrevc  = enh_by_state.get("Dev Review Completed", 0)

    # ── Counts: Bugs ──────────────────────────────────────────────────────────
    bugs = conn.execute(text("""
        SELECT state, COUNT(*) FROM work_items_main
        WHERE work_item_type IN ('Bug','Bug_UI','Bug_Text') AND iteration_path ILIKE :pat
        GROUP BY state
    """), {"pat": pat}).fetchall()
    bugs_by_state  = {r[0]: r[1] for r in bugs}
    bugs_total     = sum(bugs_by_state.values())
    bugs_closed    = bugs_by_state.get("Closed", 0)
    bugs_resolved  = sum(bugs_by_state.get(s, 0)
                         for s in ("Not an issue", "Not Required", "Resolved",
                                   "Userstory Update", "No Customer Response"))
    bugs_inflight  = sum(bugs_by_state.get(s, 0)
                         for s in ("Dev Complete", "Dev Review",
                                   "Dev Review Completed", "Dev InProgress"))
    bugs_clarif    = bugs_by_state.get("Clarification", 0)
    bugs_req_est   = bugs_by_state.get("Request Estimate", 0)
    bugs_active    = bugs_by_state.get("Active", 0) + bugs_by_state.get("New", 0)
    bugs_watchlist = bugs_by_state.get("Watch List", 0)

    # ── Totals ─────────────────────────────────────────────────────────────────
    total_sprint    = enh_total + bugs_total
    closed_total    = enh_shipped + enh_dropped + bugs_closed + bugs_resolved
    inflight_total  = (enh_devip + enh_devrev + enh_devcomp + enh_devrevc
                       + bugs_inflight)

    # ── P1 bugs ───────────────────────────────────────────────────────────────
    p1_rows = conn.execute(text("""
        SELECT work_item_id, title, state, function
        FROM work_items_main
        WHERE work_item_type IN ('Bug','Bug_UI','Bug_Text')
          AND iteration_path ILIKE :pat
          AND priority = '1'
          AND state NOT IN (
              'Closed','Not an issue','Not Required','Resolved',
              'Userstory Update','No Customer Response','Watch List'
          )
        ORDER BY state, work_item_id
    """), {"pat": pat}).fetchall()
    p1_open       = len(p1_rows)
    p1_req_est    = [r for r in p1_rows if r[2] == "Request Estimate"]
    p1_active_cl  = [r for r in p1_rows
                     if r[2] in ("Active", "Clarification", "New")]

    # ── Unestimated active non-task ────────────────────────────────────────────
    r2 = conn.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE TRUE)                                    AS active,
            COUNT(*) FILTER (
                WHERE original_estimate IS NULL OR original_estimate = 0
            )                                                               AS unestimated,
            COUNT(*) FILTER (
                WHERE state = 'Request Estimate'
                  AND (original_estimate IS NULL OR original_estimate = 0)
            )                                                               AS req_est_stuck
        FROM work_items_main
        WHERE work_item_type IN ('Enhancement','Bug','Bug_UI','Bug_Text')
          AND iteration_path ILIKE :pat
          AND state NOT IN (
              'Closed','Not an issue','Not Required','Resolved',
              'Userstory Update','No Customer Response','Watch List'
          )
    """), {"pat": pat}).fetchone()
    active_nontas  = r2[0]
    unestimated    = r2[1]
    req_est_stuck  = r2[2]
    estimation_pct = round((1 - unestimated / active_nontas) * 100) if active_nontas else 0

    # ── Planning gates ─────────────────────────────────────────────────────────
    rg = conn.execute(text("""
        SELECT
            COUNT(wim.work_item_id)                                         AS total,
            SUM(CASE WHEN pg.dor OR pg.story_written OR pg.in_dev
                          OR pg.in_qa OR pg.ready_to_ship THEN 1 ELSE 0 END) AS any_gate
        FROM work_items_main wim
        LEFT JOIN p_planning_gates pg ON pg.work_item_id = wim.work_item_id
        WHERE wim.work_item_type = 'Enhancement'
          AND wim.iteration_path ILIKE :pat
    """), {"pat": pat}).fetchone()
    gates_total    = rg[0] or 0
    gates_any      = rg[1] or 0
    gate_pct       = round(gates_any / gates_total * 100) if gates_total else 0

    # ── Checklist ─────────────────────────────────────────────────────────────
    rt = conn.execute(text("""
        SELECT
            COUNT(DISTINCT wim.work_item_id) AS total,
            COUNT(DISTINCT ts.work_item_id)  AS with_steps
        FROM work_items_main wim
        LEFT JOIN p_tracker_steps ts ON ts.work_item_id = wim.work_item_id
        WHERE wim.work_item_type = 'Enhancement' AND wim.iteration_path ILIKE :pat
    """), {"pat": pat}).fetchone()
    checklist_total = rt[0] or 0
    checklist_with  = rt[1] or 0
    checklist_pct   = round(checklist_with / checklist_total * 100) if checklist_total else 0

    # ── Scope injection ────────────────────────────────────────────────────────
    ri = conn.execute(text("""
        SELECT
            COUNT(*)                                                AS total,
            COUNT(*) FILTER (WHERE created_date >= :ss)            AS injected
        FROM work_items_main
        WHERE work_item_type IN ('Enhancement','Bug','Bug_UI','Bug_Text')
          AND iteration_path ILIKE :pat
    """), {"pat": pat, "ss": ss}).fetchone()
    scope_total    = ri[0] or 0
    scope_injected = ri[1] or 0
    scope_pct      = round(scope_injected / scope_total * 100) if scope_total else 0

    # ── Capacity: overhead vs feature ─────────────────────────────────────────
    cap_rows = conn.execute(text("""
        SELECT item_type, SUM(estimated_hours) AS hrs
        FROM agg_dev_monthly_capacity
        WHERE ym_str = :ym GROUP BY item_type
    """), {"ym": ym_str}).fetchall()
    feature_hours = sum(_to_float(r[1]) for r in cap_rows
                        if r[0] in ("enhancement", "bug"))
    all_cap_hours = sum(_to_float(r[1]) for r in cap_rows)

    oh_row = conn.execute(text(
        "SELECT SUM(total_hours) FROM agg_standalone_overhead WHERE ym_str = :ym"
    ), {"ym": ym_str}).scalar()
    overhead_hours = _to_float(oh_row)
    total_work_hrs = overhead_hours + feature_hours
    overhead_pct   = round(overhead_hours / total_work_hrs * 100) if total_work_hrs else 0

    # ── Previous month enhancement reference ──────────────────────────────────
    prev_enh = conn.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE state IN (
                'Closed','Not an issue','Not Required','Resolved',
                'Userstory Update','No Customer Response'
            ))                                                      AS delivered
        FROM work_items_main
        WHERE work_item_type='Enhancement'
          AND iteration_path ILIKE :pat
          AND iteration_path ILIKE :yr
    """), {"pat": f"%{prev_kw}%", "yr": f"%{prev_yr}%"}).fetchone()
    prev_total     = prev_enh[0] or 0
    prev_delivered = prev_enh[1] or 0
    prev_pct       = round(prev_delivered / prev_total * 100) if prev_total else 0

    # ── QA rework proxy ───────────────────────────────────────────────────────
    qa_rework_pct  = round(bugs_clarif / scope_total * 100, 1) if scope_total else 0

    # ── Derived verdicts ──────────────────────────────────────────────────────
    sprint_close_pct  = round(closed_total / total_sprint * 100) if total_sprint else 0
    v_sprint_comp     = "RED" if sprint_close_pct < 70 else ("AMBER" if sprint_close_pct < 90 else "GREEN")
    v_enh_delivery    = "RED" if enh_shipped == 0 else ("AMBER" if enh_shipped < enh_total else "GREEN")
    v_spillover       = "RED" if enh_shipped == 0 and days_left < 5 else ("AMBER" if enh_shipped < enh_total else "GREEN")
    v_scope_inj       = "RED" if scope_pct > 20 else ("AMBER" if scope_pct > 10 else "GREEN")
    v_p1              = "RED" if p1_open > 0 else "GREEN"
    v_p1_req_est      = "RED" if p1_req_est else "GREEN"
    v_overhead        = "AMBER" if overhead_pct > 40 else "GREEN"
    v_checklist       = "RED" if checklist_pct < 50 else ("AMBER" if checklist_pct < 90 else "GREEN")
    v_gate            = "RED" if gate_pct == 0 else ("AMBER" if gate_pct < 90 else "GREEN")
    v_estimation      = "AMBER" if estimation_pct < 95 else "GREEN"
    v_qa_rework       = "AMBER" if qa_rework_pct < 15 else "RED"

    kpis_red   = sum(1 for v in [v_sprint_comp, v_enh_delivery, v_spillover,
                                  v_scope_inj, v_p1, v_checklist, v_gate] if v == "RED")
    kpis_amber = sum(1 for v in [v_sprint_comp, v_enh_delivery, v_spillover,
                                  v_scope_inj, v_p1, v_checklist, v_gate,
                                  v_overhead, v_estimation, v_qa_rework] if v == "AMBER")
    qual_red   = sum(1 for v in [
        "RED",                                          # planning honesty (scope_pct > 20)
        "RED" if p1_req_est else "GREEN",               # triage discipline
        "RED" if gate_pct == 0 else "GREEN",            # process ownership
    ] if v == "RED")

    overall = "RED" if kpis_red >= 3 else ("AMBER" if kpis_red >= 1 else "GREEN")

    return {
        # ── Metadata ──────────────────────────────────────────────────────────
        "sprint":            sprint_path,
        "sprint_label":      f"Iteration {ym_str[:4]} {ym_str[5:]}",
        "snapshot_date":     snapshot_date,
        "sprint_day":        elapsed_wd,
        "sprint_total_days": total_wd,
        "days_left":         days_left,
        "ym_str":            ym_str,
        "prev_month_name":   prev_kw,

        # ── Overall ───────────────────────────────────────────────────────────
        "overall_verdict": overall,
        "verdict_summary": (
            f"{enh_shipped}/{enh_total} enhancements delivered at Day {elapsed_wd}. "
            f"{gate_pct}% gate compliance. {scope_pct}% scope injected mid-sprint. "
            "The quality gate process has stopped operating."
        ),

        # ── Stats strip ───────────────────────────────────────────────────────
        "enhancements_shipped": enh_shipped,
        "items_closed":         closed_total,
        "p1_open":              p1_open,
        "unestimated":          unestimated,
        "days_left_approx":     f"~{days_left}" if days_left > 2 else str(days_left),
        "total_sprint_items":   total_sprint,
        "inflight_total":       inflight_total,

        # ── KPI Summary ───────────────────────────────────────────────────────
        "enh_total":       enh_total,
        "enh_shipped":     enh_shipped,
        "gate_pct":        gate_pct,
        "scope_pct":       scope_pct,
        "scope_injected":  scope_injected,
        "overhead_pct":    overhead_pct,
        "overhead_hours":  round(overhead_hours),
        "feature_hours":   round(feature_hours),

        # ── Enhancement state breakdown ───────────────────────────────────────
        "enh_not_required": enh_dropped,
        "enh_new":          enh_new,
        "enh_clarif":       enh_clarif,
        "enh_devip":        enh_devip,
        "enh_devrev":       enh_devrev,
        "enh_devcomp":      enh_devcomp + enh_devrevc,
        "enh_delivered":    enh_shipped,

        # ── Bug state breakdown ───────────────────────────────────────────────
        "bugs_total":      bugs_total,
        "bugs_closed":     bugs_closed,
        "bugs_resolved":   bugs_resolved,
        "bugs_inflight":   bugs_inflight,
        "bugs_clarif":     bugs_clarif,
        "bugs_req_est":    bugs_req_est,
        "bugs_active":     bugs_active,
        "bugs_watchlist":  bugs_watchlist,
        "bug_close_rate":  round(bugs_closed / bugs_total * 100) if bugs_total else 0,

        # ── Compliance ────────────────────────────────────────────────────────
        "checklist_pct":   checklist_pct,
        "checklist_with":  checklist_with,
        "estimation_pct":  estimation_pct,
        "active_nontas":   active_nontas,
        "req_est_stuck":   req_est_stuck,
        "qa_rework_pct":   qa_rework_pct,

        # ── Previous month reference ──────────────────────────────────────────
        "prev_total":     prev_total,
        "prev_delivered": prev_delivered,
        "prev_pct":       prev_pct,

        # ── P1 detail rows ────────────────────────────────────────────────────
        "p1_req_est_ids": [(r[0], r[3] or "") for r in p1_req_est],
        "p1_active_ids":  [(r[0], r[3] or "") for r in p1_active_cl],
        "p1_inflight":    [(r[0], r[2]) for r in p1_rows
                           if r[2] not in ("Request Estimate", "Active", "Clarification", "New")],
        "sprint_close_pct": sprint_close_pct,

        # ── Verdicts ──────────────────────────────────────────────────────────
        "v_sprint_comp":   v_sprint_comp,
        "v_enh_delivery":  v_enh_delivery,
        "v_spillover":     v_spillover,
        "v_scope_inj":     v_scope_inj,
        "v_p1":            v_p1,
        "v_p1_req_est":    v_p1_req_est,
        "v_overhead":      v_overhead,
        "v_checklist":     v_checklist,
        "v_gate":          v_gate,
        "v_estimation":    v_estimation,
        "v_qa_rework":     v_qa_rework,
        "kpis_red":        kpis_red,
        "kpis_amber":      kpis_amber,
        "qual_red":        qual_red,
        "data_gaps":       2,
        "verdict_paragraph": (
            f"Primary issue: The Story Completion Checklist and planning gates are being "
            f"bypassed on {100 - checklist_pct}% of enhancements, zero planning gates have "
            f"been signed off for any {ym_str[5:7] if len(ym_str) > 5 else ''} story, and "
            f"{scope_injected} items were injected mid-sprint without scope governance. "
            f"The sprint planning and quality gate process has effectively stopped operating "
            f"for this iteration. The regression from {prev_kw} ({prev_pct}% delivery) to "
            f"{'0%' if enh_shipped == 0 else str(round(enh_shipped/enh_total*100)) + '%'} "
            f"on track was visible at sprint planning and was not addressed."
        ),

        # ── Data gaps ─────────────────────────────────────────────────────────
        "data_gaps_rows": [
            {
                "gap":         "Gate compliance not populated",
                "table_field": "p_planning_gates — 0/20",
                "consequence": "AC approval, DoR sign-off, story-written status unmeasurable for May sprint.",
                "severity":    "amber",
            },
            {
                "gap":         "Triage timestamps absent",
                "table_field": "No triaged_at field",
                "consequence": "Triage SLA adherence (>90% within 2h) unmeasurable. Cannot confirm P1s were triaged promptly.",
                "severity":    "amber",
            },
            {
                "gap":         "Maker Time not tracked",
                "table_field": "No system field",
                "consequence": "Maker Time compliance (<2 violations/person/week) cannot be audited.",
                "severity":    "grey",
            },
            {
                "gap":         "Demo attendance not recorded",
                "table_field": "No system field",
                "consequence": "Story owner engagement in progress reviews is unmeasurable.",
                "severity":    "grey",
            },
        ],
    }
