"""Iteration Report download page."""

from __future__ import annotations

from datetime import date

import dash
from dash import dcc, html, Input, Output, callback, no_update
from sqlalchemy import text

from data.loader import engine

dash.register_page(__name__, path="/reports", name="Reports")

_BD = "var(--border)"
_T1 = "var(--text-primary)"
_T2 = "var(--text-secondary)"
_CD = "var(--bg-elevated)"
_PU = "var(--purple)"


def _available_sprints() -> list[dict]:
    """Return sprints that have items in work_items_main, newest first."""
    try:
        with engine.connect() as c:
            rows = c.execute(text("""
                SELECT DISTINCT
                    '2026-' || LPAD(
                        CASE
                          WHEN iteration_path LIKE '%Iteration 2026 01-%' THEN '01'
                          WHEN iteration_path LIKE '%Iteration 2026 02-%' THEN '02'
                          WHEN iteration_path LIKE '%Iteration 2026 03-%' THEN '03'
                          WHEN iteration_path LIKE '%Iteration 2026 04-%' THEN '04'
                          WHEN iteration_path LIKE '%Iteration 2026 05-%' THEN '05'
                          WHEN iteration_path LIKE '%Iteration 2026 06-%' THEN '06'
                          WHEN iteration_path LIKE '%Iteration 2026 07-%' THEN '07'
                          WHEN iteration_path LIKE '%Iteration 2026 08-%' THEN '08'
                          WHEN iteration_path LIKE '%Iteration 2026 09-%' THEN '09'
                          WHEN iteration_path LIKE '%Iteration 2026 10-%' THEN '10'
                          WHEN iteration_path LIKE '%Iteration 2026 11-%' THEN '11'
                          WHEN iteration_path LIKE '%Iteration 2026 12-%' THEN '12'
                        END, 2, '0') AS ym
                FROM work_items_main
                WHERE iteration_path LIKE '%Iteration 2026%'
                  AND work_item_type IN ('Enhancement','Bug','Bug_UI','Bug_Text')
                ORDER BY ym DESC
            """)).fetchall()
        months = {
            "01": "January", "02": "February", "03": "March", "04": "April",
            "05": "May",      "06": "June",     "07": "July",  "08": "August",
            "09": "September","10": "October",  "11": "November","12": "December",
        }
        return [
            {"label": f"{months.get(r[0][5:], r[0][5:])} 2026", "value": r[0]}
            for r in rows if r[0] and "None" not in r[0]
        ]
    except Exception:
        return []


layout = html.Div([
    html.Div([
        html.Div("REPORTS", style={
            "fontSize": "11px", "fontWeight": "800", "color": _PU,
            "letterSpacing": "2px", "marginBottom": "4px",
        }),
        html.H1("Sprint Iteration Reports", style={
            "fontSize": "26px", "fontWeight": "700", "color": _T1,
            "margin": "0 0 6px",
        }),
        html.Div(
            "Generate and download management-ready sprint reports. "
            "Select a sprint and click Download to get the HTML report.",
            style={"fontSize": "13px", "color": _T2, "marginBottom": "32px"},
        ),
    ]),

    html.Div([
        html.Div("Select Sprint", style={
            "fontSize": "11px", "fontWeight": "700", "color": _T2,
            "textTransform": "uppercase", "letterSpacing": "0.8px",
            "marginBottom": "8px",
        }),
        html.Div([
            dcc.Dropdown(
                id="rpt-sprint-select",
                options=_available_sprints(),
                value=None,
                clearable=False,
                placeholder="Choose a sprint…",
                className="dark-dropdown",
                style={"width": "280px", "fontSize": "13px"},
            ),
            html.A(
                html.Button([
                    html.Span("↓", style={"marginRight": "8px", "fontSize": "16px"}),
                    "Download Report",
                ], style={
                    "background": "#2563EB", "color": "#fff", "border": "none",
                    "borderRadius": "8px", "padding": "10px 22px",
                    "fontSize": "13px", "fontWeight": "600", "cursor": "pointer",
                }),
                id="rpt-download-link",
                href="",
                target="_blank",
            ),
        ], style={"display": "flex", "gap": "12px", "alignItems": "center"}),

        html.Div(id="rpt-info", style={"marginTop": "12px", "fontSize": "12px", "color": _T2}),

    ], style={
        "background": _CD, "border": f"1px solid {_BD}",
        "borderRadius": "12px", "padding": "24px 28px",
        "maxWidth": "640px",
    }),

    # What's in the report
    html.Div([
        html.Div("Report Contents", style={
            "fontSize": "13px", "fontWeight": "700", "color": _T1,
            "marginBottom": "12px",
        }),
        html.Div([
            html.Div("📊  Executive Summary — 4 KPI cards (delivery, bugs, scope creep, estimation)",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("📦  Sprint Delivery — enhancements & bugs by state with completion bars",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("🎯  Scope Management — mid-sprint scope injection analysis",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("⚡  Capacity & Allocation — per-developer feature hours vs capacity",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("👥  Developer Delivery — items completed per developer",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("🔴  Priority Bugs — all P1 and P2 bug status",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("📏  Estimation Compliance — items missing estimates",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("➜   Carry-Forward — items rolling into next sprint",
                     style={"fontSize": "12px", "color": _T2, "marginBottom": "6px"}),
            html.Div("💡  Key Findings & Recommendations — data-driven insights",
                     style={"fontSize": "12px", "color": _T2}),
        ]),
    ], style={
        "background": _CD, "border": f"1px solid {_BD}",
        "borderRadius": "12px", "padding": "24px 28px",
        "maxWidth": "640px", "marginTop": "20px",
    }),

], style={"padding": "28px 32px", "maxWidth": "800px", "margin": "0 auto"})


@callback(
    Output("rpt-download-link", "href"),
    Output("rpt-info", "children"),
    Input("rpt-sprint-select", "value"),
)
def _update_link(ym_str):
    if not ym_str:
        return "", ""
    month_name = date(int(ym_str[:4]), int(ym_str[5:7]), 1).strftime("%B %Y")
    return (
        f"/download-report?sprint={ym_str}",
        f"Clicking Download will generate the {month_name} report from live data and download it as an HTML file.",
    )
