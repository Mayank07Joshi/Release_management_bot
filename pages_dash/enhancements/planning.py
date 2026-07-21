"""EOD Planning Tool — Story Readiness, BA Sign-Off & Capacity Dashboard"""

import re
import dash
import calendar as _cal_lib
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime, timedelta

from dash import dcc, html, Input, Output, State, ALL, callback, clientside_callback, ctx, no_update, ClientsideFunction
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from data.loader import load_data
from config.team_mapping import TEAM_MAPPING
from config.settings  import ADO_BASE_URL
from config.lifecycle import LIFECYCLE, STEP_INDEX, STEP_LABELS, TOTAL_STEPS

dash.register_page(__name__, path="/planning", name="Planning Tool")
print(">>> [planning.py] LOADED — panel=680px card=#252548")

import time as _time_mod
_GANTT_CACHE: dict = {"items": None, "tasks": None, "ts": 0.0}
_GANTT_TTL = 300  # 5-minute cache

# ─── Colour tokens ─────────────────────────────────────────────────────────────
G  = "var(--green)"   # green  – Ready / good
R  = "var(--red)"     # red    – Not Started / urgent
A  = "var(--amber)"   # amber  – Draft / warning
B  = "var(--blue)"    # blue   – In Dev / M0
P  = "var(--purple)"  # purple – accent
TX = "var(--text-primary)"
MT = "var(--text-secondary)"
BD = "var(--border)"
CD = "var(--bg-elevated)"
C2 = "var(--bg-hover)"
C3 = "var(--bg-base)"

# Dim (background ~12%) and border (~35%) variants for f-string replacements
G_DIM = "var(--green-dim)";  G_BRD = "var(--green-border)"
R_DIM = "var(--red-dim)";    R_BRD = "var(--red-border)"
A_DIM = "var(--amber-dim)";  A_BRD = "var(--amber-border)"
B_DIM = "var(--blue-dim)";   B_BRD = "var(--blue-border)"
P_DIM = "var(--purple-dim)"; P_BRD = "var(--purple-border)"

# Dim/border lookups for dynamic color variables
_COLOR_DIM = {G: G_DIM, R: R_DIM, A: A_DIM, B: B_DIM, P: P_DIM}
_COLOR_BRD = {G: G_BRD, R: R_BRD, A: A_BRD, B: B_BRD, P: P_BRD}

def _dim(c): return _COLOR_DIM.get(c, f"{c}22")
def _brd(c): return _COLOR_BRD.get(c, f"{c}44")

STATUS_COLOR = {
    "NOT STARTED": R,
    "IN PROGRESS": A,
    "READY":       G,
}

# BA sign-off gate fields — ordered, matches DB columns
_GATE_FIELDS = ("claude_screens", "text_written", "our_screens", "html_screens", "sn_signoff")
_GATE_LABELS = {
    "claude_screens": "Claude screens",
    "text_written":   "Text written",
    "our_screens":    "Our screens",
    "html_screens":   "HTML screens",
    "sn_signoff":     "SN sign-off",
}
_GATE_FILTER_MAP: dict = {}  # gates now toggle directly; no tracker focus mapping
_WIN_BORDER  = "var(--gold)"  # golden separator between planning window and rest of 2026

# Tab button styles (active / idle) — used by _switch_tab callback
_TAB_BTN_ACT = {
    "background": P_DIM, "border": f"1px solid {P}", "borderRadius": "8px",
    "color": TX, "fontSize": "13px", "fontWeight": "600",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}
_TAB_BTN_IDL = {
    "background": "transparent", "border": f"1px solid {BD}", "borderRadius": "8px",
    "color": MT, "fontSize": "13px", "fontWeight": "400",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}

# ─── Story Owner mapping ────────────────────────────────────────────────────────
# ADO field: Custom.Userstoryowner — short name values ("Geetika", "Chhavi")
# Maps short name → (display_name, code, role)
STORY_OWNER_MAP: dict[str, tuple] = {
    "Geetika": ("Geetika Khanna", "SO-01", "Story Owner"),
    "Chhavi":  ("Chhavi Bhardwaj", "SO-02", "Story Owner"),
}
BA_DEFAULT = ("Unassigned", "SO-00", "Story Owner")

# ─── Terminal ADO states — used for closed-item filtering only ─────────────────
_CLOSED_STATES = {
    "Closed", "Not an issue", "Not Required", "Userstory Update",
    "No Customer Response", "Resolved",
}

# ─── Matrix column order ────────────────────────────────────────────────────────
# Computed at call time: M0/M1/M2 + calendar months strictly after M2 (no duplicates)
def _matrix_months() -> list:
    cur_m = date.today().month
    rest = [_CAL[m] for m in range(min(cur_m + 3, 13), 13)]
    return ["M0", "M1", "M2"] + rest

CELL_COLORS = {
    "not_started":  {"bg": "#2e0e0e", "text": R, "border": R},
    "draft":        {"bg": "#2a1f00", "text": A, "border": A},
    "story_frozen": {"bg": "#0c2e1e", "text": G, "border": G},  # all gates complete = Ready
}

_DEV_ROLE = {
    "Development":  "Web Dev",
    "Mobile":       "Mobile Dev",
    "QA":           "QA/Test",
    "Design/Video": "Designer",
    "Management":   "Manager",
    "User Story":   "BA/PO",
}

_CAL = {1:"Jan", 2:"Feb", 3:"Mar", 4:"Apr", 5:"May", 6:"Jun",
        7:"Jul", 8:"Aug", 9:"Sep", 10:"Oct", 11:"Nov", 12:"Dec"}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

# Cache for processed planning data — avoids rebuilding 700+ stories on every page visit.
# Gate state is NOT cached here (always fresh from DB on page load).
_planning_cache: dict = {"data": None, "ts": 0.0}
_bug_cache:      dict = {"data": None, "ts": 0.0}
_st_data_cache:  dict = {"data": None, "ts": 0.0}
_PLANNING_TTL = 300  # 5 minutes, matches load_data() TTL
_PAGE_SIZE    = 4    # rows per page in BA Sign-Off table


def _load_unestimated_data() -> list[dict]:
    """
    Returns all 2026 Enhancements + Issues/Bugs from agg_story_estimation with a known month.
    Includes all est_status values so the dev×month matrix can show estimated counts too.
    """
    from data.loader import engine as _engine
    from sqlalchemy import text as _text
    try:
        with _engine.connect() as conn:
            rows = conn.execute(_text(
                "SELECT e.work_item_id, e.title, e.work_item_type, e.main_developer, e.story_owner, "
                "       e.month_key, e.est_status, e.task_count, e.task_missing_count, e.task_est_sum, e.priority, "
                "       COALESCE(w.release_date, '') AS release_date "
                "FROM agg_story_estimation e "
                "LEFT JOIN work_items_main w ON w.work_item_id = e.work_item_id "
                "WHERE e.month_key IS NOT NULL "
                "ORDER BY e.month_key NULLS LAST, e.priority NULLS LAST, e.work_item_id"
            )).fetchall()
    except Exception:
        return []

    result = []
    for r in rows:
        dev = str(r.main_developer or "Unassigned").strip()
        wtype = "Enhancement" if r.work_item_type == "Enhancement" else "Issue"
        try:
            pri = f"P{int(r.priority)}" if r.priority else "P4"
        except (TypeError, ValueError):
            pri = "P4"
        result.append({
            "id":           int(r.work_item_id),
            "title":        str(r.title or "")[:100],
            "pri":          pri,
            "type":         wtype,
            "raw_type":     str(r.work_item_type or wtype),
            "dev":          dev,
            "month":        str(r.month_key or ""),
            "est_status":   r.est_status,
            "task_count":   int(r.task_count or 0),
            "task_missing": int(r.task_missing_count or 0),
            "task_sum":     float(r.task_est_sum or 0),
            "story_owner":  str(r.story_owner or ""),
            "release_date": str(r.release_date or ""),
        })
    # M0/M1/M2 sprint months first, then other months alphabetically, then by priority
    _mk_o = {"M0": 0, "M1": 1, "M2": 2}
    result.sort(key=lambda s: (
        _mk_o.get(s["month"], 99),
        "" if s["month"] in _mk_o else s["month"],
        int(s["pri"][1:]) if len(s["pri"]) > 1 and s["pri"][1:].isdigit() else 99,
        s["id"],
    ))
    return result


def _load_bug_data() -> list[dict]:
    """Load open Bug/Bug_UI/Bug_Text items from 2026 iterations using agg_story_estimation."""
    import time as _time
    from data.loader import engine as _engine
    from sqlalchemy import text as _text

    _now = _time.monotonic()
    if _bug_cache["data"] is not None and (_now - _bug_cache["ts"]) < _PLANNING_TTL:
        return _bug_cache["data"]

    try:
        with _engine.connect() as conn:
            rows = conn.execute(_text(
                "SELECT work_item_id, title, work_item_type, main_developer, story_owner, "
                "       month_key, priority, original_estimate, state, est_status "
                "FROM agg_story_estimation "
                "WHERE work_item_type IN ('Bug', 'Bug_UI', 'Bug_Text') "
                "  AND month_key IS NOT NULL "
                "ORDER BY priority NULLS LAST, work_item_id"
            )).fetchall()
    except Exception:
        return []

    result = []
    for r in rows:
        dev      = str(r.main_developer or "Unassigned").strip()
        dev_team = TEAM_MAPPING.get(dev, "")
        dev_role = _DEV_ROLE.get(dev_team, "Developer")
        est      = float(r.original_estimate or 0)
        est_ok   = est > 0
        owner    = str(r.story_owner or "").strip()
        ba       = STORY_OWNER_MAP.get(owner, BA_DEFAULT)
        try:
            pri = f"P{int(r.priority)}" if r.priority else "P4"
        except (TypeError, ValueError):
            pri = "P4"
        result.append({
            "id":        int(r.work_item_id),
            "title":     str(r.title or "")[:100] or "(No title)",
            "pri":       pri,
            "type":      str(r.work_item_type or "Bug"),
            "dev":       dev,
            "dev_role":  dev_role,
            "ba":        ba[0],
            "ba_code":   ba[1],
            "ba_role":   ba[2],
            "month":     str(r.month_key or ""),
            "state":     str(r.state or ""),
            "estimated": est_ok,
            "hrs":       est if est_ok else None,
        })

    _bug_cache["data"] = result
    _bug_cache["ts"]   = _now
    return result


def _load_story_tracking_data() -> list[dict]:
    """Load BA story tracking rows joined with work_items_main (5-min cache)."""
    import time as _time
    from data.loader import engine as _engine
    from sqlalchemy import text as _text

    _now = _time.monotonic()
    if _st_data_cache["data"] is not None and (_now - _st_data_cache["ts"]) < _PLANNING_TTL:
        return _st_data_cache["data"]

    try:
        with _engine.connect() as conn:
            rows = conn.execute(_text("""
                SELECT
                    w.work_item_id, w.title, w.story_owner, w.area,
                    w.function, w.priority, w.main_developer, w.main_designer,
                    w.state, w.release_date,
                    t.est_start_date, t.est_end_date, t.est_hours, t.actual_hours,
                    t.story_size, t.story_status, t.story_type, t.design_type,
                    t.responsible_qa
                FROM p_story_tracking t
                JOIN work_items_main w USING (work_item_id)
                ORDER BY w.priority NULLS LAST, w.work_item_id
            """)).fetchall()
        result = [dict(r._mapping) for r in rows]
    except Exception:
        result = []

    _st_data_cache["data"] = result
    _st_data_cache["ts"]   = _now
    return result


_ST_STATUS_COLOR = {
    "Complete":     ("var(--green)",           "var(--green-dim)"),
    "Inprogress":   ("var(--amber)",           "var(--amber-dim)"),
    "Incomplete":   ("var(--text-secondary)",  "var(--bg-hover)"),
    "Not Required": ("var(--text-secondary)",  "var(--bg-hover)"),
}
_ST_SIZE_COLOR  = {"Big": P, "Medium": B, "Small": G, "Very small": MT}
_ST_DESIGN_ICON = {"New Design": "✦", "Old Design": "○"}
_ST_SIZE_RANK   = {"Big": 0, "Medium": 1, "Small": 2, "Very small": 3}

# Sort-header helper — same pattern as release_status.py
def _st_sort_th(lbl, col_key, sort_col, sort_dir):
    if sort_col == col_key:
        ind, ind_c = ("↑", B) if sort_dir == "asc" else ("↓", B)
    else:
        ind, ind_c = "⇅", BD
    return html.Div(
        [html.Span(lbl),
         html.Span(ind, style={"fontSize": "8px", "color": ind_c,
                               "marginLeft": "3px", "lineHeight": "1"})],
        id={"type": "st-sort-th", "col": col_key},
        n_clicks=0,
        style={"display": "inline-flex", "alignItems": "center",
               "cursor": "pointer", "userSelect": "none", "gap": "1px"},
    )


def _build_st_table(rows, sort_col, sort_dir, filters):
    """Render the story tracking HTML table with filters and sort applied."""
    # ── Filter ────────────────────────────────────────────────────────────────
    if filters:
        if filters.get("priority"):
            pset = set(filters["priority"])
            rows = [r for r in rows
                    if (f"P{int(r['priority'])}" if r.get("priority") else "—") in pset]
        if filters.get("status"):
            sset = set(filters["status"])
            rows = [r for r in rows if (r.get("story_status") or "") in sset]
        if filters.get("size"):
            zset = set(filters["size"])
            rows = [r for r in rows if (r.get("story_size") or "") in zset]
        if filters.get("area"):
            aset = set(filters["area"])
            rows = [r for r in rows if (r.get("area") or "") in aset]
        if filters.get("owner"):
            oset = set(filters["owner"])
            rows = [r for r in rows if (r.get("story_owner") or "") in oset]

    # ── Sort ──────────────────────────────────────────────────────────────────
    if sort_col and sort_dir:
        rev = sort_dir == "desc"
        _sk = {
            "id":        lambda r: r.get("work_item_id") or 0,
            "title":     lambda r: (r.get("title") or "").lower(),
            "owner":     lambda r: (r.get("story_owner") or "").lower(),
            "priority":  lambda r: r.get("priority") or 99,
            "area":      lambda r: (r.get("area") or "").lower(),
            "function":  lambda r: (r.get("function") or "").lower(),
            "size":      lambda r: _ST_SIZE_RANK.get(r.get("story_size") or "", 9),
            "status":    lambda r: {"Complete":0,"Inprogress":1,"Incomplete":2,"Not Required":3}.get(
                                    r.get("story_status") or "", 9),
            "stype":     lambda r: (r.get("story_type") or "").lower(),
            "est_start": lambda r: r.get("est_start_date") or date(2099, 1, 1),
            "est_end":   lambda r: r.get("est_end_date")   or date(2099, 1, 1),
            "est_hrs":   lambda r: float(r.get("est_hours")    or 0),
            "actual":    lambda r: float(r.get("actual_hours") or 0),
            "designer":  lambda r: (r.get("main_designer") or "").lower(),
            "qa":        lambda r: (r.get("responsible_qa") or "").lower(),
            "design":    lambda r: (r.get("design_type") or "").lower(),
        }
        fn = _sk.get(sort_col)
        if fn:
            rows = sorted(rows, key=fn, reverse=rev)

    # ── HTML ──────────────────────────────────────────────────────────────────
    _TH = {
        "background": "var(--bg-hover)", "color": MT,
        "fontSize": "10px", "fontWeight": "700", "letterSpacing": "1px",
        "textTransform": "uppercase", "padding": "8px 10px",
        "borderBottom": f"1px solid {BD}", "whiteSpace": "nowrap",
        "position": "sticky", "top": "0", "zIndex": "5",
    }
    _TD = {
        "padding": "7px 10px", "borderBottom": f"1px solid {BD}",
        "fontSize": "12px", "color": TX, "verticalAlign": "middle",
    }

    cols = [
        ("ID",        "id",        {}),
        ("Title",     "title",     {"minWidth": "260px"}),
        ("Owner",     "owner",     {}),
        ("Priority",  "priority",  {}),
        ("Area",      "area",      {}),
        ("Function",  "function",  {}),
        ("Size",      "size",      {}),
        ("Status",    "status",    {}),
        ("Type",      "stype",     {}),
        ("Est Start", "est_start", {}),
        ("Est End",   "est_end",   {}),
        ("Est Hrs",   "est_hrs",   {}),
        ("Actual",    "actual",    {}),
        ("Designer",  "designer",  {}),
        ("QA",        "qa",        {}),
        ("Design",    "design",    {}),
    ]

    header = html.Tr([
        html.Th(_st_sort_th(lbl, ck, sort_col, sort_dir), style={**_TH, **ex})
        for lbl, ck, ex in cols
    ])

    def _chip(text, fg, bg):
        return html.Td(html.Span(text, style={
            "background": bg, "color": fg, "borderRadius": "4px",
            "padding": "2px 7px", "fontSize": "11px", "fontWeight": "600",
            "whiteSpace": "nowrap",
        }), style=_TD)

    body_rows = []
    for r in rows:
        wid      = r["work_item_id"]
        title    = str(r.get("title") or "")
        owner    = str(r.get("story_owner") or "—")
        area     = str(r.get("area") or "—")
        func     = str(r.get("function") or "—")
        pri_raw  = r.get("priority")
        pri      = f"P{int(pri_raw)}" if pri_raw else "—"
        size     = str(r.get("story_size") or "—")
        status   = str(r.get("story_status") or "—")
        stype    = str(r.get("story_type") or "—")
        design   = str(r.get("design_type") or "—")
        designer = str(r.get("main_designer") or "—").strip().rstrip(",")
        qa       = str(r.get("responsible_qa") or "—")

        est_s = str(r["est_start_date"]) if r.get("est_start_date") else "—"
        est_e = str(r["est_end_date"])   if r.get("est_end_date")   else "—"
        est_h = f"{float(r['est_hours']):.0f}h"    if r.get("est_hours")    else "—"
        act_h = f"{float(r['actual_hours']):.0f}h" if r.get("actual_hours") else "—"

        st_fg, st_bg = _ST_STATUS_COLOR.get(status, (MT, C2))
        sz_col       = _ST_SIZE_COLOR.get(size, MT)
        design_icon  = _ST_DESIGN_ICON.get(design, "")

        body_rows.append(html.Tr([
            html.Td(html.A(str(wid), href=f"{ADO_BASE_URL}{wid}", target="_blank",
                           style={"color": P, "textDecoration": "none",
                                  "fontFamily": "monospace", "fontSize": "11px"}), style=_TD),
            html.Td(html.Div(title, style={
                "overflow": "hidden", "textOverflow": "ellipsis",
                "whiteSpace": "nowrap", "maxWidth": "280px",
            }), style=_TD),
            html.Td(owner, style={**_TD, "color": MT, "fontSize": "11px"}),
            _chip(pri, P, P_DIM),
            html.Td(area, style={**_TD, "color": MT, "fontSize": "11px", "whiteSpace": "nowrap"}),
            html.Td(func, style={**_TD, "color": MT, "fontSize": "11px"}),
            html.Td(size, style={**_TD, "color": sz_col, "fontWeight": "600", "whiteSpace": "nowrap"}),
            _chip(status, st_fg, st_bg),
            html.Td(stype, style={**_TD, "color": MT, "fontSize": "11px"}),
            html.Td(est_s, style={**_TD, "fontFamily": "monospace", "fontSize": "11px",
                                  "color": B if est_s != "—" else MT, "whiteSpace": "nowrap"}),
            html.Td(est_e, style={**_TD, "fontFamily": "monospace", "fontSize": "11px",
                                  "color": B if est_e != "—" else MT, "whiteSpace": "nowrap"}),
            html.Td(est_h, style={**_TD, "textAlign": "right", "fontFamily": "monospace",
                                  "color": TX if est_h != "—" else MT}),
            html.Td(act_h, style={**_TD, "textAlign": "right", "fontFamily": "monospace",
                                  "color": G if act_h != "—" else MT}),
            html.Td(html.Div(designer, style={
                "overflow": "hidden", "textOverflow": "ellipsis",
                "whiteSpace": "nowrap", "maxWidth": "120px",
            }), style={**_TD, "fontSize": "11px", "color": MT}),
            html.Td(qa, style={**_TD, "fontSize": "11px", "color": MT, "whiteSpace": "nowrap"}),
            html.Td(f"{design_icon} {design}",
                    style={**_TD, "fontSize": "11px", "color": MT, "whiteSpace": "nowrap"}),
        ]))

    if not body_rows:
        body_rows = [html.Tr([html.Td(
            "No stories match the current filters.",
            colSpan=16,
            style={**_TD, "color": MT, "textAlign": "center", "padding": "32px"},
        )])]

    return html.Div(
        html.Table(
            [html.Thead(header), html.Tbody(body_rows)],
            style={"width": "100%", "borderCollapse": "collapse"},
        ),
        style={"overflowX": "auto", "overflowY": "auto", "maxHeight": "65vh"},
    )


def _build_story_tracking_tab() -> html.Div:
    """Build Story Tracking tab: stores + KPI bar + filter row + table wrapper."""
    rows = _load_story_tracking_data()

    total      = len(rows)
    complete   = sum(1 for r in rows if (r.get("story_status") or "") == "Complete")
    wip        = sum(1 for r in rows if (r.get("story_status") or "").lower() == "inprogress")
    with_dates = sum(1 for r in rows if r.get("est_start_date"))
    est_hrs    = sum(float(r["est_hours"])    for r in rows if r.get("est_hours"))
    act_hrs    = sum(float(r["actual_hours"]) for r in rows if r.get("actual_hours"))

    def _kpi(label, value, sub="", color=None):
        return html.Div([
            html.Div(str(value), style={
                "fontSize": "22px", "fontWeight": "700",
                "color": color or TX, "lineHeight": "1.1",
            }),
            html.Div(label, style={"fontSize": "11px", "color": MT, "marginTop": "2px"}),
            html.Div(sub, style={"fontSize": "10px", "color": MT}) if sub else None,
        ], style={
            "background": CD, "border": f"1px solid {BD}", "borderRadius": "10px",
            "padding": "14px 18px", "flex": "1", "minWidth": "90px",
        })

    kpi_row = html.Div([
        _kpi("Total stories",   total),
        _kpi("Complete",        complete,  color=G),
        _kpi("In Progress",     wip,       color=A),
        _kpi("With plan dates", with_dates),
        _kpi("Est. hours",      f"{est_hrs:,.0f}"),
        _kpi("Actual hours",    f"{act_hrs:,.0f}",
             sub=f"{round(act_hrs/est_hrs*100)}% logged" if est_hrs else ""),
    ], style={"display": "flex", "gap": "10px", "marginBottom": "14px"})

    # ── Filter options derived from loaded data ────────────────────────────────
    pris     = sorted({f"P{int(r['priority'])}" for r in rows if r.get("priority")})
    statuses = [s for s in ["Complete", "Inprogress", "Incomplete", "Not Required"]
                if any((r.get("story_status") or "") == s for r in rows)]
    sizes    = [s for s in ["Big", "Medium", "Small", "Very small"]
                if any((r.get("story_size") or "") == s for r in rows)]
    areas    = sorted({str(r.get("area") or "") for r in rows if r.get("area")})
    owners   = sorted({str(r.get("story_owner") or "") for r in rows if r.get("story_owner")})

    _DD = {"fontSize": "12px", "flex": "1"}

    def _flbl(txt):
        return html.Span(txt, style={
            "fontSize": "10px", "fontWeight": "700", "color": MT,
            "letterSpacing": "1px", "textTransform": "uppercase",
            "whiteSpace": "nowrap", "marginRight": "6px",
        })

    filter_bar = html.Div([
        html.Div([_flbl("Priority"), dcc.Dropdown(
            id="st-flt-priority",
            options=[{"label": v, "value": v} for v in pris],
            multi=True, placeholder="All…", className="dark-dropdown", style=_DD,
        )], style={"display": "flex", "alignItems": "center", "flex": "1", "minWidth": "140px"}),
        html.Div([_flbl("Status"), dcc.Dropdown(
            id="st-flt-status",
            options=[{"label": v, "value": v} for v in statuses],
            multi=True, placeholder="All…", className="dark-dropdown", style=_DD,
        )], style={"display": "flex", "alignItems": "center", "flex": "1.4", "minWidth": "180px"}),
        html.Div([_flbl("Size"), dcc.Dropdown(
            id="st-flt-size",
            options=[{"label": v, "value": v} for v in sizes],
            multi=True, placeholder="All…", className="dark-dropdown", style=_DD,
        )], style={"display": "flex", "alignItems": "center", "flex": "1", "minWidth": "140px"}),
        html.Div([_flbl("Area"), dcc.Dropdown(
            id="st-flt-area",
            options=[{"label": v, "value": v} for v in areas],
            multi=True, placeholder="All…", className="dark-dropdown", style=_DD,
        )], style={"display": "flex", "alignItems": "center", "flex": "1.4", "minWidth": "180px"}),
        html.Div([_flbl("Owner"), dcc.Dropdown(
            id="st-flt-owner",
            options=[{"label": v, "value": v} for v in owners],
            multi=True, placeholder="All…", className="dark-dropdown", style=_DD,
        )], style={"display": "flex", "alignItems": "center", "flex": "1", "minWidth": "140px"}),
    ], style={
        "display": "flex", "gap": "10px", "flexWrap": "wrap", "alignItems": "center",
        "background": CD, "border": f"1px solid {BD}", "borderRadius": "10px",
        "padding": "10px 14px", "marginBottom": "14px",
    })

    return html.Div([
        dcc.Store(id="st-sort-store", data={"col": None, "dir": None}),
        html.Div([
            html.Span("STORY TRACKING", style={
                "fontSize": "9px", "fontWeight": "800", "color": B,
                "letterSpacing": "2px", "textTransform": "uppercase",
            }),
            html.Span(f" · {total} stories · BA planning tracker",
                      style={"fontSize": "11px", "color": MT, "marginLeft": "8px"}),
        ], style={"marginBottom": "14px"}),
        kpi_row,
        filter_bar,
        html.Div(
            html.Div(
                _build_st_table(rows, None, None, {}),
                style={"background": CD, "border": f"1px solid {BD}",
                       "borderRadius": "12px", "overflow": "hidden"},
            ),
            id="st-table-wrapper",
        ),
    ], style={"padding": "4px 0"})


def _story_status_key(s: dict) -> str:
    """Map gate dict → CELL_COLORS key for dev matrix cell colour."""
    done = sum(1 for f in _GATE_FIELDS if s.get(f))
    if done == len(_GATE_FIELDS):
        return "story_frozen"  # all gates complete → green
    if done > 0:
        return "draft"          # partial progress → amber
    return "not_started"        # no gates → grey


def _load_planning_data():
    """
    Pull open Enhancements from 2026 ADO iterations and build all planning-page
    data structures. Data loaded from agg_story_estimation (pre-computed pipeline).
    Gate state is always fetched fresh from DB on every call.

    Returns:
        stories      – list[dict]  one entry per ADO work item
        months       – list[dict]  {key, label, badge, bc} ordered M0→Dec
        init_gates   – dict        str(work_item_id) → {written, ac, est}
        ba_names     – list[str]   unique BA display names (non-default)
        dev_names    – list[str]   unique developer names (non-unassigned)
        dev_matrix   – dict        dev_name → {role, ns, M0:(...), ...}
        story_matrix – list[dict]  M0/M1/M2 stories × months (for By Story view)
    """
    import time as _time
    from data.loader import engine as _engine
    from sqlalchemy import text as _text

    # ── Check cache (stories + matrices only, not gates) ─────────────────────
    _now = _time.monotonic()
    if _planning_cache["data"] is not None and (_now - _planning_cache["ts"]) < _PLANNING_TTL:
        cached_stories, months, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat = \
            _planning_cache["data"]
        try:
            from db.planning import load_all_gates as _load_all_gates
            _db_gates = _load_all_gates()
        except Exception:
            _db_gates = {}
        stories = []
        for s in cached_stories:
            s = dict(s)
            _dg = _db_gates.get(s["id"], {})
            for _f in _GATE_FIELDS:
                s[_f] = _dg.get(_f, False)
            stories.append(s)
        init_gates = {
            str(s["id"]): {f: s.get(f, False) for f in _GATE_FIELDS}
            for s in stories
        }
        return stories, months, init_gates, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat

    # ── Load Enhancement stories from agg_story_estimation ───────────────────
    try:
        with _engine.connect() as conn:
            rows = conn.execute(_text(
                "SELECT work_item_id, title, work_item_type, state, priority, "
                "       main_developer, story_owner, month_key, function, "
                "       original_estimate, est_status "
                "FROM agg_story_estimation "
                "WHERE work_item_type = 'Enhancement' "
                "  AND month_key IS NOT NULL "
                "ORDER BY priority NULLS LAST, work_item_id"
            )).fetchall()
    except Exception:
        return [], [], {}, [], [], {}, [], []

    today = date.today()
    cur_m = today.month

    def _fmt_pri(p) -> str:
        try:
            return f"P{int(float(p))}"
        except Exception:
            return "P4"

    def _fmt_size(h) -> str | None:
        if not h or float(h) == 0:
            return None
        h = float(h)
        if h >= 80: return "Big"
        if h >= 30: return "Medium"
        if h >= 8:  return "Small"
        return "Very Small"

    # ── Build stories list ────────────────────────────────────────────────────
    stories: list[dict] = []
    for r in rows:
        dev      = str(r.main_developer or "Unassigned").strip()
        dev_team = TEAM_MAPPING.get(dev, "")
        dev_role = _DEV_ROLE.get(dev_team, "Developer")
        ba       = STORY_OWNER_MAP.get(str(r.story_owner or "").strip(), BA_DEFAULT)
        est      = float(r.original_estimate or 0)
        est_ok   = est > 0
        est_full = r.est_status in ("estimated", "estimated_via_tasks") if r.est_status else est_ok
        wtype    = str(r.work_item_type or "")

        stories.append({
            "id":            int(r.work_item_id),
            "title":         str(r.title or "")[:100] or "(No title)",
            "pri":           _fmt_pri(r.priority),
            "type":          "ENH" if wtype == "Enhancement" else "ISSUE",
            "size":          _fmt_size(est),
            "hrs":           est if est_ok else None,
            "dev":           dev,
            "dev_role":      dev_role,
            "ba":            ba[0],
            "ba_code":       ba[1],
            "ba_role":       ba[2],
            "month":          str(r.month_key or ""),
            "claude_screens": False,
            "text_written":   False,
            "our_screens":    False,
            "html_screens":   False,
            "sn_signoff":     False,
            "estimation":     est_full,
            "state":          str(r.state or ""),
            "function":      str(r.function or ""),
        })

    # ── Apply DB gate overrides ───────────────────────────────────────────────
    try:
        from db.planning import load_all_gates as _load_all_gates
        _db_gates = _load_all_gates()
    except Exception:
        _db_gates = {}

    for s in stories:
        _dg = _db_gates.get(s["id"], {})
        for _f in _GATE_FIELDS:
            s[_f] = _dg.get(_f, False)

    init_gates = {
        str(s["id"]): {f: s.get(f, False) for f in _GATE_FIELDS}
        for s in stories
    }

    # ── Build MONTHS list ─────────────────────────────────────────────────────
    _morder = ["M0","M1","M2","Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]
    _mlabels = {
        "M0": f"M0 · {_CAL[cur_m]}",
        "M1": f"M1 · {_CAL[min(cur_m+1, 12)]}",
        "M2": f"M2 · {_CAL[min(cur_m+2, 12)]}",
    }
    for _, ml in _CAL.items():
        _mlabels[ml] = ml

    months_present = {s["month"] for s in stories}
    months: list[dict] = []
    for mkey in _morder:
        if mkey not in months_present:
            continue
        ms    = [s for s in stories if s["month"] == mkey]
        ready = sum(1 for s in ms if all(s.get(f) for f in _GATE_FIELDS))
        total = len(ms)
        pct   = round(ready / total * 100) if total else 0
        ns    = sum(1 for s in ms if not any(s.get(f) for f in _GATE_FIELDS))
        bc    = G if pct >= 80 else A if pct >= 50 else R
        badge = f"{pct}%" if mkey in ("M0","M1","M2") else f"{ns}ns"
        months.append({"key": mkey, "label": _mlabels.get(mkey, mkey),
                       "badge": badge, "bc": bc, "pct": pct})

    # ── Unique BAs and devs ───────────────────────────────────────────────────
    ba_names  = sorted({s["ba"] for s in stories if s["ba"] != BA_DEFAULT[0]})
    dev_names = sorted({
        s["dev"] for s in stories
        if s["dev"] not in ("Unassigned", "Not Specified", "")
    })

    # ── By-developer matrix ───────────────────────────────────────────────────
    MATRIX_MONTHS = _matrix_months()
    _SP = {
        "story_frozen": 0, "draft": 1, "not_started": 2,
    }
    dev_matrix: dict = {}
    for s in stories:
        dname = s["dev"]
        if dname in ("Unassigned", "Not Specified", ""):
            continue
        if dname not in dev_matrix:
            dev_matrix[dname] = {"role": s["dev_role"], "ns": 0,
                                  **{mk: None for mk in MATRIX_MONTHS}}
        mkey = s["month"]
        if mkey not in MATRIX_MONTHS:
            continue
        sk = _story_status_key(s)
        if dev_matrix[dname][mkey] is None:
            dev_matrix[dname][mkey] = (1, sk)
        else:
            cnt, csk = dev_matrix[dname][mkey]
            worst = csk if _SP.get(csk, 9) >= _SP.get(sk, 9) else sk
            dev_matrix[dname][mkey] = (cnt + 1, worst)
        if not any(s.get(f) for f in _GATE_FIELDS):
            dev_matrix[dname]["ns"] += 1

    # ── By-story matrix (M0/M1/M2 only, unique titles) ───────────────────────
    story_matrix: list[dict] = []
    seen: set = set()
    m012 = sorted(
        [s for s in stories if s["month"] in ("M0","M1","M2")],
        key=lambda x: (x["pri"], x["title"]),
    )
    for s in m012:
        if s["title"] in seen:
            continue
        seen.add(s["title"])
        sm = {
            "id":      s["id"],
            "title":   s["title"],
            "size":    s["size"],
            "pri":     s["pri"],
            "type":    s["type"],
            "ba":      s["ba"],
            "ba_code": s["ba_code"],
            **{mk: None for mk in MATRIX_MONTHS},
        }
        for ss in stories:
            if ss["title"] == s["title"] and ss["month"] in MATRIX_MONTHS:
                sm[ss["month"]] = (ss["dev"], _story_status_key(ss))
        story_matrix.append(sm)

    # ── Flat list for reactive dev matrix ────────────────────────────────────
    dev_stories_flat = [
        {"id": s["id"], "dev": s["dev"], "role": s["dev_role"], "month": s["month"]}
        for s in stories
        if s["dev"] not in ("Unassigned", "Not Specified", "")
        and s["month"] in MATRIX_MONTHS
    ]

    # ── Store in cache (gates excluded — always live) ─────────────────────────
    _stories_for_cache = [
        {k: v for k, v in s.items() if k not in _GATE_FIELDS}
        for s in stories
    ]
    _planning_cache["data"] = (_stories_for_cache, months, ba_names, dev_names,
                               dev_matrix, story_matrix, dev_stories_flat)
    _planning_cache["ts"] = _time.monotonic()

    return stories, months, init_gates, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _status(g: dict) -> str:
    done = sum(1 for f in _GATE_FIELDS if g.get(f))
    if done == len(_GATE_FIELDS):
        return "READY"
    if done > 0:
        return "IN PROGRESS"
    return "NOT STARTED"


def _pri_clr(p):   return {"P1": R, "P2": A, "P3": G, "P4": MT}.get(str(p), MT)
def _type_clr(t):  return {"ENH": P, "ISSUE": "#f59e0b"}.get(t, MT)
def _size_clr(s):  return {"Big": "#e879f9", "Medium": B, "Small": G, "Very Small": MT}.get(s or "", MT)


# ═══════════════════════════════════════════════════════════════════════════════
# REUSABLE COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

def _tag(text, color):
    return html.Span(text, style={
        "fontSize": "10px", "fontWeight": "700", "padding": "2px 7px",
        "borderRadius": "4px", "background": _dim(color), "color": color,
        "marginRight": "4px", "letterSpacing": "0.3px",
    })


def _gate_btn(sid, gate, checked):
    label = _GATE_LABELS.get(gate, gate)
    txt_c = "#ffffff" if checked else MT
    return html.Div(
        [
            html.Span("✓" if checked else "○",
                      style={"color": txt_c, "marginRight": "6px",
                             "fontSize": "11px", "fontWeight": "700", "flexShrink": "0"}),
            html.Span(label, style={"fontSize": "11px", "fontWeight": "600", "color": txt_c}),
        ],
        id={"type": "gate-open-btn", "sid": sid, "gate": gate},
        n_clicks=0,
        className=f"gate-pill {'gate-done' if checked else 'gate-pending'}",
        style={
            "padding":      "7px 12px",
            "cursor":       "pointer",
            "display":      "flex",
            "alignItems":   "center",
            "borderRadius": "6px",
            "marginBottom": "3px",
            "width":        "100%",
            "transition":   "all .2s",
            "background":   G if checked else "rgba(255,255,255,0.05)",
            "border":       f"1px solid {G}" if checked else f"1px solid {BD}",
        },
    )


def _status_badge(status, g):
    c    = STATUS_COLOR.get(status, MT)
    done = sum(1 for f in _GATE_FIELDS if g.get(f))
    total = len(_GATE_FIELDS)

    stuck_at = None
    if status == "IN PROGRESS":
        for f in _GATE_FIELDS:
            if not g.get(f):
                stuck_at = _GATE_LABELS.get(f, f)
                break

    rows = [
        html.Div([
            html.Span("●", style={"color": c, "marginRight": "5px", "fontSize": "9px"}),
            html.Span(status, style={"fontSize": "11px", "fontWeight": "700",
                                     "letterSpacing": "0.4px", "color": c}),
            html.Span(f"{done}/{total} gates",
                      style={"fontSize": "10px", "color": MT,
                             "marginLeft": "7px", "fontWeight": "500"}),
        ], style={"display": "flex", "alignItems": "center"}),
    ]
    if stuck_at:
        rows.append(
            html.Div(f"Stuck at: {stuck_at}",
                     style={"fontSize": "9px", "color": A, "marginTop": "3px",
                            "fontWeight": "600"})
        )

    return html.Div(rows, style={
        "background":    _dim(c),
        "border":        f"1px solid {_brd(c)}",
        "borderRadius":  "8px",
        "padding":       "7px 12px",
        "display":       "flex",
        "flexDirection": "column",
        "minWidth":      "140px",
    })


def _kpi_card(label, value_pct, sub, color=None, count=""):
    c = color or (G if value_pct >= 80 else A if value_pct >= 50 else R)
    return html.Div([
        html.Div(label, style={
            "fontSize": "10px", "fontWeight": "700", "color": MT,
            "textTransform": "uppercase", "letterSpacing": "0.8px",
            "marginBottom": "10px",
        }),
        html.Div([
            html.Span(f"{value_pct}%", style={
                "fontSize": "28px", "fontWeight": "800",
                "color": c, "lineHeight": "1", "marginRight": "10px", "flexShrink": "0",
            }),
            html.Span(count, style={
                "fontSize": "13px", "fontWeight": "600", "color": MT,
                "marginRight": "12px", "flexShrink": "0",
            }),
            html.Div([
                html.Div(style={
                    "width": f"{value_pct}%", "height": "3px",
                    "background": c, "borderRadius": "2px", "transition": "width .5s",
                }),
            ], style={
                "flex": "1", "height": "3px",
                "background": "rgba(255,255,255,0.08)", "borderRadius": "2px",
            }),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
        html.Div(sub, style={"fontSize": "10px", "color": MT, "lineHeight": "1.5"}),
    ], style={
        "background": CD, "border": f"1px solid {c}33",
        "borderRadius": "12px", "padding": "16px 18px",
        "flex": "1", "minWidth": "200px",
    })


def _ba_card(name, code, role, pct, done, total, color=None):
    c = color or (G if pct >= 80 else A if pct >= 50 else R)
    return html.Div([
        html.Div([
            html.Span(name, style={"fontWeight": "700", "color": TX, "fontSize": "13px"}),
            html.Span(f" {pct}%", style={"fontWeight": "800", "color": c,
                                          "fontSize": "15px", "marginLeft": "8px"}),
        ], style={"marginBottom": "4px"}),
        html.Div(html.Span(f"{code} · {role}", style={"fontSize": "10px", "color": MT})),
        html.Div([
            html.Div(style={"width": f"{pct}%", "height": "3px",
                             "background": c, "borderRadius": "2px"}),
        ], style={"width": "100%", "height": "3px",
                   "background": "rgba(255,255,255,0.08)",
                   "borderRadius": "2px", "margin": "8px 0"}),
        html.Div(f"{done} of {total} stories", style={"fontSize": "10px", "color": MT}),
    ], style={
        "background": C2, "border": f"1px solid {c}33",
        "borderRadius": "10px", "padding": "12px 16px",
        "minWidth": "160px", "flex": "1",
    })


def _matrix_cell(dev_key, month_key, val):
    _win_sep = {}
    if month_key == "M0":
        _win_sep["borderLeft"] = f"2px solid {_WIN_BORDER}"
    elif month_key == "M2":
        _win_sep["borderRight"] = f"2px solid {_WIN_BORDER}"
    if val is None:
        return html.Td("—", style={
            "textAlign": "center", "color": "rgba(255,255,255,0.15)",
            "fontSize": "12px", "padding": "10px 8px",
            "borderBottom": f"1px solid {BD}", **_win_sep,
        })
    count, sk = val
    cc = CELL_COLORS.get(sk, {"bg": C2, "text": MT, "border": BD})
    label_map = {
        "story_frozen": "READY", "draft": "IN PROG", "not_started": "NS",
    }
    return html.Td(
        html.Div([
            html.Div(str(count), style={"fontSize": "20px", "fontWeight": "700",
                                         "color": cc["text"], "lineHeight": "1"}),
            html.Div(label_map.get(sk, ""), style={"fontSize": "9px", "color": cc["text"],
                                                    "opacity": "0.7", "marginTop": "2px"}),
        ], style={
            "background":   cc["bg"],
            "border":       f"1px solid {cc['border']}44",
            "borderRadius": "8px", "padding": "10px 8px",
            "textAlign":    "center", "cursor": "pointer",
            "transition":   "opacity .15s",
        }, id={"type": "matrix-cell", "dev": dev_key, "month": month_key}),
        style={"padding": "6px", "borderBottom": f"1px solid {BD}", **_win_sep},
    )


def _alert(text, color=R):
    return html.Div(text, style={
        "background":   _dim(color),
        "border":       f"1px solid {_brd(color)}",
        "borderRadius": "8px", "padding": "10px 16px",
        "fontSize":     "12px", "color": color,
        "flex": "1", "lineHeight": "1.5",
    })


def _story_matrix_cell(val, month_key=""):
    _win_sep = {}
    if month_key == "M0":
        _win_sep["borderLeft"] = f"2px solid {_WIN_BORDER}"
    elif month_key == "M2":
        _win_sep["borderRight"] = f"2px solid {_WIN_BORDER}"
    if val is None:
        return html.Td("—", style={
            "textAlign": "center", "color": "rgba(255,255,255,0.12)",
            "fontSize": "11px", "padding": "8px 4px",
            "borderBottom": f"1px solid {BD}", **_win_sep,
        })
    dev_name, sk = val
    cc      = CELL_COLORS.get(sk, {"bg": C2, "text": MT, "border": BD})
    display = (dev_name.split()[0]
               if dev_name and dev_name not in ("Unassigned","Not Specified")
               else dev_name)
    return html.Td(
        html.Div(display, style={
            "background":   cc["bg"], "color": cc["text"],
            "border":       f"1px solid {cc['border']}44",
            "borderRadius": "6px", "padding": "5px 8px",
            "fontSize":     "11px", "fontWeight": "600",
            "textAlign":    "center", "cursor": "pointer",
        }),
        style={"padding": "5px 4px", "borderBottom": f"1px solid {BD}", **_win_sep},
    )


# ─── Story table ───────────────────────────────────────────────────────────────
_TH_S = {
    "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
    "letterSpacing": "0.5px", "color": MT, "padding": "10px 16px",
    "borderBottom": f"1px solid {BD}", "textAlign": "left",
}

story_table_header = html.Tr([
    html.Th("Story",          style={**_TH_S, "width": "32%"}),
    html.Th("Developer",      style={**_TH_S, "width": "12%"}),
    html.Th("BA Responsible", style={**_TH_S, "width": "13%"}),
    html.Th("Sign-Off Gates", style={**_TH_S, "width": "21%"}),
    html.Th("Status",         style={**_TH_S, "width": "15%"}),
    html.Th("Lifecycle",      style={**_TH_S, "width": "7%", "textAlign": "center"}),
])


def _story_row(s: dict, gates: dict) -> html.Tr:
    _default_g = {f: s.get(f, False) for f in _GATE_FIELDS}
    g      = gates.get(str(s["id"]), _default_g)
    status = _status(g)
    sc     = STATUS_COLOR.get(status, MT)

    tags = [_tag(s["pri"], _pri_clr(s["pri"])), _tag(s["type"], _type_clr(s["type"]))]
    if s.get("size"):
        tags.append(_tag(s["size"], _size_clr(s["size"])))
    if s.get("hrs"):
        tags.append(html.Span(f"{s['hrs']:.0f}h",
                               style={"fontSize": "10px", "color": MT, "marginLeft": "2px"}))

    gates_col = html.Div(
        [_gate_btn(s["id"], f, g.get(f, False)) for f in _GATE_FIELDS],
        style={"display": "flex", "flexDirection": "column", "gap": "2px"},
    )

    return html.Tr([
        html.Td([
            html.Div([
                html.A(f"#{s['id']}",
                       href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                       style={"color": P, "fontSize": "12px", "fontWeight": "700",
                              "textDecoration": "none", "letterSpacing": "0.3px",
                              "marginRight": "6px", "flexShrink": "0"}),
                html.Span(s.get("month", ""),
                          style={"color": MT, "fontSize": "9px", "fontWeight": "600",
                                 "background": BD, "padding": "1px 5px",
                                 "borderRadius": "3px"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
            html.A(s["title"],
                   href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                   style={"fontWeight": "600", "color": TX, "fontSize": "14px",
                          "marginBottom": "5px", "textDecoration": "none",
                          "display": "block", "lineHeight": "1.4"}),
            html.Div(tags, style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"}),
            html.Button("🕐 History", id={"type": "ticket-log-btn", "sid": s["id"]}, n_clicks=0,
                        style={"background": "none", "border": f"1px solid {BD}",
                               "borderRadius": "6px", "color": MT, "fontSize": "10px",
                               "cursor": "pointer", "padding": "2px 8px", "marginTop": "6px",
                               "transition": "color .15s"}),
        ], style={"padding": "18px 16px",
                   "borderLeft": f"3px solid {sc}",
                   "borderBottom": f"1px solid {BD}"}),
        html.Td([
            html.Div(s["dev"],      style={"color": TX, "fontSize": "13px", "fontWeight": "600"}),
            html.Div(s["dev_role"], style={"color": MT, "fontSize": "10px"}),
        ], style={"padding": "18px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td([
            html.Div(html.Span(s["ba"], style={"color": P, "fontSize": "12px", "fontWeight": "600"})),
            html.Div(f"{s['ba_code']} · {s['ba_role']}",
                     style={"color": MT, "fontSize": "10px", "marginTop": "2px"}),
        ], style={"padding": "18px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(gates_col, style={"padding": "12px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(_status_badge(status, g), style={"padding": "18px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(
            html.Button("📋", id={"type": "tracker-btn", "sid": s["id"]}, n_clicks=0,
                        title="Open lifecycle tracker",
                        style={"background": "none", "border": f"1px solid {BD}",
                               "borderRadius": "8px", "color": P, "fontSize": "16px",
                               "cursor": "pointer", "padding": "6px 10px",
                               "transition": "all .15s"}),
            style={"padding": "10px 8px", "borderBottom": f"1px solid {BD}",
                   "textAlign": "center"},
        ),
    ], style={"background": CD, "transition": "background .15s"})


# ─── Bug table ─────────────────────────────────────────────────────────────────
bug_table_header = html.Tr([
    html.Th("Issue",      style={**_TH_S, "width": "50%"}),
    html.Th("Developer",  style={**_TH_S, "width": "16%"}),
    html.Th("Estimated",  style={**_TH_S, "width": "14%"}),
    html.Th("Status",     style={**_TH_S, "width": "20%"}),
])

_BUG_TYPE_CLR = {"Bug": R, "Bug_UI": A, "Bug_Text": "#67e8f9"}
_BUG_STATE_CLR = {
    "Active": B, "Dev InProgress": B, "Dev Review": B, "Dev Complete": G,
    "Testing": A, "Tester Assigned": A, "Request Estimate": A,
    "Reopened": R, "Watch List": MT, "On Hold": MT,
}


def _bug_row(b: dict) -> html.Tr:
    tc   = _BUG_TYPE_CLR.get(b["type"], MT)
    tags = [_tag(b["pri"], _pri_clr(b["pri"])),
            _tag(b["type"].replace("_", " "), tc)]

    if b["estimated"]:
        est_cell = html.Div([
            html.Span("✓ Estimated",
                      style={"color": G, "fontSize": "11px", "fontWeight": "600"}),
            *([ html.Span(f"  {b['hrs']:.0f}h",
                          style={"color": MT, "fontSize": "10px", "marginLeft": "4px"})
               ] if b.get("hrs") else []),
        ])
    else:
        est_cell = html.Span("✗ Not Estimated",
                             style={"color": R, "fontSize": "11px", "fontWeight": "600"})

    sc = _BUG_STATE_CLR.get(b["state"], MT)
    state_badge = html.Span(b["state"], style={
        "fontSize": "11px", "fontWeight": "600", "color": sc,
        "background": f"{sc}18", "border": f"1px solid {sc}44",
        "borderRadius": "6px", "padding": "3px 8px",
    })

    return html.Tr([
        html.Td([
            html.Div([
                html.A(f"#{b['id']}",
                       href=f"{ADO_BASE_URL}{b['id']}", target="_blank",
                       style={"color": P, "fontSize": "10px", "fontWeight": "700",
                              "textDecoration": "none", "letterSpacing": "0.3px",
                              "marginRight": "6px", "flexShrink": "0"}),
                html.Span(b.get("month", ""),
                          style={"color": MT, "fontSize": "9px", "fontWeight": "600",
                                 "background": BD, "padding": "1px 5px", "borderRadius": "3px"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
            html.A(b["title"],
                   href=f"{ADO_BASE_URL}{b['id']}", target="_blank",
                   style={"fontWeight": "600", "color": TX, "fontSize": "13px",
                          "marginBottom": "5px", "textDecoration": "none",
                          "display": "block", "lineHeight": "1.4"}),
            html.Div(tags, style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"}),
        ], style={"padding": "14px 16px", "borderLeft": f"3px solid {tc}",
                  "borderBottom": f"1px solid {BD}"}),
        html.Td([
            html.Div(b["dev"],      style={"color": TX, "fontSize": "13px", "fontWeight": "600"}),
            html.Div(b["dev_role"], style={"color": MT, "fontSize": "10px"}),
        ], style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(est_cell,    style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
        html.Td(state_badge, style={"padding": "14px 16px", "borderBottom": f"1px solid {BD}"}),
    ], style={"background": CD, "transition": "background .15s"})


def _pagination_bar(page: int, total_pages: int,
                    prev_id: str, next_id: str) -> html.Div:
    if total_pages <= 1:
        return html.Div()
    _btn = lambda label, disabled, cid: html.Button(
        label, id=cid, n_clicks=0, disabled=disabled,
        style={
            "background": "transparent",
            "border": f"1px solid {BD}",
            "borderRadius": "6px",
            "color": MT if disabled else TX,
            "fontSize": "12px",
            "cursor": "default" if disabled else "pointer",
            "padding": "4px 14px",
            "transition": "all .15s",
        },
    )
    return html.Div([
        _btn("‹ Prev", page <= 1,           prev_id),
        html.Span(f"Page {page} of {total_pages}",
                  style={"color": MT, "fontSize": "12px", "padding": "0 14px"}),
        _btn("Next ›", page >= total_pages, next_id),
    ], style={
        "display": "flex", "alignItems": "center", "justifyContent": "center",
        "gap": "8px", "padding": "12px 0",
    })


# ─── Matrix builders ────────────────────────────────────────────────────────────
def _build_dev_matrix(dev_matrix: dict, today_month: int) -> html.Table:
    MATRIX_MONTHS = _matrix_months()
    _rest_count   = len(MATRIX_MONTHS) - 3  # columns after M2
    ml = {
        "M0": f"M0 · {_CAL[today_month]}",
        "M1": f"M1 · {_CAL[min(today_month+1, 12)]}",
        "M2": f"M2 · {_CAL[min(today_month+2, 12)]}",
    }
    for _, lbl in _CAL.items():
        ml[lbl] = lbl

    col_headers = [html.Th("Developer", style={**_TH_S, "minWidth": "160px"})]
    for mk in MATRIX_MONTHS:
        is_plan = mk in ("M0","M1","M2")
        _hborder = {}
        if mk == "M0":
            _hborder = {"borderLeft":  f"2px solid {_WIN_BORDER}",
                        "borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M1":
            _hborder = {"borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M2":
            _hborder = {"borderTop":   f"2px solid {_WIN_BORDER}",
                        "borderRight": f"2px solid {_WIN_BORDER}"}
        col_headers.append(html.Th(ml.get(mk, mk), style={
            **_TH_S, "textAlign": "center", "minWidth": "80px",
            "color": B if mk == "M0" else P if is_plan else MT,
            **_hborder,
        }))
    col_headers.append(html.Th("Total", style={**_TH_S, "textAlign": "center"}))

    rows = []
    # Sort by total assigned items descending
    for dev_name, dv in sorted(
        dev_matrix.items(),
        key=lambda x: -sum(v[0] for v in x[1].values() if isinstance(v, tuple)),
    ):
        cells = [html.Td([
            html.Div(dev_name,  style={"color": TX, "fontWeight": "600", "fontSize": "13px"}),
            html.Div(dv["role"], style={"color": MT, "fontSize": "10px"}),
            html.Div(f"{dv['ns']} not started",
                     style={"color": R, "fontSize": "10px", "marginTop": "2px"}),
        ], style={"padding": "12px 16px", "borderBottom": f"1px solid {BD}", "minWidth": "160px"})]

        total = 0
        for mk in MATRIX_MONTHS:
            val = dv.get(mk)
            cells.append(_matrix_cell(dev_name, mk, val))
            if val:
                total += val[0]

        cells.append(html.Td(
            str(total) if total else "—",
            style={"textAlign": "center", "color": MT, "fontSize": "12px",
                   "fontWeight": "600", "padding": "10px 8px",
                   "borderBottom": f"1px solid {BD}"},
        ))
        rows.append(html.Tr(cells, style={"background": CD}))

    _sep_cells = [
        html.Td(),
        html.Td("← 1+2 PLANNING WINDOW →", colSpan=3, style={
            "textAlign": "center", "fontSize": "10px", "color": P,
            "fontWeight": "700", "letterSpacing": "0.5px",
            "padding": "6px", "background": P_DIM, "borderBottom": f"1px solid {BD}",
            "borderLeft":  f"2px solid {_WIN_BORDER}",
            "borderTop":   f"2px solid {_WIN_BORDER}",
            "borderRight": f"2px solid {_WIN_BORDER}",
        }),
    ]
    if _rest_count > 0:
        _sep_cells.append(html.Td("← REST OF 2026 →", colSpan=_rest_count, style={
            "textAlign": "center", "fontSize": "10px", "color": MT,
            "fontWeight": "700", "letterSpacing": "0.5px",
            "padding": "6px", "background": "rgba(255,255,255,0.02)",
            "borderBottom": f"1px solid {BD}",
        }))
    _sep_cells.append(html.Td())
    separator = html.Tr(_sep_cells)
    return html.Table(
        [html.Thead([separator, html.Tr(col_headers)]), html.Tbody(rows)],
        className="dev-matrix",
        style={"width": "100%", "borderCollapse": "collapse", "background": CD},
    )


def _build_story_matrix(story_matrix: list) -> html.Table:
    MATRIX_MONTHS = _matrix_months()
    _rest_count   = len(MATRIX_MONTHS) - 3
    col_headers = [
        html.Th("Story / Title + BA", style={**_TH_S, "minWidth": "220px"}),
        html.Th("Size",               style={**_TH_S, "width": "60px"}),
    ]
    for mk in MATRIX_MONTHS:
        is_plan = mk in ("M0","M1","M2")
        _shborder = {}
        if mk == "M0":
            _shborder = {"borderLeft":  f"2px solid {_WIN_BORDER}",
                         "borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M1":
            _shborder = {"borderTop":   f"2px solid {_WIN_BORDER}"}
        elif mk == "M2":
            _shborder = {"borderTop":   f"2px solid {_WIN_BORDER}",
                         "borderRight": f"2px solid {_WIN_BORDER}"}
        col_headers.append(html.Th(mk, style={
            **_TH_S, "textAlign": "center", "minWidth": "70px",
            "color": B if mk == "M0" else P if is_plan else MT,
            **_shborder,
        }))

    rows = []
    for sm in story_matrix:
        size_tag = _tag(sm["size"], _size_clr(sm["size"])) if sm["size"] else html.Span()
        id_link  = html.A(
            f"#{sm['id']}",
            href=f"{ADO_BASE_URL}{sm['id']}", target="_blank",
            style={"color": P, "fontSize": "10px", "fontWeight": "700",
                   "textDecoration": "none", "letterSpacing": "0.3px", "flexShrink": "0"},
        )
        ba_chip  = html.Span(
            f"● {sm['ba']}  ·  {sm['ba_code']}",
            style={"fontSize": "10px", "color": P, "display": "block", "marginTop": "3px"},
        )
        cells = [
            html.Td([
                html.Div(
                    [_tag(sm["pri"], _pri_clr(sm["pri"])),
                     _tag(sm["type"], _type_clr(sm["type"])),
                     id_link,
                     html.A(sm["title"],
                            href=f"{ADO_BASE_URL}{sm['id']}", target="_blank",
                            style={"color": TX, "fontSize": "12px", "fontWeight": "600",
                                   "textDecoration": "none"})],
                    style={"display": "flex", "alignItems": "center",
                           "flexWrap": "wrap", "gap": "4px"},
                ),
                ba_chip,
            ], style={"padding": "10px 16px", "borderBottom": f"1px solid {BD}"}),
            html.Td(size_tag, style={"padding": "10px 8px", "borderBottom": f"1px solid {BD}"}),
        ]
        for mk in MATRIX_MONTHS:
            cells.append(_story_matrix_cell(sm.get(mk), mk))
        rows.append(html.Tr(cells, style={"background": CD}))

    _sep_cells = [
        html.Td(), html.Td(),
        html.Td("← 1+2 PLANNING WINDOW →", colSpan=3, style={
            "textAlign": "center", "fontSize": "10px", "color": P,
            "fontWeight": "700", "padding": "6px",
            "background": P_DIM, "borderBottom": f"1px solid {BD}",
            "borderLeft":  f"2px solid {_WIN_BORDER}",
            "borderTop":   f"2px solid {_WIN_BORDER}",
            "borderRight": f"2px solid {_WIN_BORDER}",
        }),
    ]
    if _rest_count > 0:
        _sep_cells.append(html.Td("← REST OF 2026 →", colSpan=_rest_count, style={
            "textAlign": "center", "fontSize": "10px", "color": MT,
            "fontWeight": "700", "padding": "6px",
            "background": "rgba(255,255,255,0.02)", "borderBottom": f"1px solid {BD}",
        }))
    separator = html.Tr(_sep_cells)
    return html.Table(
        [html.Thead([separator, html.Tr(col_headers)]), html.Tbody(rows)],
        className="story-matrix",
        style={"width": "100%", "borderCollapse": "collapse", "background": CD},
    )


# ─── BA Team Brief ──────────────────────────────────────────────────────────────

_BA_ROLES = [
    {
        "code": "R-01",
        "title": "Backlog Steward",
        "subtitle": "Data integrity & prioritisation",
        "responsibilities": [
            ("Issue Triage",        "Maintain all VSTS issues from Jan 2024 onwards. Classify every item by type (customer / internal) and priority (P1 → P4). No item remains unclassified for more than 2 working days."),
            ("Enhancement Triage",  "Maintain all VSTS enhancements from inception. Tag each as customer-identified or internally-identified, and size as Big / Medium / Small / Very Small. Customer Big and Medium enhancements are always surfaced first."),
            ("Priority Sequencing", "Enforce agreed priority logic in VSTS: Customer P1 Issues → Customer Big/Medium Enhancements → Internally Identified Enhancements → Lower-priority Issues. Sequencing must be visible and defensible on demand."),
            ("Backlog Hygiene",     "Every active item must carry a type, priority, size, and status. Audit weekly. Any item open ≥ 2 weeks without all four fields is a hygiene failure and escalated immediately."),
        ],
    },
    {
        "code": "R-02",
        "title": "Story Writer (M1/M2)",
        "subtitle": "Story production for the live sprint window",
        "responsibilities": [
            ("M1 Story Delivery",  "Write, review with the Product Owner, and deliver all M1 stories fully before the first day of that month. Zero exceptions."),
            ("M2 Draft Coverage",  "Produce draft stories for all M2 items by mid-M1, with acceptance criteria locked. Estimation can begin as soon as drafts are in place."),
            ("M0 Support",         "During the current month, answer developer clarification questions only. No new writing for M0 — if a story is unclear at M0, that is a M1 process failure."),
            ("Quality Assurance",  "Own story rejection rate. Every story returned by a developer due to ambiguity or missing criteria is reviewed to identify and close the root cause."),
        ],
    },
    {
        "code": "R-03",
        "title": "Pipeline & Horizon Owner",
        "subtitle": "Long-range readiness through Dec 2026",
        "responsibilities": [
            ("Long-Horizon Library",      "Ensure all customer P1 Issues and Big/Medium Enhancements through Dec 2026 have user stories written and kept estimation-ready."),
            ("Estimation Coordination",   "Facilitate estimation sessions with developers for M1/M2 and long-horizon items. Track estimated vs unestimated items weekly."),
            ("Roadmap Alignment",         "Flag conflicts between the prioritised backlog and the delivery roadmap. Escalate to the Product Owner when capacity in any month is forecast to be exceeded."),
            ("Sprint Discipline",         "Ensure the team is always writing one month ahead of where developers are building. Identify drift early and recover before it affects developer throughput."),
        ],
    },
]


def _ba_role_card(role: dict, open_: bool = False) -> html.Div:
    rows = [
        html.Div([
            html.Span(lbl, style={
                "fontFamily": "monospace", "fontSize": "11px", "fontWeight": "700",
                "color": A, "minWidth": "180px", "paddingRight": "20px",
                "flexShrink": "0",
            }),
            html.Span(desc, style={"fontSize": "13px", "color": TX, "lineHeight": "1.6"}),
        ], style={"display": "flex", "padding": "12px 0",
                  "borderBottom": f"1px solid {BD}"})
        for lbl, desc in role["responsibilities"]
    ]
    body = html.Div(rows, id={"type": "ba-role-body", "role": role["code"]},
                    style={"display": "block" if open_ else "none",
                           "padding": "4px 24px 20px"})

    header = html.Div([
        html.Div([
            html.Span(role["code"], style={
                "fontSize": "10px", "fontWeight": "700", "color": A,
                "fontFamily": "monospace", "marginRight": "14px",
                "background": A_DIM, "border": f"1px solid {A_BRD}",
                "borderRadius": "4px", "padding": "2px 8px",
            }),
            html.Div([
                html.Div(role["title"],    style={"fontWeight": "700", "fontSize": "15px", "color": TX}),
                html.Div(role["subtitle"], style={"fontSize": "11px", "color": MT, "marginTop": "2px"}),
            ]),
        ], style={"display": "flex", "alignItems": "center", "flex": "1"}),
        html.Button(
            "×" if open_ else "+",
            id={"type": "ba-role-toggle", "role": role["code"]},
            n_clicks=0,
            style={
                "background": "none", "border": "none",
                "color": MT, "fontSize": "22px", "cursor": "pointer",
                "lineHeight": "1", "padding": "2px 6px",
            },
        ),
    ], style={"display": "flex", "alignItems": "center", "padding": "18px 20px",
              "cursor": "pointer"})

    return html.Div([header, body], style={
        "background": C2, "borderRadius": "12px",
        "border": f"1px solid {BD}", "marginBottom": "12px",
        "overflow": "hidden",
    })


def _build_ba_brief() -> html.Div:
    # ── Sub-tab strip ─────────────────────────────────────────────────────────
    sub_tabs = html.Div([
        html.Button(lbl, id={"type": "ba-brief-tab", "tab": tid}, n_clicks=0,
                    style={
                        "background":   A_DIM if i == 0 else "transparent",
                        "border":       "none",
                        "borderBottom": f"2px solid {A}" if i == 0 else "2px solid transparent",
                        "color":        TX if i == 0 else MT,
                        "fontSize":     "13px", "fontWeight": "600" if i == 0 else "400",
                        "padding":      "8px 16px", "cursor": "pointer", "marginRight": "4px",
                    })
        for i, (lbl, tid) in enumerate([
            ("Role Brief",          "role"),
            ("KPI Scorecard",       "kpi"),
            ("Operating Principles","ops"),
        ])
    ], style={"display": "flex", "borderBottom": f"1px solid {BD}",
              "marginBottom": "28px"})

    # ── Role Brief content ────────────────────────────────────────────────────
    intro = html.P([
        "The BA team has two distinct functions: ",
        html.Strong("backlog stewardship", style={"color": TX}),
        " and ",
        html.Strong("story production", style={"color": TX}),
        ". The three roles below ensure neither crowds out the other.",
    ], style={"color": MT, "fontSize": "14px", "lineHeight": "1.7",
              "marginBottom": "24px"})

    role_cards = html.Div(
        [_ba_role_card(r, open_=(r["code"] == "R-01")) for r in _BA_ROLES],
        id="ba-role-cards",
    )

    note = html.Div([
        html.Div("NOTE · TEAM COMPOSITION", style={
            "fontSize": "9px", "fontWeight": "700", "color": G,
            "letterSpacing": "1.4px", "textTransform": "uppercase", "marginBottom": "8px",
        }),
        html.P(
            "Roles can be held by three individuals or distributed differently. "
            "KPIs are role-indexed, not person-indexed, so accountability remains "
            "clear regardless of assignment.",
            style={"color": MT, "fontSize": "13px", "lineHeight": "1.6", "margin": "0"},
        ),
    ], style={
        "background": G_DIM, "border": f"1px solid {G_BRD}",
        "borderRadius": "10px", "padding": "16px 20px", "marginTop": "8px",
    })

    role_brief = html.Div([intro, role_cards, note], id="ba-tab-role",
                          style={"display": "block"})

    placeholder = html.Div(
        "Coming soon.",
        style={"color": MT, "fontSize": "14px", "padding": "40px 0"},
    )
    kpi_tab = html.Div(placeholder, id="ba-tab-kpi",  style={"display": "none"})
    ops_tab = html.Div(placeholder, id="ba-tab-ops",  style={"display": "none"})

    return html.Div([
        # ── Page header ───────────────────────────────────────────────────────
        html.Div([
            html.Div("BA TEAM · ROLE BRIEF & KPI SCORECARD", style={
                "fontSize": "9px", "fontWeight": "700", "color": A,
                "letterSpacing": "1.6px", "textTransform": "uppercase", "marginBottom": "8px",
            }),
            html.Div("BA Team Brief · Roles, KPIs & Principles", style={
                "fontSize": "26px", "fontWeight": "800", "color": TX, "marginBottom": "6px",
            }),
            html.Div("3-person team · 1+2 sprint planning model · VSTS-sourced backlog", style={
                "fontSize": "13px", "color": MT,
            }),
        ], style={"marginBottom": "28px"}),
        sub_tabs,
        role_brief, kpi_tab, ops_tab,
    ], style={"maxWidth": "860px", "padding": "8px 0"})


# ─── Static components ──────────────────────────────────────────────────────────
_legend = html.Div([
    *[html.Span([
        html.Span("■ ", style={"color": c}),
        html.Span(lbl, style={"color": MT, "fontSize": "11px", "marginRight": "14px"}),
    ]) for lbl, c in [("Ready", G), ("In Progress", A), ("Not Started", R)]],
    html.Span("— Click any cell for stories",
              style={"color": MT, "fontSize": "11px", "fontStyle": "italic"}),
], style={"display": "flex", "alignItems": "center", "marginBottom": "12px"})

signoff_modal = dbc.Modal([
    dbc.ModalHeader(
        html.Span("📋 Sign-Off Log", style={"fontWeight": "700", "color": TX}),
        style={"background": CD, "borderBottom": f"1px solid {BD}"},
    ),
    dbc.ModalBody(
        html.Div(id="log-body"),
        style={"background": CD, "maxHeight": "60vh", "overflowY": "auto"},
    ),
    dbc.ModalFooter(
        html.Div(id="log-footer"),
        style={"background": CD, "borderTop": f"1px solid {BD}"},
    ),
], id="signoff-modal", is_open=False, size="lg",
   style={"--bs-modal-bg": CD, "--bs-modal-border-color": BD})

ticket_log_modal = dbc.Modal([
    dbc.ModalHeader(
        html.Div(id="tlog-header"),
        style={"background": CD, "borderBottom": f"1px solid {BD}"},
    ),
    dbc.ModalBody(
        html.Div(id="tlog-body"),
        style={"background": CD, "maxHeight": "65vh", "overflowY": "auto"},
    ),
    dbc.ModalFooter(
        html.Div(id="tlog-footer"),
        style={"background": CD, "borderTop": f"1px solid {BD}"},
    ),
], id="tlog-modal", is_open=False, size="lg",
   style={"--bs-modal-bg": CD, "--bs-modal-border-color": BD})

tracker_modal = dbc.Modal([
    dbc.ModalHeader(
        html.Div(id="tracker-header"),
        style={"background": CD, "borderBottom": f"1px solid {BD}", "flexDirection": "column",
               "alignItems": "flex-start"},
        close_button=True,
    ),
    dbc.ModalBody(
        html.Div(id="tracker-body"),
        style={"background": C3, "padding": "20px 24px",
               "maxHeight": "75vh", "overflowY": "auto"},
    ),
], id="tracker-modal", is_open=False, size="xl",
   style={"--bs-modal-bg": C3, "--bs-modal-border-color": BD},
   scrollable=True)

# ── Capacity matrix panel styles (needed before matrix_panel definition) ──────
_CAP_PANEL_BASE   = {
    "position": "fixed", "top": "0", "right": "0",
    "height": "100vh", "width": "760px",
    "background": C2,
    "borderLeft": "1px solid rgba(255,255,255,0.10)",
    "zIndex": "1050",
    "display": "flex", "flexDirection": "column",
    "boxShadow": "-16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_CAP_PANEL_OPEN   = {**_CAP_PANEL_BASE, "transform": "translateX(0%)"}
_CAP_PANEL_CLOSED = {**_CAP_PANEL_BASE, "transform": "translateX(110%)"}

matrix_panel = html.Div([
    # Fixed header — dev name + month + close
    html.Div([
        html.Div([
            html.Div(id="matrix-panel-hdr", style={
                "fontWeight": "700", "fontSize": "15px", "color": TX,
            }),
        ], style={"flex": "1"}),
        html.Button("✕", id="matrix-panel-close", n_clicks=0, style={
            "background": "none", "border": "none", "color": MT,
            "fontSize": "20px", "cursor": "pointer",
            "padding": "2px 8px", "lineHeight": "1",
        }),
    ], style={
        "display": "flex", "alignItems": "flex-start",
        "padding": "18px 20px 14px",
        "borderBottom": f"1px solid {BD}",
        "flexShrink": "0",
    }),
    # Scrollable body
    html.Div(id="matrix-panel-body",
             style={"overflowY": "auto", "flex": "1", "padding": "0"}),
], id="matrix-panel", style=_CAP_PANEL_CLOSED)


def _type_filter_strip(sizes=False):
    _btn = lambda lbl, active=False: html.Button(
        lbl,
        id={"type": "type-f", "v": lbl},
        style={
            "background":   (A + "33") if active else "transparent",
            "border":       f"1px solid {A}" if active else f"1px solid {BD}",
            "borderRadius": "12px",
            "color":        A if active else MT,
            "fontSize":     "11px",
            "fontWeight":   "700" if active else "400",
            "padding":      "3px 10px", "cursor": "pointer", "marginRight": "4px",
        },
    )
    items = [
        html.Span("TYPE", style={"fontSize": "10px", "fontWeight": "700", "color": MT,
                                  "textTransform": "uppercase", "letterSpacing": "0.5px",
                                  "marginRight": "6px"}),
        _btn("All", active=True), _btn("Enhancements"), _btn("Issues"),
    ]
    if sizes:
        items += [
            html.Div(style={"width": "1px", "height": "16px",
                             "background": BD, "margin": "0 10px"}),
            html.Span("SIZE", style={"fontSize": "10px", "fontWeight": "700", "color": MT,
                                      "textTransform": "uppercase", "letterSpacing": "0.5px",
                                      "marginRight": "6px"}),
            *[html.Button(lbl, id={"type": "size-f", "v": lbl}, style={
                "background": "transparent", "border": f"1px solid {BD}",
                "borderRadius": "12px", "color": MT, "fontSize": "11px",
                "padding": "3px 10px", "cursor": "pointer", "marginRight": "4px",
            }) for lbl in ["All", "Big", "Medium", "Small", "Very Small"]],
        ]
    return html.Div(items, style={"display": "flex", "alignItems": "center",
                                   "marginBottom": "12px", "flexWrap": "wrap"})


_footer = html.Div([
    html.Span("ExpenseOnDemand · Planning Tool · expenseondemand / Solo Expenses",
              style={"color": MT, "fontSize": "10px"}),
    html.Span("Data: open Enhancements & Bugs in 2026 ADO iterations · Refreshes every 5 min",
              style={"color": MT, "fontSize": "10px"}),
], style={"display": "flex", "justifyContent": "space-between",
           "borderTop": f"1px solid {BD}", "paddingTop": "14px", "marginTop": "24px"})


# ═══════════════════════════════════════════════════════════════════════════════
# UNESTIMATED TAB BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

# filter key → color (used both in builder and in callback to restore card style)
_UNEST_CARD_COLORS = {
    "all":    R,
    "p1":     R,
    "issues": A,
    "enhanc": G,
    "devsp1": "#e879f9",
}


def _kcard_style(color: str, active: bool) -> dict:
    return {
        "background":   _dim(color) if active else CD,
        "border":       f"1px solid {color}" if active else f"1px solid {_brd(color)}",
        "borderRadius": "12px", "padding": "18px 22px", "flex": "1", "minWidth": "160px",
        "cursor": "pointer", "transition": "all .15s",
        "boxShadow": f"0 0 18px {_brd(color)}" if active else "none",
    }


# ── Side panel style constants ────────────────────────────────────────────────
_PANEL_BASE = {
    "position": "fixed", "top": "0", "right": "0",
    "height": "100vh", "width": "500px",
    "background": C2,
    "borderLeft": f"1px solid rgba(255,255,255,0.10)",
    "zIndex": "1050",
    "display": "flex", "flexDirection": "column",
    "boxShadow": "-16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_PANEL_OPEN   = {**_PANEL_BASE, "transform": "translateX(0%)"}
_PANEL_CLOSED = {**_PANEL_BASE, "transform": "translateX(110%)"}

_BACKDROP_BASE = {
    "position": "fixed", "top": "0", "left": "0",
    "width": "100vw", "height": "100vh",
    "background": "rgba(0,0,0,0.50)",
    "zIndex": "1049",
    "transition": "opacity 0.28s ease",
}
_BACKDROP_OPEN   = {**_BACKDROP_BASE, "opacity": "1",  "pointerEvents": "all"}
_BACKDROP_CLOSED = {**_BACKDROP_BASE, "opacity": "0",  "pointerEvents": "none"}

_FLT_PANEL_BASE = {
    "position": "fixed", "top": "0", "left": "0",
    "height": "100vh", "width": "310px",
    "background": C2,
    "borderRight": f"1px solid rgba(255,255,255,0.10)",
    "zIndex": "1050",
    "display": "flex", "flexDirection": "column",
    "boxShadow": "16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_FLT_PANEL_OPEN   = {**_FLT_PANEL_BASE, "transform": "translateX(0%)"}
_FLT_PANEL_CLOSED = {**_FLT_PANEL_BASE, "transform": "translateX(-110%)"}


def _build_unest_tab(items: list[dict], hide_cards: set | None = None) -> html.Div:
    """Build full content for the Unestimated Items tab from pre-loaded items."""
    unest_only = [s for s in items if s["est_status"] in ("unestimated", "partial")]
    if not items:
        return html.Div("No items found.",
                        style={"color": G, "fontSize": "14px", "padding": "32px"})

    total        = len(unest_only)
    p1_count     = sum(1 for s in unest_only if s["pri"] == "P1")
    issues       = sum(1 for s in unest_only if s["type"] == "Issue")
    enhancements = sum(1 for s in unest_only if s["type"] == "Enhancement")
    partial      = sum(1 for s in unest_only if s["est_status"] == "partial")
    devs_p1      = len({s["dev"] for s in unest_only
                        if s["pri"] == "P1" and s["dev"] not in ("Unassigned","Not Specified","")})
    total_devs   = len({s["dev"] for s in unest_only
                        if s["dev"] not in ("Unassigned","Not Specified","")})

    iss_pct = round(issues / total * 100) if total else 0
    enh_pct = round(enhancements / total * 100) if total else 0

    def _kcard(val, label, sub, fkey):
        color = _UNEST_CARD_COLORS[fkey]
        return html.Div([
            html.Div(str(val), style={"fontSize": "38px", "fontWeight": "800",
                                      "color": color, "lineHeight": "1"}),
            html.Div(label, style={"fontSize": "10px", "fontWeight": "700",
                                   "color": MT, "textTransform": "uppercase",
                                   "letterSpacing": "0.8px", "marginTop": "8px"}),
            html.Div(sub,   style={"fontSize": "11px", "color": MT, "marginTop": "4px"}),
        ], id={"type": "unest-kcard", "filter": fkey},
           n_clicks=0,
           style=_kcard_style(color, False))

    _hc = hide_cards or set()
    kpi_strip = html.Div([
        _kcard(total,        "Total Unestimated", f"{partial} partial (some tasks missing)", "all"),
        _kcard(p1_count,     "P1 Items",          "Highest urgency",                          "p1"),
        *([_kcard(issues,       "Issues",       f"{iss_pct}% of total", "issues")]  if "issues" not in _hc else []),
        *([_kcard(enhancements, "Enhancements", f"{enh_pct}% of total", "enhanc")]  if "enhanc" not in _hc else []),
        _kcard(devs_p1,      "Devs with P1 Gap",  f"of {total_devs} developers",              "devsp1"),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "16px", "flexWrap": "wrap"})

    # ── Developer × Month matrix ───────────────────────────────────────────────
    month_order = ["M0","M1","M2","Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]
    months_present = sorted({s["month"] for s in items},
                            key=lambda x: month_order.index(x) if x in month_order else 99)

    # Build dev → month → {est, unest, p1_unest, p2_unest} counts
    dev_month: dict = {}
    for s in items:
        dev = s["dev"]
        if dev in ("Unassigned","Not Specified",""):
            continue
        mon = s["month"]
        if dev not in dev_month:
            dev_month[dev] = {m: {"est": 0, "unest": 0, "p1_unest": 0, "p2_unest": 0} for m in month_order}
        if s["est_status"] in ("estimated", "estimated_via_tasks"):
            dev_month[dev][mon]["est"] += 1
        else:
            dev_month[dev][mon]["unest"] += 1
            if s["pri"] == "P1": dev_month[dev][mon]["p1_unest"] += 1
            if s["pri"] == "P2": dev_month[dev][mon]["p2_unest"] += 1

    # Sort devs by total unestimated desc
    sorted_devs = sorted(dev_month.keys(),
                         key=lambda d: -sum(v["unest"] for v in dev_month[d].values()))

    today_m = date.today().month
    _mlbl = {"M0": f"M0·{_CAL[today_m]}",
             "M1": f"M1·{_CAL[min(today_m+1,12)]}",
             "M2": f"M2·{_CAL[min(today_m+2,12)]}"}
    for _, lbl in _CAL.items(): _mlbl[lbl] = lbl

    th_s = {"fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
            "letterSpacing": "0.5px", "color": MT, "padding": "10px 12px",
            "borderBottom": f"1px solid {BD}", "textAlign": "center"}

    hdr = [html.Th("Developer", style={**th_s, "textAlign": "left", "minWidth": "150px"})]
    for mk in months_present:
        hdr.append(html.Th(_mlbl.get(mk, mk), style={
            **th_s, "color": B if mk == "M0" else P if mk in ("M1","M2") else MT,
        }))
    hdr.append(html.Th("Total", style={**th_s}))

    mat_rows = []
    for dev in sorted_devs:
        dm        = dev_month[dev]
        role      = _DEV_ROLE.get(TEAM_MAPPING.get(dev, ""), "Developer")
        tot       = sum(dm[mk]["est"] + dm[mk]["unest"] for mk in months_present)
        unest_tot = sum(dm[mk]["unest"] for mk in months_present)
        cells = [html.Td([
            html.Div(dev,  style={"color": TX, "fontWeight": "600", "fontSize": "13px"}),
            html.Div(role, style={"color": MT, "fontSize": "10px"}),
        ], style={"padding": "10px 14px", "borderBottom": f"1px solid {BD}"})]

        for mk in months_present:
            est_n   = dm[mk]["est"]
            unest_n = dm[mk]["unest"]
            p1      = dm[mk]["p1_unest"]
            p2      = dm[mk]["p2_unest"]
            if est_n == 0 and unest_n == 0:
                cells.append(html.Td("—", style={
                    "textAlign": "center", "color": "rgba(255,255,255,0.15)",
                    "fontSize": "12px", "padding": "10px 8px",
                    "borderBottom": f"1px solid {BD}",
                }))
            else:
                clr_u = R if p1 > 0 else A if p2 > 0 else MT
                sub_btns = []
                if est_n > 0:
                    sub_btns.append(html.Div([
                        html.Div(str(est_n), style={"fontSize": "15px", "fontWeight": "700",
                                                    "color": G, "lineHeight": "1"}),
                        html.Div("est", style={"fontSize": "8px", "color": G,
                                               "marginTop": "1px", "opacity": "0.7"}),
                    ],
                    id={"type": "unest-matrix-cell", "dev": dev, "month": mk, "est_type": "e"},
                    n_clicks=0,
                    style={"background": G_DIM, "border": f"1px solid {G_BRD}",
                           "borderRadius": "6px", "padding": "5px 8px", "textAlign": "center",
                           "cursor": "pointer", "transition": "opacity .15s", "marginBottom": "3px"},
                    ))
                if unest_n > 0:
                    sub_btns.append(html.Div([
                        html.Div(str(unest_n), style={"fontSize": "15px", "fontWeight": "700",
                                                      "color": clr_u, "lineHeight": "1"}),
                        html.Div(f"P1:{p1}" if p1 else "unest",
                                 style={"fontSize": "8px", "color": R if p1 else MT,
                                        "marginTop": "1px"}),
                    ],
                    id={"type": "unest-matrix-cell", "dev": dev, "month": mk, "est_type": "u"},
                    n_clicks=0,
                    style={"background": _dim(clr_u), "border": f"1px solid {_brd(clr_u)}",
                           "borderRadius": "6px", "padding": "5px 8px", "textAlign": "center",
                           "cursor": "pointer", "transition": "opacity .15s"},
                    ))
                cells.append(html.Td(
                    html.Div(sub_btns, style={"display": "flex", "flexDirection": "column"}),
                    style={"padding": "4px 6px", "borderBottom": f"1px solid {BD}"},
                ))

        cells.append(html.Td([
            html.Div(str(unest_tot), style={"fontWeight": "700", "fontSize": "14px",
                                            "color": R if unest_tot > 5 else A}),
            html.Div(f"+{tot - unest_tot} est" if (tot - unest_tot) > 0 else "",
                     style={"fontSize": "9px", "color": G}),
        ], style={"textAlign": "center", "padding": "10px 8px",
                   "borderBottom": f"1px solid {BD}"}))
        mat_rows.append(html.Tr(cells, style={"background": CD}))

    matrix = html.Div([
        html.Div("Estimated vs Unestimated · Developer × Month",
                 style={"fontWeight": "700", "color": TX, "fontSize": "14px",
                        "marginBottom": "12px"}),
        html.Div(
            html.Table(
                [html.Thead(html.Tr(hdr)), html.Tbody(mat_rows)],
                style={"width": "100%", "borderCollapse": "collapse", "background": CD},
            ),
            style={"background": CD, "borderRadius": "12px",
                   "border": f"1px solid {BD}", "overflow": "auto", "marginBottom": "20px"},
        ),
    ])

    # ── Priority Breakdown table ───────────────────────────────────────────────
    # Build dev → {P1, P2, P3, P4} counts (unestimated only)
    dev_pri: dict = {}
    for s in unest_only:
        dev = s["dev"]
        if dev in ("Unassigned","Not Specified",""):
            continue
        if dev not in dev_pri:
            dev_pri[dev] = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
        dev_pri[dev][s["pri"]] = dev_pri[dev].get(s["pri"], 0) + 1

    sorted_devs_p = sorted(dev_pri.keys(),
                           key=lambda d: -(dev_pri[d]["P1"]*1000 + dev_pri[d]["P2"]*100
                                          + dev_pri[d]["P3"]*10 + dev_pri[d]["P4"]))

    _td = lambda v, c=MT: html.Td(
        str(v) if v else "—",
        style={"textAlign": "center", "color": c if v else "rgba(255,255,255,0.15)",
               "fontWeight": "700" if v else "400", "fontSize": "13px",
               "padding": "12px 8px", "borderBottom": f"1px solid {BD}"},
    )
    _th2 = lambda t, w="80px": html.Th(t, style={
        "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
        "color": MT, "padding": "10px 8px", "borderBottom": f"1px solid {BD}",
        "textAlign": "center", "width": w,
    })

    pb_rows = []
    for dev in sorted_devs_p:
        dp   = dev_pri[dev]
        tot  = sum(dp.values())
        role = _DEV_ROLE.get(TEAM_MAPPING.get(dev, ""), "Developer")
        risk_lbl, risk_c = (
            ("HIGH",   R) if dp["P1"] > 0 else
            ("MEDIUM", A) if dp["P2"] > 0 else
            ("LOW",    G)
        )
        pb_rows.append(html.Tr([
            html.Td([
                html.Div(dev,  style={"color": TX, "fontWeight": "600", "fontSize": "13px"}),
                html.Div(role, style={"color": MT, "fontSize": "10px"}),
            ], style={"padding": "12px 16px", "borderBottom": f"1px solid {BD}"}),
            _td(dp["P1"], R),
            _td(dp["P2"], A),
            _td(dp["P3"], G),
            _td(dp["P4"], MT),
            html.Td(str(tot), style={
                "textAlign": "center", "color": TX, "fontWeight": "800",
                "fontSize": "14px", "padding": "12px 8px",
                "borderBottom": f"1px solid {BD}",
            }),
            html.Td(html.Span(risk_lbl, style={
                "background": f"{risk_c}22", "color": risk_c,
                "border": f"1px solid {risk_c}55", "borderRadius": "6px",
                "padding": "3px 10px", "fontSize": "11px", "fontWeight": "700",
            }), style={"textAlign": "center", "padding": "12px 8px",
                       "borderBottom": f"1px solid {BD}"}),
        ], style={"background": CD}))

    pri_table = html.Div([
        html.Div("Priority Breakdown by Developer",
                 style={"fontWeight": "700", "color": TX, "fontSize": "14px",
                        "marginBottom": "4px"}),
        html.Div("Total unestimated items per developer, split by priority",
                 style={"color": MT, "fontSize": "11px", "marginBottom": "12px"}),
        html.Div(
            html.Table([
                html.Thead(html.Tr([
                    html.Th("Developer", style={
                        "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
                        "color": MT, "padding": "10px 16px", "borderBottom": f"1px solid {BD}",
                        "textAlign": "left",
                    }),
                    _th2("P1"), _th2("P2"), _th2("P3"), _th2("P4"),
                    _th2("Total"), _th2("Risk"),
                ])),
                html.Tbody(pb_rows),
            ], style={"width": "100%", "borderCollapse": "collapse", "background": CD}),
            style={"background": CD, "borderRadius": "12px",
                   "border": f"1px solid {BD}", "overflow": "hidden"},
        ),
    ])

    # ── Partial estimates callout ──────────────────────────────────────────────
    partial_note = html.Div([], style={"display": "none"})
    if partial > 0:
        partial_note = html.Div([
            html.Span("⚠ ", style={"marginRight": "6px"}),
            html.Span(f"{partial} items have partial task estimates — "
                      "click a card to find them.",
                      style={"fontSize": "12px"}),
        ], style={
            "background": A_DIM, "border": f"1px solid {A_BRD}",
            "borderRadius": "8px", "padding": "10px 16px",
            "color": A, "marginBottom": "12px",
        })

    panel_hint = html.Div(
        "↑ Click a card to see the items",
        style={"color": MT, "fontSize": "11px", "textAlign": "center",
               "padding": "10px 0", "marginBottom": "16px",
               "border": f"1px dashed {BD}", "borderRadius": "8px"},
    )

    _lbl_s = {"fontSize": "10px", "color": MT, "fontWeight": "600", "marginBottom": "3px"}
    return html.Div([
        kpi_strip,
        html.Div(id="unest-ctrl-bar", children=[
            html.Div([
                html.Div("Sort", style=_lbl_s),
                dcc.Dropdown(
                    id="unest-srt-ctrl",
                    options=[{"label": l, "value": v} for l, v in
                             [("Month", "month"), ("Priority", "pri"), ("Release", "rd")]],
                    value="month", clearable=False,
                    style={"minWidth": "130px", "fontSize": "11px"},
                ),
            ]),
            html.Div([
                html.Div("Developer", style=_lbl_s),
                dcc.Dropdown(
                    id="unest-dev-ctrl",
                    options=[{"label": "All Devs", "value": "all"}],
                    value="all", clearable=False,
                    style={"minWidth": "180px", "fontSize": "11px"},
                ),
            ]),
        ], style={"display": "none", "gap": "10px", "alignItems": "flex-end",
                  "marginBottom": "10px"}),
        html.Div(id="unest-item-panel", children=panel_hint),
        partial_note,
        html.Div(
            "↑ Click a cell to see items for that developer × month",
            style={"color": MT, "fontSize": "11px", "marginBottom": "8px",
                   "textAlign": "right"},
        ),
        matrix,
        pri_table,
        _footer,
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT  (function — executed fresh on every page visit)
# ═══════════════════════════════════════════════════════════════════════════════
# DELIVERY TIMELINE (GANTT) HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _gantt_window(view: str = "0-12"):
    """Return (window_start, window_end, label) for a rolling view.
    view: '0-12' rolling 12M from today | '12-24' months 12-24 | '24+' months 24-36.
    """
    def _add_months(d: date, n: int) -> date:
        m = d.month - 1 + n
        return date(d.year + m // 12, m % 12 + 1, 1)

    base = date.today()
    base = date(base.year, base.month, 1)   # snap to month start
    if view == "12-24":
        ws = _add_months(base, 12)
        we = _add_months(base, 24)
    elif view == "24+":
        ws = _add_months(base, 24)
        we = _add_months(base, 36)
    else:                                    # default "0-12"
        ws = base
        we = _add_months(base, 12)
    label = f"{ws.strftime('%b %Y')} – {(we - timedelta(days=1)).strftime('%b %Y')}"
    return ws, we, label


def _parse_release_date(rd_str):
    """Parse free-text release_date ('2026 July', '2026-07-31', …) → date or None.
    'YYYY MonthName' strings (year + month only) resolve to the last day of that month."""
    if not rd_str or rd_str in ("Not Specified", "nan", ""):
        return None
    # Check for "YYYY MonthName" pattern FIRST — pd.to_datetime would return the 1st,
    # but a release target without a day should mean end-of-month.
    m = re.match(r"^(\d{4})\s+([A-Za-z]+)$", str(rd_str).strip())
    if m:
        try:
            ts = pd.to_datetime("1 " + m.group(2) + " " + m.group(1))
            last = _cal_lib.monthrange(ts.year, ts.month)[1]
            return date(ts.year, ts.month, last)
        except Exception:
            pass
    try:
        return pd.to_datetime(rd_str).date()
    except Exception:
        pass
    return None


def _build_gantt_html(
    window_start: date,
    window_end: date,
    expanded_sprints: set,   # expanded developer keys
    expanded_items: set,     # expanded function keys + expanded item wids
    dev_filter: set | None = None,
    type_filter: str = "all",           # "all" | "enh" | "bug"
    prio_filter: list | None = None,    # None = all; list of "1","2","3","4+"
    year_filter: list | None = None,    # None = all; list of int years
    cust_filter: str = "all",           # "all" | "Customer" | "Internal"
) -> html.Div:
    """HTML/CSS Gantt — Developer > Function > Item > Task hierarchy."""
    from data.loader import engine
    from sqlalchemy import text as _text

    today = date.today()
    _NONE = html.Div("No active work items match the current filters.",
                     style={"color": MT, "padding": "20px", "fontSize": "12px"})

    # ── Load from module-level cache (refreshes every 5 min) ──────────────────
    _now = _time_mod.time()
    if _GANTT_CACHE["items"] is None or _now - _GANTT_CACHE["ts"] > _GANTT_TTL:
        with engine.connect() as _c:
            _GANTT_CACHE["items"] = pd.read_sql(
                _text("SELECT * FROM agg_gantt_items ORDER BY main_developer, function, bar_start"),
                _c,
            )
            _GANTT_CACHE["tasks"] = pd.read_sql(
                _text("SELECT * FROM agg_gantt_tasks"), _c,
            )
        _GANTT_CACHE["ts"] = _now

    items_df = _GANTT_CACHE["items"].copy()
    _task_df  = _GANTT_CACHE["tasks"].copy()

    # ── Date conversion ────────────────────────────────────────────────────────
    for _dc in ("bar_start", "bar_end", "release_date"):
        if _dc in items_df.columns:
            items_df[_dc] = pd.to_datetime(items_df[_dc], errors="coerce").dt.date
    for _dc in ("bar_start", "bar_end"):
        if _dc in _task_df.columns:
            _task_df[_dc] = pd.to_datetime(_task_df[_dc], errors="coerce").dt.date

    # ── Build tasks-by-parent lookup ──────────────────────────────────────────
    tasks_by_parent: dict[int, list] = {}
    for _tr in _task_df.to_dict("records"):
        _pid = _tr.get("parent_id")
        if _pid is not None and _pid == _pid:  # NaN check (NaN != NaN)
            tasks_by_parent.setdefault(int(_pid), []).append(_tr)

    # ── Apply filters ─────────────────────────────────────────────────────────
    if dev_filter:
        items_df = items_df[items_df["main_developer"].isin(dev_filter)]

    if type_filter == "enh":
        items_df = items_df[items_df["item_type"] == "enh"]
    elif type_filter == "bug":
        items_df = items_df[items_df["item_type"] == "bug"]

    if prio_filter:
        _eff_prios: set[int] = set()
        for _p in prio_filter:
            if _p == "4+":
                _eff_prios.update({4, 5, 6, 7})
            else:
                try: _eff_prios.add(int(_p))
                except (ValueError, TypeError): pass
        items_df = items_df[items_df["priority"].isin(_eff_prios)]

    if year_filter:
        items_df = items_df[items_df["bar_start"].apply(
            lambda x: x.year if isinstance(x, date) else None
        ).isin(year_filter)]

    if cust_filter and cust_filter != "all" and "customer_type" in items_df.columns:
        items_df = items_df[items_df["customer_type"].fillna("").str.strip() == cust_filter]

    if items_df.empty:
        return _NONE

    # ── Timeline helpers ───────────────────────────────────────────────────────
    total_days = max((window_end - window_start).days, 1)

    def _pp(d: date) -> float:
        return max(0.0, min(100.0, (d - window_start).days / total_days * 100))

    _months: list = []
    _m = date(window_start.year, window_start.month, 1)
    while _m < window_end:
        _months.append(_m)
        _nm = _m.month % 12 + 1
        _ny = _m.year + (1 if _m.month == 12 else 0)
        _m  = date(_ny, _nm, 1)

    _mon_ends = [
        _months[i + 1] if i + 1 < len(_months) else window_end
        for i in range(len(_months))
    ]
    _mon_widths = [
        (min(me, window_end) - max(ms, window_start)).days / total_days * 100
        for ms, me in zip(_months, _mon_ends)
    ]

    # ── Quarter header groups ─────────────────────────────────────────────────
    _Q_MAP = {1:"Q1",2:"Q1",3:"Q1",4:"Q2",5:"Q2",6:"Q2",
              7:"Q3",8:"Q3",9:"Q3",10:"Q4",11:"Q4",12:"Q4"}
    _qtr_groups: list = []
    _cur_q, _cur_w = None, 0.0
    for i, m in enumerate(_months):
        q = f"{_Q_MAP[m.month]} {m.year}"
        if q != _cur_q:
            if _cur_q is not None:
                _qtr_groups.append((_cur_q, _cur_w))
            _cur_q, _cur_w = q, _mon_widths[i]
        else:
            _cur_w += _mon_widths[i]
    if _cur_q is not None:
        _qtr_groups.append((_cur_q, _cur_w))

    # ── Release helpers ───────────────────────────────────────────────────────
    _RELEASES = {
        "R1": date(2026, 3, 31),
        "R2": date(2026, 6, 30),
        "R3": date(2026, 9, 30),
        "R4": date(2026, 12, 18),
    }
    _RE_LINE = "rgba(211,111,104,0.5)"

    def _rel_label(d: date):
        for lbl, cutoff in _RELEASES.items():
            if d <= cutoff:
                return lbl
        return None

    # ── Design tokens ─────────────────────────────────────────────────────────
    _B1      = "var(--border)"
    _SF      = "var(--bg-elevated)"
    _RA      = "var(--bg-hover)"
    _PG      = "var(--bg-base)"
    _T1      = "var(--text-primary)"
    _T2      = "var(--text-secondary)"
    _GR      = "var(--green)"
    _AM      = "#C17D2A"
    _BL      = "var(--blue)"
    _RE_COL  = "rgba(211,111,104,0.6)"
    _COL_DIV = "rgba(117,168,177,0.15)"
    DEV_W    = 130              # developer column
    FUNC_W   = 200              # function column
    LABEL_W  = DEV_W + FUNC_W  # 330px — offset for today/release overlays
    DEV_H    = 34
    FUNC_H   = 32
    ITEM_H   = 30

    # ── Month dividers ────────────────────────────────────────────────────────
    def _divs():
        return [
            html.Div(style={
                "position": "absolute", "top": 0, "bottom": 0,
                "left": f"{_pp(m)}%", "width": "0.5px",
                "background": _B1, "pointerEvents": "none",
            })
            for m in _months[1:]
        ]

    _DIV_CELLS = _divs()  # compute once; list() copy at each use site

    # ── Progress cell ──────────────────────────────────────────────────────────
    def _prog_cell(pct):
        if pct >= 100:   bar_color = _GR
        elif pct > 50:   bar_color = _BL
        elif pct > 20:   bar_color = _AM
        else:            bar_color = "var(--red)"
        return html.Div([
            html.Span(f"{pct}%", style={"fontSize": "9px", "color": _T2, "lineHeight": "1"}),
            html.Div(
                html.Div(style={"width": f"{pct}%", "height": "100%",
                                "borderRadius": "2px", "background": bar_color}),
                style={"height": "4px", "borderRadius": "2px",
                       "background": "rgba(255,255,255,0.07)", "overflow": "hidden"}
            ),
        ], style={"display": "flex", "flexDirection": "column", "gap": "3px", "width": "100%"})

    # ── Type tag ───────────────────────────────────────────────────────────────
    def _type_tag(item_type):
        is_bug = item_type == "bug"
        return html.Span("BUG" if is_bug else "ENH", style={
            "fontSize": "8px", "fontWeight": "600", "padding": "1px 5px",
            "borderRadius": "4px", "letterSpacing": "0.03em", "flexShrink": "0",
            "lineHeight": "14px",
            "background": "rgba(211,111,104,0.12)" if is_bug else "rgba(107,158,208,0.12)",
            "color": "var(--red)" if is_bug else _BL,
            "border": "0.5px solid rgba(211,111,104,0.25)" if is_bug
                      else "0.5px solid rgba(107,158,208,0.25)",
        })

    # ── Timeline bar with CSS hover tooltip ───────────────────────────────────
    def _bar_with_tooltip(it, s_cl, e_cl, pct, is_bug, row_h):
        rem_color = _RE_COL if is_bug else _AM
        tl_ch = list(_DIV_CELLS)

        if s_cl < e_cl:
            bl = _pp(s_cl)
            bw = (e_cl - s_cl).days / total_days * 100
            parts = []
            if pct > 0:
                parts.append(html.Div(style={
                    "width": f"{pct}%", "height": "100%", "background": _GR,
                    "borderRadius": "3px 0 0 3px" if pct < 100 else "3px",
                }))
            if pct < 100:
                parts.append(html.Div(style={
                    "width": f"{100-pct}%", "height": "100%", "background": rem_color,
                    "borderRadius": "0 3px 3px 0" if pct > 0 else "3px",
                }))

            # Tooltip content
            _i_end   = it.get("bar_end")
            rel_lbl  = (_rel_label(_i_end) if _i_end else None) or "—"
            rel_date = _i_end.strftime("%d %b %Y") if _i_end else "—"
            est      = it.get("original_estimate") or 0
            rem      = it.get("t_rem") or 0
            state    = str(it.get("state", "—"))
            assigned = str(it.get("assigned_to") or "").strip()
            if not assigned or assigned in ("Unassigned", "nan", "None", ""):
                assigned = str(it.get("main_developer") or "—").strip()
            iter_lbl = it.get("month_label") or it.get("iteration_path", "—")

            tooltip = html.Div([
                html.Div([html.Span("Sprint  ", style={"color": _T2}),
                          html.Span(iter_lbl, style={"color": _T1, "fontWeight": "500"})]),
                html.Div([html.Span("Release  ", style={"color": _T2}),
                          html.Span(f"{rel_lbl} · {rel_date}", style={"color": _T1})]),
                html.Div([html.Span("State  ", style={"color": _T2}),
                          html.Span(state, style={"color": _T1})]),
                html.Div([html.Span("Assigned  ", style={"color": _T2}),
                          html.Span(assigned[:28], style={"color": _T1})]),
                html.Div([html.Span("Estimate  ", style={"color": _T2}),
                          html.Span(f"{est}h", style={"color": _T1})]),
                html.Div([html.Span("Remaining  ", style={"color": _T2}),
                          html.Span(f"{rem}h", style={"color": _T1})]),
            ], className="gantt-tooltip")

            tl_ch.append(html.Div([
                html.Div(parts, style={"width": "100%", "height": "100%", "display": "flex"}),
                tooltip,
            ], className="gantt-bar-wrap", style={
                "left": f"{bl:.2f}%", "width": f"{bw:.2f}%",
                "height": "10px", "top": "50%", "transform": "translateY(-50%)",
                "display": "flex",
            }))

        # Diamond target-date marker
        ms = it.get("bar_end")
        if ms and window_start <= ms <= window_end:
            mp = _pp(ms)
            tl_ch.append(html.Div(style={
                "position": "absolute",
                "left": f"calc({mp:.2f}% - 4.5px)", "top": "50%", "marginTop": "-4.5px",
                "width": "9px", "height": "9px",
                "background": _BL, "transform": "rotate(45deg)",
                "borderRadius": "1.5px", "zIndex": "5", "pointerEvents": "none",
            }))

        return html.Div(tl_ch, style={
            "flex": "1", "position": "relative", "height": f"{row_h}px",
        })

    TASK_H = 26

    # ── Item sub-row (under a function; expandable if it has tasks) ────────────
    def _func_item_row(it, has_tasks, is_item_exp):
        s_cl  = max(it.get("bar_start") or today, window_start)
        e_cl  = min(it.get("bar_end")   or today, window_end)
        pct   = it.get("pct", 0) or 0
        is_bug = it.get("item_type", "enh") == "bug"
        wid   = it.get("work_item_id", "")

        toggle_btn = html.Button(
            "▼" if is_item_exp else "▶",
            id={"type": "gantt-toggle", "index": f"item:{wid}"}, n_clicks=0,
            style={"background": "none", "border": "none", "cursor": "pointer",
                   "color": _T2, "fontSize": "8px",
                   "padding": "0 3px 0 4px", "lineHeight": "1", "flexShrink": "0"},
        ) if has_tasks else html.Div(style={"width": "18px", "flexShrink": "0"})

        return html.Div([
            html.Div(style={
                "width": f"{DEV_W}px", "flexShrink": "0", "height": f"{ITEM_H}px",
                "background": _RA, "borderRight": f"0.5px solid {_COL_DIV}",
            }),
            html.Div([
                html.Div(style={"width": "14px", "flexShrink": "0"}),  # indent
                toggle_btn,
                _type_tag(it.get("item_type", "enh")),
                html.A(
                    str(it.get("title", ""))[:44],
                    href=f"{ADO_BASE_URL}{wid}", target="_blank",
                    style={
                        "fontSize": "10px", "color": _T2,
                        "whiteSpace": "nowrap", "overflow": "hidden",
                        "textOverflow": "ellipsis", "textDecoration": "none",
                        "flex": "1", "minWidth": "0",
                    },
                ),
            ], style={
                "width": f"{FUNC_W}px", "flexShrink": "0", "height": f"{ITEM_H}px",
                "display": "flex", "alignItems": "center",
                "padding": "0 8px 0 0", "gap": "4px",
                "borderRight": f"0.5px solid {_B1}", "overflow": "hidden",
                "background": _RA,
            }),
            _bar_with_tooltip(it, s_cl, e_cl, pct, is_bug, ITEM_H),
        ], style={"display": "flex", "borderBottom": f"0.5px solid rgba(255,255,255,0.04)"})

    # ── Task sub-row (child of an item) ────────────────────────────────────────
    def _task_row(task):
        t_start = task.get("bar_start") or window_start
        t_end   = task.get("bar_end")   or window_end
        t_start = max(t_start, window_start)
        t_end   = min(t_end,   window_end)
        pct_t   = int(task.get("pct") or 0)
        state   = str(task.get("state") or "To Do")
        task_id = task.get("task_id", "")
        t_color = (_GR if pct_t >= 100 else
                   _BL if state in ("Active", "In Progress") else
                   "var(--red)" if state == "Blocked" else _AM)
        tl_ch = list(_DIV_CELLS)
        if t_start < t_end:
            tl_ch.append(html.Div(style={
                "position": "absolute",
                "left": f"{_pp(t_start):.2f}%",
                "width": f"{(t_end - t_start).days / total_days * 100:.2f}%",
                "height": "5px", "top": "50%", "transform": "translateY(-50%)",
                "background": t_color, "opacity": "0.7", "borderRadius": "2px",
            }))
        return html.Div([
            html.Div(style={
                "width": f"{DEV_W}px", "flexShrink": "0", "height": f"{TASK_H}px",
                "background": "var(--bg-hover)", "borderRight": f"0.5px solid {_COL_DIV}",
            }),
            html.Div([
                html.Div(style={"width": "34px", "flexShrink": "0"}),  # indent
                html.Span("TASK", style={
                    "fontSize": "7px", "fontWeight": "600", "padding": "1px 4px",
                    "borderRadius": "3px", "flexShrink": "0", "lineHeight": "14px",
                    "background": "rgba(152,131,199,0.12)", "color": "var(--purple)",
                    "border": "0.5px solid rgba(152,131,199,0.25)",
                }),
                html.A(str(task.get("title", ""))[:40],
                    href=f"{ADO_BASE_URL}{task_id}", target="_blank",
                    style={"fontSize": "9px", "color": _T2, "whiteSpace": "nowrap",
                           "overflow": "hidden", "textOverflow": "ellipsis",
                           "textDecoration": "none", "flex": "1", "minWidth": "0"}),
            ], style={
                "width": f"{FUNC_W}px", "flexShrink": "0", "height": f"{TASK_H}px",
                "display": "flex", "alignItems": "center", "gap": "4px",
                "padding": "0 8px 0 0", "borderRight": f"0.5px solid {_B1}",
                "overflow": "hidden", "background": "var(--bg-hover)",
            }),
            html.Div(tl_ch, style={
                "flex": "1", "position": "relative", "height": f"{TASK_H}px",
                "background": "var(--bg-hover)",
            }),
        ], style={"display": "flex",
                  "borderBottom": f"0.5px solid rgba(255,255,255,0.03)"})

    # ── Pre-group records once: dev -> func -> [item dicts] ───────────────────
    # Avoids repeated DataFrame slicing (was 274 to_dict calls, one per func group)
    def _norm(v, default):
        return default if v is None or v != v else str(v)  # v != v catches NaN

    _dev_func_map: dict[str, dict[str, list]] = {}
    _dev_order: list[str] = []
    for _rec in items_df.to_dict("records"):
        _dv = _norm(_rec.get("main_developer"), "Unassigned")
        _fn = _norm(_rec.get("function"), "—")
        if _dv not in _dev_func_map:
            _dev_func_map[_dv] = {}
            _dev_order.append(_dv)
        _dev_func_map[_dv].setdefault(_fn, []).append(_rec)

    # ── Build all rows (Developer > Function hierarchy) ────────────────────────
    all_rows: list = []

    for dev in _dev_order:
        dev_funcs  = _dev_func_map[dev]
        _funcs     = list(dev_funcs.keys())
        _dev_items = [it for grp in dev_funcs.values() for it in grp]
        n_items    = len(_dev_items)
        n_funcs    = len(_funcs)
        safe_dev   = re.sub(r"[^a-zA-Z0-9]", "_", str(dev))
        is_dev_exp = safe_dev in expanded_sprints

        # Developer aggregate bar
        _dev_starts = [it["bar_start"] for it in _dev_items if it.get("bar_start") and it["bar_start"] == it["bar_start"]]
        _dev_ends   = [it["bar_end"]   for it in _dev_items if it.get("bar_end")   and it["bar_end"]   == it["bar_end"]]
        dev_s = max(min(_dev_starts, default=window_start), window_start)
        dev_e = min(max(_dev_ends,   default=window_end),   window_end)
        dev_tl = list(_DIV_CELLS)
        if dev_s < dev_e:
            dev_tl.append(html.Div(style={
                "position": "absolute",
                "left": f"{_pp(dev_s):.2f}%",
                "width": f"{(dev_e - dev_s).days / total_days * 100:.2f}%",
                "height": "4px", "top": "50%", "transform": "translateY(-50%)",
                "background": _BL, "opacity": "0.15", "borderRadius": "2px",
            }))

        # Developer header row
        _dev_top = "1.5px solid var(--border)" if all_rows else "none"
        all_rows.append(html.Div([
            html.Div([
                html.Button(
                    "▼" if is_dev_exp else "▶",
                    id={"type": "gantt-toggle", "index": f"dev:{safe_dev}"}, n_clicks=0,
                    style={"background": "none", "border": "none", "cursor": "pointer",
                           "color": _BL, "fontSize": "10px",
                           "padding": "0 6px 0 8px", "lineHeight": "1", "flexShrink": "0"},
                ),
                html.Span(str(dev), style={"fontSize": "12px", "fontWeight": "700", "color": _T1}),
                html.Span(f"  {n_funcs} functions · {n_items} items",
                          style={"fontSize": "10px", "color": _T2}),
            ], style={
                "width": f"{LABEL_W}px", "flexShrink": "0", "height": f"{DEV_H}px",
                "display": "flex", "alignItems": "center", "gap": "4px",
                "background": _SF, "borderRight": f"0.5px solid {_B1}",
            }),
            html.Div(dev_tl, style={
                "flex": "1", "position": "relative", "height": f"{DEV_H}px",
                "background": _SF,
            }),
        ], style={
            "display": "flex", "borderBottom": f"0.5px solid {_B1}",
            "borderTop": _dev_top, "background": _SF,
        }))

        # Function rows (children of developer)
        func_children: list = []
        for func in _funcs:
            func_items = dev_funcs[func]
            if not func_items:
                continue
            safe_fk    = re.sub(r"[^a-zA-Z0-9]", "_", f"{dev}_{func}")
            is_func_exp = safe_fk in expanded_items

            n_enh = sum(1 for it in func_items if it.get("item_type") == "enh")
            n_bug = sum(1 for it in func_items if it.get("item_type") == "bug")
            has_bugs = n_bug > 0

            # Aggregate bar for function
            _f_starts = [it["bar_start"] for it in func_items if it.get("bar_start") and pd.notna(it.get("bar_start"))]
            _f_ends   = [it["bar_end"]   for it in func_items if it.get("bar_end")   and pd.notna(it.get("bar_end"))]
            f_s = max(min(_f_starts, default=window_start), window_start)
            f_e = min(max(_f_ends,   default=window_end),   window_end)
            avg_pct = int(sum(it.get("pct", 0) or 0 for it in func_items) / len(func_items)) if func_items else 0
            rem_color = _RE_COL if has_bugs else _AM

            func_tl = list(_DIV_CELLS)
            if f_s < f_e:
                _bl = _pp(f_s)
                _bw = (f_e - f_s).days / total_days * 100
                _parts = []
                if avg_pct > 0:
                    _parts.append(html.Div(style={
                        "width": f"{avg_pct}%", "height": "100%", "background": _GR,
                        "borderRadius": "3px 0 0 3px" if avg_pct < 100 else "3px",
                    }))
                if avg_pct < 100:
                    _parts.append(html.Div(style={
                        "width": f"{100-avg_pct}%", "height": "100%", "background": rem_color,
                        "borderRadius": "0 3px 3px 0" if avg_pct > 0 else "3px",
                    }))
                func_tl.append(html.Div(_parts, className="gantt-bar-wrap", style={
                    "left": f"{_bl:.2f}%", "width": f"{_bw:.2f}%",
                    "height": "10px", "top": "50%", "transform": "translateY(-50%)",
                    "display": "flex",
                }))
                # Diamond target marker (latest end)
                if _f_ends and window_start <= max(_f_ends) <= window_end:
                    _mp = _pp(max(_f_ends))
                    func_tl.append(html.Div(style={
                        "position": "absolute",
                        "left": f"calc({_mp:.2f}% - 4.5px)", "top": "50%", "marginTop": "-4.5px",
                        "width": "9px", "height": "9px",
                        "background": _BL, "transform": "rotate(45deg)",
                        "borderRadius": "1.5px", "zIndex": "5", "pointerEvents": "none",
                    }))

            # Count chips
            _chips = []
            if n_enh:
                _chips.append(html.Span(f"{n_enh} ENH", style={
                    "fontSize": "8px", "fontWeight": "600", "padding": "1px 5px",
                    "borderRadius": "4px", "background": "rgba(107,158,208,0.12)",
                    "color": _BL, "border": "0.5px solid rgba(107,158,208,0.25)",
                    "lineHeight": "14px", "flexShrink": "0",
                }))
            if n_bug:
                _chips.append(html.Span(f"{n_bug} BUG", style={
                    "fontSize": "8px", "fontWeight": "600", "padding": "1px 5px",
                    "borderRadius": "4px", "background": "rgba(211,111,104,0.12)",
                    "color": "var(--red)", "border": "0.5px solid rgba(211,111,104,0.25)",
                    "lineHeight": "14px", "flexShrink": "0",
                }))

            func_children.append(html.Div([
                html.Div(style={
                    "width": f"{DEV_W}px", "flexShrink": "0", "height": f"{FUNC_H}px",
                    "background": _PG, "borderRight": f"0.5px solid {_COL_DIV}",
                }),
                html.Div([
                    html.Button(
                        "▼" if is_func_exp else "▶",
                        id={"type": "gantt-toggle", "index": f"func:{safe_fk}"}, n_clicks=0,
                        style={"background": "none", "border": "none", "cursor": "pointer",
                               "color": _T2, "fontSize": "9px",
                               "padding": "0 4px 0 6px", "lineHeight": "1", "flexShrink": "0"},
                    ),
                    html.Span(str(func)[:30], style={
                        "fontSize": "11px", "color": _T1, "fontWeight": "500",
                        "whiteSpace": "nowrap", "overflow": "hidden",
                        "textOverflow": "ellipsis", "flex": "1", "minWidth": "0",
                    }),
                    *_chips,
                ], style={
                    "width": f"{FUNC_W}px", "flexShrink": "0", "height": f"{FUNC_H}px",
                    "display": "flex", "alignItems": "center",
                    "padding": "0 8px 0 0", "gap": "5px",
                    "borderRight": f"0.5px solid {_B1}", "overflow": "hidden",
                    "background": _PG,
                }),
                html.Div(func_tl, style={
                    "flex": "1", "position": "relative", "height": f"{FUNC_H}px",
                }),
            ], style={"display": "flex", "borderBottom": f"0.5px solid {_B1}"}))

            # Item sub-rows + task children (expandable from function)
            _item_rows = []
            for _it in func_items:
                _wid      = _it.get("work_item_id")
                _it_tasks = tasks_by_parent.get(_wid, [])
                _has_t    = len(_it_tasks) > 0
                _is_ie    = str(_wid) in expanded_items
                _item_rows.append(_func_item_row(_it, _has_t, _is_ie))
                if _it_tasks:
                    _item_rows.append(html.Div(
                        [_task_row(t) for t in _it_tasks],
                        id=f"gantt-it-{_wid}",
                        style={"display": "block" if _is_ie else "none"},
                    ))
            func_children.append(html.Div(
                _item_rows,
                id=f"gantt-it-func-{safe_fk}",
                style={"display": "block" if is_func_exp else "none"},
            ))

        all_rows.append(html.Div(func_children, id=f"gantt-si-dev-{safe_dev}",
                                 style={"display": "block" if is_dev_exp else "none"}))

    # ── Today + release overlays (positioned to cover only the timeline column) ─
    overlay_els: list = []
    if window_start <= today < window_end:
        tp = _pp(today)
        overlay_els += [
            html.Div(style={
                "position": "absolute", "left": f"{tp:.2f}%", "top": 0, "bottom": 0,
                "width": "1.5px", "background": "rgba(117,168,177,0.5)",
                "zIndex": "10", "pointerEvents": "none",
            }),
            html.Div("TODAY", style={
                "position": "absolute", "left": f"{tp:.2f}%", "top": "4px",
                "transform": "translateX(-50%)", "whiteSpace": "nowrap",
                "fontSize": "8px", "color": "var(--blue)", "letterSpacing": "0.03em",
                "pointerEvents": "none", "zIndex": "11",
            }),
        ]

    _rel_hdr_labels: list = []
    for lbl, rd in _RELEASES.items():
        if window_start <= rd <= window_end:
            rp = _pp(rd)
            overlay_els.append(html.Div(style={
                "position": "absolute", "left": f"{rp:.2f}%", "top": 0, "bottom": 0,
                "width": "1.5px", "background": _RE_LINE,
                "zIndex": "8", "pointerEvents": "none",
            }))
            _rel_hdr_labels.append(html.Div(lbl, style={
                "position": "absolute", "left": f"{rp:.2f}%",
                "top": "50%", "transform": "translate(-50%, -50%)",
                "fontSize": "8px", "fontWeight": "600",
                "color": "rgba(211,111,104,0.9)",
                "background": "var(--bg-hover)", "padding": "1px 4px",
                "borderRadius": "3px", "pointerEvents": "none", "zIndex": "5",
            }))

    # Overlay container covers only the timeline column (skip label cols)
    overlay_container = html.Div(overlay_els, style={
        "position": "absolute", "top": 0, "bottom": 0,
        "left": f"{LABEL_W}px", "right": 0,
        "pointerEvents": "none", "zIndex": "20",
    }) if overlay_els else html.Div()

    # ── Quarter + Month header ─────────────────────────────────────────────────
    qtr_cols = [
        html.Div(lbl, style={
            "width": f"{w:.2f}%", "flexShrink": "0",
            "display": "flex", "alignItems": "center", "padding": "0 10px", "height": "22px",
            "borderRight": f"0.5px solid {_B1}" if i < len(_qtr_groups) - 1 else "none",
            "fontSize": "9px", "color": "var(--blue)",
            "letterSpacing": "0.06em", "textTransform": "uppercase", "fontWeight": "500",
        })
        for i, (lbl, w) in enumerate(_qtr_groups)
    ]

    hdr_cols = [
        html.Div(m.strftime("%b %Y"), style={
            "width": f"{_mon_widths[i]:.2f}%", "flexShrink": "0",
            "display": "flex", "alignItems": "center", "padding": "0 10px", "height": "30px",
            "borderRight": "none" if i == len(_months) - 1 else f"0.5px solid {_B1}",
            "fontSize": "10px",
            "color": _T1 if m.year == today.year and m.month == today.month else _T2,
            "fontWeight": "500" if m.year == today.year and m.month == today.month else "400",
        })
        for i, m in enumerate(_months)
    ]

    # ── Column headers ─────────────────────────────────────────────────────────
    _ch_base = {
        "display": "flex", "alignItems": "flex-end", "padding": "0 8px 7px",
        "height": "52px", "background": _RA, "borderBottom": f"0.5px solid {_B1}",
        "fontSize": "8.5px", "color": _T2, "letterSpacing": "0.05em",
        "textTransform": "uppercase",
    }
    col_headers = html.Div([
        html.Div([
            html.Div("Developer", style={
                **_ch_base, "width": f"{DEV_W}px", "flexShrink": "0",
                "borderRight": f"0.5px solid {_COL_DIV}",
                "borderRadius": "10px 0 0 0",
            }),
            html.Div("Function", style={
                **_ch_base, "width": f"{FUNC_W}px", "flexShrink": "0",
                "borderRight": f"0.5px solid {_B1}",
            }),
        ], style={"display": "flex"}),
        html.Div([
            html.Div(qtr_cols, style={
                "display": "flex", "height": "22px", "borderBottom": f"0.5px solid {_B1}",
            }),
            html.Div([*hdr_cols, *_rel_hdr_labels], style={
                "display": "flex", "height": "30px", "position": "relative",
            }),
        ], style={"flex": "1", "background": _RA, "borderRadius": "0 10px 0 0"}),
    ], style={"display": "flex"})

    # ── Legend ─────────────────────────────────────────────────────────────────
    def _swatch(s, label):
        return html.Div([html.Div(style=s),
                         html.Span(label, style={"fontSize": "10px", "color": _T2})],
                        style={"display": "flex", "alignItems": "center", "gap": "5px"})

    def _tag_leg(label, bg, color, brd):
        return html.Div([
            html.Span(label, style={
                "fontSize": "8px", "fontWeight": "600", "padding": "1px 5px",
                "borderRadius": "4px", "background": bg, "color": color,
                "border": f"0.5px solid {brd}",
            }),
            html.Span("Enhancement" if label == "ENH" else ("Bug" if label == "BUG" else "Task"),
                      style={"fontSize": "10px", "color": _T2}),
        ], style={"display": "flex", "alignItems": "center", "gap": "5px"})

    _sep = html.Div(style={"width": "0.5px", "height": "12px", "background": _B1, "margin": "0 4px"})

    legend = html.Div([
        _swatch({"width": "12px", "height": "6px", "borderRadius": "2px",
                 "background": _GR, "flexShrink": "0"}, "Done"),
        _swatch({"width": "12px", "height": "6px", "borderRadius": "2px",
                 "background": _AM, "flexShrink": "0"}, "Remaining (Enh)"),
        _swatch({"width": "12px", "height": "6px", "borderRadius": "2px",
                 "background": _RE_COL, "flexShrink": "0"}, "Remaining (Bug)"),
        _swatch({"width": "8px", "height": "8px", "borderRadius": "1px",
                 "background": _BL, "transform": "rotate(45deg)", "flexShrink": "0"}, "Target date"),
        _sep,
        _tag_leg("ENH", "rgba(107,158,208,0.12)", _BL, "rgba(107,158,208,0.25)"),
        _tag_leg("BUG", "rgba(211,111,104,0.12)", "var(--red)", "rgba(211,111,104,0.25)"),
        _tag_leg("TASK", "rgba(152,131,199,0.12)", "var(--purple)", "rgba(152,131,199,0.25)"),
        _sep,
        _swatch({"width": "2px", "height": "12px", "borderRadius": "1px",
                 "background": _RE_LINE, "flexShrink": "0"}, "Release cut"),
        _swatch({"width": "2px", "height": "12px", "borderRadius": "1px",
                 "background": "rgba(117,168,177,0.5)", "flexShrink": "0"}, "Today"),
        html.Span("· hover bar for details", style={"fontSize": "10px", "color": _T2,
                                                      "marginLeft": "4px"}),
    ], style={
        "display": "flex", "alignItems": "center", "gap": "14px", "padding": "8px 14px",
        "flexWrap": "wrap", "borderTop": f"0.5px solid {_B1}", "background": _SF,
        "borderRadius": "0 0 10px 10px",
    })

    # ── Assemble ── (overflow: visible so CSS tooltips escape the container) ──
    return html.Div([
        col_headers,
        html.Div([*all_rows, overlay_container], style={"position": "relative"}),
        legend,
    ], style={
        "background": "var(--bg-base)",
        "border": f"0.5px solid {_B1}",
        "borderRadius": "10px",
        "overflow": "visible",
    })


def _build_gantt_fig(
    df: pd.DataFrame,
    window_start: date,
    window_end: date,
    expanded_funcs=None,
):
    """Build collapsible delivery timeline: Function ▸ Enhancement.
    expanded_funcs = set of EXPANDED function names; empty = all collapsed (default)."""
    if expanded_funcs is None: expanded_funcs = set()

    today = date.today()
    cur_m = today.month

    # ── Filter M0/M1/M2 enhancements ────────────────────────────────────────
    enh = df[
        (df["work_item_type"] == "Enhancement") &
        (~df["state"].isin(_CLOSED_STATES)) &
        df["iteration_path"].str.contains(r"Iteration 2026 \d{2}-", regex=True, na=False)
    ].copy()

    def _delta(ip):
        mm = re.search(r"Iteration 2026 (\d{2})-", str(ip))
        return int(mm.group(1)) - cur_m if mm else None

    enh["_delta"] = enh["iteration_path"].apply(_delta)
    enh = enh[enh["_delta"].isin([0, 1, 2])].copy()

    if enh.empty:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            height=160,
            xaxis=dict(type="date", side="top",
                       range=[window_start.isoformat(), window_end.isoformat()]),
            annotations=[dict(text="No M0/M1/M2 enhancements found", showarrow=False,
                              xref="paper", yref="paper", x=0.5, y=0.5,
                              font=dict(color="#8892a4", size=13))],
        )
        return fig

    # ── Parse dates ──────────────────────────────────────────────────────────
    enh["_end"] = enh["release_date"].apply(_parse_release_date)
    enh = enh[enh["_end"].notna()].copy()

    def _start(row):
        ad = row.get("activated_date")
        if ad is not None and pd.notna(ad):
            return pd.Timestamp(ad).date()
        mm = re.search(r"Iteration 2026 (\d{2})-", str(row["iteration_path"]))
        return date(2026, int(mm.group(1)), 1) if mm else today

    enh["_start"] = enh.apply(_start, axis=1)
    enh = enh[enh.apply(lambda r: r["_start"] < r["_end"], axis=1)].copy()

    if enh.empty:
        return go.Figure()

    # ── Task rollup for completion % ─────────────────────────────────────────
    task_rollup = (
        df[df["work_item_type"] == "Task"]
        .groupby("parent_id")[["completed_work", "remaining_work"]]
        .sum()
        .rename(columns={"completed_work": "t_done", "remaining_work": "t_rem"})
    )
    enh = enh.join(task_rollup, on="work_item_id", how="left")
    enh["t_done"] = enh["t_done"].fillna(0)
    enh["t_rem"]  = enh["t_rem"].fillna(0)

    def _pct(row):
        total = row["t_done"] + row["t_rem"]
        if total > 0:
            return row["t_done"] / total
        total2 = (row.get("completed_work") or 0) + (row.get("remaining_work") or 0)
        return (row.get("completed_work") or 0) / total2 if total2 > 0 else 0

    enh["_pct"] = enh.apply(_pct, axis=1)

    # ── Person + function columns ─────────────────────────────────────────────
    def _person(row):
        p = str(row.get("main_developer") or "")
        if not p or p in ("Unassigned", "nan", ""):
            p = str(row.get("assigned_to") or "Unassigned")
        return p.split(" <")[0].strip()

    enh["_person"] = enh.apply(_person, axis=1)
    if "function" in enh.columns:
        enh["_func"] = enh["function"].fillna("General").replace(
            {"Not Specified": "General", "nan": "General", "": "General"}
        )
    else:
        enh["_func"] = "General"

    enh = enh.sort_values(["_func", "_start"])

    # ── Build visible row list: Function ▸ Enhancement ───────────────────────
    # Each entry: (label, row_type, row_data_or_None, func_key)
    y_rows   = []
    cur_fkey = None

    for _, row in enh.iterrows():
        func = row["_func"]

        if func != cur_fkey:
            cur_fkey = func
            y_rows.append((f"  {func}", "func", None, func))

        if func not in expanded_funcs:
            continue

        title_short = str(row.get("title", ""))[:55]
        y_rows.append((f"      • {title_short}", "enh", row, func))

    y_rows_rev = y_rows[::-1]   # Plotly index-0 = bottom; reverse → top-to-bottom
    y_labels   = [r[0] for r in y_rows_rev]
    n_rows     = len(y_labels)

    # ── Bar & marker data ────────────────────────────────────────────────────
    MS = 86_400_000

    green_y,  green_base,  green_x  = [], [], []
    orange_y, orange_base, orange_x = [], [], []
    dia_x,    dia_y                  = [], []
    # Toggle markers (scatter inside chart — always clickable unlike bars)
    tog_x, tog_y, tog_sym, tog_cd   = [], [], [], []
    tog_date = (window_start + timedelta(days=1)).isoformat()

    for entry in y_rows_rev:
        label, row_type, row, fkey = entry

        if row_type == "func":
            tog_x.append(tog_date);  tog_y.append(label)
            tog_sym.append("triangle-down" if fkey in expanded_funcs else "triangle-right")
            tog_cd.append(["func", fkey])
            continue

        s, e, pct = row["_start"], row["_end"], row["_pct"]
        dur = (e - s).days
        if dur <= 0:
            continue
        split = s + timedelta(days=max(0, min(dur, int(dur * pct))))

        ds = max(s, window_start)
        de = min(e, window_end)
        if ds >= de:
            continue

        g_end = min(split, de)
        if g_end > ds:
            green_y.append(label);  green_base.append(ds.isoformat())
            green_x.append((g_end - ds).days * MS)

        o_start = max(split, ds)
        if de > o_start:
            orange_y.append(label);  orange_base.append(o_start.isoformat())
            orange_x.append((de - o_start).days * MS)

        if window_start <= e <= window_end:
            dia_x.append(e.isoformat());  dia_y.append(label)

    # ── Shapes ───────────────────────────────────────────────────────────────
    shapes = []
    for i, entry in enumerate(y_rows_rev):
        if entry[1] == "func":
            shapes.append(dict(
                type="rect", xref="paper", yref="y",
                x0=0, x1=1, y0=i - 0.48, y1=i + 0.48,
                fillcolor="rgba(129,140,248,0.08)",
                line=dict(width=0), layer="below",
            ))
    shapes.append(dict(
        type="line", xref="x", yref="paper",
        x0=today.isoformat(), x1=today.isoformat(), y0=0, y1=1,
        line=dict(color="rgba(255,255,255,0.25)", width=1.5, dash="dot"),
    ))

    # ── Traces ───────────────────────────────────────────────────────────────
    traces = []
    if green_x:
        traces.append(go.Bar(
            y=green_y, x=green_x, base=green_base, orientation="h",
            marker=dict(color="#22c55e", opacity=0.85, line=dict(width=0)),
            name="Completed",
            hovertemplate="<b>%{y}</b><br>Completed<extra></extra>",
        ))
    if orange_x:
        traces.append(go.Bar(
            y=orange_y, x=orange_x, base=orange_base, orientation="h",
            marker=dict(color="#f97316", opacity=0.82, line=dict(width=0)),
            name="Remaining",
            hovertemplate="<b>%{y}</b><br>Remaining<extra></extra>",
        ))
    if dia_x:
        traces.append(go.Scatter(
            x=dia_x, y=dia_y, mode="markers",
            marker=dict(symbol="diamond", size=11, color="#60a5fa",
                        line=dict(color="#93c5fd", width=1.5)),
            name="Target date",
            hovertemplate="<b>%{y}</b><br>Target: %{x|%b %d, %Y}<extra></extra>",
        ))
    if tog_x:
        # Visible ▶/▼ triangle markers inside chart — scatter is always reliably clickable.
        traces.append(go.Scatter(
            x=tog_x, y=tog_y,
            mode="markers",
            marker=dict(symbol=tog_sym, size=9, color="#818cf8",
                        line=dict(color="#a5b4fc", width=1)),
            customdata=tog_cd,
            hovertemplate="Click to expand / collapse<extra></extra>",
            showlegend=False, name="",
        ))

    fig = go.Figure(traces)
    fig.update_layout(
        barmode="overlay",
        height=max(260, n_rows * 30 + 80),
        margin=dict(l=280, r=24, t=40, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color="#8892a4", size=11),
        xaxis=dict(
            type="date",
            side="top",
            range=[window_start.isoformat(), window_end.isoformat()],
            gridcolor="rgba(255,255,255,0.06)",
            tickformat="%b %Y", dtick="M1",
            tickfont=dict(color="#94a3b8", size=12),
            linecolor="rgba(0,0,0,0)", zerolinecolor="rgba(255,255,255,0.07)",
        ),
        yaxis=dict(
            autorange=False, range=[-0.5, n_rows - 0.5],
            tickvals=list(range(n_rows)), ticktext=y_labels,
            tickfont=dict(size=11, color="#8892a4"),
            gridcolor="rgba(0,0,0,0)", linecolor="rgba(0,0,0,0)",
        ),
        shapes=shapes,
        legend=dict(
            orientation="h", x=0, y=-0.04,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8892a4", size=11),
            itemsizing="constant",
        ),
        hoverlabel=dict(
            bgcolor="#151524", bordercolor="rgba(255,255,255,0.10)",
            font=dict(color="#e2e8f0"),
        ),
        clickmode="event",
        dragmode=False,
    )
    return fig


# ═══════════════════════════════════════════════════════════════════════════════

def layout(**_):
    """Returns a shell immediately — content loaded via _init_plan callback."""
    return html.Div([
        dcc.Store(id="_plan-init", data=1),
        dcc.Loading(
            id="_plan-loading",
            type="circle",
            color="#818cf8",
            style={"minHeight": "80vh", "display": "flex",
                   "alignItems": "center", "justifyContent": "center"},
            children=html.Div(id="_plan-body"),
        ),
    ], style={"background": C3, "minHeight": "100vh",
              "fontFamily": "Inter, system-ui, sans-serif"})


def _build_full_layout():
    stories, months, init_gates, ba_names, dev_names, dev_matrix, story_matrix, dev_stories_flat = \
        _load_planning_data()

    _today      = date.today()
    today_month = _today.month

    # ── KPIs ──────────────────────────────────────────────────────────────────
    m1_s = [s for s in stories if s["month"] == "M1"]
    m2_s = [s for s in stories if s["month"] == "M2"]
    lh_s = [
        s for s in stories
        if s["month"] not in ("M0","M1","M2")
        and (s["pri"] in ("P1","P2") or s["size"] in ("Big","Medium"))
    ]

    m1_ready = sum(1 for s in m1_s if all(s.get(f) for f in _GATE_FIELDS))
    m1_total = len(m1_s) or 1
    m1_pct   = round(m1_ready / m1_total * 100)

    m2_draft = sum(1 for s in m2_s if any(s.get(f) for f in _GATE_FIELDS))
    m2_total = len(m2_s) or 1
    m2_pct   = round(m2_draft / m2_total * 100)

    lh_writ  = sum(1 for s in lh_s if any(s.get(f) for f in _GATE_FIELDS))
    lh_total = len(lh_s) or 1
    lh_pct   = round(lh_writ / lh_total * 100)

    m1_label = _CAL.get(today_month + 1, "M1")
    m2_label = _CAL.get(today_month + 2, "M2")

    kpi_strip = html.Div([
        _kpi_card(
            f"KPI-01 · {m1_label} Story Readiness Rate", m1_pct,
            f"{m1_ready} of {len(m1_s)} stories Ready · target 100%  "
            f"All must be signed off before {m1_label} starts",
            count=f"{m1_ready} / {len(m1_s)}",
        ),
        _kpi_card(
            f"KPI-02 · {m2_label} Draft Coverage", m2_pct,
            f"{m2_draft} of {len(m2_s)} {m2_label} items have story started  "
            "KPI-02 must always exceed KPI-03 in intermediate states.",
            color=R if m2_pct < 33 else None,
            count=f"{m2_draft} / {len(m2_s)}",
        ),
        _kpi_card(
            "KPI-03 · Long-Horizon Pipeline Health", lh_pct,
            f"{lh_writ} of {len(lh_s)} P1/P2/Big/Medium items (Jul–Dec) written  "
            "Pipeline lead owns sign-off of long-horizon stories.",
            color=R if lh_pct < 33 else None,
            count=f"{lh_writ} / {len(lh_s)}",
        ),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "16px", "flexWrap": "wrap"})

    # ── Alert strip ────────────────────────────────────────────────────────────
    m1_not_ready    = len(m1_s) - m1_ready
    m2_not_started  = sum(1 for s in m2_s if not any(s.get(f) for f in _GATE_FIELDS))
    lh_not_started  = len(lh_s) - lh_writ
    alerts = []
    if m1_not_ready:
        alerts.append(_alert(
            f"{m1_not_ready} {m1_label} {'story' if m1_not_ready == 1 else 'stories'} not yet Ready "
            f"— must be fixed before {m1_label} starts", R,
        ))
    if m2_not_started:
        alerts.append(_alert(
            f"{m2_not_started} {m2_label} items have no story started "
            f"— target 100% Draft by mid-{m1_label}", A,
        ))
    if lh_not_started:
        alerts.append(_alert(
            f"{lh_not_started} P1/P2/Big/Medium items (Jul–Dec) still need stories written",
            "#7f5e00",
        ))
    alert_strip = html.Div(
        alerts or [_alert("All planning KPIs on track ✓", G)],
        style={"display": "flex", "gap": "10px", "marginBottom": "16px", "flexWrap": "wrap"},
    )

    # ── Month tabs ─────────────────────────────────────────────────────────────
    active_month = next(
        (m["key"] for m in months if m["key"] == "M1"),
        months[0]["key"] if months else "M1",
    )

    def _month_tabs(active: str):
        tabs = []
        for m in months:
            is_a  = m["key"] == active
            fp    = m.get("pct", 0)
            fc    = m["bc"]
            if is_a:
                bg = f"linear-gradient(to right, {P}55 {fp}%, {P}18 {fp}%)"
            elif fp > 0:
                bg = f"linear-gradient(to right, {fc}2e {fp}%, rgba(255,255,255,0.02) {fp}%)"
            else:
                bg = "rgba(255,255,255,0.02)"
            tabs.append(html.Div([
                html.Div(m["label"], style={"fontSize": "14px", "fontWeight": "700",
                                             "color": TX if is_a else MT}),
                html.Div(m["badge"], style={"fontSize": "11px", "color": m["bc"],
                                             "fontWeight": "600", "marginTop": "4px"}),
            ], id={"type": "month-tab", "month": m["key"]}, style={
                "padding":    "12px 8px", "borderRadius": "8px", "cursor": "pointer",
                "background": bg,
                "border":     f"1px solid {P}" if is_a else f"1px solid {BD}",
                "textAlign":  "center", "flex": "1", "transition": "all .15s",
            }))
        return html.Div(tabs, style={"display": "flex", "gap": "6px", "width": "100%"})

    # ── Filter bar with real BA + dev names ────────────────────────────────────
    ba_first_names  = sorted({n.split()[0] for n in ba_names}) if ba_names else []
    dev_first_names = sorted({n.split()[0] for n in dev_names})[:20]  # cap at 20

    _cs_act = lambda c, p="5px 12px": {
        "padding": p, "borderRadius": "20px", "fontSize": "12px",
        "fontWeight": "600", "cursor": "pointer",
        "background": _dim(c), "color": c,
        "border": f"1px solid {c}", "boxShadow": f"0 0 10px {_brd(c)}",
    }
    _cs_idl = lambda p="5px 12px": {
        "padding": p, "borderRadius": "20px", "fontSize": "12px",
        "fontWeight": "500", "cursor": "pointer",
        "background": "var(--bg-hover)", "color": MT,
        "border": "1px solid rgba(255,255,255,0.08)", "boxShadow": "none",
    }

    ba_chips = [html.Div("All BAs", id="ba-all-chip", style=_cs_act(P, "5px 14px"))]
    for ba in ba_first_names:
        ba_chips.append(html.Div(ba, id={"type": "ba-chip", "ba": ba}, style=_cs_idl("5px 14px")))

    dev_chips = [html.Div("All", id="dev-all-chip", style=_cs_act(B))]
    for dv in dev_first_names:
        dev_chips.append(html.Div(dv, id={"type": "dev-chip", "dev": dv}, style=_cs_idl()))

    show_chips = []
    for label in ["Needs Action", "All", "Ready"]:
        is_act = label == "Needs Action"
        show_chips.append(html.Div(label, id={"type": "show-chip", "show": label},
                                   style=_cs_act(A) if is_act else _cs_idl()))

    tier_chips = []
    for lbl, tid in [("All", "all"), ("Not Started", "not_started"),
                     ("In Progress", "in_progress"), ("Complete", "complete")]:
        tier_chips.append(html.Div(lbl, id={"type": "tier-chip", "tier": tid},
                                   style=_cs_act(G) if tid == "all" else _cs_idl()))

    def _fsec(label, color, chips):
        return html.Div([
            html.Div([
                html.Span(label, style={
                    "fontSize": "9px", "fontWeight": "800", "letterSpacing": "2px",
                    "textTransform": "uppercase", "color": color,
                }),
                html.Div(style={
                    "flex": "1", "height": "1px", "marginLeft": "10px",
                    "background": f"linear-gradient(to right, {color}55, transparent)",
                }),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
            html.Div(chips, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),
        ], style={"marginBottom": "24px"})

    filter_bar = html.Div([
        _fsec("BA",   P, ba_chips),
        _fsec("DEV",  B, dev_chips),
        _fsec("SHOW", A, show_chips),
        _fsec("GATE", G, tier_chips),
        html.Button([html.Span(id="log-count-badge")], id="signoff-log-btn", style={"display": "none"}),
    ], style={"padding": "4px 0"})

    # ── Load unestimated data ─────────────────────────────────────────────────
    unest_items = _load_unestimated_data()

    # ── Load bug data ─────────────────────────────────────────────────────────
    bug_items = _load_bug_data()

    # ── Stores ─────────────────────────────────────────────────────────────────
    stores = html.Div([
        dcc.Store(id="plan-active-tab",    data="signoff"),
        dcc.Store(id="plan-active-month",  data=active_month),
        dcc.Store(id="plan-ba-filter",     data="All BAs"),
        dcc.Store(id="plan-dev-filter",    data="All"),
        dcc.Store(id="plan-show-filter",   data="Needs Action"),
        dcc.Store(id="plan-type-filter",   data="All"),
        dcc.Store(id="plan-size-filter",   data="All"),
        dcc.Store(id="plan-story-matrix",  data=story_matrix),
        dcc.Store(id="plan-dev-stories",   data=dev_stories_flat),
        dcc.Store(id="plan-tier-filter",   data="all"),
        dcc.Store(id="stuck-filter",       data="all"),
        dcc.Store(id="dash-collapsed",     data=False),
        dcc.Store(id="gate-store",         data=init_gates),
        dcc.Store(id="log-store",          data=[]),
        dcc.Store(id="plan-stories-store", data=stories),    # real ADO data
        dcc.Store(id="plan-months-store",  data=months),     # for month-tab rebuild
        dcc.Store(id="plan-unest-store",    data=unest_items), # unestimated items
        dcc.Store(id="unest-panel-filter",  data=None),        # active side panel filter
        dcc.Store(id="unest-active-kcard", data=None),         # which KPI card is expanded
        dcc.Store(id="ticket-log-sid",      data=None),        # selected ticket for history modal
        dcc.Store(id="tracker-sid",         data=None),        # selected ticket for lifecycle tracker
        dcc.Store(id="tracker-gate-focus",  data=None),        # gate key to scroll/highlight when opening
        dcc.Store(id="tracker-data",        data={}),          # {sid, state} for tracker modal
        dcc.Store(id="plan-main-tab",       data="readiness"),
        dcc.Store(id="plan-bugs-store",     data=bug_items),   # bug items for sign-off tab
        dcc.Store(id="story-page",          data=1),
        dcc.Store(id="bug-page",            data=1),
        dcc.Store(id="ba-type-f",           data="Enhancements"),
        dcc.Store(id="gantt-view", data="0-12"),
        dcc.Store(id="gantt-expanded",      data={"s": [], "t": []}),
    ])

    # ── Sprint info strip (dynamic) ──────────────────────────────────────────
    from calendar import monthrange as _mr
    from config.dev_capacity import DEFAULT_CAPACITY_H as _dch
    import sys as _sys
    _ld = _mr(_today.year, _today.month)[1]
    _sprint_info = (
        f"{_today.strftime('%b %Y')} · Sprint 1 · "
        f"Day {_today.day} of {_ld} · Default: {_dch}h/person"
    )
    _fm  = _sys.modules.get("pages_dash.trends.focus")
    _cm  = _sys.modules.get("pages_dash.enhancements.capacity_planner")
    _focus_section  = _fm.focus_tab_content()  if _fm  else html.Div("VSTS Focus Area loading…",   style={"padding": "20px", "color": MT})
    _devcap_section = _cm.layout()  if _cm  else html.Div("Developer Capacity loading…", style={"padding": "20px", "color": MT})

    # ── Full layout ────────────────────────────────────────────────────────────
    return html.Div([
        stores,
        signoff_modal,
        ticket_log_modal,
        tracker_modal,
        matrix_panel,

        # Page header
        html.Div([
            html.Div([
                html.Div("EOD · PLANNING", style={
                    "fontSize": "11px", "fontWeight": "700", "color": P,
                    "letterSpacing": "1px", "textTransform": "uppercase", "marginBottom": "4px",
                }),
                html.Div("Planning Tool · Story Readiness, Estimation & Capacity", style={
                    "fontSize": "20px", "fontWeight": "800", "color": TX,
                }),
                html.Div(
                    "KPI-01 M1 Readiness · KPI-02 M2 Coverage · "
                    "KPI-03 Long-Horizon Pipeline Health · Click any cell for more detail",
                    style={"fontSize": "11px", "color": MT, "marginTop": "4px"},
                ),
                html.Div(
                    "ℹ Months M0 / M1 / M2 = iteration months (sprint cadence). "
                    "M0 = current sprint, M1 = next, M2 = sprint after.",
                    style={"fontSize": "10px", "color": MT, "marginTop": "3px",
                           "fontStyle": "italic"},
                ),
            ]),
            html.Div(_sprint_info, style={
                "fontSize": "11px", "color": MT, "whiteSpace": "nowrap",
                "alignSelf": "flex-start", "marginTop": "2px",
                "background": "var(--bg-hover)",
                "border": f"1px solid {BD}",
                "borderRadius": "8px", "padding": "6px 14px",
            }),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "flex-start", "marginBottom": "20px"}),

        # ── Main tab navigation ────────────────────────────────────────────────
        html.Div([
            html.Button(
                "Story Readiness",
                id={"type": "plan-main-tab-btn", "tab": "readiness"}, n_clicks=0,
                style={
                    "background":   P_DIM,
                    "border":       f"1px solid {P}",
                    "borderRadius": "8px",
                    "color":        TX,
                    "fontSize":     "13px",
                    "fontWeight":   "600",
                    "padding":      "7px 18px", "cursor": "pointer", "marginRight": "6px",
                },
            ),
            html.Button(
                "Story Tracking",
                id={"type": "plan-main-tab-btn", "tab": "tracking"}, n_clicks=0,
                style=_MAIN_IDL,
            ),
        ], style={"display": "flex", "alignItems": "center", "gap": "4px",
                  "marginBottom": "20px", "borderBottom": f"1px solid {BD}",
                  "paddingBottom": "12px"}),

        # ── Story Readiness section ────────────────────────────────────────────
        html.Div([
            # ── Dashboard toggle row ───────────────────────────────────────────
            html.Div([
                html.Button(
                    ["▼ Hide dashboard"],
                    id="dash-toggle-btn", n_clicks=0,
                    style={
                        "background": "transparent", "border": f"1px solid {BD}",
                        "borderRadius": "8px", "color": MT, "fontSize": "12px",
                        "fontWeight": "600", "padding": "5px 14px",
                        "cursor": "pointer", "transition": "all .15s",
                        "display": "flex", "alignItems": "center", "gap": "6px",
                    },
                ),
                html.Span(id="dash-summary-text", style={"display": "none"}),
            ], style={"display": "flex", "alignItems": "center",
                      "gap": "12px", "marginBottom": "12px"}),
            # ── Collapsible KPI panel ──────────────────────────────────────────
            html.Div(kpi_strip, id="kpi-panel"),

            # Sub-tab navigation (BA Sign-Off · By Developer · By Story)
            html.Div([
                html.Span("★ ", style={"color": P, "fontSize": "16px"}),
                *[html.Button(
                    lbl, id={"type": "plan-tab", "tab": tid}, n_clicks=0,
                    style={
                        "background":   P_DIM if i == 0 else "transparent",
                        "border":       f"1px solid {P}" if i == 0 else f"1px solid {BD}",
                        "borderRadius": "8px",
                        "color":        TX if i == 0 else MT,
                        "fontSize":     "13px",
                        "fontWeight":   "600" if i == 0 else "400",
                        "padding":      "7px 18px", "cursor": "pointer", "marginRight": "6px",
                    },
                ) for i, (lbl, tid) in enumerate([
                    ("BA Sign-Off",  "signoff"),
                    ("By Developer", "bydev"),
                    ("By Story",     "bystory"),
                ])],
                html.Button([
                    html.Span("⚙", style={"marginRight": "6px", "fontSize": "13px"}),
                    html.Span("Filters", style={"fontSize": "12px", "fontWeight": "600"}),
                ], id="ba-flt-open-btn", n_clicks=0, style={
                    "display": "flex", "alignItems": "center", "marginLeft": "auto",
                    "background": "transparent", "border": f"1px solid {BD}",
                    "borderRadius": "8px", "color": MT,
                    "padding": "6px 14px", "cursor": "pointer",
                    "transition": "border-color .15s, color .15s",
                }),
            ], style={
                "display": "flex", "alignItems": "center", "gap": "4px",
                "position": "sticky", "top": "0", "zIndex": "22",
                "background": C3,
                "paddingTop": "8px", "paddingBottom": "8px",
                "marginBottom": "0", "marginTop": "0",
                "borderBottom": f"1px solid {BD}",
            }),

            # ── BA Sign-Off tab ────────────────────────────────────────────────
            html.Div(id="tab-signoff", children=[
                # Frozen iteration filter — sticks below the sub-tab nav
                html.Div(id="month-tabs-container", children=_month_tabs(active_month),
                         style={
                             "position": "sticky", "top": "50px", "zIndex": "20",
                             "background": C3,
                             "paddingTop": "8px", "paddingBottom": "10px",
                             "marginBottom": "4px",
                         }),
                dcc.Loading(
                    type="circle", color="#818cf8", style={"minHeight": "60px"},
                    children=html.Div(id="readiness-header"),
                ),
                # WHERE STORIES ARE STUCK filter bar
                html.Div(id="stuck-filter-bar", style={"marginBottom": "10px"}),
                # Enhancements section (shown by default)
                html.Div([
                    dcc.Loading(
                        type="circle", color="#818cf8", style={"minHeight": "120px"},
                        children=html.Div([
                            html.Table([
                                html.Thead(story_table_header),
                                html.Tbody(id="story-tbody"),
                            ], style={"width": "100%", "borderCollapse": "collapse"}),
                        ], style={
                            "background": CD, "borderRadius": "12px",
                            "border": f"1px solid {BD}", "overflow": "hidden", "marginBottom": "4px",
                        }),
                    ),
                    html.Div([
                        html.Button("‹ Prev", id="story-page-prev", n_clicks=0, disabled=True,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": MT, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                        html.Span(id="story-page-info",
                                  style={"color": MT, "fontSize": "12px", "padding": "0 14px"}),
                        html.Button("Next ›", id="story-page-next", n_clicks=0, disabled=False,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": TX, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                    ], id="story-pagination", style={
                        "display": "none", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0",
                    }),
                ], id="enh-section"),
                # Issues section (hidden by default, shown when TYPE=Issues)
                html.Div([
                    dcc.Loading(
                        type="circle", color="#818cf8", style={"minHeight": "120px"},
                        children=html.Div([
                            html.Table([
                                html.Thead(bug_table_header),
                                html.Tbody(id="bug-tbody"),
                            ], style={"width": "100%", "borderCollapse": "collapse"}),
                        ], style={
                            "background": CD, "borderRadius": "12px",
                            "border": f"1px solid {BD}", "overflow": "hidden", "marginBottom": "4px",
                        }),
                    ),
                    html.Div([
                        html.Button("‹ Prev", id="bug-page-prev", n_clicks=0, disabled=True,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": MT, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                        html.Span(id="bug-page-info",
                                  style={"color": MT, "fontSize": "12px", "padding": "0 14px"}),
                        html.Button("Next ›", id="bug-page-next", n_clicks=0, disabled=False,
                                    style={"background": "transparent", "border": f"1px solid {BD}",
                                           "borderRadius": "6px", "color": TX, "fontSize": "12px",
                                           "cursor": "pointer", "padding": "4px 14px"}),
                    ], id="bug-pagination", style={
                        "display": "none", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0",
                    }),
                ], id="bug-section", style={"display": "none"}),
                _footer,
            ]),

            # ── By Developer tab ──────────────────────────────────────────────
            html.Div(id="tab-bydev", style={"display": "none"}, children=[
                alert_strip,
                html.Div([_type_filter_strip(), _legend]),
                html.Div(
                    id="dev-matrix-wrap",
                    children=[_build_dev_matrix(dev_matrix, today_month)],
                    style={
                        "background": CD, "borderRadius": "12px",
                        "border": f"1px solid {BD}", "overflow": "auto", "marginBottom": "12px",
                    },
                ),
                _footer,
            ]),

            # ── By Story tab ──────────────────────────────────────────────────
            html.Div(id="tab-bystory", style={"display": "none"}, children=[
                alert_strip,
                _type_filter_strip(sizes=True),
                _legend,
                html.Div(
                    id="story-matrix-wrap",
                    children=[_build_story_matrix(story_matrix)],
                    style={
                        "background": CD, "borderRadius": "12px",
                        "border": f"1px solid {BD}", "overflow": "auto", "marginBottom": "12px",
                    },
                ),
                _footer,
            ]),

        ], id="main-sec-readiness"),

        # ── Unestimated Items section ──────────────────────────────────────────
        html.Div(id="main-sec-unest", style={"display": "none"},
                 children=[_build_unest_tab(unest_items)]),

        # ── Developer Capacity section ─────────────────────────────────────────
        html.Div(id="main-sec-devcap", style={"display": "none"},
                 children=[_devcap_section]),

        # ── Delivery Timeline (Gantt) section ─────────────────────────────────
        html.Div(id="main-sec-gantt", style={"display": "none"},
                 children=[
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("DELIVERY TIMELINE", style={
                            "fontSize": "9px", "fontWeight": "800", "color": P,
                            "letterSpacing": "2px", "textTransform": "uppercase",
                        }),
                        html.Span(id="gantt-window-label",
                                  children=f" · {_gantt_window('0-12')[2]}",
                                  style={"fontSize": "11px", "color": MT, "marginLeft": "6px"}),
                    ], style={"display": "flex", "alignItems": "center"}),
                    html.Div([
                        dcc.Dropdown(
                            id="gantt-view-select",
                            options=[
                                {"label": "Rolling 12M", "value": "0-12"},
                                {"label": "12 – 24M",    "value": "12-24"},
                                {"label": "24M+",        "value": "24+"},
                            ],
                            value="0-12",
                            clearable=False,
                            className="dark-dropdown",
                            style={"minWidth": "140px", "fontSize": "12px"},
                        ),
                        dcc.Dropdown(
                            id="gantt-type-filter",
                            options=[
                                {"label": "All work",     "value": "all"},
                                {"label": "Enhancements", "value": "enh"},
                                {"label": "Bugs",         "value": "bug"},
                            ],
                            value="all",
                            clearable=False,
                            className="dark-dropdown",
                            style={"minWidth": "140px", "fontSize": "12px"},
                        ),
                        dcc.Dropdown(
                            id="gantt-prio-filter",
                            options=[
                                {"label": "P1 — Critical", "value": "1"},
                                {"label": "P2 — High",     "value": "2"},
                                {"label": "P3 — Medium",   "value": "3"},
                                {"label": "P4+",           "value": "4+"},
                            ],
                            multi=True,
                            placeholder="All priorities…",
                            className="dark-dropdown",
                            style={"minWidth": "150px", "fontSize": "12px"},
                        ),
                    ], style={"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap"}),
                ], style={"display": "flex", "justifyContent": "space-between",
                          "alignItems": "center", "marginBottom": "12px",
                          "padding": "0 16px", "gap": "12px"}),
                dcc.Loading(
                    id="gantt-loading",
                    type="default",
                    color="var(--accent)",
                    children=html.Div(id="gantt-chart",
                                      style={"overflowY": "auto", "maxHeight": "680px"}),
                ),
            ], style={
                "background": CD, "border": f"1px solid {BD}",
                "borderRadius": "12px", "padding": "14px 0 0",
                "marginBottom": "20px", "overflow": "hidden",
            }),
        ]),

        # ── BA Team Brief section ─────────────────────────────────────────────
        html.Div(id="main-sec-bateam", style={"display": "none"},
                 children=[_build_ba_brief()]),

        # ── Story Tracking section ────────────────────────────────────────────
        html.Div(id="main-sec-tracking", style={"display": "none"},
                 children=[_build_story_tracking_tab()]),

        # ── BA filters left panel ─────────────────────────────────────────────
        html.Div(id="ba-flt-backdrop", n_clicks=0, style=_BACKDROP_CLOSED),
        html.Div([
            html.Div([
                html.Span("Filters", style={
                    "fontWeight": "700", "fontSize": "15px", "color": TX, "flex": "1",
                }),
                html.Button("✕", id="ba-flt-panel-close", n_clicks=0, style={
                    "background": "none", "border": "none", "color": MT,
                    "fontSize": "20px", "cursor": "pointer", "padding": "2px 8px",
                    "lineHeight": "1",
                }),
            ], style={
                "display": "flex", "alignItems": "center",
                "padding": "18px 20px 14px",
                "borderBottom": f"1px solid {BD}",
                "flexShrink": "0",
            }),
            html.Div([
                # TYPE section — same vertical section style as filter_bar
                html.Div([
                    html.Div([
                        html.Span("TYPE", style={
                            "fontSize": "9px", "fontWeight": "800", "letterSpacing": "2px",
                            "textTransform": "uppercase", "color": P,
                        }),
                        html.Div(style={
                            "flex": "1", "height": "1px", "marginLeft": "10px",
                            "background": f"linear-gradient(to right, {P}55, transparent)",
                        }),
                    ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
                    html.Div([
                        *[html.Button(lbl, id={"type": "ba-type-btn", "v": lbl}, n_clicks=0, style={
                            "background": P_DIM if lbl == "Enhancements" else "var(--bg-hover)",
                            "border": f"1px solid {P}" if lbl == "Enhancements" else "1px solid rgba(255,255,255,0.08)",
                            "borderRadius": "20px",
                            "color": P if lbl == "Enhancements" else MT,
                            "fontSize": "12px", "fontWeight": "600" if lbl == "Enhancements" else "500",
                            "padding": "5px 14px", "cursor": "pointer",
                            "boxShadow": f"0 0 10px {P}44" if lbl == "Enhancements" else "none",
                        }) for lbl in ("Enhancements", "Issues")],
                    ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),
                ], style={"marginBottom": "24px"}),
                # BA / DEV / SHOW / GATE sections
                filter_bar,
            ], style={"overflowY": "auto", "flex": "1", "padding": "16px 20px"}),
        ], id="ba-flt-panel", style=_FLT_PANEL_CLOSED),

        # ── Unestimated items side drawer (fixed, always in DOM) ──────────────
        html.Div(id="unest-backdrop", n_clicks=0, style=_BACKDROP_CLOSED),
        html.Div([
            # Header
            html.Div([
                html.Div(id="unest-panel-title",
                         style={"fontWeight": "700", "fontSize": "15px", "color": TX,
                                "flex": "1"}),
                html.Button("✕", id="unest-panel-close", n_clicks=0, style={
                    "background": "none", "border": "none", "color": MT,
                    "fontSize": "20px", "cursor": "pointer", "padding": "2px 8px",
                    "lineHeight": "1", "transition": "color .15s",
                }),
            ], style={
                "display": "flex", "alignItems": "center",
                "padding": "18px 20px 14px",
                "borderBottom": f"1px solid {BD}",
                "flexShrink": "0",
            }),
            # Sort / type-filter ctrl bar — shown when panel is open
            html.Div(id="unest-sp-ctrl-bar", children=[
                html.Div([
                    html.Div("Sort", style={"fontSize": "10px", "color": MT,
                                            "fontWeight": "600", "marginBottom": "3px"}),
                    dcc.Dropdown(
                        id="unest-sp-srt-ctrl",
                        options=[{"label": l, "value": v} for l, v in
                                 [("Priority", "pri"), ("Release Date", "rd"), ("Title", "title")]],
                        value="pri", clearable=False,
                        style={"minWidth": "130px", "fontSize": "11px"},
                    ),
                ]),
                html.Div([
                    html.Div("Type", style={"fontSize": "10px", "color": MT,
                                            "fontWeight": "600", "marginBottom": "3px"}),
                    dcc.Dropdown(
                        id="unest-sp-type-ctrl",
                        options=[{"label": l, "value": v} for l, v in
                                 [("All Types", "all"), ("Bug", "Bug"),
                                  ("Bug UI", "Bug_UI"), ("Bug Text", "Bug_Text")]],
                        value="all", clearable=False,
                        style={"minWidth": "150px", "fontSize": "11px"},
                    ),
                ]),
            ], style={"display": "none", "gap": "10px", "alignItems": "flex-end",
                      "padding": "10px 20px", "borderBottom": f"1px solid {BD}",
                      "flexShrink": "0"}),
            # Scrollable body
            html.Div(id="unest-panel-body",
                     style={"overflowY": "auto", "flex": "1", "padding": "16px 20px"}),
        ], id="unest-side-panel", style=_PANEL_CLOSED),

    ], style={
        "padding":    "24px 32px",
        "background": C3,
        "minHeight":  "100vh",
        "fontFamily": "Inter, system-ui, sans-serif",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

@callback(
    Output("_plan-body", "children"),
    Input("_plan-init", "data"),
)
def _init_plan(_):
    return _build_full_layout()

# ── 1. Tab switching ──────────────────────────────────────────────────────────
@callback(
    Output("tab-signoff",                    "style"),
    Output("tab-bydev",                      "style"),
    Output("tab-bystory",                    "style"),
    Output("plan-active-tab",                "data"),
    Output({"type": "plan-tab", "tab": ALL}, "style"),
    Input({"type": "plan-tab", "tab": ALL},  "n_clicks"),
    State("plan-active-tab",                 "data"),
    State({"type": "plan-tab", "tab": ALL},  "id"),
    prevent_initial_call=True,
)
def _switch_tab(n_clicks, current, btn_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    tab  = triggered["tab"]
    show = {"display": "block"}
    hide = {"display": "none"}
    btn_styles = [
        _TAB_BTN_ACT if bid["tab"] == tab else _TAB_BTN_IDL
        for bid in (btn_ids or [])
    ]
    return (
        show if tab == "signoff" else hide,
        show if tab == "bydev"   else hide,
        show if tab == "bystory" else hide,
        tab,
        btn_styles,
    )



# ── 1b. Main section tab switching ────────────────────────────────────────────
_MAIN_ACT = {
    "background": P_DIM, "border": f"1px solid {P}", "borderRadius": "8px",
    "color": TX, "fontSize": "13px", "fontWeight": "600",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}
_MAIN_IDL = {
    "background": "transparent", "border": f"1px solid {BD}", "borderRadius": "8px",
    "color": MT, "fontSize": "13px", "fontWeight": "400",
    "padding": "7px 18px", "cursor": "pointer", "marginRight": "6px",
}

@callback(
    Output("main-sec-readiness",                         "style"),
    Output("main-sec-unest",                             "style"),
    Output("main-sec-devcap",                            "style"),
    Output("main-sec-gantt",                             "style"),
    Output("main-sec-bateam",                            "style"),
    Output("main-sec-tracking",                          "style"),
    Output("plan-main-tab",                              "data"),
    Output({"type": "plan-main-tab-btn", "tab": ALL},   "style"),
    Input({"type": "plan-main-tab-btn", "tab": ALL},    "n_clicks"),
    State({"type": "plan-main-tab-btn", "tab": ALL},    "id"),
    prevent_initial_call=True,
)
def _switch_main_tab(n_clicks, btn_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    tab  = triggered["tab"]
    show = {"display": "block"}
    hide = {"display": "none"}
    btn_styles = [
        _MAIN_ACT if bid["tab"] == tab else _MAIN_IDL
        for bid in (btn_ids or [])
    ]
    return (
        show if tab == "readiness" else hide,
        show if tab == "unest"     else hide,
        show if tab == "devcap"    else hide,
        show if tab == "gantt"     else hide,
        show if tab == "bateam"    else hide,
        show if tab == "tracking"  else hide,
        tab,
        btn_styles,
    )


# ── Story Tracking — sort state ───────────────────────────────────────────────
@callback(
    Output("st-sort-store", "data"),
    Input({"type": "st-sort-th", "col": ALL}, "n_clicks"),
    State("st-sort-store", "data"),
    prevent_initial_call=True,
)
def _update_st_sort(all_clicks, current):
    if not any(all_clicks or []):
        raise dash.exceptions.PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise dash.exceptions.PreventUpdate
    col = tid["col"]
    current   = current or {}
    cur_col   = current.get("col")
    cur_dir   = current.get("dir")
    if cur_col == col:
        new_dir = "desc" if cur_dir == "asc" else (None if cur_dir == "desc" else "asc")
    else:
        new_dir = "asc"
    return {"col": col if new_dir else None, "dir": new_dir}


# ── Story Tracking — re-render table on sort/filter change ───────────────────
@callback(
    Output("st-table-wrapper", "children"),
    Input("st-sort-store",    "data"),
    Input("st-flt-priority",  "value"),
    Input("st-flt-status",    "value"),
    Input("st-flt-size",      "value"),
    Input("st-flt-area",      "value"),
    Input("st-flt-owner",     "value"),
    prevent_initial_call=True,
)
def _render_st_table(sort_state, pri, status, size, area, owner):
    rows = _load_story_tracking_data()
    filters = {
        "priority": pri    or [],
        "status":   status or [],
        "size":     size   or [],
        "area":     area   or [],
        "owner":    owner  or [],
    }
    sort_col = (sort_state or {}).get("col")
    sort_dir = (sort_state or {}).get("dir")
    return html.Div(
        _build_st_table(rows, sort_col, sort_dir, filters),
        style={"background": CD, "border": f"1px solid {BD}",
               "borderRadius": "12px", "overflow": "hidden"},
    )


# ── 2. Month tab click ────────────────────────────────────────────────────────
@callback(
    Output("plan-active-month",    "data"),
    Output("month-tabs-container", "children"),
    Input({"type": "month-tab", "month": ALL}, "n_clicks"),
    State("plan-active-month",  "data"),
    State("plan-months-store",  "data"),
    prevent_initial_call=True,
)
def _select_month(n_clicks, current, months_data):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    new_month  = triggered["month"]
    months     = months_data or []
    tabs = []
    for m in months:
        is_a  = m["key"] == new_month
        fp    = m.get("pct", 0)
        fc    = m["bc"]
        if is_a:
            bg = f"linear-gradient(to right, {P}55 {fp}%, {P}18 {fp}%)"
        elif fp > 0:
            bg = f"linear-gradient(to right, {fc}2e {fp}%, rgba(255,255,255,0.02) {fp}%)"
        else:
            bg = "rgba(255,255,255,0.02)"
        tabs.append(html.Div([
            html.Div(m["label"], style={"fontSize": "12px", "fontWeight": "700",
                                         "color": TX if is_a else MT}),
            html.Div(m["badge"], style={"fontSize": "9px", "color": m["bc"],
                                         "fontWeight": "600", "marginTop": "2px"}),
        ], id={"type": "month-tab", "month": m["key"]}, style={
            "padding":    "6px 4px", "borderRadius": "8px", "cursor": "pointer",
            "background": bg,
            "border":     f"1px solid {P}" if is_a else f"1px solid {BD}",
            "textAlign":  "center", "flex": "1", "transition": "all .15s",
        }))
    return new_month, html.Div(tabs, style={"display": "flex", "gap": "6px", "width": "100%"})


# ── 3. Gate direct-toggle — click pill to check/uncheck ──────────────────────
@callback(
    Output("gate-store", "data", allow_duplicate=True),
    Input({"type": "gate-open-btn", "sid": ALL, "gate": ALL}, "n_clicks"),
    State("gate-store",          "data"),
    State("plan-stories-store",  "data"),
    prevent_initial_call=True,
)
def _toggle_gate(gate_clicks, gates, stories_data):
    if not any(gate_clicks or []):
        return no_update
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict) or triggered.get("type") != "gate-open-btn":
        return no_update

    sid      = triggered["sid"]
    gate     = triggered["gate"]
    sid_str  = str(sid)

    current  = dict(gates or {})
    g        = dict(current.get(sid_str, {f: False for f in _GATE_FIELDS}))
    new_val  = not g.get(gate, False)

    g[gate] = new_val
    # Cascade clear downstream gates when unchecking
    if not new_val:
        gate_order = list(_GATE_FIELDS)
        idx = gate_order.index(gate) if gate in gate_order else -1
        for ds in gate_order[idx + 1:]:
            g[ds] = False

    current[sid_str] = g

    try:
        from flask_login import current_user as _cu
        performed_by = _cu.display_name if _cu and _cu.is_authenticated else "system"
    except Exception:
        performed_by = "system"
    try:
        from db.planning import upsert_gate as _upsert
        story_obj = next((s for s in (stories_data or []) if s["id"] == sid), {})
        _upsert(int(sid), gate, new_val, performed_by,
                title=story_obj.get("title", ""),
                ba=story_obj.get("ba", ""),
                dev_name=story_obj.get("dev", ""),
                month_key=story_obj.get("month", ""),
                priority=story_obj.get("pri", ""))
    except Exception:
        pass

    return current


# ── 4. Re-render story table + readiness header + stuck filter bar ────────────
@callback(
    Output("story-tbody",        "children"),
    Output("readiness-header",   "children"),
    Output("story-page-info",    "children"),
    Output("story-page-prev",    "disabled"),
    Output("story-page-next",    "disabled"),
    Output("story-pagination",   "style"),
    Output("stuck-filter-bar",   "children"),
    Output("dash-summary-text",  "children"),
    Input("gate-store",          "data"),
    Input("plan-active-month",   "data"),
    Input("plan-ba-filter",      "data"),
    Input("plan-dev-filter",     "data"),
    Input("plan-show-filter",    "data"),
    Input("plan-type-filter",    "data"),
    Input("plan-tier-filter",    "data"),
    Input("story-page",          "data"),
    Input("stuck-filter",        "data"),
    State("plan-stories-store",  "data"),
)
def _render_stories(gates, month, ba_f, dev_f, show_f, type_f, tier_f, page, stuck_f, stories_data):
    all_month = [s for s in (stories_data or []) if s["month"] == month]
    stories   = list(all_month)

    if ba_f and ba_f != "All BAs":
        stories = [s for s in stories if s["ba"].startswith(ba_f)]
    if dev_f and dev_f != "All":
        stories = [s for s in stories if s["dev"].split()[0] == dev_f]
    _actionable = {"NOT STARTED", "IN PROGRESS"}
    if show_f == "Needs Action":
        stories = [s for s in stories
                   if _status(gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS})) in _actionable]
    elif show_f == "Ready":
        stories = [s for s in stories
                   if _status(gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS})) not in _actionable]
    if type_f == "Enhancements":
        stories = [s for s in stories if s["type"] == "ENH"]
    elif type_f == "Issues":
        stories = [s for s in stories if s["type"] == "ISSUE"]

    def _gst(s):
        return gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS})

    if tier_f and tier_f != "all":
        if tier_f == "not_started":
            stories = [s for s in stories if _status(_gst(s)) == "NOT STARTED"]
        elif tier_f == "in_progress":
            stories = [s for s in stories if _status(_gst(s)) == "IN PROGRESS"]
        elif tier_f == "complete":
            stories = [s for s in stories if _status(_gst(s)) == "READY"]

    # Stuck-at filter
    def _stuck_gate(s):
        g = _gst(s)
        for f in _GATE_FIELDS:
            if not g.get(f):
                return f
        return None  # all gates done

    if stuck_f and stuck_f != "all":
        if stuck_f == "not_started":
            stories = [s for s in stories if _status(_gst(s)) == "NOT STARTED"]
        elif stuck_f == "complete":
            stories = [s for s in stories if _status(_gst(s)) == "READY"]
        else:
            stories = [s for s in stories if _stuck_gate(s) == stuck_f]

    _pri_ord = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    def _sort_key(s):
        st = _status(gates.get(str(s["id"]), {f: s.get(f, False) for f in _GATE_FIELDS}))
        return (0 if st != "READY" else 1, _pri_ord.get(s["pri"], 9), s["id"])
    stories.sort(key=_sort_key)

    # Paginate
    total_filtered = len(stories)
    total_pages    = max(1, -(-total_filtered // _PAGE_SIZE))  # ceiling div
    page           = max(1, min(page or 1, total_pages))
    start          = (page - 1) * _PAGE_SIZE
    page_stories   = stories[start : start + _PAGE_SIZE]

    rows = [_story_row(s, gates) for s in page_stories]
    if not rows:
        rows = [html.Tr(html.Td(
            "No stories match the current filters.",
            colSpan=6,
            style={"textAlign": "center", "color": MT, "padding": "32px"},
        ))]

    _pag_style_show = {"display": "flex", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0"}
    _pag_style_hide = {"display": "none"}
    if total_pages <= 1:
        pag_style    = _pag_style_hide
        page_info    = ""
        prev_disabled = True
        next_disabled = True
    else:
        pag_style    = _pag_style_show
        page_info    = f"Page {page} of {total_pages}"
        prev_disabled = (page <= 1)
        next_disabled = (page >= total_pages)

    # Readiness header (always uses the full month, not filtered)
    ready = sum(
        1 for s in all_month
        if _status(gates.get(str(s["id"]),
                   {f: s.get(f, False) for f in _GATE_FIELDS})) == "READY"
    )
    total = len(all_month)
    pct   = round(ready / total * 100) if total else 0
    c     = G if pct >= 80 else A if pct >= 50 else R

    # Group by BA
    ba_groups: dict = {}
    for s in all_month:
        key = (s["ba"], s["ba_code"], s["ba_role"])
        ba_groups.setdefault(key, []).append(s)

    ba_cards = []
    for (ba_name, ba_code, ba_role), ss in sorted(ba_groups.items()):
        r = sum(
            1 for s in ss
            if _status(gates.get(str(s["id"]),
                       {f: s.get(f, False) for f in _GATE_FIELDS})) == "READY"
        )
        ba_cards.append(
            _ba_card(ba_name, ba_code, ba_role,
                     round(r / len(ss) * 100) if ss else 100, r, len(ss))
        )

    header = html.Div([
        html.Div([
            html.Div([
                html.Span(month, style={"color": P, "fontSize": "13px", "fontWeight": "700",
                                        "marginRight": "4px"}),
                html.Span("· READINESS", style={"color": MT, "fontSize": "11px",
                                                  "fontWeight": "600", "textTransform": "uppercase",
                                                  "letterSpacing": "1px"}),
            ], style={"flexShrink": "0"}),
            html.Div([
                html.Div(style={
                    "width": f"{pct}%", "height": "100%",
                    "background": f"linear-gradient(to right, {c}88, {c})",
                    "borderRadius": "4px",
                    "transition": "width 0.5s ease",
                    "minWidth": "2px" if pct > 0 else "0",
                }),
            ], style={
                "flex": "1", "height": "6px",
                "background": "rgba(255,255,255,0.06)",
                "borderRadius": "4px", "margin": "0 20px",
            }),
            html.Div([
                html.Span(f"{pct}%", style={"color": c, "fontSize": "22px",
                                             "fontWeight": "800", "marginRight": "10px"}),
                html.Span(f"{ready} / {total} Ready",
                          style={"color": MT, "fontSize": "12px", "whiteSpace": "nowrap"}),
            ], style={"display": "flex", "alignItems": "center", "flexShrink": "0"}),
        ], style={
            "display": "flex", "alignItems": "center",
            "background": CD, "border": f"1px solid {BD}",
            "borderRadius": "12px", "padding": "14px 20px",
            "marginBottom": "12px",
        }),
        html.Div(ba_cards,
                 style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
                         "marginBottom": "16px"}),
    ])

    # ── WHERE STORIES ARE STUCK filter bar ────────────────────────────────────
    def _count_stuck(gate_key):
        return sum(1 for s in all_month if _stuck_gate(s) == gate_key)

    n_total    = len(all_month)
    n_ns       = sum(1 for s in all_month if _status(_gst(s)) == "NOT STARTED")
    n_complete = sum(1 for s in all_month if _status(_gst(s)) == "READY")

    _sfbtn_act = {"padding": "5px 12px", "borderRadius": "20px", "fontSize": "12px",
                  "fontWeight": "600", "cursor": "pointer",
                  "background": _dim(A), "color": A, "border": f"1px solid {A}"}
    _sfbtn_idl = {"padding": "5px 12px", "borderRadius": "20px", "fontSize": "12px",
                  "fontWeight": "500", "cursor": "pointer",
                  "background": "var(--bg-hover)", "color": MT, "border": f"1px solid {BD}"}

    def _sfbtn(label, count, key):
        is_act = (stuck_f or "all") == key
        return html.Div(
            f"{label} ({count})",
            id={"type": "stuck-chip", "v": key},
            n_clicks=0,
            style=_sfbtn_act if is_act else _sfbtn_idl,
        )

    stuck_bar = html.Div([
        html.Span("WHERE STORIES ARE STUCK", style={
            "fontSize": "9px", "fontWeight": "800", "letterSpacing": "2px",
            "textTransform": "uppercase", "color": A, "marginRight": "14px",
            "flexShrink": "0", "alignSelf": "center",
        }),
        _sfbtn("All",         n_total,    "all"),
        _sfbtn("Not started", n_ns,       "not_started"),
        *[_sfbtn(f"Stuck: {_GATE_LABELS[f]}", _count_stuck(f), f) for f in _GATE_FIELDS],
        _sfbtn("Complete",    n_complete, "complete"),
    ], style={
        "display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "6px",
        "background": CD, "border": f"1px solid {BD}", "borderRadius": "10px",
        "padding": "10px 16px",
    })

    summary_text = html.Span(
        f"{month}  ·  {pct}% ({ready}/{total} ready)  ·  {total_filtered} of {total} stories shown",
        style={"color": MT, "fontSize": "12px", "fontWeight": "500"},
    )

    return rows, header, page_info, prev_disabled, next_disabled, pag_style, stuck_bar, summary_text


@callback(
    Output("stuck-filter", "data"),
    Input({"type": "stuck-chip", "v": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _stuck_filter_update(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("v", "all")
    return "all"


# ── Dashboard show/hide toggle ─────────────────────────────────────────────────
@callback(
    Output("dash-collapsed", "data"),
    Input("dash-toggle-btn", "n_clicks"),
    State("dash-collapsed",  "data"),
    prevent_initial_call=True,
)
def _toggle_dashboard(n, collapsed):
    return not (collapsed or False)


@callback(
    Output("dash-toggle-btn",       "children"),
    Output("kpi-panel",             "style"),
    Output("month-tabs-container",  "style"),
    Output("dash-summary-text",     "style"),
    Input("dash-collapsed",         "data"),
)
def _apply_dashboard_collapse(collapsed):
    _sticky_base = {
        "position": "sticky", "top": "50px", "zIndex": "20",
        "background": C3,
        "paddingTop": "8px", "paddingBottom": "10px",
        "marginBottom": "4px",
    }
    if collapsed:
        return (
            ["▶ Show dashboard"],
            {"display": "none"},
            {**_sticky_base, "display": "none"},
            {"display": "inline", "color": MT, "fontSize": "12px", "fontWeight": "500"},
        )
    return (
        ["▼ Hide dashboard"],
        {"display": "block"},
        _sticky_base,
        {"display": "none"},
    )


@callback(
    Output("story-page", "data"),
    Input("plan-active-month", "data"),
    Input("plan-ba-filter",    "data"),
    Input("plan-dev-filter",   "data"),
    Input("plan-show-filter",  "data"),
    Input("plan-type-filter",  "data"),
    Input("plan-tier-filter",  "data"),
    Input("stuck-filter",      "data"),
    prevent_initial_call=True,
)
def _reset_story_page(*_):
    return 1


@callback(
    Output("story-page", "data", allow_duplicate=True),
    Input("story-page-prev", "n_clicks"),
    State("story-page",      "data"),
    prevent_initial_call=True,
)
def _story_prev(_, page):
    return max(1, (page or 1) - 1)


@callback(
    Output("story-page", "data", allow_duplicate=True),
    Input("story-page-next", "n_clicks"),
    State("story-page",      "data"),
    prevent_initial_call=True,
)
def _story_next(_, page):
    return (page or 1) + 1


# ── 4b. Render bug table ──────────────────────────────────────────────────────
@callback(
    Output("bug-tbody",       "children"),
    Output("bug-page-info",   "children"),
    Output("bug-page-prev",   "disabled"),
    Output("bug-page-next",   "disabled"),
    Output("bug-pagination",  "style"),
    Input("plan-active-month", "data"),
    Input("bug-page",          "data"),
    State("plan-bugs-store",   "data"),
)
def _render_bugs(month, page, bugs_data):
    bugs = [b for b in (bugs_data or []) if b["month"] == month]
    bugs.sort(key=lambda b: (b["pri"], b["id"]))

    total_pages = max(1, -(-len(bugs) // _PAGE_SIZE))
    page        = max(1, min(page or 1, total_pages))
    start       = (page - 1) * _PAGE_SIZE
    page_bugs   = bugs[start : start + _PAGE_SIZE]

    rows = [_bug_row(b) for b in page_bugs]
    if not rows:
        rows = [html.Tr(html.Td(
            "No issues for this iteration.",
            colSpan=5,
            style={"textAlign": "center", "color": MT, "padding": "28px"},
        ))]

    _pag_style_show = {"display": "flex", "alignItems": "center",
                        "justifyContent": "center", "gap": "8px", "padding": "10px 0"}
    if total_pages <= 1:
        return rows, "", True, True, {"display": "none"}
    return rows, f"Page {page} of {total_pages}", (page <= 1), (page >= total_pages), _pag_style_show


@callback(
    Output("bug-page", "data"),
    Input("plan-active-month", "data"),
    prevent_initial_call=True,
)
def _reset_bug_page(_):
    return 1


@callback(
    Output("bug-page", "data", allow_duplicate=True),
    Input("bug-page-prev", "n_clicks"),
    State("bug-page",      "data"),
    prevent_initial_call=True,
)
def _bug_prev(_, page):
    return max(1, (page or 1) - 1)


# ── TYPE filter (BA Sign-Off bottom strip) ─────────────────────────────────────
@callback(
    Output("ba-type-f", "data"),
    Output({"type": "ba-type-btn", "v": "Enhancements"}, "style"),
    Output({"type": "ba-type-btn", "v": "Issues"},       "style"),
    Input({"type": "ba-type-btn", "v": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _ba_type_filter(n_clicks):
    _act = {"background": P_DIM, "border": f"1px solid {P}", "borderRadius": "20px",
            "color": P, "fontSize": "12px", "fontWeight": "600",
            "padding": "5px 14px", "cursor": "pointer", "boxShadow": f"0 0 10px {P_BRD}"}
    _idl = {"background": "var(--bg-hover)", "border": f"1px solid {BD}",
            "borderRadius": "20px", "color": MT, "fontSize": "12px", "fontWeight": "500",
            "padding": "5px 14px", "cursor": "pointer", "boxShadow": "none"}
    triggered = ctx.triggered_id
    v = triggered.get("v", "Enhancements") if isinstance(triggered, dict) else "Enhancements"
    styles = {lbl: (_act if lbl == v else _idl) for lbl in ("Enhancements", "Issues")}
    return v, styles["Enhancements"], styles["Issues"]


@callback(
    Output("enh-section", "style"),
    Output("bug-section", "style"),
    Input("ba-type-f", "data"),
    prevent_initial_call=True,
)
def _toggle_ba_section(ba_type):
    if ba_type == "Issues":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


# ── BA filter panel toggle ────────────────────────────────────────────────────
@callback(
    Output("ba-flt-panel",    "style"),
    Output("ba-flt-backdrop", "style"),
    Input("ba-flt-open-btn",    "n_clicks"),
    Input("ba-flt-panel-close", "n_clicks"),
    Input("ba-flt-backdrop",    "n_clicks"),
    prevent_initial_call=True,
)
def _toggle_ba_filter_panel(open_n, close_n, backdrop_n):
    if ctx.triggered_id == "ba-flt-open-btn":
        return _FLT_PANEL_OPEN, _BACKDROP_OPEN
    return _FLT_PANEL_CLOSED, _BACKDROP_CLOSED


@callback(
    Output("bug-page", "data", allow_duplicate=True),
    Input("bug-page-next", "n_clicks"),
    State("bug-page",      "data"),
    prevent_initial_call=True,
)
def _bug_next(_, page):
    return (page or 1) + 1


# ── 5. BA filter chip ─────────────────────────────────────────────────────────
@callback(
    Output("plan-ba-filter", "data"),
    Input("ba-all-chip",                    "n_clicks"),
    Input({"type": "ba-chip", "ba": ALL},   "n_clicks"),
    prevent_initial_call=True,
)
def _ba_filter(all_clicks, ba_clicks):
    triggered = ctx.triggered_id
    if triggered == "ba-all-chip":
        return "All BAs"
    if isinstance(triggered, dict):
        return triggered.get("ba", "All BAs")
    return "All BAs"


# ── 6. Dev filter chip ────────────────────────────────────────────────────────
@callback(
    Output("plan-dev-filter", "data"),
    Input("dev-all-chip",                    "n_clicks"),
    Input({"type": "dev-chip", "dev": ALL},  "n_clicks"),
    prevent_initial_call=True,
)
def _dev_filter(all_clicks, dev_clicks):
    triggered = ctx.triggered_id
    if triggered == "dev-all-chip":
        return "All"
    if isinstance(triggered, dict):
        return triggered.get("dev", "All")
    return "All"


# ── 7. Show filter chip ───────────────────────────────────────────────────────
@callback(
    Output("plan-show-filter", "data"),
    Input({"type": "show-chip", "show": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _show_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("show", "Needs Action")
    return "Needs Action"


# ── 8. Type filter buttons ────────────────────────────────────────────────────
@callback(
    Output("plan-type-filter", "data"),
    Input({"type": "type-f", "v": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _type_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("v", "All")
    return "All"


# ── Chip highlight helpers ─────────────────────────────────────────────────────
def _chip_style(active, size="md", color=None):
    c   = color or P
    pad = "5px 14px" if size == "lg" else "5px 12px"
    if active:
        return {
            "padding": pad, "borderRadius": "20px", "fontSize": "12px",
            "fontWeight": "600", "cursor": "pointer",
            "background": _dim(c), "color": c,
            "border": f"1px solid {c}", "boxShadow": f"0 0 10px {_brd(c)}",
        }
    return {
        "padding": pad, "borderRadius": "20px", "fontSize": "12px",
        "fontWeight": "500", "cursor": "pointer",
        "background": "var(--bg-hover)", "color": MT,
        "border": f"1px solid {BD}", "boxShadow": "none",
    }


@callback(
    Output("dev-all-chip",                   "style"),
    Output({"type": "dev-chip", "dev": ALL}, "style"),
    Input("plan-dev-filter", "data"),
    State({"type": "dev-chip", "dev": ALL}, "id"),
    prevent_initial_call=True,
)
def _update_dev_chips(active, chip_ids):
    all_style   = _chip_style(active == "All", color=B)
    chip_styles = [_chip_style(cid["dev"] == active, color=B) for cid in (chip_ids or [])]
    return all_style, chip_styles


@callback(
    Output("ba-all-chip",                   "style"),
    Output({"type": "ba-chip", "ba": ALL},  "style"),
    Input("plan-ba-filter", "data"),
    State({"type": "ba-chip", "ba": ALL},   "id"),
    prevent_initial_call=True,
)
def _update_ba_chips(active, chip_ids):
    all_style   = _chip_style(active == "All BAs", size="lg", color=P)
    chip_styles = [_chip_style(cid["ba"] == active, size="lg", color=P) for cid in (chip_ids or [])]
    return all_style, chip_styles


@callback(
    Output({"type": "show-chip", "show": ALL}, "style"),
    Input("plan-show-filter", "data"),
    State({"type": "show-chip", "show": ALL}, "id"),
    prevent_initial_call=True,
)
def _update_show_chips(active, chip_ids):
    styles = []
    for cid in (chip_ids or []):
        label = cid["show"]
        color = A if label == "Needs Action" else P
        styles.append(_chip_style(label == active, color=color))
    return styles


# ── Tier filter chip ─────────────────────────────────────────────────────────
@callback(
    Output("plan-tier-filter", "data"),
    Input({"type": "tier-chip", "tier": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _tier_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("tier", "all")
    return "all"


@callback(
    Output({"type": "tier-chip", "tier": ALL}, "style"),
    Input("plan-tier-filter", "data"),
    State({"type": "tier-chip", "tier": ALL}, "id"),
    prevent_initial_call=True,
)
def _update_tier_chips(active, chip_ids):
    return [_chip_style(cid["tier"] == active, color=G) for cid in (chip_ids or [])]


@callback(
    Output({"type": "type-f", "v": ALL}, "style"),
    Input("plan-type-filter", "data"),
    State({"type": "type-f", "v": ALL}, "id"),
    prevent_initial_call=True,
)
def _update_type_chips(active, chip_ids):
    styles = []
    for cid in (chip_ids or []):
        is_active = cid["v"] == active
        styles.append({
            "background":   (A + "33") if is_active else "transparent",
            "border":       f"1px solid {A}" if is_active else f"1px solid {BD}",
            "borderRadius": "12px",
            "color":        A if is_active else MT,
            "fontSize":     "11px",
            "fontWeight":   "700" if is_active else "400",
            "padding":      "3px 10px", "cursor": "pointer", "marginRight": "4px",
        })
    return styles


# ── BA Team Brief — role card accordion ──────────────────────────────────────
@callback(
    Output({"type": "ba-role-body",   "role": ALL}, "style"),
    Output({"type": "ba-role-toggle", "role": ALL}, "children"),
    Input({"type": "ba-role-toggle",  "role": ALL}, "n_clicks"),
    State({"type": "ba-role-body",    "role": ALL}, "style"),
    State({"type": "ba-role-toggle",  "role": ALL}, "id"),
    prevent_initial_call=True,
)
def _toggle_ba_role(n_clicks, body_styles, toggle_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    new_styles  = []
    new_icons   = []
    for tid, style in zip(toggle_ids, body_styles):
        currently_open = style.get("display") != "none"
        if tid["role"] == triggered["role"]:
            new_open = not currently_open
        else:
            new_open = currently_open
        new_styles.append({"display": "block", "padding": "4px 24px 20px"}
                          if new_open else {"display": "none"})
        new_icons.append("×" if new_open else "+")
    return new_styles, new_icons


# ── BA Team Brief — sub-tab switcher ─────────────────────────────────────────
@callback(
    Output("ba-tab-role",                              "style"),
    Output("ba-tab-kpi",                               "style"),
    Output("ba-tab-ops",                               "style"),
    Output({"type": "ba-brief-tab", "tab": ALL},       "style"),
    Input({"type": "ba-brief-tab",  "tab": ALL},       "n_clicks"),
    State({"type": "ba-brief-tab",  "tab": ALL},       "id"),
    prevent_initial_call=True,
)
def _switch_ba_brief_tab(n_clicks, tab_ids):
    triggered = ctx.triggered_id
    if not triggered:
        raise dash.exceptions.PreventUpdate
    tab  = triggered["tab"]
    show = {"display": "block"}
    hide = {"display": "none"}
    btn_styles = []
    for tid in (tab_ids or []):
        active = tid["tab"] == tab
        btn_styles.append({
            "background":   A_DIM if active else "transparent",
            "border":       "none",
            "borderBottom": f"2px solid {A}" if active else "2px solid transparent",
            "color":        TX if active else MT,
            "fontSize":     "13px", "fontWeight": "600" if active else "400",
            "padding":      "8px 16px", "cursor": "pointer", "marginRight": "4px",
        })
    return (
        show if tab == "role" else hide,
        show if tab == "kpi"  else hide,
        show if tab == "ops"  else hide,
        btn_styles,
    )


# ── Size filter (By Story tab) ────────────────────────────────────────────────
@callback(
    Output("plan-size-filter", "data"),
    Input({"type": "size-f", "v": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _size_filter(n_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict):
        return triggered.get("v", "All")
    return "All"


@callback(
    Output({"type": "size-f", "v": ALL}, "style"),
    Input("plan-size-filter", "data"),
    State({"type": "size-f", "v": ALL}, "id"),
    prevent_initial_call=True,
)
def _update_size_chips(active, chip_ids):
    styles = []
    for cid in (chip_ids or []):
        is_active = cid["v"] == active
        styles.append({
            "background":   (B + "33") if is_active else "transparent",
            "border":       f"1px solid {B}" if is_active else f"1px solid {BD}",
            "borderRadius": "12px",
            "color":        B if is_active else MT,
            "fontSize":     "11px",
            "fontWeight":   "700" if is_active else "400",
            "padding":      "3px 10px", "cursor": "pointer", "marginRight": "4px",
        })
    return styles


# ── Story matrix re-render on TYPE / SIZE filter or gate change ───────────────
@callback(
    Output("story-matrix-wrap", "children"),
    Input("plan-type-filter",  "data"),
    Input("plan-size-filter",  "data"),
    Input("gate-store",        "data"),
    State("plan-story-matrix", "data"),
    prevent_initial_call=True,
)
def _filter_story_matrix(type_f, size_f, gates, story_matrix):
    if not story_matrix:
        return []
    MATRIX_MONTHS = _matrix_months()
    filtered = story_matrix
    if type_f and type_f != "All":
        want = "ENH" if type_f == "Enhancements" else "ISSUE"
        filtered = [sm for sm in filtered if sm.get("type") == want]
    if size_f and size_f != "All":
        filtered = [sm for sm in filtered if sm.get("size") == size_f]
    if gates:
        updated = []
        for sm in filtered:
            sid = str(sm.get("id", ""))
            g   = gates.get(sid, {f: False for f in _GATE_FIELDS})
            sk  = _story_status_key(g)
            new_sm = dict(sm)
            for mk in MATRIX_MONTHS:
                if new_sm.get(mk) is not None:
                    dev, _ = new_sm[mk]
                    new_sm[mk] = (dev, sk)
            updated.append(new_sm)
        filtered = updated
    return [_build_story_matrix(filtered)]


# ── Dev matrix live-update on gate change ─────────────────────────────────────
_SP = {
    "story_frozen": 0, "draft": 1, "not_started": 2,
}

@callback(
    Output("dev-matrix-wrap", "children"),
    Input("gate-store",         "data"),
    State("plan-dev-stories",   "data"),
    prevent_initial_call=True,
)
def _live_dev_matrix(gates, dev_stories):
    if not dev_stories:
        return no_update
    MATRIX_MONTHS = _matrix_months()
    dev_matrix: dict = {}
    for ds in dev_stories:
        dname = ds["dev"]
        month = ds["month"]
        sid   = str(ds["id"])
        g     = (gates or {}).get(sid, {f: False for f in _GATE_FIELDS})
        sk    = _story_status_key(g)
        if dname not in dev_matrix:
            dev_matrix[dname] = {"role": ds["role"], "ns": 0,
                                  **{mk: None for mk in MATRIX_MONTHS}}
        if dev_matrix[dname][month] is None:
            dev_matrix[dname][month] = (1, sk)
        else:
            cnt, csk = dev_matrix[dname][month]
            worst = csk if _SP.get(csk, 9) >= _SP.get(sk, 9) else sk
            dev_matrix[dname][month] = (cnt + 1, worst)
        if not any(g.get(f, False) for f in _GATE_FIELDS):
            dev_matrix[dname]["ns"] += 1
    today_month = date.today().month
    return [_build_dev_matrix(dev_matrix, today_month)]


# ── 9. Sign-off log modal ─────────────────────────────────────────────────────
_GATE_LABEL = {
    "claude_screens": "Claude Screens",
    "text_written":   "Text Written",
    "our_screens":    "Our Screens",
    "html_screens":   "HTML Screens",
    "sn_signoff":     "SN Sign-Off",
}


@callback(
    Output("signoff-modal", "is_open"),
    Output("log-body",      "children"),
    Output("log-footer",    "children"),
    Input("signoff-log-btn", "n_clicks"),
    Input("signoff-modal",   "is_open"),
    State("log-store", "data"),
    prevent_initial_call=True,
)
def _toggle_log(n_clicks, is_open, session_log):
    if ctx.triggered_id != "signoff-log-btn":
        return False, no_update, no_update

    # ── Pull full history from DB ─────────────────────────────────────────────
    try:
        from db.planning import get_log as _get_log
        db_entries = _get_log(limit=300)
    except Exception:
        db_entries = []

    if not db_entries:
        body = html.Div(
            "No sign-off actions recorded yet.",
            style={"color": MT, "fontSize": "13px", "padding": "16px"},
        )
    else:
        cards = []
        for entry in db_entries:   # already newest-first from DB
            is_conf  = entry.get("action") == "Confirmed"
            gate_lbl = _GATE_LABEL.get(entry.get("gate", ""), entry.get("gate", ""))
            pri      = entry.get("priority") or "—"
            # Format timestamp
            pat = entry.get("performed_at")
            if hasattr(pat, "strftime"):
                time_str = pat.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = str(pat)[:16] if pat else "—"

            cards.append(html.Div([
                html.Div([
                    html.Span(time_str,
                              style={"color": MT, "fontSize": "10px", "marginRight": "10px"}),
                    html.Span(gate_lbl,
                              style={"color": P, "fontSize": "11px", "fontWeight": "700",
                                     "marginRight": "8px"}),
                    html.Span(
                        ("✓ " if is_conf else "✗ ") + entry.get("action", ""),
                        style={"color": G if is_conf else R,
                               "fontSize": "11px", "fontWeight": "700"},
                    ),
                    html.Span(
                        f" · {entry.get('performed_by', '')}",
                        style={"color": MT, "fontSize": "10px", "marginLeft": "6px"},
                    ),
                ], style={"marginBottom": "4px"}),
                html.A(
                    entry.get("title") or f"Item #{entry.get('work_item_id')}",
                    href=f"{ADO_BASE_URL}{entry.get('work_item_id', '')}",
                    target="_blank",
                    style={"color": TX, "fontSize": "12px", "fontWeight": "600",
                           "marginBottom": "2px", "textDecoration": "none", "display": "block"},
                ),
                html.Div([
                    html.Span(f"BA: {entry.get('ba') or '—'}",
                              style={"color": MT, "fontSize": "10px", "marginRight": "12px"}),
                    html.Span(f"Dev: {entry.get('dev_name') or '—'}",
                              style={"color": MT, "fontSize": "10px", "marginRight": "12px"}),
                    html.Span(f"Month: {entry.get('month_key') or '—'}",
                              style={"color": MT, "fontSize": "10px", "marginRight": "12px"}),
                    html.Span(f"Pri: {pri}",
                              style={"color": _pri_clr(pri), "fontSize": "10px"}),
                ], style={"marginBottom": "4px"}),
                html.Div([
                    html.Span("→ ", style={"color": MT, "fontSize": "10px"}),
                    html.Span(
                        entry.get("new_status", ""),
                        style={"color": G if is_conf else R,
                               "fontSize": "10px", "fontWeight": "700"},
                    ),
                ]),
            ], style={
                "background": C2, "border": f"1px solid {BD}",
                "borderRadius": "8px", "padding": "12px 14px", "marginBottom": "8px",
            }))
        body = html.Div(cards)

    # Footer: totals from DB
    confirmed = sum(1 for e in db_entries if e.get("action") == "Confirmed")
    cleared   = sum(1 for e in db_entries if e.get("action") == "Cleared")
    total     = len(db_entries)
    footer = html.Div([
        html.Span(f"✓ Confirmed: {confirmed}",
                  style={"color": G, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"✗ Cleared: {cleared}",
                  style={"color": R, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"Total log entries: {total}",
                  style={"color": MT, "fontSize": "12px"}),
    ])
    return True, body, footer


# ── 9. Matrix cell click → slide-out panel ────────────────────────────────────
@callback(
    Output("matrix-panel",      "style"),
    Output("matrix-panel-hdr",  "children"),
    Output("matrix-panel-body", "children"),
    Input({"type": "matrix-cell", "dev": ALL, "month": ALL}, "n_clicks"),
    Input("matrix-panel-close", "n_clicks"),
    State("plan-stories-store", "data"),
    prevent_initial_call=True,
)
def _matrix_panel(cell_clicks, close_click, stories_data):
    triggered = ctx.triggered_id
    if triggered == "matrix-panel-close" or not triggered:
        return _CAP_PANEL_CLOSED, no_update, no_update
    # New matrix-cell components rendered by live-update have n_clicks=0 — ignore
    if not any(n and n > 0 for n in (cell_clicks or [])):
        return no_update, no_update, no_update

    dev   = triggered.get("dev", "")
    month = triggered.get("month", "")

    # ── Month label ───────────────────────────────────────────────────────────
    today_m   = date.today().month
    m_offset  = {"M0": 0, "M1": 1, "M2": 2}.get(month, 0)
    cal_month = _CAL.get(min(today_m + m_offset, 12), month)
    month_lbl = f"{month} · {cal_month} 2026"

    # ── Filter stories for this dev × month ──────────────────────────────────
    _pri_ord = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    _sort    = lambda lst: sorted(lst, key=lambda s: (_pri_ord.get(s["pri"], 9), s["id"]))

    dev_stories = _sort([
        s for s in (stories_data or [])
        if s["dev"].split()[0] == dev.split()[0] and s["month"] == month
    ])

    # ── Group by readiness status ─────────────────────────────────────────────
    groups = {"not_started": [], "draft": [], "story_frozen": []}
    for s in dev_stories:
        sk = _story_status_key(s)
        groups.setdefault(sk, []).append(s)

    _STATUS_META = {
        "not_started":  ("Not Started", R,         "■"),
        "draft":        ("In Progress", A,         "■"),
        "story_frozen": ("Ready",       G,         "■"),
    }

    # ── KPI count boxes ───────────────────────────────────────────────────────
    def _kpi_box(count, label, color):
        return html.Div([
            html.Div(str(count), style={
                "fontSize": "36px", "fontWeight": "800", "color": color,
                "lineHeight": "1", "textAlign": "center", "letterSpacing": "-1px",
            }),
            html.Div(label, style={
                "fontSize": "10px", "fontWeight": "700", "color": MT,
                "textTransform": "uppercase", "letterSpacing": "0.8px",
                "marginTop": "8px", "textAlign": "center",
            }),
        ], style={
            "flex": "1", "minWidth": "0",
            "display": "flex", "flexDirection": "column",
            "alignItems": "center", "justifyContent": "center",
            "padding": "20px 6px", "background": _dim(color),
            "borderRadius": "12px", "border": f"1px solid {_brd(color)}",
            "borderBottom": f"3px solid {color}", "margin": "0 4px",
        })

    kpi_order = ["story_frozen", "draft", "not_started"]
    kpi_boxes = [
        _kpi_box(len(groups[k]), _STATUS_META[k][0], _STATUS_META[k][1])
        for k in kpi_order if groups[k]
    ]
    if not kpi_boxes:
        kpi_boxes = [_kpi_box(0, "No Items", MT)]

    # ── Section header ────────────────────────────────────────────────────────
    def _sec_hdr(label, count, color):
        return html.Div([
            html.Span(label, style={
                "fontSize": "10px", "fontWeight": "800", "color": color,
                "textTransform": "uppercase", "letterSpacing": "1.2px",
            }),
            html.Span(f"{count} item{'s' if count != 1 else ''}", style={
                "fontSize": "10px", "color": MT,
            }),
        ], style={
            "display": "flex", "justifyContent": "space-between", "alignItems": "center",
            "borderBottom": f"1px solid {BD}",
            "paddingBottom": "8px", "marginBottom": "12px", "marginTop": "20px",
        })

    # ── Story card with gate checkmarks ───────────────────────────────────────
    def _story_card(s):
        hrs_lbl = f"{s['hrs']:.0f}h" if s.get("hrs") else "—"
        hrs_clr = MT if not s.get("hrs") else TX

        def _gate(ok, label):
            clr = G if ok else R
            sym = "✓" if ok else "✗"
            return html.Span([
                html.Span(f"{sym} ", style={"color": clr, "fontWeight": "700"}),
                html.Span(label,     style={"color": MT}),
            ], style={"fontSize": "10px", "marginRight": "14px"})

        return html.Div([
            html.A(s["title"],
                   href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                   style={"color": TX, "fontSize": "13px", "fontWeight": "600",
                          "textDecoration": "none", "display": "block",
                          "lineHeight": "1.45", "marginBottom": "10px"}),
            html.Div([
                _tag(s["pri"], _pri_clr(s["pri"])),
                html.Span(s.get("size") or s["type"], style={
                    "fontSize": "10px", "fontWeight": "600", "color": A,
                    "background": A_DIM, "border": f"1px solid {A_BRD}",
                    "borderRadius": "4px", "padding": "1px 7px", "marginLeft": "6px",
                }),
                html.Span(hrs_lbl, style={
                    "fontSize": "11px", "fontWeight": "700", "color": hrs_clr,
                    "marginLeft": "8px",
                }),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
            html.Div([
                _gate(s.get(f, False), _GATE_LABELS.get(f, f))
                for f in _GATE_FIELDS
            ], style={"display": "flex", "flexWrap": "wrap"}),
        ], style={
            "background": C3, "borderRadius": "10px",
            "padding": "14px 16px", "marginBottom": "8px",
        })

    # ── Header ────────────────────────────────────────────────────────────────
    total = len(dev_stories)
    hdr_children = [
        html.Span("STORY READINESS DETAIL", style={
            "fontSize": "9px", "color": MT, "textTransform": "uppercase",
            "letterSpacing": "1.5px", "display": "block", "marginBottom": "4px",
        }),
        html.Span(dev, style={"color": TX}),
        html.Span(f"  ·  {month_lbl}  ·  {total} items",
                  style={"color": MT, "fontWeight": "400", "fontSize": "13px"}),
    ]

    # ── KPI row + count line ──────────────────────────────────────────────────
    kpi_section = html.Div([
        html.Div(kpi_boxes, style={"display": "flex", "margin": "20px -4px 16px"}),
        html.Div([
            html.Span(str(total), style={"fontSize": "20px", "fontWeight": "800", "color": TX,
                                         "marginRight": "5px"}),
            html.Span("ITEMS", style={"fontSize": "10px", "fontWeight": "700", "color": MT,
                                      "letterSpacing": "1px", "textTransform": "uppercase"}),
        ], style={"display": "flex", "alignItems": "baseline",
                  "borderTop": f"1px solid {BD}", "paddingTop": "14px"}),
    ], style={"padding": "0 20px 16px", "borderBottom": f"1px solid {BD}"})

    # ── Story sections ordered by urgency ─────────────────────────────────────
    section_order = ["not_started", "draft", "story_frozen"]
    if not dev_stories:
        cards_block = html.Div(
            "No stories planned for this developer in this month.",
            style={"color": MT, "fontSize": "13px", "padding": "20px"},
        )
    else:
        parts = []
        for key in section_order:
            grp = groups[key]
            if not grp:
                continue
            label, color, _ = _STATUS_META[key]
            parts.append(_sec_hdr(f"{label}  ·  {len(grp)} items", len(grp), color))
            parts.extend(_story_card(s) for s in grp)
        cards_block = html.Div(parts, style={"padding": "16px 20px 48px"})

    panel_body = html.Div([kpi_section, cards_block])
    return _CAP_PANEL_OPEN, hdr_children, panel_body


# ─── Shared rendering helper ───────────────────────────────────────────────────
def _build_unest_panel(active_f: str, items: list, flt_data: dict | None, color: str):
    _UNA = ("Unassigned", "Not Specified", "")
    if active_f == "all":
        filtered, label = items, "All Unestimated Items"
    elif active_f == "p1":
        filtered, label = [s for s in items if s["pri"] == "P1"], "P1 Items"
    elif active_f == "issues":
        filtered, label = [s for s in items if s["type"] == "Issue"], "Issues"
    elif active_f == "enhanc":
        filtered, label = [s for s in items if s["type"] == "Enhancement"], "Enhancements"
    elif active_f == "devsp1":
        gap_devs = {s["dev"] for s in items if s["pri"] == "P1" and s["dev"] not in _UNA}
        filtered = [s for s in items if s["pri"] == "P1" and s["dev"] in gap_devs]
        label    = "Devs with P1 Gap"
    else:
        filtered, label = items, "Items"

    _fd   = flt_data or {"srt": "month", "dev": "all"}
    _srt  = _fd.get("srt", "month")
    _ddev = _fd.get("dev", "all")

    if _ddev != "all":
        filtered = [s for s in filtered if s.get("dev") == _ddev]

    _mk_o = {"M0": 0, "M1": 1, "M2": 2}
    if _srt == "pri":
        filtered = sorted(filtered, key=lambda s: (s["pri"], s["dev"], s["title"]))
    elif _srt == "rd":
        filtered = sorted(filtered, key=lambda s: (s.get("release_date") or "zzz", s["pri"], s["id"]))
    else:
        filtered = sorted(filtered, key=lambda s: (
            _mk_o.get(s.get("month") or "", 99),
            "" if (s.get("month") or "") in _mk_o else (s.get("month") or ""),
            s["pri"], s["dev"], s["title"],
        ))
    count = len(filtered)

    td_s = {"fontSize": "12px", "color": TX, "padding": "10px 14px",
            "borderBottom": f"1px solid {BD}", "verticalAlign": "middle"}
    th_s = {"fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
            "letterSpacing": "0.5px", "color": MT, "padding": "10px 14px",
            "borderBottom": f"1px solid {BD}", "textAlign": "left"}

    rows = []
    for s in filtered:
        est_lbl, est_c = ("Partial", A) if s["est_status"] == "partial" else ("Missing", R)
        task_note = f"  {s['task_count']}t, {s['task_missing']} missing" \
                    if s.get("task_count", 0) > 0 else ""
        rd = s.get("release_date") or ""
        rows.append(html.Tr([
            html.Td(html.A(f"#{s['id']}", href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                           style={"color": P, "fontWeight": "700", "textDecoration": "none",
                                  "fontSize": "12px"}),
                    style={**td_s, "width": "72px"}),
            html.Td([
                html.A(s["title"], href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
                       style={"color": TX, "textDecoration": "none", "fontSize": "12px",
                              "fontWeight": "500", "lineHeight": "1.4"}),
                html.Div(html.Span(rd, style={
                    "fontSize": "10px", "color": "rgb(6,182,212)",
                    "background": "rgba(6,182,212,0.10)",
                    "border": "1px solid rgba(6,182,212,0.25)",
                    "borderRadius": "3px", "padding": "1px 5px",
                }), style={"marginTop": "4px"}) if rd else None,
            ], style=td_s),
            html.Td(s["dev"] or "—", style={**td_s, "color": MT, "fontSize": "11px",
                                             "whiteSpace": "nowrap"}),
            html.Td(html.Span(s["pri"], style={
                        "background": f"{_pri_clr(s['pri'])}22", "color": _pri_clr(s["pri"]),
                        "border": f"1px solid {_pri_clr(s['pri'])}55",
                        "borderRadius": "4px", "padding": "2px 8px",
                        "fontSize": "11px", "fontWeight": "700",
                    }), style={**td_s, "textAlign": "center", "width": "54px"}),
            html.Td(s.get("month") or "—",
                    style={**td_s, "color": MT, "textAlign": "center",
                           "width": "54px", "fontSize": "11px"}),
            html.Td([
                html.Span(est_lbl, style={
                    "background": f"{est_c}22", "color": est_c,
                    "border": f"1px solid {est_c}55", "borderRadius": "4px",
                    "padding": "2px 8px", "fontSize": "11px", "fontWeight": "600",
                }),
                html.Span(task_note, style={"color": MT, "fontSize": "10px",
                                             "marginLeft": "6px"}),
            ], style={**td_s, "whiteSpace": "nowrap"}),
        ], style={"background": CD}))

    return html.Div([
        html.Div([
            html.Span(label, style={"fontWeight": "700", "color": color, "fontSize": "14px"}),
            html.Span(f"  ·  {count} items", style={"color": MT, "fontSize": "12px"}),
            html.Span("  ↗ opens in ADO",
                      style={"color": MT, "fontSize": "10px", "marginLeft": "8px"}),
        ], style={"marginBottom": "10px"}),
        html.Div(
            html.Table([
                html.Thead(html.Tr([
                    html.Th("ID",          style={**th_s, "width": "72px"}),
                    html.Th("Title",       style=th_s),
                    html.Th("Developer",   style={**th_s, "width": "150px"}),
                    html.Th("Pri",         style={**th_s, "width": "54px", "textAlign": "center"}),
                    html.Th("Month",       style={**th_s, "width": "54px", "textAlign": "center"}),
                    html.Th("Est. Status", style=th_s),
                ])),
                html.Tbody(rows),
            ], style={"width": "100%", "borderCollapse": "collapse"}),
            style={"background": CD, "borderRadius": "12px",
                   "border": f"1px solid {color}44",
                   "overflow": "auto", "maxHeight": "400px"},
        ),
    ], style={"marginBottom": "20px"})


# ─── Unestimated KPI cards → inline table ─────────────────────────────────────
_UNEST_UNA = ("Unassigned", "Not Specified", "")
_CTRL_SHOW  = {"display": "flex", "gap": "10px", "alignItems": "flex-end", "marginBottom": "10px"}
_CTRL_HIDE  = {"display": "none"}

@callback(
    Output("unest-item-panel", "children"),
    Output({"type": "unest-kcard", "filter": ALL}, "style"),
    Output("unest-active-kcard", "data"),
    Output("unest-ctrl-bar", "style"),
    Output("unest-dev-ctrl", "options"),
    Output("unest-dev-ctrl", "value"),
    Input({"type": "unest-kcard", "filter": ALL}, "n_clicks"),
    State("plan-unest-store", "data"),
    State({"type": "unest-kcard", "filter": ALL}, "id"),
    State("unest-active-kcard", "data"),
    State("unest-srt-ctrl", "value"),
    prevent_initial_call=True,
)
def _unest_card_click(clicks, items, card_ids, currently_active, srt_val):
    _nu6 = (no_update,) * 6
    trigger = ctx.triggered_id
    if not trigger or not isinstance(trigger, dict) or trigger.get("type") != "unest-kcard":
        return _nu6
    if not items:
        return _nu6

    items    = [s for s in items if s["est_status"] in ("unestimated", "partial")]
    active_f = trigger["filter"]

    # Toggle: clicking the already-active card collapses the table
    if active_f == currently_active:
        blank_styles = [_kcard_style(_UNEST_CARD_COLORS[cid["filter"]], False) for cid in card_ids]
        return html.Div(), blank_styles, None, _CTRL_HIDE, no_update, "all"

    flt_data = {"srt": srt_val or "month", "dev": "all"}
    color       = _UNEST_CARD_COLORS.get(active_f, R)
    panel       = _build_unest_panel(active_f, items, flt_data, color)
    card_styles = [_kcard_style(_UNEST_CARD_COLORS[cid["filter"]], cid["filter"] == active_f)
                   for cid in card_ids]

    # Compute dev options for the new active filter
    if active_f == "all":
        src = items
    elif active_f == "p1":
        src = [s for s in items if s["pri"] == "P1"]
    elif active_f == "issues":
        src = [s for s in items if s["type"] == "Issue"]
    elif active_f == "enhanc":
        src = [s for s in items if s["type"] == "Enhancement"]
    elif active_f == "devsp1":
        gap = {s["dev"] for s in items if s["pri"] == "P1" and s["dev"] not in _UNEST_UNA}
        src = [s for s in items if s["pri"] == "P1" and s["dev"] in gap]
    else:
        src = items
    devs = sorted({s["dev"] for s in src if s.get("dev") and s["dev"] not in _UNEST_UNA})
    dev_opts = [{"label": "All Devs", "value": "all"}] + [{"label": d, "value": d} for d in devs]

    return panel, card_styles, active_f, _CTRL_SHOW, dev_opts, "all"


# ─── Unestimated panel filter / sort ─────────────────────────────────────────
@callback(
    Output("unest-item-panel", "children", allow_duplicate=True),
    Input("unest-srt-ctrl", "value"),
    Input("unest-dev-ctrl", "value"),
    State("unest-active-kcard", "data"),
    State("plan-unest-store", "data"),
    prevent_initial_call=True,
)
def _unest_update_flt(srt_val, dev_val, active_card, items):
    if not active_card:
        raise PreventUpdate
    flt = {"srt": srt_val or "month", "dev": dev_val or "all"}
    all_items = [s for s in (items or []) if s["est_status"] in ("unestimated", "partial")]
    color     = _UNEST_CARD_COLORS.get(active_card, R)
    return _build_unest_panel(active_card, all_items, flt, color)


# ─── Unestimated matrix cell → side panel ──────────────────────────────────────

# Toggle: matrix cell click / close / backdrop → store {dev, month} or None
@callback(
    Output("unest-panel-filter", "data"),
    Input({"type": "unest-matrix-cell", "dev": ALL, "month": ALL, "est_type": ALL}, "n_clicks"),
    Input("unest-panel-close", "n_clicks"),
    Input("unest-backdrop",    "n_clicks"),
    prevent_initial_call=True,
)
def _unest_matrix_toggle(cell_clicks, close_click, backdrop_click):
    tid = ctx.triggered_id
    if tid in ("unest-panel-close", "unest-backdrop"):
        return None
    if isinstance(tid, dict) and tid.get("type") == "unest-matrix-cell":
        return {"dev": tid["dev"], "month": tid["month"], "est_type": tid.get("est_type", "u")}
    return no_update


def _sp_item_card(s: dict) -> html.A:
    if s["est_status"] in ("estimated", "estimated_via_tasks"):
        est_lbl, est_c = "Estimated", G
    elif s["est_status"] == "partial":
        est_lbl, est_c = "Partial", A
    else:
        est_lbl, est_c = "Missing", R
    task_note = ""
    if s.get("task_count", 0) > 0:
        miss = s["task_missing"]
        task_note = f"{s['task_count']} tasks" + (f", {miss} missing" if miss else "")
    card_rd = s.get("release_date") or ""
    return html.A(
        href=f"{ADO_BASE_URL}{s['id']}", target="_blank",
        style={"textDecoration": "none", "display": "block", "marginBottom": "8px"},
        children=html.Div([
            html.Div([
                html.Span(f"#{s['id']}",
                          style={"color": P, "fontWeight": "700",
                                 "fontSize": "11px", "marginRight": "8px"}),
                html.Span(s["pri"], style={
                    "background": f"{_pri_clr(s['pri'])}22", "color": _pri_clr(s["pri"]),
                    "border": f"1px solid {_pri_clr(s['pri'])}44",
                    "borderRadius": "4px", "padding": "1px 6px",
                    "fontSize": "10px", "fontWeight": "700", "marginRight": "6px",
                }),
                html.Span(est_lbl, style={
                    "background": f"{est_c}18", "color": est_c,
                    "border": f"1px solid {est_c}44",
                    "borderRadius": "4px", "padding": "1px 6px",
                    "fontSize": "10px", "fontWeight": "600",
                }),
                html.Span(card_rd, style={
                    "fontSize": "10px", "color": "rgb(6,182,212)",
                    "background": "rgba(6,182,212,0.10)",
                    "border": "1px solid rgba(6,182,212,0.25)",
                    "borderRadius": "4px", "padding": "1px 6px",
                }) if card_rd else None,
            ], style={"marginBottom": "6px", "display": "flex",
                      "alignItems": "center", "flexWrap": "wrap", "gap": "4px"}),
            html.Div(s["title"], style={
                "color": TX, "fontSize": "13px", "fontWeight": "600",
                "lineHeight": "1.4", "marginBottom": "5px",
            }),
            html.Div(html.Span(task_note, style={"color": MT, "fontSize": "10px"})),
        ], style={
            "background": CD, "border": f"1px solid {BD}",
            "borderLeft": f"3px solid {_pri_clr(s['pri'])}",
            "borderRadius": "8px", "padding": "12px 14px", "transition": "opacity .15s",
        })
    )


def _sp_section_header(label: str, count: int) -> html.Div:
    return html.Div([
        html.Span(label, style={"fontSize": "10px", "fontWeight": "700",
                                "color": MT, "textTransform": "uppercase",
                                "letterSpacing": "0.8px"}),
        html.Span(f"  {count}", style={"fontSize": "10px", "color": MT, "fontWeight": "400"}),
    ], style={"borderBottom": f"1px solid {BD}",
              "paddingBottom": "5px", "marginBottom": "8px", "marginTop": "14px"})


_BUG_TYPE_LABELS = {"Bug": "Bug", "Bug_UI": "Bug UI", "Bug_Text": "Bug Text"}

def _build_sp_body(filtered: list, est_type: str,
                   srt_val: str, type_val: str) -> html.Div:
    if type_val != "all":
        filtered = [s for s in filtered if s.get("raw_type", s["type"]) == type_val]

    if srt_val == "rd":
        filtered = sorted(filtered, key=lambda s: (s.get("release_date") or "zzz", s["pri"]))
    elif srt_val == "title":
        filtered = sorted(filtered, key=lambda s: s["title"])
    else:
        filtered = sorted(filtered, key=lambda s: (s["pri"], s["title"]))

    _est_label = "Estimated" if est_type == "e" else "Unestimated"
    if not filtered:
        return html.Div(f"No {_est_label.lower()} items for this cell.",
                        style={"color": MT, "fontSize": "13px", "padding": "20px 0"})

    # Group by raw_type so Bug/Bug_UI/Bug_Text appear as separate sections
    seen_types, groups = [], {}
    for s in filtered:
        t = s.get("raw_type", s["type"])
        if t not in groups:
            groups[t] = []
            seen_types.append(t)
        groups[t].append(s)

    body_items = [
        html.Div("↗ Click any item to open in ADO",
                 style={"color": MT, "fontSize": "10px",
                        "marginBottom": "8px", "textAlign": "right"}),
    ]
    for t in seen_types:
        label = _BUG_TYPE_LABELS.get(t, t)
        group = groups[t]
        body_items.append(_sp_section_header(label, len(group)))
        body_items.extend(_sp_item_card(s) for s in group)
    return html.Div(body_items)


# Render: store → slide panel open/closed with item cards
@callback(
    Output("unest-side-panel",    "style"),
    Output("unest-backdrop",      "style"),
    Output("unest-panel-title",   "children"),
    Output("unest-panel-body",    "children"),
    Output("unest-sp-ctrl-bar",   "style"),
    Input("unest-panel-filter",   "data"),
    State("plan-unest-store",     "data"),
    State("unest-sp-srt-ctrl",    "value"),
    State("unest-sp-type-ctrl",   "value"),
    prevent_initial_call=True,
)
def _unest_matrix_panel(cell_sel, items, srt_val, type_val):
    _sp_hide = {"display": "none", "gap": "10px", "alignItems": "flex-end",
                "padding": "10px 20px", "borderBottom": f"1px solid {BD}", "flexShrink": "0"}
    _sp_show = {**_sp_hide, "display": "flex"}

    if not cell_sel or not items:
        return _PANEL_CLOSED, _BACKDROP_CLOSED, "", [], _sp_hide

    dev      = cell_sel["dev"]
    month    = cell_sel["month"]
    est_type = cell_sel.get("est_type", "u")

    if est_type == "e":
        base = [s for s in items if s["dev"] == dev and s["month"] == month
                and s["est_status"] in ("estimated", "estimated_via_tasks")]
    else:
        base = [s for s in items if s["dev"] == dev and s["month"] == month
                and s["est_status"] in ("unestimated", "partial")]

    _est_label = "Estimated" if est_type == "e" else "Unestimated"
    title_el = [
        html.Span(dev.split()[0], style={"color": TX}),
        html.Span(f"  ·  {month}", style={"color": P, "fontWeight": "700"}),
        html.Span(f"  ·  {_est_label}",
                  style={"color": G if est_type == "e" else R,
                         "fontSize": "11px", "fontWeight": "700", "marginLeft": "4px"}),
        html.Span(f"  ·  {len(base)} item{'s' if len(base) != 1 else ''}",
                  style={"color": MT, "fontSize": "13px", "fontWeight": "400"}),
    ]

    body = _build_sp_body(base, est_type, srt_val or "pri", type_val or "all")
    return _PANEL_OPEN, _BACKDROP_OPEN, title_el, body, _sp_show


# ─── Side panel sort / type filter ───────────────────────────────────────────
@callback(
    Output("unest-panel-body", "children", allow_duplicate=True),
    Input("unest-sp-srt-ctrl",  "value"),
    Input("unest-sp-type-ctrl", "value"),
    State("unest-panel-filter", "data"),
    State("plan-unest-store",   "data"),
    prevent_initial_call=True,
)
def _unest_sp_update_flt(srt_val, type_val, cell_sel, items):
    if not cell_sel or not items:
        raise PreventUpdate
    dev      = cell_sel["dev"]
    month    = cell_sel["month"]
    est_type = cell_sel.get("est_type", "u")
    if est_type == "e":
        base = [s for s in items if s["dev"] == dev and s["month"] == month
                and s["est_status"] in ("estimated", "estimated_via_tasks")]
    else:
        base = [s for s in items if s["dev"] == dev and s["month"] == month
                and s["est_status"] in ("unestimated", "partial")]
    return _build_sp_body(base, est_type, srt_val or "pri", type_val or "all")


# ── 11. Per-ticket sign-off log ───────────────────────────────────────────────
@callback(
    Output("ticket-log-sid", "data"),
    Input({"type": "ticket-log-btn", "sid": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _ticket_log_select(n_clicks):
    # Guard: skip if no button has actually been clicked yet (all n_clicks == 0)
    if not any(n_clicks):
        return no_update
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "ticket-log-btn":
        return triggered["sid"]
    return no_update


@callback(
    Output("tlog-modal",   "is_open"),
    Output("tlog-header",  "children"),
    Output("tlog-body",    "children"),
    Output("tlog-footer",  "children"),
    Input("ticket-log-sid",     "data"),
    State("plan-stories-store", "data"),
    prevent_initial_call=True,
)
def _ticket_log_render(sid, stories_data):
    if not sid:
        return False, "", [], ""

    story    = next((s for s in (stories_data or []) if s["id"] == sid), None)
    title    = story["title"] if story else f"Item #{sid}"
    ba_txt   = story.get("ba", "") if story else ""
    dev_txt  = story.get("dev", "") if story else ""
    mon_txt  = story.get("month", "") if story else ""

    header_el = html.Div([
        html.Span("🕐 Sign-Off History  ", style={"color": MT, "fontSize": "12px"}),
        html.A(title, href=f"{ADO_BASE_URL}{sid}", target="_blank",
               style={"color": TX, "fontWeight": "700", "fontSize": "14px",
                      "textDecoration": "none"}),
        html.Div(
            f"BA: {ba_txt}  ·  Dev: {dev_txt}  ·  {mon_txt}",
            style={"color": MT, "fontSize": "11px", "marginTop": "4px"},
        ) if (ba_txt or dev_txt) else None,
    ])

    try:
        from db.planning import get_log as _get_log
        entries = _get_log(work_item_id=int(sid), limit=100)
    except Exception:
        entries = []

    if not entries:
        body = html.Div(
            "No sign-off actions recorded for this story yet.",
            style={"color": MT, "fontSize": "13px", "padding": "20px"},
        )
    else:
        cards = []
        for entry in entries:   # newest-first from DB
            is_conf  = entry.get("action") == "Confirmed"
            gate_lbl = _GATE_LABEL.get(entry.get("gate", ""), entry.get("gate", ""))
            pat      = entry.get("performed_at")
            if hasattr(pat, "strftime"):
                time_str = pat.strftime("%Y-%m-%d %H:%M:%S")
            else:
                time_str = str(pat)[:19] if pat else "—"

            cards.append(html.Div([
                html.Div([
                    html.Span(time_str,
                              style={"color": MT, "fontSize": "11px",
                                     "fontFamily": "monospace", "marginRight": "14px",
                                     "flexShrink": "0"}),
                    html.Span(gate_lbl,
                              style={"color": B, "fontSize": "12px",
                                     "fontWeight": "700", "marginRight": "10px"}),
                    html.Span(("✓ " if is_conf else "✗ ") + entry.get("action", ""),
                              style={"color": G if is_conf else R,
                                     "fontSize": "12px", "fontWeight": "700",
                                     "marginRight": "10px"}),
                    html.Span(
                        entry.get("performed_by", ""),
                        style={"color": MT, "fontSize": "11px"},
                    ),
                ], style={"display": "flex", "alignItems": "center",
                           "flexWrap": "wrap", "marginBottom": "4px"}),
                html.Div(
                    entry.get("new_status", ""),
                    style={"color": G if is_conf else R,
                           "fontSize": "11px", "fontWeight": "600"},
                ),
            ], style={
                "background":   G_DIM if is_conf else R_DIM,
                "border":       f"1px solid {G_BRD}" if is_conf else f"1px solid {R_BRD}",
                "borderLeft":   f"3px solid {G}" if is_conf else f"3px solid {R}",
                "borderRadius": "8px", "padding": "10px 14px", "marginBottom": "8px",
            }))
        body = html.Div(cards)

    confirmed = sum(1 for e in entries if e.get("action") == "Confirmed")
    cleared   = sum(1 for e in entries if e.get("action") == "Cleared")
    footer    = html.Div([
        html.Span(f"✓ {confirmed} confirmed",
                  style={"color": G, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"✗ {cleared} cleared",
                  style={"color": R, "fontSize": "12px", "fontWeight": "700",
                         "marginRight": "16px"}),
        html.Span(f"{len(entries)} total actions",
                  style={"color": MT, "fontSize": "12px"}),
    ]) if entries else ""

    return True, header_el, body, footer


# ═══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE TRACKER HELPERS + CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

def _derive_planning_gates(state: dict) -> dict:
    """BA sign-off gates are manual-only; no auto-derive from lifecycle steps."""
    return {f: False for f in _GATE_FIELDS}

def _tracker_gate_progress(gate: dict, state: dict) -> tuple[int, int]:
    """(done_steps, total_steps) for a gate."""
    total = sum(len(p["steps"]) for p in gate["phases"])
    done  = sum(1 for p in gate["phases"] for s in p["steps"] if state.get(s["key"], False))
    return done, total


def _tracker_phase_progress(phase: dict, state: dict) -> tuple[int, int]:
    """(done_steps, total_steps) for a phase."""
    total = len(phase["steps"])
    done  = sum(1 for s in phase["steps"] if state.get(s["key"], False))
    return done, total


def _build_tracker_summary(state: dict) -> html.Div:
    """Compact 6-gate progress dots row for modal header."""
    dots = []
    for gate in LIFECYCLE:
        done, total = _tracker_gate_progress(gate, state)
        gate_done   = done == total and total > 0
        pct         = round(done / total * 100) if total else 0
        clr         = gate["color"]
        dots.append(html.Div([
            html.Div(style={
                "width": "10px", "height": "10px", "borderRadius": "50%",
                "background": clr if gate_done else "transparent",
                "border": f"2px solid {clr}",
                "flexShrink": "0",
            }),
            html.Div(gate["label"],
                     style={"fontSize": "9px", "color": clr if gate_done else MT,
                             "fontWeight": "700" if gate_done else "400",
                             "marginLeft": "4px", "whiteSpace": "nowrap"}),
            html.Div(f"{pct}%",
                     style={"fontSize": "9px", "color": MT, "marginLeft": "4px"}),
        ], style={"display": "flex", "alignItems": "center", "marginRight": "16px"}))

    total_done = sum(1 for v in state.values() if v)
    return html.Div([
        html.Div(dots, style={"display": "flex", "flexWrap": "wrap", "marginBottom": "6px"}),
        html.Div(f"{total_done} / {TOTAL_STEPS} steps complete",
                 style={"fontSize": "11px", "color": MT}),
    ])


def _build_tracker_body(state: dict, gate_filter: dict | None = None) -> list:
    """
    Render lifecycle gates with phases and step checkboxes.
    gate_filter: {"gates": [gate_keys], "phases": [phase_keys] or None}
                 None = show all gates and phases.
    """
    gate_keys  = gate_filter["gates"]  if gate_filter else None
    phase_keys = gate_filter["phases"] if gate_filter else None

    gates_html = []
    for gate in LIFECYCLE:
        if gate_keys and gate["key"] not in gate_keys:
            continue
        g_done, g_total   = _tracker_gate_progress(gate, state)
        gate_complete      = g_done == g_total and g_total > 0
        clr                = gate["color"]
        gate_pct           = round(g_done / g_total * 100) if g_total else 0

        # Phase sections
        phases_html = []
        for phase in gate["phases"]:
            if phase_keys and phase["key"] not in phase_keys:
                continue
            p_done, p_total = _tracker_phase_progress(phase, state)
            phase_complete  = p_done == p_total and p_total > 0
            p_clr           = clr if phase_complete else MT

            step_btns = []
            for step in phase["steps"]:
                checked = state.get(step["key"], False)
                step_btns.append(html.Button([
                    html.Span("✓  " if checked else "○  ",
                              style={"color": clr if checked else "rgba(255,255,255,0.25)",
                                     "fontWeight": "700", "fontSize": "13px",
                                     "flexShrink": "0"}),
                    html.Span(step["label"],
                              style={"fontSize": "12px",
                                     "color": TX if checked else MT,
                                     "textDecoration": "line-through" if False else "none",
                                     "lineHeight": "1.4"}),
                ], id={"type": "tracker-step-btn", "step": step["key"]}, n_clicks=0,
                style={
                    "background":   _dim(clr) if checked else "transparent",
                    "border":       f"1px solid {_brd(clr)}" if checked else f"1px solid {BD}",
                    "borderLeft":   f"3px solid {clr}" if checked else f"3px solid transparent",
                    "borderRadius": "6px", "padding": "6px 12px",
                    "cursor": "pointer", "display": "flex", "alignItems": "flex-start",
                    "width": "100%", "textAlign": "left", "marginBottom": "4px",
                    "transition": "all .12s",
                }))

            phases_html.append(html.Div([
                html.Div([
                    html.Span("✓ " if phase_complete else f"{p_done}/{p_total}  ",
                              style={"color": p_clr, "fontSize": "11px",
                                     "fontWeight": "700", "marginRight": "6px"}),
                    html.Span(phase["label"],
                              style={"color": TX if phase_complete else TX,
                                     "fontSize": "12px", "fontWeight": "600"}),
                ], style={"display": "flex", "alignItems": "center",
                           "marginBottom": "8px", "paddingBottom": "6px",
                           "borderBottom": f"1px solid {BD}"}),
                html.Div(step_btns, style={"display": "flex", "flexDirection": "column",
                                            "gap": "2px"}),
            ], style={
                "background": CD, "borderRadius": "8px", "padding": "12px 14px",
                "marginBottom": "8px",
                "border": f"1px solid {clr}44" if phase_complete else f"1px solid {BD}",
            }))

        # Progress bar
        bar_filled = html.Div(style={
            "width": f"{gate_pct}%", "height": "4px",
            "background": clr, "borderRadius": "2px",
            "transition": "width 0.3s ease",
        })
        bar = html.Div(
            html.Div(bar_filled, style={"width": "100%", "height": "4px",
                                        "background": "rgba(255,255,255,0.08)",
                                        "borderRadius": "2px"}),
            style={"flex": "1", "margin": "0 12px"},
        )

        gate_css = "tracker-gate-card"
        if gate_complete:
            gate_css += " gate-complete"

        gates_html.append(html.Div([
            # Gate header
            html.Div([
                html.Div(style={
                    "width": "12px", "height": "12px", "borderRadius": "50%",
                    "background": clr if gate_complete else "transparent",
                    "border": f"2px solid {clr}", "flexShrink": "0",
                }),
                html.Div([
                    html.Span(gate["label"],
                              style={"color": clr, "fontSize": "13px", "fontWeight": "800",
                                     "marginRight": "8px"}),
                    html.Span(gate["desc"],
                              style={"color": MT, "fontSize": "11px"}),
                ], style={"flex": "1", "marginLeft": "10px"}),
                bar,
                html.Div(f"{g_done}/{g_total}",
                         style={"color": clr if gate_complete else MT,
                                "fontSize": "12px", "fontWeight": "700",
                                "flexShrink": "0"}),
            ], style={"display": "flex", "alignItems": "center",
                       "marginBottom": "12px"}),
            # Phases
            *phases_html,
        ], className=gate_css, style={
            "background": C2, "borderRadius": "12px", "padding": "16px 18px",
            "marginBottom": "12px",
            "border": (f"1px solid {gate['color']}55" if gate_complete
                       else f"1px solid {BD}"),
            "boxShadow": f"0 0 28px {gate['color']}18" if gate_complete else "none",
        }))

    return gates_html


# ── 12. Lifecycle tracker — select ────────────────────────────────────────────
# Only 📋 icon button opens tracker; gate pills now toggle directly (callback 3)
@callback(
    Output("tracker-sid",        "data"),
    Output("tracker-gate-focus", "data"),
    Input({"type": "tracker-btn", "sid": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _tracker_select(tracker_clicks):
    if not any(tracker_clicks or []):
        return no_update, no_update
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "tracker-btn":
        return triggered["sid"], None
    return no_update, no_update


# ── 13. Lifecycle tracker — open / step toggle ────────────────────────────────
@callback(
    Output("tracker-modal",   "is_open"),
    Output("tracker-header",  "children"),
    Output("tracker-data",    "data"),
    Output("gate-store",      "data"),
    Input("tracker-sid",      "data"),
    Input({"type": "tracker-step-btn", "step": ALL}, "n_clicks"),
    State("tracker-data",       "data"),
    State("plan-stories-store", "data"),
    State("gate-store",         "data"),
    prevent_initial_call=True,
)
def _tracker_main(sid, step_clicks, cur_data, stories_data, gate_store):
    triggered = ctx.triggered_id

    def _header(sid_, title_, state_, story_):
        done = sum(1 for v in state_.values() if v)
        gates_done = sum(
            1 for g in LIFECYCLE
            if all(state_.get(s["key"], False)
                   for p in g["phases"] for s in p["steps"])
        )
        pri = story_.get("pri", "") if story_ else ""
        return html.Div([
            html.Div([
                html.A(title_, href=f"{ADO_BASE_URL}{sid_}", target="_blank",
                       style={"color": TX, "fontWeight": "800", "fontSize": "16px",
                              "textDecoration": "none", "marginRight": "12px"}),
                html.Span(f"  {pri}",
                          style={"color": _pri_clr(pri), "fontSize": "11px",
                                 "fontWeight": "700"}) if pri else None,
                html.Span(
                    f"  {gates_done}/6 gates  ·  {done}/{TOTAL_STEPS} steps",
                    style={"color": MT, "fontSize": "12px", "marginLeft": "8px"},
                ),
            ], style={"display": "flex", "alignItems": "center",
                       "marginBottom": "10px"}),
            _build_tracker_summary(state_),
        ])

    # ── Modal open triggered by a new sid ────────────────────────────────────
    if triggered == "tracker-sid":
        if not sid:
            return False, "", {}, no_update
        try:
            from db.planning import load_tracker_state as _lts
            state = _lts(int(sid))
        except Exception:
            state = {}
        story = next((s for s in (stories_data or []) if s["id"] == sid), None)
        title = story["title"] if story else f"Item #{sid}"
        return True, _header(sid, title, state, story), {"sid": sid, "state": state}, no_update

    # ── Step button click ─────────────────────────────────────────────────────
    if isinstance(triggered, dict) and triggered.get("type") == "tracker-step-btn":
        data  = dict(cur_data or {})
        state = dict(data.get("state", {}))
        sk    = triggered["step"]
        new_v = not state.get(sk, False)
        state[sk] = new_v

        gate_key, phase_key = STEP_INDEX.get(sk, ("", ""))
        step_lbl            = STEP_LABELS.get(sk, sk)

        try:
            from flask_login import current_user as _cu
            performed_by = _cu.display_name if _cu and _cu.is_authenticated else "system"
        except Exception:
            performed_by = "system"
        try:
            from db.planning import toggle_tracker_step as _tts
            _tts(int(data["sid"]), sk, phase_key, gate_key, new_v, performed_by, step_lbl)
        except Exception as _e:
            import logging as _log
            _log.getLogger(__name__).error("toggle_tracker_step failed sid=%s step=%s: %s",
                                           data.get("sid"), sk, _e)

        # BA sign-off gates are now manual-only; tracker no longer auto-syncs them.
        new_gate_store = no_update
        new_data = {"sid": data["sid"], "state": state}
        story    = next((s for s in (stories_data or []) if s["id"] == data["sid"]), None)
        title    = story["title"] if story else f"Item #{data['sid']}"
        return no_update, _header(data["sid"], title, state, story), new_data, new_gate_store

    return no_update, no_update, no_update, no_update


# ── 14. Lifecycle tracker — render body from state ───────────────────────────
@callback(
    Output("tracker-body",       "children"),
    Input("tracker-data",        "data"),
    State("tracker-gate-focus",  "data"),
    prevent_initial_call=True,
)
def _tracker_render(data, gate_filter):
    if not data:
        return []
    return _build_tracker_body(data.get("state", {}), gate_filter)


# ── 15. Reset tracker-sid to None on modal close ──────────────────────────────
# Without this, clicking 📋 on the same story twice sends the same sid value
# so tracker-sid doesn't change → _tracker_open_or_step never re-fires →
# state is not reloaded from DB.
@callback(
    Output("tracker-sid", "data", allow_duplicate=True),
    Input("tracker-modal", "is_open"),
    prevent_initial_call=True,
)
def _reset_tracker_sid_on_close(is_open):
    if not is_open:
        return None
    return no_update


# ── 16a. Gantt window label (updates when view dropdown changes) ───────────────
@callback(
    Output("gantt-window-label", "children"),
    Input("gantt-view-select",   "value"),
    prevent_initial_call=True,
)
def _gantt_label(view):
    _, _, label = _gantt_window(view or "0-12")
    return f" · {label}"


# ── 16b. Unified Gantt toggle — external JS (assets/gantt_toggle.js) ──────────
clientside_callback(
    ClientsideFunction(namespace="gantt", function_name="toggle"),
    Output("gantt-expanded", "data"),
    Input({"type": "gantt-toggle", "index": ALL}, "n_clicks"),
    State("gantt-expanded", "data"),
    prevent_initial_call=True,
)


# ── 16c. Gantt chart render ────────────────────────────────────────────────────
@callback(
    Output("gantt-chart", "children"),
    Input("gantt-view-select",  "value"),
    Input("plan-main-tab",      "data"),
    Input("gantt-type-filter",  "value"),
    Input("gantt-prio-filter",  "value"),
    State("gantt-expanded",     "data"),
    prevent_initial_call=True,
)
def _gantt_render(view, active_tab, type_filter, prio_filter, expanded):
    if active_tab != "gantt":
        return no_update
    ws, we, _ = _gantt_window(view or "0-12")
    return _build_gantt_html(
        ws, we,
        set((expanded or {}).get("s", [])),
        set((expanded or {}).get("t", [])),
        dev_filter=None,
        type_filter=type_filter or "all",
        prio_filter=prio_filter or None,
        year_filter=None,
        cust_filter="all",   # Customer/Internal never filters the Gantt
    )
