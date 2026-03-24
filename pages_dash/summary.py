"""Summary Dashboard — daily quick-glance for release management & portfolio health"""

import base64
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, ALL, callback, ctx
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

import re
import math
from dash.exceptions import PreventUpdate
from data.loader import load_data, apply_filters, filter_activity_since
from components.matrix import compute_mom_delta
from config.settings import ANALYSIS_START_DATE, RECENT_ITEMS_COUNT, ADO_BASE_URL

dash.register_page(__name__, path="/summary", name="Summary")

# ── Constants ─────────────────────────────────────────────────────────────────
OPEN_STATES   = ["Closed", "Not an issue", "Not Required", "Userstory Update"]
P1_STALE_DAYS = 7

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
    "Userstory Update": "❌ Rejected",
}
TYPE_CONSOLIDATE = {"Bug_UI": "Bug", "Bug_Text": "Bug"}

# ── Table style constants ──────────────────────────────────────────────────────
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

# ── Pill helpers ───────────────────────────────────────────────────────────────
def _priority_pill(p):
    try:
        p_int = int(p) if pd.notna(p) else 0
    except Exception:
        p_int = 0
    cls = {1: "pill pill-p1", 2: "pill pill-p2", 3: "pill pill-p3", 4: "pill pill-p4"}.get(p_int, "pill pill-p4")
    lbl = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}.get(p_int, f"P{p_int}")
    return html.Span(lbl, className=cls)


def _state_pill(s):
    s = str(s) if pd.notna(s) else ""
    disp = STATE_MAP.get(s, s)
    if "🔵" in disp or "Active" in disp:
        cls = "pill pill-active"
    elif "✅" in disp or "Closed" in disp or "Resolved" in disp:
        cls = "pill pill-closed"
    elif "❌" in disp or "Rejected" in disp:
        cls = "pill pill-p3"
    elif "🔴" in disp or "Reopened" in disp:
        cls = "pill pill-p1"
    elif "⏸" in disp or "Hold" in disp:
        cls = "pill pill-p3"
    elif "🟡" in disp or "Review" in disp:
        cls = "pill pill-p2"
    else:
        cls = "pill"
    return html.Span(disp or s, className=cls)


def _type_pill(t):
    t = str(t) if pd.notna(t) else ""
    t_norm = {"Bug_UI": "Bug", "Bug_Text": "Bug"}.get(t, t)
    cls = {
        "Bug": "pill pill-p1",
        "Enhancement": "pill pill-p2",
        "Task": "pill pill-active",
        "User Story": "pill pill-closed",
    }.get(t_norm, "pill")
    return html.Span(t_norm or "—", className=cls)


TYPE_COLORS = {
    "Bug":         "#c06060",
    "Enhancement": "#f6ad55",
    "Task":        "#63b3ed",
    "User Story":  "#68d391",
}
SOURCE_COLORS = {
    "Customer":   "#c06060",
    "Internal":   "#63b3ed",
    "Automation": "#68d391",
}

# ── Chart plain-English descriptions ─────────────────────────────────────────
_CHART_TIPS = {
    "trend": (
        "Delivery Trend — Last 12 Weeks",
        "Shows how many items were opened vs. closed each week over the past 12 weeks. "
        "When the 'Closed' line is above 'Opened', the team is reducing backlog. "
        "When 'Opened' is above 'Closed', more work is arriving than being resolved.",
    ),
    "state": (
        "Work Item Pipeline",
        "Shows where every work item currently sits in the delivery process — "
        "from newly created through to closed. A large 'Active' bar means the team is busy. "
        "A large 'On Hold' bar is worth investigating as items may be blocked.",
    ),
    "type": (
        "Work Type Breakdown",
        "Splits your portfolio by type: Bugs to fix, Enhancements to build, Tasks, "
        "and User Stories. A high Bug share relative to Enhancements can signal "
        "quality pressure on the team.",
    ),
    "priority": (
        "Open Items by Urgency",
        "Ranks open bugs and enhancements by urgency level. "
        "P1 = fix today (critical), P2 = this sprint (high), P3–P4 = backlog. "
        "Shrinking P1 and P2 should always come first.",
    ),
    "area": (
        "Items by Product Area",
        "Shows which parts of the product have the most outstanding work. "
        "Longer bars mean more backlog in that area — useful for spotting "
        "where the team is most stretched.",
    ),
    "source": (
        "Where Issues Come From",
        "Breaks down issues by origin: Customer-reported (reached end users), "
        "Internal (caught by the team), or Automation (found by tests). "
        "A rising Customer share means issues are escaping to users.",
    ),
    "function": (
        "Open vs Closed by Function",
        "Shows how many items each functional area has open (still to fix) "
        "vs closed (resolved). Functions with a large open bar relative to their "
        "closed bar are falling behind — good for spotting which parts of the "
        "product need more focus.",
    ),
}

# ── KPI definitions ───────────────────────────────────────────────────────────
# Each entry: (label, subtitle, tooltip_explanation)
# tooltip_explanation should clarify what the delta arrow means for this metric.
_KPI_META = {
    "total": (
        "Total Items",
        "All tracked work items",
        "Count of all work items regardless of state (excludes Tasks by default). "
        "△ compares to the previous 4-week period. "
        "A rising number means scope is growing — more items have been added than removed.",
    ),
    "open": (
        "Open Items",
        "Not yet closed or rejected",
        "Items still in progress — not closed, rejected, or resolved. "
        "△ compares to the previous 4-week period. "
        "Red ▲ = backlog is growing. Green ▼ = team is closing more than opening.",
    ),
    "p1": (
        "P1 Open",
        "Critical bugs — fix immediately",
        "Critical-priority (P1) bugs still open. "
        "These represent the highest risk to users or product stability. "
        "Red ▲ = more P1s opened than resolved. Green ▼ = team is clearing critical issues.",
    ),
    "velocity": (
        "Velocity / Week",
        "Avg. items closed, last 4 weeks",
        "Average number of items closed per week over the last 4 weeks. "
        "Measures team throughput. "
        "Green ▲ = team is shipping faster. Red ▼ = pace is slowing down.",
    ),
    "bugs": (
        "Total Bugs",
        "All bugs regardless of status",
        "Total bug count across all states (open, closed, rejected). "
        "Hover to see the split by origin: Customer / Internal / Automation. "
        "Red ▲ = bug volume is rising. Green ▼ = net reduction in bugs.",
    ),
    "avg_cycle": (
        "Avg. Cycle Time",
        "Mean days to close a bug",
        "Average number of days from bug creation to closure. "
        "Lower is better — a shorter cycle means bugs are being resolved faster. "
        "Red ▲ = bugs are taking longer to fix. Green ▼ = resolution is speeding up.",
    ),
    "rem_hours": (
        "Remaining Hours",
        "Sum of estimated hours on open items",
        "Sum of 'remaining work' hours logged in ADO across all open items. "
        "Reflects the team's estimated outstanding effort. "
        "No delta shown — point-in-time figure, not a trend.",
    ),
    "unassigned": (
        "Unassigned Open",
        "Open items with no owner — click to view",
        "Open items with no assigned person. "
        "Unassigned items risk being forgotten and can stall delivery. "
        "Click this card to see the full list. Ideally this should be zero.",
    ),
}


# ── Sparkline helper ──────────────────────────────────────────────────────────
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
    # Hex → rgba fill with low alpha
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


# ── Layout helpers ────────────────────────────────────────────────────────────
def _info_icon(tip_id):
    return html.Span(
        "?", id=tip_id,
        style={
            "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
            "width": "16px", "height": "16px", "borderRadius": "50%",
            "background": "#e2e8f0", "color": "#718096",
            "fontSize": "10px", "fontWeight": "700",
            "cursor": "help", "marginLeft": "7px", "flexShrink": "0",
            "verticalAlign": "middle",
        }
    )


def _chart_card(section_key, graph_id, insight_id=None):
    """Card: plain-English title + tooltip icon + optional insight + dcc.Graph."""
    title, description = _CHART_TIPS[section_key]
    tip_id = f"tip-{section_key}"
    return html.Div([
        html.Div([
            html.Span(title, className="chart-title-text"),
            _info_icon(tip_id),
            dbc.Tooltip(description, target=tip_id, placement="right",
                        style={"maxWidth": "300px", "fontSize": "12px",
                               "textAlign": "left", "lineHeight": "1.5"}),
        ], className="chart-section-header"),
        html.Div(id=insight_id, className="chart-insight") if insight_id else html.Div(),
        dcc.Graph(id=graph_id, config={"displayModeBar": False, "responsive": True}),
    ], className="chart-card")


def _source_card():
    """Source stats card — uses html.Div output, not dcc.Graph."""
    title, description = _CHART_TIPS["source"]
    return html.Div([
        html.Div([
            html.Span(title, className="chart-title-text"),
            _info_icon("tip-source"),
            dbc.Tooltip(description, target="tip-source", placement="right",
                        style={"maxWidth": "300px", "fontSize": "12px",
                               "textAlign": "left", "lineHeight": "1.5"}),
        ], className="chart-section-header"),
        html.Div(id="sum-source-stats", style={"marginTop": "12px"}),
    ], className="chart-card", style={"height": "100%"})


# ── Layout ────────────────────────────────────────────────────────────────────
def layout():
    df        = load_data()
    all_types = sorted(df["work_item_type"].dropna().unique().tolist()) if "work_item_type" in df.columns else []
    employees = ["All"] + sorted(df["assigned_to"].dropna().unique().tolist()) if "assigned_to" in df.columns else ["All"]

    _fb_style = {
        "background": "#1c1c27", "borderRadius": "10px", "padding": "14px 18px",
        "border": "1px solid rgba(255,255,255,0.07)",
        "marginBottom": "20px",
    }
    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([html.Div("Item Type", className="filter-label"),
                     dcc.Dropdown(id="sum-item-type", options=[{"label": t, "value": t} for t in all_types],
                                  value=[t for t in all_types if t != "Task"],
                                  multi=True, placeholder="All types",
                                  style={"fontSize": "12px"})], md=4),
            dbc.Col([
                html.Div("Date Range", className="filter-label"),
                html.Div([
                    dbc.Input(id="sum-date-start", type="date", debounce=True,
                              style={"flex": "1", "minWidth": "0"}),
                    html.Span("→", style={"color": "var(--text-muted)", "flexShrink": "0", "fontSize": "12px"}),
                    dbc.Input(id="sum-date-end", type="date", debounce=True,
                              style={"flex": "1", "minWidth": "0"}),
                ], className="date-range-pair"),
            ], md=4),
            dbc.Col([html.Div("Employee", className="filter-label"),
                     dcc.Dropdown(id="sum-employee", options=[{"label": e, "value": e} for e in employees],
                                  value="All", clearable=False, style={"fontSize": "12px"})], md=4),
        ], className="g-2"),
    ], style=_fb_style)

    def _section_label(text):
        return html.Div(text, style={
            "fontSize": "11px", "fontWeight": "700", "textTransform": "uppercase",
            "letterSpacing": "0.8px", "color": "#a0aec0", "marginBottom": "12px",
            "marginTop": "4px",
        })

    return html.Div([
        # ── Page header ───────────────────────────────────────────────────────
        html.Div([
            html.H1("📊 Summary Dashboard", className="page-title"),
            html.P(
                "A complete picture of where the team stands today — "
                "open work, active bugs, priorities, and delivery pace.",
                className="page-subtitle",
            ),
        ], className="page-header"),

        # ── Filters ───────────────────────────────────────────────────────────
        filter_bar,

        # ── Status snapshot (health + alerts together, right after filters) ──
        html.Div(id="sum-health-status", className="mb-2"),
        html.Div(id="sum-alerts-row",    className="mb-3"),

        # ── Act 1: At a Glance — executive KPIs ──────────────────────────────
        _section_label("At a Glance"),
        html.Div(id="sum-kpi-row"),

        # Hover popover on Total Bugs card — shows Customer/Internal/Automation split
        dbc.Popover(
            [
                dbc.PopoverHeader(
                    "Bugs by Origin",
                    style={"fontSize": "12px", "fontWeight": "700", "padding": "8px 14px"},
                ),
                dbc.PopoverBody(
                    html.Div(id="sum-bugs-breakdown-body"),
                    style={"padding": "10px 14px"},
                ),
            ],
            target="sum-kpi-bugs",
            trigger="hover",
            placement="top",
            style={"minWidth": "220px"},
        ),

        html.Hr(className="section-divider"),

        # ── Act 2: Delivery Pace ──────────────────────────────────────────────
        _section_label("Delivery Pace"),
        _chart_card("trend", "sum-trend-chart"),

        html.Div([
            html.Div([
                html.Span("📅 Scope This Month", className="chart-title-text"),
                _info_icon("tip-scope"),
                dbc.Tooltip(
                    "Tracks how many items were added vs. closed in the current calendar month. "
                    "A positive Net Change means the backlog is growing — "
                    "more work is coming in than going out.",
                    target="tip-scope", placement="right",
                    style={"maxWidth": "280px", "fontSize": "12px", "lineHeight": "1.5"},
                ),
            ], className="chart-section-header"),
            html.Div(id="sum-scope-creep", style={"marginTop": "12px"}),
        ], className="chart-card"),
        html.Hr(className="section-divider"),

        # ── Act 3: What's Urgent ──────────────────────────────────────────────
        _section_label("What's Urgent"),
        _chart_card("priority", "sum-priority-chart", "sum-insight-priority"),

        html.Div([
            html.Div([
                html.Span("🔥 Open P1 Bugs", className="chart-title-text"),
                _info_icon("tip-p1table"),
                dbc.Tooltip(
                    "P1 bugs are the most critical issues — they affect customers or block key workflows. "
                    "These should be resolved as fast as possible. "
                    "Items highlighted in red have been open for 14+ days.",
                    target="tip-p1table", placement="right",
                    style={"maxWidth": "300px", "fontSize": "12px", "lineHeight": "1.5"},
                ),
            ], className="chart-section-header"),
            html.Div(id="sum-p1-table", style={"marginTop": "10px"}),
            html.Div([
                dbc.Button("← Prev", id="sum-p1-prev", size="sm", outline=True,
                           color="secondary", n_clicks=0),
                html.Span(id="sum-p1-page-info",
                          style={"fontSize": "12px", "color": "#a0aec0", "margin": "0 8px"}),
                dbc.Button("Next →", id="sum-p1-next", size="sm", outline=True,
                           color="secondary", n_clicks=0),
            ], style={"display": "flex", "alignItems": "center", "justifyContent": "center",
                      "marginTop": "10px", "gap": "6px"}),
        ], className="chart-card"),
        html.Hr(className="section-divider"),

        # ── Act 4: Work Breakdown — drilldown treemap (Type → Area → State) ──
        _section_label("Work Breakdown"),
        html.Div([
            html.Div([
                html.Div([
                    html.Span("🗂 Work Type Breakdown", className="chart-title-text"),
                    _info_icon("tip-type"),
                    dbc.Tooltip(
                        "Click any tile to drill into product areas, then states. "
                        "Use ← Back to navigate up.",
                        target="tip-type", placement="right",
                        style={"maxWidth": "300px", "fontSize": "12px", "lineHeight": "1.5"},
                    ),
                ], style={"display": "flex", "alignItems": "center", "gap": "6px"}),
                html.Div([
                    html.Span(id="sum-treemap-breadcrumb",
                              style={"fontSize": "12px", "color": "#a0aec0"}),
                    dbc.Button("← Back", id="sum-treemap-back", size="sm",
                               outline=True, color="secondary", n_clicks=0,
                               style={"fontSize": "11px", "padding": "2px 10px",
                                      "display": "none"}),
                ], style={"display": "flex", "alignItems": "center", "gap": "10px",
                          "marginTop": "6px"}),
            ], className="chart-section-header"),
            dcc.Graph(id="sum-type-donut", config={"displayModeBar": False},
                      style={"height": "520px"}),
        ], className="chart-card"),
        html.Hr(className="section-divider"),

        # ── Act 5: Where is the Work ──────────────────────────────────────────
        _section_label("Where Is the Work"),
        _chart_card("function", "sum-function-chart", "sum-insight-function"),
        html.Hr(className="section-divider"),

        # ── Act 6: Recent Activity ────────────────────────────────────────────
        _section_label("Recent Activity"),
        html.Div([
            html.Div([
                html.Span("📋 Recently Updated Items", className="chart-title-text"),
                _info_icon("tip-recent"),
                dbc.Tooltip(
                    "The most recently changed work items. "
                    "You can edit Priority, State, and Assigned To directly in the table — "
                    "changes sync back to Azure DevOps automatically.",
                    target="tip-recent", placement="right",
                    style={"maxWidth": "300px", "fontSize": "12px", "lineHeight": "1.5"},
                ),
            ], className="chart-section-header"),
            html.Div(id="sum-recent-table", style={"marginTop": "10px"}),
            html.Div([
                dbc.Button("← Prev", id="sum-recent-prev", size="sm", outline=True,
                           color="secondary", n_clicks=0),
                html.Span(id="sum-recent-page-info",
                          style={"fontSize": "12px", "color": "#a0aec0", "margin": "0 8px"}),
                dbc.Button("Next →", id="sum-recent-next", size="sm", outline=True,
                           color="secondary", n_clicks=0),
            ], style={"display": "flex", "alignItems": "center", "justifyContent": "center",
                      "marginTop": "10px", "gap": "6px"}),
        ], className="chart-card"),

        # ── Unassigned items modal ────────────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("📌 Unassigned Open Items")),
            dbc.ModalBody(html.Div(id="sum-unassigned-modal-body")),
            dbc.ModalFooter(
                dbc.Button("Close", id="sum-unassigned-modal-close",
                           className="ms-auto", n_clicks=0)
            ),
        ], id="sum-unassigned-modal", size="xl", scrollable=True, is_open=False),

        # ── Hidden stores ─────────────────────────────────────────────────────
        dcc.Store(id="sum-tree-data"),
        dcc.Store(id="sum-treemap-path", data=[]),
        dcc.Store(id="sum-p1-store"),
        dcc.Store(id="sum-p1-page", data=0),
        dcc.Store(id="sum-recent-store"),
        dcc.Store(id="sum-recent-page", data=0),
    ])


# ── Main callback ─────────────────────────────────────────────────────────────
@callback(
    Output("sum-health-status",       "children"),   # 1
    Output("sum-alerts-row",          "children"),   # 2
    Output("sum-bugs-breakdown-body", "children"),   # 3
    Output("sum-kpi-row",          "children"),   # 4
    Output("sum-trend-chart",      "figure"),        # 5
    Output("sum-scope-creep",      "children"),      # 6
    Output("sum-priority-chart",   "figure"),        # 7
    Output("sum-insight-priority", "children"),      # 8
    Output("sum-function-chart",   "figure"),        # 9
    Output("sum-insight-function", "children"),      # 10
    Output("sum-tree-data",        "data"),          # 13
    Output("sum-p1-store",         "data"),          # 14
    Output("sum-p1-page",          "data"),          # 15  reset on filter change
    Output("sum-recent-store",     "data"),          # 16
    Output("sum-recent-page",      "data"),          # 17  reset on filter change
    Input("sum-item-type",    "value"),
    Input("sum-date-start",   "value"),
    Input("sum-date-end",     "value"),
    Input("sum-employee",     "value"),
)
def update_summary(item_types, start_date, end_date, employee):
    df = load_data()
    df = apply_filters(df, item_types=item_types, employee=employee)
    df = filter_activity_since(df, ANALYSIS_START_DATE)

    # Date range filter (CEO time-span selector)
    if "created_date" in df.columns:
        dates = pd.to_datetime(df["created_date"], errors="coerce")
        if start_date:
            df = df[dates >= pd.Timestamp(start_date)]
        if end_date:
            df = df[dates <= pd.Timestamp(end_date)]

    open_df  = df[~df["state"].isin(OPEN_STATES)]
    bugs_all = df[df["work_item_type"].str.contains("Bug", na=False, case=False)].copy()

    for col in ["created_date", "closed_date"]:
        df[col]       = pd.to_datetime(df.get(col, pd.Series(dtype="datetime64[ns]")), errors="coerce")
        bugs_all[col] = pd.to_datetime(bugs_all.get(col, pd.Series(dtype="datetime64[ns]")), errors="coerce")
    for c in ["created_date", "closed_date"]:
        if df[c].dt.tz is not None:
            df[c]       = df[c].dt.tz_localize(None)
            bugs_all[c] = bugs_all[c].dt.tz_localize(None)

    today = pd.Timestamp.today().normalize()

    # ── Core counts ────────────────────────────────────────────────────────────
    total      = len(df)
    open_items = len(open_df)
    total_bugs = len(bugs_all)
    p1_open    = len(bugs_all[(bugs_all["priority"] == 1) & (~bugs_all["state"].isin(OPEN_STATES))])
    rem_hours  = open_df["remaining_work"].sum() if "remaining_work" in open_df.columns else 0
    unassigned = int(open_df["assigned_to"].isna().sum()) if "assigned_to" in open_df.columns else 0

    closed_bugs = bugs_all[bugs_all["state"] == "Closed"].copy()
    avg_cycle_val = (
        (closed_bugs["closed_date"] - closed_bugs["created_date"]).dt.days.mean()
        if not closed_bugs.empty else None
    )
    avg_cycle_str = f"{avg_cycle_val:.1f}d" if avg_cycle_val is not None else "—"

    four_weeks_ago  = today - pd.Timedelta(weeks=4)
    recently_closed = df[df["closed_date"].notna() & (df["closed_date"] >= four_weeks_ago)]
    velocity        = round(len(recently_closed) / 4, 1)

    # ── MoM deltas ─────────────────────────────────────────────────────────────
    cur_per  = today.to_period("M")
    prev_per = cur_per - 1

    def count_open_at(source_df, period):
        pe   = (period + 1).to_timestamp()
        mask = (source_df["created_date"] < pe) & (
            source_df["closed_date"].isna() | (source_df["closed_date"] >= pe)
        )
        return int(mask.sum())

    prev_total      = int((df["created_date"] < prev_per.to_timestamp()).sum())
    prev_open_items = count_open_at(df, prev_per)
    prev_bugs       = int((bugs_all["created_date"] < (prev_per + 1).to_timestamp()).sum())
    prev_p1_open    = count_open_at(bugs_all[bugs_all["priority"] == 1], prev_per)

    prev_8w_ago   = four_weeks_ago - pd.Timedelta(weeks=4)
    prev_closed   = df[df["closed_date"].notna() &
                       (df["closed_date"] >= prev_8w_ago) &
                       (df["closed_date"] < four_weeks_ago)]
    prev_velocity = round(len(prev_closed) / 4, 1)

    def delta_badge(current, previous, lower_is_better=False):
        if previous is None or previous == current:
            return html.Span("  —", style={"fontSize": "11px", "color": "#718096"})
        diff  = current - previous
        up    = diff > 0
        color = ("#c05050" if up else "#3d9e6b") if lower_is_better else ("#3d9e6b" if up else "#c05050")
        return html.Span(f"  {'▲' if up else '▼'}{abs(diff):,.1f}",
                         style={"fontSize": "11px", "color": color, "fontWeight": "600"})

    def kpi_card(key, value, delta_el=None, cls="", clickable_id=None, card_id=None, sparkline_src=None):
        label, subtitle, tip_text = _KPI_META[key]
        # Always assign an ID so dbc.Tooltip can target it
        resolved_id = card_id or f"sum-kpi-{key}"
        text_col = html.Div([
            html.Div(label, className="metric-label"),
            html.Div([str(value), delta_el or ""], className=f"metric-value {cls}"),
            html.Div(subtitle, className="kpi-subtitle"),
        ], style={"flex": "1 1 auto", "minWidth": 0, "overflow": "hidden"})

        spark_col = (
            html.Div(html.Img(src=sparkline_src), className="kpi-sparkline-inline")
            if sparkline_src else None
        )

        body = html.Div(
            [text_col, spark_col] if spark_col else [text_col],
            style={"display": "flex", "alignItems": "center", "gap": "8px"},
        )

        card_children = [body]
        if clickable_id:
            card_children.append(html.Div("View →", className="kpi-drill-link"))
        inner = html.Div(card_children, id=resolved_id, className="metric-card")

        # Bugs card has its own rich Popover — skip the plain tooltip for it
        tooltip = (
            dbc.Tooltip(
                tip_text,
                target=resolved_id,
                placement="top",
                style={"maxWidth": "280px", "fontSize": "12px",
                       "lineHeight": "1.5", "textAlign": "left"},
            )
            if key != "bugs" else html.Div()
        )

        if clickable_id:
            return dbc.Col(
                html.Div([
                    html.Div(inner, id=clickable_id, n_clicks=0,
                             className="metric-card-clickable"),
                    tooltip,
                ]),
                md=3,
            )
        return dbc.Col(html.Div([inner, tooltip]), md=3)

    # ── Sparkline series (8 weekly data points) ───────────────────────────────
    _vel_series, _open_series, _bugs_series, _p1_series = [], [], [], []
    for w in range(7, -1, -1):
        w_start = today - pd.Timedelta(weeks=w + 1)
        w_end   = today - pd.Timedelta(weeks=w)
        # velocity (closes per week)
        _vel_series.append(int(df[
            df["closed_date"].notna() &
            (df["closed_date"] >= w_start) & (df["closed_date"] < w_end)
        ].shape[0]))
        # open items snapshot at week-end
        _open_series.append(int((
            (df["created_date"] <= w_end) &
            (df["closed_date"].isna() | (df["closed_date"] > w_end))
        ).sum()))
        # total bugs cumulative
        _bugs_series.append(int((bugs_all["created_date"] <= w_end).sum()))
        # p1 open snapshot
        p1_mask = bugs_all["priority"] == 1
        _p1_series.append(int((
            p1_mask &
            (bugs_all["created_date"] <= w_end) &
            (bugs_all["closed_date"].isna() | (bugs_all["closed_date"] > w_end))
        ).sum()))

    sl_vel  = _sparkline_svg(_vel_series,  color="#3d9e6b")
    sl_open = _sparkline_svg(_open_series, color="#c05050")
    sl_bugs = _sparkline_svg(_bugs_series, color="#c05050")
    sl_p1   = _sparkline_svg(_p1_series,   color="#c05050")

    kpi_row = html.Div([
        # Row 1 — Executive view
        dbc.Row([
            kpi_card("total",    f"{total:,}",
                     delta_badge(total, prev_total, lower_is_better=False)),
            kpi_card("open",     f"{open_items:,}",
                     delta_badge(open_items, prev_open_items, lower_is_better=True),
                     sparkline_src=sl_open),
            kpi_card("p1",       f"{p1_open:,}",
                     delta_badge(p1_open, prev_p1_open, lower_is_better=True),
                     "danger" if p1_open > 0 else "success",
                     sparkline_src=sl_p1),
            kpi_card("velocity", f"{velocity}",
                     delta_badge(velocity, prev_velocity, lower_is_better=False),
                     sparkline_src=sl_vel),
        ], className="g-3 mb-3"),
        # Row 2 — Operational view
        dbc.Row([
            kpi_card("bugs",      f"{total_bugs:,}",
                     delta_badge(total_bugs, prev_bugs, lower_is_better=True),
                     card_id="sum-kpi-bugs", sparkline_src=sl_bugs),
            kpi_card("avg_cycle", avg_cycle_str),
            kpi_card("rem_hours", f"{rem_hours:,.0f}h"),
            kpi_card("unassigned", f"{unassigned:,}",
                     cls="danger" if unassigned > 10 else "",
                     clickable_id="sum-unassigned-card-click"),
        ], className="g-3"),
    ])

    # ── RAG health banner ───────────────────────────────────────────────────────
    open_p1_df = bugs_all[(bugs_all["priority"] == 1) & (~bugs_all["state"].isin(OPEN_STATES))].copy()
    open_p1_df["age_days"] = (today - open_p1_df["created_date"]).dt.days.fillna(0)
    stale_p1_count = int((open_p1_df["age_days"] >= P1_STALE_DAYS).sum())

    if p1_open == 0 and unassigned <= 5:
        rag_color  = "success"
        rag_icon   = "🟢"
        rag_label  = "Healthy"
        rag_detail = (
            f"No critical P1 bugs open. "
            f"Team is closing {velocity} items/week. "
            f"{unassigned} unassigned item{'s' if unassigned != 1 else ''}."
        )
    elif p1_open <= 2 and unassigned <= 20:
        rag_color  = "warning"
        rag_icon   = "🟡"
        rag_label  = "Needs Attention"
        rag_detail = (
            f"{p1_open} critical P1 bug{'s' if p1_open != 1 else ''} open"
            + (f", {stale_p1_count} stale for {P1_STALE_DAYS}+ days" if stale_p1_count else "")
            + f". {unassigned} unassigned open items."
        )
    else:
        rag_color  = "danger"
        rag_icon   = "🔴"
        rag_label  = "Critical"
        rag_detail = (
            f"{p1_open} critical P1 bug{'s' if p1_open != 1 else ''} open"
            + (f" ({stale_p1_count} stale {P1_STALE_DAYS}+ days)" if stale_p1_count else "")
            + f". {unassigned} open items have no owner assigned."
        )

    health_banner = dbc.Alert(
        dbc.Row([
            dbc.Col(html.Div([
                html.Span(f"{rag_icon} Portfolio Status: ", style={"fontWeight": "700"}),
                html.Span(rag_label, style={"fontWeight": "700"}),
            ], style={"fontSize": "15px"}), md="auto"),
            dbc.Col(html.Span(rag_detail, style={"fontSize": "13px"}),
                    className="d-flex align-items-center"),
        ], align="center"),
        color=rag_color,
        style={"padding": "12px 20px", "borderRadius": "10px", "marginBottom": "0"},
    )

    # ── Alerts ──────────────────────────────────────────────────────────────────
    alerts = []
    stale_p1 = open_p1_df[open_p1_df["age_days"] >= P1_STALE_DAYS]
    if not stale_p1.empty:
        alerts.append(dbc.Alert([
            html.Strong(f"⚠️ {len(stale_p1)} P1 bug(s) open for {P1_STALE_DAYS}+ days. "),
            f"Oldest: {int(stale_p1['age_days'].max())} days. ",
            f"Assignees: {', '.join(stale_p1['assigned_to'].dropna().unique()[:5])}",
        ], color="danger", style={"padding": "10px 16px", "fontSize": "13px", "marginBottom": "8px"}))
    if unassigned > 0:
        alerts.append(dbc.Alert(
            f"📌 {unassigned} open item(s) have no assignee — at risk of being missed.",
            color="warning", style={"padding": "10px 16px", "fontSize": "13px", "marginBottom": "8px"}
        ))
    alerts_row = html.Div(alerts) if alerts else html.Div()

    # ── Trend chart: weekly opened vs closed, last 12 weeks ────────────────────
    weeks_start = pd.date_range(end=today, periods=13, freq="W-MON")[:-1]
    trend_rows  = []
    for ws in weeks_start:
        we = ws + pd.Timedelta(days=6)
        opened = int(((df["created_date"] >= ws) & (df["created_date"] <= we)).sum())
        closed = int((df["closed_date"].notna() &
                      (df["closed_date"] >= ws) &
                      (df["closed_date"] <= we)).sum())
        trend_rows.append({"Week": ws.strftime("%b %d"), "Opened": opened, "Closed": closed})

    trend_df = pd.DataFrame(trend_rows)
    net_trend = trend_df["Closed"].sum() - trend_df["Opened"].sum()

    fig_trend = go.Figure([
        go.Scatter(
            name="Opened", x=trend_df["Week"], y=trend_df["Opened"],
            mode="lines+markers",
            line=dict(color="#c06060", width=2.5),
            marker=dict(size=5),
            hovertemplate="%{x}<br>Opened: %{y}<extra></extra>",
            fill="tozeroy", fillcolor="rgba(252,129,129,0.08)",
        ),
        go.Scatter(
            name="Closed", x=trend_df["Week"], y=trend_df["Closed"],
            mode="lines+markers",
            line=dict(color="#68d391", width=2.5),
            marker=dict(size=5),
            hovertemplate="%{x}<br>Closed: %{y}<extra></extra>",
            fill="tozeroy", fillcolor="rgba(104,211,145,0.08)",
        ),
    ])
    fig_trend.update_layout(
        height=220, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=10, b=40, l=50, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=11)),
        xaxis=dict(tickfont=dict(size=11), gridcolor="rgba(255,255,255,0.06)", tickangle=-30),
        yaxis=dict(title="Items", gridcolor="rgba(255,255,255,0.06)"),
        hovermode="x unified",
    )

    # ── Scope creep card ────────────────────────────────────────────────────────
    month_start       = today.replace(day=1)
    added_this_month  = int((df["created_date"] >= month_start).sum())
    closed_this_month = int((df["closed_date"].notna() & (df["closed_date"] >= month_start)).sum())
    net_change        = added_this_month - closed_this_month
    net_color         = "#c05050" if net_change > 0 else "#3d9e6b"
    net_label         = f"+{net_change}" if net_change > 0 else str(net_change)

    max_val = max(added_this_month, closed_this_month, 1)
    scope_card = dbc.Row([
        dbc.Col(html.Div([
            html.Div("Added",          className="metric-label"),
            html.Div(f"{added_this_month:,}",
                     className="metric-value",
                     style={"color": "#c05050"}),
            html.Div(f"in {today.strftime('%B %Y')}", className="kpi-subtitle"),
        ], className="metric-card"), md=3),

        dbc.Col(html.Div([
            html.Div("Closed",         className="metric-label"),
            html.Div(f"{closed_this_month:,}",
                     className="metric-value",
                     style={"color": "#3d9e6b"}),
            html.Div(f"in {today.strftime('%B %Y')}", className="kpi-subtitle"),
        ], className="metric-card"), md=3),

        dbc.Col(html.Div([
            html.Div("Net Change",     className="metric-label"),
            html.Div(net_label,
                     className="metric-value",
                     style={"color": net_color}),
            html.Div("positive = backlog growing", className="kpi-subtitle"),
        ], className="metric-card"), md=3),

        dbc.Col(html.Div([
            html.Div("Added vs Closed", className="metric-label",
                     style={"marginBottom": "10px"}),
            html.Div([
                html.Div("Added", style={"fontSize": "10px", "color": "#718096",
                                         "width": "42px", "display": "inline-block"}),
                html.Div(style={
                    "display": "inline-block", "height": "10px", "borderRadius": "5px",
                    "background": "#c06060", "verticalAlign": "middle",
                    "width": f"{round(added_this_month / max_val * 140)}px",
                    "minWidth": "4px",
                }),
            ], style={"marginBottom": "5px"}),
            html.Div([
                html.Div("Closed", style={"fontSize": "10px", "color": "#718096",
                                          "width": "42px", "display": "inline-block"}),
                html.Div(style={
                    "display": "inline-block", "height": "10px", "borderRadius": "5px",
                    "background": "#68d391", "verticalAlign": "middle",
                    "width": f"{round(closed_this_month / max_val * 140)}px",
                    "minWidth": "4px",
                }),
            ]),
        ], className="metric-card"), md=3),
    ], className="g-3")

    # ── State breakdown ────────────────────────────────────────────────────────
    df_state = df.copy()
    df_state["state_group"] = df_state["state"].map(STATE_MAP).fillna("❓ Other")
    df_state["type_group"]  = df_state["work_item_type"].replace(TYPE_CONSOLIDATE)

    state_counts = df_state.groupby(["state_group", "type_group"]).size().reset_index(name="count")
    state_order  = (state_counts.groupby("state_group")["count"].sum()
                    .sort_values(ascending=True).index.tolist())
    state_h      = max(len(state_order) * 50 + 100, 300)

    # fig_state removed — treemap drilldown replaces the pipeline bar chart

    # ── Work Type Breakdown — 3-level drilldown treemap (Type → Area → State) ────
    if "area" in df_state.columns:
        tree_df = (
            df_state
            .assign(Area=df_state["area"].fillna("Unknown"))
            .groupby(["type_group", "Area", "state_group"])
            .size()
            .reset_index(name="Count")
            .rename(columns={"type_group": "Type", "state_group": "State"})
        )
        tree_path = ["Type", "Area", "State"]
    else:
        tree_df = (
            df_state
            .groupby(["type_group", "state_group"])
            .size()
            .reset_index(name="Count")
            .rename(columns={"type_group": "Type", "state_group": "State"})
        )
        tree_path = ["Type", "State"]

    # ── Priority chart ──────────────────────────────────────────────────────────
    bugs_df = open_df[open_df["work_item_type"].str.contains("Bug",         na=False, case=False)]
    enh_df  = open_df[open_df["work_item_type"].str.contains("Enhancement", na=False, case=False)]
    bug_pri = bugs_df["priority"].value_counts().sort_index().reindex([1, 2, 3, 4], fill_value=0)
    enh_pri = enh_df["priority"].value_counts().sort_index().reindex([1, 2, 3, 4], fill_value=0)
    labels  = ["P1 — Critical 🔥", "P2 — High ⚠️", "P3 — Medium", "P4 — Low"]

    fig_pri = go.Figure([
        go.Bar(name="Bugs",         x=labels, y=bug_pri.values, marker_color="#c06060",
               hovertemplate="%{x}<br>Bugs: %{y}<extra></extra>"),
        go.Bar(name="Enhancements", x=labels, y=enh_pri.values, marker_color="#f6ad55",
               hovertemplate="%{x}<br>Enhancements: %{y}<extra></extra>"),
    ])
    fig_pri.update_layout(
        barmode="group", height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=20, b=60, l=60, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig_pri.update_xaxes(tickfont=dict(size=12), ticklabelstandoff=6)
    fig_pri.update_yaxes(title="Number of Open Items", gridcolor="rgba(255,255,255,0.06)", ticklabelstandoff=6)

    p1_bugs_count = int(bug_pri.get(1, 0))
    p2_bugs_count = int(bug_pri.get(2, 0))
    p1_enh_count  = int(enh_pri.get(1, 0))
    parts = []
    if p1_bugs_count > 0:
        parts.append(f"{p1_bugs_count} critical P1 bug{'s' if p1_bugs_count != 1 else ''} need immediate resolution")
    if p1_enh_count > 0:
        parts.append(f"{p1_enh_count} P1 enhancement{'s' if p1_enh_count != 1 else ''} marked critical")
    if not parts:
        parts.append("No P1 items open")
    insight_priority = (". ".join(parts) + ". "
                        + (f"{p2_bugs_count} P2 high-priority bug{'s' if p2_bugs_count != 1 else ''} also require attention."
                           if p2_bugs_count > 0 else ""))

    # ── Area chart — concentric circles ─────────────────────────────────────────
    _CIRCLE_COLORS = [
        "#7c6af4", "#5a8fd4", "#3d9e6b", "#c97d3a",
        "#c05050", "#68d391", "#a78bfa", "#f6ad55",
    ]

    if "area" in df.columns:
        area_data = df_state.copy()
        if "type_group" not in area_data.columns:
            area_data["type_group"] = area_data["work_item_type"].replace(TYPE_CONSOLIDATE)
        area_counts  = area_data.groupby(["area", "type_group"]).size().reset_index(name="count")
        area_totals  = area_counts.groupby("area")["count"].sum().sort_values(ascending=False)

        if not area_totals.empty:
            # Cap at 8 areas; merge the rest into "Other"
            MAX_AREAS = 8
            if len(area_totals) > MAX_AREAS:
                top          = area_totals.head(MAX_AREAS - 1)
                other_count  = int(area_totals.iloc[MAX_AREAS - 1:].sum())
                area_totals  = pd.concat([top, pd.Series({"Other": other_count})])

            sorted_areas = (
                area_totals.reset_index()
                .rename(columns={0: "total", "count": "total"})
            )
            sorted_areas.columns = ["area", "total"]
            sorted_areas = sorted_areas.sort_values("total", ascending=False).reset_index(drop=True)

            max_count = int(sorted_areas["total"].max())
            theta     = np.linspace(0, 2 * np.pi, 300)
            radii     = [(float(row["total"]) / max_count) ** 0.5
                         for _, row in sorted_areas.iterrows()]

            fig_area = go.Figure()

            for i, (_, row) in enumerate(sorted_areas.iterrows()):
                area_name = str(row["area"])
                count     = int(row["total"])
                r         = radii[i]
                color     = _CIRCLE_COLORS[i % len(_CIRCLE_COLORS)]
                hx        = color.lstrip("#")
                rgb       = f"{int(hx[0:2],16)},{int(hx[2:4],16)},{int(hx[4:6],16)}"

                fig_area.add_trace(go.Scatter(
                    x=(r * np.cos(theta)).tolist(),
                    y=(r * np.sin(theta)).tolist(),
                    fill="toself",
                    fillcolor=f"rgba({rgb},0.13)",
                    line=dict(color=color, width=2),
                    mode="lines",
                    name=area_name,
                    hovertemplate=f"<b>{area_name}</b><br>{count} open items<extra></extra>",
                    showlegend=True,
                ))

                # Annotation in the centre of this ring band
                r_next   = radii[i + 1] if i + 1 < len(radii) else 0
                label_y  = (r + r_next) / 2
                fig_area.add_annotation(
                    x=0, y=label_y,
                    text=f"<b>{count}</b>",
                    showarrow=False,
                    font=dict(size=14, color=color),
                    align="center", xanchor="center", yanchor="middle",
                )

            fig_area.update_layout(
                height=400,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(visible=False, range=[-1.2, 1.2], fixedrange=True),
                yaxis=dict(visible=False, range=[-1.2, 1.2],
                           scaleanchor="x", scaleratio=1, fixedrange=True),
                margin=dict(t=10, b=110, l=10, r=10),
                legend=dict(
                    orientation="h", yanchor="top", y=-0.04,
                    xanchor="center", x=0.5,
                    font=dict(size=11, color="#c8c8e0"),
                    bgcolor="rgba(0,0,0,0)",
                    itemsizing="constant",
                    traceorder="normal",
                ),
            )

            top_area       = sorted_areas.iloc[0]["area"]
            top_area_count = int(sorted_areas.iloc[0]["total"])
            second_area    = sorted_areas.iloc[1]["area"] if len(sorted_areas) > 1 else None
            insight_area   = (
                f"'{top_area}' has the most outstanding items ({top_area_count})"
                + (f", followed by '{second_area}' ({int(sorted_areas.iloc[1]['total'])})."
                   if second_area else ".")
            )
        else:
            fig_area     = go.Figure()
            insight_area = ""
    else:
        fig_area     = go.Figure()
        insight_area = ""

    # ── Function open vs closed bubble chart ────────────────────────────────────
    if "function" in df.columns:
        func_df = df.copy()
        func_df["is_open"] = ~func_df["state"].isin(OPEN_STATES)
        func_agg = func_df.groupby("function").agg(
            open=("is_open", "sum"),
            total=("is_open", "count"),
        ).reset_index()
        func_agg["closed"]   = func_agg["total"] - func_agg["open"]
        func_agg["open"]     = func_agg["open"].astype(int)
        func_agg["pct_open"] = (func_agg["open"] / func_agg["total"] * 100).round(1)
        func_agg = func_agg[func_agg["total"] > 0]

        # Colour each bubble: red if majority open, green if majority closed
        func_agg["color"] = func_agg["pct_open"].apply(
            lambda p: "#c06060" if p >= 50 else "#3d9e6b"
        )
        max_size = func_agg["total"].max()
        func_agg["marker_size"] = func_agg["total"].apply(
            lambda v: max(8, min(52, v / max_size * 52))
        )

        # Only label the top 12 by open count — everything else is hover-only
        label_threshold = func_agg["open"].nlargest(12).min()
        func_agg["label"] = func_agg.apply(
            lambda r: r["function"] if r["open"] >= label_threshold else "", axis=1
        )

        fig_function = go.Figure()
        fig_function.add_trace(go.Scatter(
            x=func_agg["closed"],
            y=func_agg["open"],
            mode="markers+text",
            marker=dict(
                size=func_agg["marker_size"],
                color=func_agg["color"],
                opacity=0.72,
                line=dict(width=1.5, color="white"),
            ),
            text=func_agg["label"],
            textposition="top center",
            textfont=dict(size=11, color="#c8c8e0"),
            customdata=func_agg[["function", "total", "pct_open"]].values,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Open: %{y}  |  Closed: %{x}<br>"
                "Total: %{customdata[1]}  |  %{customdata[2]:.1f}% open"
                "<extra></extra>"
            ),
        ))

        # Diagonal reference line: equal open & closed
        max_val = int(max(func_agg["open"].max(), func_agg["closed"].max()) * 1.15) + 1
        fig_function.add_shape(
            type="line", x0=0, y0=0, x1=max_val, y1=max_val,
            line=dict(color="#cbd5e0", width=1, dash="dot"),
        )
        fig_function.add_annotation(
            x=max_val * 0.82, y=max_val * 0.90, text="Equal open & closed",
            showarrow=False, font=dict(size=11, color="#a0aec0"),
        )

        fig_function.update_layout(
            height=520,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=30, b=60, l=70, r=40),
            xaxis=dict(title="Closed Items", gridcolor="rgba(255,255,255,0.06)", zeroline=False,
                       title_font=dict(size=12)),
            yaxis=dict(title="Open Items", gridcolor="rgba(255,255,255,0.06)", zeroline=False,
                       title_font=dict(size=12)),
            showlegend=False,
        )

        if not func_agg.empty:
            worst_row   = func_agg.loc[func_agg["open"].idxmax()]
            worst_func  = worst_row["function"]
            worst_open  = int(worst_row["open"])
            worst_pct   = worst_row["pct_open"]
            insight_function = (
                f"'{worst_func}' has the most open items ({worst_open}, {worst_pct:.0f}% of its total). "
                "Bubbles above the dotted line have more open than closed work — focus there first."
            )
        else:
            insight_function = "No function data available."
    else:
        fig_function     = go.Figure()
        insight_function = ""

    # ── Source stats (3 bold numbers) ──────────────────────────────────────────
    if "type" in df.columns:
        src        = df["type"].fillna("Unknown").value_counts()
        total_src  = src.sum()

        def _src_stat(label, key, color):
            count = int(src.get(key, 0))
            pct   = round(count / total_src * 100) if total_src else 0
            descs = {
                "Customer":   "Reported by end users",
                "Internal":   "Caught by the team",
                "Automation": "Found by tests",
            }
            return dbc.Col(html.Div([
                html.Div(label, className="metric-label"),
                html.Div(f"{count:,}", style={"fontSize": "26px", "fontWeight": "700",
                                               "color": color, "lineHeight": "1.1"}),
                html.Div(f"{pct}% of total", className="kpi-subtitle"),
                html.Div(descs.get(key, ""), className="kpi-subtitle"),
            ], className="metric-card"), md=4)

        source_stats = dbc.Row([
            _src_stat("Customer",   "Customer",   SOURCE_COLORS["Customer"]),
            _src_stat("Internal",   "Internal",   SOURCE_COLORS["Internal"]),
            _src_stat("Automation", "Automation", SOURCE_COLORS["Automation"]),
        ], className="g-2")
    else:
        source_stats = html.Div("No source data available.",
                                style={"color": "#718096", "fontSize": "13px", "padding": "12px 0"})

    # ── Open P1 table ───────────────────────────────────────────────────────────
    p1_open_df = bugs_all[
        (bugs_all["priority"] == 1) & (~bugs_all["state"].isin(OPEN_STATES))
    ].copy()
    p1_open_df["age_days"] = (today - p1_open_df["created_date"]).dt.days.fillna(0).astype(int)
    p1_open_df = p1_open_df.sort_values("age_days", ascending=False)

    p1_cols = [c for c in ["work_item_id", "title", "assigned_to", "team",
                             "state", "function", "area", "age_days"]
               if c in p1_open_df.columns]

    # p1_table HTML removed — now rendered by render_p1_table callback from sum-p1-store

    # ── Recent items table ──────────────────────────────────────────────────────
    cols_show = [c for c in ["work_item_id", "title", "assigned_to", "team",
                              "state", "priority", "function", "area", "type"]
                 if c in df.columns]
    date_col  = next((c for c in ["changed_date", "updated_date", "created_date"]
                      if c in df.columns), None)
    if date_col:
        recent = df.copy()
        recent[date_col] = pd.to_datetime(recent[date_col], errors="coerce")
        recent = recent.sort_values(date_col, ascending=False).head(RECENT_ITEMS_COUNT)[cols_show]
    else:
        recent = df[cols_show].tail(RECENT_ITEMS_COUNT).copy()

    # recent_table HTML removed — now rendered by render_recent_table callback from sum-recent-store

    # ── Bugs-by-origin popover content ─────────────────────────────────────────
    _src_colors = {"Customer": "#c06060", "Internal": "#63b3ed", "Automation": "#68d391"}
    if "type" in bugs_all.columns:
        src_counts = bugs_all["type"].fillna("Unknown").value_counts()
        src_total  = int(src_counts.sum())
        popover_rows = []
        for src_key, src_color in _src_colors.items():
            cnt = int(src_counts.get(src_key, 0))
            pct = round(cnt / src_total * 100) if src_total else 0
            bar_w = round(cnt / src_total * 100) if src_total else 0
            popover_rows.append(html.Div([
                html.Div([
                    html.Span(src_key, style={"fontSize": "11px", "color": "#718096",
                                              "width": "72px", "display": "inline-block"}),
                    html.Span(f"{cnt:,}", style={"fontSize": "13px", "fontWeight": "700",
                                                  "color": src_color, "width": "52px",
                                                  "display": "inline-block"}),
                    html.Span(f"{pct}%", style={"fontSize": "11px", "color": "#a0aec0"}),
                ], style={"marginBottom": "4px"}),
                html.Div(style={
                    "height": "5px", "borderRadius": "3px",
                    "background": src_color, "opacity": "0.7",
                    "width": f"{bar_w}%", "minWidth": "4px",
                    "marginBottom": "8px",
                }),
            ]))
        bugs_breakdown = html.Div(popover_rows)
    else:
        bugs_breakdown = html.Div("No origin data available.",
                                  style={"fontSize": "12px", "color": "#718096"})

    # ── Insight callout helper ──────────────────────────────────────────────────
    def _insight_el(text):
        if not text:
            return html.Div()
        return html.Div([
            html.Span("💡 ", style={"marginRight": "4px"}),
            html.Span(text),
        ], className="chart-insight")

    return (
        health_banner,                      # 1  sum-health-status
        alerts_row,                         # 2  sum-alerts-row
        bugs_breakdown,                     # 3  sum-bugs-breakdown-body
        kpi_row,                            # 4  sum-kpi-row
        fig_trend,                          # 5  sum-trend-chart
        scope_card,                         # 6  sum-scope-creep
        fig_pri,                            # 7  sum-priority-chart
        _insight_el(insight_priority),      # 8  sum-insight-priority
        fig_function,                       # 9  sum-function-chart
        _insight_el(insight_function),      # 10 sum-insight-function
        tree_df.to_dict("records") if not tree_df.empty else [],  # 13 sum-tree-data
        p1_open_df[p1_cols].to_dict("records") if not p1_open_df.empty else [],  # 14 sum-p1-store
        0,                                  # 15 sum-p1-page reset
        recent.to_dict("records") if not recent.empty else [],    # 16 sum-recent-store
        0,                                  # 17 sum-recent-page reset
    )


# ── Unassigned modal callback ─────────────────────────────────────────────────
@callback(
    Output("sum-unassigned-modal",      "is_open"),
    Output("sum-unassigned-modal-body", "children"),
    Input("sum-unassigned-card-click",  "n_clicks"),
    Input("sum-unassigned-modal-close", "n_clicks"),
    State("sum-item-type",        "value"),
    State("sum-date-start",       "value"),
    State("sum-date-end",         "value"),
    State("sum-employee",         "value"),
    State("sum-unassigned-modal", "is_open"),
    prevent_initial_call=True,
)
def toggle_unassigned_modal(open_clicks, close_clicks,
                             item_types, start_date, end_date, employee,
                             is_open):
    if open_clicks is None:
        raise PreventUpdate

    if ctx.triggered_id == "sum-unassigned-modal-close":
        return False, dash.no_update

    # Load and filter data
    df = load_data()
    df = apply_filters(df, item_types=item_types, employee=employee)
    df = filter_activity_since(df, ANALYSIS_START_DATE)
    if "created_date" in df.columns:
        dates = pd.to_datetime(df["created_date"], errors="coerce")
        if start_date:
            df = df[dates >= pd.Timestamp(start_date)]
        if end_date:
            df = df[dates <= pd.Timestamp(end_date)]

    open_df      = df[~df["state"].isin(OPEN_STATES)]
    unassigned   = open_df[open_df["assigned_to"].isna()].copy()

    if unassigned.empty:
        return True, html.P("✅ No unassigned open items.",
                            style={"color": "#3d9e6b", "fontWeight": "600"})

    cols = [c for c in ["work_item_id", "title", "work_item_type", "priority",
                         "state", "team", "area", "created_date"]
            if c in unassigned.columns]
    disp = unassigned[cols].copy()

    if "created_date" in disp.columns:
        disp["created_date"] = pd.to_datetime(disp["created_date"], errors="coerce") \
                                  .dt.strftime("%Y-%m-%d")

    header_map_ua = {"work_item_id": "ID", "work_item_type": "Type"}
    rows_ua = []
    for _, row in disp.iterrows():
        cells = []
        for c in disp.columns:
            v = row.get(c)
            if c == "work_item_id":
                cells.append(html.Td(
                    html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                           style={"color": "#7c6af4", "fontWeight": "600",
                                  "textDecoration": "none", "fontSize": "12px"})
                    if pd.notna(v) else "—", style=_TD))
            elif c == "title":
                cells.append(html.Td(str(v)[:80] if pd.notna(v) else "—",
                    style={**_TD, "maxWidth": "220px", "overflow": "hidden",
                           "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
            elif c == "priority":
                cells.append(html.Td(_priority_pill(v), style=_TD))
            elif c == "state":
                cells.append(html.Td(_state_pill(v), style=_TD))
            elif c == "work_item_type":
                cells.append(html.Td(_type_pill(v), style=_TD))
            else:
                cells.append(html.Td(str(v) if pd.notna(v) else "—",
                    style={**_TD, "color": "#8888aa"}))
        rows_ua.append(html.Tr(cells))

    table = html.Div(
        html.Table([
            html.Thead(html.Tr([
                html.Th(header_map_ua.get(c, c.replace("_", " ").title()), style=_TH)
                for c in disp.columns
            ])),
            html.Tbody(rows_ua),
        ], style={"width": "100%", "borderCollapse": "collapse"}),
        style={"overflowX": "auto"},
    )
    return True, html.Div([
        html.P(f"{len(unassigned)} open items currently have no owner. "
               "Assign them in Azure DevOps or use the Recent Items table to update.",
               style={"fontSize": "13px", "color": "#718096", "marginBottom": "12px"}),
        table,
    ])


# ── Table pagination constants ─────────────────────────────────────────────────
_PAGE_SIZE = 12


def _build_p1_table_html(records, page):
    """Build html.Table for P1 bugs from serialized records, sliced to current page."""
    if not records:
        return html.Div([
            html.Span("✅", style={"fontSize": "24px"}),
            html.P("No open P1 bugs — great shape!",
                   style={"color": "#3d9e6b", "fontWeight": "600",
                          "marginTop": "8px", "marginBottom": "0"}),
        ], style={"textAlign": "center", "padding": "20px 0"})

    start = page * _PAGE_SIZE
    sliced = records[start: start + _PAGE_SIZE]
    header_map = {"work_item_id": "ID", "assigned_to": "Owner", "age_days": "Age (days)"}
    cols = list(sliced[0].keys()) if sliced else []

    rows = []
    for row in sliced:
        item_id_raw = row.get("work_item_id")
        cells = []
        for c in cols:
            v = row.get(c)
            is_na = v is None or (isinstance(v, float) and math.isnan(v))
            if c == "work_item_id":
                cells.append(html.Td(
                    html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                           style={"color": "#7c6af4", "fontWeight": "600",
                                  "textDecoration": "none", "fontSize": "12px"})
                    if not is_na else "—", style=_TD))
            elif c == "title":
                cells.append(html.Td(str(v)[:80] if not is_na else "—",
                    style={**_TD, "maxWidth": "200px", "overflow": "hidden",
                           "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
            elif c == "state":
                cells.append(html.Td(_state_pill(v) if not is_na else "—", style=_TD))
            elif c == "age_days":
                age = int(v) if not is_na else 0
                color = "#e07070" if age >= 14 else "#c8c8e0"
                cells.append(html.Td(str(age), style={**_TD, "color": color, "fontWeight": "600" if age >= 14 else "400"}))
            else:
                cells.append(html.Td(str(v) if not is_na else "—",
                    style={**_TD, "color": "#8888aa"}))
        rows.append(html.Tr(cells))

    return html.Div(
        html.Table([
            html.Thead(html.Tr([
                html.Th(header_map.get(c, c.replace("_", " ").title()), style=_TH)
                for c in cols
            ])),
            html.Tbody(rows),
        ], style={"width": "100%", "borderCollapse": "collapse"}),
        style={"overflowX": "auto"},
    )


def _build_recent_table_html(records, page):
    """Build html.Table for recently updated items from serialized records."""
    if not records:
        return html.Div("No recent activity found.",
                        style={"fontSize": "13px", "color": "#718096", "padding": "20px 0"})

    start = page * _PAGE_SIZE
    sliced = records[start: start + _PAGE_SIZE]
    header_map = {"work_item_id": "ID", "assigned_to": "Owner"}
    _plain_cols = {"team", "function", "area"}
    cols = list(sliced[0].keys()) if sliced else []

    rows = []
    for row in sliced:
        item_id_raw = row.get("work_item_id")
        cells = []
        for c in cols:
            v = row.get(c)
            is_na = v is None or (isinstance(v, float) and math.isnan(v))
            if c == "work_item_id":
                cells.append(html.Td(
                    html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                           style={"color": "#7c6af4", "fontWeight": "600",
                                  "textDecoration": "none", "fontSize": "12px"})
                    if not is_na else "—", style=_TD))
            elif c == "title":
                cells.append(html.Td(str(v)[:80] if not is_na else "—",
                    style={**_TD, "maxWidth": "200px", "overflow": "hidden",
                           "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
            elif c == "state":
                cells.append(html.Td(_state_pill(v) if not is_na else "—", style=_TD))
            elif c == "priority":
                cells.append(html.Td(_priority_pill(v), style=_TD))
            elif c == "assigned_to":
                cells.append(html.Td(str(v) if not is_na else "—", style=_TD))
            elif c == "type":
                cells.append(html.Td(_type_pill(v), style=_TD))
            elif c in _plain_cols:
                cells.append(html.Td(str(v) if not is_na else "—",
                    style={**_TD, "color": "#8888aa"}))
            else:
                cells.append(html.Td(str(v) if not is_na else "—",
                    style={**_TD, "color": "#8888aa"}))
        rows.append(html.Tr(cells))

    return html.Div(
        html.Table([
            html.Thead(html.Tr([
                html.Th(header_map.get(c, c.replace("_", " ").title()), style=_TH)
                for c in cols
            ])),
            html.Tbody(rows),
        ], style={"width": "100%", "borderCollapse": "collapse"}),
        style={"overflowX": "auto"},
    )


# ── Treemap drilldown callback ─────────────────────────────────────────────────
@callback(
    Output("sum-type-donut",          "figure"),
    Output("sum-treemap-path",        "data"),
    Output("sum-treemap-breadcrumb",  "children"),
    Output("sum-treemap-back",        "style"),
    Input("sum-tree-data",            "data"),
    Input("sum-type-donut",           "clickData"),
    Input("sum-treemap-back",         "n_clicks"),
    State("sum-treemap-path",         "data"),
    prevent_initial_call=False,
)
def drill_treemap(tree_data, click_data, _back_clicks, path):
    triggered = ctx.triggered_id

    if not tree_data:
        return go.Figure(), [], "", {"display": "none"}

    df_tree = pd.DataFrame(tree_data)
    has_area = "Area" in df_tree.columns

    # ── Determine new path ────────────────────────────────────────────────────
    if triggered == "sum-tree-data":
        # Filters changed → reset to root
        path = []
    elif triggered == "sum-treemap-back" and path:
        path = path[:-1]
    elif triggered == "sum-type-donut" and click_data:
        label = click_data["points"][0].get("label", "")
        if not label:
            pass
        elif len(path) == 0 and has_area:
            path = [label]       # Type → drill to Area
        elif len(path) == 1 and has_area:
            path = path + [label]  # Area → drill to State
        # len==2 is leaf — no further drill

    # ── Build figure for current level ───────────────────────────────────────
    max_depth = 2 if has_area else 1

    if len(path) == 0:
        # Root: types
        agg = df_tree.groupby("Type")["Count"].sum().reset_index()
        fig = px.treemap(agg, path=["Type"], values="Count",
                         color="Type", color_discrete_map=TYPE_COLORS)
        crumb = ""
    elif len(path) == 1 and has_area:
        # Level 1: areas within a type
        filtered = df_tree[df_tree["Type"] == path[0]]
        agg = filtered.groupby("Area")["Count"].sum().reset_index()
        color = TYPE_COLORS.get(path[0], "#7c6af4")
        fig = px.treemap(agg, path=["Area"], values="Count",
                         color_discrete_sequence=[color])
        crumb = f"Work Type  ›  {path[0]}"
    else:
        # Level 2: states within a type + area (or type+state if no area)
        if has_area and len(path) == 2:
            filtered = df_tree[(df_tree["Type"] == path[0]) & (df_tree["Area"] == path[1])]
            agg = filtered.groupby("State")["Count"].sum().reset_index()
            crumb = f"Work Type  ›  {path[0]}  ›  {path[1]}"
        else:
            filtered = df_tree[df_tree["Type"] == path[0]]
            agg = filtered.groupby("State")["Count"].sum().reset_index()
            crumb = f"Work Type  ›  {path[0]}"
        color = TYPE_COLORS.get(path[0], "#7c6af4")
        fig = px.treemap(agg, path=["State"] if has_area else ["State"], values="Count",
                         color_discrete_sequence=[color])

    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{value:,}<br>%{percentRoot:.0%}",
        textfont=dict(size=14, color="white"),
        marker=dict(line=dict(color="rgba(8,8,18,0.55)", width=3)),
        hovertemplate="<b>%{label}</b><br>%{value:,} items (%{percentRoot:.1%})<extra></extra>",
        root_color="rgba(0,0,0,0)",
    )
    fig.update_layout(
        height=500,
        margin=dict(t=0, b=0, l=0, r=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#c8c8e0"),
        transition={"duration": 400, "easing": "cubic-in-out"},
    )

    back_style = {"fontSize": "11px", "padding": "2px 10px",
                  "display": "inline-block" if path else "none"}
    return fig, path, crumb, back_style


# ── P1 table render + pagination ───────────────────────────────────────────────
@callback(
    Output("sum-p1-table",     "children"),
    Output("sum-p1-page-info", "children"),
    Input("sum-p1-store",      "data"),
    Input("sum-p1-page",       "data"),
)
def render_p1_table(records, page):
    records = records or []
    page = page or 0
    total = len(records)
    total_pages = max(1, math.ceil(total / _PAGE_SIZE))
    page = min(page, total_pages - 1)
    info = f"Page {page + 1} of {total_pages}  ({total} items)"
    return _build_p1_table_html(records, page), info


@callback(
    Output("sum-p1-page", "data", allow_duplicate=True),
    Input("sum-p1-prev",  "n_clicks"),
    Input("sum-p1-next",  "n_clicks"),
    State("sum-p1-page",  "data"),
    State("sum-p1-store", "data"),
    prevent_initial_call=True,
)
def paginate_p1(prev_clicks, next_clicks, page, records):
    total = len(records or [])
    total_pages = max(1, math.ceil(total / _PAGE_SIZE))
    page = page or 0
    if ctx.triggered_id == "sum-p1-prev":
        page = max(0, page - 1)
    else:
        page = min(total_pages - 1, page + 1)
    return page


# ── Recent table render + pagination ──────────────────────────────────────────
@callback(
    Output("sum-recent-table",     "children"),
    Output("sum-recent-page-info", "children"),
    Input("sum-recent-store",      "data"),
    Input("sum-recent-page",       "data"),
)
def render_recent_table(records, page):
    records = records or []
    page = page or 0
    total = len(records)
    total_pages = max(1, math.ceil(total / _PAGE_SIZE))
    page = min(page, total_pages - 1)
    info = f"Page {page + 1} of {total_pages}  ({total} items)"
    return _build_recent_table_html(records, page), info


@callback(
    Output("sum-recent-page", "data", allow_duplicate=True),
    Input("sum-recent-prev",  "n_clicks"),
    Input("sum-recent-next",  "n_clicks"),
    State("sum-recent-page",  "data"),
    State("sum-recent-store", "data"),
    prevent_initial_call=True,
)
def paginate_recent(prev_clicks, next_clicks, page, records):
    total = len(records or [])
    total_pages = max(1, math.ceil(total / _PAGE_SIZE))
    page = page or 0
    if ctx.triggered_id == "sum-recent-prev":
        page = max(0, page - 1)
    else:
        page = min(total_pages - 1, page + 1)
    return page
