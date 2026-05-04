"""Teams Dashboard — Select a team to see its specific delivery, quality, and workload metrics."""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data, apply_filters, filter_activity_since
from config.settings import ANALYSIS_START_DATE
from config.team_mapping import TEAM_MAPPING, TEAM_TYPES, TEAMS_LIST, QA_TEAM_MEMBERS

dash.register_page(__name__, path="/teams", name="Teams")

CLOSED_STATES   = {"Closed"}
REJECTED_STATES = {"Not an issue", "Not Required", "No Customer Response"}
CLOSED_ALL      = CLOSED_STATES | REJECTED_STATES | {"Userstory Update"}
SLA_DAYS        = {1: 1, 2: 2, 3: 5, 4: 10}   # QA SLA targets by priority

QA_STATES = {
    "Tester Assigned", "Dev Complete", "Dev Review", "Resolved"
}
DEV_ACTIVE_STATES = {"Dev InProgress", "Dev Review", "Dev Complete", "Active"}


# ── Helpers ────────────────────────────────────────────────────────────────────
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


def _kpi(label, val, cls="", subtitle=None):
    children = [
        html.Div(label, className="metric-label"),
        html.Div(str(val), className=f"metric-value {cls}"),
    ]
    if subtitle:
        children.append(html.Div(subtitle, className="kpi-subtitle"))
    return dbc.Col(html.Div(children, className="metric-card"), md=3)


_sb = {
    "background": "rgba(255,255,255,0.015)",
    "borderRadius": "12px",
    "border": "1px solid rgba(255,255,255,0.04)",
    "padding": "20px 20px 12px 20px",
    "marginBottom": "24px",
}


# ── Layout ─────────────────────────────────────────────────────────────────────
def layout():
    df    = load_data()
    teams = sorted([t for t in TEAMS_LIST if t in df.get("team", pd.Series()).unique()])
    if not teams:
        teams = TEAMS_LIST
    default_team = teams[0]

    _fb_style = {
        "background": "#1c1c27", "borderRadius": "10px", "padding": "14px 18px",
        "border": "1px solid rgba(255,255,255,0.07)", "marginBottom": "20px",
    }

    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([
                html.Div("Team", className="filter-label"),
                dcc.Dropdown(id="teams-team",
                             options=[{"label": t, "value": t} for t in teams],
                             value=default_team, clearable=False,
                             style={"fontSize": "12px"}),
            ], md=6),
            dbc.Col([
                html.Div("Throughput Grouping", className="filter-label"),
                dcc.Dropdown(id="teams-grouping",
                             options=[{"label": "Weekly",       "value": "Weekly"},
                                      {"label": "By Iteration", "value": "By Iteration"}],
                             value="Weekly", clearable=False,
                             style={"fontSize": "12px"}),
            ], md=6),
        ], className="g-2"),
    ], style=_fb_style)

    return html.Div([
        filter_bar,

        # ── KPIs ──────────────────────────────────────────────────────────────
        html.Div([
            _section_label("At a Glance"),
            html.Div(id="teams-kpi-row"),
        ], style=_sb),

        # ── Delivery Pace ─────────────────────────────────────────────────────
        html.Div([
            _section_label("Delivery Pace & Backlog"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(id="teams-throughput"), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(id="teams-wip"),        className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),

        # ── Member Execution & Workload ────────────────────────────────────────
        html.Div([
            _section_label("Member Execution & Workload"),
            html.Div(dcc.Graph(id="teams-member-tp"), className="chart-card mb-3"),
            html.Div(dcc.Graph(id="teams-workload"),  className="chart-card"),
        ], style=_sb),

        # ── Team-type specific section (QA / Dev / Design / Management) ───────
        html.Div(id="teams-specific-content"),
    ])


# ── Callback ───────────────────────────────────────────────────────────────────
@callback(
    Output("teams-kpi-row",          "children"),
    Output("teams-throughput",        "figure"),
    Output("teams-wip",               "figure"),
    Output("teams-member-tp",         "figure"),
    Output("teams-workload",          "figure"),
    Output("teams-specific-content",  "children"),
    Input("teams-team",     "value"),
    Input("teams-grouping", "value"),
)
def update_teams(team, grouping):
    df = load_data()
    df = filter_activity_since(df, ANALYSIS_START_DATE)

    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)

    df_team = df[df["team"] == team].copy() if (team and "team" in df.columns) else df.copy()

    team_type = TEAM_TYPES.get(team, "dev")

    def num(col, src=None):
        src = src if src is not None else df_team
        return pd.to_numeric(src.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0)

    # ── KPIs (common base + type-specific extras) ──────────────────────────────
    assigned = num("original_estimate").sum()
    comp     = num("completed_work").sum()
    rem      = max(assigned - comp, 0)
    comp_pct = comp / assigned * 100 if assigned > 0 else 0

    members      = df_team["assigned_to"].dropna().nunique() if "assigned_to" in df_team.columns else 0
    open_items   = int((~df_team["state"].isin(CLOSED_ALL)).sum()) if "state" in df_team.columns else 0
    closed_items = int(df_team["state"].eq("Closed").sum()) if "state" in df_team.columns else 0

    if team_type == "qa":
        # Bug-specific KPIs for QA
        bugs = df_team[df_team.get("work_item_type", pd.Series()).str.contains("Bug", na=False, case=False)] \
            if "work_item_type" in df_team.columns else df_team
        p1_open = int((bugs[~bugs["state"].isin(CLOSED_ALL)]["priority"] == 1).sum()) \
            if "priority" in bugs.columns else 0
        reopen  = int(bugs["state"].eq("Reopened").sum()) if "state" in bugs.columns else 0
        kpi_row = html.Div([
            dbc.Row([
                _kpi("Headcount",     str(members)),
                _kpi("Open Bugs",     str(open_items),
                     cls="danger" if open_items > 20 else "warning" if open_items > 5 else "success"),
                _kpi("P1 Open",       str(p1_open),
                     cls="danger" if p1_open > 0 else "success"),
                _kpi("Reopened",      str(reopen),
                     cls="warning" if reopen > 0 else "success",
                     subtitle="Bugs reopened after close"),
            ], className="g-3 mb-3"),
            dbc.Row([
                _kpi("Closed (All Time)", str(closed_items), cls="success"),
                _kpi("Completion %",      f"{comp_pct:.1f}%",
                     cls="success" if comp_pct >= 70 else "warning"),
                _kpi("Assigned (h)",      f"{assigned:,.0f}"),
                _kpi("Completed (h)",     f"{comp:,.0f}", cls="success"),
            ], className="g-3"),
        ])
    elif team_type in ("dev", "design"):
        # Cycle time for dev/design
        closed = df_team[df_team["state"] == "Closed"].copy() if "state" in df_team.columns else pd.DataFrame()
        if not closed.empty and {"created_date", "closed_date"}.issubset(closed.columns):
            closed["created_date"] = pd.to_datetime(closed["created_date"], errors="coerce")
            closed["closed_date"]  = pd.to_datetime(closed["closed_date"],  errors="coerce")
            avg_cycle = (closed["closed_date"] - closed["created_date"]).dt.days.mean()
            cycle_str = f"{avg_cycle:.1f}d" if pd.notna(avg_cycle) else "—"
        else:
            cycle_str = "—"

        kpi_row = html.Div([
            dbc.Row([
                _kpi("Headcount",     str(members)),
                _kpi("Open Items",    str(open_items)),
                _kpi("Closed Items",  str(closed_items), cls="success"),
                _kpi("Avg Cycle Time", cycle_str,
                     subtitle="Created → Closed"),
            ], className="g-3 mb-3"),
            dbc.Row([
                _kpi("Assigned (h)",  f"{assigned:,.0f}"),
                _kpi("Completed (h)", f"{comp:,.0f}", cls="success"),
                _kpi("Remaining (h)", f"{rem:,.0f}",
                     cls="warning" if rem > 0 else ""),
                _kpi("Completion %",  f"{comp_pct:.1f}%",
                     cls="success" if comp_pct >= 70 else "warning"),
            ], className="g-3"),
        ])
    else:
        # Management — simple overview
        kpi_row = html.Div([
            dbc.Row([
                _kpi("Headcount",     str(members)),
                _kpi("Open Items",    str(open_items)),
                _kpi("Closed Items",  str(closed_items), cls="success"),
                _kpi("Completion %",  f"{comp_pct:.1f}%",
                     cls="success" if comp_pct >= 70 else "warning"),
            ], className="g-3 mb-3"),
            dbc.Row([
                _kpi("Assigned (h)",  f"{assigned:,.0f}"),
                _kpi("Completed (h)", f"{comp:,.0f}", cls="success"),
                _kpi("Remaining (h)", f"{rem:,.0f}",
                     cls="warning" if rem > 0 else ""),
                _kpi("Bug Fix Ratio", f"{(num('completed_work', df_team[df_team.get('work_item_type', pd.Series()).str.contains('Bug', na=False)]).sum() / comp * 100) if comp > 0 and 'work_item_type' in df_team.columns else 0:.1f}%",
                     subtitle="% hours on bugs"),
            ], className="g-3"),
        ])

    # ── Throughput ─────────────────────────────────────────────────────────────
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
            fig_tp.update_layout(height=360, plot_bgcolor="rgba(0,0,0,0)",
                                 paper_bgcolor="rgba(0,0,0,0)",
                                 margin=dict(t=50, b=80, l=60, r=20))
            fig_tp.update_xaxes(tickangle=-35, tickfont=dict(size=12))
            fig_tp.update_yaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)")
        else:
            fig_tp = _empty_fig("No throughput data")
    else:
        fig_tp = _empty_fig()

    # ── WIP ────────────────────────────────────────────────────────────────────
    if {"created_date", "closed_date"}.issubset(df_team.columns):
        d2 = df_team.copy()
        d2["created_date"] = pd.to_datetime(d2["created_date"], errors="coerce")
        d2["closed_date"]  = pd.to_datetime(d2["closed_date"],  errors="coerce")
        today  = pd.Timestamp.today().normalize()
        st     = max(d2["created_date"].dropna().min(), pd.to_datetime(ANALYSIS_START_DATE))
        max_c  = d2["created_date"].dropna().max()
        max_cl = d2["closed_date"].dropna().max()
        en     = min(max(max_c, max_cl) if pd.notna(max_cl) else max_c, today)
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
                    x="week", y="open", title="Open Backlog Trend",
                    color_discrete_sequence=["#7c69d4"],
                    labels={"week": "", "open": "Open Items"},
                )
                fig_wip.update_layout(height=360, plot_bgcolor="rgba(0,0,0,0)",
                                      paper_bgcolor="rgba(0,0,0,0)",
                                      margin=dict(t=50, b=80, l=60, r=20))
                fig_wip.update_xaxes(tickangle=-35, tickfont=dict(size=12))
                fig_wip.update_yaxes(title="Open Items", gridcolor="rgba(255,255,255,0.06)")
            else:
                fig_wip = _empty_fig("No backlog data")
        else:
            fig_wip = _empty_fig("Insufficient date range")
    else:
        fig_wip = _empty_fig()

    # ── Member Throughput ──────────────────────────────────────────────────────
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
                    height=420, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=90, b=120, l=60, r=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                fig_mtp.update_xaxes(tickangle=-35, tickfont=dict(size=13))
                fig_mtp.update_yaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)")
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
                fig_mtp.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)")
                fig_mtp.update_yaxes(tickfont=dict(size=13))
            else:
                fig_mtp = _empty_fig("No member output data")
    else:
        fig_mtp = _empty_fig()

    # ── Member Workload ────────────────────────────────────────────────────────
    if {"assigned_to", "original_estimate", "completed_work"}.issubset(df_team.columns):
        d4 = df_team.copy()
        d4["orig"] = num("original_estimate", d4)
        d4["comp"] = num("completed_work", d4)
        g4 = d4.groupby("assigned_to")[["orig", "comp"]].sum().reset_index()
        g4["rem"] = (g4["orig"] - g4["comp"]).clip(lower=0)
        long = g4.melt(id_vars="assigned_to", value_vars=["orig", "comp", "rem"],
                       var_name="Type", value_name="Hours").replace(
            {"orig": "Assigned", "comp": "Completed", "rem": "Remaining"})
        if not long.empty:
            fig_wl = px.scatter(
                long, x="Hours", y="assigned_to", color="Type", opacity=0.85,
                title="Member Workload Pipeline",
                color_discrete_map={"Assigned": "#5a8fd4", "Completed": "#3d9e6b",
                                    "Remaining": "#c06060"},
            )
            fig_wl.update_traces(marker=dict(size=12))
            fig_wl.update_layout(
                height=max(len(g4) * 42 + 120, 300),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=90, b=60, l=185, r=40),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            fig_wl.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)")
            fig_wl.update_yaxes(tickfont=dict(size=12))
        else:
            fig_wl = _empty_fig("No workload data")
    else:
        fig_wl = _empty_fig()

    # ── Team-specific section ──────────────────────────────────────────────────
    specific = _build_specific_section(df_team, team, team_type)

    return (kpi_row, fig_tp, fig_wip, fig_mtp, fig_wl, specific)


# ── Team-specific section builder ─────────────────────────────────────────────
def _build_specific_section(df_team, team, team_type):
    """Return html children for the team-type-specific analysis section."""

    if team_type == "qa":
        return _section_qa(df_team)
    elif team_type in ("dev",):
        return _section_dev(df_team)
    elif team_type == "design":
        return _section_design(df_team)
    else:
        return _section_management(df_team)


def _section_qa(df):
    """QA-specific metrics: SLA compliance, reopen rate, defect discovery, state distribution."""
    bugs = df[df["work_item_type"].str.contains("Bug", na=False, case=False)].copy() \
        if "work_item_type" in df.columns else df.copy()

    if bugs.empty:
        return html.Div([
            html.Div([_section_label("QA Quality Metrics"),
                      html.P("No bug data available for this team.",
                             style={"color": "#718096", "fontSize": "13px"})],
                     style=_sb)
        ])

    for col in ["created_date", "closed_date"]:
        if col in bugs.columns:
            bugs[col] = pd.to_datetime(bugs[col], errors="coerce")
            if bugs[col].dt.tz is not None:
                bugs[col] = bugs[col].dt.tz_localize(None)

    today      = pd.Timestamp.today().normalize()
    open_bugs  = bugs[~bugs["state"].isin(CLOSED_ALL)].copy() if "state" in bugs.columns else bugs.copy()
    closed_bugs = bugs[bugs["state"] == "Closed"].copy() if "state" in bugs.columns else pd.DataFrame()

    # ── SLA compliance ─────────────────────────────────────────────────────────
    fig_sla = _empty_fig("No closed bug data for SLA")
    if not closed_bugs.empty and {"priority", "created_date", "closed_date"}.issubset(closed_bugs.columns):
        cb = closed_bugs.copy()
        cb["priority"] = pd.to_numeric(cb["priority"], errors="coerce")
        cb["cycle"]    = (cb["closed_date"] - cb["created_date"]).dt.days
        cb = cb.dropna(subset=["priority", "cycle"])
        rows = []
        for p, sla in SLA_DAYS.items():
            grp = cb[cb["priority"] == p]
            if grp.empty:
                continue
            met = int((grp["cycle"] <= sla).sum())
            total = len(grp)
            rows.append({
                "Priority": f"P{p}",
                "SLA (days)": sla,
                "Met": met,
                "Breached": total - met,
                "Compliance %": met / total * 100,
            })
        if rows:
            sla_df = pd.DataFrame(rows)
            fig_sla = go.Figure()
            fig_sla.add_trace(go.Bar(
                name="Within SLA", x=sla_df["Priority"], y=sla_df["Met"],
                marker_color="#34d399",
                text=sla_df["Met"], textposition="inside", textfont=dict(size=11),
            ))
            fig_sla.add_trace(go.Bar(
                name="Breached", x=sla_df["Priority"], y=sla_df["Breached"],
                marker_color="#f87171",
                text=sla_df["Breached"], textposition="inside", textfont=dict(size=11),
            ))
            fig_sla.update_layout(
                barmode="stack", title="SLA Compliance by Priority",
                height=320, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=50, l=60, r=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            fig_sla.update_xaxes(tickfont=dict(size=13))
            fig_sla.update_yaxes(title="Bugs", gridcolor="rgba(255,255,255,0.06)")

    # ── Reopen rate over time ──────────────────────────────────────────────────
    fig_reopen = _empty_fig("No reopen data")
    if "state" in bugs.columns and "created_date" in bugs.columns:
        reopened = bugs[bugs["state"] == "Reopened"].copy()
        if not reopened.empty:
            reopened["week"] = reopened["created_date"].dt.to_period("W").dt.start_time
            rw = reopened.groupby("week").size().reset_index(name="count")
            fig_reopen = px.bar(rw, x="week", y="count",
                                title="Bugs Reopened (Weekly)",
                                color_discrete_sequence=["#f87171"],
                                labels={"week": "", "count": "Reopened"})
            fig_reopen.update_layout(
                height=280, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=60, l=60, r=20),
            )
            fig_reopen.update_xaxes(tickangle=-35, tickfont=dict(size=11))
            fig_reopen.update_yaxes(gridcolor="rgba(255,255,255,0.06)")

    # ── Bug discovery rate (bugs opened per week) ──────────────────────────────
    fig_discovery = _empty_fig("No discovery data")
    if "created_date" in bugs.columns:
        bw = bugs.copy()
        bw["week"] = bw["created_date"].dt.to_period("W").dt.start_time
        disc = bw.groupby("week").size().reset_index(name="count")
        if not disc.empty:
            fig_discovery = px.line(disc, x="week", y="count", markers=True,
                                    title="Bug Discovery Rate (New Bugs / Week)",
                                    color_discrete_sequence=["#fb923c"],
                                    labels={"week": "", "count": "New Bugs"})
            fig_discovery.update_layout(
                height=280, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=60, l=60, r=20),
            )
            fig_discovery.update_xaxes(tickangle=-35, tickfont=dict(size=11))
            fig_discovery.update_yaxes(gridcolor="rgba(255,255,255,0.06)")

    # ── Bug state distribution ──────────────────────────────────────────────────
    fig_states = _empty_fig("No state data")
    if "state" in bugs.columns:
        sc = bugs["state"].value_counts().reset_index()
        sc.columns = ["State", "Count"]
        sc = sc.sort_values("Count", ascending=True)
        fig_states = go.Figure(go.Bar(
            x=sc["Count"], y=sc["State"], orientation="h",
            marker_color="#818cf8",
            text=sc["Count"], textposition="outside", textfont=dict(size=11),
        ))
        fig_states.update_layout(
            title="Bugs by Current State",
            height=max(len(sc) * 38 + 100, 280),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=20, l=180, r=80),
        )
        fig_states.update_xaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
        fig_states.update_yaxes(tickfont=dict(size=12))

    # ── Mean time to close by priority ─────────────────────────────────────────
    fig_mttc = _empty_fig("No closed bug data")
    if not closed_bugs.empty and {"priority", "created_date", "closed_date"}.issubset(closed_bugs.columns):
        c = closed_bugs.copy()
        c["priority"] = pd.to_numeric(c["priority"], errors="coerce")
        c["days"]     = (c["closed_date"] - c["created_date"]).dt.days
        mttc = c.groupby("priority")["days"].mean().round(1).reset_index()
        mttc["label"] = mttc["priority"].map({1: "P1🔥", 2: "P2⚠️", 3: "P3", 4: "P4"})
        mttc = mttc.dropna(subset=["label"])
        if not mttc.empty:
            fig_mttc = px.bar(
                mttc, x="label", y="days",
                title="Mean Time to Close by Priority (days)",
                color="label",
                color_discrete_map={"P1🔥": "#c05050", "P2⚠️": "#dd6b20",
                                    "P3": "#3182ce", "P4": "#805ad5"},
                text="days",
            )
            fig_mttc.update_traces(texttemplate="%{text:.1f}d", textposition="outside")
            fig_mttc.update_layout(
                height=300, showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=50, l=60, r=40),
            )
            fig_mttc.update_yaxes(title="Days", gridcolor="rgba(255,255,255,0.06)")

    return [
        html.Div([
            _section_label("QA Quality — SLA & Fix Speed"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_sla),   className="chart-card"), md=7),
                dbc.Col(html.Div(dcc.Graph(figure=fig_mttc),  className="chart-card"), md=5),
            ], className="mb-2"),
        ], style=_sb),
        html.Div([
            _section_label("Defect Discovery & Reopen Rate"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_discovery), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_reopen),    className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),
        html.Div([
            _section_label("Bug State Distribution"),
            html.Div(dcc.Graph(figure=fig_states), className="chart-card"),
        ], style=_sb),
    ]


def _section_dev(df):
    """Dev/Mobile-specific metrics: cycle time, item type mix, bug introduction rate, spillover."""

    if df.empty:
        return html.Div()

    for col in ["created_date", "closed_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # ── Cycle time distribution ────────────────────────────────────────────────
    fig_cycle = _empty_fig("No cycle time data")
    closed = df[df["state"] == "Closed"].copy() if "state" in df.columns else pd.DataFrame()
    if not closed.empty and {"created_date", "closed_date"}.issubset(closed.columns):
        closed["days"] = (closed["closed_date"] - closed["created_date"]).dt.days
        closed = closed.dropna(subset=["days"])
        closed = closed[closed["days"] >= 0]
        if not closed.empty:
            fig_cycle = px.histogram(
                closed, x="days", nbins=30,
                title="Cycle Time Distribution (Created → Closed)",
                labels={"days": "Days", "count": "Items"},
                color_discrete_sequence=["#60a5fa"],
            )
            fig_cycle.update_layout(
                height=320, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=60, l=60, r=20),
            )
            fig_cycle.update_xaxes(title="Days to Close", gridcolor="rgba(255,255,255,0.06)")
            fig_cycle.update_yaxes(title="Items", gridcolor="rgba(255,255,255,0.06)")

    # ── Item type mix ──────────────────────────────────────────────────────────
    fig_types = _empty_fig("No item type data")
    if "work_item_type" in df.columns:
        tc = df["work_item_type"].value_counts().reset_index()
        tc.columns = ["Type", "Count"]
        tc = tc.sort_values("Count", ascending=True)
        COLOR_MAP = {"Bug": "#c06060", "Enhancement": "#3d9e6b",
                     "Task": "#5a8fd4", "Feature": "#9f7aea",
                     "User Story": "#f6ad55"}
        colors = [COLOR_MAP.get(t, "#a0aec0") for t in tc["Type"]]
        fig_types = go.Figure(go.Bar(
            x=tc["Count"], y=tc["Type"], orientation="h",
            marker_color=colors,
            text=tc["Count"], textposition="outside", textfont=dict(size=11),
        ))
        fig_types.update_layout(
            title="Work Item Type Mix",
            height=max(len(tc) * 42 + 100, 260),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=20, l=175, r=80),
        )
        fig_types.update_xaxes(title="Items", gridcolor="rgba(255,255,255,0.06)")
        fig_types.update_yaxes(tickfont=dict(size=12))

    # ── Bug introduction rate (bugs raised in same iteration as team's items) ──
    fig_bugs_intro = _empty_fig("No bug introduction data")
    if {"work_item_type", "iteration_path"}.issubset(df.columns):
        bugs_in_iters = df[
            df["work_item_type"].str.contains("Bug", na=False, case=False)
        ].copy()
        bugs_in_iters["iteration_path"] = bugs_in_iters["iteration_path"].apply(_strip_iter)
        bi = bugs_in_iters.groupby("iteration_path").size().reset_index(name="Bugs")
        bi = bi.sort_values("Bugs", ascending=True).tail(15)
        if not bi.empty:
            fig_bugs_intro = go.Figure(go.Bar(
                x=bi["Bugs"], y=bi["iteration_path"], orientation="h",
                marker_color="#f87171",
                text=bi["Bugs"], textposition="outside", textfont=dict(size=11),
            ))
            fig_bugs_intro.update_layout(
                title="Bugs per Iteration (Introduction Rate)",
                height=max(len(bi) * 38 + 100, 280),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=20, l=175, r=80),
            )
            fig_bugs_intro.update_xaxes(title="Bug Count", gridcolor="rgba(255,255,255,0.06)")
            fig_bugs_intro.update_yaxes(tickfont=dict(size=12))

    # ── Spillover (items created in an iteration, not yet closed) ──────────────
    fig_spillover = _empty_fig("No spillover data")
    if {"state", "iteration_path"}.issubset(df.columns):
        sp = df.copy()
        sp["iteration_path"] = sp["iteration_path"].apply(_strip_iter)
        sp["is_open"] = ~sp["state"].isin(CLOSED_ALL)
        spill = sp.groupby("iteration_path")["is_open"].agg(
            Total="count", Open="sum"
        ).reset_index()
        spill["Spillover %"] = (spill["Open"] / spill["Total"] * 100).round(1)
        spill = spill.sort_values("Spillover %", ascending=True).tail(15)
        if not spill.empty:
            fig_spillover = px.bar(
                spill, x="Spillover %", y="iteration_path", orientation="h",
                title="Spillover Rate by Iteration (% items still open)",
                color="Spillover %", color_continuous_scale="Reds",
                labels={"iteration_path": ""},
                text="Spillover %",
            )
            fig_spillover.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig_spillover.update_layout(
                height=max(len(spill) * 38 + 100, 280),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=20, l=175, r=100),
                showlegend=False,
            )
            fig_spillover.update_xaxes(title="Spillover %", gridcolor="rgba(255,255,255,0.06)")
            fig_spillover.update_coloraxes(showscale=False)
            fig_spillover.update_yaxes(tickfont=dict(size=12))

    return [
        html.Div([
            _section_label("Delivery Quality — Cycle Time & Item Mix"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_cycle),  className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_types),  className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),
        html.Div([
            _section_label("Iteration Health — Bugs Introduced & Spillover"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_bugs_intro),  className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_spillover),   className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),
    ]


def _section_design(df):
    """Design/Video team: task completion and type breakdown."""

    fig_types = _empty_fig("No item type data")
    if "work_item_type" in df.columns:
        tc = df["work_item_type"].value_counts().reset_index()
        tc.columns = ["Type", "Count"]
        tc = tc.sort_values("Count", ascending=True)
        fig_types = go.Figure(go.Bar(
            x=tc["Count"], y=tc["Type"], orientation="h",
            marker_color="#a78bfa",
            text=tc["Count"], textposition="outside", textfont=dict(size=11),
        ))
        fig_types.update_layout(
            title="Work Item Type Distribution",
            height=max(len(tc) * 42 + 100, 260),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=20, l=175, r=80),
        )
        fig_types.update_xaxes(title="Items", gridcolor="rgba(255,255,255,0.06)")

    fig_state = _empty_fig("No state data")
    if "state" in df.columns:
        sc = df["state"].value_counts().reset_index()
        sc.columns = ["State", "Count"]
        sc = sc.sort_values("Count", ascending=True)
        fig_state = go.Figure(go.Bar(
            x=sc["Count"], y=sc["State"], orientation="h",
            marker_color="#818cf8",
            text=sc["Count"], textposition="outside", textfont=dict(size=11),
        ))
        fig_state.update_layout(
            title="Items by Current State",
            height=max(len(sc) * 38 + 100, 280),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=20, l=175, r=80),
        )
        fig_state.update_xaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")

    return [
        html.Div([
            _section_label("Work Breakdown & Queue"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_types), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_state), className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),
    ]


def _section_management(df):
    """Management: cross-team comparison and item distribution."""

    # Cross-team completion comparison
    df_all = load_data()
    df_all = filter_activity_since(df_all, ANALYSIS_START_DATE)

    fig_teams = _empty_fig("No team data")
    if "team" in df_all.columns and "completed_work" in df_all.columns:
        tg = df_all.groupby("team")["completed_work"].apply(
            lambda x: pd.to_numeric(x, errors="coerce").fillna(0).sum()
        ).reset_index()
        tg.columns = ["Team", "Completed (h)"]
        tg = tg[tg["Completed (h)"] > 0].sort_values("Completed (h)", ascending=True)
        if not tg.empty:
            fig_teams = go.Figure(go.Bar(
                x=tg["Completed (h)"], y=tg["Team"], orientation="h",
                marker_color="#818cf8",
                text=tg["Completed (h)"].apply(lambda v: f"{v:,.0f}h"),
                textposition="outside", textfont=dict(size=11),
            ))
            fig_teams.update_layout(
                title="Completed Hours by Team",
                height=max(len(tg) * 48 + 100, 280),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=20, l=150, r=100),
            )
            fig_teams.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)")

    fig_open = _empty_fig("No team data")
    if "team" in df_all.columns and "state" in df_all.columns:
        df_all["is_open"] = ~df_all["state"].isin(CLOSED_ALL)
        og = df_all.groupby("team")["is_open"].sum().reset_index()
        og.columns = ["Team", "Open Items"]
        og = og[og["Open Items"] > 0].sort_values("Open Items", ascending=True)
        if not og.empty:
            fig_open = go.Figure(go.Bar(
                x=og["Open Items"], y=og["Team"], orientation="h",
                marker_color="#fb923c",
                text=og["Open Items"].astype(int).astype(str),
                textposition="outside", textfont=dict(size=11),
            ))
            fig_open.update_layout(
                title="Open Items by Team",
                height=max(len(og) * 48 + 100, 280),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=20, l=150, r=80),
            )
            fig_open.update_xaxes(title="Open Items", gridcolor="rgba(255,255,255,0.06)")

    return [
        html.Div([
            _section_label("Cross-Team Overview"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_teams), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_open),  className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),
    ]
