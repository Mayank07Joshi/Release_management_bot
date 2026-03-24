"""Release Outlook — per-release progress, health signal, blockers, and scope"""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback, dash_table
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from data.loader import load_data
from config.settings import ADO_BASE_URL

dash.register_page(__name__, path="/release-outlook", name="Release Outlook")

# ── Constants ─────────────────────────────────────────────────────────────────
CLOSED_STATES = {"Closed", "Not an issue", "Not Required", "Userstory Update"}

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

TYPE_COLORS = {
    "Bug":         "#c06060",
    "User Story":  "#63b3ed",
    "Enhancement": "#f6ad55",
    "Task":        "#68d391",
    "Feature":     "#b794f4",
}

_TIPS = {
    "progress": (
        "Release Progress",
        "% of items genuinely closed. Rejected items (Not an issue / Not Required) "
        "are excluded from this count — they appear in the Audit tab.",
    ),
    "state": (
        "Items by State",
        "Where open items currently sit in the workflow. "
        "A large Active bar = team is busy. On Hold = potential blockers.",
    ),
    "type": (
        "Item Type Mix",
        "Split of deliverables by type. Tasks are excluded by default — "
        "toggle them in the filter if you need the full breakdown.",
    ),
    "blockers": (
        "P1 / P2 Blockers",
        "Critical (P1) and High (P2) items still open. "
        "Every P1 must be closed before a GO decision.",
    ),
    "at_risk": (
        "Stale Open Items",
        "Open items with no activity in 7+ days. "
        "These risk slipping out of the release.",
    ),
    "assignee": (
        "Open Items by Owner",
        "How many open items each person currently owns for this release. "
        "Useful for spotting overloaded team members.",
    ),
    "rejected": (
        "Rejected / Out of Scope",
        "Items closed as 'Not an issue' or 'Not Required'. "
        "These were descoped or invalidated — they do not count toward closure %.",
    ),
    "estimation": (
        "Estimation Accuracy",
        "Original estimate vs actual completed work for closed items. "
        "Large gaps signal planning issues worth addressing next release.",
    ),
    "throughput": (
        "Closed by Owner",
        "How many items each person closed for this release. "
        "A rough signal of individual contribution to the delivery.",
    ),
    "cycle": (
        "Cycle Time",
        "Days from item creation to close (created_date → closed_date). "
        "Long tails indicate items that sat unresolved for too long.",
    ),
}


# ── Layout helpers ─────────────────────────────────────────────────────────────
def _kpi(label, value, cls="", subtitle=None, md=3):
    children = [
        html.Div(label, className="metric-label"),
        html.Div(value, className=f"metric-value {cls}"),
    ]
    if subtitle:
        children.append(html.Div(subtitle, className="kpi-subtitle"))
    return dbc.Col(html.Div(children, className="metric-card"), md=md)


def _info(tip_id):
    title, _ = _TIPS.get(tip_id, ("", ""))
    return html.Span(
        " ?",
        id=f"ro-tip-{tip_id}",
        style={"cursor": "pointer", "color": "#a0aec0", "fontSize": "11px",
               "fontWeight": "700", "marginLeft": "4px"},
    )


def _chart_card(title, tip_key, graph_id, insight_id=None):
    _, tip_text = _TIPS.get(tip_key, ("", ""))
    header = html.Div([
        html.Span(title, className="chart-title-text"),
        _info(tip_key),
        dbc.Tooltip(tip_text, target=f"ro-tip-{tip_key}", placement="right"),
    ], className="chart-section-header")
    body = [header]
    if insight_id:
        body.append(html.Div(id=insight_id, className="chart-insight"))
    body.append(dcc.Graph(id=graph_id, config={"responsive": True}))
    return html.Div(body, className="chart-card mb-4")


def _section_label(text):
    return html.Div(text, style={
        "fontSize": "11px", "fontWeight": "700", "textTransform": "uppercase",
        "letterSpacing": "0.8px", "color": "#a0aec0",
        "marginBottom": "12px", "marginTop": "4px",
    })


def _table_card(title, tip_key, body_id):
    _, tip_text = _TIPS.get(tip_key, ("", ""))
    return html.Div([
        html.Div([
            html.Span(title, style={"fontSize": "14px", "fontWeight": "700"}),
            _info(tip_key),
            dbc.Tooltip(tip_text, target=f"ro-tip-{tip_key}", placement="right"),
        ], className="chart-section-header"),
        html.Div(id=body_id),
    ], className="chart-card mb-4")


# ── Layout ────────────────────────────────────────────────────────────────────
def layout():
    df = load_data()
    releases = sorted(
        [r for r in df["release_date"].dropna().unique()
         if r not in ("Not Specified", "")],
        reverse=True,
    ) if "release_date" in df.columns else []
    teams = ["All"] + sorted(df["team"].dropna().unique().tolist()) if "team" in df.columns else ["All"]

    all_types     = sorted(df["work_item_type"].dropna().unique().tolist()) if "work_item_type" in df.columns else []
    default_types = [t for t in all_types if t not in ("Task",)]
    default_release = releases[0] if releases else None

    _fb = {
        "background": "#1c1c27", "borderRadius": "10px", "padding": "14px 18px",
        "border": "1px solid rgba(255,255,255,0.07)",
        "marginBottom": "20px",
    }

    filter_bar = html.Div([
        dbc.Row([
            dbc.Col([
                html.Div("Release", className="filter-label"),
                dcc.Dropdown(
                    id="ro-release",
                    options=[{"label": r, "value": r} for r in releases],
                    value=default_release, clearable=False,
                    style={"fontSize": "13px", "fontWeight": "600"},
                ),
            ], md=4),
            dbc.Col([
                html.Div("Team", className="filter-label"),
                dcc.Dropdown(
                    id="ro-team",
                    options=[{"label": t, "value": t} for t in teams],
                    value="All", clearable=False, style={"fontSize": "12px"},
                ),
            ], md=3),
            dbc.Col([
                html.Div("Item Type", className="filter-label"),
                dcc.Dropdown(
                    id="ro-type",
                    options=[{"label": t, "value": t} for t in all_types],
                    value=default_types, multi=True, placeholder="All types",
                    style={"fontSize": "12px"},
                ),
            ], md=5),
        ], className="g-2"),
    ], style=_fb)

    # ── Tab styles ────────────────────────────────────────────────────────────
    _tab_style = {
        "padding": "10px 24px", "fontWeight": "600", "fontSize": "13px",
        "color": "#718096", "borderTop": "none", "borderLeft": "none",
        "borderRight": "none", "borderBottom": "2px solid transparent",
        "background": "transparent",
    }
    _tab_selected_style = {
        **_tab_style,
        "color": "#e8e8f0", "borderBottom": "2px solid #8b7ee8",
    }

    live_tab = dcc.Tab(
        label="📡  Live View",
        value="live",
        style=_tab_style,
        selected_style=_tab_selected_style,
        children=html.Div([
            # ── Go / No-Go banner ────────────────────────────────────────────
            html.Div(id="ro-health-banner", className="mb-3"),

            # ── Progress bar ─────────────────────────────────────────────────
            html.Div(id="ro-progress-bar", className="mb-4"),

            # ── AT A GLANCE ──────────────────────────────────────────────────
            _section_label("At a Glance"),
            html.Div(id="ro-kpi-row", className="mb-4"),
            html.Hr(className="section-divider"),

            # ── DELIVERY HEALTH ──────────────────────────────────────────────
            _section_label("Delivery Health"),
            dbc.Row([
                dbc.Col(_chart_card("Items by State",  "state",    "ro-state-bar",
                                    insight_id="ro-insight-state"), md=7),
                dbc.Col(_chart_card("Item Type Mix",   "type",     "ro-type-donut"),  md=5),
            ], className="mb-2"),
            html.Hr(className="section-divider"),

            # ── WHO OWNS THE WORK ────────────────────────────────────────────
            _section_label("Who Owns the Work"),
            _chart_card("Open Items by Owner", "assignee", "ro-assignee-chart"),
            html.Hr(className="section-divider"),

            # ── BLOCKERS ─────────────────────────────────────────────────────
            _section_label("Blockers"),
            _table_card("🚨 P1 / P2 Blockers", "blockers", "ro-blockers-body"),
            html.Hr(className="section-divider"),

            # ── RISK WATCH ───────────────────────────────────────────────────
            _section_label("Risk Watch"),
            _table_card("🕰️ Stale Open Items (7+ days no activity)", "at_risk", "ro-atrisk-body"),
        ], style={"paddingTop": "20px"}),
    )

    audit_tab = dcc.Tab(
        label="🔍  Release Audit",
        value="audit",
        style=_tab_style,
        selected_style=_tab_selected_style,
        children=html.Div([
            # ── REJECTED / OUT OF SCOPE ──────────────────────────────────────
            _section_label("Rejected / Out of Scope"),
            _table_card("🚫 Not an Issue / Not Required", "rejected", "ro-rejected-body"),
            html.Hr(className="section-divider"),

            # ── ESTIMATION ACCURACY ──────────────────────────────────────────
            _section_label("Estimation Accuracy"),
            _chart_card("Original Estimate vs Completed Work", "estimation", "ro-audit-estimation"),
            html.Hr(className="section-divider"),

            # ── THROUGHPUT ───────────────────────────────────────────────────
            _section_label("Delivery Contribution"),
            _chart_card("Closed Items by Owner", "throughput", "ro-audit-throughput"),
            html.Hr(className="section-divider"),

            # ── CYCLE TIME ───────────────────────────────────────────────────
            _section_label("Cycle Time"),
            _chart_card("Days from Created → Closed", "cycle", "ro-audit-cycle",
                        insight_id="ro-audit-cycle-insight"),
        ], style={"paddingTop": "20px"}),
    )

    return html.Div([
        html.Div([
            html.H1("🚀 Release Outlook", className="page-title"),
            html.P("Per-release health signal, progress, blockers, and scope control.",
                   className="page-subtitle"),
        ], className="page-header"),

        filter_bar,

        dcc.Tabs(
            id="ro-tabs",
            value="live",
            children=[live_tab, audit_tab],
            style={"borderBottom": "1px solid #e8ecf0", "marginBottom": "24px"},
        ),
    ])


# ── Callback ──────────────────────────────────────────────────────────────────
@callback(
    # Live tab
    Output("ro-health-banner",       "children"),
    Output("ro-progress-bar",        "children"),
    Output("ro-kpi-row",             "children"),
    Output("ro-state-bar",           "figure"),
    Output("ro-type-donut",          "figure"),
    Output("ro-insight-state",       "children"),
    Output("ro-assignee-chart",      "figure"),
    Output("ro-blockers-body",       "children"),
    Output("ro-atrisk-body",         "children"),
    # Audit tab
    Output("ro-rejected-body",       "children"),
    Output("ro-audit-estimation",    "figure"),
    Output("ro-audit-throughput",    "figure"),
    Output("ro-audit-cycle",         "figure"),
    Output("ro-audit-cycle-insight", "children"),
    Input("ro-release", "value"),
    Input("ro-team",    "value"),
    Input("ro-type",    "value"),
)
def update_release_outlook(release, team, item_types):
    df    = load_data()
    today = pd.Timestamp.today().normalize()

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
        empty_fig(), empty_fig(), "",
        empty_fig(), html.Div(), html.Div(),
        html.Div(), empty_fig(), empty_fig(), empty_fig(), "",
    )

    if not release:
        banner = dbc.Alert("Select a release above to see the outlook.", color="info")
        return (banner,) + no_data[1:]

    # ── Filter ──────────────────────────────────────────────────────────────
    if "release_date" in df.columns:
        df = df[df["release_date"] == release]
    if team and team != "All" and "team" in df.columns:
        df = df[df["team"] == team]
    if item_types and "work_item_type" in df.columns:
        df = df[df["work_item_type"].isin(item_types)]

    if "assigned_to" in df.columns:
        df["assigned_to"] = df["assigned_to"].astype(str).str.split(" <").str[0]

    total = len(df)
    if total == 0:
        banner = dbc.Alert(f"No items found for release '{release}' with the current filters.",
                           color="warning")
        return (banner,) + no_data[1:]

    # ── Core derived frames ──────────────────────────────────────────────────
    REJECTED_STATES = {"Not an issue", "Not Required"}
    TRULY_CLOSED    = CLOSED_STATES - REJECTED_STATES

    if "state" in df.columns:
        is_rejected = df["state"].isin(REJECTED_STATES)
        is_closed   = df["state"].isin(TRULY_CLOSED)
    else:
        is_rejected = pd.Series(False, index=df.index)
        is_closed   = pd.Series(False, index=df.index)

    rejected_df = df[is_rejected]
    closed_df   = df[is_closed]
    open_df     = df[~is_closed & ~is_rejected]

    n_rejected  = len(rejected_df)
    n_closed    = len(closed_df)
    n_open      = len(open_df)
    closure_pct = n_closed / total * 100 if total > 0 else 0

    p1_open = int((open_df["priority"] == 1).sum()) if "priority" in open_df.columns else 0
    p2_open = int((open_df["priority"] == 2).sum()) if "priority" in open_df.columns else 0

    rem_hours = 0
    if "remaining_work" in open_df.columns:
        rem_hours = int(pd.to_numeric(open_df["remaining_work"], errors="coerce").fillna(0).sum())

    scope_added = 0
    if "created_date" in df.columns:
        cutoff = today - pd.Timedelta(days=30)
        scope_added = int((pd.to_datetime(df["created_date"], errors="coerce") >= cutoff).sum())

    # ════════════════════════════════════════════════════════════════════════
    # LIVE TAB
    # ════════════════════════════════════════════════════════════════════════

    # ── Health banner ────────────────────────────────────────────────────────
    if closure_pct >= 85 and p1_open == 0:
        h_color, h_icon, h_msg = "success", "✅", "GO — Release is on track"
    elif closure_pct >= 60 and p1_open <= 2:
        h_color, h_icon, h_msg = "warning", "⚠️", "AT RISK — Needs attention before release"
    else:
        h_color, h_icon, h_msg = "danger",  "🚫", "NO-GO — Release is not ready"

    h_sub = (f"{closure_pct:.0f}% closed  ·  {p1_open} P1 open  ·  "
             f"{p2_open} P2 open  ·  {scope_added} items added last 30 days")

    health_banner = dbc.Alert(
        dbc.Row([
            dbc.Col(html.Span(f"{h_icon} {h_msg}",
                              style={"fontSize": "16px", "fontWeight": "700"}), md=8),
            dbc.Col(html.Span(h_sub, style={"fontSize": "12px", "opacity": "0.85"}),
                    md=4, className="text-md-end"),
        ], align="center"),
        color=h_color, style={"padding": "14px 20px", "borderRadius": "10px"},
    )

    # ── Progress bar ─────────────────────────────────────────────────────────
    bar_color = "success" if closure_pct >= 85 else ("warning" if closure_pct >= 60 else "danger")
    progress_bar = html.Div([
        dbc.Row([
            dbc.Col(html.Div(
                f"Release Progress — {n_closed} of {total} items closed",
                style={"fontSize": "13px", "fontWeight": "600", "marginBottom": "6px"},
            )),
            dbc.Col(html.Div(
                f"{closure_pct:.1f}%",
                style={"fontSize": "13px", "fontWeight": "700", "textAlign": "right"},
            )),
        ]),
        dbc.Progress(
            value=closure_pct, color=bar_color,
            striped=(closure_pct < 85), animated=(closure_pct < 85),
            style={"height": "22px", "borderRadius": "8px"},
        ),
    ], className="chart-card")

    # ── KPI row ───────────────────────────────────────────────────────────────
    kpi_row = html.Div([
        dbc.Row([
            _kpi("Total Items",  str(total),      subtitle=f"In '{release}'"),
            _kpi("Closed",       str(n_closed),   cls="success", subtitle="Genuinely resolved"),
            _kpi("Closure %",    f"{closure_pct:.1f}%",
                 cls="success" if closure_pct >= 85 else ("warning" if closure_pct >= 60 else "danger"),
                 subtitle="Closed ÷ total (excl. rejected)"),
            _kpi("Open",         str(n_open),
                 cls="" if n_open == 0 else ("warning" if n_open <= 5 else "danger"),
                 subtitle="Still in progress"),
        ], className="g-3 mb-3"),
        dbc.Row([
            _kpi("P1 / P2 Open",  f"{p1_open} / {p2_open}",
                 cls="danger" if p1_open > 0 else ("warning" if p2_open > 0 else "success"),
                 subtitle="Critical blockers"),
            _kpi("Remaining Hrs", f"{rem_hours:,}h" if rem_hours else "—",
                 cls="warning" if rem_hours > 0 else "",
                 subtitle="Estimated hours left"),
            _kpi("Scope Added",   str(scope_added),
                 cls="" if scope_added == 0 else "warning",
                 subtitle="Added last 30 days"),
            _kpi("Rejected",      str(n_rejected),
                 cls="danger" if n_rejected > 0 else "",
                 subtitle="Not an issue / Not required"),
        ], className="g-3"),
    ])

    # ── State bar ─────────────────────────────────────────────────────────────
    if "state" in df.columns:
        df["state_label"] = df["state"].map(STATE_MAP).fillna(df["state"])
        open_states_df = df[~is_closed].copy()
        sc = open_states_df["state_label"].value_counts().reset_index()
        sc.columns = ["State", "Count"]
        sc["color"] = sc["State"].map(STATE_COLORS).fillna("#a0aec0")
        sc = sc.sort_values("Count", ascending=True)

        if not sc.empty:
            top_state = sc.iloc[-1]["State"]
            insight_state = (
                f"{top_state} accounts for {sc.iloc[-1]['Count']} open items "
                f"({sc.iloc[-1]['Count'] / n_open * 100:.0f}% of all open work)."
                if n_open > 0 else ""
            )
            fig_state = go.Figure(go.Bar(
                x=sc["Count"], y=sc["State"], orientation="h",
                marker_color=sc["color"], text=sc["Count"],
                textposition="outside", textfont=dict(size=11),
                hovertemplate="%{y}: %{x} items<extra></extra>",
            ))
            fig_state.update_layout(
                height=max(len(sc) * 40 + 80, 240),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=40, l=185, r=90),
                xaxis=dict(gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12)),
                yaxis=dict(tickfont=dict(size=12)),
            )
        else:
            fig_state     = empty_fig("No open items")
            insight_state = ""
    else:
        fig_state     = empty_fig()
        insight_state = ""

    # ── Type donut ────────────────────────────────────────────────────────────
    if "work_item_type" in df.columns:
        df["type_clean"] = df["work_item_type"].replace({"Bug_UI": "Bug", "Bug_Text": "Bug"})
        tc = df["type_clean"].value_counts().reset_index()
        tc.columns = ["Type", "Count"]
        fig_type = px.pie(
            tc, names="Type", values="Count", hole=0.55,
            color="Type", color_discrete_map=TYPE_COLORS,
        )
        fig_type.update_traces(textposition="outside", textinfo="label+percent",
                               textfont_size=11)
        fig_type.update_layout(
            height=320, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=20, l=20, r=20), showlegend=False,
        )
    else:
        fig_type = empty_fig()

    # ── Open items by owner ───────────────────────────────────────────────────
    if "assigned_to" in open_df.columns and not open_df.empty:
        owner_counts = (
            open_df["assigned_to"]
            .replace("Unassigned", "⚠️ Unassigned")
            .value_counts().reset_index()
        )
        owner_counts.columns = ["Owner", "Open Items"]
        owner_counts = owner_counts.sort_values("Open Items", ascending=True).tail(20)
        owner_counts["color"] = owner_counts["Owner"].apply(
            lambda x: "#c06060" if "Unassigned" in x else "#63b3ed"
        )
        fig_assignee = go.Figure(go.Bar(
            x=owner_counts["Open Items"], y=owner_counts["Owner"], orientation="h",
            marker_color=owner_counts["color"], text=owner_counts["Open Items"],
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{y}: %{x} open items<extra></extra>",
        ))
        fig_assignee.update_layout(
            height=max(len(owner_counts) * 42 + 80, 260),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=40, l=185, r=90),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12), title="Open Items"),
            yaxis=dict(tickfont=dict(size=12)),
        )
    else:
        fig_assignee = empty_fig("No open items")

    # ── P1/P2 Blockers ────────────────────────────────────────────────────────
    if "priority" in df.columns and "state" in df.columns:
        blockers = open_df[open_df["priority"].isin([1, 2])].sort_values("priority").copy()
        if not blockers.empty:
            cols = [c for c in ["work_item_id", "title", "work_item_type", "priority",
                                 "state", "assigned_to", "function", "changed_date"]
                    if c in blockers.columns]
            tbl = blockers[cols].copy()
            if "changed_date" in tbl.columns:
                tbl["changed_date"] = pd.to_datetime(
                    tbl["changed_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            if "work_item_id" in tbl.columns:
                tbl["work_item_id"] = tbl["work_item_id"].apply(
                    lambda x: f"[{x}]({ADO_BASE_URL}{x})" if pd.notna(x) else x
                )
            col_defs = [
                {"name": "ID", "id": "work_item_id", "presentation": "markdown"}
                if c == "work_item_id"
                else {"name": c.replace("_", " ").title(), "id": c}
                for c in cols
            ]
            blockers_body = html.Div([
                html.Div(
                    f"{len(blockers)} item(s) blocking release — all must be resolved before GO.",
                    className="chart-insight", style={"marginBottom": "10px"},
                ),
                dash_table.DataTable(
                    data=tbl.to_dict("records"), columns=col_defs,
                    style_table={"overflowX": "auto"},
                    style_cell={"fontSize": "12px", "padding": "8px 12px",
                                "textAlign": "left", "maxWidth": "260px",
                                "overflow": "hidden", "textOverflow": "ellipsis"},
                    style_header={"fontWeight": "600", "background": "#fff5f5",
                                  "fontSize": "11px", "color": "#c53030"},
                    style_data_conditional=[
                        {"if": {"filter_query": "{priority} = 1"},
                         "background": "#fff5f5", "color": "#c53030", "fontWeight": "600"},
                        {"if": {"filter_query": "{priority} = 2"},
                         "background": "#fffaf0", "color": "#c05621"},
                    ],
                    sort_action="native", page_size=10,
                    tooltip_data=[
                        {c: {"value": str(row.get(c, "")), "type": "markdown"} for c in cols}
                        for row in tbl.to_dict("records")
                    ],
                    tooltip_delay=0, tooltip_duration=None,
                ),
            ])
        else:
            blockers_body = dbc.Alert(
                "✅ No P1/P2 blockers open for this release.",
                color="success", style={"padding": "10px 16px", "fontSize": "13px"},
            )
    else:
        blockers_body = html.Div("Priority or State data not available.",
                                 style={"color": "#a0aec0"})

    # ── Stale / at-risk items ─────────────────────────────────────────────────
    if "changed_date" in df.columns and "state" in df.columns:
        stale_cut = today - pd.Timedelta(days=7)
        at_risk   = open_df.copy()
        at_risk["changed_dt"] = pd.to_datetime(at_risk["changed_date"], errors="coerce")
        at_risk = at_risk[at_risk["changed_dt"] < stale_cut].copy()
        if not at_risk.empty:
            at_risk["days_stale"] = (today - at_risk["changed_dt"]).dt.days.astype(int)
            at_risk = at_risk.sort_values("days_stale", ascending=False)
            cols = [c for c in ["work_item_id", "title", "work_item_type", "priority",
                                 "state", "assigned_to", "days_stale", "function"]
                    if c in at_risk.columns]
            tbl = at_risk[cols].copy()
            if "work_item_id" in tbl.columns:
                tbl["work_item_id"] = tbl["work_item_id"].apply(
                    lambda x: f"[{x}]({ADO_BASE_URL}{x})" if pd.notna(x) else x
                )
            col_defs = [
                {"name": "ID", "id": "work_item_id", "presentation": "markdown"}
                if c == "work_item_id"
                else {"name": c.replace("_", " ").title(), "id": c}
                for c in cols
            ]
            atrisk_body = html.Div([
                html.Div(
                    f"{len(at_risk)} open item(s) with no update in 7+ days — follow up needed.",
                    className="chart-insight", style={"marginBottom": "10px"},
                ),
                dash_table.DataTable(
                    data=tbl.to_dict("records"), columns=col_defs,
                    style_table={"overflowX": "auto"},
                    style_cell={"fontSize": "12px", "padding": "8px 12px",
                                "textAlign": "left", "maxWidth": "260px",
                                "overflow": "hidden", "textOverflow": "ellipsis"},
                    style_header={"fontWeight": "600", "background": "#f7fafc", "fontSize": "11px"},
                    style_data_conditional=[
                        {"if": {"row_index": "odd"},           "backgroundColor": "#f7fafc"},
                        {"if": {"filter_query": "{days_stale} >= 30"},
                         "background": "#fff5f5", "color": "#c53030", "fontWeight": "600"},
                        {"if": {"filter_query": "{days_stale} >= 14"},
                         "background": "#fffaf0", "color": "#c05621"},
                    ],
                    sort_action="native", page_size=10,
                ),
            ])
        else:
            atrisk_body = dbc.Alert(
                "✅ No stale open items — everything is actively progressing.",
                color="success", style={"padding": "10px 16px", "fontSize": "13px"},
            )
    else:
        atrisk_body = html.Div("Date data not available.", style={"color": "#a0aec0"})

    # ════════════════════════════════════════════════════════════════════════
    # AUDIT TAB
    # ════════════════════════════════════════════════════════════════════════

    # ── Rejected items ────────────────────────────────────────────────────────
    if not rejected_df.empty:
        tbl = rejected_df.copy()
        if "created_date" in tbl.columns and "changed_date" in tbl.columns:
            created_dt  = pd.to_datetime(tbl["created_date"],  errors="coerce")
            rejected_dt = pd.to_datetime(tbl["changed_date"],  errors="coerce")
            tbl["days_in_scope"] = (rejected_dt - created_dt).dt.days.fillna(0).astype(int)
        else:
            tbl["days_in_scope"] = 0

        deliberated = int((tbl["days_in_scope"] > 0).sum())

        for col in ("created_date", "changed_date"):
            if col in tbl.columns:
                tbl[col] = pd.to_datetime(tbl[col], errors="coerce").dt.strftime("%Y-%m-%d")

        if "work_item_id" in tbl.columns:
            tbl["work_item_id"] = tbl["work_item_id"].apply(
                lambda x: f"[{x}]({ADO_BASE_URL}{x})" if pd.notna(x) else x
            )

        cols = [c for c in ["work_item_id", "title", "work_item_type", "priority",
                             "state", "assigned_to", "created_date", "changed_date",
                             "days_in_scope", "function"]
                if c in tbl.columns]
        tbl = tbl[cols]

        col_label = {
            "work_item_id":  "ID",
            "created_date":  "Created",
            "changed_date":  "Rejected On",
            "days_in_scope": "Days in Scope",
        }
        col_defs = [
            {"name": col_label.get(c, c.replace("_", " ").title()), "id": c,
             **({"presentation": "markdown"} if c == "work_item_id" else {})}
            for c in cols
        ]

        insight_text = (
            f"{n_rejected} item(s) marked as out of scope or invalid — excluded from closure %."
        )
        if deliberated > 0:
            insight_text += (
                f"  ⚠️ {deliberated} had active deliberation time before being descoped."
            )

        rejected_body = html.Div([
            html.Div(insight_text, className="chart-insight", style={"marginBottom": "10px"}),
            dash_table.DataTable(
                data=tbl.to_dict("records"), columns=col_defs,
                style_table={"overflowX": "auto"},
                style_cell={"fontSize": "12px", "padding": "8px 12px",
                            "textAlign": "left", "maxWidth": "260px",
                            "overflow": "hidden", "textOverflow": "ellipsis"},
                style_header={"fontWeight": "600", "background": "#f7fafc", "fontSize": "11px"},
                style_data_conditional=[
                    {"if": {"row_index": "odd"}, "backgroundColor": "rgba(255,255,255,0.03)"},
                    {"if": {"filter_query": "{days_in_scope} >= 7"},
                     "background": "#fff5f5", "color": "#c53030", "fontWeight": "600"},
                    {"if": {"filter_query": "{days_in_scope} >= 1 && {days_in_scope} < 7"},
                     "background": "#fffaf0", "color": "#c05621"},
                    {"if": {"filter_query": "{days_in_scope} = 0"},
                     "color": "#718096", "fontStyle": "italic"},
                ],
                sort_action="native", page_size=10,
                tooltip_data=[
                    {c: {"value": str(row.get(c, "")), "type": "markdown"} for c in cols}
                    for row in tbl.to_dict("records")
                ],
                tooltip_delay=0, tooltip_duration=None,
            ),
        ])
    else:
        rejected_body = dbc.Alert(
            "✅ No rejected or out-of-scope items for this release.",
            color="success", style={"padding": "10px 16px", "fontSize": "13px"},
        )

    # ── Estimation accuracy ───────────────────────────────────────────────────
    est_cols = {"original_estimate", "completed_work", "title"}
    if est_cols.issubset(df.columns) and not closed_df.empty:
        est = closed_df[["title", "work_item_id", "original_estimate",
                          "completed_work", "assigned_to"]].copy()
        est["original_estimate"] = pd.to_numeric(est["original_estimate"], errors="coerce").fillna(0)
        est["completed_work"]    = pd.to_numeric(est["completed_work"],    errors="coerce").fillna(0)
        # Only rows where at least one value is non-zero
        est = est[(est["original_estimate"] > 0) | (est["completed_work"] > 0)].copy()

        if not est.empty:
            est["label"] = est["work_item_id"].astype(str) + " – " + est["title"].str[:40]
            est = est.sort_values("original_estimate", ascending=True).tail(25)

            fig_est = go.Figure()
            fig_est.add_trace(go.Bar(
                name="Original Estimate",
                y=est["label"], x=est["original_estimate"],
                orientation="h", marker_color="#63b3ed",
                hovertemplate="%{y}<br>Estimate: %{x}h<extra></extra>",
            ))
            fig_est.add_trace(go.Bar(
                name="Completed Work",
                y=est["label"], x=est["completed_work"],
                orientation="h", marker_color="#68d391",
                hovertemplate="%{y}<br>Actual: %{x}h<extra></extra>",
            ))
            fig_est.update_layout(
                barmode="overlay", height=max(len(est) * 36 + 100, 300),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=40, l=300, r=60),
                xaxis=dict(gridcolor="rgba(255,255,255,0.06)", title="Hours", tickfont=dict(size=11)),
                yaxis=dict(tickfont=dict(size=11)),
                legend=dict(orientation="h", y=1.04, x=0),
            )
        else:
            fig_est = empty_fig("No estimation data for closed items")
    else:
        fig_est = empty_fig("No closed items or estimation data available")

    # ── Throughput by owner ───────────────────────────────────────────────────
    if "assigned_to" in closed_df.columns and not closed_df.empty:
        tp = (
            closed_df["assigned_to"]
            .replace("Unassigned", "⚠️ Unassigned")
            .value_counts().reset_index()
        )
        tp.columns = ["Owner", "Closed"]
        tp = tp.sort_values("Closed", ascending=True)
        fig_throughput = go.Figure(go.Bar(
            x=tp["Closed"], y=tp["Owner"], orientation="h",
            marker_color="#68d391", text=tp["Closed"],
            textposition="outside", textfont=dict(size=11),
            hovertemplate="%{y}: %{x} items closed<extra></extra>",
        ))
        fig_throughput.update_layout(
            height=max(len(tp) * 42 + 80, 260),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=20, b=40, l=185, r=90),
            xaxis=dict(gridcolor="rgba(255,255,255,0.06)", title="Items Closed", tickfont=dict(size=12)),
            yaxis=dict(tickfont=dict(size=12)),
        )
    else:
        fig_throughput = empty_fig("No closed items")

    # ── Cycle time ────────────────────────────────────────────────────────────
    cycle_insight = ""
    if "created_date" in closed_df.columns and "closed_date" in closed_df.columns and not closed_df.empty:
        cyc = closed_df.copy()
        cyc["created_dt"] = pd.to_datetime(cyc["created_date"], errors="coerce")
        cyc["closed_dt"]  = pd.to_datetime(cyc["closed_date"],  errors="coerce")
        cyc["cycle_days"] = (cyc["closed_dt"] - cyc["created_dt"]).dt.days
        cyc = cyc[cyc["cycle_days"].notna() & (cyc["cycle_days"] >= 0)]

        if not cyc.empty:
            med = cyc["cycle_days"].median()
            p90 = cyc["cycle_days"].quantile(0.9)
            cycle_insight = (
                f"Median cycle time: {med:.0f} days  ·  "
                f"90th percentile: {p90:.0f} days  ·  "
                f"{len(cyc)} closed items measured"
            )
            fig_cycle = go.Figure(go.Histogram(
                x=cyc["cycle_days"], nbinsx=20,
                marker_color="#b794f4", marker_line_color="white", marker_line_width=1,
                hovertemplate="~%{x} days: %{y} items<extra></extra>",
            ))
            fig_cycle.add_vline(
                x=med, line_dash="dash", line_color="#c05050",
                annotation_text=f"Median {med:.0f}d",
                annotation_position="top right",
                annotation_font=dict(size=11, color="#c05050"),
            )
            fig_cycle.update_layout(
                height=300, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=40, l=60, r=40),
                xaxis=dict(title="Days (Created → Closed)", gridcolor="rgba(255,255,255,0.06)",
                           tickfont=dict(size=12)),
                yaxis=dict(title="Items", gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=12)),
            )
        else:
            fig_cycle    = empty_fig("No cycle time data available")
    else:
        fig_cycle    = empty_fig("Created/closed date data not available")

    return (
        # Live tab
        health_banner,
        progress_bar,
        kpi_row,
        fig_state,
        fig_type,
        insight_state,
        fig_assignee,
        blockers_body,
        atrisk_body,
        # Audit tab
        rejected_body,
        fig_est,
        fig_throughput,
        fig_cycle,
        cycle_insight,
    )
