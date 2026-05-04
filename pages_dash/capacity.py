"""Capacity Planning Dashboard — utilisation, accuracy, throughput, workload & forecasting"""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback, MATCH, ALL, no_update, ctx, dash_table
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data, apply_filters, filter_activity_since, update_db_workitem
from config.settings import ANALYSIS_START_DATE, ADO_BASE_URL
from config.team_mapping import TEAM_MAPPING
from reports.summarizer import summarize_capacity
from reports.formatter import format_report
from reports.recommendations import get_recommendations_capacity
from reports.rec_display import rec_strip
from sync.ado_write import write_fields, write_iteration
from db.platform_ops import (
    get_active_users, get_capacity_summary,
    get_iteration_capacity, upsert_iteration_capacity,
    get_tasks_for_iteration, get_all_iterations_from_features,
    get_all_items_for_iteration,
)

dash.register_page(__name__, path="/capacity", name="Capacity")

COMPLETED_STATES = ["Closed"]
OVERBURDEN_RATIO = 1.1

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
    "cleanup": ("2025-09-11", "2025-09-12"),
    "Iteration 2025 10-October":   ("2025-10-01", "2025-10-31"),
    "Iteration 2025 11-November":  ("2025-11-01", "2025-11-30"),
    "Iteration 2025 12-December":  ("2025-12-01", "2025-12-31"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _business_days(start, end):
    if pd.isna(start) or pd.isna(end) or start > end:
        return 0
    rng = pd.date_range(start.normalize(), end.normalize(), freq="D")
    return int(np.sum(rng.weekday < 5))


def _add_bdays(start, days, max_days=3650):
    days = min(int(days), max_days)
    if days <= 0:
        return start
    cur, added = start, 0
    while added < days:
        cur += pd.Timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def get_iteration_bdays(iteration_name):
    if not iteration_name or pd.isna(iteration_name):
        return 20
    if iteration_name in ITERATION_DATES:
        st, en = ITERATION_DATES[iteration_name]
        return _business_days(pd.to_datetime(st), pd.to_datetime(en))
    s = str(iteration_name)
    if "Iteration " in s and "-" in s:
        try:
            parts = s.split(" ")
            year  = int(parts[1])
            if year >= 2026:
                month = int(parts[2].split("-")[0])
                start = pd.Timestamp(year=year, month=month, day=1)
                end   = start + pd.offsets.MonthEnd(1)
                return _business_days(start, end)
        except Exception:
            pass
    return 20


def _strip_iter(x):
    if pd.notna(x) and str(x) not in ("Not Specified", ""):
        return str(x).split("\\")[-1]
    return x


def _section_label(text):
    return html.Div([
        html.Div(style={
            "display": "inline-block", "width": "3px", "height": "14px",
            "borderRadius": "2px", "background": "#7c6af4",
            "verticalAlign": "middle", "marginRight": "8px",
        }),
        html.Span(text),
    ], style={
        "fontSize": "13px", "fontWeight": "700", "textTransform": "uppercase",
        "letterSpacing": "0.7px", "color": "#c8c8e0", "marginBottom": "14px",
        "marginTop": "4px", "display": "flex", "alignItems": "center",
    })


def _empty_fig(msg="No data"):
    return go.Figure().update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_visible=False, yaxis_visible=False,
        annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                          font=dict(size=14, color="#a0aec0"))],
    )


def _planner_nav_btn(section_id, icon, label, active=False):
    """Sidebar navigation button for the planner sections."""
    return html.Div(
        [
            html.Div(icon, style={"fontSize": "18px", "lineHeight": "1"}),
            html.Div(label, style={"fontSize": "10px", "fontWeight": "600",
                                   "letterSpacing": "0.3px", "marginTop": "3px"}),
        ],
        id={"type": "pl-nav-btn", "index": section_id},
        n_clicks=0,
        className="pl-nav-btn" + (" pl-nav-btn--active" if active else ""),
    )


_MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "februari": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _parse_release_dates(name):
    """Parse '2025 April' or '2025 April Hotfix' → (start, end) Timestamps or (None, None)."""
    import re
    parts = str(name).strip().split()
    if len(parts) < 2:
        return None, None
    try:
        year  = int(parts[0])
        month = _MONTH_MAP.get(parts[1].lower())
        if not month:
            return None, None
        is_hotfix = any(p.lower() in ("hotfix", "hotfix2", "2nd") for p in parts[2:])
        if is_hotfix:
            # Hotfix: ~3 weeks into month, 2-week window
            start = pd.Timestamp(year=year, month=month, day=15)
            end   = start + pd.Timedelta(weeks=2)
        else:
            start = pd.Timestamp(year=year, month=month, day=1)
            end   = start + pd.offsets.MonthEnd(1)
        return start, end
    except Exception:
        return None, None


def _build_iter_path_map(df):
    """Return dict mapping short iteration name → full ADO iteration path."""
    if "iteration_path" not in df.columns:
        return {}
    mapping = {}
    for full_path in df["iteration_path"].dropna().unique():
        short = str(full_path).split("\\")[-1]
        if short not in ("Not Specified", ""):
            mapping[short] = str(full_path)
    return mapping


# ── Table cell styles (used by matrix drill modal) ────────────────────────────
_TH_CAP = {
    "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
    "letterSpacing": "0.5px", "color": "#8892a4",
    "padding": "8px 12px", "borderBottom": "1px solid rgba(255,255,255,0.08)",
    "textAlign": "left", "whiteSpace": "nowrap",
}
_TD_CAP = {
    "fontSize": "12px", "padding": "9px 12px",
    "borderBottom": "1px solid rgba(255,255,255,0.04)",
    "color": "#c8c8e0", "verticalAlign": "middle",
}


def _dt_style():
    """Shared dark-theme style for DataTable components."""
    return dict(
        style_table={"overflowX": "auto", "borderRadius": "8px",
                     "border": "1px solid rgba(255,255,255,0.06)"},
        style_header={"backgroundColor": "#0e0e1a", "color": "#94a3b8",
                      "fontWeight": "600", "fontSize": "11px",
                      "border": "1px solid rgba(255,255,255,0.06)",
                      "textTransform": "uppercase", "letterSpacing": "0.5px"},
        style_cell={"backgroundColor": "#09090f", "color": "#e2e8f0",
                    "fontSize": "12px", "border": "1px solid rgba(255,255,255,0.04)",
                    "padding": "8px 12px", "fontFamily": "Inter, sans-serif"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "rgba(255,255,255,0.015)"},
            {"if": {"state": "selected"},
             "backgroundColor": "rgba(129,140,248,0.15)",
             "border": "1px solid rgba(129,140,248,0.4)"},
        ],
        page_size=20,
        row_selectable="multi",
        selected_rows=[],
        filter_action="native",
        sort_action="native",
    )


# ── Layout ────────────────────────────────────────────────────────────────────
def layout():
    df = load_data()

    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    if "main_developer" in df.columns:
        df["main_developer"] = df["main_developer"].astype(str).str.split(" <").str[0]

    person_col = "main_developer" if "main_developer" in df.columns else "assigned_to"

    teams     = (["All"] + sorted([t for t in df["main_dev_team"].dropna().unique() if t != "Unassigned"])
                 if "main_dev_team" in df.columns else ["All"])
    employees = (["All"] + sorted(df[person_col].replace("", pd.NA).dropna().unique().tolist())
                 if person_col in df.columns else ["All"])
    iters     = sorted(
        [i for i in df["iteration_path"].dropna().unique()
         if i not in ("Not Specified", "")],
        reverse=True,
    ) if "iteration_path" in df.columns else []

    _fb = {
        "background": "#1c1c27", "borderRadius": "10px", "padding": "14px 18px",
        "border": "1px solid rgba(255,255,255,0.07)",
        "marginBottom": "20px",
    }
    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([
                html.Div("Team", className="filter-label"),
                dcc.Dropdown(id="cap-team",
                             options=[{"label": t, "value": t} for t in teams],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Developer", className="filter-label"),
                dcc.Dropdown(id="cap-employee",
                             options=[{"label": e, "value": e} for e in employees],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Iteration", className="filter-label"),
                dcc.Dropdown(id="cap-iteration",
                             options=[{"label": i, "value": i} for i in iters],
                             value=[], multi=True, placeholder="All",
                             style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Hours / person / day", className="filter-label"),
                dcc.Slider(id="cap-hours-day", min=4, max=12, step=1, value=8,
                           marks={4: "4", 6: "6", 8: "8", 10: "10", 12: "12"},
                           tooltip={"placement": "bottom", "always_visible": False}),
            ], md=2),
            dbc.Col([
                html.Div("Lookback (wks)", className="filter-label"),
                dcc.Slider(id="cap-lookback", min=2, max=12, step=1, value=4,
                           marks={2: "2", 4: "4", 8: "8", 12: "12"},
                           tooltip={"placement": "bottom", "always_visible": False}),
            ], md=1),
        ], className="g-2"),
    ], style=_fb)

    _sb = {
        "background": "rgba(255,255,255,0.015)",
        "borderRadius": "12px",
        "border": "1px solid rgba(255,255,255,0.04)",
        "padding": "20px 20px 12px 20px",
        "marginBottom": "24px",
    }

    cap_report_modal = dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("📄 Capacity Planning Report"), close_button=True),
        dbc.ModalBody(
            html.Div(id="cap-report-body",
                     style={"maxHeight": "70vh", "overflowY": "auto", "padding": "4px 8px"}),
        ),
        dbc.ModalFooter(
            html.Span(id="cap-report-ts", style={"fontSize": "11px", "color": "#8892a4"}),
        ),
    ], id="cap-report-modal", is_open=False, size="xl", backdrop="static",
       style={"--bs-modal-bg": "#13131f", "color": "#e2e8f0"})

    _pl = {
        "background": "rgba(255,255,255,0.015)", "borderRadius": "12px",
        "border": "1px solid rgba(255,255,255,0.04)",
        "padding": "20px 20px 14px 20px", "marginBottom": "16px",
    }

    # ── Planner tab — ADO data, multi-section ─────────────────────────────────
    _iter_opts = [{"label": i, "value": i} for i in iters]

    import re as _re
    _release_opts = []
    if "release_date" in df.columns:
        _named_releases = sorted(
            [r for r in df["release_date"].dropna().unique()
             if _re.match(r"^\d{4}\s+[A-Za-z]", str(r))],
            reverse=True,
        )
        _release_opts = [{"label": r, "value": r} for r in _named_releases]

    # ── Section: Board ─────────────────────────────────────────────────────────
    board_section = html.Div([
        html.Div([
            _section_label("Work Item Board"),
            html.Div(id="cap-pl-task-board"),
        ], style=_pl),
        dbc.Row([
            dbc.Col(html.Div([
                _section_label("Item Breakdown"),
                dcc.Graph(id="cap-pl-breakdown", config={"displayModeBar": False}),
            ], style=_pl), md=4),
            dbc.Col(html.Div([
                _section_label("Iteration Burndown"),
                dcc.Graph(id="cap-pl-burndown", config={"displayModeBar": False}),
            ], style=_pl), md=8),
        ]),
        html.Div([
            _section_label("Workload by Person"),
            html.Div(id="cap-pl-workload"),
        ], style=_pl),
        html.Div([
            _section_label("Red Flags & Attention"),
            html.Div(id="cap-pl-redflags"),
        ], style=_pl),
    ], id="cap-pl-board-section")

    # ── Section: Item Adjuster ─────────────────────────────────────────────────
    adjuster_section = html.Div([

        # Filter strip
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Div("View", className="filter-label"),
                    dbc.RadioItems(
                        id="cap-adj-view-mode",
                        options=[
                            {"label": "🔄 Iteration", "value": "iteration"},
                            {"label": "📦 Release",   "value": "release"},
                        ],
                        value="iteration", inline=True,
                        style={"fontSize": "12px"},
                    ),
                ], md=2),
                dbc.Col(html.Div([
                    html.Div("Iteration", className="filter-label"),
                    dcc.Dropdown(id="cap-adj-iter", options=_iter_opts,
                                 placeholder="Select iteration…", clearable=True,
                                 style={"fontSize": "12px"}),
                ], id="cap-adj-iter-wrap"), md=3),
                dbc.Col(html.Div([
                    html.Div("Release", className="filter-label"),
                    dcc.Dropdown(id="cap-adj-release", options=_release_opts,
                                 placeholder="Select release…", clearable=True,
                                 style={"fontSize": "12px"}),
                ], id="cap-adj-release-wrap", style={"display": "none"}), md=3),
                dbc.Col([
                    html.Div("Team", className="filter-label"),
                    dcc.Dropdown(id="cap-adj-team",
                                 options=[{"label": t, "value": t} for t in teams],
                                 value="All", clearable=False,
                                 style={"fontSize": "12px"}),
                ], md=2),
                dbc.Col([
                    html.Div("Group By", className="filter-label"),
                    dcc.Dropdown(
                        id="cap-adj-groupby",
                        options=[
                            {"label": "👤 Person",   "value": "person"},
                            {"label": "🏷️ Type",    "value": "type"},
                            {"label": "⚡ State",    "value": "state"},
                            {"label": "🗂️ Area",    "value": "function"},
                        ],
                        value="person", clearable=False,
                        style={"fontSize": "12px"},
                    ),
                ], md=2),
            ], className="g-2"),
        ], style={"background": "#1c1c27", "borderRadius": "10px",
                  "padding": "14px 18px", "border": "1px solid rgba(255,255,255,0.07)",
                  "marginBottom": "14px"}),

        # KPI chips
        html.Div(id="cap-adj-kpis",
                 style={"display": "flex", "gap": "8px", "flexWrap": "wrap",
                        "marginBottom": "14px"}),

        # Delivery timeline Gantt (items as bars)
        html.Div([
            _section_label("Delivery Timeline"),
            html.Div([
                html.Span("Each row = one group across time. Bar = items in that window. ",
                          style={"fontSize": "11px", "color": "#475569"}),
                html.Span("■ On track  ", style={"fontSize": "11px", "color": "#34d399"}),
                html.Span("■ At risk  ",  style={"fontSize": "11px", "color": "#fbbf24"}),
                html.Span("■ Over-cap / Delay risk",
                          style={"fontSize": "11px", "color": "#f87171"}),
            ], style={"marginBottom": "8px"}),
            dcc.Graph(id="cap-adj-gantt",
                      config={"displayModeBar": True,
                              "modeBarButtonsToRemove": ["select2d", "lasso2d"]}),
        ], style=_pl),

        # Breakdown + Burndown row
        dbc.Row([
            dbc.Col(html.Div([
                _section_label("Item Breakdown"),
                dcc.Graph(id="cap-adj-breakdown", config={"displayModeBar": False}),
            ], style=_pl), md=4),
            dbc.Col(html.Div([
                _section_label("Burndown"),
                dcc.Graph(id="cap-adj-burndown", config={"displayModeBar": False}),
            ], style=_pl), md=8),
        ]),

        # Workload by person
        html.Div([
            _section_label("Workload by Person"),
            html.Div(id="cap-adj-workload"),
        ], style=_pl),

        # Capacity matrix
        html.Div([
            _section_label("Capacity Matrix"),
            dbc.Row([
                dbc.Col([
                    html.Div("Hours / person / day", className="filter-label"),
                    dcc.Slider(id="cap-adj-hours-day", min=4, max=10, step=1, value=8,
                               marks={4: "4h", 6: "6h", 8: "8h", 10: "10h"},
                               tooltip={"placement": "bottom", "always_visible": False}),
                ], md=4),
            ], className="mb-3"),
            html.Div(id="cap-adj-cap-matrix"),
        ], style=_pl),

        # Move items
        html.Div([
            _section_label("Move Items"),
            html.P(
                "Items from the selected scope. Select rows and assign to a new iteration.",
                style={"fontSize": "12px", "color": "#64748b", "marginBottom": "12px"},
            ),
            dbc.Row([
                dbc.Col([
                    html.Div("Target Iteration", className="filter-label"),
                    dcc.Dropdown(id="cap-adj-move-tgt", options=_iter_opts,
                                 placeholder="Target iteration…", clearable=True,
                                 style={"fontSize": "12px"}),
                ], md=5),
                dbc.Col([
                    html.Div("\u00a0", className="filter-label"),
                    dbc.Button("Move Selected \u2192", id="cap-adj-move-btn",
                               disabled=True, size="sm",
                               style={"width": "100%",
                                      "background": "rgba(129,140,248,0.15)",
                                      "border": "1px solid rgba(129,140,248,0.3)",
                                      "color": "#818cf8", "fontWeight": "600"}),
                ], md=2),
            ], className="g-2 mb-2"),
            html.Div(id="cap-adj-move-feedback",
                     style={"fontSize": "12px", "minHeight": "20px", "marginBottom": "8px"}),
            html.Div(id="cap-adj-move-table-container"),
        ], style=_pl),

    ], id="cap-pl-adjuster-section", style={"display": "none"})

    # ── Section: Backlog ───────────────────────────────────────────────────────
    backlog_section = html.Div([
        html.P("Items with no iteration assigned. Select rows and assign to an iteration via ADO.",
               style={"fontSize": "12px", "color": "#64748b", "marginBottom": "14px"}),
        dbc.Row([
            dbc.Col([
                html.Div("Assign to Iteration", className="filter-label"),
                dcc.Dropdown(id="cap-pl-backlog-tgt", options=_iter_opts,
                             placeholder="Target iteration…", clearable=True,
                             style={"fontSize": "12px"}),
            ], md=5),
            dbc.Col([
                html.Div("\u00a0", className="filter-label"),
                dbc.Button("Assign Selected →", id="cap-pl-backlog-btn",
                           disabled=True, size="sm",
                           style={"width": "100%", "background": "rgba(52,211,153,0.12)",
                                  "border": "1px solid rgba(52,211,153,0.3)",
                                  "color": "#34d399", "fontWeight": "600"}),
            ], md=2),
        ], className="g-2 mb-2"),
        html.Div(id="cap-pl-backlog-feedback",
                 style={"fontSize": "12px", "minHeight": "20px", "marginBottom": "8px"}),
        html.Div(id="cap-pl-backlog-table-container"),
    ], id="cap-pl-backlog-section", style=_pl | {"display": "none"})

    # ── Planner content ────────────────────────────────────────────────────────
    planner_content = html.Div([
        # Top strip: filters + KPIs
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Div("Iteration", className="filter-label"),
                    dcc.Dropdown(
                        id="cap-planner-iter",
                        options=_iter_opts,
                        placeholder="Select an iteration…",
                        clearable=True,
                        style={"fontSize": "12px"},
                    ),
                ], md=4),
                dbc.Col([
                    html.Div("Team", className="filter-label"),
                    dcc.Dropdown(
                        id="cap-pl-team",
                        options=[{"label": t, "value": t} for t in teams],
                        value="All", clearable=False,
                        style={"fontSize": "12px"},
                    ),
                ], md=3),
                dbc.Col([
                    html.Div("Person", className="filter-label"),
                    dcc.Dropdown(
                        id="cap-pl-person",
                        options=[{"label": e, "value": e} for e in employees],
                        value="All", clearable=False,
                        style={"fontSize": "12px"},
                    ),
                ], md=3),
                dbc.Col([
                    html.Div("Type", className="filter-label"),
                    dcc.Dropdown(
                        id="cap-pl-type",
                        options=[{"label": t, "value": t} for t in
                                 sorted(df["work_item_type"].dropna().unique()
                                        if "work_item_type" in df.columns else [])],
                        placeholder="All types",
                        multi=True, clearable=True,
                        style={"fontSize": "12px"},
                    ),
                ], md=2),
            ], className="g-2 mb-2"),
            html.Div(id="cap-pl-kpis",
                     style={"display": "flex", "gap": "8px", "flexWrap": "wrap",
                            "marginTop": "8px"}),
        ], style={"background": "#1c1c27", "borderRadius": "10px",
                  "padding": "14px 18px", "border": "1px solid rgba(255,255,255,0.07)",
                  "marginBottom": "16px"}),

        # Sidebar + content
        html.Div([
            # ── Left sidebar ──────────────────────────────────────────────
            html.Div([
                _planner_nav_btn("board",    "📋", "Board",    active=True),
                _planner_nav_btn("adjuster", "🎯", "Adjuster"),
                _planner_nav_btn("backlog",  "📌", "Backlog"),
            ], id="cap-pl-sidebar",
               style={"width": "80px", "minWidth": "80px", "display": "flex",
                      "flexDirection": "column", "gap": "6px",
                      "paddingRight": "16px",
                      "borderRight": "1px solid rgba(255,255,255,0.06)"}),

            # ── Main content ──────────────────────────────────────────────
            html.Div([
                board_section,
                adjuster_section,
                backlog_section,
            ], style={"flex": "1", "minWidth": "0"}),
        ], style={"display": "flex", "gap": "16px"}),

        # Active section store
        dcc.Store(id="cap-pl-active-section", data="board"),

        # Person drill-down modal
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle("", id="cap-pl-person-modal-title"),
                close_button=True,
            ),
            dbc.ModalBody(
                html.Div(id="cap-pl-person-modal-body",
                         style={"maxHeight": "65vh", "overflowY": "auto", "padding": "4px 8px"}),
            ),
        ], id="cap-pl-person-modal", is_open=False, size="xl",
           style={"--bs-modal-bg": "#13131f", "color": "#e2e8f0"}),

        # Capacity matrix drill-down modal
        dbc.Modal([
            dbc.ModalHeader(
                dbc.ModalTitle("", id="cap-matrix-drill-title"),
                close_button=True,
            ),
            dbc.ModalBody([
                html.Div(id="cap-adj-writeback-status",
                         style={"minHeight": "20px", "fontSize": "12px",
                                "padding": "4px 0 2px 0"}),
                html.Div(id="cap-matrix-drill-body",
                         style={"maxHeight": "65vh", "overflowY": "auto",
                                "padding": "4px 8px"}),
            ]),
        ], id="cap-matrix-drill-modal", is_open=False, size="xl",
           style={"--bs-modal-bg": "#13131f", "color": "#e2e8f0"}),
    ], style={"paddingTop": "16px"})

    # ── Audit tab ─────────────────────────────────────────────────────────────
    audit_content = html.Div([
        filter_bar,
        html.Div(id="cap-rec-strip"),
        html.Div(id="cap-overburden-alert", className="mb-3"),
        html.Div([
            _section_label("At a Glance"),
            html.Div(id="cap-kpi-row"),
        ], style=_sb),
        html.Div([
            _section_label("Team Utilisation & Workload"),
            html.Div(dcc.Graph(id="cap-team-multibar"), className="chart-card mb-3"),
            html.Div(dcc.Graph(id="cap-team-util"),     className="chart-card"),
        ], style=_sb),
        html.Div([
            _section_label("Individual Utilisation"),
            html.Div(dcc.Graph(id="cap-person-util"), className="chart-card"),
        ], style=_sb),
        html.Div([
            _section_label("Iteration Capacity vs Commitment"),
            html.P("Compare hours committed (Original Estimate) vs available capacity per iteration. "
                   "Red bars = over-committed.",
                   style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
            html.Div(dcc.Graph(id="cap-iter-capacity"), className="chart-card"),
        ], style=_sb),
        html.Div([
            _section_label("Estimation Accuracy"),
            html.Div(dcc.Graph(id="cap-acc-team"), className="chart-card mb-3"),
            html.Div(dcc.Graph(id="cap-acc-emp"),  className="chart-card"),
        ], style=_sb),
        html.Div([
            _section_label("Estimation Accuracy Trend"),
            html.P("Is the team getting better at estimating over time?",
                   style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
            html.Div(dcc.Graph(id="cap-acc-trend"), className="chart-card"),
        ], style=_sb),
        html.Div([
            _section_label("Throughput & WIP"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(id="cap-throughput"), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(id="cap-wip"),        className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),
        html.Div([
            _section_label("Completion Rate by Item Type"),
            html.P("What % of each item type actually gets completed in this period.",
                   style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
            html.Div(dcc.Graph(id="cap-completion-rate"), className="chart-card"),
        ], style=_sb),
        html.Div([
            _section_label("Employee Workload Detail"),
            html.Div(dcc.Graph(id="cap-dotplot"), className="chart-card"),
        ], style=_sb),
        html.Div([
            _section_label("Delivery Forecast"),
            html.Div(id="cap-forecast-card"),
        ], style=_sb),
        cap_report_modal,
    ], style={"paddingTop": "16px"})

    _tab_lbl  = {"color": "#94a3b8", "fontSize": "13px", "fontWeight": "600"}
    _tab_albl = {"color": "#818cf8", "fontSize": "13px", "fontWeight": "600"}

    return html.Div([
        html.Div([
            html.Div([
                html.H1("📈 Capacity Planning", className="page-title"),
                html.P("Planner — current & upcoming iterations  ·  Audit — historical ADO analytics.",
                       className="page-subtitle"),
            ]),
            dbc.Button("📄 Board Report", id="cap-report-btn", size="sm",
                       style={"background": "rgba(129,140,248,0.15)", "border": "1px solid rgba(129,140,248,0.3)",
                              "color": "#818cf8", "fontWeight": "600", "alignSelf": "center"}),
        ], className="page-header",
           style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}),

        dbc.Tabs([
            dbc.Tab(planner_content, label="🗓 Planner", tab_id="tab-planner",
                    label_style=_tab_lbl, active_label_style=_tab_albl),
            dbc.Tab(audit_content,   label="📊 Audit",   tab_id="tab-audit",
                    label_style=_tab_lbl, active_label_style=_tab_albl),
        ], id="cap-tabs", active_tab="tab-planner",
           style={"borderBottom": "1px solid rgba(255,255,255,0.07)", "marginBottom": "4px"}),
    ])


# ── Callback ──────────────────────────────────────────────────────────────────
@callback(
    Output("cap-overburden-alert", "children"),
    Output("cap-kpi-row",          "children"),
    Output("cap-team-multibar",    "figure"),
    Output("cap-team-util",        "figure"),
    Output("cap-person-util",      "figure"),
    Output("cap-iter-capacity",    "figure"),
    Output("cap-acc-team",         "figure"),
    Output("cap-acc-emp",          "figure"),
    Output("cap-acc-trend",        "figure"),
    Output("cap-throughput",       "figure"),
    Output("cap-wip",              "figure"),
    Output("cap-completion-rate",  "figure"),
    Output("cap-dotplot",          "figure"),
    Output("cap-forecast-card",    "children"),
    Input("cap-team",      "value"),
    Input("cap-employee",  "value"),
    Input("cap-iteration", "value"),
    Input("cap-hours-day", "value"),
    Input("cap-lookback",  "value"),
)
def update_capacity(team, employee, iterations, hours_day, lookback):
    df = load_data()
    # Strip iteration paths BEFORE filtering so dropdown values (stripped) match
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    # Filter by main_dev_team (not assigned_to team) so capacity reflects who built it
    df = apply_filters(df, employee=employee, iterations=iterations)
    if team and team != "All" and "main_dev_team" in df.columns:
        df = df[df["main_dev_team"] == team]
    df = filter_activity_since(df, ANALYSIS_START_DATE)

    # Exclude parent containers to avoid double-counting with child Tasks.
    # Root/Middle items with completed_work=0 are new-style containers whose
    # children (Leaf Tasks) are already in the dataset.
    if "hierarchy_type" in df.columns:
        cw = pd.to_numeric(df.get("completed_work", 0), errors="coerce").fillna(0)
        is_container = df["hierarchy_type"].isin(["Root", "Middle"]) & (cw == 0)
        df = df[~is_container]

    # 2026+ iterations use task-bound practice — only count Tasks to avoid
    # double-counting estimates on parent bugs/enhancements and their tasks.
    # Pre-2026 data had no task creation habit so we keep all item types there.
    def _is_2026_iteration(iter_name):
        s = str(iter_name)
        return "2026" in s or s.startswith("Iteration 2026")

    if iterations and all(_is_2026_iteration(i) for i in iterations):
        # All selected iterations are 2026 → tasks-only
        df = df[df["work_item_type"] == "Task"]
    elif not iterations and "iteration_path" in df.columns:
        # No filter selected — split: 2026 iterations keep tasks only,
        # pre-2026 iterations keep everything (old practice)
        mask_2026 = df["iteration_path"].apply(lambda x: _is_2026_iteration(x) if pd.notna(x) else False)
        df_pre2026  = df[~mask_2026]
        df_2026     = df[mask_2026 & (df["work_item_type"] == "Task")]
        df = pd.concat([df_pre2026, df_2026], ignore_index=True)

    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    if "main_developer" in df.columns:
        df["main_developer"] = df["main_developer"].astype(str).str.split(" <").str[0]

    # Use main_developer as the authoritative person field; fall back to assigned_to
    person_field = "main_developer" if "main_developer" in df.columns else "assigned_to"

    def num(col, src=None):
        src = src if src is not None else df
        return pd.to_numeric(src.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0)

    today = pd.Timestamp.today().normalize()

    # ── Core totals ───────────────────────────────────────────────────────────
    assigned      = num("original_estimate").sum()
    completed     = num("completed_work").sum()
    remaining     = max(assigned - completed, 0)
    active_iters  = df["iteration_path"].dropna().unique().tolist() if "iteration_path" in df.columns else []
    unique_people = df[person_field].dropna().nunique() if person_field in df.columns else 0

    if iterations:
        total_bdays      = sum(get_iteration_bdays(i) for i in active_iters)
        workdays_display = f"{total_bdays} days"
    else:
        cd = pd.to_datetime(df.get("created_date", pd.Series(dtype="datetime64[ns]")), errors="coerce").dropna()
        total_bdays      = _business_days(cd.min(), cd.max()) if not cd.empty else 20
        workdays_display = f"~{total_bdays} days"

    total_cap = unique_people * total_bdays * hours_day
    util      = assigned / total_cap * 100 if total_cap > 0 else 0
    acc       = completed / assigned * 100 if assigned > 0 else 0

    util_color = "danger" if util > 120 else ("warning" if util >= 90 else "")
    acc_color  = "" if 80 <= acc <= 110 else ("warning" if 70 <= acc < 80 else "danger")

    def _kpi(label, val, cls="", subtitle=None):
        children = [
            html.Div(label, className="metric-label"),
            html.Div(val, className=f"metric-value {cls}"),
        ]
        if subtitle:
            children.append(html.Div(subtitle, className="kpi-subtitle"))
        return dbc.Col(html.Div(children, className="metric-card"), md=3)

    kpi_row = html.Div([
        dbc.Row([
            _kpi("Assigned (h)",  f"{assigned:,.0f}"),
            _kpi("Completed (h)", f"{completed:,.0f}", cls="success"),
            _kpi("Remaining (h)", f"{remaining:,.0f}",
                 cls="warning" if remaining > 0 else ""),
            _kpi("Utilisation %", f"{util:.1f}%", cls=util_color),
        ], className="g-3 mb-3"),
        dbc.Row([
            _kpi("Accuracy %",    f"{acc:.1f}%",    cls=acc_color,
                 subtitle="Completed ÷ assigned"),
            _kpi("People",        str(unique_people),
                 subtitle="Unique developers"),
            _kpi("Work Days",     workdays_display,
                 subtitle="In selected scope"),
            _kpi("Total Capacity", f"{total_cap:,.0f}h",
                 subtitle=f"{unique_people}p × {workdays_display} × {hours_day}h"),
        ], className="g-3"),
    ])

    # ── Overburden alert ──────────────────────────────────────────────────────
    overburden_div = html.Div()
    if {person_field, "original_estimate"}.issubset(df.columns):
        emp_hrs   = df.groupby(person_field).agg(
            assigned=("original_estimate", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum())
        ).reset_index()
        indiv_cap = (sum(get_iteration_bdays(i) for i in active_iters) if iterations else 20) * hours_day
        emp_hrs["over"] = emp_hrs["assigned"] > (indiv_cap * OVERBURDEN_RATIO)
        overburdened    = emp_hrs[emp_hrs["over"]].sort_values("assigned", ascending=False)
        if not overburdened.empty:
            names = ", ".join(overburdened[person_field].tolist()[:5])
            max_h = overburdened["assigned"].max()
            overburden_div = dbc.Alert([
                html.Strong(f"⚠️ {len(overburdened)} team member(s) are over-assigned. "),
                f"Max: {max_h:,.0f}h vs individual capacity {indiv_cap:,.0f}h.  ",
                f"Affected: {names}",
            ], color="danger",
               style={"padding": "10px 16px", "fontSize": "13px", "marginBottom": "8px"})

    # ── Team multi-bar ────────────────────────────────────────────────────────
    if {"main_dev_team", "original_estimate", "completed_work"}.issubset(df.columns):
        tm = df.copy()
        tm["orig"] = num("original_estimate", tm)
        tm["comp"] = num("completed_work",    tm)
        tm["rem"]  = (tm["orig"] - tm["comp"]).clip(lower=0)
        g = tm.groupby("main_dev_team")[["orig", "comp", "rem"]].sum().reset_index()
        melt = g.melt(id_vars="main_dev_team", var_name="Type", value_name="Hours").replace(
            {"orig": "Original Estimate", "comp": "Completed", "rem": "Remaining"})
        fig_tmb = px.bar(
            melt, x="main_dev_team", y="Hours", color="Type", barmode="group",
            title="Team: Original vs Completed vs Remaining",
            color_discrete_map={"Original Estimate": "#5a8fd4",
                                 "Completed": "#3d9e6b", "Remaining": "#c06060"},
            labels={"main_dev_team": "", "Hours": "Hours"},
        )
        fig_tmb.update_layout(
            height=450, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=90, b=100, l=60, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        fig_tmb.update_xaxes(tickangle=-35, tickfont=dict(size=13))
        fig_tmb.update_yaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
    else:
        fig_tmb = _empty_fig()

    # ── Team utilisation % ────────────────────────────────────────────────────
    if {"main_dev_team", "original_estimate"}.issubset(df.columns) and person_field in df.columns:
        grp = df.groupby("main_dev_team").agg(
            assigned=("original_estimate", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
            headcount=(person_field, lambda s: s.dropna().nunique()),
        ).reset_index()
        grp_bdays       = sum(get_iteration_bdays(i) for i in active_iters) if iterations else 20
        grp["capacity"] = grp["headcount"] * grp_bdays * hours_day
        grp["util_pct"] = np.where(grp["capacity"] > 0,
                                    grp["assigned"] / grp["capacity"] * 100, 0)
        grp = grp.sort_values("util_pct", ascending=True)
        fig_tu = go.Figure(go.Bar(
            x=grp["util_pct"], y=grp["main_dev_team"], orientation="h",
            marker_color=[
                "#c05050" if v > 110 else ("#c97d3a" if v >= 90 else "#3d9e6b")
                for v in grp["util_pct"]
            ],
            text=grp["util_pct"].apply(lambda x: f"{x:.0f}%"),
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        ))
        fig_tu.add_vline(x=100, line_dash="dash", line_color="#718096",
                         annotation_text="100%", annotation_position="top right",
                         annotation_font=dict(size=11))
        fig_tu.update_layout(
            title="Team Utilisation % (Assigned ÷ Capacity)",
            height=max(len(grp) * 42 + 120, 250),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=40, l=185, r=80),
        )
        fig_tu.update_xaxes(title="Utilisation %", gridcolor="rgba(255,255,255,0.06)",
                            ticksuffix="%", tickfont=dict(size=13))
        fig_tu.update_yaxes(tickfont=dict(size=13))
    else:
        fig_tu = _empty_fig()

    # ── Per-person utilisation % ──────────────────────────────────────────────
    if {person_field, "original_estimate"}.issubset(df.columns):
        indiv_bdays = (sum(get_iteration_bdays(i) for i in active_iters) if iterations else 20)
        indiv_cap   = indiv_bdays * hours_day

        emp_util = df.groupby(person_field).agg(
            assigned=("original_estimate", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
        ).reset_index()
        emp_util["capacity"] = indiv_cap
        emp_util["util_pct"] = np.where(
            emp_util["capacity"] > 0,
            emp_util["assigned"] / emp_util["capacity"] * 100, 0
        )
        emp_util = emp_util[emp_util["assigned"] > 0].sort_values("util_pct", ascending=True)

        if not emp_util.empty:
            fig_pu = go.Figure(go.Bar(
                x=emp_util["util_pct"], y=emp_util[person_field], orientation="h",
                marker_color=[
                    "#c05050" if v > 110 else ("#c97d3a" if v >= 90 else "#3d9e6b")
                    for v in emp_util["util_pct"]
                ],
                text=emp_util["util_pct"].apply(lambda x: f"{x:.0f}%"),
                textposition="outside", textfont=dict(size=10),
                customdata=emp_util["assigned"],
                hovertemplate="%{y}<br>Assigned: %{customdata:,.0f}h<br>Util: %{x:.1f}%<extra></extra>",
            ))
            fig_pu.add_vline(x=100, line_dash="dash", line_color="#718096",
                             annotation_text="100%", annotation_position="top right",
                             annotation_font=dict(size=11))
            fig_pu.update_layout(
                title=f"Individual Utilisation % (Assigned ÷ {indiv_cap:.0f}h capacity per person)",
                height=max(len(emp_util) * 42 + 120, 300),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=40, l=185, r=80),
            )
            fig_pu.update_xaxes(title="Utilisation %", gridcolor="rgba(255,255,255,0.06)",
                                ticksuffix="%", tickfont=dict(size=12))
            fig_pu.update_yaxes(tickfont=dict(size=12))
        else:
            fig_pu = _empty_fig("No estimation data per person")
    else:
        fig_pu = _empty_fig()

    # ── Iteration capacity comparison ─────────────────────────────────────────
    if {"iteration_path", "original_estimate"}.issubset(df.columns) and person_field in df.columns:
        it = df.copy()
        it["orig"] = num("original_estimate", it)
        iter_grp = it.groupby("iteration_path").agg(
            committed=("orig", "sum"),
            headcount=(person_field, lambda s: s.dropna().nunique()),
        ).reset_index().sort_values("iteration_path")
        iter_grp["bdays"]    = iter_grp["iteration_path"].apply(get_iteration_bdays)
        iter_grp["capacity"] = iter_grp["headcount"] * iter_grp["bdays"] * hours_day
        iter_grp["over"]     = iter_grp["committed"] > iter_grp["capacity"]

        iter_melt = pd.concat([
            iter_grp[["iteration_path", "committed"]].rename(
                columns={"committed": "Hours"}).assign(Type="Committed"),
            iter_grp[["iteration_path", "capacity"]].rename(
                columns={"capacity": "Hours"}).assign(Type="Capacity"),
        ])
        fig_iter = px.bar(
            iter_melt, x="iteration_path", y="Hours", color="Type", barmode="group",
            title="Committed Hours vs Available Capacity per Iteration",
            color_discrete_map={"Committed": "#c06060", "Capacity": "#3d9e6b"},
            labels={"iteration_path": "", "Hours": "Hours"},
        )
        fig_iter.update_layout(
            height=450, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=90, b=120, l=60, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        fig_iter.update_xaxes(tickangle=-35, tickfont=dict(size=13))
        fig_iter.update_yaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
    else:
        fig_iter = _empty_fig()

    # ── Estimation accuracy — by team ─────────────────────────────────────────
    if {"main_dev_team", "original_estimate", "completed_work"}.issubset(df.columns):
        d = df.copy()
        d["orig"] = num("original_estimate", d)
        d["comp"] = num("completed_work",    d)

        tea = d.groupby("main_dev_team")[["orig", "comp"]].sum().reset_index()
        tea["acc"] = np.where(tea["orig"] > 0, tea["comp"] / tea["orig"] * 100, np.nan)
        tea = tea.dropna(subset=["acc"]).sort_values("acc", ascending=True)

        if not tea.empty:
            fig_at = go.Figure(go.Bar(
                x=tea["acc"], y=tea["main_dev_team"], orientation="h",
                marker_color=[
                    "#c05050" if v < 70 else ("#c97d3a" if v < 85 else
                                              ("#3d9e6b" if v <= 115 else "#c97d3a"))
                    for v in tea["acc"]
                ],
                text=tea["acc"].apply(lambda x: f"{x:.0f}%"),
                textposition="outside", textfont=dict(size=11),
                hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
            ))
            fig_at.add_vline(x=100, line_dash="dash", line_color="#718096",
                             annotation_text="100%", annotation_position="top right",
                             annotation_font=dict(size=11))
            fig_at.update_layout(
                title="Estimation Accuracy % — by Team  (green = 85–115%, orange = off, red = <70%)",
                height=max(len(tea) * 42 + 120, 250),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=40, l=185, r=80),
            )
            fig_at.update_xaxes(title="Accuracy %", gridcolor="rgba(255,255,255,0.06)",
                                ticksuffix="%", tickfont=dict(size=13))
            fig_at.update_yaxes(tickfont=dict(size=13))
        else:
            fig_at = _empty_fig("No team estimation data")
    else:
        fig_at = _empty_fig()
        d = df.copy()

    # ── Estimation accuracy — by employee ─────────────────────────────────────
    if {person_field, "original_estimate", "completed_work"}.issubset(df.columns):
        if "d" not in dir():
            d = df.copy()
            d["orig"] = num("original_estimate", d)
            d["comp"] = num("completed_work",    d)

        emp = d.groupby(person_field)[["orig", "comp"]].sum().reset_index()
        emp["acc"] = np.where(emp["orig"] > 0, emp["comp"] / emp["orig"] * 100, np.nan)
        emp = emp.dropna(subset=["acc"]).sort_values("acc", ascending=True)

        if not emp.empty:
            fig_ae = go.Figure(go.Bar(
                x=emp["acc"], y=emp[person_field], orientation="h",
                marker_color=[
                    "#c05050" if v < 70 else ("#c97d3a" if v < 85 else
                                              ("#3d9e6b" if v <= 115 else "#c97d3a"))
                    for v in emp["acc"]
                ],
                text=emp["acc"].apply(lambda x: f"{x:.0f}%"),
                textposition="outside", textfont=dict(size=10),
                hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
            ))
            fig_ae.add_vline(x=100, line_dash="dash", line_color="#718096",
                             annotation_text="100%", annotation_position="top right",
                             annotation_font=dict(size=11))
            fig_ae.update_layout(
                title="Estimation Accuracy % — by Developer",
                height=max(len(emp) * 42 + 120, 300),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=40, l=185, r=80),
            )
            fig_ae.update_xaxes(title="Accuracy %", gridcolor="rgba(255,255,255,0.06)",
                                ticksuffix="%", tickfont=dict(size=13))
            fig_ae.update_yaxes(tickfont=dict(size=12))
        else:
            fig_ae = _empty_fig("No employee estimation data")
    else:
        fig_ae = _empty_fig()

    # ── Estimation accuracy trend by iteration ────────────────────────────────
    if {"iteration_path", "original_estimate", "completed_work"}.issubset(df.columns):
        it2 = df.copy()
        it2["orig"] = num("original_estimate", it2)
        it2["comp"] = num("completed_work",    it2)
        it_acc = it2.groupby("iteration_path")[["orig", "comp"]].sum().reset_index()
        it_acc["acc"] = np.where(it_acc["orig"] > 0,
                                  it_acc["comp"] / it_acc["orig"] * 100, np.nan)
        it_acc = it_acc.dropna(subset=["acc"]).sort_values("iteration_path")

        if not it_acc.empty:
            fig_acc_trend = px.line(
                it_acc, x="iteration_path", y="acc", markers=True,
                title="Estimation Accuracy % — Trend by Iteration",
                labels={"iteration_path": "", "acc": "Accuracy %"},
                color_discrete_sequence=["#5a8fd4"],
            )
            fig_acc_trend.add_hline(y=100, line_dash="dash", line_color="#3d9e6b",
                                    annotation_text="Perfect (100%)",
                                    annotation_font=dict(size=11))
            fig_acc_trend.add_hrect(y0=85, y1=115, fillcolor="#3d9e6b", opacity=0.06,
                                    line_width=0,
                                    annotation_text="Target zone",
                                    annotation_position="right",
                                    annotation_font=dict(size=10, color="#3d9e6b"))
            fig_acc_trend.update_layout(
                height=450, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=120, l=60, r=20),
            )
            fig_acc_trend.update_xaxes(tickangle=-35, tickfont=dict(size=13))
            fig_acc_trend.update_yaxes(title="Accuracy %", gridcolor="rgba(255,255,255,0.06)",
                                       ticksuffix="%", tickfont=dict(size=13))
        else:
            fig_acc_trend = _empty_fig("No iteration accuracy data")
    else:
        fig_acc_trend = _empty_fig()

    # ── Throughput (completed hours/week) ─────────────────────────────────────
    if "closed_date" in df.columns and "completed_work" in df.columns:
        d2 = df.dropna(subset=["closed_date"]).copy()
        d2["week"] = pd.to_datetime(d2["closed_date"], errors="coerce").dt.to_period("W").dt.start_time
        d2["comp"] = num("completed_work", d2)
        thr = d2.groupby("week")["comp"].sum().reset_index()
        if not thr.empty:
            fig_tp = px.line(
                thr, x="week", y="comp", markers=True,
                title="Completed Hours Per Week (Throughput)",
                color_discrete_sequence=["#5a8fd4"],
                labels={"week": "", "comp": "Hours"},
            )
            fig_tp.update_layout(
                height=400, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=80, l=60, r=20),
            )
            fig_tp.update_xaxes(tickangle=-35, tickfont=dict(size=12))
            fig_tp.update_yaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12))
        else:
            fig_tp = _empty_fig("No throughput data")
    else:
        fig_tp = _empty_fig()

    # ── WIP trend ─────────────────────────────────────────────────────────────
    if {"created_date", "closed_date"}.issubset(df.columns):
        d3 = df.copy()
        d3["created_date"] = pd.to_datetime(d3["created_date"], errors="coerce")
        d3["closed_date"]  = pd.to_datetime(d3["closed_date"],  errors="coerce")
        st     = max(d3["created_date"].dropna().min(), pd.to_datetime(ANALYSIS_START_DATE))
        cd_max = d3["created_date"].dropna().max()
        cl_max = d3["closed_date"].dropna().max()
        en     = min(max(cd_max, cl_max) if pd.notna(cl_max) else cd_max, today)
        if pd.notna(st) and pd.notna(en) and st <= en:
            weeks = pd.date_range(st.normalize(), en.normalize(), freq="W-MON")
            oc = [
                int(((d3["created_date"] <= wk + pd.Timedelta(6)) &
                     (d3["closed_date"].isna() | (d3["closed_date"] > wk + pd.Timedelta(6)))).sum())
                for wk in weeks
            ]
            fig_wip = px.area(
                pd.DataFrame({"week": weeks, "open_items": oc}),
                x="week", y="open_items",
                title="Open Items Over Time (WIP Trend)",
                color_discrete_sequence=["#7c69d4"],
                labels={"week": "", "open_items": "Open Items"},
            )
            fig_wip.update_layout(
                height=400, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=80, l=60, r=20),
            )
            fig_wip.update_xaxes(tickangle=-35, tickfont=dict(size=12))
            fig_wip.update_yaxes(title="Open Items", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12))
        else:
            fig_wip = _empty_fig("Insufficient date range")
    else:
        fig_wip = _empty_fig()

    # ── Completion rate by item type ──────────────────────────────────────────
    if {"work_item_type", "state"}.issubset(df.columns):
        cr = df.copy()
        cr["type_clean"]  = cr["work_item_type"].replace({"Bug_UI": "Bug", "Bug_Text": "Bug"})
        cr["is_complete"] = cr["state"].isin(COMPLETED_STATES)
        cr_grp = cr.groupby("type_clean").agg(
            total=("is_complete", "count"),
            done=("is_complete", "sum"),
        ).reset_index()
        cr_grp["pct"] = np.where(cr_grp["total"] > 0,
                                  cr_grp["done"] / cr_grp["total"] * 100, 0).round(1)
        cr_grp = cr_grp.sort_values("pct", ascending=True)
        if not cr_grp.empty:
            fig_cr = go.Figure(go.Bar(
                x=cr_grp["pct"], y=cr_grp["type_clean"], orientation="h",
                marker_color=[
                    "#c05050" if v < 40 else ("#c97d3a" if v < 70 else "#3d9e6b")
                    for v in cr_grp["pct"]
                ],
                text=cr_grp["pct"].apply(lambda x: f"{x:.1f}%"),
                textposition="outside", textfont=dict(size=13),
                hovertemplate="%{y}: %{x:.1f}% complete<extra></extra>",
            ))
            fig_cr.update_layout(
                title="Completion Rate by Item Type (%)",
                height=max(len(cr_grp) * 60 + 120, 300),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=40, l=185, r=80),
            )
            fig_cr.update_xaxes(title="Completion %", range=[0, 120], gridcolor="rgba(255,255,255,0.06)",
                                ticksuffix="%", tickfont=dict(size=13))
            fig_cr.update_yaxes(tickfont=dict(size=13))
        else:
            fig_cr = _empty_fig("No completion data")
    else:
        fig_cr = _empty_fig()

    # ── Employee workload dot-plot ─────────────────────────────────────────────
    if {person_field, "original_estimate", "completed_work"}.issubset(df.columns):
        d4 = df.copy()
        d4["orig"] = num("original_estimate", d4)
        d4["comp"] = num("completed_work",    d4)
        g4 = d4.groupby(person_field)[["orig", "comp"]].sum().reset_index()
        g4["rem"] = (g4["orig"] - g4["comp"]).clip(lower=0)
        long = g4.melt(id_vars=person_field, value_vars=["orig", "comp", "rem"],
                       var_name="Type", value_name="Hours").replace(
            {"orig": "Original", "comp": "Completed", "rem": "Remaining"})
        if not long.empty:
            fig_dot = px.scatter(
                long, x="Hours", y=person_field, color="Type", opacity=0.85,
                title="Developer Workload — Original vs Completed vs Remaining",
                color_discrete_map={"Original": "#5a8fd4",
                                     "Completed": "#3d9e6b", "Remaining": "#c06060"},
            )
            fig_dot.update_traces(marker=dict(size=12))
            fig_dot.update_layout(
                height=max(len(g4) * 42 + 120, 300),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=90, b=60, l=185, r=40),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            fig_dot.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
            fig_dot.update_yaxes(tickfont=dict(size=12))
        else:
            fig_dot = _empty_fig("No workload data")
    else:
        fig_dot = _empty_fig()

    # ── Delivery forecast ─────────────────────────────────────────────────────
    forecast_card = html.Div()
    if {"completed_work", "closed_date", "original_estimate"}.issubset(df.columns):
        d6 = df.copy()
        d6["closed_date"] = pd.to_datetime(d6["closed_date"], errors="coerce")
        d6["comp"] = num("completed_work",    d6)
        d6["orig"] = num("original_estimate", d6)
        rem6     = max(d6["orig"].sum() - d6["comp"].sum(), 0)
        lb_start = today - pd.Timedelta(weeks=lookback)
        recent   = d6[d6["closed_date"].notna() & (d6["closed_date"] >= lb_start)]
        comp_win = recent["comp"].sum()
        wdays_win = _business_days(lb_start, today)
        thr_day   = comp_win / wdays_win if wdays_win > 0 else 0

        if thr_day > 0 and rem6 > 0:
            days_needed = int(np.ceil(rem6 / thr_day))
            if days_needed > 3650:
                forecast_card = dbc.Alert(
                    f"⚠️ Forecast requires {days_needed:,} working days — throughput too low to project meaningfully.",
                    color="warning")
            else:
                finish = _add_bdays(today, days_needed)
                lo     = _add_bdays(today, int(np.ceil(days_needed * 0.8)))
                hi     = _add_bdays(today, int(np.ceil(days_needed * 1.2)))
                forecast_card = dbc.Alert([
                    dbc.Row([
                        dbc.Col([
                            html.Div("🔮 Delivery Forecast",
                                     style={"fontWeight": "700", "fontSize": "15px",
                                            "marginBottom": "8px"}),
                            html.Div([
                                html.Span("Remaining: ", style={"fontWeight": "600"}),
                                f"{rem6:,.0f}h",
                                html.Span("  ·  Throughput: ", style={"fontWeight": "600"}),
                                f"{thr_day:.1f}h/day (last {lookback}wks)",
                                html.Span("  ·  Days needed: ", style={"fontWeight": "600"}),
                                str(days_needed),
                            ], style={"fontSize": "13px", "marginBottom": "6px"}),
                        ], md=8),
                        dbc.Col([
                            html.Div(finish.strftime("%d %b %Y"),
                                     style={"fontSize": "22px", "fontWeight": "800",
                                            "color": "#2b6cb0"}),
                            html.Div(
                                f"optimistic {lo.strftime('%d %b')} — pessimistic {hi.strftime('%d %b')}",
                                style={"fontSize": "11px", "color": "#718096"}),
                        ], md=4, className="text-md-end"),
                    ], align="center"),
                ], color="info", style={"marginBottom": "20px"})
        else:
            forecast_card = dbc.Alert(
                "Not enough throughput data to generate a forecast. "
                "Try increasing the lookback window or check that completed_work is populated.",
                color="secondary")

    return (overburden_div, kpi_row,
            fig_tmb, fig_tu,
            fig_pu,
            fig_iter,
            fig_at, fig_ae,
            fig_acc_trend,
            fig_tp, fig_wip,
            fig_cr,
            fig_dot,
            forecast_card)


# ── Report callback ───────────────────────────────────────────────────────────
@callback(
    Output("cap-report-modal", "is_open"),
    Output("cap-report-body",  "children"),
    Output("cap-report-ts",    "children"),
    Input("cap-report-btn",    "n_clicks"),
    State("cap-team",      "value"),
    State("cap-employee",  "value"),
    State("cap-iteration", "value"),
    State("cap-hours-day", "value"),
    prevent_initial_call=True,
)
def _open_cap_report(n, team, employee, iterations, hours_day):
    if not n:
        from dash import no_update
        return no_update, no_update, no_update
    df = load_data()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    df = apply_filters(df, employee=employee, iterations=iterations)
    if team and team != "All" and "main_dev_team" in df.columns:
        df = df[df["main_dev_team"] == team]
    # Mirror same 2026 task-only logic as the main capacity callback
    def _is_2026(x): return "2026" in str(x)
    if iterations and all(_is_2026(i) for i in iterations):
        df = df[df["work_item_type"] == "Task"]
    elif not iterations and "iteration_path" in df.columns:
        mask_2026 = df["iteration_path"].apply(lambda x: _is_2026(x) if pd.notna(x) else False)
        df = pd.concat([df[~mask_2026], df[mask_2026 & (df["work_item_type"] == "Task")]], ignore_index=True)
    summary = summarize_capacity(df)
    body    = format_report(summary)
    # Build filter note for footer
    parts = []
    if team and team != "All":                     parts.append(f"Team: {team}")
    if employee and employee != "All":             parts.append(f"Person: {employee}")
    if iterations:
        shown = ", ".join(iterations[:3])
        parts.append(f"Iterations: {shown}{'…' if len(iterations) > 3 else ''}")
    filter_note = "  ·  Filters: " + " · ".join(parts) if parts else ""
    ts = (f"Generated {summary['as_of']}  •  {summary['total_est']:.0f}h estimated"
          f"  •  {summary['utilisation_pct']}% utilised{filter_note}")
    return True, body, ts


@callback(
    Output("cap-rec-strip", "children"),
    Input("cap-team",      "value"),
    Input("cap-employee",  "value"),
    Input("cap-iteration", "value"),
    Input("cap-hours-day", "value"),
)
def update_cap_recs(team, employee, iterations, hours_day):
    df = load_data()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    df = apply_filters(df, employee=employee, iterations=iterations)
    if team and team != "All" and "main_dev_team" in df.columns:
        df = df[df["main_dev_team"] == team]
    # Mirror the same tasks-only logic so rec thresholds fire on clean data
    def _is_2026(x): return "2026" in str(x)
    if iterations and all(_is_2026(i) for i in iterations):
        df = df[df["work_item_type"] == "Task"]
    elif not iterations and "iteration_path" in df.columns:
        mask_2026 = df["iteration_path"].apply(lambda x: _is_2026(x) if pd.notna(x) else False)
        df = pd.concat([df[~mask_2026], df[mask_2026 & (df["work_item_type"] == "Task")]], ignore_index=True)
    recs = get_recommendations_capacity(df, hours_day=hours_day or 8)
    return rec_strip(recs)


def _summary_chip(label, value, color="#94a3b8"):
    return html.Div([
        html.Div(str(value), style={"fontSize": "20px", "fontWeight": "700", "color": color}),
        html.Div(label, style={"fontSize": "11px", "color": "#64748b"}),
    ], style={"background": "rgba(255,255,255,0.03)", "borderRadius": "8px",
              "border": "1px solid rgba(255,255,255,0.06)",
              "padding": "10px 18px", "textAlign": "center", "minWidth": "100px"})



# ── Planner board helpers (ADO data) ──────────────────────────────────────────

# Map ADO states → 4 board columns
_ADO_STATE_MAP = {
    "New":              "To Do",
    "Request Estimate": "To Do",
    "Clarification":    "To Do",
    "Estimated":        "To Do",
    "Reopened":         "To Do",
    "Active":           "In Progress",
    "Dev InProgress":   "In Progress",
    "Dev Review":       "In Progress",
    "Tester Assigned":  "In Progress",
    "Dev Complete":     "In Progress",
    "Watch List":       "Blocked",
    "On Hold":          "Blocked",
    "Rare Scenario":    "Blocked",
    "Closed":           "Done",
    "Resolved":         "Done",
    "Userstory Update": "Done",
    "Not an issue":     "Done",
    "Not Required":     "Done",
    "No Customer Response": "Done",
}
BOARD_STATES = ["To Do", "In Progress", "Blocked", "Done"]
_STATE_COLORS = {
    "To Do":       "#a0aec0",
    "In Progress": "#60a5fa",
    "Blocked":     "#f87171",
    "Done":        "#34d399",
}
_TYPE_COLORS = {
    "Task":        "#60a5fa",
    "Bug":         "#f87171",
    "Bug_UI":      "#f87171",
    "Bug_Text":    "#f87171",
    "User Story":  "#818cf8",
    "Enhancement": "#34d399",
}
_TYPE_GROUPS = {
    "Bug_UI":   "Bug",
    "Bug_Text": "Bug",
}
_STALE_DAYS = 7
_ADO_DONE_STATES = {"Closed", "Resolved", "Userstory Update", "Not an issue",
                    "Not Required", "No Customer Response"}
_ALL_ADO_STATES = list(_ADO_STATE_MAP.keys())


def _ado_item_card(row, modal_mode=False):
    """Render one ADO item card. modal_mode=True omits the state-change dropdown."""
    raw_state    = row.get("state") or ""
    board_col    = _ADO_STATE_MAP.get(raw_state, "To Do")
    col_color    = _STATE_COLORS[board_col]
    wtype        = row.get("work_item_type") or "Unknown"
    type_color   = _TYPE_COLORS.get(wtype, "#94a3b8")
    est          = row.get("original_estimate")
    title        = str(row.get("title") or "")
    assignee     = str(row.get("assigned_to") or row.get("main_developer") or "Unassigned")
    assignee     = assignee.split(" <")[0]
    work_item_id = row.get("work_item_id", "")

    # ── Stale badge ───────────────────────────────────────────────────────────
    stale_badge = None
    if raw_state not in _ADO_DONE_STATES:
        try:
            changed_ts = pd.Timestamp(row.get("changed_date"))
            if pd.notna(changed_ts):
                age = (pd.Timestamp.now() - changed_ts).days
                if age >= _STALE_DAYS:
                    stale_badge = html.Span(f"⏱ {age}d stale", style={
                        "fontSize": "9px", "color": "#fbbf24",
                        "background": "rgba(251,191,36,0.08)",
                        "border": "1px solid rgba(251,191,36,0.25)",
                        "padding": "1px 5px", "borderRadius": "4px",
                    })
        except Exception:
            pass

    header_items = [
        html.A(str(work_item_id),
               href=f"{ADO_BASE_URL}{work_item_id}", target="_blank",
               style={"fontSize": "10px", "color": "#5c6bc0", "fontFamily": "monospace",
                      "textDecoration": "none", "fontWeight": "600"},
               title="Open in Azure DevOps"),
        html.Span(_TYPE_GROUPS.get(wtype, wtype), style={
            "fontSize": "10px", "background": "rgba(0,0,0,0.2)",
            "color": type_color, "padding": "1px 6px", "borderRadius": "4px",
            "border": f"1px solid {type_color}40",
        }),
        html.Span(raw_state, style={
            "fontSize": "10px", "color": "#64748b",
            "padding": "1px 5px", "borderRadius": "4px",
            "background": "rgba(255,255,255,0.04)",
        }),
    ]
    if stale_badge:
        header_items.append(stale_badge)

    card_id_int = int(work_item_id) if str(work_item_id).isdigit() else 0

    footer_children = [
        html.Span(assignee, style={"fontSize": "11px", "color": "#818cf8"}),
        html.Span(" · ", style={"color": "#475569"}),
        html.Span(f"{est}h" if est else "—", style={"fontSize": "11px", "color": "#94a3b8"}),
    ]

    state_row = []
    if not modal_mode and card_id_int:
        state_row = [html.Div([
            dcc.Dropdown(
                id={"type": "card-state-select", "index": card_id_int},
                options=[{"label": s, "value": s} for s in _ALL_ADO_STATES],
                value=None,
                placeholder=raw_state,
                clearable=False,
                style={"fontSize": "10px", "minWidth": "160px",
                       "background": "rgba(0,0,0,0.3)"},
            ),
            html.Span(id={"type": "card-state-feedback", "index": card_id_int},
                      style={"fontSize": "10px", "marginLeft": "6px",
                             "color": "#34d399", "minWidth": "20px"}),
        ], style={"display": "flex", "alignItems": "center", "marginTop": "6px", "gap": "4px"})]

    return html.Div([
        html.Div(header_items, style={"display": "flex", "gap": "4px", "flexWrap": "wrap",
                                      "alignItems": "center", "marginBottom": "5px"}),
        html.Div((title[:70] + "…" if len(title) > 70 else title), style={
            "fontSize": "12px", "fontWeight": "600", "color": "#e2e8f0",
            "lineHeight": "1.3", "marginBottom": "5px",
        }),
        html.Div(footer_children, style={"marginBottom": "2px"}),
        *state_row,
    ], style={
        "background": "rgba(255,255,255,0.02)", "borderRadius": "7px",
        "border": f"1px solid {'rgba(248,113,113,0.2)' if board_col == 'Blocked' else 'rgba(255,255,255,0.04)'}",
        "borderLeft": f"3px solid {col_color}",
        "padding": "10px 12px", "marginBottom": "6px",
    })


def _render_ado_board(df_iter):
    if df_iter.empty:
        return html.Div("No items found for this iteration.",
                        style={"fontSize": "13px", "color": "#64748b", "padding": "16px 0"})

    columns = {s: [] for s in BOARD_STATES}
    for _, row in df_iter.iterrows():
        col = _ADO_STATE_MAP.get(row.get("state") or "", "To Do")
        columns[col].append(row.to_dict())

    col_divs = []
    for state in BOARD_STATES:
        items = columns[state]
        color = _STATE_COLORS[state]
        col_divs.append(html.Div([
            html.Div([
                html.Div(style={"width": "8px", "height": "8px", "borderRadius": "50%",
                                "background": color, "display": "inline-block", "marginRight": "6px"}),
                html.Span(state, style={"fontSize": "11px", "fontWeight": "700", "color": "#c8c8e0",
                                        "textTransform": "uppercase", "letterSpacing": "0.5px"}),
                html.Span(f"  {len(items)}", style={"fontSize": "11px", "color": "#64748b"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
            html.Div(
                [_ado_item_card(r) for r in items] if items
                else [html.Div("Empty", style={"fontSize": "11px", "color": "#475569",
                                               "textAlign": "center", "padding": "10px"})],
                style={"maxHeight": "520px", "overflowY": "auto"},
            ),
        ], style={
            "minWidth": "0",
            "background": "rgba(255,255,255,0.01)", "borderRadius": "10px",
            "border": "1px solid rgba(255,255,255,0.04)", "padding": "12px",
        }))

    return html.Div(col_divs, style={
        "display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "12px",
    })


def _build_ado_breakdown(df_iter):
    if df_iter.empty:
        return _empty_fig("No items")
    counts = df_iter.groupby("work_item_type").size().reset_index(name="n")
    colors = [_TYPE_COLORS.get(t, "#94a3b8") for t in counts["work_item_type"]]
    fig = go.Figure(go.Pie(
        labels=counts["work_item_type"].tolist(),
        values=counts["n"].tolist(),
        hole=0.55,
        marker_colors=colors,
        textinfo="label+value",
        textfont=dict(size=11, color="#e2e8f0"),
    ))
    fig.update_layout(
        showlegend=False, height=280,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _build_ado_burndown(df_iter, iteration):
    if df_iter.empty:
        return _empty_fig("No items to plot")

    dates = ITERATION_DATES.get(iteration)
    if not dates:
        # Try to parse "Iteration YYYY MM-MonthName" or sprint-style names
        try:
            parts = str(iteration).split(" ")
            if len(parts) >= 3 and "-" in parts[2]:
                year  = int(parts[1])
                month = int(parts[2].split("-")[0])
                start = pd.Timestamp(year=year, month=month, day=1)
                end   = start + pd.offsets.MonthEnd(1)
                dates = (str(start.date()), str(end.date()))
        except Exception:
            pass

    if not dates:
        return _empty_fig("Iteration dates unknown")

    iter_start = pd.Timestamp(dates[0])
    iter_end   = pd.Timestamp(dates[1])
    today      = pd.Timestamp.now().normalize()
    plot_end   = min(iter_end, today)
    date_range = pd.date_range(iter_start, plot_end, freq="D")
    total      = len(df_iter)

    closed_dates = pd.to_datetime(df_iter["closed_date"].dropna(), errors="coerce").dt.normalize()

    actual = []
    for day in date_range:
        done = (closed_dates <= day).sum()
        actual.append(total - int(done))

    total_days = max(1, (iter_end - iter_start).days)
    ideal = [max(0.0, total - total * (day - iter_start).days / total_days)
             for day in date_range]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=date_range.tolist(), y=ideal, name="Ideal",
        line=dict(color="rgba(129,140,248,0.4)", dash="dash", width=1.5), mode="lines",
    ))
    fig.add_trace(go.Scatter(
        x=date_range.tolist(), y=actual, name="Remaining",
        line=dict(color="#34d399", width=2),
        fill="tozeroy", fillcolor="rgba(52,211,153,0.06)",
        mode="lines+markers", marker=dict(size=4),
    ))
    fig.update_layout(
        height=280, margin=dict(t=10, b=30, l=30, r=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color="#94a3b8", size=10)),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickfont=dict(color="#8892a4", size=10)),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickfont=dict(color="#8892a4", size=10),
                   title=dict(text="Remaining", font=dict(color="#64748b", size=10))),
    )
    return fig


def _build_ado_workload(df_iter):
    if df_iter.empty:
        return html.Div("No data.", style={"fontSize": "13px", "color": "#64748b"})

    person_col = "main_developer" if "main_developer" in df_iter.columns else "assigned_to"
    df_iter = df_iter.copy()
    df_iter["_person"] = df_iter[person_col].astype(str).str.split(" <").str[0].replace("nan", "Unassigned")

    grp = df_iter.groupby("_person").agg(
        total=("work_item_id", "count"),
        est_hours=("original_estimate", "sum"),
        done=("state", lambda s: s.isin(_ADO_DONE_STATES).sum()),
    ).reset_index().sort_values("total", ascending=False)

    rows = []
    for _, r in grp.iterrows():
        pct    = round(r["done"] / r["total"] * 100) if r["total"] else 0
        person = r["_person"]
        rows.append(html.Div([
            html.Div([
                html.Div(
                    [person, html.Span(" ↗", style={"fontSize": "10px", "opacity": "0.5"})],
                    id={"type": "pl-person", "index": person},
                    n_clicks=0,
                    title="Click to see this person's items",
                    style={"fontSize": "13px", "fontWeight": "600", "color": "#818cf8",
                           "minWidth": "180px", "cursor": "pointer",
                           "textDecoration": "underline dotted rgba(129,140,248,0.5)"},
                ),
                html.Span(f"{int(r['total'])} items", style={"fontSize": "11px", "color": "#818cf8",
                           "background": "rgba(129,140,248,0.1)", "padding": "2px 8px",
                           "borderRadius": "20px", "marginLeft": "8px"}),
                html.Span(f"{int(r['est_hours'] or 0)}h est",
                          style={"fontSize": "11px", "color": "#94a3b8", "marginLeft": "8px"}),
                html.Span(f"{pct}% done",
                          style={"fontSize": "11px", "color": "#34d399" if pct >= 50 else "#fb923c",
                                 "marginLeft": "8px"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "4px"}),
            html.Div([
                html.Div(style={"height": "4px", "width": f"{pct}%",
                                "background": "#34d399" if pct >= 50 else "#fb923c",
                                "borderRadius": "2px"}),
            ], style={"background": "rgba(255,255,255,0.06)", "borderRadius": "2px",
                      "height": "4px", "width": "100%", "overflow": "hidden"}),
        ], style={"marginBottom": "10px"}))

    return html.Div(rows)


def _render_ado_redflags(df_iter):
    if df_iter.empty:
        return [html.Div("✅ No data for this iteration.",
                         style={"fontSize": "12px", "color": "#34d399", "padding": "6px 0"})]

    no_est  = df_iter[(df_iter["original_estimate"].isna()) &
                      (~df_iter["state"].isin(_ADO_DONE_STATES))]
    blocked = df_iter[df_iter["state"].isin(["Watch List", "On Hold", "Rare Scenario"])]
    flags   = []

    def _flag_row(icon, label, df_sub, bg, border, text_color):
        excerpt = ", ".join(
            f"#{r['work_item_id']} {str(r.get('title',''))[:28]}"
            for _, r in df_sub.head(5).iterrows()
        ) + (f" +{len(df_sub)-5} more" if len(df_sub) > 5 else "")
        return html.Div([
            html.Div(f"{icon} {label}",
                     style={"fontSize": "12px", "fontWeight": "700", "color": text_color, "marginBottom": "4px"}),
            html.Div(excerpt, style={"fontSize": "11px", "color": "#94a3b8"}),
        ], style={"background": bg, "border": border, "borderRadius": "8px",
                  "padding": "10px 14px", "marginBottom": "8px"})

    if len(no_est):
        flags.append(_flag_row("⚠", f"No Estimate ({len(no_est)})", no_est,
                               "rgba(251,146,60,0.05)", "1px solid rgba(251,146,60,0.2)", "#fb923c"))
    if len(blocked):
        flags.append(_flag_row("🚫", f"Blocked / On Hold ({len(blocked)})", blocked,
                               "rgba(248,113,113,0.05)", "1px solid rgba(248,113,113,0.2)", "#f87171"))

    return flags or [html.Div("✅ No red flags for this iteration.",
                              style={"fontSize": "12px", "color": "#34d399", "padding": "6px 0"})]


# ── Planner board callback ─────────────────────────────────────────────────────

@callback(
    Output("cap-pl-kpis",       "children"),
    Output("cap-pl-task-board", "children"),
    Output("cap-pl-breakdown",  "figure"),
    Output("cap-pl-burndown",   "figure"),
    Output("cap-pl-workload",   "children"),
    Output("cap-pl-redflags",   "children"),
    Input("cap-planner-iter",   "value"),
    Input("cap-pl-team",        "value"),
    Input("cap-pl-person",      "value"),
    Input("cap-pl-type",        "value"),
)
def _render_planner_board(iteration, team_filter, person_filter, type_filter):
    _empty_board = html.Div("Select an iteration above to load the planner.",
                            style={"fontSize": "13px", "color": "#64748b", "padding": "20px 0"})
    _no_data = _empty_fig("No iteration selected")
    if not iteration:
        return [], _empty_board, _no_data, _no_data, html.Span(), []

    df = load_data()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    if "main_developer" in df.columns:
        df["main_developer"] = df["main_developer"].astype(str).str.split(" <").str[0]

    df_iter = df[df["iteration_path"] == iteration].copy()

    if df_iter.empty:
        msg = html.Div(f"No ADO items found for '{iteration}'.",
                       style={"fontSize": "13px", "color": "#64748b", "padding": "16px 0"})
        return [], msg, _empty_fig("No data"), _empty_fig("No data"), html.Span(), []

    # ── Apply board-level filters ─────────────────────────────────────────────
    person_col = "main_developer" if "main_developer" in df_iter.columns else "assigned_to"

    if team_filter and team_filter != "All" and "main_dev_team" in df_iter.columns:
        df_iter = df_iter[df_iter["main_dev_team"] == team_filter]
    if person_filter and person_filter != "All" and person_col in df_iter.columns:
        df_iter = df_iter[df_iter[person_col] == person_filter]
    if type_filter and "work_item_type" in df_iter.columns:
        df_iter = df_iter[df_iter["work_item_type"].isin(type_filter)]

    if df_iter.empty:
        msg = html.Div("No items match the current filters.",
                       style={"fontSize": "13px", "color": "#64748b", "padding": "16px 0"})
        return [], msg, _empty_fig("No items"), _empty_fig("No items"), html.Span(), []

    BLOCKED_STATES = {"Watch List", "On Hold", "Rare Scenario"}

    total      = len(df_iter)
    done_ct    = df_iter["state"].isin(_ADO_DONE_STATES).sum()
    blocked_ct = df_iter["state"].isin(BLOCKED_STATES).sum()
    inprog_ct  = total - done_ct - blocked_ct - df_iter["state"].isin(
        ["New", "Request Estimate", "Clarification", "Estimated", "Reopened"]).sum()
    total_est  = pd.to_numeric(df_iter["original_estimate"], errors="coerce").sum()
    no_est_ct  = df_iter[df_iter["original_estimate"].isna() &
                         ~df_iter["state"].isin(_ADO_DONE_STATES)].shape[0]
    done_pct   = round(done_ct / total * 100) if total else 0

    # Filter label suffix for KPIs
    filter_parts = []
    if team_filter and team_filter != "All":   filter_parts.append(team_filter)
    if person_filter and person_filter != "All": filter_parts.append(person_filter)
    if type_filter: filter_parts.extend(type_filter)
    filter_note = f" [{', '.join(filter_parts)}]" if filter_parts else ""

    kpi_chips = [
        _summary_chip(f"Items{filter_note}", total),
        _summary_chip("Done", f"{done_ct} ({done_pct}%)", "#34d399"),
        _summary_chip("In Progress", int(inprog_ct), "#60a5fa"),
        _summary_chip("Blocked", int(blocked_ct), "#f87171" if blocked_ct else "#64748b"),
        _summary_chip("Est. Hours", f"{total_est:.0f}h", "#818cf8"),
        _summary_chip("No Estimate", int(no_est_ct), "#fb923c" if no_est_ct else "#64748b"),
    ]

    return (
        kpi_chips,
        _render_ado_board(df_iter),
        _build_ado_breakdown(df_iter),
        _build_ado_burndown(df_iter, iteration),
        _build_ado_workload(df_iter),
        _render_ado_redflags(df_iter),
    )


# ── State-change from card ─────────────────────────────────────────────────────

@callback(
    Output({"type": "card-state-feedback", "index": MATCH}, "children"),
    Output({"type": "card-state-select",   "index": MATCH}, "value"),
    Input({"type": "card-state-select",    "index": MATCH}, "value"),
    State({"type": "card-state-select",    "index": MATCH}, "id"),
    prevent_initial_call=True,
)
def _card_state_change(new_state, comp_id):
    """Write new ADO state for a work item directly from the board card."""
    if not new_state:
        return no_update, no_update
    ado_id = comp_id["index"]
    from sync.ado_write import write_fields_sync
    ok, err = write_fields_sync(ado_id, {"state": new_state})
    if ok:
        return html.Span("✓", style={"color": "#34d399", "fontWeight": "700"}), None
    return html.Span("✗", title=err[:120], style={"color": "#f87171", "fontWeight": "700"}), None


# ── Person drill-down modal ────────────────────────────────────────────────────

@callback(
    Output("cap-pl-person-modal",       "is_open"),
    Output("cap-pl-person-modal-title", "children"),
    Output("cap-pl-person-modal-body",  "children"),
    Input({"type": "pl-person", "index": ALL}, "n_clicks"),
    State("cap-planner-iter", "value"),
    prevent_initial_call=True,
)
def _person_modal(n_clicks_list, iteration):
    """Open person drill-down modal showing all their items in the selected iteration."""
    if not any(n_clicks_list) or not ctx.triggered_id:
        return False, "", []
    triggered = ctx.triggered_id
    if not isinstance(triggered, dict):
        return False, "", []
    person = triggered["index"]
    if not iteration:
        return True, person, [html.Div("Select an iteration first.",
                                       style={"color": "#64748b", "fontSize": "13px"})]

    df = load_data()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    df_iter = df[df["iteration_path"] == iteration].copy()

    person_col = "main_developer" if "main_developer" in df_iter.columns else "assigned_to"
    df_iter["_p"] = df_iter[person_col].astype(str).str.split(" <").str[0].replace("nan", "Unassigned")
    df_person = df_iter[df_iter["_p"] == person].copy()

    title_str = f"{person}  ·  {iteration}  ({len(df_person)} items)"

    if df_person.empty:
        return True, title_str, [html.Div("No items found.", style={"color": "#64748b"})]

    # Sort: Blocked first, then In Progress, then To Do, then Done
    _order = {"Blocked": 0, "In Progress": 1, "To Do": 2, "Done": 3}
    df_person["_col"] = df_person["state"].map(_ADO_STATE_MAP).fillna("To Do")
    df_person["_sort"] = df_person["_col"].map(_order).fillna(2)
    df_person = df_person.sort_values("_sort")

    # Group by board column for clear sections
    body = []
    for col_name in BOARD_STATES:
        subset = df_person[df_person["_col"] == col_name]
        if subset.empty:
            continue
        color = _STATE_COLORS[col_name]
        body.append(html.Div([
            html.Div([
                html.Div(style={"width": "8px", "height": "8px", "borderRadius": "50%",
                                "background": color, "display": "inline-block", "marginRight": "6px"}),
                html.Span(col_name, style={"fontSize": "11px", "fontWeight": "700", "color": "#c8c8e0",
                                           "textTransform": "uppercase", "letterSpacing": "0.5px"}),
                html.Span(f"  {len(subset)}", style={"fontSize": "11px", "color": "#64748b"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px",
                      "marginTop": "12px"}),
            *[_ado_item_card(r.to_dict(), modal_mode=True) for _, r in subset.iterrows()],
        ]))

    return True, title_str, body


# ═══════════════════════════════════════════════════════════════════════════════
# PLANNER SECTION NAV
# ═══════════════════════════════════════════════════════════════════════════════

_PLANNER_SECTIONS = ["board", "adjuster", "backlog"]
_SECTION_DIV_IDS  = [
    "cap-pl-board-section", "cap-pl-adjuster-section", "cap-pl-backlog-section",
]


@callback(
    Output("cap-pl-active-section", "data"),
    Input({"type": "pl-nav-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _pl_switch_section(_):
    if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
        return no_update
    return ctx.triggered_id["index"]


@callback(
    # Section visibility
    Output("cap-pl-board-section",    "style"),
    Output("cap-pl-adjuster-section", "style"),
    Output("cap-pl-backlog-section",  "style"),
    # Nav button active classes
    Output({"type": "pl-nav-btn", "index": "board"},    "className"),
    Output({"type": "pl-nav-btn", "index": "adjuster"}, "className"),
    Output({"type": "pl-nav-btn", "index": "backlog"},  "className"),
    Input("cap-pl-active-section", "data"),
)
def _pl_toggle_sections(active):
    _show    = {"display": "block"}
    _hide    = {"display": "none"}
    _pl_card = {
        "background": "rgba(255,255,255,0.015)", "borderRadius": "12px",
        "border": "1px solid rgba(255,255,255,0.04)",
        "padding": "20px 20px 14px 20px", "marginBottom": "16px",
    }
    styles_out = []
    for sec in _PLANNER_SECTIONS:
        if sec == active:
            styles_out.append(_show | _pl_card if sec == "backlog" else _show)
        else:
            styles_out.append(_hide)

    base    = "pl-nav-btn"
    act_cls = "pl-nav-btn pl-nav-btn--active"
    btn_cls = [act_cls if s == active else base for s in _PLANNER_SECTIONS]

    return (*styles_out, *btn_cls)


# ═══════════════════════════════════════════════════════════════════════════════
# ITEM ADJUSTER
# ═══════════════════════════════════════════════════════════════════════════════

@callback(
    Output("cap-adj-iter-wrap",    "style"),
    Output("cap-adj-release-wrap", "style"),
    Input("cap-adj-view-mode",     "value"),
)
def _adj_mode_toggle(mode):
    """Show/hide iteration vs release dropdown based on view mode radio."""
    show, hide = {}, {"display": "none"}
    return (hide, show) if mode == "release" else (show, hide)


def _build_item_gantt(df, groupby, selected, mode, hours_day=8):
    """
    Item-level Gantt: rows = groupby dimension, bars = each iteration/release window.
    Bar size = duration of that window. Color = capacity utilisation or delay risk.
    Clicking a bar selects that window (via customdata).
    """
    import re as _re
    _epoch = pd.Timestamp("1970-01-01")
    today  = pd.Timestamp.now().normalize()

    # ── Time windows ──────────────────────────────────────────────────────────
    if mode == "iteration":
        windows = []
        known   = set(ITERATION_DATES.keys())
        for iter_name, (s, e) in ITERATION_DATES.items():
            st, en = pd.Timestamp(s), pd.Timestamp(e)
            windows.append({
                "label": iter_name, "start": st, "end": en,
                "cap_h": _business_days(st, en) * (hours_day or 8),
            })
        # 2026+ monthly iterations from data
        if "iteration_path" in df.columns:
            for iter_name in df["iteration_path"].dropna().unique():
                if iter_name in known or not iter_name:
                    continue
                try:
                    parts = str(iter_name).split(" ")
                    year  = int(parts[1])
                    month = int(parts[2].split("-")[0])
                    st    = pd.Timestamp(year=year, month=month, day=1)
                    en    = st + pd.offsets.MonthEnd(1)
                    windows.append({
                        "label": iter_name, "start": st, "end": en,
                        "cap_h": _business_days(st, en) * (hours_day or 8),
                    })
                except Exception:
                    pass
        win_col = "iteration_path"
    else:
        if "release_date" not in df.columns:
            return _empty_fig("No release_date column in data")
        named   = [r for r in df["release_date"].dropna().unique()
                   if _re.match(r"^\d{4}\s+[A-Za-z]", str(r))]
        windows = []
        for rel in named:
            st, en = _parse_release_dates(rel)
            if st is None:
                continue
            windows.append({"label": rel, "start": st, "end": en, "cap_h": None})
        win_col = "release_date"

    if not windows:
        return _empty_fig("No time windows available")

    # Limit to ±12 months
    cutoff_lo = today - pd.Timedelta(days=365)
    cutoff_hi = today + pd.Timedelta(days=365)
    windows   = [w for w in windows if w["end"] >= cutoff_lo and w["start"] <= cutoff_hi]
    windows   = sorted(windows, key=lambda w: w["start"])
    if not windows:
        return _empty_fig("No time windows in the ±12 month range")

    # ── Grouping column ───────────────────────────────────────────────────────
    _col_map = {
        "person":   "main_developer",
        "type":     "work_item_type",
        "state":    "state",
        "function": "function",
    }
    group_col = _col_map.get(groupby or "person", "main_developer")
    if group_col not in df.columns:
        group_col = "assigned_to" if "assigned_to" in df.columns else None
    if not group_col:
        return _empty_fig("Grouping column not available")

    df_use = df.copy()
    df_use["_group"] = (
        df_use[group_col].astype(str).str.split(" <").str[0]
        .replace("nan", "Unassigned").fillna("Unassigned")
    )
    groups = sorted(df_use["_group"].dropna().unique())
    if not groups:
        return _empty_fig("No data to display")

    # ── Build one trace per (group, window) ───────────────────────────────────
    fig = go.Figure()
    for win in windows:
        if win_col in df_use.columns:
            df_win = df_use[df_use[win_col] == win["label"]]
        else:
            df_win = pd.DataFrame()

        dur      = max((win["end"] - win["start"]).days, 1)
        base_day = (win["start"] - _epoch).days
        is_sel   = bool(selected and win["label"] == selected)

        for group in groups:
            df_g = df_win[df_win["_group"] == group] if not df_win.empty else pd.DataFrame()
            if df_g.empty:
                continue

            est_h = pd.to_numeric(df_g.get("original_estimate", 0), errors="coerce").fillna(0).sum()
            rem_h = pd.to_numeric(df_g.get("remaining_work",    0), errors="coerce").fillna(0).sum()
            cmp_h = pd.to_numeric(df_g.get("completed_work",    0), errors="coerce").fillna(0).sum()
            total = len(df_g)
            done  = int(df_g["state"].isin(_ADO_DONE_STATES).sum()) if "state" in df_g.columns else 0
            delay = rem_h > max(est_h - cmp_h, 0) + 0.5   # remaining > budget left

            pct_done = done / total * 100 if total else 0
            if win["cap_h"] and win["cap_h"] > 0:
                util_pct = est_h / win["cap_h"] * 100
                if util_pct > 110:   color = "rgba(248,113,113,0.75)"
                elif util_pct >= 80: color = "rgba(251,191,36,0.75)"
                else:                color = "rgba(52,211,153,0.65)"
            elif delay:              color = "rgba(248,113,113,0.75)"
            elif pct_done >= 80:     color = "rgba(52,211,153,0.65)"
            else:                    color = "rgba(129,140,248,0.65)"

            hover = (
                f"<b>{group}</b> — {win['label']}<br>"
                f"Items: {total}  |  Done: {done} ({pct_done:.0f}%)<br>"
                f"Est: {est_h:.0f}h  Completed: {cmp_h:.0f}h  Remaining: {rem_h:.0f}h"
                + ("  <b>⚠ Delay risk</b>" if delay else "")
                + (f"<br>Util: {est_h/win['cap_h']*100:.0f}% of capacity" if win["cap_h"] else "")
                + "<extra></extra>"
            )
            fig.add_trace(go.Bar(
                y=[group], x=[dur], orientation="h",
                base=[base_day],
                marker_color=color,
                marker_line_width=2 if is_sel else 0,
                marker_line_color="#e2e8f0",
                text=[f"{total}i · {est_h:.0f}h"],
                textposition="inside",
                textfont=dict(color="#ffffff", size=9),
                hovertemplate=hover,
                customdata=[[win["label"]]],
                showlegend=False,
            ))

    if not fig.data:
        return _empty_fig("No items in the visible date range")

    today_days = (today - _epoch).days
    span_start = min(w["start"] for w in windows)
    span_end   = max(w["end"]   for w in windows)
    tick_dates = pd.date_range(span_start, span_end,
                               periods=min(12, len(windows) + 2))
    tick_vals  = [(d - _epoch).days for d in tick_dates]
    tick_lbls  = [d.strftime("%b %Y") for d in tick_dates]

    fig.add_vline(x=today_days, line_dash="dash",
                  line_color="rgba(251,191,36,0.7)", line_width=1.5,
                  annotation_text="Today",
                  annotation_font=dict(size=10, color="#fbbf24"))
    fig.update_layout(
        height=max(len(groups) * 36 + 100, 350),
        barmode="overlay", bargap=0.28,
        xaxis=dict(tickvals=tick_vals, ticktext=tick_lbls,
                   gridcolor="rgba(255,255,255,0.04)", tickfont=dict(size=10)),
        yaxis=dict(gridcolor="rgba(255,255,255,0)", tickfont=dict(size=10),
                   autorange="reversed", categoryorder="array",
                   categoryarray=list(reversed(groups))),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=20, b=40, l=200, r=20),
        clickmode="event",
    )
    return fig


def _build_adj_cap_matrix(df, hours_day=8):
    """Capacity matrix for Item Adjuster — recent + upcoming iterations."""
    if "iteration_path" not in df.columns:
        return html.Div("No iteration data.", style={"color": "#64748b"})

    person_col = "main_developer" if "main_developer" in df.columns else "assigned_to"
    today      = pd.Timestamp.now().normalize()
    relevant   = []
    known      = set(ITERATION_DATES.keys())

    for iter_name, (s, e) in ITERATION_DATES.items():
        if pd.Timestamp(e) >= today - pd.Timedelta(weeks=8):
            relevant.append((pd.Timestamp(s), iter_name))

    for iter_name in df["iteration_path"].dropna().unique():
        if iter_name in known or not iter_name:
            continue
        try:
            parts = str(iter_name).split(" ")
            year  = int(parts[1])
            month = int(parts[2].split("-")[0])
            st    = pd.Timestamp(year=year, month=month, day=1)
            en    = st + pd.offsets.MonthEnd(1)
            if en >= today - pd.Timedelta(weeks=8):
                relevant.append((st, iter_name))
        except Exception:
            pass

    relevant   = sorted(set(relevant))[:8]
    iter_names = [name for _, name in relevant]
    if not iter_names:
        return html.Div("No upcoming iterations found.", style={"color": "#64748b"})

    df_rel = df[df["iteration_path"].isin(iter_names)].copy()
    df_rel["_person"] = df_rel[person_col].replace("nan", "Unassigned").fillna("Unassigned")
    df_rel["_est"]    = pd.to_numeric(df_rel.get("original_estimate", 0), errors="coerce").fillna(0)

    people = sorted(df_rel["_person"].dropna().unique())
    if not people:
        return html.Div("No assignee data found.", style={"color": "#64748b"})

    header = html.Tr([
        html.Th("Person", style={"minWidth": "160px"}),
        *[html.Th(html.Div([
            html.Div(n, style={"fontSize": "10px", "fontWeight": "600",
                               "color": "#94a3b8", "whiteSpace": "nowrap",
                               "overflow": "hidden", "textOverflow": "ellipsis",
                               "maxWidth": "110px"}),
            html.Div(f"{get_iteration_bdays(n)} days",
                     style={"fontSize": "9px", "color": "#475569"}),
          ]), style={"minWidth": "120px", "textAlign": "center", "padding": "8px 6px"})
          for n in iter_names],
    ], style={"background": "#0e0e1a"})

    t_rows = []
    for person in people:
        cells = [html.Td(person, style={"fontWeight": "600", "color": "#e2e8f0",
                                        "fontSize": "12px"})]
        for iter_name in iter_names:
            mask  = (df_rel["_person"] == person) & (df_rel["iteration_path"] == iter_name)
            est_h = df_rel[mask]["_est"].sum()
            bdays = get_iteration_bdays(iter_name)
            cap_h = bdays * (hours_day or 8)
            pct   = est_h / cap_h * 100 if cap_h else 0
            if pct > 110:   bg, tc = "rgba(248,113,113,0.18)", "#f87171"
            elif pct >= 80: bg, tc = "rgba(251,191,36,0.12)",  "#fbbf24"
            elif est_h > 0: bg, tc = "rgba(52,211,153,0.10)",  "#34d399"
            else:           bg, tc = "transparent",             "#475569"
            _bar_content = html.Div([
                html.Div(f"{est_h:.0f}h / {cap_h:.0f}h",
                         style={"fontSize": "11px", "color": tc, "fontWeight": "600"}),
                html.Div(style={"height": "3px", "marginTop": "3px",
                                "width": f"{min(pct, 100):.0f}%",
                                "background": tc, "borderRadius": "2px"}),
            ])
            if est_h > 0:
                _cell_inner = html.Div(
                    _bar_content,
                    id={"type": "cap-matrix-cell", "person": person, "iter": iter_name},
                    n_clicks=0,
                    title=f"Click to see {person}'s items in {iter_name}",
                    style={"cursor": "pointer"},
                )
            else:
                _cell_inner = _bar_content
            cells.append(html.Td(
                _cell_inner,
                style={"background": bg, "textAlign": "center",
                       "padding": "6px 8px", "borderRadius": "4px"},
            ))
        t_rows.append(html.Tr(cells, style={"borderBottom": "1px solid rgba(255,255,255,0.04)"}))

    table = html.Table(
        [html.Thead(header), html.Tbody(t_rows)],
        style={"width": "100%", "borderCollapse": "separate",
               "borderSpacing": "0 2px", "fontSize": "12px"},
    )
    return html.Div(table, style={"overflowX": "auto"})


# ── Capacity matrix cell drill-down ───────────────────────────────────────────
@callback(
    Output("cap-matrix-drill-modal", "is_open"),
    Output("cap-matrix-drill-title", "children"),
    Output("cap-matrix-drill-body",  "children"),
    Input({"type": "cap-matrix-cell", "person": ALL, "iter": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def cap_matrix_drill(n_clicks_list):
    # Guard: ignore ghost-fires (n_clicks=0) or empty trigger
    if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
        return no_update, no_update, no_update
    triggered_val = ctx.triggered[0]["value"] if ctx.triggered else 0
    if not triggered_val:
        return no_update, no_update, no_update

    person    = ctx.triggered_id["person"]
    iter_name = ctx.triggered_id["iter"]

    # Load & filter data — keep raw copy for full iteration paths (needed for ADO write)
    df_raw = load_data()

    df = df_raw.copy()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    if "main_developer" in df.columns:
        df["main_developer"] = df["main_developer"].astype(str).str.split(" <").str[0]
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]

    person_col = "main_developer" if "main_developer" in df.columns else "assigned_to"
    df_cell = df[
        (df[person_col].replace("nan", "Unassigned").fillna("Unassigned") == person) &
        (df["iteration_path"] == iter_name)
    ].copy()

    title = f"{person} — {iter_name}"

    # Dropdown options for inline writeback controls
    all_iters = sorted(
        [i for i in df["iteration_path"].dropna().unique()
         if i not in ("Not Specified", "", "Unassigned")],
        reverse=True,
    )
    all_releases = sorted(
        [r for r in df["release_date"].dropna().unique()
         if r not in ("Not Specified", "", "Unassigned")],
        reverse=True,
    ) if "release_date" in df.columns else []

    if df_cell.empty:
        return True, title, html.P("No items found for this cell.",
                                   style={"color": "#718096", "padding": "16px 0"})

    # Classify rows
    is_bug = df_cell["work_item_type"].str.contains("Bug", na=False, case=False)
    is_enh = df_cell["work_item_type"].str.contains("Enhancement", na=False, case=False)
    bugs   = df_cell[is_bug]
    enhs   = df_cell[is_enh]
    others = df_cell[~is_bug & ~is_enh]

    disp_cols = [c for c in ["work_item_id", "title", "state", "priority",
                              "original_estimate", "remaining_work"]
                 if c in df_cell.columns]

    def _item_table(subset, label, accent):
        if subset.empty:
            return html.Div()
        est_t = pd.to_numeric(subset.get("original_estimate", 0), errors="coerce").fillna(0).sum()
        rem_t = pd.to_numeric(subset.get("remaining_work",    0), errors="coerce").fillna(0).sum()

        rows = []
        for _, row in subset.iterrows():  # full row — need iteration_path/release_date for dropdowns
            cells = []
            for c in disp_cols:
                v = row.get(c)
                na = v is None or (isinstance(v, float) and pd.isna(v))
                if c == "work_item_id":
                    cells.append(html.Td(
                        html.A(f"#{v}", href=f"{ADO_BASE_URL}{v}", target="_blank",
                               style={"color": "#7c6af4", "fontWeight": "600",
                                      "textDecoration": "none", "fontSize": "12px"})
                        if not na else "—", style=_TD_CAP))
                elif c == "title":
                    cells.append(html.Td(
                        str(v)[:75] if not na else "—",
                        style={**_TD_CAP, "maxWidth": "260px", "overflow": "hidden",
                               "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
                elif c in ("original_estimate", "remaining_work"):
                    num_v = pd.to_numeric(v, errors="coerce")
                    cells.append(html.Td(
                        f"{num_v:.0f}h" if pd.notna(num_v) and num_v > 0 else "—",
                        style={**_TD_CAP, "textAlign": "right", "fontFamily": "monospace"}))
                elif c == "priority":
                    p_map = {1: ("P1", "#f87171"), 2: ("P2", "#fbbf24"),
                             3: ("P3", "#60a5fa"), 4: ("P4", "#94a3b8")}
                    try:
                        pi = int(float(v)) if not na else 4
                    except Exception:
                        pi = 4
                    lbl, clr = p_map.get(pi, ("—", "#94a3b8"))
                    cells.append(html.Td(
                        html.Span(lbl, style={"background": f"{clr}22",
                                              "color": clr, "borderRadius": "4px",
                                              "padding": "2px 7px", "fontSize": "11px",
                                              "fontWeight": "700"}),
                        style=_TD_CAP))
                else:
                    cells.append(html.Td(str(v) if not na else "—",
                                         style={**_TD_CAP, "color": "#8888aa"}))

            # ── Writeback dropdowns ───────────────────────────────────────────
            wid = row.get("work_item_id")
            wid_safe = str(int(wid)) if (wid is not None and pd.notna(wid)) else "0"

            # Iteration dropdown — pre-populate with item's current iteration
            cur_iter = _strip_iter(str(row.get("iteration_path", "")))
            if cur_iter in ("Not Specified", "nan", "None", ""):
                cur_iter = iter_name
            cells.append(html.Td(
                dcc.Dropdown(
                    id={"type": "adj-iter-sel", "id": wid_safe},
                    options=[{"label": i, "value": i} for i in all_iters],
                    value=cur_iter if cur_iter in all_iters else None,
                    clearable=False, searchable=True,
                    className="adj-dark-dd",
                    style={"minWidth": "170px", "fontSize": "11px"},
                ) if wid_safe != "0" else html.Span("—"),
                style=_TD_CAP,
            ))

            # Release dropdown — pre-populate with item's current release
            cur_rel = str(row.get("release_date", "")) if "release_date" in row.index else ""
            if cur_rel in ("Not Specified", "nan", "None", ""):
                cur_rel = None
            cells.append(html.Td(
                dcc.Dropdown(
                    id={"type": "adj-rel-sel", "id": wid_safe},
                    options=[{"label": r, "value": r} for r in all_releases],
                    value=cur_rel if (cur_rel and cur_rel in all_releases) else None,
                    clearable=True, searchable=True,
                    placeholder="—",
                    className="adj-dark-dd",
                    style={"minWidth": "150px", "fontSize": "11px"},
                ) if wid_safe != "0" and all_releases else html.Span("—"),
                style=_TD_CAP,
            ))

            rows.append(html.Tr(cells,
                                style={"borderBottom": "1px solid rgba(255,255,255,0.04)"}))

        header_map = {"work_item_id": "ID", "original_estimate": "Est (h)",
                      "remaining_work": "Rem (h)"}
        all_header_labels = (
            [header_map.get(c, c.replace("_", " ").title()) for c in disp_cols]
            + ["Move Iteration", "Release"]
        )
        return html.Div([
            html.Div([
                html.Span(label,
                          style={"fontWeight": "700", "color": accent, "fontSize": "13px"}),
                html.Span(f" · {len(subset)} item{'s' if len(subset) != 1 else ''}",
                          style={"fontSize": "12px", "color": "#718096"}),
                html.Span(f" · Est {est_t:.0f}h  ·  Rem {rem_t:.0f}h",
                          style={"fontSize": "12px", "color": "#94a3b8", "marginLeft": "12px"}),
            ], style={"marginBottom": "8px", "marginTop": "20px",
                      "paddingBottom": "6px", "borderBottom": f"2px solid {accent}33"}),
            html.Div(
                html.Table([
                    html.Thead(html.Tr([
                        html.Th(lbl, style=_TH_CAP) for lbl in all_header_labels
                    ])),
                    html.Tbody(rows),
                ], style={"width": "100%", "borderCollapse": "collapse"}),
                style={"overflowX": "auto"},
            ),
        ])

    total_est = pd.to_numeric(df_cell.get("original_estimate", 0), errors="coerce").fillna(0).sum()
    total_rem = pd.to_numeric(df_cell.get("remaining_work",    0), errors="coerce").fillna(0).sum()
    bdays = get_iteration_bdays(iter_name)
    cap_h = bdays * 8
    pct   = total_est / cap_h * 100 if cap_h else 0
    pct_color = "#f87171" if pct > 110 else ("#fbbf24" if pct >= 80 else "#34d399")

    summary_bar = html.Div([
        html.Span(f"{len(df_cell)} items total",
                  style={"fontWeight": "600", "color": "#e2e8f0", "fontSize": "13px"}),
        html.Span(f" · Est {total_est:.0f}h / {cap_h:.0f}h capacity",
                  style={"color": "#94a3b8", "marginLeft": "12px", "fontSize": "13px"}),
        html.Span(f" · {pct:.0f}% loaded",
                  style={"color": pct_color, "fontWeight": "600",
                         "marginLeft": "12px", "fontSize": "13px"}),
        html.Span(f" · Rem {total_rem:.0f}h",
                  style={"color": "#64748b", "marginLeft": "12px", "fontSize": "12px"}),
    ], style={"padding": "10px 0 12px 0",
              "borderBottom": "1px solid rgba(255,255,255,0.08)", "marginBottom": "4px"})

    body = html.Div([
        summary_bar,
        _item_table(bugs,   "🐛 Bugs",         "#f87171"),
        _item_table(enhs,   "⚡ Enhancements",  "#fbbf24"),
        _item_table(others, "📋 Other",         "#818cf8"),
    ])
    return True, title, body


# ── Capacity adjuster — inline field writeback ─────────────────────────────────
@callback(
    Output("cap-adj-writeback-status", "children"),
    Input({"type": "adj-iter-sel", "id": ALL}, "value"),
    Input({"type": "adj-rel-sel",  "id": ALL}, "value"),
    prevent_initial_call=True,
)
def adj_field_change(iter_vals, rel_vals):
    """Write iteration or release change to local DB then fire ADO sync."""
    if not ctx.triggered_id or not isinstance(ctx.triggered_id, dict):
        return no_update
    triggered_type = ctx.triggered_id.get("type", "")
    wid_str        = ctx.triggered_id.get("id", "0")
    if not wid_str or wid_str == "0":
        return no_update
    new_val = ctx.triggered[0]["value"] if ctx.triggered else None
    if not new_val:
        return no_update

    try:
        wid = int(wid_str)
    except (ValueError, TypeError):
        return no_update

    _ok  = {"color": "#34d399", "fontWeight": "600", "fontSize": "12px"}
    _err = {"color": "#f87171", "fontSize": "12px"}

    df = load_data()

    if triggered_type == "adj-iter-sel":
        # Ghost-fire guard: skip if value matches what's already in DB
        if "iteration_path" in df.columns:
            row = df[df["work_item_id"] == wid]
            if not row.empty:
                if _strip_iter(str(row.iloc[0]["iteration_path"])) == new_val:
                    return no_update

        # Resolve full ADO iteration path for DB + ADO (DB stores full path)
        iter_path_map = _build_iter_path_map(df)
        full_path = iter_path_map.get(new_val, new_val)
        try:
            update_db_workitem(wid, "iteration_path", full_path)
        except Exception as e:
            return html.Span(f"❌ #{wid} DB error: {e}", style=_err)
        write_iteration(wid, full_path)
        return html.Span(
            f"✓ #{wid} iteration → '{new_val}'  (ADO sync queued)",
            style=_ok,
        )

    if triggered_type == "adj-rel-sel":
        # Ghost-fire guard
        if "release_date" in df.columns:
            row = df[df["work_item_id"] == wid]
            if not row.empty:
                cur_rel = str(row.iloc[0]["release_date"])
                if cur_rel in ("Not Specified", "nan", "None", ""):
                    cur_rel = None
                if cur_rel == new_val:
                    return no_update

        try:
            update_db_workitem(wid, "release_date", new_val)
        except Exception as e:
            return html.Span(f"❌ #{wid} DB error: {e}", style=_err)
        write_fields(wid, {"release_date": new_val})
        return html.Span(
            f"✓ #{wid} release → '{new_val}'  (ADO sync queued)",
            style=_ok,
        )

    return no_update


@callback(
    Output("cap-adj-gantt",                "figure"),
    Output("cap-adj-kpis",                 "children"),
    Output("cap-adj-breakdown",            "figure"),
    Output("cap-adj-burndown",             "figure"),
    Output("cap-adj-workload",             "children"),
    Output("cap-adj-cap-matrix",           "children"),
    Output("cap-adj-move-table-container", "children"),
    Output("cap-adj-move-btn",             "disabled"),
    Input("cap-pl-active-section",         "data"),
    Input("cap-adj-view-mode",             "value"),
    Input("cap-adj-iter",                  "value"),
    Input("cap-adj-release",               "value"),
    Input("cap-adj-team",                  "value"),
    Input("cap-adj-groupby",               "value"),
    Input("cap-adj-hours-day",             "value"),
)
def _render_adjuster(active, mode, iteration, release, team, groupby, hours_day):
    if active != "adjuster":
        return (no_update,) * 8

    df = load_data()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    if "main_developer" in df.columns:
        df["main_developer"] = df["main_developer"].astype(str).str.split(" <").str[0]

    if team and team != "All" and "main_dev_team" in df.columns:
        df = df[df["main_dev_team"] == team]

    selected  = iteration if mode == "iteration" else release
    hours_day = hours_day or 8

    # Gantt
    gantt_fig = _build_item_gantt(df, groupby or "person", selected, mode, hours_day)

    # Scope for detail charts
    if mode == "iteration" and iteration and "iteration_path" in df.columns:
        df_sel = df[df["iteration_path"] == iteration].copy()
    elif mode == "release" and release and "release_date" in df.columns:
        df_sel = df[df["release_date"] == release].copy()
    else:
        df_sel = pd.DataFrame()

    # KPI chips
    if not df_sel.empty:
        total      = len(df_sel)
        done_ct    = int(df_sel["state"].isin(_ADO_DONE_STATES).sum()) if "state" in df_sel.columns else 0
        blocked_ct = int(df_sel["state"].isin({"Watch List", "On Hold", "Rare Scenario"}).sum()) if "state" in df_sel.columns else 0
        est_h      = pd.to_numeric(df_sel.get("original_estimate", 0), errors="coerce").fillna(0).sum()
        cmp_h      = pd.to_numeric(df_sel.get("completed_work",    0), errors="coerce").fillna(0).sum()
        rem_h      = pd.to_numeric(df_sel.get("remaining_work",    0), errors="coerce").fillna(0).sum()
        done_pct   = round(done_ct / total * 100) if total else 0
        kpis = [
            _summary_chip("Items",    total),
            _summary_chip("Done",     f"{done_ct} ({done_pct}%)", "#34d399"),
            _summary_chip("Blocked",  int(blocked_ct), "#f87171" if blocked_ct else "#64748b"),
            _summary_chip("Est (h)",  f"{est_h:.0f}h", "#818cf8"),
            _summary_chip("Done (h)", f"{cmp_h:.0f}h", "#34d399"),
            _summary_chip("Rem (h)",  f"{rem_h:.0f}h", "#fb923c" if rem_h > 0 else "#64748b"),
        ]
    else:
        kpis = [html.Div("Select an iteration or release above to see details.",
                         style={"fontSize": "12px", "color": "#64748b"})]

    # Detail charts (iteration mode only for burndown)
    if not df_sel.empty and mode == "iteration" and iteration:
        breakdown = _build_ado_breakdown(df_sel)
        burndown  = _build_ado_burndown(df_sel, iteration)
        workload  = _build_ado_workload(df_sel)
    elif not df_sel.empty:
        breakdown = _build_ado_breakdown(df_sel)
        burndown  = _empty_fig("Burndown available for iteration view only")
        workload  = _build_ado_workload(df_sel)
    else:
        breakdown = _empty_fig("Select an iteration or release")
        burndown  = _empty_fig("Select an iteration or release")
        workload  = html.Div("Select an iteration or release to see workload.",
                             style={"fontSize": "12px", "color": "#64748b"})

    # Capacity matrix
    cap_matrix = _build_adj_cap_matrix(df, hours_day)

    # Move table
    if df_sel.empty:
        move_table       = html.Div("Select an iteration or release above to load items.",
                                    style={"color": "#64748b", "fontSize": "13px"})
        move_btn_disabled = True
    else:
        cols_show = ["work_item_id", "work_item_type", "title", "state",
                     "assigned_to", "original_estimate", "remaining_work"]
        cols_show = [c for c in cols_show if c in df_sel.columns]
        col_labels = {
            "work_item_id":      "ID",
            "work_item_type":    "Type",
            "title":             "Title",
            "state":             "State",
            "assigned_to":       "Assignee",
            "original_estimate": "Est (h)",
            "remaining_work":    "Rem (h)",
        }
        col_defs = [{"name": col_labels.get(c, c), "id": c} for c in cols_show]
        move_table = dash_table.DataTable(
            id="cap-adj-move-table",
            data=df_sel[cols_show].fillna("").to_dict("records"),
            columns=col_defs,
            style_cell_conditional=[
                {"if": {"column_id": "work_item_id"}, "maxWidth": "80px",  "width": "80px"},
                {"if": {"column_id": "title"},        "maxWidth": "400px", "width": "400px"},
            ],
            **_dt_style(),
        )
        move_btn_disabled = False

    return (gantt_fig, kpis, breakdown, burndown,
            workload, cap_matrix, move_table, move_btn_disabled)


@callback(
    Output("cap-adj-iter",     "value", allow_duplicate=True),
    Output("cap-adj-release",  "value", allow_duplicate=True),
    Input("cap-adj-gantt",     "clickData"),
    State("cap-adj-view-mode", "value"),
    prevent_initial_call=True,
)
def _adj_gantt_click(click_data, mode):
    """Click a Gantt bar → select that iteration/release in the filter."""
    if not click_data:
        return no_update, no_update
    try:
        win_label = click_data["points"][0]["customdata"][0]
        return (win_label, no_update) if mode == "iteration" else (no_update, win_label)
    except Exception:
        return no_update, no_update


@callback(
    Output("cap-adj-move-feedback", "children"),
    Input("cap-adj-move-btn",       "n_clicks"),
    State("cap-adj-move-table",     "selected_rows"),
    State("cap-adj-move-table",     "data"),
    State("cap-adj-move-tgt",       "value"),
    prevent_initial_call=True,
)
def _adj_move_execute(n_clicks, selected_rows, table_data, tgt_iter):
    if not selected_rows:
        return html.Span("⚠ Select at least one item.", style={"color": "#fb923c"})
    if not tgt_iter:
        return html.Span("⚠ Select a target iteration.", style={"color": "#fb923c"})

    df       = load_data()
    paths    = _build_iter_path_map(df)
    tgt_full = paths.get(tgt_iter, tgt_iter)

    from sync.ado_write import write_fields_sync
    ok_ids, fail_ids = [], []
    for idx in selected_rows:
        row    = table_data[idx]
        ado_id = int(row["work_item_id"])
        ok, _  = write_fields_sync(ado_id, {"iteration": tgt_full})
        (ok_ids if ok else fail_ids).append(ado_id)

    parts = []
    if ok_ids:
        parts.append(html.Span(f"✓ Moved {len(ok_ids)} item(s) to {tgt_iter}.",
                               style={"color": "#34d399", "marginRight": "12px"}))
    if fail_ids:
        parts.append(html.Span(f"✗ Failed: #{', #'.join(map(str, fail_ids))}",
                               style={"color": "#f87171"}))
    return html.Div(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# BACKLOG
# ═══════════════════════════════════════════════════════════════════════════════

@callback(
    Output("cap-pl-backlog-table-container", "children"),
    Output("cap-pl-backlog-btn",             "disabled"),
    Input("cap-pl-active-section",           "data"),
)
def _render_backlog(active_section):
    if active_section != "backlog":
        return no_update, no_update

    df = load_data()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)

    backlog = df[
        df["iteration_path"].isna() |
        df["iteration_path"].isin(["Not Specified", "", "Backlog", "Phase 4 Backlog"])
    ].copy()

    if backlog.empty:
        return html.Div("No backlog items found. Everything is assigned to an iteration! 🎉",
                        style={"color": "#34d399", "fontSize": "13px"}), True

    if "assigned_to" in backlog.columns:
        backlog["assigned_to"] = backlog["assigned_to"].astype(str).str.split(" <").str[0]

    cols_show = ["work_item_id", "work_item_type", "title", "state",
                 "assigned_to", "original_estimate", "iteration_path"]
    cols_show = [c for c in cols_show if c in backlog.columns]
    col_labels = {
        "work_item_id": "ID", "work_item_type": "Type", "title": "Title",
        "state": "State", "assigned_to": "Assignee",
        "original_estimate": "Est (h)", "iteration_path": "Current Iteration",
    }
    col_defs = [{"name": col_labels.get(c, c), "id": c} for c in cols_show]

    tbl = dash_table.DataTable(
        id="cap-pl-backlog-table",
        data=backlog[cols_show].fillna("").to_dict("records"),
        columns=col_defs,
        style_cell_conditional=[
            {"if": {"column_id": "work_item_id"},   "maxWidth": "80px",  "width": "80px"},
            {"if": {"column_id": "title"},           "maxWidth": "400px", "width": "400px"},
            {"if": {"column_id": "iteration_path"},  "maxWidth": "200px", "width": "200px"},
        ],
        **_dt_style(),
    )
    return tbl, False


@callback(
    Output("cap-pl-backlog-feedback", "children"),
    Input("cap-pl-backlog-btn",       "n_clicks"),
    State("cap-pl-backlog-table",     "selected_rows"),
    State("cap-pl-backlog-table",     "data"),
    State("cap-pl-backlog-tgt",       "value"),
    prevent_initial_call=True,
)
def _backlog_assign(n_clicks, selected_rows, table_data, tgt_iter):
    if not selected_rows:
        return html.Span("⚠ Select at least one item.", style={"color": "#fb923c"})
    if not tgt_iter:
        return html.Span("⚠ Select a target iteration.", style={"color": "#fb923c"})

    df      = load_data()
    paths   = _build_iter_path_map(df)
    tgt_full = paths.get(tgt_iter, tgt_iter)

    from sync.ado_write import write_fields_sync
    ok_ids, fail_ids = [], []
    for idx in selected_rows:
        row    = table_data[idx]
        ado_id = int(row["work_item_id"])
        ok, _  = write_fields_sync(ado_id, {"iteration": tgt_full})
        (ok_ids if ok else fail_ids).append(ado_id)

    parts = []
    if ok_ids:
        parts.append(html.Span(f"✓ Assigned {len(ok_ids)} item(s) to {tgt_iter}.",
                               style={"color": "#34d399", "marginRight": "12px"}))
    if fail_ids:
        parts.append(html.Span(f"✗ Failed: #{', #'.join(map(str, fail_ids))}",
                               style={"color": "#f87171"}))
    return html.Div(parts)
