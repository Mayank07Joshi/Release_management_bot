"""
pages_dash/misc/release_audit.py
──────────────────────────────────
Release Audit page — post-release quality and delivery review.
Dynamic: user picks a release_date tag; content rebuilds via callback.
"""
from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html, no_update

from db.release_audit import get_release_audit_data, get_release_options, get_release_trend

dash.register_page(__name__, path="/release-audit", name="Release Audit")

# ── Palette (explicit, no CSS-var dependency) ─────────────────────────────────
_BG      = "rgb(10,13,21)"
_CARD    = "rgb(18,22,31)"
_RAISED  = "rgb(23,28,40)"
_BD      = "rgb(38,44,58)"
_T1      = "rgb(234,236,242)"
_T2      = "rgb(180,186,200)"
_T3      = "rgb(139,146,164)"
_DIM     = "rgb(91,98,118)"
_MONO    = "'DM Mono','JetBrains Mono','SF Mono',monospace"

_RED     = "rgb(239,110,99)"
_AMBER   = "rgb(224,162,60)"
_GREEN   = "rgb(70,194,142)"
_INDIGO  = "rgb(110,118,241)"
_CYAN    = "rgb(63,182,201)"
_PURPLE  = "rgb(168,130,255)"

_P_COLOR = {1: _RED, 2: _AMBER, 3: _INDIGO, 4: _DIM}
_P_BG    = {
    1: "rgba(239,110,99,.08)",
    2: "rgba(224,162,60,.08)",
    3: "rgba(110,118,241,.08)",
    4: "rgba(91,98,118,.06)",
}


# ── Primitive components ───────────────────────────────────────────────────────

def _label(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize": "9px", "textTransform": "uppercase",
        "letterSpacing": "0.07em", "color": _T3, "fontWeight": "600",
    })


def _section_header(letter: str, title: str,
                    badge_text: str = "", badge_color: str = _GREEN) -> html.Div:
    badge = html.Span([
        html.Span("●", style={"fontSize": "7px", "marginRight": "5px", "color": badge_color}),
        badge_text,
    ], style={
        "fontSize": "9.5px", "fontWeight": "600", "color": badge_color,
        "background": f"{badge_color}18",
        "border": f"0.5px solid {badge_color}55",
        "padding": "3px 10px", "borderRadius": "20px", "letterSpacing": "0.03em",
    }) if badge_text else html.Span()

    return html.Div([
        html.Span(letter, style={
            "fontSize": "10px", "color": _DIM, "fontFamily": _MONO, "marginRight": "8px",
        }),
        html.Span(title, style={
            "fontSize": "14px", "fontWeight": "600", "color": _T1,
        }),
        html.Span(style={"flex": "1"}),
        badge,
    ], style={
        "display": "flex", "alignItems": "center", "gap": "4px",
        "marginBottom": "16px", "paddingBottom": "12px",
        "borderBottom": f"1px solid {_BD}",
    })


def _card(*children, style=None) -> html.Div:
    base = {
        "background": _CARD, "border": f"1px solid {_BD}",
        "borderRadius": "10px", "overflow": "hidden",
    }
    if style:
        base.update(style)
    return html.Div(list(children), style=base)


def _card_header(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize": "9px", "textTransform": "uppercase",
        "letterSpacing": "0.07em", "color": _T3, "fontWeight": "600",
        "padding": "8px 14px", "borderBottom": f"1px solid {_BD}",
        "background": _RAISED,
    })


# ── KPI Strip ─────────────────────────────────────────────────────────────────

def _kpi_strip(d: dict) -> html.Div:
    del_pct   = d["delivery_pct"]
    del_col   = _RED if del_pct < 50 else _AMBER if del_pct < 80 else _GREEN
    p1_col    = _RED if d["p1_open"] > 0 else _T1
    bcl_col   = _GREEN if d["bug_close_pct"] >= 80 else _AMBER
    fixed_col = _GREEN if d["bugs_fixed_total"] > 0 else _DIM

    def _cell(val, lbl, color, last=False):
        return html.Div([
            html.Div(val, style={
                "fontSize": "28px", "fontWeight": "700", "color": color,
                "fontFamily": _MONO, "lineHeight": "1", "marginBottom": "6px",
                "letterSpacing": "-0.5px",
            }),
            html.Div(lbl, style={
                "fontSize": "9px", "textTransform": "uppercase",
                "letterSpacing": "0.07em", "color": _T3, "fontWeight": "600",
            }),
        ], style={
            "flex": "1", "padding": "18px 20px",
            **({} if last else {"borderRight": f"1px solid {_BD}"}),
        })

    def _group_label(text, accent):
        return html.Div([
            html.Span("●", style={"color": accent, "fontSize": "7px", "marginRight": "6px"}),
            text,
        ], style={
            "fontSize": "9px", "textTransform": "uppercase", "letterSpacing": "0.08em",
            "fontWeight": "700", "color": accent,
            "padding": "7px 16px", "borderBottom": f"1px solid {_BD}",
            "background": _RAISED,
        })

    deliveries = _card(
        _group_label("Deliveries", _GREEN),
        html.Div([
            _cell(str(d["enh_total"]),         "Planned",       _T1),
            _cell(str(d["enh_closed"]),         "Shipped",       _GREEN if d["enh_closed"] > 0 else _DIM),
            _cell(f"{del_pct}%",               "Delivery Rate", del_col),
            _cell(str(d["bugs_fixed_total"]),   "Bugs Fixed",    fixed_col, last=True),
        ], style={"display": "flex"}),
        style={"flex": "3", "marginRight": "12px"},
    )

    discoveries = _card(
        _group_label("Discoveries", _AMBER),
        html.Div([
            _cell(str(d["bug_total"]),      "Bugs Raised", _AMBER if d["bug_total"] > 0 else _DIM),
            _cell(str(d["p1_open"]),        "P1 Open",     p1_col),
            _cell(f"{d['bug_close_pct']}%", "Close Rate",  bcl_col, last=True),
        ], style={"display": "flex"}),
        style={"flex": "2"},
    )

    return html.Div([deliveries, discoveries],
                    style={"display": "flex", "marginBottom": "24px"})


# ── Priority block (big numbers) ──────────────────────────────────────────────

def _priority_block(counts: dict, title: str = "BY PRIORITY") -> html.Div:
    def _p(p, last=False):
        n   = counts.get(p, 0)
        col = _P_COLOR[p]
        bg  = _P_BG[p]
        return html.Div([
            html.Div(f"P{p}", style={
                "fontSize": "10px", "fontWeight": "700", "color": col,
                "letterSpacing": "0.05em", "marginBottom": "8px",
            }),
            html.Div(str(n), style={
                "fontSize": "36px", "fontWeight": "700", "color": col,
                "fontFamily": _MONO, "lineHeight": "1",
            }),
        ], style={
            "flex": "1", "padding": "18px 20px", "background": bg,
            "textAlign": "center",
            **({} if last else {"borderRight": f"1px solid {_BD}"}),
        })

    return _card(
        _card_header(title),
        html.Div([_p(1), _p(2), _p(3), _p(4, last=True)], style={"display": "flex"}),
        style={"flex": "1"},
    )


# ── Horizontal bar chart ──────────────────────────────────────────────────────

def _bar_chart(title: str, items: list[tuple[str, int]], color: str,
               max_rows: int = 10) -> html.Div:
    if not items:
        return _card(
            _card_header(title),
            html.Div("—", style={"padding": "14px", "color": _DIM, "fontSize": "12px"}),
            style={"flex": "1"},
        )

    total   = sum(c for _, c in items[:max_rows]) or 1
    rows    = []
    for i, (lbl, cnt) in enumerate(items[:max_rows]):
        pct     = round(cnt / total * 100)
        is_last = (i == len(items[:max_rows]) - 1)
        rows.append(html.Div([
            html.Div(lbl, style={
                "fontSize": "11.5px", "color": _T2,
                "width": "130px", "flexShrink": "0",
                "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
            }),
            html.Div([
                html.Div(style={
                    "width": f"{min(pct, 100)}%", "height": "100%",
                    "background": color, "borderRadius": "2px",
                    "transition": "width 0.4s ease",
                }),
            ], style={
                "flex": "1", "height": "8px", "background": _BD,
                "borderRadius": "2px", "overflow": "hidden", "margin": "0 12px",
            }),
            html.Div([
                html.Span(str(cnt), style={
                    "fontSize": "12px", "fontWeight": "700",
                    "color": _T1, "fontFamily": _MONO,
                }),
                html.Span(f"  {pct}%", style={
                    "fontSize": "10px", "color": _T3,
                }),
            ], style={"width": "58px", "textAlign": "right", "flexShrink": "0"}),
        ], style={
            "display": "flex", "alignItems": "center",
            "padding": "9px 14px",
            "borderBottom": "" if is_last else f"1px solid {_BD}",
            "background": _CARD,
        }))

    return _card(
        _card_header(title),
        *rows,
        style={"flex": "1"},
    )


# ── State pill list ───────────────────────────────────────────────────────────

def _state_list(states: dict, total: int) -> html.Div:
    STATE_COLOR = {
        "Closed": _GREEN, "Resolved": _GREEN,
        "Not Required": _DIM, "Not an issue": _DIM,
        "Userstory Update": _DIM, "No Customer Response": _DIM,
        "Active": _AMBER, "Dev InProgress": _AMBER,
        "Dev Review": _AMBER, "Dev Complete": _CYAN,
        "Clarification": _RED, "Request Estimate": _RED,
        "New": _T3,
    }
    rows = []
    for i, (st, cnt) in enumerate(states.items()):
        col     = STATE_COLOR.get(st, _T3)
        pct     = round(cnt / total * 100) if total else 0
        is_last = (i == len(states) - 1)
        rows.append(html.Div([
            html.Span("●", style={"color": col, "fontSize": "8px",
                                  "marginRight": "8px", "flexShrink": "0"}),
            html.Span(st, style={"fontSize": "12px", "color": _T1, "flex": "1"}),
            html.Div([
                html.Div(style={
                    "width": f"{min(pct, 100)}%", "height": "100%",
                    "background": col, "borderRadius": "2px",
                }),
            ], style={
                "width": "120px", "height": "6px", "background": _BD,
                "borderRadius": "2px", "overflow": "hidden", "margin": "0 14px",
            }),
            html.Span(str(cnt), style={
                "fontSize": "12px", "fontWeight": "700",
                "color": _T1, "fontFamily": _MONO, "width": "28px", "textAlign": "right",
            }),
            html.Span(f"{pct}%", style={
                "fontSize": "10px", "color": _T3,
                "width": "36px", "textAlign": "right",
            }),
        ], style={
            "display": "flex", "alignItems": "center",
            "padding": "9px 14px",
            "borderBottom": "" if is_last else f"1px solid {_BD}",
            "background": _CARD,
        }))

    return _card(
        _card_header("STATE BREAKDOWN"),
        *rows,
        style={"marginBottom": "14px"},
    )


# ── Sections ──────────────────────────────────────────────────────────────────

def _enh_section(d: dict) -> html.Div:
    pct      = d["delivery_pct"]
    total    = d["enh_total"]
    badge_c  = _GREEN if pct >= 80 else _AMBER if pct >= 50 else _RED
    badge_l  = f"{pct}% DELIVERED  ·  {d['enh_closed']} / {total}"

    if not total:
        return html.Div([
            html.Div(style={"paddingTop": "24px"}),
            _section_header("A", "Enhancement Delivery"),
            html.Div("No enhancements tagged for this release.",
                     style={"color": _DIM, "fontSize": "12px"}),
        ])

    states_card = _state_list(d["enh_states"], total)
    top_funcs   = list(d["enh_function"].items())[:9]

    return html.Div([
        html.Div(style={"paddingTop": "28px"}),
        _section_header("A", "Enhancement Delivery", badge_l, badge_c),
        states_card,
        html.Div([
            _priority_block(d["enh_priority"]),
            html.Div(style={"width": "14px", "flexShrink": "0"}),
            _bar_chart("BY DEVICE / AREA", list(d["enh_area"].items()), _INDIGO),
            html.Div(style={"width": "14px", "flexShrink": "0"}),
            _bar_chart("BY FUNCTION (TOP 9)", top_funcs, _CYAN),
        ], style={"display": "flex"}),
    ])


def _release_date_banner(d: dict) -> html.Div:
    start = d.get("release_start") or "—"
    end   = d.get("release_end")   or "Ongoing"
    title = d.get("release_title", "")

    def _date_block(label, value, color):
        return html.Div([
            html.Div(label, style={
                "fontSize": "9px", "textTransform": "uppercase",
                "letterSpacing": "0.07em", "color": _T3, "fontWeight": "600",
                "marginBottom": "4px",
            }),
            html.Div(value, style={
                "fontSize": "15px", "fontWeight": "700",
                "color": color, "fontFamily": _MONO,
            }),
        ])

    return html.Div([
        html.Div([
            html.Div(title, style={
                "fontSize": "14px", "fontWeight": "700", "color": _T1,
                "marginBottom": "10px",
            }),
            html.Div([
                _date_block("Start Date", start, _CYAN),
                html.Div("→", style={
                    "fontSize": "20px", "color": _DIM,
                    "margin": "0 20px", "alignSelf": "flex-end", "paddingBottom": "2px",
                }),
                _date_block("End Date", end, _CYAN),
            ], style={"display": "flex", "alignItems": "flex-end"}),
        ]),
    ], style={
        "background": _CARD, "border": f"1px solid {_BD}",
        "borderLeft": f"4px solid {_CYAN}",
        "borderRadius": "0 10px 10px 0",
        "padding": "18px 24px",
        "marginBottom": "24px",
    })


def _bugs_raised_section(d: dict) -> html.Div:
    bug_total = d["bug_total"]
    p1_open   = d["p1_open"]
    badge_c   = _RED if p1_open > 0 else _AMBER if bug_total > 0 else _GREEN
    badge_l   = f"{bug_total} TOTAL  ·  {d['bug_open']} OPEN  ·  {p1_open} P1"

    if not bug_total:
        return html.Div([
            html.Div(style={"paddingTop": "28px"}),
            _section_header("B", "Bugs Raised in Release", "0 BUGS RAISED", _GREEN),
            html.Div("No bugs raised in this release window.",
                     style={"color": _GREEN, "fontSize": "12px"}),
        ])

    return html.Div([
        html.Div(style={"paddingTop": "28px"}),
        _section_header("B", "Bugs Raised in Release", badge_l, badge_c),
        html.Div([
            html.Span("Bugs created between release start and next release start date.",
                      style={"fontSize": "11px", "color": _T3}),
        ], style={"marginBottom": "16px"}),

        html.Div([
            _priority_block(d["bug_priority"]),
            html.Div(style={"width": "14px", "flexShrink": "0"}),
            _bar_chart("BY DEVICE / AREA", list(d["bug_area"].items()), _RED),
            html.Div(style={"width": "14px", "flexShrink": "0"}),
            _bar_chart("BY ENVIRONMENT (STAGE)", list(d["bug_stage"].items()), _AMBER),
        ], style={"display": "flex", "marginBottom": "14px"}),

        html.Div([
            _bar_chart("STATE BREAKDOWN", list(d["bug_states"].items()), _INDIGO),
            html.Div(style={"width": "14px", "flexShrink": "0"}),
            _bar_chart("BUG TYPE", list(d["bug_type"].items()), _RED),
        ], style={"display": "flex"}),

        _p1_detail_card(d.get("p1_bug_details", [])),
    ])


def _p1_detail_card(details: list) -> html.Div:
    if not details:
        return html.Span()

    _S_COLOR = {
        "Active": _AMBER, "Dev InProgress": _AMBER, "Dev Review": _AMBER,
        "Dev Complete": _CYAN, "Clarification": _RED, "New": _T3,
        "Request Estimate": _RED,
    }

    hdr = html.Tr([
        html.Th(t, style={
            "padding": "7px 14px", "fontSize": "9px", "textTransform": "uppercase",
            "letterSpacing": "0.06em", "color": _T3, "fontWeight": "600",
            "textAlign": "left", "background": _RAISED, "borderBottom": f"1px solid {_BD}",
            "whiteSpace": "nowrap",
        }) for t in ["ID", "TITLE", "STATE", "ASSIGNED TO", "AREA", "RAISED"]
    ])

    rows = []
    for i, bug in enumerate(details):
        is_last = i == len(details) - 1
        bd = "" if is_last else f"1px solid {_BD}"
        scol = _S_COLOR.get(bug["state"], _T2)
        bg = _CARD if i % 2 == 0 else _RAISED
        rows.append(html.Tr([
            html.Td(str(bug["id"]), style={
                "padding": "8px 14px", "fontSize": "11px", "color": _DIM,
                "fontFamily": _MONO, "borderBottom": bd, "whiteSpace": "nowrap",
            }),
            html.Td(bug["title"], style={
                "padding": "8px 14px", "fontSize": "12px", "color": _T1,
                "borderBottom": bd, "maxWidth": "320px",
                "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
            }),
            html.Td(html.Span(bug["state"], style={"color": scol, "fontWeight": "600"}), style={
                "padding": "8px 14px", "fontSize": "12px", "borderBottom": bd, "whiteSpace": "nowrap",
            }),
            html.Td(bug["assigned_to"], style={
                "padding": "8px 14px", "fontSize": "12px", "color": _T2,
                "borderBottom": bd, "whiteSpace": "nowrap",
            }),
            html.Td(bug["area"], style={
                "padding": "8px 14px", "fontSize": "12px", "color": _T3,
                "borderBottom": bd,
            }),
            html.Td(bug["created"][:10] if bug.get("created") else "—", style={
                "padding": "8px 14px", "fontSize": "11px", "color": _DIM,
                "fontFamily": _MONO, "borderBottom": bd, "whiteSpace": "nowrap",
            }),
        ], style={"background": bg}))

    return html.Div([
        html.Div(style={"height": "14px"}),
        _card(
            _card_header(f"P1 OPEN BUGS — {len(details)} ITEMS REQUIRING ATTENTION"),
            html.Div(
                html.Table([html.Thead(hdr), html.Tbody(rows)],
                           style={"width": "100%", "borderCollapse": "collapse"}),
                style={"overflowX": "auto"},
            ),
        ),
    ])


def _bugs_fixed_section(d: dict) -> html.Div:
    n     = d["bugs_fixed_total"]
    badge = f"{n} FIXED / CLOSED"
    bcol  = _GREEN if n > 0 else _DIM

    if not n:
        return html.Div([
            html.Div(style={"paddingTop": "28px"}),
            _section_header("C", "Bugs Fixed in Release", "0 FIXED", _DIM),
            html.Div("No bugs closed in this release window.",
                     style={"color": _DIM, "fontSize": "12px"}),
        ])

    return html.Div([
        html.Div(style={"paddingTop": "28px"}),
        _section_header("C", "Bugs Fixed in Release", badge, bcol),
        html.Div([
            html.Span("Bugs whose closed_date falls within this release window (any source release).",
                      style={"fontSize": "11px", "color": _T3}),
        ], style={"marginBottom": "16px"}),

        html.Div([
            _priority_block(d["bugs_fixed_priority"], title="FIXED BY PRIORITY"),
            html.Div(style={"width": "14px", "flexShrink": "0"}),
            _bar_chart("FIXED BY DEVICE / AREA", list(d["bugs_fixed_area"].items()), _GREEN),
            html.Div(style={"width": "14px", "flexShrink": "0"}),
            _bar_chart("FIXED BY ENVIRONMENT", list(d["bugs_fixed_stage"].items()), _CYAN),
        ], style={"display": "flex"}),
    ])


def _verdict_section(d: dict) -> html.Div:
    v     = d["verdict"]
    col   = {
        "RED": _RED, "AMBER": _AMBER, "GREEN": _GREEN,
    }.get(v, _DIM)

    summaries = {
        "RED": (
            f"{d['p1_open']} P1 bug{'s' if d['p1_open'] != 1 else ''} still open. "
            f"Enhancement delivery at {d['delivery_pct']}%. "
            "Immediate remediation required before the next release cycle."
        ) if d["p1_open"] > 0 else (
            f"Enhancement delivery at {d['delivery_pct']}% — below acceptable threshold. "
            f"{d['bug_open']} bugs open at audit time."
        ),
        "AMBER": (
            f"Delivery at {d['delivery_pct']}%. {d['bug_open']} of {d['bug_total']} "
            "bugs still open. Monitor and remediate before next release cut."
        ),
        "GREEN": (
            f"{d['delivery_pct']}% of planned enhancements delivered. "
            f"{d['bug_closed']} of {d['bug_total']} bugs closed ({d['bug_close_pct']}%). "
            "Release is in healthy shape."
        ),
        "UNKNOWN": (
            f"No items found for release \"{d.get('release_title', '')}\" in ADO. "
            "Verify the release_date field is populated on enhancements."
        ),
    }

    return html.Div([
        html.Div(style={"paddingTop": "28px"}),
        _section_header("D", "Release Verdict"),
        html.Div([
            html.Div([
                _label("OVERALL VERDICT"),
                html.Div([
                    html.Span("●", style={"fontSize": "10px", "color": col, "marginRight": "8px"}),
                    html.Span(v, style={
                        "fontSize": "22px", "fontWeight": "700",
                        "color": col, "fontFamily": _MONO,
                    }),
                ], style={"display": "flex", "alignItems": "center",
                          "margin": "10px 0 12px"}),
                html.Div(summaries.get(v, ""), style={
                    "fontSize": "12.5px", "color": _T2, "lineHeight": "1.7",
                }),
            ], style={"flex": "1"}),
        ], style={
            "display": "flex", "padding": "20px 22px",
            "background": _CARD, "border": f"1px solid {_BD}",
            "borderLeft": f"4px solid {col}",
            "borderRadius": "0 10px 10px 0",
        }),
    ])


# ── Content + empty state ─────────────────────────────────────────────────────

def _trend_table() -> html.Div:
    rows = get_release_trend()
    if not rows:
        return html.Span()

    def _del_chip(pct):
        if pct is None:
            return html.Span("—", style={"color": _DIM, "fontSize": "11px"})
        c = _GREEN if pct >= 80 else _AMBER if pct >= 50 else _RED
        return html.Span(f"{pct}%", style={
            "color": c, "fontWeight": "700", "fontFamily": _MONO, "fontSize": "12px",
        })

    def _n(val, warn_color=None):
        c = warn_color if (warn_color and val > 0) else _T2
        return html.Span(str(val), style={
            "color": c, "fontFamily": _MONO, "fontSize": "12px", "fontWeight": "600",
        })

    header = html.Tr([
        html.Th(t, style={
            "padding": "7px 14px", "fontSize": "9px", "textTransform": "uppercase",
            "letterSpacing": "0.06em", "color": _T3, "fontWeight": "600",
            "textAlign": "left", "background": _RAISED, "borderBottom": f"1px solid {_BD}",
        })
        for t in ["RELEASE", "PERIOD", "ENH PLANNED", "DELIVERED", "BUGS FOUND", "P1", "P2"]
    ])

    tbl_rows = []
    for i, r in enumerate(rows):
        is_last = (i == len(rows) - 1)
        bd = "" if is_last else f"1px solid {_BD}"
        period = (
            f"{r['start_date']} → {r['target_date']}"
            if r['target_date'] != "—"
            else f"{r['start_date']} → ongoing"
        )
        status_dot = html.Span("●", style={
            "color": _GREEN if r["status"] == "Released" else _AMBER,
            "fontSize": "7px", "marginRight": "6px",
        })
        tbl_rows.append(html.Tr([
            html.Td([status_dot, r["title"]], style={
                "padding": "9px 14px", "fontSize": "12px", "color": _T1,
                "fontWeight": "500", "borderBottom": bd,
            }),
            html.Td(period, style={
                "padding": "9px 14px", "fontSize": "10.5px", "color": _T3,
                "fontFamily": _MONO, "borderBottom": bd,
            }),
            html.Td(_n(r["enh_total"]), style={"padding": "9px 14px", "borderBottom": bd}),
            html.Td(_del_chip(r["delivery_pct"]), style={"padding": "9px 14px", "borderBottom": bd}),
            html.Td(_n(r["bug_total"], _AMBER), style={"padding": "9px 14px", "borderBottom": bd}),
            html.Td(_n(r["p1_bugs"], _RED),    style={"padding": "9px 14px", "borderBottom": bd}),
            html.Td(_n(r["p2_bugs"], _AMBER),  style={"padding": "9px 14px", "borderBottom": bd}),
        ], style={"background": _CARD if i % 2 == 0 else _RAISED}))

    return html.Div([
        html.Div(style={"paddingTop": "28px"}),
        _section_header("E", "Release History"),
        _card(
            html.Table(
                [html.Thead(header), html.Tbody(tbl_rows)],
                style={"width": "100%", "borderCollapse": "collapse"},
            ),
        ),
    ])


def _build_content(d: dict) -> html.Div:
    return html.Div([
        _release_date_banner(d),
        _kpi_strip(d),
        _enh_section(d),
        _bugs_raised_section(d),
        _bugs_fixed_section(d),
        _verdict_section(d),
        _trend_table(),
        html.Div([
            html.Span(f"Release: {d.get('release_title', '')}",
                      style={"fontSize": "10px", "color": _DIM}),
            html.Span(f"Generated from Azure DevOps live sync · {d.get('generated', '')}",
                      style={"fontSize": "10px", "color": _DIM}),
        ], style={
            "borderTop": f"1px solid {_BD}", "paddingTop": "14px",
            "display": "flex", "justifyContent": "space-between",
            "marginTop": "32px",
        }),
    ])


def _empty_state() -> html.Div:
    return html.Div("Select a release to view the audit report.", style={
        "color": _DIM, "fontSize": "13px",
        "padding": "60px 0", "textAlign": "center",
    })


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("ra-content", "children"),
    Input("ra-release-select", "value"),
    prevent_initial_call=True,
)
def _on_release_change(release_key):
    if release_key is None:
        return _empty_state()
    return _build_content(get_release_audit_data(release_key))


def _make_html_report(d: dict, trend: list) -> str:
    vcol_map = {"RED": "#e04848", "AMBER": "#e0a23c", "GREEN": "#2ecc8a"}
    vcol     = vcol_map.get(d["verdict"], "#888")

    def _pct_c(pct, hi=80, lo=50):
        return "#2ecc8a" if pct >= hi else "#e0a23c" if pct >= lo else "#e04848"

    def _trow(*cells, header=False, bg="#fff"):
        tag = "th" if header else "td"
        inner = "".join(f"<{tag} style='padding:7px 12px;border-bottom:1px solid #e0e0e0;"
                        f"text-align:left;font-size:13px;white-space:nowrap'>{c}</{tag}>"
                        for c in cells)
        return f"<tr style='background:{bg}'>{inner}</tr>"

    def _section(letter, title, rows_html, subtitle=""):
        sub = f"<p style='font-size:11px;color:#888;margin:4px 0 12px'>{subtitle}</p>" if subtitle else ""
        return (
            f"<div style='margin-top:32px'>"
            f"<div style='display:flex;align-items:center;gap:8px;border-bottom:2px solid #1a1a2e;"
            f"padding-bottom:8px;margin-bottom:14px'>"
            f"<span style='font-size:11px;color:#888;font-family:monospace'>{letter}</span>"
            f"<span style='font-size:15px;font-weight:700;color:#1a1a2e'>{title}</span></div>"
            f"{sub}{rows_html}</div>"
        )

    def _kpi_cell(val, label, color="#1a1a2e"):
        return (f"<div style='flex:1;padding:16px 18px;border-right:1px solid #e0e0e0'>"
                f"<div style='font-size:26px;font-weight:700;color:{color};"
                f"font-family:monospace;line-height:1;margin-bottom:4px'>{val}</div>"
                f"<div style='font-size:10px;text-transform:uppercase;letter-spacing:0.06em;"
                f"color:#888;font-weight:600'>{label}</div></div>")

    def _table(headers, rows):
        hdr = "".join(f"<th style='padding:8px 12px;background:#f5f7fa;border-bottom:2px solid #ddd;"
                      f"text-align:left;font-size:11px;text-transform:uppercase;"
                      f"letter-spacing:0.05em;color:#555;white-space:nowrap'>{h}</th>"
                      for h in headers)
        body = ""
        for i, r in enumerate(rows):
            bg = "#fff" if i % 2 == 0 else "#f9fafb"
            body += "".join(f"<tr style='background:{bg}'>" +
                            "".join(f"<td style='padding:8px 12px;border-bottom:1px solid #eee;"
                                    f"font-size:13px'>{c}</td>" for c in r) +
                            "</tr>")
        return (f"<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;"
                f"border:1px solid #e0e0e0;border-radius:6px;overflow:hidden'>"
                f"<thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table></div>")

    # ── KPI ───────────────────────────────────────────────────────────────────
    del_c = _pct_c(d["delivery_pct"])
    bcl_c = _pct_c(d["bug_close_pct"])
    p1_c  = "#e04848" if d["p1_open"] > 0 else "#1a1a2e"
    fx_c  = "#2ecc8a" if d["bugs_fixed_total"] > 0 else "#aaa"

    kpi_deliveries = (
        f"<div style='border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;flex:3;margin-right:12px'>"
        f"<div style='padding:7px 14px;background:#f0fff7;font-size:11px;font-weight:700;"
        f"text-transform:uppercase;letter-spacing:0.07em;color:#2ecc8a;"
        f"border-bottom:1px solid #e0e0e0'>&#9679; Deliveries</div>"
        f"<div style='display:flex'>"
        f"{_kpi_cell(d['enh_total'], 'Planned')}"
        f"{_kpi_cell(d['enh_closed'], 'Shipped', '#2ecc8a' if d['enh_closed'] else '#aaa')}"
        f"{_kpi_cell(str(d['delivery_pct'])+'%', 'Delivery Rate', del_c)}"
        f"<div style='flex:1;padding:16px 18px'>"
        f"<div style='font-size:26px;font-weight:700;color:{fx_c};"
        f"font-family:monospace;line-height:1;margin-bottom:4px'>{d['bugs_fixed_total']}</div>"
        f"<div style='font-size:10px;text-transform:uppercase;letter-spacing:0.06em;"
        f"color:#888;font-weight:600'>Bugs Fixed</div></div>"
        f"</div></div>"
    )
    kpi_discoveries = (
        f"<div style='border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;flex:2'>"
        f"<div style='padding:7px 14px;background:#fffbf0;font-size:11px;font-weight:700;"
        f"text-transform:uppercase;letter-spacing:0.07em;color:#e0a23c;"
        f"border-bottom:1px solid #e0e0e0'>&#9679; Discoveries</div>"
        f"<div style='display:flex'>"
        f"{_kpi_cell(d['bug_total'], 'Bugs Raised', '#e0a23c' if d['bug_total'] else '#aaa')}"
        f"{_kpi_cell(d['p1_open'], 'P1 Open', p1_c)}"
        f"<div style='flex:1;padding:16px 18px'>"
        f"<div style='font-size:26px;font-weight:700;color:{bcl_c};"
        f"font-family:monospace;line-height:1;margin-bottom:4px'>{d['bug_close_pct']}%</div>"
        f"<div style='font-size:10px;text-transform:uppercase;letter-spacing:0.06em;"
        f"color:#888;font-weight:600'>Close Rate</div></div>"
        f"</div></div>"
    )
    kpi_html = f"<div style='display:flex;margin-bottom:24px'>{kpi_deliveries}{kpi_discoveries}</div>"

    # ── Enhancement table ─────────────────────────────────────────────────────
    enh_rows = [
        [st, str(cnt), f"{round(cnt/max(d['enh_total'],1)*100)}%"]
        for st, cnt in d["enh_states"].items()
    ] if d["enh_states"] else [["No enhancements tagged", "—", "—"]]
    enh_html = _section("A", "Enhancement Delivery",
                        _table(["State", "Count", "%"], enh_rows),
                        f"{d['enh_closed']} of {d['enh_total']} delivered — {d['delivery_pct']}%")

    # ── P1 open bugs table ────────────────────────────────────────────────────
    p1_details = d.get("p1_bug_details", [])
    if p1_details:
        p1_rows_html = [
            [str(b["id"]), b["title"], b["state"], b["assigned_to"],
             b["area"], b["created"][:10] if b.get("created") else "—"]
            for b in p1_details
        ]
        p1_html_inner = _table(["ID", "Title", "State", "Assigned To", "Area", "Raised"],
                               p1_rows_html)
    else:
        p1_html_inner = "<p style='color:#2ecc8a;font-size:13px'>No P1 bugs open.</p>"

    # ── Bugs raised table ─────────────────────────────────────────────────────
    pri_rows_r = [[f"P{p}", str(c)] for p, c in d["bug_priority"].items()]
    st_rows_r  = [[s, str(c)] for s, c in d["bug_states"].items()]
    bugs_raised_html = _section(
        "B", "Bugs Raised in Release",
        _table(["Priority", "Count"], pri_rows_r) +
        "<div style='margin-top:12px'></div>" +
        _table(["State", "Count"], st_rows_r) +
        "<div style='margin-top:16px'><strong style='font-size:13px'>P1 Open — Needs Immediate Attention</strong></div>" +
        "<div style='margin-top:8px'>" + p1_html_inner + "</div>",
        f"{d['bug_total']} total · {d['bug_open']} open · {d['p1_open']} P1 open",
    )

    # ── Bugs fixed table ──────────────────────────────────────────────────────
    pri_rows_f = [[f"P{p}", str(c)] for p, c in d["bugs_fixed_priority"].items()]
    bugs_fixed_html = _section(
        "C", "Bugs Fixed in Release",
        _table(["Priority", "Count"], pri_rows_f),
        f"{d['bugs_fixed_total']} bugs closed within the release window",
    )

    # ── Verdict ───────────────────────────────────────────────────────────────
    verdict_summaries = {
        "RED": f"{d['p1_open']} P1 bug(s) still open. Delivery at {d['delivery_pct']}%. Immediate remediation required.",
        "AMBER": f"Delivery at {d['delivery_pct']}%. {d['bug_open']} bugs still open. Monitor before next release.",
        "GREEN": f"{d['delivery_pct']}% delivered. {d['bug_closed']} of {d['bug_total']} bugs closed ({d['bug_close_pct']}%).",
        "UNKNOWN": "No items found for this release in ADO. Verify release_date tags.",
    }
    verdict_html = _section("D", "Release Verdict",
        f"<div style='display:inline-block;padding:8px 20px;border-radius:6px;"
        f"background:{vcol}20;border:1.5px solid {vcol};color:{vcol};"
        f"font-size:15px;font-weight:700;margin-bottom:10px'>{d['verdict']}</div>"
        f"<p style='font-size:13px;color:#555;line-height:1.7'>"
        f"{verdict_summaries.get(d['verdict'], '')}</p>")

    # ── History table ─────────────────────────────────────────────────────────
    hist_rows = [
        [r["title"],
         f"{r['start_date']} → {r['target_date']}",
         r["status"],
         str(r["enh_total"]),
         f"{r['delivery_pct']}%" if r["delivery_pct"] is not None else "—",
         str(r["bug_total"]),
         str(r["p1_bugs"])]
        for r in trend
    ] if trend else []
    hist_html = _section("E", "Release History",
                         _table(["Release", "Period", "Status", "Planned",
                                 "Delivered", "Bugs", "P1"], hist_rows))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Release Audit — {d['release_title']}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        background: #f0f2f5; color: #1a1a2e; padding: 32px; font-size: 14px; }}
.page {{ max-width: 1100px; margin: 0 auto; background: #fff;
         border-radius: 8px; padding: 40px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
@media print {{ body {{ background:#fff;padding:0 }} .page {{ box-shadow:none }} }}
</style>
</head>
<body><div class="page">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.1em;
              color:#6860d4;font-weight:700;margin-bottom:10px">
    Expense on Demand &nbsp;·&nbsp; Internal Confidential &nbsp;·&nbsp; Azure DevOps
  </div>
  <h1 style="font-size:22px;font-weight:700;margin-bottom:4px">Release Audit Report</h1>
  <p style="font-size:13px;color:#888;margin-bottom:6px">
    {d['release_title']} &nbsp;·&nbsp;
    {d['release_start'] or '—'} → {d['release_end'] or 'Ongoing'}
  </p>
  <p style="font-size:11px;color:#aaa;margin-bottom:28px">
    Generated {d['generated']} from Azure DevOps live sync
  </p>
  {kpi_html}
  {enh_html}
  {bugs_raised_html}
  {bugs_fixed_html}
  {verdict_html}
  {hist_html}
  <div style="margin-top:32px;padding-top:14px;border-top:1px solid #e0e0e0;
              font-size:11px;color:#aaa">
    Expense on Demand — Internal use only &nbsp;·&nbsp; Generated {d['generated']}
  </div>
</div></body></html>"""


@callback(
    Output("ra-download", "data"),
    Input("ra-download-btn", "n_clicks"),
    State("ra-release-select", "value"),
    prevent_initial_call=True,
)
def _download_report(n_clicks, release_key):
    if not n_clicks or release_key is None:
        return no_update
    d     = get_release_audit_data(release_key)
    trend = get_release_trend()
    html_str = _make_html_report(d, trend)
    fname = f"Release_Audit_{d['release_title'].replace(' ', '_')}.html"
    return dcc.send_string(html_str, fname, type="text/html")


# ── Layout ────────────────────────────────────────────────────────────────────

def layout(**_):
    options = get_release_options()
    default = options[0]["value"] if options else None   # newest first
    initial = _build_content(get_release_audit_data(default)) if default else _empty_state()

    header = html.Div([
        html.Div([
            html.Div(
                "EXPENSE ON DEMAND  ·  INTERNAL CONFIDENTIAL  ·  AZURE DEVOPS",
                style={
                    "fontSize": "9px", "letterSpacing": "0.1em",
                    "textTransform": "uppercase", "color": _INDIGO,
                    "fontWeight": "600", "marginBottom": "10px",
                }
            ),
            html.H1([
                html.Span("Release ", style={"fontWeight": "300", "color": _T2}),
                html.Span("Audit Report", style={"fontWeight": "700", "color": _T1}),
            ], style={
                "fontSize": "26px", "lineHeight": "1.1",
                "letterSpacing": "-0.4px", "marginBottom": "5px",
            }),
            html.Div(
                "Post-release quality & delivery review  ·  Azure DevOps live sync",
                style={"fontSize": "11.5px", "color": _T3},
            ),
        ], style={"flex": "1"}),

        html.Div([
            html.Div("RELEASE", style={
                "fontSize": "9px", "textTransform": "uppercase",
                "letterSpacing": "0.07em", "color": _T3,
                "fontWeight": "600", "marginBottom": "6px",
            }),
            dcc.Dropdown(
                id="ra-release-select",
                options=options,
                value=default,
                clearable=False,
                style={"width": "180px", "fontSize": "12px"},
            ),
            html.Button([
                html.Span("↓", style={"marginRight": "6px", "fontSize": "14px"}),
                "Download Report",
            ], id="ra-download-btn", n_clicks=0, style={
                "marginTop": "10px", "width": "100%",
                "background": _INDIGO, "color": _T1,
                "border": "none", "borderRadius": "6px",
                "padding": "8px 14px", "fontSize": "11px",
                "fontWeight": "600", "cursor": "pointer",
                "letterSpacing": "0.03em",
            }),
        ], style={"flexShrink": "0"}),
    ], style={
        "display": "flex", "alignItems": "flex-start",
        "justifyContent": "space-between", "gap": "24px",
        "background": _CARD, "borderBottom": f"1px solid {_BD}",
        "padding": "28px 40px",
    })

    return html.Div([
        header,
        dcc.Download(id="ra-download"),
        dcc.Loading(
            html.Div(id="ra-content", children=initial,
                     style={"padding": "20px 40px 40px"}),
            type="dot",
        ),
    ], style={"background": _BG, "minHeight": "100vh"})
