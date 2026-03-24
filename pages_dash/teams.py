"""Teams Dashboard — Team delivery output, workload execution, and defect fixing pace."""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data, apply_filters, filter_activity_since
from config.settings import ANALYSIS_START_DATE

dash.register_page(__name__, path="/teams", name="Teams")

CLOSED_STATES   = {"Closed"}
REJECTED_STATES = {"Not an issue", "Not Required"}


# ── Helpers ────────────────────────────────────────────────────────────────────
def _strip_iter(x):
    if pd.notna(x) and str(x) not in ("Not Specified", ""):
        return str(x).split("\\")[-1]
    return x


def _section_label(text):
    return html.Div(text, style={
        "fontSize": "11px", "fontWeight": "700", "textTransform": "uppercase",
        "letterSpacing": "0.8px", "color": "#a0aec0",
        "marginBottom": "12px", "marginTop": "4px",
    })


def _empty_fig(msg="No data"):
    return go.Figure().update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis_visible=False, yaxis_visible=False,
        annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                          font=dict(size=14, color="#a0aec0"))],
    )


# ── Layout ─────────────────────────────────────────────────────────────────────
def layout():
    df = load_data()
    teams = (["All"] + sorted([t for t in df["team"].dropna().unique() if t != "Unassigned"])
             if "team" in df.columns else ["All"])

    _fb = {
        "background": "#ffffff", "borderRadius": "10px", "padding": "14px 18px",
        "boxShadow": "0 1px 3px rgba(0,0,0,0.08)", "border": "1px solid #e8ecf0",
        "marginBottom": "20px",
    }
    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([
                html.Div("Team", className="filter-label"),
                dcc.Dropdown(id="teams-team",
                             options=[{"label": t, "value": t} for t in teams],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=8),
            dbc.Col([
                html.Div("Throughput Grouping", className="filter-label"),
                dcc.Dropdown(id="teams-grouping",
                             options=[{"label": "Weekly",       "value": "Weekly"},
                                      {"label": "By Iteration", "value": "By Iteration"}],
                             value="Weekly", clearable=False, style={"fontSize": "12px"}),
            ], md=4),
        ], className="g-2"),
    ], style=_fb)

    return html.Div([
        html.Div([
            html.H1("👥 Team Delivery", className="page-title"),
            html.P("Measure what teams are shipping, their balance of feature work vs bugs, and individual workloads.",
                   className="page-subtitle"),
        ], className="page-header"),

        filter_bar,

        # ── KPIs ──────────────────────────────────────────────────────────────
        _section_label("At a Glance"),
        html.Div(id="teams-kpi-row", className="mb-4"),
        html.Hr(className="section-divider"),

        # ── What are we building? ─────────────────────────────────────────────
        _section_label("What Are We Building?"),
        html.P("Breakdown of completed hours by work item type (features vs defect fixes).",
               style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
        html.Div(dcc.Graph(id="teams-type-breakdown"), className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Delivery Pace & Backlog ────────────────────────────────────────────
        _section_label("Delivery Pace & Backlog"),
        dbc.Row([
            dbc.Col(html.Div(dcc.Graph(id="teams-throughput"), className="chart-card"), md=6),
            dbc.Col(html.Div(dcc.Graph(id="teams-wip"),        className="chart-card"), md=6),
        ], className="mb-4"),
        html.Hr(className="section-divider"),

        # ── Member Execution & Workload ────────────────────────────────────────
        _section_label("Member Execution & Workload"),
        html.P("Who is completing the work, and what does their remaining queue look like?",
               style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
        html.Div(dcc.Graph(id="teams-member-tp"), className="chart-card mb-4"),
        html.Div(dcc.Graph(id="teams-workload"),  className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Bug Fixing Focus ───────────────────────────────────────────────────
        _section_label("Top Buggy Functions (Team Focus Area)"),
        html.P("Where is this team spending their bug-fixing time?",
               style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
        html.Div(dcc.Graph(id="teams-top-funcs"), className="chart-card mb-4"),
    ])


# ── Callback ───────────────────────────────────────────────────────────────────
@callback(
    Output("teams-kpi-row",        "children"),
    Output("teams-type-breakdown", "figure"),
    Output("teams-throughput",     "figure"),
    Output("teams-wip",            "figure"),
    Output("teams-member-tp",      "figure"),
    Output("teams-workload",       "figure"),
    Output("teams-top-funcs",      "figure"),
    Input("teams-team",     "value"),
    Input("teams-grouping", "value"),
)
def update_teams(team, grouping):
    df = load_data()
    df = apply_filters(df, team=team if team != "All" else None)
    df = filter_activity_since(df, ANALYSIS_START_DATE)

    df_team = df[df["team"] == team].copy() if (team != "All" and "team" in df.columns) else df.copy()

    if "assigned_to" in df_team.columns:
        df_team["assigned_to"] = df_team["assigned_to"].astype(str).str.split(" <").str[0]
    if "iteration_path" in df_team.columns:
        df_team["iteration_path"] = df_team["iteration_path"].apply(_strip_iter)

    def num(col, src=None):
        src = src if src is not None else df_team
        return pd.to_numeric(src.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0)

    # ── KPIs ───────────────────────────────────────────────────────────────────
    assigned = num("original_estimate").sum()
    comp     = num("completed_work").sum()
    rem      = max(assigned - comp, 0)
    comp_pct = comp / assigned * 100 if assigned > 0 else 0

    unique_members = df_team["assigned_to"].dropna().nunique() if "assigned_to" in df_team.columns else 0
    open_items   = len(df_team[~df_team["state"].isin(CLOSED_STATES | REJECTED_STATES)]) if "state" in df_team.columns else 0
    closed_items = len(df_team[df_team["state"].isin(CLOSED_STATES)]) if "state" in df_team.columns else 0

    bug_ratio = 0.0
    if "work_item_type" in df_team.columns and comp > 0:
        bug_comp = num("completed_work", df_team[df_team["work_item_type"].str.contains("Bug", na=False, case=False)]).sum()
        bug_ratio = bug_comp / comp * 100

    def _kpi(label, val, cls="", subtitle=None):
        children = [
            html.Div(label, className="metric-label"),
            html.Div(str(val), className=f"metric-value {cls}"),
        ]
        if subtitle:
            children.append(html.Div(subtitle, className="kpi-subtitle"))
        return dbc.Col(html.Div(children, className="metric-card"), md=3)

    kpi_row = html.Div([
        dbc.Row([
            _kpi("Headcount",    str(unique_members)),
            _kpi("Assigned (h)", f"{assigned:,.0f}"),
            _kpi("Completed (h)", f"{comp:,.0f}", cls="success"),
            _kpi("Remaining (h)", f"{rem:,.0f}",
                 cls="warning" if rem > 0 else ""),
        ], className="g-3 mb-3"),
        dbc.Row([
            _kpi("Completion %", f"{comp_pct:.1f}%",
                 cls="" if comp_pct >= 70 else "warning"),
            _kpi("Bug Fix Ratio", f"{bug_ratio:.1f}%",
                 cls="warning" if bug_ratio > 40 else "",
                 subtitle="% of completed hours on bugs"),
            _kpi("Open Items",   str(open_items)),
            _kpi("Closed Items", str(closed_items)),
        ], className="g-3"),
    ])

    # ── 1. Type Breakdown ─────────────────────────────────────────────────────
    if "work_item_type" in df_team.columns and "completed_work" in df_team.columns:
        tb = df_team.copy()
        tb["comp"] = num("completed_work", tb)
        tb["Type"] = tb["work_item_type"].replace({"Bug_UI": "Bug", "Bug_Text": "Bug"})
        type_grp = tb.groupby("Type")["comp"].sum().reset_index()
        type_grp = type_grp[type_grp["comp"] > 0].sort_values("comp", ascending=True)
        if not type_grp.empty:
            COLOR_MAP = {"Bug": "#c06060", "Enhancement": "#3d9e6b",
                         "Task": "#5a8fd4", "Feature": "#9f7aea"}
            colors = [COLOR_MAP.get(t, "#a0aec0") for t in type_grp["Type"]]
            fig_types = go.Figure(go.Bar(
                x=type_grp["comp"], y=type_grp["Type"], orientation="h",
                marker_color=colors,
                text=type_grp["comp"].apply(lambda v: f"{v:,.0f}h"),
                textposition="outside", textfont=dict(size=11),
                hovertemplate="%{y}: %{x:,.0f}h<extra></extra>",
            ))
            fig_types.update_layout(
                title="Completed Hours by Item Type",
                height=max(len(type_grp) * 42 + 120, 250),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=40, l=185, r=80),
            )
            fig_types.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
            fig_types.update_yaxes(tickfont=dict(size=13))
        else:
            fig_types = _empty_fig("No completed work by type")
    else:
        fig_types = _empty_fig()

    # ── 2. Team Throughput ────────────────────────────────────────────────────
    if {"closed_date", "completed_work"}.issubset(df_team.columns):
        d = df_team.dropna(subset=["closed_date"]).copy()
        d["week"] = pd.to_datetime(d["closed_date"], errors="coerce").dt.to_period("W").dt.start_time
        d["comp"] = num("completed_work", d)
        weekly = d.groupby("week")["comp"].sum().reset_index()
        if not weekly.empty:
            fig_tp = px.line(weekly, x="week", y="comp", markers=True,
                             title="Team Output (Completed Hours / Week)",
                             color_discrete_sequence=["#5a8fd4"],
                             labels={"week": "", "comp": "Hours"})
            fig_tp.update_layout(height=380, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                 margin=dict(t=50, b=80, l=60, r=20))
            fig_tp.update_xaxes(tickangle=-35, tickfont=dict(size=12))
            fig_tp.update_yaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12))
        else:
            fig_tp = _empty_fig("No throughput data")
    else:
        fig_tp = _empty_fig()

    # ── 3. Team WIP ───────────────────────────────────────────────────────────
    if {"created_date", "closed_date"}.issubset(df_team.columns):
        d2 = df_team.copy()
        d2["created_date"] = pd.to_datetime(d2["created_date"], errors="coerce")
        d2["closed_date"]  = pd.to_datetime(d2["closed_date"],  errors="coerce")
        today = pd.Timestamp.today().normalize()
        st    = max(d2["created_date"].dropna().min(), pd.to_datetime(ANALYSIS_START_DATE))
        max_c  = d2["created_date"].dropna().max()
        max_cl = d2["closed_date"].dropna().max()
        en = min(max(max_c, max_cl) if pd.notna(max_cl) else max_c, today)
        if pd.notna(st) and pd.notna(en) and st <= en:
            weeks = pd.date_range(st.normalize(), en.normalize(), freq="W-MON")
            oc = [
                int(((d2["created_date"] <= wk + pd.Timedelta(6)) &
                     (d2["closed_date"].isna() | (d2["closed_date"] > wk + pd.Timedelta(6)))).sum())
                for wk in weeks
            ]
            if any(oc):
                fig_wip = px.area(
                    pd.DataFrame({"week": weeks, "open": oc}),
                    x="week", y="open", title="Team Open Backlog Trend",
                    color_discrete_sequence=["#7c69d4"],
                    labels={"week": "", "open": "Open Items"},
                )
                fig_wip.update_layout(height=380, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                      margin=dict(t=50, b=80, l=60, r=20))
                fig_wip.update_xaxes(tickangle=-35, tickfont=dict(size=12))
                fig_wip.update_yaxes(title="Open Items", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12))
            else:
                fig_wip = _empty_fig("No backlog trend data")
        else:
            fig_wip = _empty_fig("Insufficient date range")
    else:
        fig_wip = _empty_fig()

    # ── 4. Member Throughput ──────────────────────────────────────────────────
    if "completed_work" in df_team.columns:
        d3 = df_team.copy()
        d3["comp"] = num("completed_work", d3)

        if grouping == "By Iteration" and "iteration_path" in d3.columns:
            g = d3.groupby(["iteration_path", "assigned_to"])["comp"].sum().reset_index()
            if not g.empty:
                fig_mtp = px.bar(
                    g, x="iteration_path", y="comp", color="assigned_to", barmode="group",
                    title="Member Throughput by Iteration",
                    labels={"iteration_path": "", "comp": "Completed Hours"},
                )
                fig_mtp.update_layout(
                    height=450, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=90, b=120, l=60, r=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                fig_mtp.update_xaxes(tickangle=-35, tickfont=dict(size=13))
                fig_mtp.update_yaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
            else:
                fig_mtp = _empty_fig("No member throughput data")
        else:
            g = d3.groupby("assigned_to")["comp"].sum().reset_index().sort_values("comp", ascending=True)
            if not g.empty:
                fig_mtp = go.Figure(go.Bar(
                    x=g["comp"], y=g["assigned_to"], orientation="h",
                    marker_color="#5a8fd4",
                    text=g["comp"].apply(lambda v: f"{v:,.0f}h"),
                    textposition="outside", textfont=dict(size=11),
                    hovertemplate="%{y}: %{x:,.0f}h<extra></extra>",
                ))
                fig_mtp.update_layout(
                    title="Total Member Output (Hours Logged)",
                    height=max(len(g) * 42 + 120, 300),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=50, b=40, l=185, r=80),
                )
                fig_mtp.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
                fig_mtp.update_yaxes(tickfont=dict(size=13))
            else:
                fig_mtp = _empty_fig("No member output data")
    else:
        fig_mtp = _empty_fig()

    # ── 5. Member Workload Dot-Plot ────────────────────────────────────────────
    if {"assigned_to", "original_estimate", "completed_work"}.issubset(df_team.columns):
        d4 = df_team.copy()
        d4["orig"] = num("original_estimate", d4)
        d4["comp"] = num("completed_work",    d4)
        g4 = d4.groupby("assigned_to")[["orig", "comp"]].sum().reset_index()
        g4["rem"] = (g4["orig"] - g4["comp"]).clip(lower=0)
        long = g4.melt(id_vars="assigned_to", value_vars=["orig", "comp", "rem"],
                       var_name="Type", value_name="Hours").replace(
            {"orig": "Assigned", "comp": "Completed", "rem": "Remaining"})
        if not long.empty:
            fig_wl = px.scatter(
                long, x="Hours", y="assigned_to", color="Type", opacity=0.85,
                title="Member Workload Pipeline",
                color_discrete_map={"Assigned": "#5a8fd4", "Completed": "#3d9e6b", "Remaining": "#c06060"},
            )
            fig_wl.update_traces(marker=dict(size=12))
            fig_wl.update_layout(
                height=max(len(g4) * 42 + 120, 300),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=90, b=60, l=185, r=40),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            fig_wl.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
            fig_wl.update_yaxes(tickfont=dict(size=12))
        else:
            fig_wl = _empty_fig("No workload data")
    else:
        fig_wl = _empty_fig()

    # ── 6. Top Buggy Functions ─────────────────────────────────────────────────
    if "work_item_type" in df_team.columns:
        bugs = df_team[df_team["work_item_type"].str.contains("Bug", na=False, case=False)]
    else:
        bugs = pd.DataFrame()

    if "function" in bugs.columns and not bugs.empty:
        fc = bugs["function"].value_counts().head(10).sort_values(ascending=True)
        if not fc.empty:
            fig_funcs = go.Figure(go.Bar(
                x=fc.values, y=fc.index, orientation="h",
                marker_color="#c05050",
                text=fc.values.astype(str),
                textposition="outside", textfont=dict(size=11),
                hovertemplate="%{y}: %{x} bugs<extra></extra>",
            ))
            fig_funcs.update_layout(
                title="Top Buggy Functions (Bug Count)",
                height=max(len(fc) * 42 + 120, 280),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=40, l=185, r=60),
            )
            fig_funcs.update_xaxes(title="Bug Count", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
            fig_funcs.update_yaxes(tickfont=dict(size=13))
        else:
            fig_funcs = _empty_fig("No buggy function data")
    else:
        fig_funcs = _empty_fig("No function data for bugs")

    return (kpi_row, fig_types, fig_tp, fig_wip, fig_mtp, fig_wl, fig_funcs)
