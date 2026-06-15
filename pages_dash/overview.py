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

_CLOSED = frozenset([
    "Resolved", "Closed", "Not an issue", "Not Required",
    "No Customer Response", "Userstory Update",
])
_ENH_TYPES   = {"Enhancement", "User Story"}
_ISSUE_TYPES = {"Bug", "Bug_UI", "Bug_Text"}
_ALL_TYPES   = _ENH_TYPES | _ISSUE_TYPES

_CARD = "var(--bg-elevated)"
_BD   = "var(--border)"
_MT   = "var(--text-secondary)"
_TXT  = "var(--text-primary)"
_CAP_H = 180  # default capacity per developer per month


# ── KPI card ──────────────────────────────────────────────────────────────────

def _kpi(label, value, suffix="", color="#e2e8f0", href=None):
    content = html.Div([
        html.Div(label, style={
            "fontSize": "10px", "fontWeight": "700", "color": _MT,
            "letterSpacing": "0.08em", "textTransform": "uppercase",
            "marginBottom": "14px",
        }),
        html.Div([
            html.Span(str(value), style={
                "fontSize": "34px", "fontWeight": "700",
                "color": color, "lineHeight": "1",
            }),
            *([ html.Span(f" {suffix}", style={
                "fontSize": "13px", "color": _MT,
                "marginLeft": "3px", "fontWeight": "500",
            })] if suffix else []),
        ]),
    ], style={
        "background": _CARD, "border": f"1px solid {_BD}",
        "borderRadius": "10px", "padding": "18px 20px",
        "flex": "1", "minWidth": "0", "height": "100%",
        "transition": "border-color 0.15s",
    })
    if href:
        return html.A(content, href=href, style={
            "textDecoration": "none", "flex": "1", "minWidth": "0",
        })
    return html.Div(content, style={"flex": "1", "minWidth": "0"})


def _section(label, dot_color, cards):
    return html.Div([
        html.Div([
            html.Span(style={
                "width": "8px", "height": "8px", "borderRadius": "50%",
                "background": dot_color, "display": "inline-block",
                "marginRight": "8px", "flexShrink": "0",
            }),
            html.Span(label, style={
                "fontSize": "11px", "fontWeight": "700", "color": _MT,
                "letterSpacing": "0.10em",
            }),
        ], style={
            "display": "flex", "alignItems": "center",
            "marginBottom": "12px",
        }),
        html.Div(cards, style={
            "display": "flex", "gap": "12px", "flexWrap": "wrap",
        }),
    ], style={"marginBottom": "28px"})


# ── Layout (queries run lazily on navigation) ─────────────────────────────────

def layout(**_):
    today = date.today()
    _, days_in_month = monthrange(today.year, today.month)
    ym_str = today.strftime("%Y-%m")
    sprint_ctx = f"{today.strftime('%b %Y')}  ·  Day {today.day} / {days_in_month}"

    # ── ADO items query ────────────────────────────────────────────────────────
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT work_item_id, work_item_type, state, priority,
                       COALESCE(assigned_to, '') AS assigned_to,
                       COALESCE(release_date,  '') AS release_date,
                       COALESCE(original_estimate, 0) AS original_estimate
                FROM work_items_main
                WHERE work_item_type IN
                      ('Bug','Bug_UI','Bug_Text','Enhancement','User Story')
            """), conn)
    except Exception:
        df = pd.DataFrame(columns=[
            "work_item_id", "work_item_type", "state", "priority",
            "assigned_to", "release_date", "original_estimate",
        ])

    df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(4).astype(int)
    is_closed = df["state"].isin(_CLOSED)

    # ── Stories ready (User Stories with sn_signoff complete) ─────────────────
    try:
        with engine.connect() as conn:
            gate_rows = conn.execute(text(
                "SELECT work_item_id FROM p_planning_gates WHERE sn_signoff = TRUE"
            )).fetchall()
        signed_off_ids = {r[0] for r in gate_rows}
    except Exception:
        signed_off_ids = set()

    open_stories = df[
        (df["work_item_type"] == "User Story") & (~is_closed)
    ]
    stories_ready = int(open_stories["work_item_id"].isin(signed_off_ids).sum())
    stories_total = len(open_stories)

    # ── Enhancements ──────────────────────────────────────────────────────────
    open_enh = df[df["work_item_type"].isin(_ENH_TYPES) & (~is_closed)]
    stuck    = int((open_enh["state"] == "Active").sum())
    in_pipe  = int(
        (open_enh["release_date"].str.strip() != "").sum()
    )

    # ── Bugs & Issues ─────────────────────────────────────────────────────────
    open_iss  = df[df["work_item_type"].isin(_ISSUE_TYPES) & (~is_closed)]
    open_p1   = int((open_iss["priority"] == 1).sum())
    open_p2   = int((open_iss["priority"] == 2).sum())
    unassigned = int(
        ((open_iss["assigned_to"].str.strip() == "") |
         (open_iss["assigned_to"].isna())).sum()
    )

    # ── Capacity ──────────────────────────────────────────────────────────────
    total_cap_h = len(DEVELOPERS) * _CAP_H  # e.g. 11 × 180 = 1980

    try:
        with engine.connect() as conn:
            gantt_rows = conn.execute(text("""
                SELECT main_developer,
                       SUM(COALESCE(original_estimate, 0)) AS total_h
                FROM agg_gantt_items
                WHERE '2026-' || LPAD(month_num::TEXT, 2, '0') = :ym
                  AND main_developer IS NOT NULL
                GROUP BY main_developer
            """), {"ym": ym_str}).fetchall()
    except Exception:
        gantt_rows = []

    dev_assigned: dict[str, float] = {}
    for dev, h in gantt_rows:
        dev_assigned[dev] = float(h or 0)

    total_assigned_h = sum(dev_assigned.values())
    cap_pct = round(total_assigned_h / total_cap_h * 100) if total_cap_h else 0
    over_cap = sum(1 for h in dev_assigned.values() if h > _CAP_H)

    try:
        with engine.connect() as conn:
            oh_row = conn.execute(text("""
                SELECT COALESCE(SUM(total_hours), 0)
                FROM agg_standalone_overhead
                WHERE ym_str = :ym
            """), {"ym": ym_str}).scalar()
        overhead_h = float(oh_row or 0)
    except Exception:
        overhead_h = 0.0

    overhead_pct = round(overhead_h / total_cap_h * 100) if total_cap_h else 0

    avg_story_h = round(
        float(open_stories["original_estimate"].mean())
    ) if not open_stories.empty else 0

    n_devs = len(DEVELOPERS)

    # ── Colour helpers ────────────────────────────────────────────────────────
    G  = "var(--green)"
    AM = "var(--amber)"
    RE = "var(--red)"
    BL = "var(--blue)"
    PU = "var(--purple)"

    stories_ready_color = G if stories_total and (stories_ready / stories_total) >= 0.5 else RE
    cap_color = (
        RE if cap_pct > 95 else AM if cap_pct > 80 else G
    )

    # ── Assemble ──────────────────────────────────────────────────────────────
    return html.Div([
        # Sprint context chip (top right)
        html.Div(sprint_ctx, style={
            "position": "absolute", "top": "36px", "right": "40px",
            "fontSize": "12px", "color": _MT,
            "background": _CARD, "border": f"1px solid {_BD}",
            "borderRadius": "8px", "padding": "5px 14px",
        }),

        html.Div("EOD · PLANNING", style={
            "fontSize": "10px", "fontWeight": "700", "color": PU,
            "letterSpacing": "0.12em", "marginBottom": "10px",
        }),
        html.Div([
            html.Div("Overview", style={
                "fontSize": "30px", "fontWeight": "700", "color": _TXT,
                "display": "inline", "marginRight": "12px",
            }),
            html.Span("BUILT", style={
                "fontSize": "11px", "fontWeight": "700", "color": G,
                "background": "rgba(52,211,153,0.13)",
                "border": "1px solid rgba(52,211,153,0.35)",
                "borderRadius": "6px", "padding": "3px 10px",
                "verticalAlign": "middle",
            }),
        ], style={"marginBottom": "6px"}),
        html.Div("Monday-morning glance across every stream", style={
            "fontSize": "13px", "color": _MT, "marginBottom": "14px",
        }),
        html.P([
            "Headline numbers pulled from each screen below — the single view before drilling in. "
            "Work the screens ",
            html.Strong("bottom-up to decide"),
            " (capacity, then bugs, then enhancements) and ",
            html.Strong("top-down to track"),
            ".",
        ], style={
            "fontSize": "13px", "color": _MT, "lineHeight": "1.7",
            "marginBottom": "36px",
        }),

        # ── ENHANCEMENTS ──────────────────────────────────────────────────────
        _section("ENHANCEMENTS", PU, [
            _kpi("Stories Ready",
                 f"{stories_ready}",
                 suffix=f"/ {stories_total}",
                 color=stories_ready_color,
                 href="/planning"),
            _kpi("Stuck in Gates", stuck,
                 color=AM if stuck > 0 else G,
                 href="/planning"),
            _kpi("Design At-Risk", "—",
                 color=_MT),
            _kpi("In Release Pipeline", in_pipe,
                 color=BL,
                 href="/release-status"),
        ]),

        # ── BUGS & ISSUES ─────────────────────────────────────────────────────
        _section("BUGS & ISSUES", RE, [
            _kpi("Open P1", open_p1,
                 color=RE if open_p1 > 0 else G,
                 href="/issue-planning"),
            _kpi("P2", open_p2,
                 color=AM if open_p2 > 0 else G,
                 href="/issue-planning"),
            _kpi("Unassigned", unassigned,
                 color=AM if unassigned > 0 else G,
                 href="/issue-planning"),
            _kpi("Over Cap", over_cap,
                 suffix="dev" if over_cap != 1 else "dev",
                 color=RE if over_cap > 0 else G,
                 href="/dev-capacity"),
        ]),

        # ── CAPACITY ──────────────────────────────────────────────────────────
        _section("CAPACITY", BL, [
            _kpi("Team Capacity Used", cap_pct,
                 suffix="%",
                 color=cap_color,
                 href="/dev-capacity"),
            _kpi("Admin Overhead", overhead_pct,
                 suffix="%",
                 color=AM if overhead_pct > 20 else G,
                 href="/admin-hours"),
            _kpi("Hours for Stories", avg_story_h,
                 suffix="avg",
                 color=_TXT,
                 href="/planning"),
            _kpi("Developers", n_devs,
                 color=BL,
                 href="/dev-capacity"),
        ]),

    ], style={"padding": "36px 40px", "position": "relative", "maxWidth": "1400px"})
