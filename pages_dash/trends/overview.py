"""Overview — Monday-morning glance across every stream"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

import dash
import pandas as pd
from dash import html
from sqlalchemy import text

from config.dev_capacity import DEVELOPERS
from data.loader import engine

dash.register_page(__name__, path="/overview", name="Overview")

_OPEN_STATES = frozenset([
    "New", "Request Estimate", "Estimated", "Clarification",
    "Active", "Dev InProgress", "Dev Review", "Dev Complete",
    "reopened",
])
_ENH_TYPES   = {"Enhancement", "User Story"}
_ISSUE_TYPES = {"Bug", "Bug_UI", "Bug_Text"}
_CAP_H       = 180
_MONO        = "'JetBrains Mono','SF Mono',monospace"

_BG_CARD = "rgb(18,22,31)"
_BD_COL  = "rgb(38,44,58)"
_MT      = "rgb(139,146,164)"
_DIM     = "rgb(91,98,118)"


def _kpi(label, value, suffix="", color="rgb(234,236,242)", href=None):
    card = html.Div([
        html.Div(label, style={
            "fontSize": "9.5px", "fontWeight": "700", "color": _MT,
            "textTransform": "uppercase", "letterSpacing": "0.6px",
            "marginBottom": "7px",
        }),
        html.Div([
            html.Span(str(value), style={
                "fontSize": "26px", "fontWeight": "700",
                "color": color, "fontFamily": _MONO, "lineHeight": "1",
            }),
            *([ html.Span(suffix, style={
                "fontSize": "11px", "color": _DIM, "marginLeft": "5px",
            })] if suffix else []),
        ], style={"display": "flex", "alignItems": "baseline", "gap": "5px"}),
    ], style={
        "background": _BG_CARD, "border": f"1px solid {_BD_COL}",
        "borderRadius": "11px", "padding": "13px 15px",
    })
    if href:
        return html.A(card, href=href, style={"textDecoration": "none"})
    return card


def _section(label, dot_color, cards):
    return html.Div([
        html.Div([
            html.Span(style={
                "width": "7px", "height": "7px", "borderRadius": "2px",
                "background": dot_color, "display": "inline-block",
                "marginRight": "8px", "flexShrink": "0",
            }),
            html.Span(label, style={
                "fontSize": "11px", "fontWeight": "700", "color": _MT,
                "textTransform": "uppercase", "letterSpacing": "0.6px",
            }),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
        html.Div(cards, style={
            "display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "12px",
        }),
    ], style={"marginBottom": "20px"})


def layout(**_):
    today = date.today()
    _, days_in_month = monthrange(today.year, today.month)
    ym_str     = today.strftime("%Y-%m")
    sprint_ctx = f"{today.strftime('%b %Y')} · Sprint 1 · Day {today.day} / {days_in_month}"

    # ── Bugs query — uses confirmed open-state allowlist ──────────────────────
    _OPEN_IN = (
        "'New','Request Estimate','Estimated','Clarification',"
        "'Active','Dev InProgress','Dev Review','Dev Complete',"
        "'reopened'"
    )
    try:
        with engine.connect() as conn:
            bugs_df = pd.read_sql(text(f"""
                SELECT work_item_id, priority,
                       COALESCE(assigned_to, '') AS assigned_to
                FROM work_items_main
                WHERE work_item_type IN ('Bug','Bug_UI','Bug_Text')
                  AND state IN ({_OPEN_IN})
            """), conn)
    except Exception:
        bugs_df = pd.DataFrame(columns=["work_item_id", "priority", "assigned_to"])

    bugs_df["priority"] = pd.to_numeric(bugs_df["priority"], errors="coerce").fillna(4).astype(int)
    open_p1    = int((bugs_df["priority"] == 1).sum())
    open_p2    = int((bugs_df["priority"] == 2).sum())
    unassigned = int(
        ((bugs_df["assigned_to"].str.strip() == "") |
         (bugs_df["assigned_to"].isna())).sum()
    )

    # ── Enhancements query — separate, uses its own closed-state exclusion ─────
    _ENH_CLOSED = (
        "'Resolved','Closed','Not an issue','Not Required',"
        "'No Customer Response','Userstory Update'"
    )
    try:
        with engine.connect() as conn:
            enh_df = pd.read_sql(text(f"""
                SELECT work_item_id, work_item_type, state,
                       COALESCE(release_date, '') AS release_date,
                       COALESCE(original_estimate, 0) AS original_estimate
                FROM work_items_main
                WHERE work_item_type IN ('Enhancement','User Story')
                  AND state NOT IN ({_ENH_CLOSED})
            """), conn)
    except Exception:
        enh_df = pd.DataFrame(columns=[
            "work_item_id", "work_item_type", "state", "release_date", "original_estimate",
        ])

    # Stories ready
    try:
        with engine.connect() as conn:
            gate_rows = conn.execute(text(
                "SELECT work_item_id FROM p_planning_gates WHERE sn_signoff = TRUE"
            )).fetchall()
        signed_off_ids = {r[0] for r in gate_rows}
    except Exception:
        signed_off_ids = set()

    open_stories  = enh_df[enh_df["work_item_type"] == "User Story"]
    stories_ready = int(open_stories["work_item_id"].isin(signed_off_ids).sum())
    stories_total = len(open_stories)

    open_enh = enh_df[enh_df["work_item_type"].isin(_ENH_TYPES)]
    stuck    = int((open_enh["state"] == "Active").sum())
    in_pipe  = int((open_enh["release_date"].str.strip() != "").sum())

    # Capacity
    known_devs   = {d["name"] for d in DEVELOPERS}
    total_cap_h  = len(DEVELOPERS) * _CAP_H
    try:
        with engine.connect() as conn:
            cap_rows = conn.execute(text("""
                SELECT main_developer, SUM(estimated_hours) AS total_h
                FROM agg_dev_monthly_capacity
                WHERE ym_str = :ym
                  AND main_developer IS NOT NULL
                GROUP BY main_developer
            """), {"ym": ym_str}).fetchall()
    except Exception:
        cap_rows = []

    dev_assigned     = {dev: float(h or 0) for dev, h in cap_rows if dev in known_devs}
    total_assigned_h = sum(dev_assigned.values())
    cap_pct          = round(total_assigned_h / total_cap_h * 100) if total_cap_h else 0
    over_cap         = sum(1 for h in dev_assigned.values() if h > _CAP_H)

    try:
        with engine.connect() as conn:
            oh_row = conn.execute(text("""
                SELECT COALESCE(SUM(total_hours), 0)
                FROM agg_standalone_overhead WHERE ym_str = :ym
            """), {"ym": ym_str}).scalar()
        overhead_h = float(oh_row or 0)
    except Exception:
        overhead_h = 0.0

    overhead_pct = round(overhead_h / total_cap_h * 100) if total_cap_h else 0
    avg_story_h  = round(float(open_stories["original_estimate"].mean())) if not open_stories.empty else 0
    n_devs       = len(DEVELOPERS)

    # Colors
    C_GREEN  = "rgb(70,194,142)"
    C_AMBER  = "rgb(224,162,60)"
    C_RED    = "rgb(239,110,99)"
    C_CYAN   = "rgb(63,182,201)"
    C_INDIGO = "rgb(110,118,241)"
    C_SALMON = "rgb(240,137,122)"
    C_GRAY   = _MT

    stories_color = C_GREEN if stories_total and (stories_ready / stories_total) >= 0.5 else C_RED
    cap_color     = C_RED if cap_pct > 95 else C_AMBER if cap_pct > 80 else C_INDIGO

    return html.Div([
        # ── Page header bar ──────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div([
                    html.H1("Overview", style={
                        "fontSize": "21px", "fontWeight": "700", "margin": "0",
                        "color": "rgb(234,236,242)",
                    }),
                    html.Span("Built", style={
                        "fontSize": "10px", "fontWeight": "700",
                        "padding": "3px 9px", "borderRadius": "20px",
                        "textTransform": "uppercase", "letterSpacing": "0.5px",
                        "background": "rgba(70,194,142,0.118)",
                        "color": C_GREEN,
                        "border": "1px solid rgba(70,194,142,0.333)",
                    }),
                ], style={"display": "flex", "alignItems": "center", "gap": "12px"}),
                html.Div("Monday-morning glance across every stream", style={
                    "fontSize": "12.5px", "color": _MT, "marginTop": "6px",
                }),
            ]),
            html.Div(sprint_ctx, style={
                "fontSize": "11px", "color": _DIM, "fontFamily": _MONO,
                "background": "rgb(23,28,40)", "border": f"1px solid {_BD_COL}",
                "borderRadius": "8px", "padding": "7px 11px", "whiteSpace": "nowrap",
            }),
        ], style={
            "padding": "18px 26px", "borderBottom": f"1px solid {_BD_COL}",
            "display": "flex", "justifyContent": "space-between", "alignItems": "flex-start",
            "background": "rgb(18,22,31)",
        }),

        # ── Main content ─────────────────────────────────────────────────────
        html.Div([
            html.Div([
                "Headline numbers pulled from each screen below — the single view before drilling in. "
                "Work the screens ",
                html.B("bottom-up to decide", style={"color": "rgb(234,236,242)"}),
                " (capacity, then bugs, then enhancements) and ",
                html.B("top-down to track", style={"color": "rgb(234,236,242)"}),
                ". Numbers refresh on page load.",
            ], style={
                "fontSize": "12.5px", "color": _MT, "marginBottom": "18px",
                "maxWidth": "760px", "lineHeight": "1.6",
            }),

            _section("Enhancements", "rgb(139,124,240)", [
                _kpi("Stories ready",       f"{stories_ready}", suffix=f"/ {stories_total}", color=stories_color, href="/planning"),
                _kpi("Stuck in gates",      stuck,  color=C_AMBER  if stuck    > 0 else C_GREEN, href="/planning"),
                _kpi("Design at-risk",      "—",    color=_MT),
                _kpi("In release pipeline", in_pipe, color=C_CYAN,  href="/release-status"),
            ]),

            _section("Bugs & Issues", "rgb(240,137,122)", [
                _kpi("Open P1",    open_p1,    color=C_RED    if open_p1    > 0 else C_GREEN, href="/issue-planning"),
                _kpi("P2",         open_p2,    color=C_AMBER  if open_p2    > 0 else C_GREEN, href="/issue-planning"),
                _kpi("Unassigned", unassigned, color=C_SALMON if unassigned > 0 else C_GREEN, href="/issue-planning"),
                _kpi("Over cap",   over_cap,   suffix="dev",  color=C_GREEN if over_cap == 0 else C_RED, href="/dev-capacity"),
            ]),

            _section("Capacity", "rgb(63,182,201)", [
                _kpi("Team capacity used", cap_pct,      suffix="%",   color=cap_color,  href="/dev-capacity"),
                _kpi("Admin overhead",     overhead_pct, suffix="%",   color=C_AMBER if overhead_pct > 20 else C_GREEN, href="/admin-hours"),
                _kpi("Hours for stories",  avg_story_h,  suffix="avg", color=C_GREEN,    href="/planning"),
                _kpi("Developers",         n_devs,                     color=C_GRAY,     href="/dev-capacity"),
            ]),

        ], style={"padding": "22px 26px", "flex": "1", "overflowY": "auto"}),

    ], style={
        "display": "flex", "flexDirection": "column",
        "minHeight": "100vh", "background": "rgb(10,13,21)",
    })
