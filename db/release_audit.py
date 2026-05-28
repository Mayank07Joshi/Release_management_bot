"""
db/release_audit.py
────────────────────
Single data-fetch function for the Release Audit page.
Returns a plain dict — layout code never touches the DB directly.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import text

from data.loader import engine

log = logging.getLogger(__name__)

# ── Closed / terminal state sets ──────────────────────────────────────────────
_CLOSED = frozenset({
    "Closed", "Not an issue", "Not Required",
    "Userstory Update", "No Customer Response", "Resolved",
})
_NON_TASK_TYPES = frozenset({"Enhancement", "Bug", "Bug_UI", "Bug_Text", "User Story"})


def _rag(value, thresholds: dict) -> str:
    """
    Map a numeric value to RED / AMBER / GREEN using caller-supplied thresholds.
    thresholds = {"red": <max>, "amber": <max>}  (anything above amber = GREEN)
    """
    if value is None:
        return "UNKNOWN"
    if value <= thresholds.get("red", -1):
        return "RED"
    if value <= thresholds.get("amber", -1):
        return "AMBER"
    return "GREEN"


def get_release_audit_data(sprint_keyword: str = "May") -> dict:
    """
    Pull all metrics needed for the Release Audit page.

    sprint_keyword — matched against iteration_path with ILIKE '%<keyword>%'.
    Default: current calendar month name.

    Returns a flat dict.  All numeric values are Python int/float.
    Missing data is signalled by verdict="UNKNOWN" and value=None.
    """
    today = date.today()
    if sprint_keyword == "May":
        sprint_start = date(2026, 5, 1)
    else:
        # Generic: first day of the month whose name matches the keyword
        sprint_start = today.replace(day=1)

    generated = f"{today.day} {today.strftime('%B %Y')}"

    try:
        with engine.connect() as conn:
            data = _fetch(conn, sprint_keyword, sprint_start)
    except Exception as exc:
        log.error("release_audit: DB fetch failed: %s", exc)
        data = _empty_data()

    data["generated"] = generated
    data["report_month"] = sprint_keyword
    data["report_year"] = str(sprint_start.year)
    return data


def _fetch(conn, sprint_kw: str, sprint_start: date) -> dict:
    pat = f"%{sprint_kw}%"
    ss  = sprint_start.isoformat()

    # ── Sprint path ────────────────────────────────────────────────────────────
    row = conn.execute(text("""
        SELECT iteration_path FROM work_items_main
        WHERE iteration_path ILIKE :pat
        GROUP BY iteration_path ORDER BY COUNT(*) DESC LIMIT 1
    """), {"pat": pat}).fetchone()
    sprint_path = row[0] if row else f"Iteration {sprint_kw}"

    # ── Releases ───────────────────────────────────────────────────────────────
    releases_completed = conn.execute(text(
        "SELECT COUNT(*) FROM p_releases WHERE status = 'Completed'"
    )).scalar() or 0

    # ── Bugs ──────────────────────────────────────────────────────────────────
    defects_logged = conn.execute(text("SELECT COUNT(*) FROM p_bugs")).scalar() or 0

    # ── Sprint items breakdown ─────────────────────────────────────────────────
    r = conn.execute(text("""
        SELECT
            COUNT(*)                                                        AS total,
            COUNT(*) FILTER (WHERE work_item_type != 'Task')                AS non_task,
            COUNT(*) FILTER (WHERE work_item_type = 'Enhancement')          AS enhancements,
            COUNT(*) FILTER (
                WHERE work_item_type != 'Task'
                  AND created_date >= :ss
            )                                                               AS injected,
            COUNT(*) FILTER (WHERE state = 'Clarification')                 AS clarification,
            COUNT(*) FILTER (WHERE state = 'Request Estimate')              AS request_estimate
        FROM work_items_main
        WHERE iteration_path ILIKE :pat
    """), {"pat": pat, "ss": ss}).fetchone()

    total_sprint        = r.total
    non_task_sprint     = r.non_task
    enhancement_count   = r.enhancements
    injected_count      = r.injected
    clarification_count = r.clarification
    request_est_count   = r.request_estimate

    scope_pct = round(injected_count / non_task_sprint * 100, 1) if non_task_sprint else None

    # ── Active unestimated (non-task, non-closed) ──────────────────────────────
    r2 = conn.execute(text("""
        SELECT
            COUNT(*)                                                        AS active_non_task,
            COUNT(*) FILTER (
                WHERE (original_estimate IS NULL OR original_estimate = 0)
            )                                                               AS unestimated
        FROM work_items_main
        WHERE iteration_path ILIKE :pat
          AND work_item_type != 'Task'
          AND state NOT IN (
              'Closed','Not an issue','Not Required',
              'Userstory Update','No Customer Response','Resolved','Watch List'
          )
    """), {"pat": pat}).fetchone()

    active_non_task = r2.active_non_task
    unestimated     = r2.unestimated
    vsts_pct = round((1 - unestimated / active_non_task) * 100, 1) if active_non_task else None

    # ── Planning gates for sprint enhancements ─────────────────────────────────
    rg = conn.execute(text("""
        SELECT
            COUNT(wim.work_item_id)                                         AS total,
            COUNT(pg.work_item_id)                                          AS have_row,
            SUM(CASE WHEN pg.dor            THEN 1 ELSE 0 END)              AS dor,
            SUM(CASE WHEN pg.story_written  THEN 1 ELSE 0 END)              AS story_written,
            SUM(CASE WHEN pg.in_dev         THEN 1 ELSE 0 END)              AS in_dev,
            SUM(CASE WHEN pg.in_qa          THEN 1 ELSE 0 END)              AS in_qa,
            SUM(CASE WHEN pg.ready_to_ship  THEN 1 ELSE 0 END)              AS ready_to_ship,
            SUM(CASE WHEN pg.delivery       THEN 1 ELSE 0 END)              AS delivery
        FROM work_items_main wim
        LEFT JOIN p_planning_gates pg ON pg.work_item_id = wim.work_item_id
        WHERE wim.work_item_type = 'Enhancement'
          AND wim.iteration_path ILIKE :pat
    """), {"pat": pat}).fetchone()

    gates_total       = rg.total or 0
    gates_have_row    = rg.have_row or 0
    gates_dor         = rg.dor or 0
    gates_story       = rg.story_written or 0
    any_gate_filled   = max(gates_dor, gates_story, rg.in_dev or 0,
                            rg.in_qa or 0, rg.ready_to_ship or 0, rg.delivery or 0)

    # ── Tracker steps (Story Completion Checklist) ─────────────────────────────
    rt = conn.execute(text("""
        SELECT
            COUNT(DISTINCT wim.work_item_id)                        AS total,
            COUNT(DISTINCT ts.work_item_id)                         AS have_steps,
            COUNT(ts.work_item_id)                                  AS step_rows,
            COUNT(ts.work_item_id) FILTER (WHERE ts.checked = TRUE) AS checked_steps
        FROM work_items_main wim
        LEFT JOIN p_tracker_steps ts ON ts.work_item_id = wim.work_item_id
        WHERE wim.work_item_type = 'Enhancement'
          AND wim.iteration_path ILIKE :pat
    """), {"pat": pat}).fetchone()

    tracker_total    = rt.total or 0
    tracker_with     = rt.have_steps or 0
    tracker_steps    = rt.step_rows or 0
    tracker_checked  = rt.checked_steps or 0
    checklist_pct    = round(tracker_with / tracker_total * 100) if tracker_total else 0

    # ── P1 bugs (open, non-closed) in sprint ───────────────────────────────────
    p1_open = conn.execute(text("""
        SELECT COUNT(*) FROM work_items_main
        WHERE work_item_type IN ('Bug','Bug_UI','Bug_Text')
          AND iteration_path ILIKE :pat
          AND priority = '1'
          AND state NOT IN (
              'Closed','Not an issue','Not Required',
              'Userstory Update','No Customer Response','Resolved','Watch List'
          )
    """), {"pat": pat}).scalar() or 0

    # ── QA rework (from item_state_history if populated) ──────────────────────
    ish_count = conn.execute(text("SELECT COUNT(*) FROM item_state_history")).scalar() or 0
    if ish_count > 0:
        rework_row = conn.execute(text("""
            SELECT COUNT(*) as rework_items, COALESCE(AVG(rework_cycles), 0) as avg_cycles
            FROM agg_qa_rework aqr
            JOIN work_items_main wim ON wim.work_item_id = aqr.work_item_id
            WHERE wim.iteration_path ILIKE :pat
        """), {"pat": pat}).fetchone()
        rework_items = rework_row[0] if rework_row else 0
        rework_rate  = round(rework_items / non_task_sprint * 100, 1) if non_task_sprint else None
        rework_source = "measured"
    else:
        rework_items = None
        rework_rate  = None
        rework_source = "no_history"

    # ── Derived verdicts ───────────────────────────────────────────────────────
    # 1.1
    v_ac_before_dev   = "RED" if any_gate_filled == 0 else ("AMBER" if any_gate_filled < gates_total else "GREEN")
    v_pre_dev_qa      = "RED" if tracker_with < 3 else ("AMBER" if tracker_with < gates_total * 0.9 else "GREEN")
    v_doc_link        = "UNKNOWN"   # no field in schema yet
    v_blocked_qa      = "AMBER" if clarification_count > 0 else "GREEN"

    # 1.2
    v_test_cases_qa   = "UNKNOWN"   # not tracked in schema
    v_checklist       = "RED" if checklist_pct < 50 else ("AMBER" if checklist_pct < 90 else "GREEN")
    v_qa_rework       = ("AMBER" if rework_rate is not None and rework_rate < 15
                         else ("RED" if rework_rate is not None else "UNKNOWN"))
    v_multi_qa        = "UNKNOWN"   # no state history cycle count

    # 1.4
    v_scope_inj       = "RED" if (scope_pct or 0) > 20 else ("AMBER" if (scope_pct or 0) > 10 else "GREEN")
    v_vsts_fields     = "AMBER" if vsts_pct is not None and vsts_pct < 95 else ("GREEN" if vsts_pct else "UNKNOWN")
    v_ready_release   = "UNKNOWN" if releases_completed == 0 else "GREEN"

    # 1.5 — all UNKNOWN until p_bugs populated and releases completed
    v_defect_escape   = "UNKNOWN"
    v_hotfix          = "UNKNOWN"
    v_post_incidents  = "UNKNOWN"
    v_root_cause      = "UNKNOWN"

    # ── Count KPI colours ─────────────────────────────────────────────────────
    all_verdicts = [
        v_ac_before_dev, v_pre_dev_qa, v_checklist, v_scope_inj,
        v_blocked_qa, v_vsts_fields,
    ]
    red_kpis   = sum(1 for v in all_verdicts if v == "RED")
    amber_kpis = sum(1 for v in all_verdicts if v == "AMBER")
    # data_gaps = structural schema/process gaps shown in data gaps table (not all UNKNOWNs)
    data_gaps  = 4

    return {
        # ── Metadata ──────────────────────────────────────────────────────────
        "sprint":             sprint_path,
        "sprint_start":       sprint_start.isoformat(),
        "overall_verdict":    "RED",
        "verdict_summary":    (
            f"No completed production release exists in the tracking system. "
            f"All release quality KPIs are unmeasurable — the absence of release "
            f"tracking is itself a governance failure."
        ),

        # ── Stats strip ───────────────────────────────────────────────────────
        "releases_completed": releases_completed,
        "red_kpis":           red_kpis,
        "amber_kpis":         amber_kpis,
        "data_gaps":          data_gaps,
        "defects_logged":     defects_logged,
        "actions_required":   2,

        # ── Raw counts (used in result text) ──────────────────────────────────
        "enhancement_count":  enhancement_count,
        "gates_total":        gates_total,
        "gates_have_row":     gates_have_row,
        "any_gate_filled":    any_gate_filled,
        "tracker_total":      tracker_total,
        "tracker_with":       tracker_with,
        "tracker_steps":      tracker_steps,
        "tracker_checked":    tracker_checked,
        "checklist_pct":      checklist_pct,
        "total_sprint":       total_sprint,
        "non_task_sprint":    non_task_sprint,
        "injected_count":     injected_count,
        "scope_pct":          scope_pct,
        "active_non_task":    active_non_task,
        "unestimated":        unestimated,
        "vsts_pct":           vsts_pct,
        "clarification_count": clarification_count,
        "request_est_count":  request_est_count,
        "p1_open":            p1_open,
        "rework_items":       rework_items,
        "rework_rate":        rework_rate,
        "rework_source":      rework_source,
        "defects_logged":     defects_logged,
        "releases_completed": releases_completed,
        "ish_populated":      ish_count > 0,

        # ── Section 1.1 verdicts ──────────────────────────────────────────────
        "v_ac_before_dev":    v_ac_before_dev,
        "v_pre_dev_qa":       v_pre_dev_qa,
        "v_doc_link":         v_doc_link,
        "v_blocked_qa":       v_blocked_qa,

        # ── Section 1.2 verdicts ──────────────────────────────────────────────
        "v_test_cases_qa":    v_test_cases_qa,
        "v_checklist":        v_checklist,
        "v_qa_rework":        v_qa_rework,
        "v_multi_qa":         v_multi_qa,

        # ── Section 1.4 verdicts ──────────────────────────────────────────────
        "v_scope_inj":        v_scope_inj,
        "v_vsts_fields":      v_vsts_fields,
        "v_ready_release":    v_ready_release,

        # ── Section 1.5 verdicts ──────────────────────────────────────────────
        "v_defect_escape":    v_defect_escape,
        "v_hotfix":           v_hotfix,
        "v_post_incidents":   v_post_incidents,
        "v_root_cause":       v_root_cause,

        # ── Verdict summary counts ────────────────────────────────────────────
        "verdict_kpis_red":   red_kpis,
        "verdict_kpis_amber": amber_kpis,
        "verdict_data_gaps":  data_gaps,
        "verdict_actions":    2,
        "verdict_paragraph": (
            "Primary issue: no production release has been recorded in "
            f"p_releases and no production defects have been logged in p_bugs. "
            "The Release Audit framework cannot function without these two data "
            "inputs — the audit verdict of RED is driven by governance failure, "
            "not by bad metrics. Until release tracking is operational, release "
            "quality is entirely invisible to management."
        ),

        # ── Data gaps table rows ──────────────────────────────────────────────
        "data_gaps_rows": [
            {
                "gap":         "No production release logged",
                "table_field": "p_releases — 0 completed",
                "consequence": "Entire Release Audit is unmeasurable. Release quality governance is completely blind.",
                "severity":    "red",
            },
            {
                "gap":         "No production defects recorded",
                "table_field": "p_bugs — 0 rows",
                "consequence": "Defect escape rate, hotfix count, post-release incidents all unknown.",
                "severity":    "red",
            },
            {
                "gap":         "Gate compliance not populated",
                "table_field": "p_planning_gates — 0/20",
                "consequence": "AC approval, DoR sign-off, story-written status unmeasurable for May sprint.",
                "severity":    "amber",
            },
            {
                "gap":         "Test case links not enforced",
                "table_field": "No doc_link field",
                "consequence": "Cannot verify test coverage was adequate before QA entry for any story.",
                "severity":    "grey",
            },
        ],
    }


def _empty_data() -> dict:
    """Fallback when DB is unreachable."""
    return {
        "sprint": "Unknown", "sprint_start": "", "overall_verdict": "UNKNOWN",
        "verdict_summary": "Database unavailable.",
        "releases_completed": 0, "red_kpis": 0, "amber_kpis": 0,
        "data_gaps": 0, "defects_logged": 0, "actions_required": 0,
        "enhancement_count": 0, "gates_total": 0, "gates_have_row": 0,
        "any_gate_filled": 0, "tracker_total": 0, "tracker_with": 0,
        "tracker_steps": 0, "tracker_checked": 0, "checklist_pct": 0,
        "total_sprint": 0, "non_task_sprint": 0, "injected_count": 0,
        "scope_pct": None, "active_non_task": 0, "unestimated": 0,
        "vsts_pct": None, "clarification_count": 0, "request_est_count": 0,
        "p1_open": 0, "rework_items": None, "rework_rate": None,
        "rework_source": "no_history", "ish_populated": False,
        "v_ac_before_dev": "UNKNOWN", "v_pre_dev_qa": "UNKNOWN",
        "v_doc_link": "UNKNOWN", "v_blocked_qa": "UNKNOWN",
        "v_test_cases_qa": "UNKNOWN", "v_checklist": "UNKNOWN",
        "v_qa_rework": "UNKNOWN", "v_multi_qa": "UNKNOWN",
        "v_scope_inj": "UNKNOWN", "v_vsts_fields": "UNKNOWN",
        "v_ready_release": "UNKNOWN", "v_defect_escape": "UNKNOWN",
        "v_hotfix": "UNKNOWN", "v_post_incidents": "UNKNOWN",
        "v_root_cause": "UNKNOWN",
        "verdict_kpis_red": 0, "verdict_kpis_amber": 0,
        "verdict_data_gaps": 0, "verdict_actions": 0,
        "verdict_paragraph": "", "data_gaps_rows": [],
    }
