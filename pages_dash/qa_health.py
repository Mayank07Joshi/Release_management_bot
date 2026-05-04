"""QA Health Dashboard — Testing volume, defect discovery, SLAs, and workload."""

import base64
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data, apply_filters, filter_activity_since
from config.settings import ANALYSIS_START_DATE
from config.team_mapping import QA_TEAM_MEMBERS
from reports.summarizer import summarize_qa
from reports.formatter import format_report

dash.register_page(__name__, path="/qa-health", name="QA Health")

# SLA targets (days to fix per priority)
SLA = {1: 1, 2: 2, 3: 5, 4: 10}

CLOSED_STATES  = {"Closed"}
REJECTED_STATES = {"Not an issue", "Not Required", "No Customer Response"}
OPEN_STATES_QA  = CLOSED_STATES | REJECTED_STATES  # non-open

_STATE_MAP_QA = {
    "New": "🆕 New", "Active": "🔵 Active", "Dev InProgress": "🔵 Active",
    "Dev Review": "🔵 Active", "Tester Assigned": "🔵 Active",
    "Dev Complete": "🟡 In Review", "Request Estimate": "🟡 In Review",
    "Clarification": "🟡 In Review", "Estimated": "🟡 In Review",
    "Watch List": "⏸ On Hold", "On Hold": "⏸ On Hold",
    "Reopened": "🔴 Reopened", "Resolved": "✅ Resolved",
    "Closed": "✅ Closed", "Not an issue": "❌ Rejected",
    "Not Required": "❌ Rejected", "No Customer Response": "❌ Rejected",
    "Userstory Update": "❌ Rejected",
}

# ── Table style constants ──────────────────────────────────────────────────────
_TH_QA = {
    "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
    "letterSpacing": "0.5px", "color": "#8892a4",
    "padding": "8px 12px", "borderBottom": "1px solid rgba(255,255,255,0.08)",
    "textAlign": "left", "whiteSpace": "nowrap",
}
_TD_QA = {
    "fontSize": "12px", "padding": "9px 12px",
    "borderBottom": "1px solid rgba(255,255,255,0.04)",
    "color": "#c8c8e0", "verticalAlign": "middle",
}


def _priority_pill_qa(p):
    """Return an html.Span pill for a priority int."""
    try:
        p_int = int(p) if pd.notna(p) else 0
    except Exception:
        p_int = 0
    cls = {1: "pill pill-p1", 2: "pill pill-p2", 3: "pill pill-p3", 4: "pill pill-p4"}.get(p_int, "pill pill-p4")
    lbl = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}.get(p_int, f"P{p_int}")
    return html.Span(lbl, className=cls)


def _state_pill_qa(s):
    """Return an html.Span pill for a state string."""
    s = str(s) if pd.notna(s) else ""
    disp = _STATE_MAP_QA.get(s, s)
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


# ── Layout ─────────────────────────────────────────────────────────────────────
def layout():
    df = load_data()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)
    iters = sorted(
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
                html.Div("Iteration", className="filter-label"),
                dcc.Dropdown(id="qa-iteration",
                             options=[{"label": i, "value": i} for i in iters],
                             value=[], multi=True, placeholder="All iterations",
                             style={"fontSize": "12px"}),
            ], md=6),
            dbc.Col([
                html.Div("Throughput Grouping", className="filter-label"),
                dcc.Dropdown(id="qa-grouping",
                             options=[{"label": "Weekly",       "value": "Weekly"},
                                      {"label": "By Iteration", "value": "By Iteration"}],
                             value="Weekly", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
            dbc.Col([
                html.Div("Heatmap Dimension", className="filter-label"),
                dcc.Dropdown(id="qa-heatmap-dim",
                             options=[{"label": "Area",     "value": "area"},
                                      {"label": "Function", "value": "function"}],
                             value="area", clearable=False, style={"fontSize": "12px"}),
            ], md=3),
        ], className="g-2"),
    ], style=_fb)

    _sb = {
        "background": "rgba(255,255,255,0.015)",
        "borderRadius": "12px",
        "border": "1px solid rgba(255,255,255,0.04)",
        "padding": "20px 20px 12px 20px",
        "marginBottom": "24px",
    }

    qa_report_modal = dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("📄 QA Health Report"), close_button=True),
        dbc.ModalBody(
            html.Div(id="qa-report-body",
                     style={"maxHeight": "70vh", "overflowY": "auto", "padding": "4px 8px"}),
        ),
        dbc.ModalFooter(
            html.Span(id="qa-report-ts", style={"fontSize": "11px", "color": "#8892a4"}),
        ),
    ], id="qa-report-modal", is_open=False, size="xl", backdrop="static",
       style={"--bs-modal-bg": "#13131f", "color": "#e2e8f0"})

    return html.Div([
        html.Div([
            html.Div([
                html.H1("🧪 QA Health", className="page-title"),
                html.P("Testing volume, defect discovery, fix SLAs, and QA workload.",
                       className="page-subtitle"),
            ]),
            dbc.Button("📄 Board Report", id="qa-report-btn", size="sm",
                       style={"background": "rgba(129,140,248,0.15)", "border": "1px solid rgba(129,140,248,0.3)",
                              "color": "#818cf8", "fontWeight": "600", "alignSelf": "center"}),
        ], className="page-header", style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}),

        filter_bar,

        # ── KPIs ──────────────────────────────────────────────────────────────
        html.Div([
            _section_label("At a Glance"),
            html.Div(id="qa-kpi-row"),
        ], style=_sb),

        # ── Output & Quality ──────────────────────────────────────────────────
        html.Div([
            _section_label("Output & Quality"),
            dbc.Row([
                dbc.Col(html.Div(dcc.Graph(id="qa-throughput"),       className="chart-card"), md=6),
                dbc.Col(html.Div(dcc.Graph(id="qa-defect-discovery"), className="chart-card"), md=6),
            ], className="mb-2"),
        ], style=_sb),

        # ── Fix Speeds & SLA Compliance ───────────────────────────────────────
        html.Div([
            _section_label("Fix Speeds & SLA Compliance"),
            html.P("Are we fixing critical bugs within expected timeframes? (P1=1d, P2=2d, P3=5d)",
                   style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
            html.Div(dcc.Graph(id="qa-sla"),   className="chart-card mb-3"),
            html.Div(dcc.Graph(id="qa-aging"), className="chart-card"),
        ], style=_sb),

        # ── Defect Clustering Heatmap ─────────────────────────────────────────
        html.Div([
            _section_label("Defect Clustering Heatmap"),
            html.P("Where are the bugs hiding? Darker red = high volume of critical issues.",
                   style={"fontSize": "12px", "color": "#718096", "marginBottom": "10px"}),
            html.Div(dcc.Graph(id="qa-heatmap"), className="chart-card"),
        ], style=_sb),

        # ── QA Team Output & Workload ─────────────────────────────────────────
        html.Div([
            _section_label("QA Team Output & Workload"),
            html.Div(dcc.Graph(id="qa-member-tp"), className="chart-card mb-3"),
            html.Div(dcc.Graph(id="qa-workload"),  className="chart-card"),
        ], style=_sb),

        # ── Raw Data Table ────────────────────────────────────────────────────
        html.Div([
            _section_label("Recent QA Items"),
            html.Div(id="qa-recent-table"),
        ], style=_sb),
        qa_report_modal,
    ])


# ── Callback ───────────────────────────────────────────────────────────────────
@callback(
    Output("qa-kpi-row",          "children"),
    Output("qa-throughput",       "figure"),
    Output("qa-defect-discovery", "figure"),
    Output("qa-sla",              "figure"),
    Output("qa-aging",            "figure"),
    Output("qa-heatmap",          "figure"),
    Output("qa-member-tp",        "figure"),
    Output("qa-workload",         "figure"),
    Output("qa-recent-table",     "children"),
    Input("qa-iteration",         "value"),
    Input("qa-grouping",          "value"),
    Input("qa-heatmap-dim",       "value"),
)
def update_qa(iterations, grouping, heatmap_dim):
    df = load_data()
    df = apply_filters(df, iterations=iterations)
    df = filter_activity_since(df, ANALYSIS_START_DATE)

    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(_strip_iter)

    # Data subsets
    qa_df = df[df["assigned_to"].isin(QA_TEAM_MEMBERS)].copy()
    bugs  = df[df["work_item_type"].str.contains("Bug", na=False, case=False)].copy()

    if "created_date" in bugs.columns:
        bugs["created_date"] = pd.to_datetime(bugs["created_date"], errors="coerce")
    if "closed_date" in bugs.columns:
        bugs["closed_date"]  = pd.to_datetime(bugs["closed_date"],  errors="coerce")
    if "priority" in bugs.columns:
        bugs["priority"] = pd.to_numeric(bugs["priority"], errors="coerce").astype("Int64")

    # ── KPIs ───────────────────────────────────────────────────────────────────
    total_qa  = len(qa_df)
    open_qa   = len(qa_df[~qa_df["state"].isin(OPEN_STATES_QA)]) if "state" in qa_df.columns else 0
    total_bugs = len(bugs)
    open_bugs  = bugs[~bugs["state"].isin(OPEN_STATES_QA)] if "state" in bugs.columns else bugs
    p1_open   = len(open_bugs[open_bugs["priority"] == 1]) if "priority" in open_bugs.columns else 0
    p2_open   = len(open_bugs[open_bugs["priority"] == 2]) if "priority" in open_bugs.columns else 0

    qa_assigned = pd.to_numeric(qa_df.get("original_estimate", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
    qa_comp     = pd.to_numeric(qa_df.get("completed_work",    pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
    qa_acc      = (qa_comp / qa_assigned * 100) if qa_assigned > 0 else 0
    acc_color   = "" if 85 <= qa_acc <= 115 else ("warning" if 70 <= qa_acc < 85 else "danger")

    closed_bugs_all = bugs[bugs["closed_date"].notna()] if "closed_date" in bugs.columns else pd.DataFrame()
    mttc = 0.0
    if not closed_bugs_all.empty and "created_date" in closed_bugs_all.columns:
        mttc = (closed_bugs_all["closed_date"] - closed_bugs_all["created_date"]).dt.days.median()
        mttc = mttc if pd.notna(mttc) else 0.0

    # Weekly bug sparkline (last 8 weeks)
    today_qa = pd.Timestamp.today().normalize()
    _bugs_w, _p1_w = [], []
    for w in range(7, -1, -1):
        w_end = today_qa - pd.Timedelta(weeks=w)
        _bugs_w.append(int((bugs["created_date"] <= w_end).sum())
                       if "created_date" in bugs.columns else 0)
        if "priority" in bugs.columns and "created_date" in bugs.columns:
            _p1_w.append(int((
                (bugs["priority"] == 1) &
                (bugs["created_date"] <= w_end) &
                (bugs["closed_date"].isna() | (bugs["closed_date"] > w_end))
            ).sum()) if "closed_date" in bugs.columns else 0)
        else:
            _p1_w.append(0)

    sl_bugs = _sparkline_svg(_bugs_w, color="#c05050")
    sl_p1   = _sparkline_svg(_p1_w,   color="#c05050")

    def _kpi(label, val, cls="", subtitle=None, sparkline_src=None):
        children = [
            html.Div(label, className="metric-label"),
            html.Div(str(val), className=f"metric-value {cls}"),
        ]
        if subtitle:
            children.append(html.Div(subtitle, className="kpi-subtitle"))
        if sparkline_src:
            children.append(html.Div(
                html.Img(src=sparkline_src, style={"width": "100%", "height": "28px", "display": "block"}),
                className="kpi-sparkline",
            ))
        return dbc.Col(html.Div(children, className="metric-card"), md=3)

    kpi_row = html.Div([
        dbc.Row([
            _kpi("QA Items",      f"{total_qa:,}"),
            _kpi("QA Open",       f"{open_qa:,}"),
            _kpi("Total Bugs",    f"{total_bugs:,}", sparkline_src=sl_bugs),
            _kpi("P1 Open",       f"{p1_open:,}",
                 cls="danger" if p1_open > 0 else "success", sparkline_src=sl_p1),
        ], className="g-3 mb-3"),
        dbc.Row([
            _kpi("P2 Open",        f"{p2_open:,}",
                 cls="warning" if p2_open > 0 else ""),
            _kpi("QA Hours Logged", f"{qa_comp:,.0f}h"),
            _kpi("QA Est. Accuracy", f"{qa_acc:.1f}%", cls=acc_color,
                 subtitle="Completed ÷ assigned"),
            _kpi("Median MTTC",   f"{mttc:.1f}d",
                 subtitle="Days to close bugs"),
        ], className="g-3"),
    ])

    # ── 1. QA Throughput ───────────────────────────────────────────────────────
    if "closed_date" in qa_df.columns and "completed_work" in qa_df.columns:
        d = qa_df.dropna(subset=["closed_date"]).copy()
        d["week"] = pd.to_datetime(d["closed_date"], errors="coerce").dt.to_period("W").dt.start_time
        d["comp"] = pd.to_numeric(d["completed_work"], errors="coerce").fillna(0)
        weekly = d.groupby("week")["comp"].sum().reset_index()
        if not weekly.empty:
            fig_tp = px.line(weekly, x="week", y="comp", markers=True,
                             title="QA Testing Output (Hours per week)",
                             color_discrete_sequence=["#5a8fd4"],
                             labels={"week": "", "comp": "Hours"})
            fig_tp.update_layout(height=380, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                 margin=dict(t=50, b=80, l=60, r=20))
            fig_tp.update_xaxes(tickangle=-35, tickfont=dict(size=12))
            fig_tp.update_yaxes(title="Hours Logged", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12))
        else:
            fig_tp = _empty_fig("No QA throughput data")
    else:
        fig_tp = _empty_fig()

    # ── 2. Defect Discovery Trend ──────────────────────────────────────────────
    if "created_date" in bugs.columns:
        b_trend = bugs.dropna(subset=["created_date"]).copy()
        b_trend["week"] = b_trend["created_date"].dt.to_period("W").dt.start_time
        b_count = b_trend.groupby("week").size().reset_index(name="bug_count")
        if not b_count.empty:
            fig_disc = px.bar(b_count, x="week", y="bug_count",
                              title="New Bugs Discovered (Per Week)",
                              color_discrete_sequence=["#c05050"],
                              labels={"week": "", "bug_count": "Bugs"})
            fig_disc.update_layout(height=380, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                   margin=dict(t=50, b=80, l=60, r=20))
            fig_disc.update_xaxes(tickangle=-35, tickfont=dict(size=12))
            fig_disc.update_yaxes(title="Bugs Found", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12))
        else:
            fig_disc = _empty_fig("No defect discovery data")
    else:
        fig_disc = _empty_fig()

    # ── 3. SLA Compliance ─────────────────────────────────────────────────────
    closed_bugs = bugs[bugs["closed_date"].notna()].copy() if "closed_date" in bugs.columns else pd.DataFrame()
    if not closed_bugs.empty and "priority" in closed_bugs.columns and "created_date" in closed_bugs.columns:
        closed_bugs["aging_days"] = (closed_bugs["closed_date"] - closed_bugs["created_date"]).dt.days
        closed_bugs["sla_days"]   = closed_bugs["priority"].map(SLA)
        closed_bugs["compliant"]  = closed_bugs["aging_days"] <= closed_bugs["sla_days"]
        comp = (closed_bugs.groupby("priority")["compliant"].mean()
                .reindex([1, 2, 3, 4], fill_value=0).reset_index(name="rate"))
        comp["priority_label"] = "P" + comp["priority"].astype(str)
        comp["rate_pct"] = (comp["rate"] * 100).round(1)

        fig_sla = go.Figure(go.Bar(
            x=comp["rate_pct"], y=comp["priority_label"], orientation="h",
            marker_color=[
                "#3d9e6b" if v >= 80 else ("#c97d3a" if v >= 60 else "#c05050")
                for v in comp["rate_pct"]
            ],
            text=comp["rate_pct"].apply(lambda v: f"{v:.1f}%"),
            textposition="outside", textfont=dict(size=13),
            hovertemplate="%{y}: %{x:.1f}% compliant<extra></extra>",
        ))
        fig_sla.add_vline(x=100, line_dash="dash", line_color="#718096",
                          annotation_text="Target", annotation_position="top right",
                          annotation_font=dict(size=11))
        fig_sla.update_layout(
            title="SLA Compliance % by Priority  (green ≥ 80%, orange ≥ 60%, red < 60%)",
            height=280,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=40, l=60, r=80),
        )
        fig_sla.update_xaxes(title="Compliance %", range=[0, 120],
                             gridcolor="rgba(255,255,255,0.06)", ticksuffix="%", tickfont=dict(size=13))
        fig_sla.update_yaxes(tickfont=dict(size=13))
    else:
        fig_sla = _empty_fig("No closed bugs with priority data")

    # ── 4. Defect Aging Boxplot ────────────────────────────────────────────────
    if not closed_bugs.empty and "priority" in closed_bugs.columns and "created_date" in closed_bugs.columns:
        closed_bugs["aging_days"]     = (closed_bugs["closed_date"] - closed_bugs["created_date"]).dt.days
        closed_bugs["priority_label"] = "P" + closed_bugs["priority"].astype(str)
        fig_age = px.box(
            closed_bugs, x="priority_label", y="aging_days", color="priority_label",
            title="Defect Aging Distribution (Days to Fix)",
            color_discrete_map={"P1": "#c05050", "P2": "#c97d3a", "P3": "#c9963a", "P4": "#5a8fd4"},
            labels={"priority_label": "", "aging_days": "Days to Fix"},
        )
        fig_age.update_layout(
            height=400, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=50, b=50, l=60, r=20), showlegend=False,
        )
        fig_age.update_xaxes(tickfont=dict(size=13))
        fig_age.update_yaxes(title="Days to Fix", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
    else:
        fig_age = _empty_fig("No closed bugs for aging analysis")

    # ── 5. Defect Clustering Heatmap ──────────────────────────────────────────
    if "priority" in bugs.columns and heatmap_dim in bugs.columns:
        bugs["priority_num"] = pd.to_numeric(bugs["priority"], errors="coerce").fillna(0).astype(int)
        pivot = (bugs.groupby([heatmap_dim, "priority_num"]).size()
                 .unstack(fill_value=0).reindex(columns=[1, 2, 3, 4], fill_value=0))
        pivot.columns = ["P1", "P2", "P3", "P4"]
        if not pivot.empty:
            fig_hm = px.imshow(pivot, color_continuous_scale="Reds", aspect="auto",
                               title=f"Bug Severity Heatmap by {heatmap_dim.title()}")
            fig_hm.update_layout(
                height=max(len(pivot) * 35 + 150, 400),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=50, b=20, l=200, r=20),
            )
            fig_hm.update_xaxes(tickfont=dict(size=13))
            fig_hm.update_yaxes(tickfont=dict(size=13))
            max_val = pivot.max().max()
            for i in range(len(pivot.index)):
                for j in range(len(pivot.columns)):
                    val = pivot.iloc[i, j]
                    fig_hm.add_annotation(
                        x=j, y=i, text=str(val), showarrow=False,
                        font=dict(color="white" if val >= max_val / 2 else "black", size=12),
                    )
        else:
            fig_hm = _empty_fig("No bug data for heatmap")
    else:
        fig_hm = _empty_fig()

    # ── 6. QA Member Throughput ───────────────────────────────────────────────
    if "completed_work" in qa_df.columns:
        d3 = qa_df.copy()
        d3["comp"] = pd.to_numeric(d3["completed_work"], errors="coerce").fillna(0)

        if grouping == "By Iteration" and "iteration_path" in d3.columns:
            g = d3.groupby(["iteration_path", "assigned_to"])["comp"].sum().reset_index()
            if not g.empty:
                fig_mtp = px.bar(
                    g, x="iteration_path", y="comp", color="assigned_to", barmode="group",
                    title="QA Hours Logged by Member per Iteration",
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
                fig_mtp = _empty_fig("No QA data for selected iterations")
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
                    title="Total QA Throughput by Member (Hours Logged)",
                    height=max(len(g) * 42 + 120, 300),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=50, b=40, l=185, r=80),
                )
                fig_mtp.update_xaxes(title="Hours", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=13))
                fig_mtp.update_yaxes(tickfont=dict(size=13))
            else:
                fig_mtp = _empty_fig("No QA throughput data")
    else:
        fig_mtp = _empty_fig()

    # ── 7. QA Workload Dot-Plot ────────────────────────────────────────────────
    if {"original_estimate", "completed_work"}.issubset(qa_df.columns):
        d4 = qa_df.copy()
        d4["orig"] = pd.to_numeric(d4["original_estimate"], errors="coerce").fillna(0)
        d4["comp"] = pd.to_numeric(d4["completed_work"],    errors="coerce").fillna(0)
        g4 = d4.groupby("assigned_to")[["orig", "comp"]].sum().reset_index()
        g4["rem"] = (g4["orig"] - g4["comp"]).clip(lower=0)
        long = g4.melt(id_vars="assigned_to", value_vars=["orig", "comp", "rem"],
                       var_name="Type", value_name="Hours").replace(
            {"orig": "Assigned", "comp": "Completed", "rem": "Remaining"})
        if not long.empty:
            fig_wl = px.scatter(
                long, x="Hours", y="assigned_to", color="Type", opacity=0.85,
                title="QA Individual Workload — Assigned vs Completed vs Remaining",
                color_discrete_map={"Assigned": "#5a8fd4", "Completed": "#3d9e6b", "Remaining": "#fc8181"},
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
            fig_wl = _empty_fig("No QA workload data")
    else:
        fig_wl = _empty_fig()

    # ── 8. Recent QA Table ─────────────────────────────────────────────────────
    cols = [c for c in ["title", "work_item_type", "state", "priority",
                        "assigned_to", "iteration_path"] if c in df.columns]
    table_df = bugs.sort_values("created_date", ascending=False) if not bugs.empty else qa_df
    recent   = table_df.head(50)[cols].copy()

    header_map_qa = {"work_item_type": "Type", "assigned_to": "Owner", "iteration_path": "Iteration"}
    rows_qa = []
    for _, row in recent.iterrows():
        it = str(row.get("iteration_path", "—"))
        if pd.notna(row.get("iteration_path")) and "\\" in it:
            it = it.split("\\")[-1]
        cells_qa = []
        for c in recent.columns:
            v = row.get(c)
            if c == "title":
                cells_qa.append(html.Td(str(v)[:90] if pd.notna(v) else "—",
                    style={**_TD_QA, "maxWidth": "320px", "overflow": "hidden",
                           "textOverflow": "ellipsis", "whiteSpace": "nowrap"}))
            elif c == "priority":
                cells_qa.append(html.Td(_priority_pill_qa(v), style=_TD_QA))
            elif c == "state":
                cells_qa.append(html.Td(_state_pill_qa(v), style=_TD_QA))
            elif c == "work_item_type":
                cells_qa.append(html.Td(
                    html.Span(str(v) if pd.notna(v) else "—",
                              className="pill pill-active" if str(v).lower() == "task" else "pill pill-p1"),
                    style=_TD_QA))
            elif c == "iteration_path":
                cells_qa.append(html.Td(it, style={**_TD_QA, "color": "#8892a4", "fontSize": "11px"}))
            else:
                cells_qa.append(html.Td(str(v) if pd.notna(v) else "—", style={**_TD_QA, "color": "#8888aa"}))
        rows_qa.append(html.Tr(cells_qa))

    tbl = html.Div(
        html.Table([
            html.Thead(html.Tr([
                html.Th(header_map_qa.get(c, c.replace("_", " ").title()), style=_TH_QA)
                for c in recent.columns
            ])),
            html.Tbody(rows_qa),
        ], style={"width": "100%", "borderCollapse": "collapse"}),
        style={"overflowX": "auto"},
    )

    return (kpi_row, fig_tp, fig_disc, fig_sla, fig_age,
            fig_hm, fig_mtp, fig_wl, tbl)


# ── Report callback ───────────────────────────────────────────────────────────
@callback(
    Output("qa-report-modal", "is_open"),
    Output("qa-report-body",  "children"),
    Output("qa-report-ts",    "children"),
    Input("qa-report-btn",    "n_clicks"),
    prevent_initial_call=True,
)
def _open_qa_report(n):
    if not n:
        from dash import no_update
        return no_update, no_update, no_update
    df      = load_data()
    summary = summarize_qa(df)
    body    = format_report(summary)
    ts      = f"Generated {summary['as_of']}  •  {summary['total_bugs']} total bugs"
    return True, body, ts
