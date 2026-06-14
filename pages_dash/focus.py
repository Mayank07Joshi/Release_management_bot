"""VSTS Focus Area & Sprint Activity"""

import dash
from dash import dcc, html, Input, Output, State, callback, dash_table, ctx, ALL, no_update
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
from calendar import monthrange

from data.loader import load_data, engine
from sqlalchemy import text

# Page no longer registered standalone — content embedded in Summary page via focus_tab_content()

# ── Palette ───────────────────────────────────────────────────────────────────
BG   = "var(--bg-base)"
CARD = "var(--bg-elevated)"
BD   = "var(--border)"
ACC  = "var(--purple)"
G    = "var(--green)"
GOLD = "var(--gold)"
RED  = "var(--red)"
ORG  = "var(--amber)"
MT   = "var(--text-secondary)"
TXT  = "var(--text-primary)"
BLU  = "var(--blue)"

ISSUE_TYPES = {"Bug", "Bug_UI", "Bug_Text"}
ENH_TYPES   = {"Enhancement", "User Story"}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_sprint_path() -> str | None:
    today      = date.today()
    month_name = today.strftime("%B")   # "April"  — matches "04-April"
    year       = today.year             # 2026
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT iteration_path, COUNT(*) AS cnt FROM work_items_main "
                    "WHERE iteration_path ILIKE :p "
                    "GROUP BY iteration_path ORDER BY cnt DESC LIMIT 1"
                ),
                {"p": f"%{year}%{month_name}%"},
            ).fetchall()
        if rows:
            return rows[0].iteration_path
    except Exception:
        pass
    return None


def _load_sprint_history(sprint_path: str) -> dict[int, datetime | None]:
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT work_item_id, added_to_iteration_at "
                    "FROM p_sprint_item_history WHERE iteration_path = :p"
                ),
                {"p": sprint_path},
            ).fetchall()
        return {r.work_item_id: r.added_to_iteration_at for r in rows}
    except Exception:
        return {}


# ── Shared UI components ──────────────────────────────────────────────────────

def _kpi_card(number, label_main, label_sub, color):
    return html.Div([
        html.Div(str(number), style={
            "fontSize": "38px", "fontWeight": "700", "color": color,
            "lineHeight": "1.1", "marginBottom": "8px",
        }),
        html.Div(label_main, style={
            "fontSize": "10px", "fontWeight": "700", "color": MT,
            "letterSpacing": "0.08em", "textTransform": "uppercase",
        }),
        html.Div(label_sub, style={"fontSize": "11px", "color": MT, "marginTop": "2px"}),
    ], style={
        "background": CARD, "border": f"1px solid {BD}",
        "borderRadius": "10px", "padding": "20px 24px",
        "flex": "1", "minWidth": "0",
    })


def _bar_row(label, segments, show_pct=True, margin_bottom="18px"):
    """
    Horizontal stacked bar row.
    segments: list of (count, color, name)
    """
    total = sum(c for c, _, _ in segments)
    if total == 0:
        return html.Div()

    bar_segs = [
        html.Div(style={
            "flex": str(c),
            "height": "10px",
            "background": col,
            "borderRadius": "3px",
        })
        for c, col, _ in segments if c > 0
    ]

    legend_items = [
        html.Span([
            html.Span("■ ", style={"color": col, "fontSize": "14px"}),
            html.Span(
                f"{name}: {c:,} ({round(c / total * 100)}%)" if show_pct
                else f"{name}: {c:,}",
                style={"color": MT, "fontSize": "11px"},
            ),
        ], style={"marginRight": "16px", "whiteSpace": "nowrap"})
        for c, col, name in segments if c > 0
    ]

    return html.Div([
        html.Div([
            html.Span(label, style={
                "fontSize": "10px", "fontWeight": "700", "color": MT,
                "letterSpacing": "0.07em", "textTransform": "uppercase",
            }),
            html.Span(f"{total:,} items", style={"fontSize": "11px", "color": MT}),
        ], style={"display": "flex", "justifyContent": "space-between", "marginBottom": "6px"}),
        html.Div(bar_segs, style={"display": "flex", "gap": "2px", "width": "100%"}),
        html.Div(legend_items, style={"display": "flex", "flexWrap": "wrap", "marginTop": "7px"}),
    ], style={"marginBottom": margin_bottom})


def _callout(title, subtitle, number, bg_color, border_color, num_color, sub_color):
    return html.Div([
        html.Div([
            html.Div(title, style={
                "fontSize": "13px", "fontWeight": "600", "color": TXT, "marginBottom": "5px",
            }),
            html.Div(subtitle, style={"fontSize": "12px", "color": sub_color}),
        ]),
        html.Div(str(number), style={
            "fontSize": "34px", "fontWeight": "700", "color": num_color,
            "lineHeight": "1", "flexShrink": "0",
        }),
    ], style={
        "display": "flex", "justifyContent": "space-between", "alignItems": "center",
        "background": bg_color, "border": f"1px solid {border_color}",
        "borderRadius": "8px", "padding": "14px 18px", "marginTop": "8px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────

_ALL_STATES = [
    "New", "Request Estimate", "Estimated", "Clarification",
    "Active", "Dev InProgress", "Dev Review", "Dev Complete",
    "Tester Assigned", "Testing", "Watch List",
    "On Hold", "Waiting on Customer", "Reopened",
    "Resolved", "Closed", "Not an issue", "Not Required",
    "Userstory Update", "No Customer Response",
]

_STATE_OPTIONS = [{"label": s, "value": s} for s in _ALL_STATES]

_DEFAULT_STATES = ["Active", "Clarification", "Estimated", "New", "Reopened", "Request Estimate"]


def focus_tab_content():
    """Returns the VSTS Focus Area content for embedding in the Summary page."""
    return html.Div([
        dcc.Store(id="focus-type",         data="All"),
        dcc.Store(id="focus-tab",          data="summary"),
        dcc.Store(id="focus-state-filter", data=_DEFAULT_STATES),
        dcc.Store(id="adl-horizon",        data="365d"),
        dcc.Store(id="adl-source",         data="All"),
        dcc.Store(id="adl-type",           data="All"),
        dcc.Store(id="adl-team",           data="All"),
        dcc.Store(id="adl-selected-month", data=None),
        dcc.Store(id="adl-month-running",  data={}),

        # ── Month drill-down backdrop ──────────────────────────────────────────
        html.Div(id="adl-backdrop", n_clicks=0, style={
            "display": "none",
            "position": "fixed", "top": "0", "left": "0",
            "width": "100vw", "height": "100vh",
            "background": "rgba(0,0,0,0.55)",
            "zIndex": "1000",
        }),

        # ── Month drill-down side panel ────────────────────────────────────────
        html.Div([
            html.Button("×", id="adl-panel-close-btn", n_clicks=0, style={
                "position": "absolute", "top": "16px", "right": "16px",
                "background": "rgba(255,255,255,0.06)",
                "border": "1px solid rgba(255,255,255,0.12)",
                "color": "#94a3b8", "fontSize": "18px", "lineHeight": "1",
                "width": "32px", "height": "32px", "borderRadius": "6px",
                "cursor": "pointer", "display": "flex",
                "alignItems": "center", "justifyContent": "center",
                "zIndex": "2",
            }),
            html.Div(id="adl-panel-content"),
        ], id="adl-panel-wrapper", style={
            "position": "fixed", "top": "0", "right": "0",
            "width": "420px", "height": "100vh",
            "background": "#0d0d1e",
            "borderLeft": "1px solid rgba(255,255,255,0.09)",
            "overflowY": "auto", "overflowX": "hidden",
            "zIndex": "1001",
            "transform": "translateX(100%)",
            "transition": "transform 0.26s cubic-bezier(0.4,0,0.2,1)",
            "boxShadow": "-12px 0 40px rgba(0,0,0,0.6)",
        }),

        # ── Breadcrumb ────────────────────────────────────────────────────────
        html.Div("VSTS DATA · FOCUS AREA & SPRINT ACTIVITY", style={
            "fontSize": "10px", "fontWeight": "700", "color": MT,
            "letterSpacing": "0.12em", "marginBottom": "6px",
        }),

        # ── Title row ─────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("VSTS Focus Area & Sprint Activity", style={
                    "fontSize": "24px", "fontWeight": "700", "color": TXT,
                }),
                html.Div(id="focus-subtitle", style={
                    "fontSize": "13px", "color": MT, "marginTop": "4px",
                }),
            ]),
        ], style={"marginBottom": "24px"}),

        # ── Sticky filter bar: STATE ──────────────────────────────────────────
        html.Div([
            html.Div([
                html.Span("STATE", style={
                    "fontSize": "9px", "fontWeight": "700", "color": MT,
                    "letterSpacing": "0.06em", "textTransform": "uppercase",
                    "whiteSpace": "nowrap", "width": "52px", "flexShrink": "0",
                }),
                dcc.Dropdown(
                    id="focus-state-dropdown",
                    options=_STATE_OPTIONS,
                    value=_DEFAULT_STATES,
                    multi=True,
                    placeholder="All states — click to filter…",
                    clearable=True,
                    style={"flex": "1", "minWidth": "0"},
                    className="focus-state-dropdown",
                ),
                html.Div(id="focus-last-refreshed", style={
                    "fontSize": "11px", "color": MT,
                    "whiteSpace": "nowrap", "marginLeft": "16px", "flexShrink": "0",
                }),
            ], style={"display": "flex", "alignItems": "center"}),
        ], style={
            "position": "sticky", "top": "58px", "zIndex": "20",
            "background": BG,
            "paddingTop": "8px", "paddingBottom": "10px",
            "marginBottom": "10px",
        }),

        # ── Tab strip ─────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("Data Load Summary", id="focus-tab-summary-btn", n_clicks=0,
                         className="focus-tab-btn focus-tab-active"),
                html.Div("Addition & Deletion", id="focus-tab-sprint-btn", n_clicks=0,
                         className="focus-tab-btn"),
            ], style={"display": "flex"}),
            html.Div(id="focus-tab-meta", style={"fontSize": "12px", "color": MT}),
        ], style={
            "display": "flex", "justifyContent": "space-between", "alignItems": "flex-end",
            "borderBottom": f"1px solid {BD}", "marginBottom": "24px",
        }),

        # ── Content ───────────────────────────────────────────────────────────
        dcc.Loading(
            id="loading-focus-content",
            type="circle",
            color="#818cf8",
            style={"minHeight": "200px"},
            children=html.Div(id="focus-content"),
        ),
    ], style={"padding": "28px 32px"})


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("focus-tab",             "data"),
    Output("focus-tab-summary-btn", "className"),
    Output("focus-tab-sprint-btn",  "className"),
    Input("focus-tab-summary-btn",  "n_clicks"),
    Input("focus-tab-sprint-btn",   "n_clicks"),
    prevent_initial_call=True,
)
def _select_tab(n1, n2):
    active  = "focus-tab-btn focus-tab-active"
    default = "focus-tab-btn"
    if ctx.triggered_id == "focus-tab-sprint-btn":
        return "sprint", default, active
    return "summary", active, default


@callback(Output("adl-horizon", "data"),
          Input({"type": "adl-horizon-chip", "val": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _adl_horizon(n_clicks):
    if not any(n_clicks):
        raise PreventUpdate
    return ctx.triggered_id["val"]


@callback(Output("adl-source", "data"),
          Input({"type": "adl-source-chip", "val": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _adl_source(n_clicks):
    if not any(n_clicks):
        raise PreventUpdate
    return ctx.triggered_id["val"]


@callback(Output("adl-type", "data"),
          Input({"type": "adl-type-chip", "val": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _adl_type_cb(n_clicks):
    if not any(n_clicks):
        raise PreventUpdate
    return ctx.triggered_id["val"]


@callback(Output("adl-team", "data"),
          Input({"type": "adl-team-chip", "val": ALL}, "n_clicks"),
          prevent_initial_call=True)
def _adl_team(n_clicks):
    if not any(n_clicks):
        raise PreventUpdate
    return ctx.triggered_id["val"]


@callback(
    Output("focus-state-filter", "data"),
    Input("focus-state-dropdown", "value"),
)
def _sync_state_filter(value):
    return value or []


@callback(
    Output("focus-content",        "children"),
    Output("focus-subtitle",       "children"),
    Output("focus-tab-meta",       "children"),
    Output("focus-last-refreshed", "children"),
    Output("adl-month-running",    "data"),
    Input("focus-type",            "data"),
    Input("focus-tab",             "data"),
    Input("focus-state-filter",    "data"),
    Input("adl-horizon",           "data"),
    Input("adl-source",            "data"),
    Input("adl-type",              "data"),
    Input("adl-team",              "data"),
)
def _render(type_filter, tab, state_filter, adl_horizon, adl_source, adl_type, adl_team):
    # Lightweight query — only the 7 columns needed for summary stats and sprint count
    try:
        with engine.connect() as _conn:
            df_raw = pd.read_sql(text("""
                SELECT work_item_type, state, priority,
                       COALESCE(original_estimate, 0) AS original_estimate,
                       type, iteration_path, created_date
                FROM work_items_main
                WHERE created_date >= '2025-01-01'
                   OR closed_date  >= '2025-01-01'
                   OR changed_date >= '2025-01-01'
                   OR (created_date < '2025-01-01'
                       AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
            """), _conn)
    except Exception:
        df_raw = pd.DataFrame(columns=[
            "work_item_type", "state", "priority",
            "original_estimate", "type", "iteration_path", "created_date",
        ])
    df_raw["priority"] = pd.to_numeric(df_raw["priority"], errors="coerce").fillna(4).astype(int)
    df_raw["original_estimate"] = pd.to_numeric(df_raw["original_estimate"], errors="coerce").fillna(0)

    # State filter applies to summary analysis only
    df = df_raw[df_raw["state"].isin(state_filter)] if state_filter else df_raw

    df_issues = df[df["work_item_type"].isin(ISSUE_TYPES)]
    df_issues_scope = df_issues[
        pd.to_datetime(df_issues["created_date"], errors="coerce", utc=True) >= pd.Timestamp("2024-01-01", tz="UTC")
    ]
    df_enh = df[df["work_item_type"].isin(ENH_TYPES)]

    total_scope = len(df)
    state_label = (
        f" · States: {', '.join(state_filter)}" if state_filter else ""
    )
    subtitle = (
        f"{total_scope:,} items in scope · "
        f"Issues: Jan 2024+ · Enhancements: Inception+{state_label}"
    )
    tab_meta = f"{total_scope:,} items · refreshed {date.today().strftime('%d %b %Y')}"

    try:
        from sync.ado_sync import get_last_sync_result
        res = get_last_sync_result()
        ts  = res.get("timestamp", "")
        if ts:
            dt = datetime.fromisoformat(ts)
            refreshed = f"Last refreshed: {dt.strftime('%d %b %Y, %H:%M')}"
        else:
            refreshed = "Last refreshed: —"
    except Exception:
        refreshed = ""

    if tab == "sprint":
        try:
            content, running_dict = _render_sprint_adl(adl_horizon, adl_source, adl_type, adl_team)
        except Exception as _e:
            import traceback
            content = html.Div([
                html.Div("Sprint Activity failed to load", style={
                    "color": RED, "fontWeight": "700", "marginBottom": "8px",
                }),
                html.Pre(traceback.format_exc(), style={
                    "color": MT, "fontSize": "11px", "whiteSpace": "pre-wrap",
                    "background": CARD, "padding": "12px", "borderRadius": "8px",
                }),
            ], style={"padding": "20px"})
            running_dict = {}
        return content, subtitle, tab_meta, refreshed, running_dict
    else:
        content = _render_summary(df, df_issues_scope, df_enh, type_filter)

    return content, subtitle, tab_meta, refreshed, no_update


# ── Data Load Summary ─────────────────────────────────────────────────────────

def _render_summary(df, df_issues_scope, df_enh, type_filter):
    # ── KPI row ───────────────────────────────────────────────────────────────
    if type_filter == "Issues":
        df_main = df[df["work_item_type"].isin(ISSUE_TYPES)]
    elif type_filter == "Enhancements":
        df_main = df_enh
    else:
        df_main = df

    unest = int((df_main["original_estimate"].fillna(0) == 0).sum())

    _n_iss_all = len(df[df["work_item_type"].isin(ISSUE_TYPES)])
    _n_tasks   = len(df[df["work_item_type"] == "Task"])
    _n_other   = len(df) - len(df_enh) - _n_iss_all - _n_tasks
    _breakdown_rows = [(len(df_enh), "Enhancements", BLU), (_n_iss_all, "Issues", G)]
    if _n_other > 0:
        _breakdown_rows.append((_n_other, "Other", "#6b7280"))

    breakdown_card = html.Div([
        html.Div(f"{len(df):,}", style={
            "fontSize": "38px", "fontWeight": "700", "color": GOLD,
            "lineHeight": "1.1", "marginBottom": "6px",
        }),
        html.Div("ALL WORK ITEMS", style={
            "fontSize": "10px", "fontWeight": "700", "color": MT,
            "letterSpacing": "0.08em", "textTransform": "uppercase",
            "marginBottom": "10px",
        }),
        *[
            html.Div([
                html.Span(f"{cnt:,}", style={
                    "fontWeight": "700", "fontSize": "13px", "color": clr,
                    "width": "44px", "display": "inline-block",
                }),
                html.Span(lbl, style={"fontSize": "11px", "color": MT}),
            ], style={"marginBottom": "3px"})
            for cnt, lbl, clr in _breakdown_rows
        ],
    ], style={
        "background": CARD, "border": f"1px solid {BD}",
        "borderRadius": "10px", "padding": "20px 24px",
        "flex": "1", "minWidth": "0",
    })

    kpis = html.Div([
        breakdown_card,
        _kpi_card(f"{len(df_issues_scope):,}", "Issues in Scope",       "Jan 2024 – Present",  G),
        _kpi_card(f"{len(df_enh):,}",          "Enhancements in Scope", "Inception – Present",  BLU),
        _kpi_card(f"{_n_tasks:,}",             "Tasks",                 "Child work items",     ACC),
        _kpi_card(f"{unest:,}",                "Unestimated Items",     "Needs attention",      RED),
    ], style={"display": "flex", "gap": "16px", "marginBottom": "24px"})

    # ── Issues panel ──────────────────────────────────────────────────────────
    issues_panel = None
    if type_filter in ("All", "Issues"):
        dfi = df_issues_scope
        n_i = len(dfi)

        # BY TYPE (Customer / Internal)
        cust_i = int((dfi["type"].str.strip() == "Customer").sum()) if "type" in dfi.columns else 0
        int_i  = int((dfi["type"].str.strip() == "Internal").sum()) if "type" in dfi.columns else 0
        other_i = n_i - cust_i - int_i
        by_type_segs = [(cust_i, GOLD, "Customer"), (int_i, BLU, "Internal")]
        if other_i > 0:
            by_type_segs.append((other_i, MT, "Other"))

        # BY PRIORITY
        def _prio_count(p):
            col = dfi["priority"]
            try:
                return int((col.astype(int) == p).sum())
            except Exception:
                return 0
        p1, p2, p3, p4 = _prio_count(1), _prio_count(2), _prio_count(3), _prio_count(4)
        by_prio_segs = [
            (p1, RED, "P1"), (p2, ORG, "P2"), (p3, BLU, "P3"), (p4, ACC, "P4"),
        ]

        # ESTIMATION
        est_i  = int((dfi["original_estimate"].fillna(0) > 0).sum())
        uest_i = n_i - est_i
        by_est_segs = [(est_i, G, f"Estimated: {est_i:,} ({round(est_i/n_i*100) if n_i else 0}%)"),
                       (uest_i, RED, f"Unestimated: {uest_i:,} ({round(uest_i/n_i*100) if n_i else 0}%)")]

        issues_panel = html.Div([
            # Header
            html.Div([
                html.Div([
                    html.Span("Issues", style={
                        "fontSize": "16px", "fontWeight": "700", "color": TXT,
                        "marginRight": "8px",
                    }),
                    html.Span("Jan 2024 – Present", style={"fontSize": "12px", "color": MT}),
                ]),
                html.Span(f"{n_i:,} items", style={
                    "fontSize": "11px", "fontWeight": "600", "color": GOLD,
                    "background": "rgba(251,191,36,0.15)",
                    "border": "1px solid rgba(251,191,36,0.30)",
                    "borderRadius": "12px", "padding": "2px 10px",
                }),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "center", "marginBottom": "18px"}),

            _bar_row("By Type",     by_type_segs),
            _bar_row("By Priority", by_prio_segs, show_pct=False),
            _bar_row("Estimation",  by_est_segs,  show_pct=False, margin_bottom="12px"),

            _callout(
                "P1 Issues (top priority)",
                "All P1s must be fully estimated through Dec 2026",
                p1, "rgba(248,113,113,0.08)", "rgba(248,113,113,0.22)", RED, RED,
            ),
        ], style={
            "background": CARD, "border": f"1px solid {BD}",
            "borderRadius": "12px", "padding": "20px 24px", "flex": "1",
        })

    # ── Enhancements panel ────────────────────────────────────────────────────
    enh_panel = None
    if type_filter in ("All", "Enhancements"):
        dfe = df_enh
        n_e = len(dfe)

        # BY TYPE
        cust_e = int((dfe["type"].str.strip() == "Customer").sum()) if "type" in dfe.columns else 0
        int_e  = int((dfe["type"].str.strip() == "Internal").sum()) if "type" in dfe.columns else 0
        other_e = n_e - cust_e - int_e
        by_type_e = [(cust_e, G, "Customer"), (int_e, BLU, "Internal")]
        if other_e > 0:
            by_type_e.append((other_e, MT, "Other"))

        # BY SIZE
        est_col = dfe["original_estimate"].fillna(0)
        big    = int((est_col >= 40).sum())
        medium = int(((est_col >= 8) & (est_col < 40)).sum())
        small  = n_e - big - medium
        by_size_e = [(big, RED, "Big"), (medium, GOLD, "Medium"), (small, G, "Small")]

        # ESTIMATION
        est_e  = int((est_col > 0).sum())
        uest_e = n_e - est_e
        by_est_e = [
            (est_e,  G,   f"Estimated: {est_e:,} ({round(est_e/n_e*100) if n_e else 0}%)"),
            (uest_e, RED, f"Unestimated: {uest_e:,} ({round(uest_e/n_e*100) if n_e else 0}%)"),
        ]
        big_med = big + medium

        enh_panel = html.Div([
            html.Div([
                html.Div([
                    html.Span("Enhancements", style={
                        "fontSize": "16px", "fontWeight": "700", "color": TXT,
                        "marginRight": "8px",
                    }),
                    html.Span("Inception – Present", style={"fontSize": "12px", "color": MT}),
                ]),
                html.Span(f"{n_e:,} items", style={
                    "fontSize": "11px", "fontWeight": "600", "color": G,
                    "background": "rgba(52,211,153,0.12)",
                    "border": "1px solid rgba(52,211,153,0.28)",
                    "borderRadius": "12px", "padding": "2px 10px",
                }),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "center", "marginBottom": "18px"}),

            _bar_row("By Type",     by_type_e),
            _bar_row("By Size",     by_size_e, show_pct=False),
            _bar_row("Estimation",  by_est_e,  show_pct=False, margin_bottom="12px"),

            _callout(
                "Big + Medium (top priority)",
                "Customer Big & Medium fully estimated through Dec 2026",
                big_med, "rgba(251,191,36,0.07)", "rgba(251,191,36,0.22)", GOLD, GOLD,
            ),
        ], style={
            "background": CARD, "border": f"1px solid {BD}",
            "borderRadius": "12px", "padding": "20px 24px", "flex": "1",
        })

    # ── Tasks breakdown panel ─────────────────────────────────────────────────
    _OH = "#a78bfa"
    _CAT_COLORS = {
        "Meetings & Calls":  "#60a5fa",
        "Dev Overhead":      "#a78bfa",
        "Research & Spikes": "#fbbf24",
        "Design & Docs":     "#f472b6",
        "Testing & QA":      "#34d399",
        "Operations":        "#fb923c",
        "Other":             "#6b7280",
    }
    try:
        with engine.connect() as conn:
            _cat_rows = conn.execute(text(
                "SELECT stc.category, stc.method, COUNT(*) AS cnt "
                "FROM standalone_task_classifications stc "
                "JOIN work_items_main w ON w.work_item_id = stc.task_id "
                "GROUP BY stc.category, stc.method"
            )).fetchall()
    except Exception:
        _cat_rows = []

    _cat_counts: dict[str, int] = {}
    _meth_counts: dict[str, int] = {}
    for r in _cat_rows:
        _cat_counts[r.category] = _cat_counts.get(r.category, 0) + r.cnt
        _meth_counts[r.method]  = _meth_counts.get(r.method,  0) + r.cnt
    _n_classified = sum(_meth_counts.values())

    _cat_segs  = [(v, _CAT_COLORS.get(k, MT), k)
                  for k, v in sorted(_cat_counts.items(), key=lambda x: -x[1]) if v > 0]
    _meth_segs = [
        (_meth_counts.get("rules",    0), G,   "Keyword Rules"),
        (_meth_counts.get("ollama",   0), _OH, "AI · Ollama"),
        (_meth_counts.get("fallback", 0), MT,  "Fallback"),
    ]

    tasks_panel = html.Div([
        html.Div([
            html.Div([
                html.Span("Tasks", style={
                    "fontSize": "16px", "fontWeight": "700",
                    "color": TXT, "marginRight": "8px",
                }),
                html.Span("Dev & Mobile · standalone (not linked to any story or bug)",
                          style={"fontSize": "12px", "color": MT}),
            ]),
            html.Span(f"{_n_classified:,} classified", style={
                "fontSize": "11px", "fontWeight": "600", "color": _OH,
                "background": "rgba(167,139,250,0.12)",
                "border": "1px solid rgba(167,139,250,0.28)",
                "borderRadius": "12px", "padding": "2px 10px",
            }),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "center", "marginBottom": "18px"}),
        _bar_row("By Category", _cat_segs,  show_pct=False),
        _bar_row("By Method",   _meth_segs, show_pct=False, margin_bottom="12px"),
        html.Div([
            html.Span("ℹ", style={"color": _OH, "fontSize": "14px",
                                   "marginRight": "8px", "lineHeight": "1"}),
            html.Span(
                f"Classified automatically on every ADO sync · "
                f"{max(_n_tasks - _n_classified, 0):,} tasks unclassified (linked to stories/bugs or outside Dev+Mobile scope)",
                style={"fontSize": "12px", "color": MT},
            ),
        ], style={
            "display": "flex", "alignItems": "flex-start",
            "background": "rgba(167,139,250,0.07)",
            "border": "1px solid rgba(167,139,250,0.20)",
            "borderRadius": "8px", "padding": "12px 16px",
        }),
    ], style={
        "background": CARD, "border": f"1px solid {BD}",
        "borderRadius": "12px", "padding": "20px 24px",
        "flex": "1", "minWidth": "0",
    })

    panels = [p for p in [issues_panel, enh_panel, tasks_panel] if p is not None]

    # ── Decision Validity Gate ────────────────────────────────────────────────
    validity_gate = html.Div([
        html.Div([
            html.Span("ℹ", style={
                "color": BLU, "fontSize": "16px", "marginRight": "10px", "lineHeight": "1",
            }),
            html.Span("Decision Validity Gate", style={
                "fontSize": "14px", "fontWeight": "700", "color": BLU,
            }),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"}),
        html.Div(
            "Confirm total loaded matches expected VSTS export before each sprint planning session. "
            "If Issues count is below Jan 2024 baseline or Enhancements count has drifted by > 2%, "
            "re-pull before proceeding.",
            style={"fontSize": "13px", "color": MT, "lineHeight": "1.7"},
        ),
    ], style={
        "background": "rgba(96,165,250,0.07)",
        "border": "1px solid rgba(96,165,250,0.20)",
        "borderRadius": "10px", "padding": "16px 20px", "marginTop": "20px",
    })

    return html.Div([
        kpis,
        html.Div(panels, style={"display": "flex", "gap": "20px", "flexWrap": "wrap"}),
        validity_gate,
    ])


# ── Addition & Deletion ───────────────────────────────────────────────────────

_CLOSED_STATES = frozenset([
    "Resolved", "Closed", "Not an issue", "Not Required",
    "No Customer Response", "Userstory Update",
])

_TEAM_LABEL = {
    "Development": "Web Dev",
    "Mobile":      "Mobile Dev",
    "Design/Video":"Design",
    "QA":          "QA",
    "User Story":  "Story Writers",
    "Management":  "Management",
}


def _adl_chip(label, chip_type, val, active):
    bg  = "rgba(129,140,248,0.15)" if active else "rgba(255,255,255,0.04)"
    brd = "rgba(129,140,248,0.55)" if active else "rgba(255,255,255,0.12)"
    clr = "#c4b5fd" if active else MT
    fw  = "700" if active else "500"
    return html.Div(label, id={"type": chip_type, "val": val}, n_clicks=0, style={
        "padding": "5px 14px", "borderRadius": "20px", "cursor": "pointer",
        "fontSize": "12px", "fontWeight": fw,
        "background": bg, "color": clr, "border": f"1px solid {brd}",
        "whiteSpace": "nowrap",
    })


def _render_sprint_adl(horizon: str, source: str, adl_type: str, team: str):
    from config.team_mapping import TEAM_MAPPING, TEAMS_LIST

    today         = date.today()
    n_days        = {"30d": 30, "90d": 90, "180d": 180, "365d": 365}.get(horizon, 365)
    horizon_start = today - timedelta(days=n_days)
    h_ts          = pd.Timestamp(horizon_start)
    today_ts      = pd.Timestamp(today)

    # ── Query ─────────────────────────────────────────────────────────────
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT work_item_id, work_item_type, state,
                       type AS source_type, assigned_to,
                       created_date, closed_date
                FROM work_items_main
                WHERE created_date IS NOT NULL
            """), conn)
    except Exception:
        import traceback
        return html.Div([
            html.Div("Failed to load data", style={"color": RED, "fontWeight": "700"}),
            html.Pre(traceback.format_exc(), style={"color": MT, "fontSize": "11px"}),
        ]), {}

    if df.empty:
        return html.Div("No data available.", style={"color": MT, "padding": "40px"}), {}

    # ── Normalise dates ────────────────────────────────────────────────────
    for col in ("created_date", "closed_date"):
        s = pd.to_datetime(df[col], utc=True, errors="coerce")
        df[col] = s.dt.tz_localize(None) if s.dt.tz is None else s.dt.tz_convert(None)

    # ── Derive team ────────────────────────────────────────────────────────
    def _map_team(name):
        clean = str(name).split(" <")[0].strip()
        return TEAM_MAPPING.get(clean, "Unassigned")

    df["team"]        = df["assigned_to"].apply(_map_team)
    df["source_type"] = df["source_type"].fillna("").astype(str).str.strip()

    # ── Apply type filter (All = Issues + Enhancements only) ──────────────
    _all_types = ISSUE_TYPES | ENH_TYPES
    if adl_type == "Issues":
        df = df[df["work_item_type"].isin(ISSUE_TYPES)]
    elif adl_type == "Enhancements":
        df = df[df["work_item_type"].isin(ENH_TYPES)]
    else:
        df = df[df["work_item_type"].isin(_all_types)]

    # ── Apply source filter ───────────────────────────────────────────────
    if source != "All":
        df = df[df["source_type"] == source]

    # Per-team counts for chip labels (before team filter)
    team_counts: dict[str, int] = {"All": len(df)}
    for t in TEAMS_LIST:
        team_counts[t] = int((df["team"] == t).sum())

    # ── Apply team filter ─────────────────────────────────────────────────
    if team != "All":
        df = df[df["team"] == team]

    # ── Compute KPIs ──────────────────────────────────────────────────────
    is_closed    = df["state"].isin(_CLOSED_STATES)
    open_now     = int((~is_closed).sum())

    # Items in opening backlog = created before horizon AND either:
    #   (a) currently open, OR
    #   (b) closed with a real closed_date inside the horizon window
    # Excludes items in closed state with NULL closed_date — those can't be
    # placed in any month and would inflate the running total forever.
    opening_mask = (
        (df["created_date"] < h_ts) &
        (
            (~is_closed) |
            (is_closed & df["closed_date"].notna() & (df["closed_date"] >= h_ts))
        )
    )
    opening_backlog = int(opening_mask.sum())

    # "Added" = items created in horizon that we can properly account for:
    # either still open, or closed with a real closed_date we can place on the chart.
    # Items created in horizon but in a closed state with NULL closed_date are ADO
    # data-quality gaps — we can't place their removal on any month, so including
    # them in added would permanently inflate net and the running total.
    added_mask = (
        (df["created_date"] >= h_ts) & (df["created_date"] <= today_ts) &
        (~is_closed | df["closed_date"].notna())
    )
    closed_mask = (
        is_closed & df["closed_date"].notna() &
        (df["closed_date"] >= h_ts) & (df["closed_date"] <= today_ts)
    )
    added_total  = int(added_mask.sum())
    closed_total = int(closed_mask.sum())
    net          = added_total - closed_total
    net_str      = f"+{net}" if net > 0 else str(net)
    net_color    = RED if net > 0 else (G if net < 0 else MT)
    net_sub      = "Backlog growing" if net > 0 else ("Backlog shrinking" if net < 0 else "Stable")

    # ── Monthly buckets ───────────────────────────────────────────────────
    months = pd.period_range(
        start=pd.Timestamp(horizon_start).to_period("M"),
        end=today_ts.to_period("M"),
        freq="M",
    )
    added_by_m  = df.loc[added_mask,  "created_date"].dt.to_period("M").value_counts()
    closed_by_m = df.loc[closed_mask, "closed_date" ].dt.to_period("M").value_counts()

    added_vals  = [int(added_by_m.get(m, 0))  for m in months]
    closed_vals = [int(closed_by_m.get(m, 0)) for m in months]
    net_vals    = [a - c for a, c in zip(added_vals, closed_vals)]

    running: list[int] = []
    cur = opening_backlog
    for n in net_vals:
        cur += n
        running.append(cur)

    xlabels = [m.strftime("%b-%y") for m in months]

    # ── Plotly figure ─────────────────────────────────────────────────────
    fig = go.Figure()

    # Additions — purple, positive (go up)
    fig.add_trace(go.Bar(
        x=xlabels, y=added_vals,
        name="Additions (up)",
        marker=dict(color="#a78bfa", line=dict(width=0)),
        width=0.38,
        offset=-0.41,
    ))
    # Deletions — green, negative (go down), same x, offset to the right
    fig.add_trace(go.Bar(
        x=xlabels, y=[-v for v in closed_vals],
        name="Deletions (down)",
        marker=dict(color="#34d399", line=dict(width=0)),
        width=0.38,
        offset=0.03,
    ))
    # Net — orange diamonds
    fig.add_trace(go.Scatter(
        x=xlabels, y=net_vals,
        mode="lines+markers",
        name="Net",
        line=dict(color="#f59e0b", width=2),
        marker=dict(symbol="diamond", size=10, color="#f59e0b",
                    line=dict(width=0)),
    ))
    # Running open total — cyan on right axis
    fig.add_trace(go.Scatter(
        x=xlabels, y=running,
        mode="lines+markers",
        name="Open items (running total, right axis)",
        line=dict(color="#22d3ee", width=2.5),
        marker=dict(symbol="circle", size=6, color="#22d3ee",
                    line=dict(width=0)),
        yaxis="y2",
    ))

    y_max = max(max(added_vals or [0]), max(closed_vals or [0]), 1)
    fig.update_layout(
        template="midnight",
        height=360,
        barmode="overlay",
        margin=dict(l=10, r=55, t=16, b=70),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            tickfont=dict(size=11, color="#94a3b8"),
            title=None, fixedrange=True,
            showgrid=False,
            zeroline=False,
        ),
        yaxis=dict(
            title=None, fixedrange=True,
            range=[-(y_max * 1.45), y_max * 1.45],
            zeroline=True,
            zerolinecolor="rgba(255,255,255,0.25)",
            zerolinewidth=1.5,
            gridcolor="rgba(255,255,255,0.04)",
            tickfont=dict(size=10, color="#64748b"),
        ),
        yaxis2=dict(
            overlaying="y", side="right", showgrid=False,
            fixedrange=True, title=None,
            tickfont=dict(size=10, color="#22d3ee"),
            zeroline=False,
        ),
        legend=dict(
            orientation="h", y=-0.22, x=0,
            font=dict(size=11, color="#94a3b8"),
            bgcolor="rgba(0,0,0,0)",
        ),
    )

    # ── Chip helpers ──────────────────────────────────────────────────────
    # Team chips
    team_chip_rows = [("All", "All")] + [(t, t) for t in TEAMS_LIST]
    team_chips = []
    for key, t_key in team_chip_rows:
        display = _TEAM_LABEL.get(key, key)
        cnt = team_counts.get(t_key, 0)
        team_chips.append(_adl_chip(
            f"{display}  {cnt}", "adl-team-chip", t_key, team == t_key,
        ))

    # Horizon chips
    h_chips = [_adl_chip(h, "adl-horizon-chip", h, horizon == h)
               for h in ("30d", "90d", "180d", "365d")]

    # Source chips
    src_counts = {
        "All":      len(df),
        "Customer": int((df["source_type"] == "Customer").sum()),
        "Internal": int((df["source_type"] == "Internal").sum()),
    }
    s_chips = [
        _adl_chip(f"{s}  {src_counts[s]}", "adl-source-chip", s, source == s)
        for s in ("All", "Customer", "Internal")
    ]

    # Type chips
    type_counts = {
        "All":          len(df),
        "Issues":       int(df["work_item_type"].isin(ISSUE_TYPES).sum()),
        "Enhancements": int(df["work_item_type"].isin(ENH_TYPES).sum()),
    }
    t_chips = [
        _adl_chip(f"{lbl}  {type_counts[lbl]}", "adl-type-chip", lbl, adl_type == lbl)
        for lbl in ("All", "Issues", "Enhancements")
    ]

    subtitle = f"Rolling {horizon} from {horizon_start.strftime('%b-%y')}"
    running_dict = {label: val for label, val in zip(xlabels, running)}

    # ── Assemble layout ───────────────────────────────────────────────────
    layout = html.Div([
        # Title row
        html.Div([
            html.Span("Issues/Enhancements — Addition & Deletion", style={
                "fontSize": "18px", "fontWeight": "700", "color": TXT, "marginRight": "12px",
            }),
            html.Span(subtitle, style={"fontSize": "12px", "color": MT}),
        ], style={"marginBottom": "14px", "display": "flex", "alignItems": "baseline", "flexWrap": "wrap"}),

        # Team chips row
        html.Div(team_chips, style={
            "display": "flex", "gap": "8px", "flexWrap": "wrap", "marginBottom": "12px",
        }),

        # Filter bar
        html.Div([
            html.Div([
                html.Span("HORIZON", style={
                    "fontSize": "9px", "fontWeight": "700", "color": MT,
                    "letterSpacing": "0.07em", "whiteSpace": "nowrap",
                }),
                *h_chips,
                html.Div(style={"width": "1px", "background": "rgba(255,255,255,0.12)",
                                "margin": "0 10px", "alignSelf": "stretch"}),
                html.Span("SOURCE", style={
                    "fontSize": "9px", "fontWeight": "700", "color": MT,
                    "letterSpacing": "0.07em", "whiteSpace": "nowrap",
                }),
                *s_chips,
                html.Div(style={"width": "1px", "background": "rgba(255,255,255,0.12)",
                                "margin": "0 10px", "alignSelf": "stretch"}),
                html.Span("TYPE", style={
                    "fontSize": "9px", "fontWeight": "700", "color": MT,
                    "letterSpacing": "0.07em", "whiteSpace": "nowrap",
                }),
                *t_chips,
            ], style={
                "display": "flex", "alignItems": "center", "gap": "6px",
                "flexWrap": "wrap", "flex": "1",
            }),
            html.Div([
                html.Span(f"{added_total} added", style={"color": "#a78bfa", "fontWeight": "600"}),
                html.Span(" · ", style={"color": MT}),
                html.Span(f"{closed_total} fixed", style={"color": "#34d399", "fontWeight": "600"}),
                html.Span(" · ", style={"color": MT}),
                html.Span(f"open {open_now}", style={"color": "#22d3ee", "fontWeight": "600"}),
            ], style={
                "display": "flex", "gap": "4px", "fontSize": "12px",
                "whiteSpace": "nowrap", "flexShrink": "0",
            }),
        ], style={
            "display": "flex", "justifyContent": "space-between", "alignItems": "center",
            "marginBottom": "16px", "flexWrap": "wrap", "gap": "8px",
        }),

        # KPI cards
        html.Div([
            _kpi_card(open_now,      "Open Now",    f"was {opening_backlog} at start", "#22d3ee"),
            _kpi_card(added_total,   "Added",       f"over {horizon}",                "#a78bfa"),
            _kpi_card(closed_total,  "Closed",      f"over {horizon}",                "#34d399"),
            _kpi_card(net_str,       "Net Change",  net_sub,                          net_color),
        ], style={"display": "flex", "gap": "16px", "marginBottom": "20px", "flexWrap": "wrap"}),

        # Chart card
        html.Div([
            html.Div([
                html.Div([
                    html.Div("Additions, deletions & open backlog", style={
                        "fontSize": "15px", "fontWeight": "700", "color": TXT,
                        "letterSpacing": "-0.01em",
                    }),
                    html.Div("Click any month for the items added and fixed", style={
                        "fontSize": "12px", "color": MT, "marginTop": "3px",
                    }),
                ]),
                html.Div([
                    html.Span("Open now: ", style={"fontSize": "13px", "color": MT}),
                    html.Span(str(open_now), style={
                        "fontSize": "14px", "fontWeight": "700", "color": "#22d3ee",
                    }),
                ]),
            ], style={
                "display": "flex", "justifyContent": "space-between",
                "alignItems": "flex-start", "marginBottom": "4px",
            }),

            dcc.Graph(
                figure=fig,
                config={"displayModeBar": False},
                id="adl-chart",
                style={"margin": "0 -8px"},
            ),

            html.Div(
                "Additions / deletions are item counts per month.  "
                "Net = additions − deletions.  "
                "Open items = opening backlog + cumulative net.  "
                "Scoped to the active team / source / type / horizon filters.",
                style={
                    "fontSize": "11px", "color": MT,
                    "marginTop": "4px", "lineHeight": "1.6",
                    "borderTop": "1px solid rgba(255,255,255,0.06)",
                    "paddingTop": "10px",
                },
            ),
        ], style={
            "background": "rgba(15,15,30,0.6)",
            "border": f"1px solid {BD}",
            "borderRadius": "14px", "padding": "22px 28px",
        }),
    ])
    return layout, running_dict


def _render_sprint(df, df_issues_scope, df_enh, type_filter):
    today        = date.today()
    sprint_start = date(today.year, today.month, 1)
    _, last_day  = monthrange(today.year, today.month)
    days_elapsed = today.day
    sprint_ts    = pd.Timestamp(sprint_start)

    if type_filter == "Issues":
        df = df[df["work_item_type"].isin(ISSUE_TYPES)]
    elif type_filter == "Enhancements":
        df = df[df["work_item_type"].isin(ENH_TYPES)]

    # ── Sprint items ──────────────────────────────────────────────────────────
    sprint_path = _get_sprint_path()
    if sprint_path:
        df_sprint = df[df["iteration_path"] == sprint_path].copy()
    else:
        month_str = today.strftime("%B")   # "April" matches "04-April"
        df_sprint = df[
            df["iteration_path"].str.contains(str(today.year), na=False)
            & df["iteration_path"].str.contains(month_str, na=False, case=False)
        ].copy()

    # ── Daily activity from pre-computed table ────────────────────────────────
    ym_str = today.strftime("%Y-%m")
    added_by_day:  dict[int, int] = {d: 0 for d in range(1, last_day + 1)}
    closed_by_day: dict[int, int] = {d: 0 for d in range(1, last_day + 1)}
    try:
        from data.loader import engine as _engine
        from sqlalchemy import text as _text
        with _engine.connect() as _conn:
            _rows = _conn.execute(_text(
                "SELECT day_date, added_count, closed_count "
                "FROM agg_sprint_daily_activity WHERE ym_str = :ym"
            ), {"ym": ym_str}).fetchall()
        for day_date, added, closed in _rows:
            d = pd.Timestamp(day_date).day
            if d in added_by_day:
                added_by_day[d]  = int(added  or 0)
                closed_by_day[d] = int(closed or 0)
    except Exception:
        pass

    # ── Totals ────────────────────────────────────────────────────────────────
    added_total  = sum(v for k, v in added_by_day.items() if k <= days_elapsed)
    closed_total = sum(v for k, v in closed_by_day.items() if k <= days_elapsed)
    net          = added_total - closed_total
    net_str      = f"+{net}" if net > 0 else str(net)
    net_color    = RED if net > 0 else G
    net_sub      = "Backlog growing" if net > 0 else ("Backlog shrinking" if net < 0 else "Stable")
    in_progress  = int((df_sprint["state"] == "Active").sum())

    # ── KPI cards ─────────────────────────────────────────────────────────────
    kpis = html.Div([
        _kpi_card(days_elapsed,        "Days Elapsed",      f"of {last_day}",           TXT),
        _kpi_card(f"{added_total:,}",  "Added This Sprint", f"Days 1–{days_elapsed}",   GOLD),
        _kpi_card(f"{closed_total:,}", "Closed This Sprint",f"Days 1–{days_elapsed}",   G),
        _kpi_card(net_str,             "Net Change",        net_sub,                    net_color),
    ], style={"display": "flex", "gap": "16px", "marginBottom": "24px"})

    # ── Daily activity chart ───────────────────────────────────────────────────
    all_days = list(range(1, last_day + 1))
    added_vals  = [added_by_day.get(d, 0)  for d in all_days]
    closed_vals = [closed_by_day.get(d, 0) for d in all_days]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=all_days, y=added_vals,
        name="Added", marker_color=GOLD,
        marker_line_width=0,
    ))
    fig.add_trace(go.Bar(
        x=all_days, y=closed_vals,
        name="Closed", marker_color=G,
        marker_line_width=0,
    ))
    # Today triangle marker
    fig.add_trace(go.Scatter(
        x=[today.day], y=[0],
        mode="markers",
        marker=dict(symbol="triangle-up", size=9, color=GOLD),
        name=f"Today = Day {days_elapsed} of {last_day}",
        showlegend=True,
    ))
    # Shade future days with a subtle shape
    fig.add_vrect(
        x0=today.day + 0.5, x1=last_day + 0.5,
        fillcolor="rgba(255,255,255,0.02)", line_width=0,
    )

    fig.update_layout(
        template="midnight", height=260, barmode="group",
        margin=dict(l=0, r=0, t=10, b=40),
        bargap=0.25, bargroupgap=0.05,
        xaxis=dict(
            tickmode="linear", tick0=1, dtick=1,
            tickfont=dict(size=9, color=MT),
            title=None, fixedrange=True,
        ),
        yaxis=dict(title=None, fixedrange=True),
        legend=dict(
            orientation="h", y=-0.22, x=0,
            font=dict(size=11, color=MT),
            bgcolor="rgba(0,0,0,0)",
        ),
        clickmode="event",
    )

    chart_card = html.Div([
        html.Div([
            html.Div([
                html.Div(
                    f"Daily Activity · Sprint 1 · {today.strftime('%b %Y')}",
                    style={"fontSize": "14px", "fontWeight": "700", "color": TXT},
                ),
                html.Div("Click any day bar for breakdown detail",
                         style={"fontSize": "12px", "color": MT, "marginTop": "2px"}),
            ]),
            html.Div([
                html.Span("In Progress today: ", style={"fontSize": "13px", "color": MT}),
                html.Span(str(in_progress), style={
                    "fontSize": "13px", "fontWeight": "700", "color": BLU,
                }),
            ]),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "flex-start", "marginBottom": "12px"}),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ], style={
        "background": CARD, "border": f"1px solid {BD}",
        "borderRadius": "12px", "padding": "20px 24px", "marginBottom": "20px",
    })

    # ── Recent activity table ─────────────────────────────────────────────────
    # Collect last 7 working days (newest first)
    working_days: list[date] = []
    cursor = today
    while len(working_days) < 7:
        if cursor.weekday() < 5:
            working_days.append(cursor)
        cursor -= timedelta(days=1)

    rows = []
    for wd in working_days:
        is_today = wd == today
        d        = wd.day
        a        = added_by_day.get(d, 0)
        c        = closed_by_day.get(d, 0)
        n        = a - c
        n_str    = f"+{n}" if n > 0 else str(n)
        status   = "Growing" if n > 0 else ("Reducing" if n < 0 else "Stable")
        ip       = str(in_progress) if is_today else "—"
        rows.append({
            "Day":         f"▶ {d}" if is_today else str(d),
            "Date":        wd.strftime("%d %b"),
            "Added":       a,
            "Closed":      c,
            "Net":         n_str,
            "In Progress": ip,
            "Status":      status,
        })

    tbl = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c}
                 for c in ("Day", "Date", "Added", "Closed", "Net", "In Progress", "Status")],
        style_table={"overflowX": "auto"},
        style_header={
            "background": "#1a1a2e", "color": MT,
            "fontWeight": "700", "fontSize": "10px",
            "textTransform": "uppercase", "letterSpacing": "0.07em",
            "border": f"1px solid {BD}", "padding": "10px 16px",
        },
        style_cell={
            "background": CARD, "color": TXT,
            "border": f"1px solid {BD}",
            "fontSize": "13px", "padding": "12px 16px",
            "fontFamily": "Inter, sans-serif", "textAlign": "center",
        },
        style_cell_conditional=[
            {"if": {"column_id": "Day"},    "textAlign": "left", "color": MT},
            {"if": {"column_id": "Date"},   "textAlign": "left", "color": MT},
            {"if": {"column_id": "Status"}, "fontWeight": "600"},
        ],
        style_data_conditional=[
            # Added = gold
            {"if": {"column_id": "Added", "filter_query": "{Added} > 0"},
             "color": GOLD, "fontWeight": "600"},
            # Closed = green
            {"if": {"column_id": "Closed", "filter_query": "{Closed} > 0"},
             "color": G, "fontWeight": "600"},
            # Net positive = red
            {"if": {"column_id": "Net", "filter_query": '{Net} contains "+"'},
             "color": RED, "fontWeight": "700"},
            # Net negative = green
            {"if": {"column_id": "Net", "filter_query": '{Net} contains "-"'},
             "color": G, "fontWeight": "700"},
            # In Progress = blue
            {"if": {"column_id": "In Progress", "filter_query": '{In Progress} != "—"'},
             "color": BLU, "fontWeight": "600"},
            # Status pills
            {"if": {"column_id": "Status", "filter_query": '{Status} = "Growing"'},
             "color": "#0f0f1e", "background": RED,
             "borderRadius": "12px"},
            {"if": {"column_id": "Status", "filter_query": '{Status} = "Reducing"'},
             "color": "#0f0f1e", "background": G,
             "borderRadius": "12px"},
            {"if": {"column_id": "Status", "filter_query": '{Status} = "Stable"'},
             "color": MT, "background": "#1e1e38",
             "borderRadius": "12px"},
            # Today row highlight
            {"if": {"filter_query": '{Day} contains "▶"'},
             "background": "rgba(129,140,248,0.06)"},
        ],
        page_action="none", sort_action="none",
    )

    sprint_label = html.Div(
        f"Sprint path: {sprint_path}" if sprint_path else
        "Sprint path not detected — run a sync to populate iteration history.",
        style={"fontSize": "11px", "color": MT, "marginBottom": "16px"},
    )

    table_card = html.Div([
        html.Div("Recent Activity · Last 7 Working Days", style={
            "fontSize": "14px", "fontWeight": "700", "color": TXT, "marginBottom": "16px",
        }),
        tbl,
    ], style={
        "background": CARD, "border": f"1px solid {BD}",
        "borderRadius": "12px", "padding": "20px 24px",
    })

    return html.Div([
        kpis,
        sprint_label,
        chart_card,
        table_card,
    ])


# ── Month drill-down callbacks ─────────────────────────────────────────────────

@callback(
    Output("adl-selected-month", "data"),
    Input("adl-chart",           "clickData"),
    Input("adl-backdrop",        "n_clicks"),
    Input("adl-panel-close-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _adl_select_month(click_data, _back, _close):
    if ctx.triggered_id in ("adl-backdrop", "adl-panel-close-btn"):
        return None
    if not click_data or not click_data.get("points"):
        raise PreventUpdate
    return click_data["points"][0]["x"]


_PANEL_OPEN_STYLE = {
    "position": "fixed", "top": "0", "right": "0",
    "width": "420px", "height": "100vh",
    "background": "#0d0d1e",
    "borderLeft": "1px solid rgba(255,255,255,0.09)",
    "overflowY": "auto", "overflowX": "hidden",
    "zIndex": "1001",
    "transform": "translateX(0)",
    "transition": "transform 0.26s cubic-bezier(0.4,0,0.2,1)",
    "boxShadow": "-12px 0 40px rgba(0,0,0,0.6)",
}
_PANEL_CLOSED_STYLE = {
    "position": "fixed", "top": "0", "right": "0",
    "width": "420px", "height": "100vh",
    "background": "#0d0d1e",
    "borderLeft": "1px solid rgba(255,255,255,0.09)",
    "overflowY": "auto", "overflowX": "hidden",
    "zIndex": "1001",
    "transform": "translateX(100%)",
    "transition": "transform 0.26s cubic-bezier(0.4,0,0.2,1)",
    "boxShadow": "-12px 0 40px rgba(0,0,0,0.6)",
}
_BACKDROP_ON  = {"display": "block", "position": "fixed", "top": "0", "left": "0",
                 "width": "100vw", "height": "100vh",
                 "background": "rgba(0,0,0,0.55)", "zIndex": "1000"}
_BACKDROP_OFF = {"display": "none", "position": "fixed", "top": "0", "left": "0",
                 "width": "100vw", "height": "100vh",
                 "background": "rgba(0,0,0,0.55)", "zIndex": "1000"}

_ADO_BASE = "https://dev.azure.com/expenseondemand/Solo%20Expenses/_workitems/edit"


def _mini_kpi(value, label, color):
    return html.Div([
        html.Div(str(value), style={
            "fontSize": "28px", "fontWeight": "700", "color": color, "lineHeight": "1.1",
        }),
        html.Div(label, style={
            "fontSize": "10px", "fontWeight": "700", "color": "rgba(255,255,255,0.45)",
            "letterSpacing": "0.08em", "textTransform": "uppercase", "marginTop": "3px",
        }),
    ], style={
        "background": "rgba(255,255,255,0.04)",
        "border": "1px solid rgba(255,255,255,0.08)",
        "borderRadius": "10px", "padding": "14px 18px",
        "flex": "1", "minWidth": "0",
    })


def _item_row(item):
    wid        = item.get("work_item_id", "")
    title      = str(item.get("title") or "Untitled")[:70]
    wtype      = item.get("work_item_type", "")
    assigned   = str(item.get("assigned_to") or "")
    first_name = assigned.split(" <")[0].split()[0] if assigned else "—"
    src        = str(item.get("source_type") or "").strip()

    src_badge = html.Span(src or "—", style={
        "fontSize": "10px", "fontWeight": "600",
        "color": "#60a5fa" if src == "Customer" else "#94a3b8",
        "background": "rgba(96,165,250,0.12)" if src == "Customer" else "rgba(255,255,255,0.06)",
        "border": "1px solid rgba(96,165,250,0.28)" if src == "Customer"
                  else "1px solid rgba(255,255,255,0.10)",
        "borderRadius": "10px", "padding": "1px 7px",
    })

    return html.Div([
        html.Div([
            html.A(f"#{wid}", href=f"{_ADO_BASE}/{wid}", target="_blank", style={
                "fontSize": "11px", "fontWeight": "700", "color": "#818cf8",
                "textDecoration": "none", "marginRight": "6px", "flexShrink": "0",
            }),
            html.Span(title, style={
                "fontSize": "12px", "color": "#e2e8f0", "flexGrow": "1",
                "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
            }),
        ], style={"display": "flex", "alignItems": "baseline",
                  "overflow": "hidden", "marginBottom": "5px"}),
        html.Div([
            html.Span("P1", style={
                "fontSize": "10px", "fontWeight": "700", "color": "#fbbf24",
                "background": "rgba(251,191,36,0.12)",
                "border": "1px solid rgba(251,191,36,0.30)",
                "borderRadius": "10px", "padding": "1px 7px", "marginRight": "6px",
            }),
            src_badge,
            html.Span(f"{first_name} · {wtype}", style={
                "fontSize": "10px", "color": "rgba(255,255,255,0.38)",
                "marginLeft": "6px",
            }),
        ], style={"display": "flex", "alignItems": "center"}),
    ], style={
        "padding": "10px 14px",
        "borderRadius": "8px",
        "background": "rgba(255,255,255,0.025)",
        "border": "1px solid rgba(255,255,255,0.055)",
        "marginBottom": "6px",
    })


@callback(
    Output("adl-panel-content",  "children"),
    Output("adl-panel-wrapper",  "style"),
    Output("adl-backdrop",       "style"),
    Input("adl-selected-month",  "data"),
    State("adl-horizon",         "data"),
    State("adl-source",          "data"),
    State("adl-type",            "data"),
    State("adl-team",            "data"),
    State("adl-month-running",   "data"),
)
def _adl_panel_render(selected_month, adl_horizon, adl_source, adl_type, adl_team, running_data):
    if not selected_month:
        return [], _PANEL_CLOSED_STYLE, _BACKDROP_OFF

    # Parse "Jun-26" → month period
    try:
        dt = datetime.strptime(selected_month, "%b-%y")
        month_start = pd.Timestamp(dt).normalize()
        month_end   = (month_start + pd.offsets.MonthEnd(1)).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    except Exception:
        return [], _PANEL_CLOSED_STYLE, _BACKDROP_OFF

    # Query items touching this month
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT work_item_id, work_item_type, state, title,
                       type AS source_type, assigned_to,
                       created_date, closed_date, priority
                FROM work_items_main
                WHERE created_date IS NOT NULL
            """), conn)
    except Exception:
        return [html.Div("Failed to load panel data", style={"color": RED, "padding": "24px"})], \
               _PANEL_OPEN_STYLE, _BACKDROP_ON

    if df.empty:
        return [html.Div("No data.", style={"color": MT, "padding": "24px"})], \
               _PANEL_OPEN_STYLE, _BACKDROP_ON

    # Normalise
    for col in ("created_date", "closed_date"):
        s = pd.to_datetime(df[col], utc=True, errors="coerce")
        df[col] = s.dt.tz_localize(None) if s.dt.tz is None else s.dt.tz_convert(None)
    df["priority"]    = pd.to_numeric(df["priority"], errors="coerce").fillna(4).astype(int)
    df["source_type"] = df["source_type"].fillna("").astype(str).str.strip()

    from config.team_mapping import TEAM_MAPPING
    def _map_team(name):
        clean = str(name).split(" <")[0].strip()
        return TEAM_MAPPING.get(clean, "Unassigned")
    df["team"] = df["assigned_to"].apply(_map_team)

    # Apply type filter (same logic as chart)
    _all_types = ISSUE_TYPES | ENH_TYPES
    if adl_type == "Issues":
        df = df[df["work_item_type"].isin(ISSUE_TYPES)]
    elif adl_type == "Enhancements":
        df = df[df["work_item_type"].isin(ENH_TYPES)]
    else:
        df = df[df["work_item_type"].isin(_all_types)]

    if adl_source != "All":
        df = df[df["source_type"] == adl_source]
    if adl_team != "All":
        df = df[df["team"] == adl_team]

    is_closed = df["state"].isin(_CLOSED_STATES)

    added_mask = (
        (df["created_date"] >= month_start) & (df["created_date"] <= month_end) &
        (~is_closed | df["closed_date"].notna())
    )
    closed_mask = (
        is_closed & df["closed_date"].notna() &
        (df["closed_date"] >= month_start) & (df["closed_date"] <= month_end)
    )

    added_total  = int(added_mask.sum())
    closed_total = int(closed_mask.sum())
    net          = added_total - closed_total
    open_after   = int(running_data.get(selected_month, 0)) if running_data else 0

    net_str   = f"+{net}" if net > 0 else str(net)
    net_color = RED if net > 0 else (G if net < 0 else MT)

    # P1 items
    df_added  = df[added_mask  & (df["priority"] == 1)].to_dict("records")
    df_closed = df[closed_mask & (df["priority"] == 1)].to_dict("records")

    # Subtitle
    team_label = adl_team if adl_team != "All" else "All teams"
    net_part   = f"{'+' if net >= 0 else ''}{net} net"

    def _section(title, items, accent):
        if not items:
            return html.Div([
                html.Div(title, style={
                    "fontSize": "11px", "fontWeight": "700", "color": accent,
                    "letterSpacing": "0.07em", "textTransform": "uppercase",
                    "marginBottom": "8px",
                }),
                html.Div("No P1 items this month", style={
                    "fontSize": "12px", "color": "rgba(255,255,255,0.3)",
                    "padding": "10px 0",
                }),
            ], style={"marginBottom": "20px"})
        return html.Div([
            html.Div([
                html.Span(title, style={
                    "fontSize": "11px", "fontWeight": "700", "color": accent,
                    "letterSpacing": "0.07em", "textTransform": "uppercase",
                }),
                html.Span(f" {len(items)}", style={
                    "fontSize": "11px", "fontWeight": "600", "color": accent,
                    "background": f"rgba(255,255,255,0.07)",
                    "borderRadius": "10px", "padding": "1px 7px", "marginLeft": "6px",
                }),
            ], style={"marginBottom": "10px", "display": "flex", "alignItems": "center"}),
            *[_item_row(it) for it in items],
        ], style={"marginBottom": "20px"})

    content = html.Div([
        # Header
        html.Div([
            html.Div([
                html.Div(selected_month, style={
                    "fontSize": "22px", "fontWeight": "700", "color": "#e2e8f0",
                    "marginBottom": "4px",
                }),
                html.Div(
                    f"{team_label} · {added_total} added · {closed_total} fixed · {net_part}",
                    style={"fontSize": "12px", "color": "rgba(255,255,255,0.45)"},
                ),
            ]),
        ], style={
            "padding": "24px 56px 20px 24px",
            "borderBottom": "1px solid rgba(255,255,255,0.07)",
            "marginBottom": "20px",
        }),

        # KPI mini-cards
        html.Div([
            html.Div([
                _mini_kpi(f"+{added_total}", "Added",      "#a78bfa"),
                _mini_kpi(f"-{closed_total}", "Fixed",     "#34d399"),
            ], style={"display": "flex", "gap": "10px", "marginBottom": "10px"}),
            html.Div([
                _mini_kpi(net_str, "Net",      net_color),
                _mini_kpi(open_after, "Open after", "#22d3ee"),
            ], style={"display": "flex", "gap": "10px"}),
        ], style={"padding": "0 24px", "marginBottom": "24px"}),

        # Item lists
        html.Div([
            _section("Added this month (P1)", df_added,  "#a78bfa"),
            _section("Fixed this month (P1)",  df_closed, "#34d399"),
        ], style={"padding": "0 24px 24px 24px"}),
    ])

    return content, _PANEL_OPEN_STYLE, _BACKDROP_ON
