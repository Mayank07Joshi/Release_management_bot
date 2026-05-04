"""Items Dashboard — work items with type-aware analytics"""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback, dash_table
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data, apply_filters, filter_activity_since
from components.matrix import build_bug_matrix
from config.settings import ANALYSIS_START_DATE
from reports.summarizer import summarize_bugs
from reports.formatter import format_report
from reports.recommendations import get_recommendations_bugs
from reports.rec_display import rec_strip

dash.register_page(__name__, path="/items", name="Items")

CLOSED_STATES   = {"Closed", "Not an issue", "Not Required", "Userstory Update", "No Customer Response"}
REJECTED_STATES = {"Not an issue", "Not Required", "No Customer Response"}
EXCL_STATES     = ["Userstory Update", "Not an issue", "Not Required", "No Customer Response"]
P_COLORS        = ["#c05050", "#dd6b20", "#3182ce", "#805ad5"]
SOURCE_COLORS   = {"Customer": "#c06060", "Internal": "#63b3ed", "Automation": "#68d391"}
AGE_BINS        = [0, 7, 30, 90, float("inf")]
AGE_LABELS      = ["0–7 days", "8–30 days", "31–90 days", "90+ days"]

ITEM_TYPE_OPTIONS = [
    {"label": "All Types",    "value": "All"},
    {"label": "Bugs",         "value": "Bug"},
    {"label": "Enhancements", "value": "Enhancement"},
    {"label": "User Stories", "value": "User Story"},
    {"label": "Tasks",        "value": "Task"},
    {"label": "Features",     "value": "Feature"},
]

_SB = {
    "background": "rgba(255,255,255,0.015)", "borderRadius": "12px",
    "border": "1px solid rgba(255,255,255,0.04)",
    "padding": "20px 20px 12px 20px", "marginBottom": "24px",
}


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
        margin=dict(t=20, b=20, l=20, r=20), xaxis_visible=False, yaxis_visible=False,
        annotations=[dict(text=msg, x=0.5, y=0.5, showarrow=False,
                          font=dict(size=14, color="#a0aec0"))],
    )


# ── Layout ─────────────────────────────────────────────────────────────────────
def layout():
    df = load_data()
    releases  = ["All"] + sorted(df["release_date"].dropna().unique().tolist()) if "release_date" in df.columns else ["All"]
    iters     = sorted(df["iteration_path"].dropna().unique().tolist()) if "iteration_path" in df.columns else []
    teams     = ["All"] + sorted(df["team"].dropna().unique().tolist()) if "team" in df.columns else ["All"]
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    employees = ["All"] + sorted(df["assigned_to"].dropna().unique().tolist()) if "assigned_to" in df.columns else ["All"]
    states    = sorted(df["state"].dropna().unique().tolist()) if "state" in df.columns else []

    _fb = {
        "background": "#1c1c27", "borderRadius": "10px", "padding": "14px 18px",
        "border": "1px solid rgba(255,255,255,0.07)", "marginBottom": "20px",
    }
    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([html.Div("Item Type", className="filter-label"),
                     dcc.Dropdown(id="items-type", options=ITEM_TYPE_OPTIONS,
                                  value="Bug", clearable=False, style={"fontSize": "12px"})], md=3),
            dbc.Col([html.Div("Release", className="filter-label"),
                     dcc.Dropdown(id="items-release",
                                  options=[{"label": r, "value": r} for r in releases],
                                  value="All", clearable=False, style={"fontSize": "12px"})], md=3),
            dbc.Col([html.Div("Iteration", className="filter-label"),
                     dcc.Dropdown(id="items-iteration",
                                  options=[{"label": i, "value": i} for i in iters],
                                  value=[], multi=True, placeholder="All",
                                  style={"fontSize": "12px"})], md=3),
            dbc.Col([html.Div("Team", className="filter-label"),
                     dcc.Dropdown(id="items-team",
                                  options=[{"label": t, "value": t} for t in teams],
                                  value="All", clearable=False, style={"fontSize": "12px"})], md=3),
        ], className="g-2"),
        dbc.Row([
            dbc.Col([html.Div("Employee", className="filter-label"),
                     dcc.Dropdown(id="items-employee",
                                  options=[{"label": e, "value": e} for e in employees],
                                  value="All", clearable=False, style={"fontSize": "12px"})], md=6),
            dbc.Col([html.Div("State", className="filter-label"),
                     dcc.Dropdown(id="items-state",
                                  options=[{"label": s, "value": s} for s in states],
                                  value=[], multi=True, placeholder="All states",
                                  style={"fontSize": "12px"})], md=6),
        ], className="g-2 mt-2"),
        dbc.Row([
            dbc.Col([
                html.Div("Created Between", className="filter-label"),
                dcc.DatePickerRange(
                    id="items-created-range",
                    display_format="DD MMM YYYY",
                    clearable=True,
                    start_date_placeholder_text="From",
                    end_date_placeholder_text="To",
                    style={"fontSize": "12px"},
                ),
            ], md=6),
            dbc.Col([
                html.Div("Closed Between", className="filter-label"),
                dcc.DatePickerRange(
                    id="items-closed-range",
                    display_format="DD MMM YYYY",
                    clearable=True,
                    start_date_placeholder_text="From",
                    end_date_placeholder_text="To",
                    style={"fontSize": "12px"},
                ),
            ], md=6),
        ], className="g-2 mt-2"),
    ], style=_fb)

    report_modal = dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("📄 Items / Bug Board Report"), close_button=True),
        dbc.ModalBody(
            html.Div(id="items-report-body",
                     style={"maxHeight": "70vh", "overflowY": "auto", "padding": "4px 8px"}),
        ),
        dbc.ModalFooter(
            html.Span(id="items-report-ts",
                      style={"fontSize": "11px", "color": "#8892a4"}),
        ),
    ], id="items-report-modal", is_open=False, size="xl", backdrop="static",
       style={"--bs-modal-bg": "#13131f", "color": "#e2e8f0"})

    return html.Div([
        html.Div([
            dbc.Button("📄 Board Report", id="items-report-btn", size="sm",
                       style={"background": "rgba(129,140,248,0.15)", "border": "1px solid rgba(129,140,248,0.3)",
                              "color": "#818cf8", "fontWeight": "600", "float": "right", "marginBottom": "12px"}),
        ]),
        filter_bar,
        html.Div(id="items-rec-strip"),
        html.Div([_section_label("At a Glance"), html.Div(id="items-kpi-row")], style=_SB),
        html.Div([_section_label("Priority Breakdown"),
                  html.Div(dcc.Graph(id="items-priority-chart"), className="chart-card")], style=_SB),
        html.Div([_section_label("Age & Ownership"),
                  dbc.Row([
                      dbc.Col(html.Div(dcc.Graph(id="items-age-chart"),   className="chart-card"), md=6),
                      dbc.Col(html.Div(dcc.Graph(id="items-owner-chart"), className="chart-card"), md=6),
                  ])], style=_SB),
        html.Div([_section_label("Trends Over Time"),
                  dbc.Row([
                      dbc.Col(html.Div(dcc.Graph(id="items-flow-chart"),    className="chart-card"), md=7),
                      dbc.Col(html.Div(dcc.Graph(id="items-backlog-chart"), className="chart-card"), md=5),
                  ])], style=_SB),
        html.Div(id="items-specific-content"),
        report_modal,
    ])


# ── Matrix table helper ────────────────────────────────────────────────────────
def _matrix_table(df_matrix):
    if df_matrix.empty:
        return html.P("No data.", style={"color": "#718096", "fontSize": "12px"})
    tbl = df_matrix.reset_index()
    tbl.columns = [str(c) for c in tbl.columns]
    return dash_table.DataTable(
        data=tbl.to_dict("records"),
        columns=[{"name": c, "id": c} for c in tbl.columns],
        style_table={"overflowX": "auto"},
        style_cell={"fontSize": "11px", "padding": "6px 10px",
                    "backgroundColor": "#1a1a2e", "color": "#e2e8f0",
                    "border": "1px solid rgba(255,255,255,0.06)",
                    "textAlign": "center", "minWidth": "60px"},
        style_header={"fontWeight": "bold", "backgroundColor": "#252540",
                      "color": "#a0aec0", "textAlign": "center"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "rgba(255,255,255,0.03)"},
            {"if": {"column_id": "Total"}, "fontWeight": "bold",
             "backgroundColor": "rgba(255,255,255,0.06)"},
        ],
    )


# ── Type-specific section builders ────────────────────────────────────────────
def _section_bug(df_all, open_items, today):
    """Bug-specific: source, MTTC, hotspots, CI trend, movement matrices."""
    # Source donut
    if "type" in df_all.columns:
        src_counts = df_all["type"].fillna("Unknown").value_counts().reset_index()
        src_counts.columns = ["Source", "Count"]
        fig_source = px.pie(src_counts, names="Source", values="Count",
                            title="Issue Source (Customer vs Internal)",
                            hole=0.52, color="Source", color_discrete_map=SOURCE_COLORS)
        fig_source.update_traces(textposition="inside", textinfo="percent+label",
                                 textfont_size=12, insidetextorientation="radial")
        fig_source.update_layout(height=340, margin=dict(t=50, b=60, l=10, r=10),
                                 showlegend=True,
                                 legend=dict(orientation="h", yanchor="bottom", y=-0.15,
                                             xanchor="center", x=0.5))
    else:
        fig_source = _empty_fig("No source data")

    # MTTC by priority
    closed_all = df_all[df_all["state"] == "Closed"].copy() if "state" in df_all.columns else pd.DataFrame()
    if not closed_all.empty and "priority" in closed_all.columns and "closed_date" in closed_all.columns:
        closed_all["cycle_days"] = (closed_all["closed_date"] - closed_all["created_date"]).dt.days
        closed_all["priority_label"] = closed_all["priority"].map(
            {1: "P1🔥", 2: "P2⚠️", 3: "P3", 4: "P4"}).fillna("Unknown")
        mttc_df = (closed_all.groupby("priority_label")["cycle_days"]
                   .mean().round(1).reset_index())
        mttc_df.columns = ["Priority", "Avg Days to Close"]
        mttc_df = mttc_df[mttc_df["Priority"].isin(["P1🔥", "P2⚠️", "P3", "P4"])]
        mttc_df["sort_key"] = mttc_df["Priority"].map({"P1🔥": 0, "P2⚠️": 1, "P3": 2, "P4": 3})
        mttc_df = mttc_df.sort_values("sort_key")
        if not mttc_df.empty:
            fig_mttc = px.bar(mttc_df, x="Priority", y="Avg Days to Close",
                              title="Mean Time to Close by Priority (days)",
                              color="Priority",
                              color_discrete_map={"P1🔥": "#c05050", "P2⚠️": "#dd6b20",
                                                  "P3": "#3182ce", "P4": "#805ad5"},
                              text="Avg Days to Close")
            fig_mttc.update_traces(texttemplate="%{text:.1f}d", textposition="outside")
            fig_mttc.update_layout(height=340, showlegend=False,
                                   plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                   margin=dict(t=50, b=50, l=60, r=40))
            fig_mttc.update_yaxes(title="Days", gridcolor="rgba(255,255,255,0.06)")
        else:
            fig_mttc = _empty_fig("No closed bugs")
    else:
        fig_mttc = _empty_fig("No closed bugs with priority data")

    # Hotspots: Area + Function
    bugs_main = df_all[~df_all["state"].isin(EXCL_STATES)].copy() if "state" in df_all.columns else df_all.copy()
    if "area" in open_items.columns and not open_items.empty:
        area_c = open_items["area"].value_counts().reset_index()
        area_c.columns = ["Area", "Count"]
        area_c = area_c.sort_values("Count", ascending=True)
        fig_area = go.Figure(go.Bar(x=area_c["Count"], y=area_c["Area"], orientation="h",
                                    marker_color="#c06060", text=area_c["Count"],
                                    textposition="outside", textfont=dict(size=11)))
        fig_area.update_layout(title="Open Bugs by Area",
                               height=max(len(area_c) * 42 + 100, 280),
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               margin=dict(t=50, b=20, l=185, r=80))
        fig_area.update_xaxes(title="Open Bugs", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_area = _empty_fig("No area data")

    if "function" in bugs_main.columns and not bugs_main.empty:
        func_c = bugs_main["function"].value_counts().head(12)
        fig_func = go.Figure(go.Bar(x=func_c.values, y=func_c.index, orientation="h",
                                    marker_color="#f6ad55", text=func_c.values,
                                    textposition="outside", textfont=dict(size=11)))
        fig_func.update_layout(title="Top 12 Buggy Functions",
                               height=max(len(func_c) * 48 + 100, 300),
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               margin=dict(t=50, b=40, l=185, r=80))
        fig_func.update_xaxes(title="Bug Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_func = _empty_fig("No function data")

    # Customer vs Internal weekly trend
    fig_ci = _empty_fig("No type data")
    if "type" in df_all.columns and "created_date" in df_all.columns:
        weeks = pd.date_range(end=today, periods=25, freq="W-MON")
        rows = []
        for ws in weeks:
            we = ws + pd.Timedelta(days=6)
            for src in ("Customer", "Internal"):
                mask = (df_all["type"].eq(src) & df_all["created_date"].notna() &
                        (df_all["created_date"] >= ws) & (df_all["created_date"] <= we))
                rows.append({"Week": ws, "Type": src, "Count": int(mask.sum())})
        ci_df = pd.DataFrame(rows)
        if not ci_df.empty and ci_df["Count"].sum() > 0:
            fig_ci = go.Figure()
            clrs = {"Customer": "#f87171", "Internal": "#818cf8"}
            fills = {"Customer": "rgba(248,113,113,0.08)", "Internal": "rgba(129,140,248,0.07)"}
            for src, grp in ci_df.groupby("Type"):
                fig_ci.add_trace(go.Scatter(
                    x=grp["Week"], y=grp["Count"], mode="lines+markers", name=src,
                    line=dict(color=clrs.get(src, "#a0aec0"), width=2), marker=dict(size=5),
                    fill="tozeroy", fillcolor=fills.get(src, "rgba(160,174,192,0.07)"),
                    hovertemplate=f"<b>{src}</b><br>Week: %{{x|%d %b}}<br>Count: %{{y}}<extra></extra>",
                ))
            fig_ci.update_layout(height=320, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                 margin=dict(t=20, b=50, l=50, r=20), hovermode="x unified",
                                 xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickangle=-30),
                                 yaxis=dict(gridcolor="rgba(255,255,255,0.06)", title="New Bugs"),
                                 legend=dict(orientation="h", y=1.1, x=0))

    # Movement matrices (built inline)
    m_open = m_new = m_comp = m_close = html.P("No data.", style={"color": "#718096"})
    if "created_date" in df_all.columns:
        mv = df_all.copy()
        mv["priority"] = pd.to_numeric(mv["priority"], errors="coerce") if "priority" in mv.columns else 0
        valid = mv.dropna(subset=["created_date"])
        if not valid.empty:
            min_dt = max(valid["created_date"].min(), pd.to_datetime(ANALYSIS_START_DATE))
            max_cl = mv["closed_date"].max() if "closed_date" in mv.columns else pd.NaT
            max_dt = max_cl if pd.notna(max_cl) else valid["created_date"].max()
            if pd.notna(min_dt) and pd.notna(max_dt) and min_dt <= max_dt:
                months_m = list(pd.period_range(min_dt.to_period("M"), max_dt.to_period("M"), freq="M"))
                for mode in ["open_start", "new", "completed", "open_end"]:
                    tbl = build_bug_matrix(mv, months_m, mode)
                    tbl.loc["Total"] = tbl.sum(numeric_only=True)
                    if mode == "open_start":  m_open  = _matrix_table(tbl)
                    elif mode == "new":       m_new   = _matrix_table(tbl)
                    elif mode == "completed": m_comp  = _matrix_table(tbl)
                    elif mode == "open_end":  m_close = _matrix_table(tbl)

    # ── Function × Source correlations ────────────────────────────────────────
    # Safe defaults first so the return list never hits a NameError
    _excl_list = ["Not Specified", "Unassigned", ""]
    insight_row     = html.Div()
    fig_func_cust   = _empty_fig("No customer bug data")
    fig_func_int    = _empty_fig("No internal bug data")
    fig_func_priority = _empty_fig("No function / priority data")
    fig_func_mttc   = _empty_fig("No closed bugs with function data")

    try:
        _top_func, _top_cust, _top_int = "—", "—", "—"
        _top_func_n, _top_cust_n, _top_int_n = 0, 0, 0

        has_func = "function" in bugs_main.columns and not bugs_main.empty
        has_type = "type" in bugs_main.columns

        if has_func:
            _func_mask = ~bugs_main["function"].isin(_excl_list)
            _fc_all = bugs_main.loc[_func_mask, "function"].value_counts()
            if not _fc_all.empty:
                _top_func, _top_func_n = str(_fc_all.index[0]), int(_fc_all.iloc[0])

            if has_type:
                _c_mask = (bugs_main["type"] == "Customer") & _func_mask
                _i_mask = (bugs_main["type"] == "Internal") & _func_mask
                _cust_ser = bugs_main.loc[_c_mask, "function"].value_counts()
                _int_ser  = bugs_main.loc[_i_mask, "function"].value_counts()
                if not _cust_ser.empty:
                    _top_cust, _top_cust_n = str(_cust_ser.index[0]), int(_cust_ser.iloc[0])
                if not _int_ser.empty:
                    _top_int, _top_int_n = str(_int_ser.index[0]), int(_int_ser.iloc[0])

        def _chip(label, name, cnt, bg, border, color):
            return html.Span([
                html.Span(label, style={"fontSize": "11px", "color": "#94a3b8", "marginRight": "6px"}),
                html.Span(name,  style={"fontSize": "12px", "fontWeight": "700", "color": color}),
                html.Span(f" ({cnt})", style={"fontSize": "11px", "color": "#94a3b8"}),
            ], style={"background": bg, "border": border, "borderRadius": "8px",
                      "padding": "6px 14px", "display": "inline-block"})

        insight_row = html.Div([
            _chip("Most Buggy Function",   _top_func, _top_func_n,
                  "rgba(248,113,113,0.08)", "1px solid rgba(248,113,113,0.18)", "#f87171"),
            _chip("Top Customer Function", _top_cust, _top_cust_n,
                  "rgba(192,96,96,0.08)",  "1px solid rgba(192,96,96,0.2)",    "#c06060"),
            _chip("Top Internal Function", _top_int,  _top_int_n,
                  "rgba(99,179,237,0.08)", "1px solid rgba(99,179,237,0.2)",   "#63b3ed"),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "8px", "marginBottom": "18px"})

        # Customer / Internal bars
        if has_func and has_type:
            for _src, _clr, _title, _attr in [
                ("Customer", "#c06060", "Customer Bugs by Function", "fig_func_cust"),
                ("Internal", "#63b3ed", "Internal Bugs by Function", "fig_func_int"),
            ]:
                _src_mask = (bugs_main["type"] == _src) & ~bugs_main["function"].isin(_excl_list)
                _sub = bugs_main.loc[_src_mask, "function"].value_counts().head(15).reset_index()
                _sub.columns = ["Function", "Count"]
                if not _sub.empty:
                    _sub = _sub.sort_values("Count", ascending=True)
                    _fig = go.Figure(go.Bar(
                        x=_sub["Count"], y=_sub["Function"], orientation="h",
                        marker_color=_clr, text=_sub["Count"],
                        textposition="outside", textfont=dict(size=11),
                        hovertemplate="%{y}: %{x} bugs<extra></extra>",
                    ))
                    _fig.update_layout(title=_title,
                                       height=max(len(_sub) * 44 + 100, 300),
                                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                       margin=dict(t=50, b=20, l=185, r=80))
                    _fig.update_xaxes(title="Bug Count", gridcolor="rgba(255,255,255,0.06)")
                    if _attr == "fig_func_cust":
                        fig_func_cust = _fig
                    else:
                        fig_func_int = _fig

        # Function × Priority stacked bar
        if has_func and "priority" in bugs_main.columns:
            _fp = bugs_main.loc[~bugs_main["function"].isin(_excl_list)].copy()
            if not _fp.empty:
                _top10 = _fp["function"].value_counts().head(10).index.tolist()
                _fp = _fp.loc[_fp["function"].isin(_top10)].copy()
                _fp["priority_label"] = (
                    pd.to_numeric(_fp["priority"], errors="coerce")
                    .map({1: "P1", 2: "P2", 3: "P3", 4: "P4"})
                    .fillna("Other")
                )
                _grp = _fp.groupby(["function", "priority_label"]).size().reset_index(name="count")
                if not _grp.empty:
                    fig_func_priority = px.bar(
                        _grp, x="function", y="count", color="priority_label", barmode="stack",
                        title="Top 10 Functions — Priority Breakdown",
                        labels={"function": "", "count": "Bug Count", "priority_label": "Priority"},
                        category_orders={"priority_label": ["P1", "P2", "P3", "P4", "Other"]},
                        color_discrete_map={"P1": "#c05050", "P2": "#dd6b20",
                                            "P3": "#3182ce", "P4": "#805ad5", "Other": "#64748b"},
                    )
                    fig_func_priority.update_layout(
                        height=360, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(t=50, b=90, l=60, r=20),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                    )
                    fig_func_priority.update_xaxes(tickangle=-35, gridcolor="rgba(255,255,255,0.06)")
                    fig_func_priority.update_yaxes(gridcolor="rgba(255,255,255,0.06)")

        # Function × MTTC
        if "state" in df_all.columns:
            _cb_f = df_all.loc[df_all["state"] == "Closed"].copy()
            if (not _cb_f.empty and "function" in _cb_f.columns
                    and "created_date" in _cb_f.columns and "closed_date" in _cb_f.columns):
                _cb_f = _cb_f.loc[~_cb_f["function"].isin(_excl_list)].copy()
                _cb_f["cycle_days"] = (_cb_f["closed_date"] - _cb_f["created_date"]).dt.days
                _cb_f = _cb_f.loc[_cb_f["cycle_days"].notna() & (_cb_f["cycle_days"] >= 0)]
                if not _cb_f.empty:
                    _mttc_f = (_cb_f.groupby("function")["cycle_days"]
                               .agg(["mean", "count"]).reset_index())
                    _mttc_f.columns = ["Function", "Avg Days", "Count"]
                    _mttc_f = (_mttc_f[_mttc_f["Count"] >= 2]
                               .sort_values("Avg Days", ascending=False).head(15)
                               .sort_values("Avg Days", ascending=True))
                    _mttc_f["Avg Days"] = _mttc_f["Avg Days"].round(1)
                    if not _mttc_f.empty:
                        fig_func_mttc = go.Figure(go.Bar(
                            x=_mttc_f["Avg Days"], y=_mttc_f["Function"], orientation="h",
                            marker_color="#a78bfa",
                            text=_mttc_f["Avg Days"].apply(lambda v: f"{v:.1f}d"),
                            textposition="outside", textfont=dict(size=11),
                            customdata=_mttc_f["Count"],
                            hovertemplate="%{y}<br>Avg: %{x:.1f}d · %{customdata} closed<extra></extra>",
                        ))
                        fig_func_mttc.update_layout(
                            title="Avg Days to Fix by Function (≥2 closed bugs)",
                            height=max(len(_mttc_f) * 44 + 100, 300),
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(t=50, b=20, l=185, r=100),
                        )
                        fig_func_mttc.update_xaxes(title="Avg Days to Close",
                                                   gridcolor="rgba(255,255,255,0.06)")

    except Exception as _corr_err:
        print(f"[Items] Correlation charts error: {_corr_err}")

    return [
        html.Div([
            _section_label("Source & Resolution Speed"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_source), className="chart-card"), md=5),
                dbc.Col(html.Div(dcc.Graph(figure=fig_mttc),   className="chart-card"), md=7),
            ]),
        ], style=_SB),
        html.Div([
            _section_label("Hotspots"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_area), className="chart-card"), md=5),
                dbc.Col(html.Div(dcc.Graph(figure=fig_func), className="chart-card"), md=7),
            ]),
        ], style=_SB),
        html.Div([
            _section_label("Customer vs Internal — Weekly Trend"),
            html.Div("Track how customer-reported vs internally-caught bugs evolve week over week. "
                     "A growing Customer line signals quality escaping to production.",
                     className="chart-insight"),
            html.Div(dcc.Graph(figure=fig_ci), className="chart-card"),
        ], style=_SB),
        html.Div([
            _section_label("Function Breakdown — Customer vs Internal"),
            html.Div("Which functions generate the most customer-facing vs internally-caught bugs. "
                     "Use these to prioritise QA coverage and code review focus.",
                     className="chart-insight"),
            insight_row,
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_func_cust), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_func_int),  className="chart-card"), md=6),
            ]),
        ], style=_SB),
        html.Div([
            _section_label("Function Quality Signals"),
            html.Div("Priority concentration per function reveals severity hotspots. "
                     "Fix time per function exposes complexity debt — where bugs take longest to resolve.",
                     className="chart-insight"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_func_priority), className="chart-card"), md=7),
                dbc.Col(html.Div(dcc.Graph(figure=fig_func_mttc),     className="chart-card"), md=5),
            ]),
        ], style=_SB),
        dbc.Button("📊 Show / Hide Bug Movement Matrices",
                   id="bug-matrix-toggle", color="light", outline=True, size="sm",
                   style={"marginBottom": "12px", "fontSize": "13px"}),
        dbc.Collapse(
            html.Div([
                html.P("Opening Balance + New − Completed = Closing Balance. "
                       "Use for monthly data integrity checks.",
                       style={"fontSize": "12px", "color": "#718096", "marginBottom": "12px"}),
                html.Div("🟦 Opening Balance", className="chart-title", style={"fontSize": "13px"}),
                html.Div(m_open,  className="chart-card"),
                html.Div("🟧 New Bugs",        className="chart-title", style={"fontSize": "13px"}),
                html.Div(m_new,   className="chart-card"),
                html.Div("🟩 Completed",       className="chart-title", style={"fontSize": "13px"}),
                html.Div(m_comp,  className="chart-card"),
                html.Div("⬜ Closing Balance",  className="chart-title", style={"fontSize": "13px"}),
                html.Div(m_close, className="chart-card"),
            ]),
            id="bug-matrix-collapse", is_open=False,
        ),
    ]


def _section_general(df_all, open_items, type_label):
    """Enhancement / User Story / Feature / Task: state, cycle time, area, iteration."""
    # State distribution
    if "state" in df_all.columns and not df_all.empty:
        sc = df_all["state"].value_counts().reset_index()
        sc.columns = ["State", "Count"]
        sc = sc.sort_values("Count", ascending=True)
        fig_state = go.Figure(go.Bar(x=sc["Count"], y=sc["State"], orientation="h",
                                     marker_color="#818cf8", text=sc["Count"],
                                     textposition="outside", textfont=dict(size=11)))
        fig_state.update_layout(title=f"{type_label} by State",
                                height=max(len(sc) * 38 + 100, 280),
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(t=50, b=20, l=185, r=80))
        fig_state.update_xaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_state = _empty_fig("No state data")

    # Cycle time histogram
    closed = df_all[df_all["state"].isin(CLOSED_STATES)].copy() if "state" in df_all.columns else pd.DataFrame()
    if (not closed.empty and "created_date" in closed.columns and "closed_date" in closed.columns):
        closed["cycle_days"] = (closed["closed_date"] - closed["created_date"]).dt.days
        closed = closed[closed["cycle_days"].notna() & (closed["cycle_days"] >= 0)]
    if not closed.empty and "cycle_days" in closed.columns:
        fig_cycle = px.histogram(closed, x="cycle_days", nbins=20,
                                 title="Cycle Time Distribution — Days to Close",
                                 labels={"cycle_days": "Days to Close"},
                                 color_discrete_sequence=["#818cf8"])
        fig_cycle.update_layout(height=320, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(t=50, b=50, l=60, r=20))
        fig_cycle.update_xaxes(title="Days", gridcolor="rgba(255,255,255,0.06)")
        fig_cycle.update_yaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_cycle = _empty_fig("No closed items with date data")

    # Area breakdown
    if "area" in open_items.columns and not open_items.empty:
        ac = open_items["area"].value_counts().head(15).reset_index()
        ac.columns = ["Area", "Count"]
        ac = ac.sort_values("Count", ascending=True)
        fig_area = go.Figure(go.Bar(x=ac["Count"], y=ac["Area"], orientation="h",
                                    marker_color="#818cf8", text=ac["Count"],
                                    textposition="outside", textfont=dict(size=11)))
        fig_area.update_layout(title=f"Open {type_label} by Area",
                               height=max(len(ac) * 42 + 100, 280),
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               margin=dict(t=50, b=20, l=185, r=80))
        fig_area.update_xaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_area = _empty_fig("No area data")

    # Iteration distribution
    if "iteration_path" in df_all.columns and not df_all.empty:
        ic = df_all["iteration_path"].value_counts().head(12).reset_index()
        ic.columns = ["Iteration", "Count"]
        fig_iter = px.bar(ic, x="Iteration", y="Count",
                          title=f"{type_label} by Iteration",
                          color_discrete_sequence=["#34d399"])
        fig_iter.update_layout(height=320, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               margin=dict(t=50, b=80, l=60, r=20))
        fig_iter.update_xaxes(tickangle=-35, title="")
        fig_iter.update_yaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_iter = _empty_fig("No iteration data")

    return [
        html.Div([
            _section_label("State & Cycle Time"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_state), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_cycle), className="chart-card"), md=6),
            ]),
        ], style=_SB),
        html.Div([
            _section_label("Distribution"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_area), className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(figure=fig_iter), className="chart-card"), md=6),
            ]),
        ], style=_SB),
    ]


def _section_all(df_all, open_items):
    """All types: item mix, state distribution, area breakdown."""
    if "work_item_type" in df_all.columns and not df_all.empty:
        tc = df_all["work_item_type"].value_counts().reset_index()
        tc.columns = ["Type", "Count"]
        fig_types = px.pie(tc, names="Type", values="Count",
                           title="Item Type Distribution", hole=0.45)
        fig_types.update_traces(textposition="inside", textinfo="percent+label",
                                textfont_size=11, insidetextorientation="radial")
        fig_types.update_layout(height=320, margin=dict(t=50, b=60, l=10, r=10),
                                legend=dict(orientation="h", yanchor="bottom", y=-0.15,
                                            xanchor="center", x=0.5))
    else:
        fig_types = _empty_fig("No type data")

    if "state" in df_all.columns and not df_all.empty:
        sc = df_all["state"].value_counts().reset_index()
        sc.columns = ["State", "Count"]
        sc = sc.sort_values("Count", ascending=True)
        fig_state = go.Figure(go.Bar(x=sc["Count"], y=sc["State"], orientation="h",
                                     marker_color="#60a5fa", text=sc["Count"],
                                     textposition="outside", textfont=dict(size=11)))
        fig_state.update_layout(title="All Items by State",
                                height=max(len(sc) * 38 + 100, 300),
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(t=50, b=20, l=185, r=80))
        fig_state.update_xaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_state = _empty_fig("No state data")

    if "area" in open_items.columns and not open_items.empty:
        ac = open_items["area"].value_counts().head(15).reset_index()
        ac.columns = ["Area", "Count"]
        ac = ac.sort_values("Count", ascending=True)
        fig_area = go.Figure(go.Bar(x=ac["Count"], y=ac["Area"], orientation="h",
                                    marker_color="#60a5fa", text=ac["Count"],
                                    textposition="outside", textfont=dict(size=11)))
        fig_area.update_layout(title="Open Items by Area",
                               height=max(len(ac) * 42 + 100, 280),
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               margin=dict(t=50, b=20, l=185, r=80))
        fig_area.update_xaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_area = _empty_fig("No area data")

    return [
        html.Div([
            _section_label("Item Mix"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(figure=fig_types), className="chart-card"), md=5),
                dbc.Col(html.Div(dcc.Graph(figure=fig_state), className="chart-card"), md=7),
            ]),
        ], style=_SB),
        html.Div([
            _section_label("Area Breakdown"),
            html.Div(dcc.Graph(figure=fig_area), className="chart-card"),
        ], style=_SB),
    ]


# ── Matrix toggle ──────────────────────────────────────────────────────────────
@callback(
    Output("bug-matrix-collapse", "is_open"),
    Input("bug-matrix-toggle",    "n_clicks"),
    State("bug-matrix-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_matrices(n, is_open):
    return not is_open


# ── Main callback ──────────────────────────────────────────────────────────────
@callback(
    Output("items-kpi-row",          "children"),
    Output("items-priority-chart",   "figure"),
    Output("items-age-chart",        "figure"),
    Output("items-owner-chart",      "figure"),
    Output("items-flow-chart",       "figure"),
    Output("items-backlog-chart",    "figure"),
    Output("items-specific-content", "children"),
    Input("items-type",      "value"),
    Input("items-release",   "value"),
    Input("items-iteration", "value"),
    Input("items-team",      "value"),
    Input("items-employee",  "value"),
    Input("items-state",           "value"),
    Input("items-created-range",   "start_date"),
    Input("items-created-range",   "end_date"),
    Input("items-closed-range",    "start_date"),
    Input("items-closed-range",    "end_date"),
)
def update_items(item_type, release, iterations, team, employee, states_filter,
                 cr_start, cr_end, cl_start, cl_end):
    df = load_data()
    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]

    df = apply_filters(df, release=release, iterations=iterations, team=team, employee=employee)
    df = filter_activity_since(df, ANALYSIS_START_DATE)
    if cr_start and "created_date" in df.columns:
        df = df[df["created_date"].notna() & (df["created_date"] >= pd.to_datetime(cr_start))]
    if cr_end and "created_date" in df.columns:
        df = df[df["created_date"].notna() & (df["created_date"] <= pd.to_datetime(cr_end))]
    if cl_start and "closed_date" in df.columns:
        df = df[df["closed_date"].notna() & (df["closed_date"] >= pd.to_datetime(cl_start))]
    if cl_end and "closed_date" in df.columns:
        df = df[df["closed_date"].notna() & (df["closed_date"] <= pd.to_datetime(cl_end))]
    if states_filter:
        df = df[df["state"].isin(states_filter)]
    if item_type and item_type != "All" and "work_item_type" in df.columns:
        df = df[df["work_item_type"].str.contains(item_type, na=False, case=False)]

    today = pd.Timestamp.today().normalize()
    for col in ["created_date", "closed_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
            if df[col].dt.tz is not None:
                df[col] = df[col].dt.tz_localize(None)

    is_bug = (not item_type or item_type == "Bug")
    is_all = (item_type == "All")
    type_label = item_type if item_type and item_type != "All" else "Items"

    open_items   = df[~df["state"].isin(CLOSED_STATES)].copy() if "state" in df.columns else df.copy()
    closed_items = df[df["state"].isin(CLOSED_STATES)].copy() if "state" in df.columns else pd.DataFrame()

    total       = len(df)
    n_open      = len(open_items)
    n_closed    = len(closed_items)
    closure_pct = n_closed / total * 100 if total > 0 else 0

    cb = df[df["state"] == "Closed"].copy() if "state" in df.columns else pd.DataFrame()
    avg_mttc = None
    if (not cb.empty and "created_date" in cb.columns and "closed_date" in cb.columns):
        avg_mttc = (cb["closed_date"] - cb["created_date"]).dt.days.mean()

    def _kpi(label, val, cls="", subtitle=None):
        ch = [html.Div(label, className="metric-label"),
              html.Div(str(val), className=f"metric-value {cls}")]
        if subtitle:
            ch.append(html.Div(subtitle, className="kpi-subtitle"))
        return dbc.Col(html.Div(ch, className="metric-card"), md=3)

    mttc_str = f"{avg_mttc:.1f}d" if pd.notna(avg_mttc) else "—"

    if is_bug:
        p1 = int((open_items["priority"] == 1).sum()) if "priority" in open_items.columns else 0
        p2 = int((open_items["priority"] == 2).sum()) if "priority" in open_items.columns else 0
        rej = int(df["state"].isin(REJECTED_STATES).sum()) if "state" in df.columns else 0
        kpi_row = html.Div([
            dbc.Row([_kpi("Total Bugs", f"{total:,}"),
                     _kpi("Open", f"{n_open:,}", cls="danger" if n_open > 0 else "success"),
                     _kpi("P1 Open", f"{p1:,}", cls="danger" if p1 > 0 else "success"),
                     _kpi("P2 Open", f"{p2:,}", cls="warning" if p2 > 0 else "")],
                    className="g-3 mb-3"),
            dbc.Row([_kpi("Closed", f"{n_closed:,}", cls="success"),
                     _kpi("Closure %", f"{closure_pct:.1f}%",
                          cls="success" if closure_pct >= 70 else ("warning" if closure_pct >= 40 else "danger")),
                     _kpi("Rejected", f"{rej:,}", subtitle="Not an issue / Not required"),
                     _kpi("Avg MTTC", mttc_str, subtitle="Mean time to close")],
                    className="g-3"),
        ])
    elif is_all:
        bug_c  = int(df["work_item_type"].str.contains("Bug",         na=False, case=False).sum()) if "work_item_type" in df.columns else 0
        enh_c  = int(df["work_item_type"].str.contains("Enhancement", na=False, case=False).sum()) if "work_item_type" in df.columns else 0
        task_c = int(df["work_item_type"].str.contains("Task",        na=False, case=False).sum()) if "work_item_type" in df.columns else 0
        kpi_row = html.Div([
            dbc.Row([_kpi("Total Items", f"{total:,}"),
                     _kpi("Open", f"{n_open:,}", cls="danger" if n_open > 0 else "success"),
                     _kpi("Closed", f"{n_closed:,}", cls="success"),
                     _kpi("Closure %", f"{closure_pct:.1f}%",
                          cls="success" if closure_pct >= 70 else ("warning" if closure_pct >= 40 else "danger"))],
                    className="g-3 mb-3"),
            dbc.Row([_kpi("Bugs", f"{bug_c:,}"),
                     _kpi("Enhancements", f"{enh_c:,}"),
                     _kpi("Tasks", f"{task_c:,}"),
                     _kpi("Avg Days to Close", mttc_str)],
                    className="g-3"),
        ])
    else:
        in_prog = int(df["state"].isin(["Active", "In Progress", "In Development"]).sum()) if "state" in df.columns else 0
        valid_dates = open_items["created_date"].dropna() if "created_date" in open_items.columns else pd.Series(dtype="datetime64[ns]")
        oldest = f"{int((today - valid_dates.min()).days)}d" if not valid_dates.empty else "—"
        avg_age = f"{int((today - valid_dates).dt.days.mean())}d" if not valid_dates.empty else "—"
        kpi_row = html.Div([
            dbc.Row([_kpi(f"Total {type_label}s", f"{total:,}"),
                     _kpi("Open", f"{n_open:,}", cls="warning" if n_open > 0 else "success"),
                     _kpi("In Progress", f"{in_prog:,}"),
                     _kpi("Closed", f"{n_closed:,}", cls="success")],
                    className="g-3 mb-3"),
            dbc.Row([_kpi("Closure %", f"{closure_pct:.1f}%",
                          cls="success" if closure_pct >= 70 else ("warning" if closure_pct >= 40 else "danger")),
                     _kpi("Avg Days to Close", mttc_str, subtitle="All closed items"),
                     _kpi("Oldest Open", oldest, subtitle="Days since oldest open created"),
                     _kpi("Avg Open Age", avg_age, subtitle="Average age of open items")],
                    className="g-3"),
        ])

    # ── Common charts ──────────────────────────────────────────────────────────
    main_df = df[~df["state"].isin(EXCL_STATES)].copy() if "state" in df.columns else df.copy()
    if not main_df.empty and "priority" in main_df.columns:
        priority_counts = (main_df["priority"].value_counts().sort_index()
                           .reindex([1, 2, 3, 4], fill_value=0))
        fig_pri = go.Figure(go.Bar(
            x=["P1 🔥", "P2 ⚠️", "P3", "P4"], y=priority_counts.values,
            marker_color=P_COLORS, text=priority_counts.values,
            textposition="outside", textfont=dict(size=12),
            hovertemplate="%{x}: %{y}<extra></extra>",
        ))
        fig_pri.update_layout(title=f"{type_label} by Priority", height=340,
                              showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                              margin=dict(t=50, b=50, l=60, r=40))
        fig_pri.update_xaxes(tickfont=dict(size=13))
        fig_pri.update_yaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_pri = _empty_fig("No priority data")

    if not open_items.empty and "created_date" in open_items.columns:
        oba = open_items.copy()
        oba["age_days"] = (today - oba["created_date"]).dt.days.fillna(0)
        oba["age_bucket"] = pd.cut(oba["age_days"], bins=AGE_BINS, labels=AGE_LABELS, right=False)
        if "priority" in oba.columns:
            oba["priority_label"] = oba["priority"].map(
                {1: "P1🔥", 2: "P2⚠️", 3: "P3", 4: "P4"}).fillna("Unknown")
            age_grp = oba.groupby(["age_bucket", "priority_label"], observed=True).size().reset_index(name="count")
            if not age_grp.empty:
                fig_age = px.bar(age_grp, x="age_bucket", y="count", color="priority_label",
                                 barmode="stack", title=f"Open {type_label} Age Distribution",
                                 labels={"age_bucket": "Age", "count": "Count", "priority_label": "Priority"},
                                 category_orders={"age_bucket": AGE_LABELS,
                                                  "priority_label": ["P1🔥", "P2⚠️", "P3", "P4"]},
                                 color_discrete_map={"P1🔥": "#c05050", "P2⚠️": "#dd6b20",
                                                     "P3": "#3182ce", "P4": "#805ad5"})
                fig_age.update_layout(height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                      margin=dict(t=90, b=60, l=60, r=20),
                                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
                fig_age.update_yaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
            else:
                fig_age = _empty_fig("No open items")
        else:
            age_grp = oba.groupby("age_bucket", observed=True).size().reset_index(name="count")
            fig_age = px.bar(age_grp, x="age_bucket", y="count",
                             title=f"Open {type_label} Age Distribution",
                             color_discrete_sequence=["#818cf8"])
            fig_age.update_layout(height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                  margin=dict(t=50, b=60, l=60, r=20))
            fig_age.update_yaxes(title="Count", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_age = _empty_fig("No open items")

    if "assigned_to" in open_items.columns and not open_items.empty:
        owner = (open_items["assigned_to"].replace("Unassigned", "⚠️ Unassigned")
                 .value_counts().reset_index())
        owner.columns = ["Owner", "Count"]
        owner = owner.sort_values("Count", ascending=True).tail(20)
        colors = owner["Owner"].apply(lambda x: "#c06060" if "Unassigned" in x else "#63b3ed")
        fig_owner = go.Figure(go.Bar(x=owner["Count"], y=owner["Owner"], orientation="h",
                                     marker_color=colors, text=owner["Count"],
                                     textposition="outside", textfont=dict(size=11),
                                     hovertemplate="%{y}: %{x} open<extra></extra>"))
        fig_owner.update_layout(title=f"Open {type_label} by Owner",
                                height=max(len(owner) * 42 + 80, 260),
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(t=50, b=40, l=185, r=80))
        fig_owner.update_xaxes(title="Open Items", gridcolor="rgba(255,255,255,0.06)")
    else:
        fig_owner = _empty_fig("No open items with owner data")

    mv    = df.copy()
    valid = mv.dropna(subset=["created_date"]) if "created_date" in mv.columns else pd.DataFrame()
    fig_flow = fig_backlog = _empty_fig("Not enough date data")

    if not valid.empty:
        analysis_start = pd.to_datetime(ANALYSIS_START_DATE)
        min_dt  = max(valid["created_date"].min(), analysis_start)
        max_dtc = valid["created_date"].max()
        max_dtl = mv["closed_date"].max() if "closed_date" in mv.columns else pd.NaT
        max_dt  = max_dtl if pd.notna(max_dtl) else max_dtc

        if pd.notna(min_dt) and pd.notna(max_dt) and min_dt <= max_dt:
            months = list(pd.period_range(min_dt.to_period("M"), max_dt.to_period("M"), freq="M"))
            monthly = {"month": [str(m) for m in months], "New": [], "Completed": [], "Opening": [], "Closing": []}
            for month in months:
                ms    = month.to_timestamp()
                me    = (month + 1).to_timestamp()
                new_n = len(mv[(mv["created_date"] >= ms) & (mv["created_date"] < me)])
                cmp_n = len(mv[(mv["closed_date"] >= ms) & (mv["closed_date"] < me)]) if "closed_date" in mv.columns else 0
                opn_n = len(mv[(mv["created_date"] < ms) &
                               (mv["closed_date"].isna() | (mv["closed_date"] >= ms))]) if "closed_date" in mv.columns else 0
                monthly["New"].append(new_n)
                monthly["Completed"].append(cmp_n)
                monthly["Opening"].append(opn_n)
                monthly["Closing"].append(max(opn_n + new_n - cmp_n, 0))

            mdf = pd.DataFrame(monthly)
            fig_flow = px.line(
                mdf.melt(id_vars="month", value_vars=["Opening", "New", "Completed"]),
                x="month", y="value", color="variable", markers=True,
                title=f"{type_label} Flow Over Time",
                labels={"month": "", "value": "Count", "variable": ""},
                color_discrete_map={"Opening": "#5a8fd4", "New": "#c97d3a", "Completed": "#3d9e6b"},
            )
            fig_flow.update_layout(height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                   margin=dict(t=90, b=60, l=60, r=20), hovermode="x unified",
                                   legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
            fig_flow.update_xaxes(tickangle=-30)
            fig_flow.update_yaxes(gridcolor="rgba(255,255,255,0.06)")

            trend_dir = ("📈 INCREASING ⚠️"
                         if len(mdf) >= 2 and mdf["Closing"].iloc[-1] > mdf["Closing"].iloc[0]
                         else "📉 DECREASING ✅")
            fig_backlog = px.bar(mdf, x="month", y="Closing",
                                 title=f"{type_label} Backlog (End-of-Month) — {trend_dir}",
                                 color="Closing",
                                 color_continuous_scale="Reds" if is_bug else "Blues",
                                 labels={"month": "", "Closing": "Open"})
            fig_backlog.update_layout(height=340, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                      margin=dict(t=50, b=60, l=60, r=20), showlegend=False)
            fig_backlog.update_xaxes(tickangle=-30)
            fig_backlog.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig_backlog.update_coloraxes(showscale=False)

    # ── Type-specific section ──────────────────────────────────────────────────
    if is_bug:
        specific = _section_bug(df, open_items, today)
    elif is_all:
        specific = _section_all(df, open_items)
    else:
        specific = _section_general(df, open_items, type_label)

    return kpi_row, fig_pri, fig_age, fig_owner, fig_flow, fig_backlog, specific


# ── Report callback ───────────────────────────────────────────────────────────
@callback(
    Output("items-report-modal", "is_open"),
    Output("items-report-body",  "children"),
    Output("items-report-ts",    "children"),
    Input("items-report-btn",    "n_clicks"),
    prevent_initial_call=True,
)
def _open_items_report(n):
    if not n:
        from dash import no_update
        return no_update, no_update, no_update
    df      = load_data()
    summary = summarize_bugs(df)
    body    = format_report(summary)
    ts      = f"Generated {summary['as_of']}  •  {summary['total']} total bugs  •  {summary['total_open']} open"
    return True, body, ts


@callback(
    Output("items-rec-strip", "children"),
    Input("items-type",      "value"),
    Input("items-release",   "value"),
    Input("items-iteration", "value"),
    Input("items-team",      "value"),
    Input("items-employee",  "value"),
)
def update_items_recs(item_types, release, iterations, team, employee):
    df = load_data()
    df = apply_filters(df, item_types=item_types, release=release,
                       iterations=iterations, team=team, employee=employee)
    df = filter_activity_since(df, ANALYSIS_START_DATE)
    recs = get_recommendations_bugs(df)
    return rec_strip(recs)
