"""Bugs Dashboard — deep dive into bug health, aging, trends, and root causes"""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback, dash_table
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data, apply_filters, filter_activity_since
from components.matrix import build_bug_matrix
from config.settings import ANALYSIS_START_DATE

dash.register_page(__name__, path="/bugs", name="Bugs")

CLOSED_BUG_STATES = {"Closed", "Not an issue", "Not Required", "Userstory Update"}
REJECTED_BUG_STATES = {"Not an issue", "Not Required"}
EXCL_STATES   = ["Userstory Update", "Not an issue", "Not Required"]
P_COLORS      = ["#c05050", "#dd6b20", "#3182ce", "#805ad5"]
SOURCE_COLORS = {"Customer": "#c06060", "Internal": "#63b3ed", "Automation": "#68d391"}

AGE_BINS   = [0, 7, 30, 90, float("inf")]
AGE_LABELS = ["0–7 days", "8–30 days", "31–90 days", "90+ days"]


def _section_label(text):
    return html.Div(text, style={
        "fontSize": "11px", "fontWeight": "700", "textTransform": "uppercase",
        "letterSpacing": "0.8px", "color": "#a0aec0",
        "marginBottom": "12px", "marginTop": "4px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────
def layout():
    df       = load_data()
    releases = ["All"] + sorted(df["release_date"].dropna().unique().tolist()) if "release_date" in df.columns else ["All"]
    iters    = sorted(df["iteration_path"].dropna().unique().tolist()) if "iteration_path" in df.columns else []
    teams    = ["All"] + sorted(df["team"].dropna().unique().tolist()) if "team" in df.columns else ["All"]

    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    employees = ["All"] + sorted(df["assigned_to"].dropna().unique().tolist()) if "assigned_to" in df.columns else ["All"]
    states    = sorted(df["state"].dropna().unique().tolist()) if "state" in df.columns else []

    _fb_style = {
        "background": "#1c1c27", "borderRadius": "10px", "padding": "14px 18px",
        "border": "1px solid rgba(255,255,255,0.07)",
        "marginBottom": "20px",
    }
    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([
                html.Div("Release", className="filter-label"),
                dcc.Dropdown(id="bug-release",
                             options=[{"label": r, "value": r} for r in releases],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Iteration", className="filter-label"),
                dcc.Dropdown(id="bug-iteration",
                             options=[{"label": i, "value": i} for i in iters],
                             value=[], multi=True, placeholder="All",
                             style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Team", className="filter-label"),
                dcc.Dropdown(id="bug-team",
                             options=[{"label": t, "value": t} for t in teams],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Employee", className="filter-label"),
                dcc.Dropdown(id="bug-employee",
                             options=[{"label": e, "value": e} for e in employees],
                             value="All", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
        ], className="g-2"),
        dbc.Row([
            dbc.Col([
                html.Div("State", className="filter-label"),
                dcc.Dropdown(id="bug-state",
                             options=[{"label": s, "value": s} for s in states],
                             value=[], multi=True, placeholder="All states",
                             style={"fontSize": "12px"}),
            ], md=12),
        ], className="g-2 mt-2"),
    ], style=_fb_style)

    return html.Div([
        html.Div([
            html.H1("🐛 Bugs Dashboard", className="page-title"),
            html.P("Bug inventory, aging, priority, owner accountability, and trend analysis.",
                   className="page-subtitle"),
        ], className="page-header"),

        filter_bar,

        # ── KPIs ──────────────────────────────────────────────────────────────
        _section_label("At a Glance"),
        html.Div(id="bug-kpi-row", className="mb-4"),
        html.Hr(className="section-divider"),

        # ── Priority + Source ──────────────────────────────────────────────────
        _section_label("Priority & Source"),
        dbc.Row([
            dbc.Col(html.Div(dcc.Graph(id="bug-priority-chart"), className="chart-card"), md=7),
            dbc.Col(html.Div(dcc.Graph(id="bug-source-donut"),   className="chart-card"), md=5),
        ], className="mb-2"),
        html.Hr(className="section-divider"),

        # ── Age + MTTC ─────────────────────────────────────────────────────────
        _section_label("Age & Resolution Speed"),
        dbc.Row([
            dbc.Col(html.Div(dcc.Graph(id="bug-age-chart"),  className="chart-card"), md=6),
            dbc.Col(html.Div(dcc.Graph(id="bug-mttc-chart"), className="chart-card"), md=6),
        ], className="mb-2"),
        html.Hr(className="section-divider"),

        # ── Area + Function ────────────────────────────────────────────────────
        _section_label("Hotspots"),
        dbc.Row([
            dbc.Col(html.Div(dcc.Graph(id="bug-area-chart"), className="chart-card"), md=5),
            dbc.Col(html.Div(dcc.Graph(id="bug-func-chart"), className="chart-card"), md=7),
        ], className="mb-2"),
        html.Hr(className="section-divider"),

        # ── Owner accountability ───────────────────────────────────────────────
        _section_label("Owner Accountability"),
        html.Div(dcc.Graph(id="bug-owner-chart"), className="chart-card mb-4"),
        html.Hr(className="section-divider"),

        # ── Bug trends ────────────────────────────────────────────────────────
        _section_label("Trends Over Time"),
        dbc.Row([
            dbc.Col(html.Div(dcc.Graph(id="bug-flow-chart"),    className="chart-card"), md=7),
            dbc.Col(html.Div(dcc.Graph(id="bug-backlog-chart"), className="chart-card"), md=5),
        ], className="mb-2"),
        html.Hr(className="section-divider"),

        # ── Movement matrices (collapsible) ───────────────────────────────────
        dbc.Button(
            "📊 Show / Hide Bug Movement Matrices",
            id="bug-matrix-toggle", color="light", outline=True, size="sm",
            style={"marginBottom": "12px", "fontSize": "13px"},
        ),
        dbc.Collapse(
            html.Div([
                html.P(
                    "Opening Balance + New − Completed = Closing Balance. "
                    "Use for monthly data integrity checks.",
                    style={"fontSize": "12px", "color": "#718096", "marginBottom": "12px"},
                ),
                html.Div("🟦 Opening Balance", className="chart-title", style={"fontSize": "13px"}),
                html.Div(id="bug-matrix-open",  className="chart-card"),
                html.Div("🟧 New Bugs",         className="chart-title", style={"fontSize": "13px"}),
                html.Div(id="bug-matrix-new",   className="chart-card"),
                html.Div("🟩 Completed",        className="chart-title", style={"fontSize": "13px"}),
                html.Div(id="bug-matrix-comp",  className="chart-card"),
                html.Div("⬜ Closing Balance",   className="chart-title", style={"fontSize": "13px"}),
                html.Div(id="bug-matrix-close", className="chart-card"),
            ]),
            id="bug-matrix-collapse", is_open=False,
        ),
    ])


# ── Matrix helper ─────────────────────────────────────────────────────────────
def _matrix_table(df_matrix: pd.DataFrame):
    if df_matrix.empty:
        return html.P("No data.", style={"color": "#718096", "fontSize": "12px"})
    tbl = df_matrix.reset_index()
    tbl.columns = [str(c) for c in tbl.columns]
    return dash_table.DataTable(
        data=tbl.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl.columns],
        style_table={"overflowX": "auto"},
        style_cell={"fontSize": "11px", "padding": "6px 10px",
                    "textAlign": "center", "minWidth": "60px"},
        style_header={"fontWeight": "bold", "backgroundColor": "#edf2f7",
                      "textAlign": "center"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "rgba(255,255,255,0.03)"},
            {"if": {"column_id": "Total"}, "fontWeight": "bold",
             "backgroundColor": "#e2e8f0"},
        ],
    )


# ── Matrix toggle ─────────────────────────────────────────────────────────────
@callback(
    Output("bug-matrix-collapse", "is_open"),
    Input("bug-matrix-toggle",    "n_clicks"),
    State("bug-matrix-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_matrices(n, is_open):
    return not is_open


# ── Main callback ─────────────────────────────────────────────────────────────
@callback(
    Output("bug-kpi-row",        "children"),
    Output("bug-priority-chart", "figure"),
    Output("bug-source-donut",   "figure"),
    Output("bug-age-chart",      "figure"),
    Output("bug-mttc-chart",     "figure"),
    Output("bug-area-chart",     "figure"),
    Output("bug-func-chart",     "figure"),
    Output("bug-owner-chart",    "figure"),
    Output("bug-flow-chart",     "figure"),
    Output("bug-backlog-chart",  "figure"),
    Output("bug-matrix-open",    "children"),
    Output("bug-matrix-new",     "children"),
    Output("bug-matrix-comp",    "children"),
    Output("bug-matrix-close",   "children"),
    Input("bug-release",   "value"),
    Input("bug-iteration", "value"),
    Input("bug-team",      "value"),
    Input("bug-employee",  "value"),
    Input("bug-state",     "value"),
)
def update_bugs(release, iterations, team, employee, states_filter):
    df = load_data()
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]

    df = apply_filters(df, release=release, iterations=iterations,
                       team=team, employee=employee)
    df = filter_activity_since(df, ANALYSIS_START_DATE)
    if states_filter:
        df = df[df["state"].isin(states_filter)]

    def empty_fig(msg="No data"):
        return go.Figure().update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=20, l=20, r=20),
            xaxis_visible=False, yaxis_visible=False,
            annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                              font=dict(size=14, color="#a0aec0"))],
        )

    bugs_all  = df[df["work_item_type"].str.contains("Bug", na=False, case=False)].copy()
    bugs_main = bugs_all[~bugs_all["state"].isin(EXCL_STATES)].copy()
    open_bugs = bugs_all[~bugs_all["state"].isin(CLOSED_BUG_STATES)].copy()

    today = pd.Timestamp.today().normalize()

    for col in ["created_date", "closed_date"]:
        for src in [bugs_all, bugs_main, open_bugs]:
            src[col] = pd.to_datetime(src.get(col, pd.Series(dtype="datetime64[ns]")), errors="coerce")
            if src[col].dt.tz is not None:
                src[col] = src[col].dt.tz_localize(None)

    total_bugs   = len(bugs_all)
    n_open       = len(open_bugs)
    closed_bugs  = int(bugs_all["state"].eq("Closed").sum())
    rejected     = int(bugs_all["state"].isin(REJECTED_BUG_STATES).sum())
    p1_open      = int((open_bugs["priority"] == 1).sum()) if "priority" in open_bugs.columns else 0
    p2_open      = int((open_bugs["priority"] == 2).sum()) if "priority" in open_bugs.columns else 0
    closure_pct  = closed_bugs / total_bugs * 100 if total_bugs > 0 else 0

    cb       = bugs_all[bugs_all["state"] == "Closed"].copy()
    avg_mttc = (cb["closed_date"] - cb["created_date"]).dt.days.mean() if not cb.empty else None

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
            _kpi("Total Bugs",  f"{total_bugs:,}"),
            _kpi("Open Bugs",   f"{n_open:,}",
                 cls="danger" if n_open > 0 else "success"),
            _kpi("P1 Open",     f"{p1_open:,}",
                 cls="danger" if p1_open > 0 else "success"),
            _kpi("P2 Open",     f"{p2_open:,}",
                 cls="warning" if p2_open > 0 else ""),
        ], className="g-3 mb-3"),
        dbc.Row([
            _kpi("Closed",      f"{closed_bugs:,}",    cls="success"),
            _kpi("Closure %",   f"{closure_pct:.1f}%",
                 cls="success" if closure_pct >= 70 else ("warning" if closure_pct >= 40 else "danger")),
            _kpi("Rejected",    f"{rejected:,}",
                 subtitle="Not an issue / Not required"),
            _kpi("Avg MTTC",    f"{avg_mttc:.1f}d" if avg_mttc else "—",
                 subtitle="Mean time to close"),
        ], className="g-3"),
    ])

    # ── Priority chart ────────────────────────────────────────────────────────
    if not bugs_main.empty and "priority" in bugs_main.columns:
        priority_counts = (bugs_main["priority"].value_counts().sort_index()
                           .reindex([1, 2, 3, 4], fill_value=0))
        fig_pri = go.Figure(go.Bar(
            x=["P1 🔥", "P2 ⚠️", "P3", "P4"],
            y=priority_counts.values,
            marker_color=P_COLORS,
            text=priority_counts.values,
            textposition="outside",
            textfont=dict(size=12),
            hovertemplate="%{x}: %{y} bugs<extra></extra>",
        ))
        fig_pri.update_layout(
            title="Bugs by Priority (excl. rejected)",
            height=340, showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=50, l=60, r=40),
        )
        fig_pri.update_xaxes(tickfont=dict(size=13))
        fig_pri.update_yaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_pri = empty_fig("No bug data")

    # ── Issue source donut ────────────────────────────────────────────────────
    if "type" in bugs_all.columns:
        src_counts = bugs_all["type"].fillna("Unknown").value_counts().reset_index()
        src_counts.columns = ["Source", "Count"]
        fig_source = px.pie(
            src_counts, names="Source", values="Count",
            title="Issue Source (Customer vs Internal)",
            hole=0.52, color="Source", color_discrete_map=SOURCE_COLORS,
        )
        fig_source.update_traces(textposition="inside", textinfo="percent+label",
                                  textfont_size=12, insidetextorientation="radial")
        fig_source.update_layout(
            height=340, margin=dict(t=50, b=60, l=10, r=10),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.15,
                        xanchor="center", x=0.5),
        )
    else:
        fig_source = empty_fig("No source data")

    # ── Bug Age Distribution ──────────────────────────────────────────────────
    if not open_bugs.empty:
        oba = open_bugs.copy()
        oba["age_days"] = (today - oba["created_date"]).dt.days.fillna(0)
        oba["age_bucket"] = pd.cut(oba["age_days"], bins=AGE_BINS,
                                   labels=AGE_LABELS, right=False)
        oba["priority_label"] = oba["priority"].map(
            {1: "P1🔥", 2: "P2⚠️", 3: "P3", 4: "P4"}
        ).fillna("Unknown") if "priority" in oba.columns else "Unknown"

        age_grp = (oba.groupby(["age_bucket", "priority_label"], observed=True)
                   .size().reset_index(name="count"))
        if not age_grp.empty:
            fig_age = px.bar(
                age_grp, x="age_bucket", y="count", color="priority_label",
                barmode="stack", title="Open Bug Age Distribution",
                labels={"age_bucket": "Age", "count": "Bugs", "priority_label": "Priority"},
                category_orders={"age_bucket": AGE_LABELS,
                                 "priority_label": ["P1🔥", "P2⚠️", "P3", "P4"]},
                color_discrete_map={"P1🔥": "#c05050", "P2⚠️": "#dd6b20",
                                    "P3": "#3182ce", "P4": "#805ad5"},
            )
            fig_age.update_layout(
                height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=90, b=60, l=60, r=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            fig_age.update_xaxes(ticklabelstandoff=6)
            fig_age.update_yaxes(title="Open Bugs", gridcolor="rgba(255,255,255,0.06)")
        else:
            fig_age = empty_fig("No open bugs")
    else:
        fig_age = empty_fig("No open bugs")

    # ── MTTC by Priority ──────────────────────────────────────────────────────
    closed_all = bugs_all[bugs_all["state"] == "Closed"].copy()
    if not closed_all.empty and "priority" in closed_all.columns:
        closed_all["cycle_days"] = (closed_all["closed_date"] - closed_all["created_date"]).dt.days
        closed_all["priority_label"] = closed_all["priority"].map(
            {1: "P1🔥", 2: "P2⚠️", 3: "P3", 4: "P4"}
        ).fillna("Unknown")
        mttc_df = (closed_all.groupby("priority_label")["cycle_days"]
                   .mean().round(1).reset_index())
        mttc_df.columns = ["Priority", "Avg Days to Close"]
        mttc_df = mttc_df[mttc_df["Priority"].isin(["P1🔥", "P2⚠️", "P3", "P4"])]
        mttc_df["sort_key"] = mttc_df["Priority"].map(
            {"P1🔥": 0, "P2⚠️": 1, "P3": 2, "P4": 3}
        )
        mttc_df = mttc_df.sort_values("sort_key")

        if not mttc_df.empty:
            fig_mttc = px.bar(
                mttc_df, x="Priority", y="Avg Days to Close",
                title="Mean Time to Close by Priority (days)",
                color="Priority",
                color_discrete_map={"P1🔥": "#c05050", "P2⚠️": "#dd6b20",
                                    "P3": "#3182ce", "P4": "#805ad5"},
                text="Avg Days to Close",
            )
            fig_mttc.update_traces(texttemplate="%{text:.1f}d", textposition="outside")
            fig_mttc.update_layout(
                height=340, showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=50, l=60, r=40),
            )
            fig_mttc.update_xaxes(ticklabelstandoff=6)
            fig_mttc.update_yaxes(title="Days", gridcolor="rgba(255,255,255,0.06)")
        else:
            fig_mttc = empty_fig("No closed bugs")
    else:
        fig_mttc = empty_fig("No closed bugs with priority data")

    # ── Open bugs by Area ─────────────────────────────────────────────────────
    if "area" in open_bugs.columns and not open_bugs.empty:
        area_counts = open_bugs["area"].value_counts().reset_index()
        area_counts.columns = ["Area", "Open Bugs"]
        area_counts = area_counts.sort_values("Open Bugs", ascending=True)
        fig_area = go.Figure(go.Bar(
            x=area_counts["Open Bugs"], y=area_counts["Area"], orientation="h",
            marker_color="#c06060", text=area_counts["Open Bugs"],
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{y}: %{x} open bugs<extra></extra>",
        ))
        fig_area.update_layout(
            title="Open Bugs by Area",
            height=max(len(area_counts) * 42 + 100, 280),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=20, l=185, r=80),
        )
        fig_area.update_xaxes(title="Open Bugs", gridcolor="rgba(255,255,255,0.06)")
        fig_area.update_yaxes(tickfont=dict(size=12))
    else:
        fig_area = empty_fig("No area data")

    # ── Top Buggy Functions ───────────────────────────────────────────────────
    if "function" in bugs_main.columns and not bugs_main.empty:
        func_counts = bugs_main["function"].value_counts().head(12)
        fig_func = go.Figure(go.Bar(
            x=func_counts.values, y=func_counts.index, orientation="h",
            marker_color="#f6ad55", text=func_counts.values,
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{y}: %{x} bugs<extra></extra>",
        ))
        fig_func.update_layout(
            title="Top 12 Buggy Functions",
            height=max(len(func_counts) * 48 + 100, 300),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=40, l=185, r=80),
        )
        fig_func.update_xaxes(title="Bug Count", gridcolor="rgba(255,255,255,0.06)")
        fig_func.update_yaxes(tickfont=dict(size=12))
    else:
        fig_func = empty_fig("No function data")

    # ── Open bugs by Owner ────────────────────────────────────────────────────
    if "assigned_to" in open_bugs.columns and not open_bugs.empty:
        owner = (
            open_bugs["assigned_to"]
            .replace("Unassigned", "⚠️ Unassigned")
            .value_counts().reset_index()
        )
        owner.columns = ["Owner", "Open Bugs"]
        owner = owner.sort_values("Open Bugs", ascending=True).tail(20)

        # Color by priority mix per owner
        colors = owner["Owner"].apply(
            lambda x: "#c06060" if "Unassigned" in x else "#63b3ed"
        )

        fig_owner = go.Figure(go.Bar(
            x=owner["Open Bugs"], y=owner["Owner"], orientation="h",
            marker_color=colors, text=owner["Open Bugs"],
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{y}: %{x} open bugs<extra></extra>",
        ))
        fig_owner.update_layout(
            title="Open Bugs by Owner (top 20)",
            height=max(len(owner) * 42 + 80, 260),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=40, l=185, r=80),
        )
        fig_owner.update_xaxes(title="Open Bugs", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12))
        fig_owner.update_yaxes(tickfont=dict(size=12))
    else:
        fig_owner = empty_fig("No open bugs with owner data")

    # ── Bug Flow Over Time ────────────────────────────────────────────────────
    bugs_mv        = bugs_all.copy()
    analysis_start = pd.to_datetime(ANALYSIS_START_DATE)
    valid          = bugs_mv.dropna(subset=["created_date"])
    fig_flow = fig_backlog = empty_fig("Not enough date data")

    if not valid.empty:
        min_dt   = max(valid["created_date"].min(), analysis_start)
        max_dt_c = valid["created_date"].max()
        max_dt_l = valid["closed_date"].max()
        max_dt   = max_dt_l if pd.notna(max_dt_l) else max_dt_c

        if pd.notna(min_dt) and pd.notna(max_dt) and min_dt <= max_dt:
            months       = list(pd.period_range(min_dt.to_period("M"), max_dt.to_period("M"), freq="M"))
            month_labels = [str(m) for m in months]
            monthly = {"month": month_labels, "New": [], "Completed": [], "Opening": [], "Closing": []}

            for month in months:
                ms    = month.to_timestamp()
                me    = (month + 1).to_timestamp()
                new_n = len(bugs_mv[(bugs_mv["created_date"] >= ms) & (bugs_mv["created_date"] < me)])
                cmp_n = len(bugs_mv[(bugs_mv["closed_date"]  >= ms) & (bugs_mv["closed_date"]  < me)])
                opn_n = len(bugs_mv[
                    (bugs_mv["created_date"] < ms) &
                    (bugs_mv["closed_date"].isna() | (bugs_mv["closed_date"] >= ms))
                ])
                monthly["New"].append(new_n)
                monthly["Completed"].append(cmp_n)
                monthly["Opening"].append(opn_n)
                monthly["Closing"].append(max(opn_n + new_n - cmp_n, 0))

            mdf = pd.DataFrame(monthly)
            fig_flow = px.line(
                mdf.melt(id_vars="month", value_vars=["Opening", "New", "Completed"]),
                x="month", y="value", color="variable", markers=True,
                title="Bug Flow Over Time",
                labels={"month": "", "value": "Bugs", "variable": ""},
                color_discrete_map={"Opening": "#5a8fd4", "New": "#c97d3a",
                                    "Completed": "#3d9e6b"},
            )
            fig_flow.update_layout(
                height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=90, b=60, l=60, r=20), hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            fig_flow.update_xaxes(tickangle=-30)
            fig_flow.update_yaxes(gridcolor="rgba(255,255,255,0.06)")

            trend_dir = ("📈 INCREASING ⚠️"
                         if len(mdf) >= 2 and mdf["Closing"].iloc[-1] > mdf["Closing"].iloc[0]
                         else "📉 DECREASING ✅")
            fig_backlog = px.bar(
                mdf, x="month", y="Closing",
                title=f"Bug Backlog (End-of-Month) — {trend_dir}",
                color="Closing", color_continuous_scale="Reds",
                labels={"month": "", "Closing": "Open Bugs"},
            )
            fig_backlog.update_layout(
                height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=60, l=60, r=20), showlegend=False,
            )
            fig_backlog.update_xaxes(tickangle=-30)
            fig_backlog.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig_backlog.update_coloraxes(showscale=False)

    # ── Bug Movement Matrices ─────────────────────────────────────────────────
    bugs_mv["priority"] = pd.to_numeric(bugs_mv["priority"], errors="coerce")
    m_open = m_new = m_comp = m_close = html.P("No data.", style={"color": "#718096"})

    if not valid.empty:
        min_dt2 = max(valid["created_date"].min(), analysis_start)
        max_cd  = valid["created_date"].max()
        max_cl  = valid["closed_date"].max()
        max_dt2 = max_cl if pd.notna(max_cl) else max_cd
        if pd.notna(min_dt2) and pd.notna(max_dt2) and min_dt2 <= max_dt2:
            months_m = list(pd.period_range(min_dt2.to_period("M"), max_dt2.to_period("M"), freq="M"))
            for mode in ["open_start", "new", "completed", "open_end"]:
                tbl = build_bug_matrix(bugs_mv, months_m, mode)
                tbl.loc["Total"] = tbl.sum(numeric_only=True)
                if mode == "open_start":  m_open  = _matrix_table(tbl)
                elif mode == "new":       m_new   = _matrix_table(tbl)
                elif mode == "completed": m_comp  = _matrix_table(tbl)
                elif mode == "open_end":  m_close = _matrix_table(tbl)

    return (kpi_row,
            fig_pri, fig_source,
            fig_age, fig_mttc,
            fig_area, fig_func,
            fig_owner,
            fig_flow, fig_backlog,
            m_open, m_new, m_comp, m_close)
