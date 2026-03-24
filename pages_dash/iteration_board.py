"""Iteration Board — sprint progress, burndown, workload, velocity, and scope intelligence"""

import base64
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data
from config.settings import ADO_BASE_URL

dash.register_page(__name__, path="/iteration", name="Iteration Board")

# ── Constants ─────────────────────────────────────────────────────────────────
REJECTED_STATES = {"Not an issue", "Not Required"}
CLOSED_STATES   = {"Closed", "Resolved", "Userstory Update"}
ALL_DONE_STATES = CLOSED_STATES | REJECTED_STATES

STATE_MAP = {
    "New":              "🆕 New",
    "Active":           "🔵 Active",
    "Dev InProgress":   "🔵 Active",
    "Dev Review":       "🔵 Active",
    "Tester Assigned":  "🔵 Active",
    "Dev Complete":     "🟡 In Review",
    "Request Estimate": "🟡 In Review",
    "Clarification":    "🟡 In Review",
    "Estimated":        "🟡 In Review",
    "Watch List":       "⏸ On Hold",
    "On Hold":          "⏸ On Hold",
    "Rare Scenario":    "⏸ On Hold",
    "Reopened":         "🔴 Reopened",
    "Resolved":         "✅ Resolved",
    "Closed":           "✅ Closed",
    "Not an issue":     "❌ Rejected",
    "Not Required":     "❌ Rejected",
    "Userstory Update": "✅ Closed",
}

STATE_COLORS = {
    "🆕 New":       "#a0aec0",
    "🔵 Active":    "#5a8fd4",
    "🟡 In Review": "#ecc94b",
    "⏸ On Hold":   "#718096",
    "🔴 Reopened":  "#c06060",
    "✅ Resolved":  "#68d391",
    "✅ Closed":    "#3d9e6b",
    "❌ Rejected":  "#c05050",
}

ITERATION_DATES = {
    "Iteration 2025.01": ("2024-12-28", "2025-01-10"),
    "Iteration 2025.02": ("2025-01-11", "2025-01-24"),
    "Iteration 2025.03": ("2025-01-25", "2025-02-07"),
    "Iteration 2025.04": ("2025-02-08", "2025-02-21"),
    "Iteration 2025.05": ("2025-02-22", "2025-03-07"),
    "Iteration 2025.06": ("2025-03-08", "2025-03-21"),
    "Iteration 2025.07": ("2025-03-22", "2025-04-04"),
    "Iteration 2025.08": ("2025-04-05", "2025-04-18"),
    "Iteration 2025.09": ("2025-04-19", "2025-05-02"),
    "Iteration 2025.10": ("2025-05-03", "2025-05-16"),
    "Iteration 2025.11": ("2025-05-17", "2025-05-30"),
    "Iteration 2025.12": ("2025-05-31", "2025-06-13"),
    "Iteration 2025.13": ("2025-06-14", "2025-06-27"),
    "Iteration 2025.14": ("2025-06-28", "2025-07-11"),
    "Iteration 2025.15": ("2025-07-12", "2025-07-25"),
    "Iteration 2025.16": ("2025-07-26", "2025-08-08"),
    "Iteration 2025.17": ("2025-08-09", "2025-08-22"),
    "Iteration 2025.18": ("2025-08-23", "2025-08-31"),
    "Iteration 2025 09-September": ("2025-09-01", "2025-09-30"),
    "Iteration 2025 10-October":   ("2025-10-01", "2025-10-31"),
    "Iteration 2025 11-November":  ("2025-11-01", "2025-11-30"),
    "Iteration 2025 12-December":  ("2025-12-01", "2025-12-31"),
}

_TIPS = {
    "burndown_items": (
        "Sprint Burndown — Items",
        "Items remaining open each day. Dashed line = ideal pace. "
        "Red line above dashed = team is falling behind.",
    ),
    "burndown_hours": (
        "Sprint Burndown — Hours",
        "Remaining hours (original estimate − completed work) per day. "
        "More honest than item count when tasks vary in size.",
    ),
    "workload": (
        "Workload by Person",
        "Items assigned per person: green = closed, red = still open. "
        "Useful for spotting imbalanced loads across the team.",
    ),
    "hours": (
        "Remaining Hours by Person",
        "Hours of work remaining per person for this sprint. "
        "High bars with few days left = risk of spillover.",
    ),
    "state": (
        "Items by State",
        "Where all sprint items currently sit in the workflow. "
        "Large 'On Hold' bar = potential blockers to investigate.",
    ),
    "blockers": (
        "P1 / P2 Blockers",
        "Critical and high-priority items still open. "
        "Each P1 is a direct sprint risk.",
    ),
    "velocity": (
        "Velocity Trend",
        "Items closed per sprint over the last 8 sprints. "
        "Rising trend = team is improving. Flat/falling = investigate.",
    ),
    "scope_creep": (
        "Mid-Sprint Scope Additions",
        "Items created AFTER this sprint's start date — added to scope mid-sprint. "
        "Frequent additions signal poor sprint planning or uncontrolled interruptions.",
    ),
    "carryover": (
        "Older Items in This Sprint",
        "Items currently assigned to this sprint but created BEFORE the sprint started. "
        "These are likely carryovers or items that sat unplanned for a while.",
    ),
    "tasks": (
        "Tasks in This Sprint",
        "Task-level breakdown of work backing the items in this sprint. "
        "Tasks are the most granular unit of work — useful for daily standups.",
    ),
}


# ── Iteration helpers ──────────────────────────────────────────────────────────
def _strip_path(x):
    if pd.notna(x) and str(x) not in ("Not Specified", ""):
        return str(x).split("\\")[-1]
    return x


def get_iteration_dates(name):
    if not name or (isinstance(name, float) and np.isnan(name)):
        return None, None
    if name in ITERATION_DATES:
        s, e = ITERATION_DATES[name]
        return pd.Timestamp(s), pd.Timestamp(e)
    s = str(name)
    if "Iteration " in s and "-" in s:
        try:
            parts = s.split(" ")
            year  = int(parts[1])
            if year >= 2026:
                month = int(parts[2].split("-")[0])
                start = pd.Timestamp(year=year, month=month, day=1)
                end   = start + pd.offsets.MonthEnd(1)
                return start, end
        except Exception:
            pass
    return None, None


def get_current_iteration(all_iters):
    today = pd.Timestamp.today().normalize()
    for it in all_iters:
        start, end = get_iteration_dates(it)
        if start is not None and end is not None and start <= today <= end:
            return it
    past = [(it, end) for it in all_iters
            if (lambda s, e: e is not None and e < today)(*get_iteration_dates(it))]
    if past:
        past.sort(key=lambda x: x[1], reverse=True)
        return past[0][0]
    return all_iters[0] if all_iters else None


# ── Layout helpers ─────────────────────────────────────────────────────────────
def _kpi(label, value, cls="", subtitle=None, md=3, ring_pct=None, sparkline_src=None):
    if ring_pct is not None:
        # CSS conic-gradient completion ring beside the value
        if ring_pct >= 80:
            ring_color = "#3d9e6b"
        elif ring_pct >= 50:
            ring_color = "#c97d3a"
        else:
            ring_color = "#c05050"
        ring = html.Div([
            html.Div(
                html.Div(f"{ring_pct:.0f}%", className="completion-ring-inner"),
                className="completion-ring",
                style={
                    "background": (
                        f"conic-gradient({ring_color} {ring_pct:.1f}%, "
                        f"rgba(255,255,255,0.07) {ring_pct:.1f}%)"
                    )
                },
            )
        ], style={"display": "flex", "alignItems": "center"})
        value_area = html.Div([ring], className="completion-ring-wrap")
        children = [
            html.Div(label, className="metric-label"),
            value_area,
        ]
    else:
        children = [
            html.Div(label, className="metric-label"),
            html.Div(value, className=f"metric-value {cls}"),
        ]
    if subtitle:
        children.append(html.Div(subtitle, className="kpi-subtitle"))
    if sparkline_src:
        children.append(html.Div(
            html.Img(src=sparkline_src, style={"width": "100%", "height": "28px", "display": "block"}),
            className="kpi-sparkline",
        ))
    return dbc.Col(html.Div(children, className="metric-card"), md=md)


def _info(tip_id):
    _, tip_text = _TIPS.get(tip_id, ("", ""))
    return html.Span(
        " ?",
        id=f"ib-tip-{tip_id}",
        style={"cursor": "pointer", "color": "#a0aec0", "fontSize": "11px",
               "fontWeight": "700", "marginLeft": "4px"},
    )


def _chart_card(title, tip_key, graph_id, insight_id=None):
    _, tip_text = _TIPS.get(tip_key, ("", ""))
    header = html.Div([
        html.Span(title, className="chart-title-text"),
        _info(tip_key),
        dbc.Tooltip(tip_text, target=f"ib-tip-{tip_key}", placement="right"),
    ], className="chart-section-header")
    body = [header]
    if insight_id:
        body.append(html.Div(id=insight_id, className="chart-insight"))
    body.append(dcc.Graph(id=graph_id, config={"responsive": True}))
    return html.Div(body, className="chart-card mb-4")


def _table_card(title, tip_key, body_id):
    _, tip_text = _TIPS.get(tip_key, ("", ""))
    return html.Div([
        html.Div([
            html.Span(title, style={"fontSize": "14px", "fontWeight": "700"}),
            _info(tip_key),
            dbc.Tooltip(tip_text, target=f"ib-tip-{tip_key}", placement="right"),
        ], className="chart-section-header"),
        html.Div(id=body_id),
    ], className="chart-card mb-4")


def _sparkline_svg(values, color="#5a8fd4", width=100, height=28):
    """Return a data:image/svg+xml base64 URI sparkline from numeric values."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    mn, mx = min(vals), max(vals)
    rng = mx - mn or 1
    pad = 3
    w, h = width - pad * 2, height - pad * 2
    pts = [
        (pad + i / (len(vals) - 1) * w, pad + (1 - (v - mn) / rng) * h)
        for i, v in enumerate(vals)
    ]
    path_d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    fill_d = path_d + f" L {pts[-1][0]:.1f} {height} L {pts[0][0]:.1f} {height} Z"
    hx = color.lstrip("#")
    r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    fill_rgba = f"rgba({r},{g},{b},0.18)"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<path d="{fill_d}" fill="{fill_rgba}" stroke="none"/>'
        f'<path d="{path_d}" stroke="{color}" stroke-width="1.5" fill="none" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64}"


# ── Table style constants (shared across all html.Table sections) ─────────────
_TH = {
    "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
    "letterSpacing": "0.5px", "color": "#8892a4",
    "padding": "8px 12px", "borderBottom": "1px solid rgba(255,255,255,0.08)",
    "textAlign": "left", "whiteSpace": "nowrap",
}
_TD = {
    "fontSize": "12px", "padding": "9px 12px",
    "borderBottom": "1px solid rgba(255,255,255,0.04)",
    "color": "#c8c8e0", "verticalAlign": "middle",
}


def _priority_pill(p):
    """Return an html.Span pill for a priority int."""
    try:
        p_int = int(p) if pd.notna(p) else 0
    except Exception:
        p_int = 0
    cls = {1: "pill pill-p1", 2: "pill pill-p2", 3: "pill pill-p3", 4: "pill pill-p4"}.get(p_int, "pill pill-p4")
    lbl = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}.get(p_int, f"P{p_int}")
    return html.Span(lbl, className=cls)


def _state_pill(s):
    """Return an html.Span pill for a state string."""
    state_map = {
        "🆕 New":       "pill pill-new",
        "🔵 Active":    "pill pill-active",
        "🟡 In Review": "pill pill-review",
        "⏸ On Hold":   "pill pill-hold",
        "🔴 Reopened":  "pill pill-reopened",
        "✅ Resolved":  "pill pill-closed",
        "✅ Closed":    "pill pill-closed",
        "❌ Rejected":  "pill pill-rejected",
    }
    raw = str(s) if pd.notna(s) else ""
    mapped = STATE_MAP.get(raw, raw)
    label = mapped.split(" ", 1)[-1] if " " in mapped else mapped
    cls = state_map.get(mapped, "pill pill-new")
    return html.Span(label, className=cls)


def _type_pill(t):
    """Return an html.Span pill for a work item type string."""
    t = str(t) if pd.notna(t) else ""
    t_norm = {"Bug_UI": "Bug", "Bug_Text": "Bug"}.get(t, t)
    cls = {
        "Bug": "pill pill-p1",
        "Enhancement": "pill pill-p2",
        "Task": "pill pill-active",
        "User Story": "pill pill-closed",
    }.get(t_norm, "pill")
    return html.Span(t_norm or "—", className=cls)


def _section_label(text):
    return html.Div(text, style={
        "fontSize": "11px", "fontWeight": "700", "textTransform": "uppercase",
        "letterSpacing": "0.8px", "color": "#a0aec0",
        "marginBottom": "12px", "marginTop": "4px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────
def layout():
    df = load_data()

    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_path)
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]

    iters = sorted(
        [i for i in df["iteration_path"].dropna().unique()
         if i not in ("Not Specified", "")],
        reverse=True,
    ) if "iteration_path" in df.columns else []

    teams = (["All"] + sorted(df["team"].dropna().unique().tolist())
             if "team" in df.columns else ["All"])
    employees = (["All"] + sorted(df["assigned_to"].dropna().unique().tolist())
                 if "assigned_to" in df.columns else ["All"])

    default_iter = get_current_iteration(iters) if iters else None

    _fb = {
        "background": "#1c1c27", "borderRadius": "10px", "padding": "14px 18px",
        "border": "1px solid rgba(255,255,255,0.07)",
        "marginBottom": "20px",
    }

    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([
                html.Div("Iteration / Sprint", className="filter-label"),
                dcc.Dropdown(
                    id="ib-iteration",
                    options=[{"label": i, "value": i} for i in iters],
                    value=default_iter, clearable=False,
                    style={"fontSize": "13px", "fontWeight": "600"},
                ),
            ], md=5),
            dbc.Col([
                html.Div("Team", className="filter-label"),
                dcc.Dropdown(id="ib-team",
                             options=[{"label": t, "value": t} for t in teams],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Employee", className="filter-label"),
                dcc.Dropdown(id="ib-employee",
                             options=[{"label": e, "value": e} for e in employees],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=4),
        ], className="g-2"),
    ], style=_fb)

    _tab_style = {
        "padding": "10px 24px", "fontWeight": "600", "fontSize": "13px",
        "color": "#718096", "borderTop": "none", "borderLeft": "none",
        "borderRight": "none", "borderBottom": "2px solid transparent",
        "background": "transparent",
    }
    _tab_selected = {**_tab_style, "color": "#e8e8f0", "borderBottom": "2px solid #8b7ee8"}

    sprint_tab = dcc.Tab(
        label="📡  Sprint View", value="sprint",
        style=_tab_style, selected_style=_tab_selected,
        children=html.Div([
            html.Div(id="ib-timeline-strip", className="mb-3"),
            html.Div(id="ib-health-banner",  className="mb-3"),

            _section_label("At a Glance"),
            html.Div(id="ib-kpi-row", className="mb-4"),
            html.Hr(className="section-divider"),

            _section_label("Burndown"),
            dbc.Row([
                dbc.Col(_chart_card("Items Remaining", "burndown_items",
                                    "ib-burndown-items", insight_id="ib-insight-burndown"), md=6),
                dbc.Col(_chart_card("Hours Remaining", "burndown_hours",
                                    "ib-burndown-hours"), md=6),
            ], className="mb-2"),
            html.Hr(className="section-divider"),

            _section_label("Team Workload"),
            dbc.Row([
                dbc.Col(_chart_card("Workload by Person (Closed vs Open)",
                                    "workload", "ib-workload-bar"), md=6),
                dbc.Col(_chart_card("Remaining Hours by Person",
                                    "hours", "ib-hours-bar"), md=6),
            ], className="mb-2"),
            html.Hr(className="section-divider"),

            _section_label("State Breakdown"),
            _chart_card("Items by State", "state", "ib-state-bar",
                        insight_id="ib-insight-state"),
            html.Hr(className="section-divider"),

            _section_label("Blockers"),
            _table_card("🚨 P1 / P2 Open Items", "blockers", "ib-blockers-body"),
            html.Hr(className="section-divider"),

            _section_label("All Open Items"),
            html.Div([
                html.Div("📋 Open Items in This Sprint",
                         style={"fontSize": "14px", "fontWeight": "700", "marginBottom": "10px"}),
                html.Div(id="ib-open-table"),
            ], className="chart-card mb-4"),
        ], style={"paddingTop": "20px"}),
    )

    intel_tab = dcc.Tab(
        label="📊  Sprint Intelligence", value="intel",
        style=_tab_style, selected_style=_tab_selected,
        children=html.Div([
            _section_label("Velocity Trend"),
            _chart_card("Items Closed per Sprint (Last 8)", "velocity",
                        "ib-velocity-chart", insight_id="ib-velocity-insight"),
            html.Hr(className="section-divider"),

            _section_label("Scope Discipline"),
            dbc.Row([
                dbc.Col(_table_card("➕ Added Mid-Sprint (Scope Creep)",
                                    "scope_creep", "ib-scope-body"), md=6),
                dbc.Col(_table_card("🔁 Older Items (Possible Carryover)",
                                    "carryover", "ib-carryover-body"), md=6),
            ], className="mb-2"),
            html.Hr(className="section-divider"),

            _section_label("Tasks"),
            _table_card("🔧 Tasks in This Sprint", "tasks", "ib-tasks-body"),
        ], style={"paddingTop": "20px"}),
    )

    return html.Div([
        html.Div([
            html.H1("🔄 Iteration Board", className="page-title"),
            html.P("Sprint-level view of progress, burndown, workload, velocity, and scope.",
                   className="page-subtitle"),
        ], className="page-header"),
        filter_bar,
        dcc.Tabs(
            id="ib-tabs", value="sprint",
            children=[sprint_tab, intel_tab],
            style={"borderBottom": "1px solid #e8ecf0", "marginBottom": "24px"},
        ),
    ])


# ── Callback ──────────────────────────────────────────────────────────────────
@callback(
    # Sprint tab
    Output("ib-timeline-strip",    "children"),
    Output("ib-health-banner",     "children"),
    Output("ib-kpi-row",           "children"),
    Output("ib-burndown-items",    "figure"),
    Output("ib-insight-burndown",  "children"),
    Output("ib-burndown-hours",    "figure"),
    Output("ib-workload-bar",      "figure"),
    Output("ib-hours-bar",         "figure"),
    Output("ib-state-bar",         "figure"),
    Output("ib-insight-state",     "children"),
    Output("ib-blockers-body",     "children"),
    Output("ib-open-table",        "children"),
    # Intelligence tab
    Output("ib-velocity-chart",    "figure"),
    Output("ib-velocity-insight",  "children"),
    Output("ib-scope-body",        "children"),
    Output("ib-carryover-body",    "children"),
    Output("ib-tasks-body",        "children"),
    Input("ib-iteration", "value"),
    Input("ib-team",      "value"),
    Input("ib-employee",  "value"),
)
def update_iteration_board(iteration, team, employee):
    full_df = load_data()
    today   = pd.Timestamp.today().normalize()

    # Clean iteration path and names globally
    if "iteration_path" in full_df.columns:
        full_df["iteration_path"] = full_df["iteration_path"].apply(_strip_path)
    if "assigned_to" in full_df.columns:
        full_df["assigned_to"] = full_df["assigned_to"].astype(str).str.split(" <").str[0]

    def empty_fig(msg="No data"):
        return go.Figure().update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=20, l=20, r=20),
            xaxis_visible=False, yaxis_visible=False,
            annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                              font=dict(size=14, color="#a0aec0"))],
        )

    no_data = (
        html.Div(), html.Div(), html.Div(),
        empty_fig(), "", empty_fig(),
        empty_fig(), empty_fig(), empty_fig(), "",
        html.Div(), html.Div(),
        empty_fig(), "", html.Div(), html.Div(), html.Div(),
    )

    if not iteration:
        banner = dbc.Alert("Select an iteration above to view the board.", color="info")
        return (banner,) + no_data[1:]

    # ── Filter to this sprint ────────────────────────────────────────────────
    df = full_df.copy()
    if "iteration_path" in df.columns:
        df = df[df["iteration_path"] == iteration]
    if team and team != "All" and "team" in df.columns:
        df = df[df["team"] == team]
    if employee and employee != "All" and "assigned_to" in df.columns:
        df = df[df["assigned_to"] == employee]

    total = len(df)
    if total == 0:
        banner = dbc.Alert(f"No items found for iteration '{iteration}'.", color="warning")
        return (banner,) + no_data[1:]

    # ── Iteration window ─────────────────────────────────────────────────────
    iter_start, iter_end = get_iteration_dates(iteration)

    # ── Core state splits ────────────────────────────────────────────────────
    if "state" in df.columns:
        is_closed   = df["state"].isin(CLOSED_STATES)
        is_rejected = df["state"].isin(REJECTED_STATES)
    else:
        is_closed   = pd.Series(False, index=df.index)
        is_rejected = pd.Series(False, index=df.index)

    closed_df = df[is_closed]
    open_df   = df[~is_closed & ~is_rejected]
    n_closed  = len(closed_df)
    n_open    = len(open_df)
    comp_pct  = n_closed / total * 100 if total > 0 else 0

    rem_hours = 0.0
    if "remaining_work" in df.columns:
        rem_hours = pd.to_numeric(df["remaining_work"], errors="coerce").fillna(0).sum()
    elif {"original_estimate", "completed_work"}.issubset(df.columns):
        orig = pd.to_numeric(df["original_estimate"], errors="coerce").fillna(0)
        comp = pd.to_numeric(df["completed_work"],    errors="coerce").fillna(0)
        rem_hours = max((orig - comp).clip(lower=0).sum(), 0)

    days_left = max(0, (iter_end - today).days) if iter_end else None

    velocity_day = "—"
    if iter_start and n_closed > 0:
        days_elapsed = max((today - iter_start).days, 1)
        velocity_day = f"{n_closed / days_elapsed:.1f}/day"

    # ════════════════════════════════════════════════════════════════════════
    # SPRINT TAB
    # ════════════════════════════════════════════════════════════════════════

    # ── Timeline strip ───────────────────────────────────────────────────────
    if iter_start and iter_end:
        total_days    = (iter_end - iter_start).days + 1
        elapsed_days  = max(0, min((today - iter_start).days + 1, total_days))
        remaining_cal = max(0, (iter_end - today).days)
        progress_pct  = min(elapsed_days / total_days * 100, 100)
        bar_color     = ("success" if remaining_cal > 5
                         else "warning" if remaining_cal > 2 else "danger")
        timeline = html.Div([
            dbc.Row([
                dbc.Col(html.Span([
                    html.Span("Start: ", style={"fontWeight": "600", "fontSize": "12px"}),
                    html.Span(iter_start.strftime("%d %b %Y"), style={"fontSize": "12px"}),
                ]), md=3),
                dbc.Col(html.Span([
                    html.Span("End: ", style={"fontWeight": "600", "fontSize": "12px"}),
                    html.Span(iter_end.strftime("%d %b %Y"), style={"fontSize": "12px"}),
                ]), md=3),
                dbc.Col(html.Span([
                    html.Span("Elapsed: ", style={"fontWeight": "600", "fontSize": "12px"}),
                    html.Span(f"{elapsed_days} of {total_days} days", style={"fontSize": "12px"}),
                ]), md=3),
                dbc.Col(html.Span([
                    html.Span("Days Left: ", style={"fontWeight": "600", "fontSize": "12px"}),
                    html.Span(str(remaining_cal), style={
                        "fontSize": "12px", "fontWeight": "700",
                        "color": "#c05050" if remaining_cal <= 2
                                 else "#d69e2e" if remaining_cal <= 5 else "#3d9e6b",
                    }),
                ]), md=3),
            ], className="mb-2"),
            dbc.Progress(value=progress_pct, color=bar_color,
                         style={"height": "8px", "borderRadius": "4px"}),
        ], className="chart-card", style={"padding": "14px 20px"})
    else:
        timeline = html.Div()

    # ── Health banner ────────────────────────────────────────────────────────
    if comp_pct >= 80:
        h_color, h_icon, h_msg = "success", "✅", "On Track — Sprint completing well"
    elif comp_pct >= 50:
        h_color, h_icon, h_msg = "warning", "⚠️", "At Risk — Sprint may not fully complete"
    elif days_left is not None and days_left <= 3:
        h_color, h_icon, h_msg = "danger",  "🚫", "Behind — Sprint at high risk"
    else:
        h_color, h_icon, h_msg = "warning", "⚠️", "In Progress"

    h_sub = (
        f"{comp_pct:.0f}% complete  ·  {n_closed} closed  ·  {n_open} open  ·  "
        f"{rem_hours:,.0f}h remaining"
        + (f"  ·  {days_left} days left" if days_left is not None else "")
    )
    health_banner = dbc.Alert(
        dbc.Row([
            dbc.Col(html.Span(f"{h_icon} {h_msg}",
                              style={"fontSize": "16px", "fontWeight": "700"}), md=8),
            dbc.Col(html.Span(h_sub, style={"fontSize": "12px", "opacity": "0.85"}),
                    md=4, className="text-md-end"),
        ], align="center"),
        color=h_color, style={"padding": "14px 20px", "borderRadius": "10px"},
    )

    # ── KPI row ───────────────────────────────────────────────────────────────
    p1_open = int((open_df["priority"] == 1).sum()) if "priority" in open_df.columns else 0
    p2_open = int((open_df["priority"] == 2).sum()) if "priority" in open_df.columns else 0

    # Daily close sparkline for velocity card (last 14 days)
    _close_series = []
    if "closed_date" in df.columns:
        _cd = pd.to_datetime(df["closed_date"], errors="coerce")
        for d in range(13, -1, -1):
            day = today - pd.Timedelta(days=d)
            _close_series.append(int((_cd.dt.normalize() == day).sum()))
    sl_vel_ib = _sparkline_svg(_close_series, color="#3d9e6b") if _close_series else None

    kpi_row = html.Div([
        dbc.Row([
            _kpi("Total Items",  str(total),           subtitle=f"{iteration}"),
            _kpi("Closed",       str(n_closed),        cls="success"),
            _kpi("Open",         str(n_open),
                 cls="" if n_open == 0 else ("warning" if comp_pct >= 50 else "danger")),
            _kpi("Complete %",   f"{comp_pct:.1f}%",
                 cls="success" if comp_pct >= 80 else ("warning" if comp_pct >= 50 else "danger"),
                 ring_pct=comp_pct),
        ], className="g-3 mb-3"),
        dbc.Row([
            _kpi("Remaining Hrs", f"{rem_hours:,.0f}h",
                 cls="" if rem_hours == 0 else "warning"),
            _kpi("Velocity",      velocity_day,        subtitle="Items closed/day",
                 sparkline_src=sl_vel_ib),
            _kpi("P1 Open",       str(p1_open),
                 cls="danger" if p1_open > 0 else "success"),
            _kpi("P2 Open",       str(p2_open),
                 cls="warning" if p2_open > 0 else ""),
        ], className="g-3"),
    ])

    # ── Burndown — items ─────────────────────────────────────────────────────
    insight_burndown = ""
    if iter_start and iter_end and "closed_date" in df.columns:
        window_end   = min(today, iter_end)
        days         = pd.date_range(iter_start, window_end, freq="D")
        closed_dates = pd.to_datetime(df["closed_date"], errors="coerce")

        remaining_per_day = [
            int((closed_dates.isna() | (closed_dates > d)).sum())
            for d in days
        ]
        ideal_days = pd.date_range(iter_start, iter_end, freq="D")
        ideal_vals = [total - total * i / max(len(ideal_days) - 1, 1)
                      for i in range(len(ideal_days))]

        fig_burn_items = go.Figure()
        fig_burn_items.add_trace(go.Scatter(
            x=days, y=remaining_per_day, mode="lines+markers",
            name="Actual", line=dict(color="#c05050", width=2.5), marker=dict(size=5),
            fill="tozeroy", fillcolor="rgba(229,62,62,0.07)",
            hovertemplate="%{x|%b %d}: %{y} items remaining<extra></extra>",
        ))
        fig_burn_items.add_trace(go.Scatter(
            x=ideal_days, y=ideal_vals, mode="lines", name="Ideal",
            line=dict(color="#a0aec0", width=1.5, dash="dash"),
            hovertemplate="%{x|%b %d}: %{y:.0f} ideal<extra></extra>",
        ))
        fig_burn_items.update_layout(
            height=300, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=50, l=50, r=20),
            legend=dict(orientation="h", y=1.05, x=0),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)", tickangle=-35, tickfont=dict(size=11)),
            yaxis=dict(title="Items Remaining", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=11)),
        )
        if remaining_per_day:
            latest     = remaining_per_day[-1]
            ideal_now  = ideal_vals[min(len(days) - 1, len(ideal_vals) - 1)]
            diff       = latest - ideal_now
            if diff > 2:
                insight_burndown = f"{latest} items remaining — {diff:.0f} above ideal pace. Sprint is running behind."
            elif diff < -2:
                insight_burndown = f"{latest} items remaining — {abs(diff):.0f} ahead of ideal pace."
            else:
                insight_burndown = f"{latest} items remaining — tracking close to ideal pace."
    else:
        fig_burn_items = empty_fig("No date data for burndown")

    # ── Burndown — hours ─────────────────────────────────────────────────────
    if (iter_start and iter_end
            and "closed_date" in df.columns
            and {"original_estimate", "completed_work"}.issubset(df.columns)):
        window_end   = min(today, iter_end)
        days         = pd.date_range(iter_start, window_end, freq="D")
        closed_dates = pd.to_datetime(df["closed_date"], errors="coerce")
        orig         = pd.to_numeric(df["original_estimate"], errors="coerce").fillna(0)
        total_est    = orig.sum()

        hrs_remaining = []
        for d in days:
            still_open_mask = closed_dates.isna() | (closed_dates > d)
            hrs_remaining.append(float(orig[still_open_mask].sum()))

        ideal_days = pd.date_range(iter_start, iter_end, freq="D")
        ideal_hrs  = [total_est - total_est * i / max(len(ideal_days) - 1, 1)
                      for i in range(len(ideal_days))]

        fig_burn_hrs = go.Figure()
        fig_burn_hrs.add_trace(go.Scatter(
            x=days, y=hrs_remaining, mode="lines+markers",
            name="Actual hrs", line=dict(color="#f6ad55", width=2.5), marker=dict(size=5),
            fill="tozeroy", fillcolor="rgba(246,173,85,0.07)",
            hovertemplate="%{x|%b %d}: %{y:.0f}h remaining<extra></extra>",
        ))
        fig_burn_hrs.add_trace(go.Scatter(
            x=ideal_days, y=ideal_hrs, mode="lines", name="Ideal",
            line=dict(color="#a0aec0", width=1.5, dash="dash"),
        ))
        fig_burn_hrs.update_layout(
            height=300, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=50, l=60, r=20),
            legend=dict(orientation="h", y=1.05, x=0),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)", tickangle=-35, tickfont=dict(size=11)),
            yaxis=dict(title="Hours Remaining", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=11)),
        )
    else:
        fig_burn_hrs = empty_fig("No estimate data for hours burndown")

    # ── Workload by person ────────────────────────────────────────────────────
    if "assigned_to" in df.columns and "state" in df.columns:
        wl = df.copy()
        wl["status"] = wl["state"].isin(CLOSED_STATES).map({True: "Closed", False: "Open"})
        wl_grp = wl.groupby(["assigned_to", "status"]).size().reset_index(name="Count")
        fig_wl = px.bar(
            wl_grp, x="Count", y="assigned_to", color="status", orientation="h",
            color_discrete_map={"Closed": "#68d391", "Open": "#c06060"},
            labels={"assigned_to": "", "Count": "Items", "status": ""},
            barmode="stack",
        )
        n_people = wl_grp["assigned_to"].nunique()
        fig_wl.update_layout(
            height=max(n_people * 42 + 120, 280),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=40, l=185, r=60),
            legend=dict(orientation="h", y=1.05, x=0),
        )
        fig_wl.update_xaxes(gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=11))
        fig_wl.update_yaxes(tickfont=dict(size=11))
    else:
        fig_wl = empty_fig()

    # ── Remaining hours by person ─────────────────────────────────────────────
    fig_hrs = empty_fig("No hours data")
    if "assigned_to" in df.columns:
        hrs = df.copy()
        if "remaining_work" in hrs.columns:
            hrs["rem"] = pd.to_numeric(hrs["remaining_work"], errors="coerce").fillna(0)
        elif {"original_estimate", "completed_work"}.issubset(hrs.columns):
            hrs["rem"] = (
                pd.to_numeric(hrs["original_estimate"], errors="coerce").fillna(0) -
                pd.to_numeric(hrs["completed_work"],    errors="coerce").fillna(0)
            ).clip(lower=0)
        else:
            hrs["rem"] = 0

        hrs_grp = hrs.groupby("assigned_to")["rem"].sum().reset_index()
        hrs_grp = hrs_grp[hrs_grp["rem"] > 0].sort_values("rem", ascending=True)
        if not hrs_grp.empty:
            fig_hrs = px.bar(
                hrs_grp, x="rem", y="assigned_to", orientation="h",
                color="rem",
                color_continuous_scale=["#68d391", "#c97d3a", "#c05050"],
                labels={"assigned_to": "", "rem": "Hours Remaining"},
            )
            fig_hrs.update_layout(
                height=max(len(hrs_grp) * 42 + 120, 280),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=40, l=185, r=100),
                coloraxis_showscale=False,
            )
            fig_hrs.update_xaxes(gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=11))
            fig_hrs.update_yaxes(tickfont=dict(size=11))
            fig_hrs.update_traces(
                text=hrs_grp["rem"].apply(lambda x: f"{x:,.0f}h"),
                textposition="outside", textfont=dict(size=10),
                cliponaxis=False,
            )

    # ── State bar ─────────────────────────────────────────────────────────────
    insight_state = ""
    if "state" in df.columns:
        df["state_label"] = df["state"].map(STATE_MAP).fillna(df["state"])
        sc = df["state_label"].value_counts().reset_index()
        sc.columns = ["State", "Count"]
        sc["color"] = sc["State"].map(STATE_COLORS).fillna("#a0aec0")
        sc = sc.sort_values("Count", ascending=True)
        if not sc.empty:
            top = sc.iloc[-1]
            insight_state = (f"{top['State']} — {top['Count']} items "
                             f"({top['Count'] / total * 100:.0f}% of sprint).")
        fig_state = go.Figure(go.Bar(
            x=sc["Count"], y=sc["State"], orientation="h",
            marker_color=sc["color"], text=sc["Count"],
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{y}: %{x} items<extra></extra>",
        ))
        fig_state.update_layout(
            height=max(len(sc) * 40 + 80, 220),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=40, l=160, r=60),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12)),
            yaxis=dict(tickfont=dict(size=12), automargin=True),
        )
    else:
        fig_state = empty_fig()

    # ── P1/P2 Blockers ────────────────────────────────────────────────────────
    if "priority" in df.columns:
        blockers = open_df[open_df["priority"].isin([1, 2])].sort_values("priority").copy()
        if not blockers.empty:
            _th_style = {
                "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
                "letterSpacing": "0.5px", "color": "#8892a4",
                "padding": "8px 12px", "borderBottom": "1px solid rgba(255,255,255,0.08)",
                "textAlign": "left", "whiteSpace": "nowrap",
            }
            _td_style = {
                "fontSize": "12px", "padding": "9px 12px",
                "borderBottom": "1px solid rgba(255,255,255,0.04)",
                "color": "#c8c8e0", "verticalAlign": "middle",
            }
            rows = []
            for _, row in blockers.iterrows():
                item_id = row.get("work_item_id", "")
                title   = str(row.get("title", ""))[:80]
                wtype   = str(row.get("work_item_type", ""))
                prio    = row.get("priority", "")
                state   = row.get("state", "")
                owner   = str(row.get("assigned_to", "—"))
                changed = pd.to_datetime(row.get("changed_date", ""), errors="coerce")
                changed_str = changed.strftime("%d %b") if pd.notna(changed) else "—"

                id_cell = html.A(f"#{item_id}", href=f"{ADO_BASE_URL}{item_id}",
                                 target="_blank",
                                 style={"color": "#7c6af4", "fontWeight": "600",
                                        "textDecoration": "none", "fontSize": "12px"}) \
                          if pd.notna(item_id) else html.Span("—")

                rows.append(html.Tr([
                    html.Td(id_cell,                   style=_td_style),
                    html.Td(title,                     style={**_td_style, "maxWidth": "280px",
                                                              "overflow": "hidden",
                                                              "textOverflow": "ellipsis",
                                                              "whiteSpace": "nowrap"}),
                    html.Td(wtype,                     style={**_td_style, "color": "#8888aa"}),
                    html.Td(_priority_pill(prio),      style=_td_style),
                    html.Td(_state_pill(state),        style=_td_style),
                    html.Td(owner,                     style={**_td_style, "color": "#8888aa"}),
                    html.Td(changed_str,               style={**_td_style, "color": "#8892a4",
                                                              "textAlign": "right"}),
                ]))

            tbl_el = html.Table([
                html.Thead(html.Tr([
                    html.Th("ID",      style=_th_style),
                    html.Th("Title",   style={**_th_style, "width": "100%"}),
                    html.Th("Type",    style=_th_style),
                    html.Th("Priority", style=_th_style),
                    html.Th("State",   style=_th_style),
                    html.Th("Owner",   style=_th_style),
                    html.Th("Updated", style={**_th_style, "textAlign": "right"}),
                ])),
                html.Tbody(rows),
            ], style={"width": "100%", "borderCollapse": "collapse"})

            blockers_body = html.Div([
                html.Div(f"{len(blockers)} critical item(s) open — must be resolved.",
                         className="chart-insight", style={"marginBottom": "10px"}),
                html.Div(tbl_el, style={"overflowX": "auto"}),
            ])
        else:
            blockers_body = dbc.Alert("✅ No P1/P2 blockers in this sprint.",
                                      color="success",
                                      style={"padding": "10px 16px", "fontSize": "13px"})
    else:
        blockers_body = html.Div("Priority data not available.", style={"color": "#a0aec0"})

    # ── Open items table ──────────────────────────────────────────────────────
    if not open_df.empty:
        cols = [c for c in ["work_item_id", "title", "work_item_type", "state",
                             "priority", "assigned_to", "remaining_work", "function"]
                if c in open_df.columns]
        header_map_ot = {
            "work_item_id": "ID", "work_item_type": "Type",
            "assigned_to": "Owner", "remaining_work": "Rem.",
        }
        rows_ot = []
        for _, row in open_df[cols].iterrows():
            cells = []
            for c in cols:
                v = row.get(c)
                if c == "work_item_id":
                    cells.append(html.Td(
                        html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                               style={"color": "#7c6af4", "fontWeight": "600",
                                      "textDecoration": "none", "fontSize": "12px"})
                        if pd.notna(v) else "—", style=_TD))
                elif c == "title":
                    cells.append(html.Td(str(v)[:80] if pd.notna(v) else "—",
                        style={**_TD, "maxWidth": "260px", "overflow": "hidden",
                               "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
                elif c == "priority":
                    cells.append(html.Td(_priority_pill(v), style=_TD))
                elif c == "state":
                    cells.append(html.Td(_state_pill(v), style=_TD))
                elif c == "work_item_type":
                    cells.append(html.Td(_type_pill(v), style=_TD))
                elif c == "remaining_work":
                    rem = pd.to_numeric(v, errors="coerce")
                    cells.append(html.Td(
                        f"{rem:,.1f}h" if pd.notna(rem) and rem > 0 else "—",
                        style={**_TD, "color": "#8888aa", "textAlign": "right"}))
                else:
                    cells.append(html.Td(str(v) if pd.notna(v) else "—",
                        style={**_TD, "color": "#8888aa"}))
            rows_ot.append(html.Tr(cells))
        open_table = html.Div(
            html.Table([
                html.Thead(html.Tr([
                    html.Th(header_map_ot.get(c, c.replace("_", " ").title()), style=_TH)
                    for c in cols
                ])),
                html.Tbody(rows_ot),
            ], style={"width": "100%", "borderCollapse": "collapse"}),
            style={"overflowX": "auto"},
        )
    else:
        open_table = dbc.Alert("✅ All items in this sprint are closed!",
                               color="success",
                               style={"padding": "10px 16px", "fontSize": "13px"})

    # ════════════════════════════════════════════════════════════════════════
    # INTELLIGENCE TAB
    # ════════════════════════════════════════════════════════════════════════

    # ── Velocity trend (last 8 iterations with known dates) ──────────────────
    all_iters = sorted(
        [i for i in full_df["iteration_path"].dropna().unique()
         if i not in ("Not Specified", "")],
        reverse=True,
    ) if "iteration_path" in full_df.columns else []

    # Keep only iterations with known dates, sort chronologically, take last 8
    dated = [(it, *get_iteration_dates(it)) for it in all_iters]
    dated = [(it, s, e) for it, s, e in dated if s is not None]
    dated.sort(key=lambda x: x[1])
    dated = dated[-8:]

    velocity_insight = ""
    if dated:
        vel_data = []
        for it, s, e in dated:
            it_df = full_df[full_df["iteration_path"] == it]
            if team and team != "All" and "team" in full_df.columns:
                it_df = it_df[it_df["team"] == team]
            n_done = int(it_df["state"].isin(CLOSED_STATES).sum()) if "state" in it_df.columns else 0
            is_current = (it == iteration)
            vel_data.append({"Sprint": it, "Closed": n_done, "current": is_current,
                             "start": s, "end": e})

        vdf = pd.DataFrame(vel_data)
        # Short label for x-axis
        vdf["label"] = vdf["Sprint"].apply(
            lambda x: x.replace("Iteration ", "").replace("2025", "").strip(".")
        )
        colors = ["#5a8fd4" if not r["current"] else "#f6ad55"
                  for _, r in vdf.iterrows()]

        fig_vel = go.Figure(go.Bar(
            x=vdf["label"], y=vdf["Closed"],
            marker_color=colors, text=vdf["Closed"],
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{x}: %{y} items closed<extra></extra>",
        ))
        # Trend line
        if len(vdf) >= 3:
            x_idx = list(range(len(vdf)))
            z     = np.polyfit(x_idx, vdf["Closed"], 1)
            trend = np.poly1d(z)(x_idx)
            fig_vel.add_trace(go.Scatter(
                x=vdf["label"], y=trend, mode="lines",
                name="Trend", line=dict(color="#c05050", width=1.5, dash="dot"),
                hoverinfo="skip",
            ))
            avg = vdf["Closed"].mean()
            direction = "improving ▲" if z[0] > 0.5 else ("declining ▼" if z[0] < -0.5 else "stable →")
            velocity_insight = (
                f"Average {avg:.1f} items/sprint over last {len(vdf)} sprints — velocity is {direction}. "
                f"Orange bar = current sprint."
            )

        fig_vel.update_layout(
            height=300, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=30, b=60, l=50, r=20),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)", tickangle=-30, tickfont=dict(size=11)),
            yaxis=dict(title="Items Closed", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=11)),
            showlegend=False,
        )
    else:
        fig_vel = empty_fig("Not enough sprint history")

    # ── Scope creep — items added after sprint start ──────────────────────────
    if iter_start and "created_date" in df.columns:
        df["created_dt"] = pd.to_datetime(df["created_date"], errors="coerce")
        added_mid = df[df["created_dt"] >= iter_start].copy()
        if not added_mid.empty:
            cols = [c for c in ["work_item_id", "title", "work_item_type", "priority",
                                 "state", "assigned_to", "created_date"]
                    if c in added_mid.columns]
            header_map_sc = {
                "work_item_id": "ID", "work_item_type": "Type",
                "assigned_to": "Owner", "created_date": "Created",
            }
            rows_sc = []
            for _, row in added_mid[cols].iterrows():
                cells = []
                for c in cols:
                    v = row.get(c)
                    if c == "work_item_id":
                        cells.append(html.Td(
                            html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                                   style={"color": "#7c6af4", "fontWeight": "600",
                                          "textDecoration": "none", "fontSize": "12px"})
                            if pd.notna(v) else "—", style=_TD))
                    elif c == "title":
                        cells.append(html.Td(str(v)[:80] if pd.notna(v) else "—",
                            style={**_TD, "maxWidth": "200px", "overflow": "hidden",
                                   "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
                    elif c == "priority":
                        cells.append(html.Td(_priority_pill(v), style=_TD))
                    elif c == "state":
                        cells.append(html.Td(_state_pill(v), style=_TD))
                    elif c == "work_item_type":
                        cells.append(html.Td(_type_pill(v), style=_TD))
                    elif c == "created_date":
                        d_str = pd.to_datetime(v, errors="coerce")
                        cells.append(html.Td(
                            d_str.strftime("%Y-%m-%d") if pd.notna(d_str) else "—",
                            style={**_TD, "color": "#8888aa"}))
                    else:
                        cells.append(html.Td(str(v) if pd.notna(v) else "—",
                            style={**_TD, "color": "#8888aa"}))
                rows_sc.append(html.Tr(cells))
            scope_body = html.Div([
                html.Div(
                    f"{len(added_mid)} item(s) created after sprint start "
                    f"({iter_start.strftime('%d %b')}) — added mid-sprint.",
                    className="chart-insight", style={"marginBottom": "10px"},
                ),
                html.Div(
                    html.Table([
                        html.Thead(html.Tr([
                            html.Th(header_map_sc.get(c, c.replace("_", " ").title()), style=_TH)
                            for c in cols
                        ])),
                        html.Tbody(rows_sc),
                    ], style={"width": "100%", "borderCollapse": "collapse"}),
                    style={"overflowX": "auto"},
                ),
            ])
        else:
            scope_body = dbc.Alert("✅ No mid-sprint additions — scope was well controlled.",
                                   color="success",
                                   style={"padding": "10px 16px", "fontSize": "13px"})
    else:
        scope_body = html.Div("Sprint start date not available.", style={"color": "#a0aec0"})

    # ── Carryover — items created before sprint start ─────────────────────────
    if iter_start and "created_date" in df.columns:
        older = df[df["created_dt"] < iter_start].copy()
        if not older.empty:
            older["age_days"] = (iter_start - older["created_dt"]).dt.days.astype(int)
            older = older.sort_values("age_days", ascending=False)
            cols = [c for c in ["work_item_id", "title", "work_item_type", "priority",
                                 "state", "assigned_to", "created_date", "age_days"]
                    if c in older.columns]
            header_map_co = {
                "work_item_id": "ID", "work_item_type": "Type",
                "assigned_to": "Owner", "created_date": "Created",
                "age_days": "Age (days)",
            }
            rows_co = []
            for _, row in older[cols].iterrows():
                cells = []
                for c in cols:
                    v = row.get(c)
                    if c == "work_item_id":
                        cells.append(html.Td(
                            html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                                   style={"color": "#7c6af4", "fontWeight": "600",
                                          "textDecoration": "none", "fontSize": "12px"})
                            if pd.notna(v) else "—", style=_TD))
                    elif c == "title":
                        cells.append(html.Td(str(v)[:80] if pd.notna(v) else "—",
                            style={**_TD, "maxWidth": "200px", "overflow": "hidden",
                                   "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
                    elif c == "priority":
                        cells.append(html.Td(_priority_pill(v), style=_TD))
                    elif c == "state":
                        cells.append(html.Td(_state_pill(v), style=_TD))
                    elif c == "work_item_type":
                        cells.append(html.Td(_type_pill(v), style=_TD))
                    elif c == "created_date":
                        d_str = pd.to_datetime(v, errors="coerce")
                        cells.append(html.Td(
                            d_str.strftime("%Y-%m-%d") if pd.notna(d_str) else "—",
                            style={**_TD, "color": "#8888aa"}))
                    elif c == "age_days":
                        age_val = int(v) if pd.notna(v) else 0
                        age_color = ("#e07070" if age_val >= 30
                                     else "#d4924a" if age_val >= 14
                                     else "#8888aa")
                        cells.append(html.Td(str(age_val),
                            style={**_TD, "color": age_color, "fontWeight": "600",
                                   "textAlign": "right"}))
                    else:
                        cells.append(html.Td(str(v) if pd.notna(v) else "—",
                            style={**_TD, "color": "#8888aa"}))
                rows_co.append(html.Tr(cells))
            carryover_body = html.Div([
                html.Div(
                    f"{len(older)} item(s) existed before this sprint started — "
                    f"possible carryovers or long-lived backlog items.",
                    className="chart-insight", style={"marginBottom": "10px"},
                ),
                html.Div(
                    html.Table([
                        html.Thead(html.Tr([
                            html.Th(header_map_co.get(c, c.replace("_", " ").title()), style=_TH)
                            for c in cols
                        ])),
                        html.Tbody(rows_co),
                    ], style={"width": "100%", "borderCollapse": "collapse"}),
                    style={"overflowX": "auto"},
                ),
            ])
        else:
            carryover_body = dbc.Alert(
                "✅ All items were created within this sprint — no carryovers detected.",
                color="success", style={"padding": "10px 16px", "fontSize": "13px"},
            )
    else:
        carryover_body = html.Div("Date data not available.", style={"color": "#a0aec0"})

    # ── Tasks section ─────────────────────────────────────────────────────────
    if "work_item_type" in df.columns:
        tasks_df = df[df["work_item_type"].str.lower() == "task"].copy()
        if not tasks_df.empty:
            cols = [c for c in ["work_item_id", "title", "state", "assigned_to",
                                 "original_estimate", "completed_work",
                                 "remaining_work", "function"]
                    if c in tasks_df.columns]
            header_map_tk = {
                "work_item_id": "ID", "assigned_to": "Owner",
                "original_estimate": "Est.", "completed_work": "Done",
                "remaining_work": "Rem.",
            }
            n_closed_tasks = int(tasks_df["state"].isin(CLOSED_STATES).sum()) if "state" in tasks_df.columns else 0
            _hour_cols = {"original_estimate", "completed_work", "remaining_work"}
            rows_tk = []
            for _, row in tasks_df[cols].iterrows():
                cells = []
                for c in cols:
                    v = row.get(c)
                    if c == "work_item_id":
                        cells.append(html.Td(
                            html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                                   style={"color": "#7c6af4", "fontWeight": "600",
                                          "textDecoration": "none", "fontSize": "12px"})
                            if pd.notna(v) else "—", style=_TD))
                    elif c == "title":
                        cells.append(html.Td(str(v)[:80] if pd.notna(v) else "—",
                            style={**_TD, "maxWidth": "260px", "overflow": "hidden",
                                   "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
                    elif c == "state":
                        cells.append(html.Td(_state_pill(v), style=_TD))
                    elif c in _hour_cols:
                        h_val = pd.to_numeric(v, errors="coerce")
                        cells.append(html.Td(
                            f"{h_val:,.1f}h" if pd.notna(h_val) else "—",
                            style={**_TD, "color": "#8888aa", "textAlign": "right"}))
                    else:
                        cells.append(html.Td(str(v) if pd.notna(v) else "—",
                            style={**_TD, "color": "#8888aa"}))
                rows_tk.append(html.Tr(cells))
            tasks_body = html.Div([
                html.Div(
                    f"{len(tasks_df)} task(s) in this sprint — {n_closed_tasks} closed, "
                    f"{len(tasks_df) - n_closed_tasks} open.",
                    className="chart-insight", style={"marginBottom": "10px"},
                ),
                html.Div(
                    html.Table([
                        html.Thead(html.Tr([
                            html.Th(header_map_tk.get(c, c.replace("_", " ").title()), style=_TH)
                            for c in cols
                        ])),
                        html.Tbody(rows_tk),
                    ], style={"width": "100%", "borderCollapse": "collapse"}),
                    style={"overflowX": "auto"},
                ),
            ])
        else:
            tasks_body = dbc.Alert("No tasks found in this sprint.",
                                   color="secondary",
                                   style={"padding": "10px 16px", "fontSize": "13px"})
    else:
        tasks_body = html.Div("Work item type data not available.", style={"color": "#a0aec0"})

    return (
        # Sprint tab
        timeline, health_banner, kpi_row,
        fig_burn_items, insight_burndown,
        fig_burn_hrs,
        fig_wl, fig_hrs,
        fig_state, insight_state,
        blockers_body, open_table,
        # Intelligence tab
        fig_vel, velocity_insight,
        scope_body, carryover_body,
        tasks_body,
    )
