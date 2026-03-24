"""Capacity Planning Dashboard — utilisation, accuracy, throughput, workload & forecasting"""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data, apply_filters, filter_activity_since
from config.settings import ANALYSIS_START_DATE

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

    teams     = (["All"] + sorted(df["team"].dropna().unique().tolist())
                 if "team" in df.columns else ["All"])
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

    return html.Div([
        html.Div([
            html.H1("📈 Capacity Planning", className="page-title"),
            html.P("Workload, utilisation, estimation accuracy, throughput, and delivery forecast.",
                   className="page-subtitle"),
        ], className="page-header"),

        filter_bar,

        # ── Overburden alerts ──────────────────────────────────────────────────
        html.Div(id="cap-overburden-alert", className="mb-3"),

        # ── KPIs ──────────────────────────────────────────────────────────────
        _section_label("At a Glance"),
        html.Div(id="cap-kpi-row", className="mb-4"),
        html.Hr(className="section-divider"),

        # ── Team utilisation & workload ────────────────────────────────────────
        _section_label("Team Utilisation & Workload"),
        html.Div(dcc.Graph(id="cap-team-multibar"), className="chart-card mb-4"),
        html.Div(dcc.Graph(id="cap-team-util"),     className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Per-person utilisation ─────────────────────────────────────────────
        _section_label("Individual Utilisation"),
        html.Div(dcc.Graph(id="cap-person-util"),   className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Iteration capacity comparison ──────────────────────────────────────
        _section_label("Iteration Capacity vs Commitment"),
        html.P("Compare hours committed (Original Estimate) vs available capacity per iteration. "
               "Red bars = over-committed.",
               style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
        html.Div(dcc.Graph(id="cap-iter-capacity"), className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Estimation accuracy ────────────────────────────────────────────────
        _section_label("Estimation Accuracy"),
        html.Div(dcc.Graph(id="cap-acc-team"), className="chart-card mb-4"),
        html.Div(dcc.Graph(id="cap-acc-emp"),  className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Estimation trend ──────────────────────────────────────────────────
        _section_label("Estimation Accuracy Trend"),
        html.P("Is the team getting better at estimating over time?",
               style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
        html.Div(dcc.Graph(id="cap-acc-trend"), className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Throughput + WIP ──────────────────────────────────────────────────
        _section_label("Throughput & WIP"),
        dbc.Row([
            dbc.Col(html.Div(dcc.Graph(id="cap-throughput"), className="chart-card"), md=6),
            dbc.Col(html.Div(dcc.Graph(id="cap-wip"),        className="chart-card"), md=6),
        ], className="mb-4"),
        html.Hr(className="section-divider"),

        # ── Completion rate by type ────────────────────────────────────────────
        _section_label("Completion Rate by Item Type"),
        html.P("What % of each item type actually gets completed in this period.",
               style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
        html.Div(dcc.Graph(id="cap-completion-rate"), className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Employee workload dot-plot ─────────────────────────────────────────
        _section_label("Employee Workload Detail"),
        html.Div(dcc.Graph(id="cap-dotplot"), className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Forecast ──────────────────────────────────────────────────────────
        _section_label("Delivery Forecast"),
        html.Div(id="cap-forecast-card"),
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
    df = apply_filters(df, team=team, employee=employee, iterations=iterations)
    df = filter_activity_since(df, ANALYSIS_START_DATE)

    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    if "main_developer" in df.columns:
        df["main_developer"] = df["main_developer"].astype(str).str.split(" <").str[0]
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)

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
    if {"team", "original_estimate", "completed_work"}.issubset(df.columns):
        tm = df.copy()
        tm["orig"] = num("original_estimate", tm)
        tm["comp"] = num("completed_work",    tm)
        tm["rem"]  = (tm["orig"] - tm["comp"]).clip(lower=0)
        g = tm.groupby("team")[["orig", "comp", "rem"]].sum().reset_index()
        melt = g.melt(id_vars="team", var_name="Type", value_name="Hours").replace(
            {"orig": "Original Estimate", "comp": "Completed", "rem": "Remaining"})
        fig_tmb = px.bar(
            melt, x="team", y="Hours", color="Type", barmode="group",
            title="Team: Original vs Completed vs Remaining",
            color_discrete_map={"Original Estimate": "#5a8fd4",
                                 "Completed": "#3d9e6b", "Remaining": "#c06060"},
            labels={"team": "", "Hours": "Hours"},
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
    if {"team", "original_estimate"}.issubset(df.columns) and person_field in df.columns:
        grp = df.groupby("team").agg(
            assigned=("original_estimate", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
            headcount=(person_field, lambda s: s.dropna().nunique()),
        ).reset_index()
        grp_bdays       = sum(get_iteration_bdays(i) for i in active_iters) if iterations else 20
        grp["capacity"] = grp["headcount"] * grp_bdays * hours_day
        grp["util_pct"] = np.where(grp["capacity"] > 0,
                                    grp["assigned"] / grp["capacity"] * 100, 0)
        grp = grp.sort_values("util_pct", ascending=True)
        fig_tu = go.Figure(go.Bar(
            x=grp["util_pct"], y=grp["team"], orientation="h",
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
    if {"team", "original_estimate", "completed_work"}.issubset(df.columns):
        d = df.copy()
        d["orig"] = num("original_estimate", d)
        d["comp"] = num("completed_work",    d)

        tea = d.groupby("team")[["orig", "comp"]].sum().reset_index()
        tea["acc"] = np.where(tea["orig"] > 0, tea["comp"] / tea["orig"] * 100, np.nan)
        tea = tea.dropna(subset=["acc"]).sort_values("acc", ascending=True)

        if not tea.empty:
            fig_at = go.Figure(go.Bar(
                x=tea["acc"], y=tea["team"], orientation="h",
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
