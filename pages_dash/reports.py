"""Reports page — sprint downloads, custom analysis requests, and admin queue."""
from __future__ import annotations
import json
from datetime import date, datetime, timezone

import dash
from dash import dcc, html, Input, Output, State, callback, callback_context, no_update, ALL
from sqlalchemy import text

from data.loader import engine
from db.report_requests import (
    STATUS_PENDING, STATUS_CP1, STATUS_CP1_OK, STATUS_CP2, STATUS_CP2_OK,
    STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED,
    add_request, get_all_requests, get_request, set_field, status_label,
)

dash.register_page(__name__, path="/reports", name="Reports")

_BD = "var(--border)"
_T1 = "var(--text-primary)"
_T2 = "var(--text-secondary)"
_CD = "var(--bg-elevated)"
_PU = "var(--purple)"
_BG = "var(--bg-primary)"


# ── Sprint list helper ─────────────────────────────────────────────────────────

def _available_sprints() -> list[dict]:
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
            "01": "January", "02": "February", "03": "March",    "04": "April",
            "05": "May",     "06": "June",      "07": "July",    "08": "August",
            "09": "September","10": "October",  "11": "November","12": "December",
        }
        return [
            {"label": f"{months.get(r[0][5:], r[0][5:])} 2026", "value": r[0]}
            for r in rows if r[0] and "None" not in r[0]
        ]
    except Exception:
        return []


# ── Queue row renderer ─────────────────────────────────────────────────────────

def _fmt_time(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    try:
        return dt.strftime("%-d %b %H:%M") if hasattr(dt, "strftime") else str(dt)
    except ValueError:
        return dt.strftime("%d %b %H:%M")


def _render_cp1_detail(spec: dict, plan: dict) -> html.Div:
    queries = plan.get("queries", [])
    query_items = [
        html.Div([
            html.Span(f"{i+1}. {q.get('label','')}", style={
                "fontWeight": "600", "fontSize": "12px", "color": _T1, "display": "block",
            }),
            html.Span(q.get("purpose", ""), style={
                "fontSize": "11px", "color": _T2, "display": "block", "marginBottom": "4px",
            }),
            html.Pre(q.get("sql", ""), style={
                "fontSize": "11px", "background": "rgba(0,0,0,0.2)",
                "padding": "8px", "borderRadius": "4px", "overflowX": "auto",
                "color": "#a5f3fc", "margin": "0 0 8px", "whiteSpace": "pre-wrap",
            }),
        ])
        for i, q in enumerate(queries)
    ]
    focus = spec.get("focus_areas", [])
    return html.Div([
        html.Div("What the AI understood:", style={
            "fontSize": "11px", "fontWeight": "700", "color": _T2,
            "textTransform": "uppercase", "letterSpacing": "0.7px", "marginBottom": "6px",
        }),
        html.Div([
            html.Span(f"Type: {spec.get('analysis_type','')}  ·  "
                      f"Range: {spec.get('time_range','')}  ·  "
                      f"Focus: {', '.join(focus) if focus else '—'}",
                      style={"fontSize": "12px", "color": _T2}),
        ], style={"marginBottom": "8px"}),
        html.Div(spec.get("summary", ""), style={
            "fontSize": "12px", "color": _T1, "marginBottom": "12px",
            "fontStyle": "italic",
        }),
        html.Div("Planned queries (review before approving):", style={
            "fontSize": "11px", "fontWeight": "700", "color": _T2,
            "textTransform": "uppercase", "letterSpacing": "0.7px", "marginBottom": "8px",
        }),
        *query_items,
    ], style={
        "background": "rgba(0,0,0,0.15)", "borderRadius": "8px",
        "padding": "12px 16px", "margin": "10px 0",
    })


def _render_cp2_detail(data_findings: str) -> html.Div:
    lines = (data_findings or "").split("\n")
    headers = [l for l in lines if l.startswith("## ")]
    summary_lines = []
    for h in headers:
        label = h[3:].strip()
        for next_line in lines[lines.index(h)+1:lines.index(h)+5]:
            if next_line.startswith("Rows:"):
                summary_lines.append(f"· {label} — {next_line.strip()}")
                break
            elif next_line.startswith("No rows"):
                summary_lines.append(f"· {label} — no rows returned")
                break
    preview = "\n".join(summary_lines) if summary_lines else (data_findings or "")[:400]
    return html.Div([
        html.Div("Data gathered (preview):", style={
            "fontSize": "11px", "fontWeight": "700", "color": _T2,
            "textTransform": "uppercase", "letterSpacing": "0.7px", "marginBottom": "8px",
        }),
        html.Pre(preview, style={
            "fontSize": "12px", "color": _T1, "whiteSpace": "pre-wrap",
            "background": "rgba(0,0,0,0.15)", "padding": "10px", "borderRadius": "6px",
            "maxHeight": "200px", "overflowY": "auto",
        }),
    ], style={"margin": "10px 0"})


def _render_log(agent_log: str) -> html.Div | None:
    if not agent_log:
        return None
    lines = (agent_log or "").strip().split("\n")
    last_lines = "\n".join(lines[-8:])  # show last 8 lines
    return html.Div([
        html.Div("Agent log:", style={
            "fontSize": "11px", "color": _T2, "marginBottom": "4px",
        }),
        html.Pre(last_lines, style={
            "fontSize": "11px", "color": "#94a3b8", "whiteSpace": "pre-wrap",
            "background": "rgba(0,0,0,0.15)", "padding": "8px", "borderRadius": "4px",
            "maxHeight": "120px", "overflowY": "auto", "margin": 0,
        }),
    ], style={"margin": "8px 0"})


def _render_queue_row(req: dict) -> html.Div:
    status = req["status"]
    label, color = status_label(status)

    # Detail panel based on status
    detail = None
    if status == STATUS_CP1:
        try:
            spec = json.loads(req.get("intake_spec") or "{}")
            plan = json.loads(req.get("query_plan") or "{}")
            detail = _render_cp1_detail(spec, plan)
        except Exception:
            pass
    elif status == STATUS_CP2:
        detail = _render_cp2_detail(req.get("data_findings", ""))

    # Show log while actively running
    show_log = status in ("running", "researching", "building", STATUS_CP1, STATUS_CP2)
    log_el = _render_log(req.get("agent_log", "")) if show_log else None

    # Action buttons
    btn_style = {
        "border": "none", "borderRadius": "6px", "padding": "6px 14px",
        "fontSize": "12px", "fontWeight": "600", "cursor": "pointer",
    }
    actions = []
    if status == STATUS_PENDING:
        actions.append(html.Button(
            "▶ Run",
            id={"type": "rq-run", "index": req["id"]},
            n_clicks=0,
            style={**btn_style, "background": "#2563EB", "color": "#fff"},
        ))
    elif status == STATUS_CP1:
        actions.append(html.Button(
            "✓ Approve Plan",
            id={"type": "rq-approve", "index": req["id"]},
            n_clicks=0,
            style={**btn_style, "background": "#16a34a", "color": "#fff"},
        ))
    elif status == STATUS_CP2:
        actions.append(html.Button(
            "✓ Approve Build",
            id={"type": "rq-approve", "index": req["id"]},
            n_clicks=0,
            style={**btn_style, "background": "#16a34a", "color": "#fff"},
        ))
    elif status == STATUS_DONE and req.get("report_path"):
        actions.append(html.A(
            "↓ Download",
            href=f"/download-generated?id={req['id']}",
            target="_blank",
            style={
                **btn_style, "background": "#0f172a", "color": "#34d399",
                "border": "1px solid #34d399", "textDecoration": "none",
                "display": "inline-block",
            },
        ))

    if status not in (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED):
        actions.append(html.Button(
            "✕ Cancel",
            id={"type": "rq-cancel", "index": req["id"]},
            n_clicks=0,
            style={**btn_style, "background": "transparent", "color": "#f87171",
                   "border": "1px solid rgba(248,113,113,0.4)", "marginLeft": "6px"},
        ))

    query_preview = req["query_text"]
    if len(query_preview) > 200:
        query_preview = query_preview[:200] + "…"

    return html.Div([
        html.Div([
            html.Span(f"#{req['id']}", style={
                "fontSize": "12px", "fontWeight": "700", "color": _T2,
                "minWidth": "28px",
            }),
            html.Span(req["email"], style={
                "fontSize": "12px", "color": _T1, "fontWeight": "500",
            }),
            html.Span(_fmt_time(req.get("created_at")), style={
                "fontSize": "11px", "color": _T2, "marginLeft": "auto",
            }),
            html.Span(label, style={
                "fontSize": "11px", "fontWeight": "700", "color": color,
                "background": f"{color}1a", "padding": "2px 8px",
                "borderRadius": "999px", "marginLeft": "12px",
            }),
        ], style={
            "display": "flex", "alignItems": "center", "gap": "10px",
            "marginBottom": "6px",
        }),
        html.Div(query_preview, style={
            "fontSize": "12px", "color": _T2, "lineHeight": "1.5",
            "marginBottom": "4px" if (detail or log_el or actions) else "0",
        }),
        detail,
        log_el,
        html.Div(actions, style={"marginTop": "10px", "display": "flex", "gap": "6px"})
        if actions else None,
    ], style={
        "background": _CD, "border": f"1px solid {_BD}",
        "borderRadius": "10px", "padding": "14px 18px",
        "marginBottom": "8px",
    })


# ── Layout ─────────────────────────────────────────────────────────────────────

layout = html.Div([
    html.Div([
        html.Div("REPORTS", style={
            "fontSize": "11px", "fontWeight": "800", "color": _PU,
            "letterSpacing": "2px", "marginBottom": "4px",
        }),
        html.H1("Analytics & Reports", style={
            "fontSize": "26px", "fontWeight": "700", "color": _T1,
            "margin": "0 0 6px",
        }),
        html.Div(
            "Download sprint reports or request a custom analysis from the agent pipeline.",
            style={"fontSize": "13px", "color": _T2, "marginBottom": "32px"},
        ),
    ]),

    # ── Section 1: Sprint report download ─────────────────────────────────────
    html.Div([
        html.Div("Sprint Iteration Reports", style={
            "fontSize": "14px", "fontWeight": "700", "color": _T1, "marginBottom": "16px",
        }),
        html.Div([
            dcc.Dropdown(
                id="rpt-sprint-select",
                options=_available_sprints(),
                value=None,
                clearable=False,
                placeholder="Choose a sprint…",
                className="dark-dropdown",
                style={"width": "260px", "fontSize": "13px"},
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
        html.Div(id="rpt-info", style={"marginTop": "10px", "fontSize": "12px", "color": _T2}),
    ], style={
        "background": _CD, "border": f"1px solid {_BD}",
        "borderRadius": "12px", "padding": "24px 28px", "marginBottom": "24px",
    }),

    # ── Section 2: Request custom analysis ────────────────────────────────────
    html.Div([
        html.Div("Request Custom Analysis", style={
            "fontSize": "14px", "fontWeight": "700", "color": _T1, "marginBottom": "6px",
        }),
        html.Div(
            "Describe what you want to know. The agent pipeline will gather the data and build a report.",
            style={"fontSize": "12px", "color": _T2, "marginBottom": "16px"},
        ),
        dcc.Textarea(
            id="rq-query-input",
            placeholder=(
                "e.g. Show me bug trends for Q2 2026, broken down by developer and priority. "
                "I want to know which devs are resolving bugs fastest and what P1/P2s are still open."
            ),
            style={
                "width": "100%", "height": "90px", "fontSize": "13px",
                "background": "var(--bg-primary)", "color": _T1,
                "border": f"1px solid {_BD}", "borderRadius": "8px",
                "padding": "10px 14px", "resize": "vertical", "outline": "none",
                "fontFamily": "Inter, sans-serif",
            },
        ),
        html.Div([
            dcc.Input(
                id="rq-email-input",
                type="email",
                placeholder="your.email@company.com",
                style={
                    "fontSize": "13px", "background": "var(--bg-primary)", "color": _T1,
                    "border": f"1px solid {_BD}", "borderRadius": "8px",
                    "padding": "9px 14px", "outline": "none", "width": "280px",
                    "fontFamily": "Inter, sans-serif",
                },
            ),
            html.Button(
                "Submit Request",
                id="rq-submit-btn",
                n_clicks=0,
                style={
                    "background": _PU, "color": "#fff", "border": "none",
                    "borderRadius": "8px", "padding": "9px 22px",
                    "fontSize": "13px", "fontWeight": "600", "cursor": "pointer",
                },
            ),
        ], style={"display": "flex", "gap": "10px", "alignItems": "center", "marginTop": "10px"}),
        html.Div(id="rq-submit-status", style={"marginTop": "10px", "fontSize": "12px"}),
    ], style={
        "background": _CD, "border": f"1px solid {_BD}",
        "borderRadius": "12px", "padding": "24px 28px", "marginBottom": "24px",
    }),

    # ── Section 3: Admin queue ─────────────────────────────────────────────────
    html.Div([
        html.Div([
            html.Div("Request Queue", style={
                "fontSize": "14px", "fontWeight": "700", "color": _T1,
            }),
            html.Div("Auto-refreshes every 8 s", style={
                "fontSize": "11px", "color": _T2,
            }),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "center", "marginBottom": "16px"}),
        html.Div(id="rq-queue-panel",
                 children=[html.Div("Loading…", style={"fontSize": "13px", "color": _T2})]),
    ], style={
        "background": _CD, "border": f"1px solid {_BD}",
        "borderRadius": "12px", "padding": "24px 28px",
    }),

    # Hidden plumbing
    dcc.Interval(id="rq-queue-poll", interval=8000, n_intervals=0),
    dcc.Store(id="rq-refresh-store", data=0),

], style={"padding": "28px 32px", "maxWidth": "900px", "margin": "0 auto"})


# ── Callbacks ──────────────────────────────────────────────────────────────────

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
        f"Clicking Download will generate the {month_name} report from live data.",
    )


@callback(
    Output("rq-submit-status", "children"),
    Output("rq-refresh-store", "data"),
    Input("rq-submit-btn", "n_clicks"),
    State("rq-query-input", "value"),
    State("rq-email-input", "value"),
    State("rq-refresh-store", "data"),
    prevent_initial_call=True,
)
def _submit_request(n_clicks, query, email, refresh_counter):
    if not query or not query.strip():
        return html.Span("Query cannot be empty.", style={"color": "#f87171"}), no_update
    if not email or "@" not in email:
        return html.Span("Enter a valid email address.", style={"color": "#f87171"}), no_update
    try:
        req_id = add_request(email.strip(), query.strip())
        return (
            html.Span(f"✓ Request #{req_id} submitted. It will appear in the queue below.",
                      style={"color": "#34d399"}),
            (refresh_counter or 0) + 1,
        )
    except Exception as e:
        return html.Span(f"Error: {e}", style={"color": "#f87171"}), no_update


@callback(
    Output("rq-queue-panel", "children"),
    Input("rq-queue-poll", "n_intervals"),
    Input("rq-refresh-store", "data"),
)
def _refresh_queue(n, _refresh):
    try:
        requests = get_all_requests()
    except Exception as e:
        return html.Div(f"Error loading queue: {e}", style={"color": "#f87171", "fontSize": "13px"})
    if not requests:
        return html.Div(
            "No requests yet. Submit one above.",
            style={"fontSize": "13px", "color": _T2, "padding": "8px 0"},
        )
    return [_render_queue_row(r) for r in requests]


@callback(
    Output("rq-refresh-store", "data", allow_duplicate=True),
    Input({"type": "rq-run", "index": ALL}, "n_clicks"),
    State("rq-refresh-store", "data"),
    prevent_initial_call=True,
)
def _handle_run(clicks, refresh_counter):
    ctx = callback_context
    if not ctx.triggered or not ctx.triggered_id:
        return no_update
    n = ctx.triggered[0].get("value") or 0
    if not n:
        return no_update
    req_id = ctx.triggered_id["index"]
    from agents.pipeline import start_pipeline
    started = start_pipeline(req_id)
    if started:
        set_field(req_id, status="running")
    return (refresh_counter or 0) + 1


@callback(
    Output("rq-refresh-store", "data", allow_duplicate=True),
    Input({"type": "rq-approve", "index": ALL}, "n_clicks"),
    State("rq-refresh-store", "data"),
    prevent_initial_call=True,
)
def _handle_approve(clicks, refresh_counter):
    ctx = callback_context
    if not ctx.triggered or not ctx.triggered_id:
        return no_update
    n = ctx.triggered[0].get("value") or 0
    if not n:
        return no_update
    req_id = ctx.triggered_id["index"]
    r = get_request(req_id)
    if not r:
        return no_update
    if r["status"] == STATUS_CP1:
        set_field(req_id, status=STATUS_CP1_OK)
    elif r["status"] == STATUS_CP2:
        set_field(req_id, status=STATUS_CP2_OK)
    return (refresh_counter or 0) + 1


@callback(
    Output("rq-refresh-store", "data", allow_duplicate=True),
    Input({"type": "rq-cancel", "index": ALL}, "n_clicks"),
    State("rq-refresh-store", "data"),
    prevent_initial_call=True,
)
def _handle_cancel(clicks, refresh_counter):
    ctx = callback_context
    if not ctx.triggered or not ctx.triggered_id:
        return no_update
    n = ctx.triggered[0].get("value") or 0
    if not n:
        return no_update
    req_id = ctx.triggered_id["index"]
    set_field(req_id, status=STATUS_CANCELLED)
    return (refresh_counter or 0) + 1
