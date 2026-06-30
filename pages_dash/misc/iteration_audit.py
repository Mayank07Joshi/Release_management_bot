"""
pages_dash/iteration_audit.py
──────────────────────────────
Iteration Audit page — mid-sprint / post-iteration quality review.
Scope: Enhancements + Bugs in the sprint iteration (no Tasks).
Read-only display, no callbacks.
"""
import dash
from dash import html

from db.iteration_audit import get_iteration_audit_data

dash.register_page(__name__, path="/iteration-audit", name="Iteration Audit")

# ── Style helpers ─────────────────────────────────────────────────────────────

def _rag_styles(verdict: str) -> dict:
    if verdict == "RED":
        return {"color": "var(--re)", "background": "var(--re-bg)",
                "border": "0.5px solid var(--re-bd)"}
    if verdict == "AMBER":
        return {"color": "var(--am)", "background": "var(--am-bg)",
                "border": "0.5px solid var(--am-bd)"}
    if verdict == "GREEN":
        return {"color": "var(--gr)", "background": "var(--gr-bg)",
                "border": "0.5px solid var(--gr-bd)"}
    return {"color": "var(--t3)", "background": "rgba(128,128,128,.08)",
            "border": "0.5px solid rgba(128,128,128,.2)"}


def _badge(verdict: str, label: str | None = None) -> html.Span:
    text = label or verdict
    s = {**_rag_styles(verdict),
         "display": "inline-flex", "alignItems": "center", "gap": "3px",
         "fontSize": "9px", "fontWeight": "500", "letterSpacing": "0.04em",
         "padding": "2px 7px", "borderRadius": "20px", "textTransform": "uppercase",
         "whiteSpace": "nowrap"}
    dot_color = _rag_styles(verdict)["color"]
    return html.Span([
        html.Span("●", style={"fontSize": "7px", "color": dot_color}),
        text,
    ], style=s)


def _code(t: str) -> html.Code:
    return html.Code(t, style={
        "fontFamily": "'DM Mono', 'Courier New', monospace",
        "fontSize": "11px", "color": "var(--t2)", "background": "var(--ra)",
        "padding": "1px 5px", "borderRadius": "3px", "border": "0.5px solid var(--b2)",
    })


def _chip(item_id: int) -> html.Span:
    return html.Span(f"#{item_id}", style={
        "fontFamily": "'DM Mono', monospace", "fontSize": "10px",
        "color": "var(--ac)", "background": "var(--ra)",
        "padding": "1px 6px", "borderRadius": "3px", "border": "0.5px solid var(--b1)",
        "marginRight": "4px",
    })


def _section_header(number: str, title: str, badge_verdict: str | None = None,
                    badge_label: str | None = None) -> html.Div:
    badge = None
    if badge_verdict:
        if badge_verdict == "DATA GAP":
            badge = html.Span(badge_label or "DATA GAP", style={
                "color": "var(--t3)", "background": "rgba(128,128,128,.08)",
                "border": "0.5px solid rgba(128,128,128,.2)",
                "fontSize": "9px", "fontWeight": "500", "letterSpacing": "0.04em",
                "padding": "2px 7px", "borderRadius": "20px", "textTransform": "uppercase",
            })
        else:
            badge = _badge(badge_verdict)

    return html.Div([
        html.Span(number, style={
            "fontFamily": "'DM Mono', monospace", "fontSize": "10px",
            "color": "var(--t3)", "marginRight": "8px",
        }),
        html.Span(title, style={
            "fontSize": "13px", "fontWeight": "500", "color": "var(--t1)",
        }),
        html.Span(style={"flex": "1"}),
        badge or html.Span(),
    ], style={
        "display": "flex", "alignItems": "baseline", "gap": "4px",
        "marginBottom": "14px", "paddingBottom": "10px",
        "borderBottom": "0.5px solid var(--b1)",
    })


def _metric_row(metric: str, target: str, verdict: str,
                badge_label: str | None = None, note: str | None = None,
                note_children=None, last: bool = False) -> html.Tr:
    result_content = [_badge(verdict, badge_label)]
    if note_children:
        result_content += [html.Span(" ", style={"marginLeft": "6px"})] + note_children
    elif note:
        result_content.append(html.Span(" " + note, style={
            "fontSize": "11.5px", "color": "var(--t2)", "lineHeight": "1.55",
        }))

    return html.Tr([
        html.Td(metric, style={
            "width": "34%", "padding": "10px 12px", "fontSize": "12px",
            "color": "var(--t1)", "verticalAlign": "top",
            "borderBottom": "none" if last else "0.5px solid var(--b1)",
        }),
        html.Td(target, style={
            "width": "9%", "padding": "10px 12px", "fontSize": "11px",
            "fontFamily": "'DM Mono', monospace", "color": "var(--t3)",
            "verticalAlign": "top",
            "borderBottom": "none" if last else "0.5px solid var(--b1)",
        }),
        html.Td(result_content, style={
            "width": "57%", "padding": "10px 12px", "fontSize": "11.5px",
            "color": "var(--t2)", "verticalAlign": "top", "lineHeight": "1.55",
            "borderBottom": "none" if last else "0.5px solid var(--b1)",
        }),
    ], style={"background": "var(--sf)"})


def _metric_table(rows: list) -> html.Div:
    return html.Div(html.Table([
        html.Thead(html.Tr([
            html.Th("METRIC",  style=_th_style("34%")),
            html.Th("TARGET",  style=_th_style("9%")),
            html.Th("RESULT",  style=_th_style("57%")),
        ]), style={"background": "var(--ra)", "borderBottom": "0.5px solid var(--b1)"}),
        html.Tbody(rows),
    ], style={"width": "100%", "borderCollapse": "collapse"}),
    style={"border": "0.5px solid var(--b1)", "borderRadius": "7px",
           "overflow": "hidden", "marginBottom": "14px"})


def _th_style(width: str) -> dict:
    return {
        "width": width, "padding": "7px 12px",
        "fontSize": "9px", "textTransform": "uppercase", "letterSpacing": "0.05em",
        "color": "var(--t3)", "fontWeight": "400", "textAlign": "left",
    }


def _callout(children, color: str = "var(--re)") -> html.Div:
    return html.Div(children, style={
        "borderLeft": f"2px solid {color}", "background": "var(--ra)",
        "padding": "10px 14px", "borderRadius": "0 6px 6px 0",
        "fontSize": "12px", "color": "var(--t2)", "lineHeight": "1.65",
        "marginBottom": "12px",
    })


def _progress_bar(label: str, numerator: int, denominator: int,
                  pct: int, color: str) -> html.Div:
    return html.Div([
        html.Div([
            html.Span(label, style={
                "fontSize": "11px", "color": "var(--t2)", "flex": "1",
            }),
            html.Span(f"{pct}%", style={
                "fontSize": "11px", "fontWeight": "500", "color": color,
                "fontFamily": "'DM Mono', monospace",
            }),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "marginBottom": "4px"}),
        html.Div(
            html.Div(style={
                "width": f"{min(pct, 100)}%", "height": "100%",
                "background": color, "borderRadius": "2px",
                "transition": "width 0.3s ease",
            }),
            style={
                "height": "5px", "background": "var(--ra)",
                "borderRadius": "2px", "overflow": "hidden",
            }
        ),
    ], style={"marginBottom": "12px"})


# ── Page sections ─────────────────────────────────────────────────────────────

def _cover(d: dict) -> html.Div:
    v = d["overall_verdict"]
    vs = _rag_styles(v)
    return html.Div([
        # Brand stripe
        html.Div(style={
            "height": "3px",
            "background": "linear-gradient(90deg, var(--ac), #00B8D4)",
        }),
        # Cover content
        html.Div([
            # Two-col flex
            html.Div([
                # Left
                html.Div([
                    html.Div(
                        "EXPENSE ON DEMAND · INTERNAL CONFIDENTIAL · AZURE DEVOPS",
                        style={"fontSize": "9px", "letterSpacing": "0.1em",
                               "textTransform": "uppercase", "color": "var(--ac)",
                               "fontWeight": "500", "marginBottom": "10px"}
                    ),
                    html.H1([
                        html.Span("Iteration ", style={"fontWeight": "300"}),
                        html.Span("Audit Report", style={"fontWeight": "500"}),
                    ], style={"fontSize": "28px", "lineHeight": "1.1",
                              "letterSpacing": "-0.3px", "marginBottom": "5px",
                              "color": "var(--t1)"}),
                    html.Div(
                        f"Mid-sprint snapshot · Day {d['sprint_day']} of ~{d['sprint_total_days']} "
                        f"working days · {d.get('prev_month_name', '')} {d['ym_str'][:4] if 'ym_str' in d else ''}",
                        style={"fontSize": "12px", "color": "var(--t2)"}
                    ),
                ], style={"flex": "1"}),

                # Right — verdict card
                html.Div([
                    html.Div("OVERALL VERDICT", style={
                        "fontSize": "9px", "textTransform": "uppercase",
                        "letterSpacing": "0.05em", "color": "var(--t3)", "marginBottom": "4px",
                    }),
                    html.Div([
                        html.Span("●", style={"fontSize": "7px", "color": vs["color"],
                                              "marginRight": "5px"}),
                        html.Span(v, style={"fontSize": "16px", "fontWeight": "500",
                                            "color": vs["color"]}),
                    ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),
                    html.Div(d["verdict_summary"], style={
                        "fontSize": "11px", "color": "var(--t2)", "lineHeight": "1.5",
                    }),
                ], style={
                    "flexShrink": "0", "minWidth": "260px", "maxWidth": "380px",
                    "border": f"0.5px solid {vs['border'].split(' ')[-1]}",
                    "borderRadius": "6px", "background": vs["background"],
                    "padding": "12px 16px",
                }),
            ], style={"display": "flex", "alignItems": "flex-start",
                      "justifyContent": "space-between", "gap": "24px",
                      "paddingBottom": "20px"}),

            # Meta strip
            html.Div([
                _meta_item("REPORT TYPE",    "Iteration Audit",                              first=True),
                _meta_item("SPRINT",         f"Iteration {d['ym_str'][:4]} {d['ym_str'][5:]}"),
                _meta_item("SNAPSHOT DATE",  d["snapshot_date"]),
                _meta_item("SPRINT DAY",     f"Day {d['sprint_day']} of ~{d['sprint_total_days']}"),
                _meta_item("DAYS REMAINING", f"~{d['days_left']} working days"),
            ], style={
                "borderTop": "0.5px solid var(--b1)", "margin": "0 -40px",
                "padding": "0 40px", "display": "flex",
            }),
        ], style={"background": "var(--sf)", "borderBottom": "0.5px solid var(--b1)",
                  "padding": "28px 40px 0"}),
    ])


def _meta_item(label: str, value: str, first: bool = False) -> html.Div:
    s = {"flex": "1", "padding": "10px 0", "display": "flex",
         "flexDirection": "column", "gap": "2px"}
    if not first:
        s.update({"borderLeft": "0.5px solid var(--b1)",
                  "paddingLeft": "20px", "marginLeft": "20px"})
    return html.Div([
        html.Div(label, style={
            "fontSize": "9px", "textTransform": "uppercase",
            "letterSpacing": "0.05em", "color": "var(--t3)",
        }),
        html.Div(value, style={
            "fontSize": "11px", "fontWeight": "500", "color": "var(--t2)",
        }),
    ], style=s)


def _stats_strip(d: dict) -> html.Div:
    items = [
        (str(d["enhancements_shipped"]), "ENHANCEMENTS SHIPPED",
         "#9EECC5" if d["enhancements_shipped"] > 0 else "#FFB3AE"),
        (str(d["items_closed"]),         "ITEMS CLOSED",         "#FFD99A"),
        (str(d["p1_open"]),              "P1 BUGS OPEN",         "#FFB3AE"),
        (str(d["unestimated"]),          "UNESTIMATED ITEMS",    "#FFB3AE"),
        (d["days_left_approx"],          "WORKING DAYS LEFT",    "rgba(255,255,255,0.9)"),
        (str(d["total_sprint_items"]),   "TOTAL SPRINT ITEMS",   "rgba(255,255,255,0.9)"),
    ]
    children = []
    for i, (val, label, color) in enumerate(items):
        style = {
            "flex": "1", "padding": "14px 0", "display": "flex",
            "flexDirection": "column", "gap": "3px",
        }
        if i < len(items) - 1:
            style.update({"borderRight": "0.5px solid rgba(255,255,255,0.2)",
                          "paddingRight": "20px", "marginRight": "20px"})
        children.append(html.Div([
            html.Div(val, style={
                "fontSize": "22px", "fontWeight": "500", "color": color,
                "fontVariantNumeric": "tabular-nums", "lineHeight": "1",
            }),
            html.Div(label, style={
                "fontSize": "9px", "textTransform": "uppercase",
                "letterSpacing": "0.05em", "color": "rgba(255,255,255,0.65)",
            }),
        ], style=style))

    return html.Div(children, style={
        "background": "var(--bg-base)", "padding": "0 40px",
        "display": "flex", "borderBottom": "1px solid rgba(255,255,255,0.06)",
    })


def _kpi_card(label: str, value: str, sub: str, color: str = "var(--re)") -> html.Div:
    return html.Div([
        html.Div(label, style={
            "fontSize": "9px", "textTransform": "uppercase", "letterSpacing": "0.05em",
            "color": "var(--t3)", "marginBottom": "6px",
        }),
        html.Div(value, style={
            "fontSize": "28px", "fontWeight": "500", "color": color,
            "fontVariantNumeric": "tabular-nums", "lineHeight": "1.1", "marginBottom": "8px",
        }),
        html.Div(sub, style={"fontSize": "11.5px", "color": "var(--t2)", "lineHeight": "1.6"}),
    ], style={
        "flex": "1", "padding": "16px", "border": "0.5px solid var(--b1)",
        "borderRadius": "7px", "background": "var(--sf)",
    })


def _finding_card(number: str, value: str, title: str, body: str,
                  color: str = "var(--re)") -> html.Div:
    return html.Div([
        html.Div(f"FINDING #{number}", style={
            "fontSize": "9px", "textTransform": "uppercase", "letterSpacing": "0.05em",
            "color": "var(--t3)", "marginBottom": "6px",
        }),
        html.Div(value, style={
            "fontSize": "22px", "fontWeight": "500", "color": color,
            "marginBottom": "4px",
        }),
        html.Div(title, style={
            "fontSize": "12px", "fontWeight": "500", "color": "var(--t1)",
            "marginBottom": "8px",
        }),
        html.Div(body, style={"fontSize": "11.5px", "color": "var(--t2)", "lineHeight": "1.6"}),
    ], style={
        "flex": "1", "padding": "14px 16px",
        "borderTop": f"2px solid {color}",
        "border": "0.5px solid var(--b1)",
        "borderRadius": "0 0 7px 7px",
        "background": "var(--sf)",
    })


def _action_row(idx: int, text: str, owner: str, deadline: str,
                last: bool = False) -> html.Div:
    return html.Div([
        html.Div(str(idx), style={
            "width": "32px", "display": "flex", "alignItems": "center",
            "justifyContent": "center", "background": "var(--ra)",
            "borderRight": "0.5px solid var(--b1)", "fontFamily": "'DM Mono', monospace",
            "fontSize": "10px", "color": "var(--t3)", "flexShrink": "0",
        }),
        html.Div([
            html.Div(text, style={
                "fontSize": "12px", "color": "var(--t1)", "lineHeight": "1.5",
                "marginBottom": "2px",
            }),
            html.Div(f"Owner: {owner}", style={"fontSize": "10px", "color": "var(--t3)"}),
        ], style={"flex": "1", "padding": "10px 14px", "background": "var(--sf)"}),
        html.Div(deadline, style={
            "width": "110px", "background": "var(--ra)",
            "borderLeft": "0.5px solid var(--b1)", "display": "flex",
            "alignItems": "center", "justifyContent": "center",
            "padding": "0 10px", "textAlign": "center",
            "fontSize": "10px", "fontWeight": "500", "color": "var(--am)",
        }),
    ], style={
        "display": "flex", "borderBottom": "none" if last else "0.5px solid var(--b1)",
        "minHeight": "44px",
    })


def _sprint_summary(d: dict) -> html.Div:
    prev_m = d.get("prev_month_name", "April")
    p1_req_ids = d.get("p1_req_est_ids", [])
    p1_act_ids = d.get("p1_active_ids", [])

    kpi_cards = html.Div([
        _kpi_card(
            "ENHANCEMENTS DELIVERED",
            f"{d['enh_shipped']} / {d['enh_total']}",
            f"Day {d['sprint_day']} of {d['sprint_total_days']}. "
            f"{prev_m} delivered {d['prev_delivered']}/{d['prev_total']} "
            f"({d['prev_pct']}%). May is on track for zero — a full unaddressed regression.",
        ),
        _kpi_card(
            "PLANNING GATE COMPLIANCE",
            f"{d['gate_pct']}%",
            f"Not a single gate — DoR, story written, in-dev, in-QA — signed off "
            f"for any of the {d['enh_total']} May enhancements.",
        ),
        _kpi_card(
            "SCOPE INJECTION RATE",
            f"{d['scope_pct']}%",
            f"{d['scope_injected']} of {d['total_sprint_items']} items created after "
            f"May 1st. Sprint was not scoped at planning, demand loaded reactively.",
        ),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "12px"})

    finding_body_3 = (
        f"{d['overhead_hours']}h standalone overhead vs {d['feature_hours']}h feature work. "
        f"Three developers exceed their entire 180h monthly capacity on overhead alone "
        f"before any feature work is counted."
    )

    finding_cards = html.Div([
        _finding_card("1", f"{d['gate_pct']}%", "Gate Compliance",
            "Not a single planning gate has been signed off for any of the "
            f"{d['enh_total']} May enhancements. The lifecycle checklist is being "
            "bypassed entirely — not partially, entirely."),
        _finding_card("2", f"{d['enh_shipped']} / {d['enh_total']}", "Enhancements Delivered",
            f"Zero shipped with {d['days_left']} days remaining. {prev_m} delivered "
            f"{d['prev_pct']}%. May is on track for a clean zero — a significant "
            "regression that went unaddressed at sprint planning."),
        _finding_card("3", f"{d['overhead_pct']}%", "Capacity Lost to Overhead",
            finding_body_3, color="var(--am)"),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "16px"})

    # Build action text with chips for P1 bugs
    p1_chips = [_chip(i) for i, _ in p1_req_ids[:3]]
    p1_areas = list({a for _, a in p1_req_ids if a})
    area_str = f"({'/'.join(p1_areas[:2])})" if p1_areas else ""

    action1_children = [
        f"Resolve {len(p1_req_ids)} P1 bug{'s' if len(p1_req_ids) != 1 else ''} stuck in "
        f"\"Request Estimate\" — ",
        *p1_chips,
        f" {area_str}. P1s must be estimated or downgraded within 48 hours. "
        "They cannot be parked in Request Estimate state.",
    ]

    actions = html.Div([
        html.Div("IMMEDIATE ACTIONS REQUIRED", style={
            "fontSize": "9px", "textTransform": "uppercase", "letterSpacing": "0.05em",
            "color": "var(--t3)", "padding": "8px 14px",
            "borderBottom": "0.5px solid var(--b1)",
            "background": "var(--ra)",
        }),
        _action_row(1, action1_children if p1_req_ids else
                    "Resolve all P1 bugs stuck in Request Estimate state immediately.",
                    "Dev Lead", "48 hours"),
        _action_row(2,
            "Enforce DoR gate sign-off before any story enters Dev InProgress starting "
            "June sprint. Block stories at the tooling level if DoR = false — soft "
            "enforcement has not worked.",
            "Release Manager + Dev Lead", "June sprint start", last=True),
    ], style={
        "border": "0.5px solid var(--b1)", "borderRadius": "7px", "overflow": "hidden",
        "marginBottom": "14px",
    })

    return html.Div([
        html.Div([
            html.Span("⚡", style={"fontSize": "14px", "marginRight": "8px"}),
            html.Span("Sprint Summary", style={
                "fontSize": "14px", "fontWeight": "500", "color": "var(--t1)",
            }),
        ], style={"display": "flex", "alignItems": "center",
                  "marginBottom": "14px", "paddingTop": "24px"}),
        kpi_cards,
        finding_cards,
        actions,
    ])


def _section_20(d: dict) -> html.Div:
    # Mini stat bar
    mini_stats = html.Div([
        _mini_stat(str(d["total_sprint_items"]), "TOTAL ITEMS"),
        _mini_stat(str(d["items_closed"]),          "CLOSED",              "var(--am)"),
        _mini_stat(str(d.get("inflight_total", 0)), "DEV COMPLETE / REVIEW", "var(--am)"),
        _mini_stat(str(d["p1_open"]),            "P1 BUGS OPEN",        "var(--re)"),
        _mini_stat(str(d["enh_shipped"]),        "ENHANCEMENTS SHIPPED", "var(--re)" if d["enh_shipped"] == 0 else "var(--gr)"),
        _mini_stat(d["days_left_approx"],        "WORKING DAYS LEFT"),
    ], style={
        "display": "flex", "border": "0.5px solid var(--b1)",
        "borderRadius": "7px", "overflow": "hidden", "marginBottom": "14px",
    })

    # State breakdown: two columns
    enh_rows = [
        ("Not Required (dropped)",  d["enh_not_required"], None),
        ("New (not started)",       d["enh_new"],          None),
        ("Clarification (blocked)", d["enh_clarif"],       "var(--am)" if d["enh_clarif"] > 0 else None),
        ("Dev InProgress",          d["enh_devip"],        "var(--am)" if d["enh_devip"] > 0 else None),
        ("Dev Review",              d["enh_devrev"],       "var(--am)" if d["enh_devrev"] > 0 else None),
        ("Dev Complete (awaiting QA)", d["enh_devcomp"],   "var(--am)" if d["enh_devcomp"] > 0 else None),
        ("Delivered (Closed)",      d["enh_delivered"],    "var(--re)" if d["enh_delivered"] == 0 else "var(--gr)"),
    ]
    bugs_total = d["bugs_total"]
    bug_rows = [
        ("Closed",                  d["bugs_closed"],    "var(--t1)", f"({round(d['bugs_closed']/bugs_total*100) if bugs_total else 0}%)"),
        ("Resolved / Not an issue", d["bugs_resolved"],  None, None),
        ("Dev Complete / Review",   d["bugs_inflight"],  "var(--am)" if d["bugs_inflight"] > 0 else None, None),
        ("Clarification",           d["bugs_clarif"],    "var(--am)" if d["bugs_clarif"] > 0 else None, None),
        ("Request Estimate (blocked)", d["bugs_req_est"],"var(--re)" if d["bugs_req_est"] > 0 else None, None),
        ("Active / New",            d["bugs_active"],    None, None),
        ("Watch List",              d["bugs_watchlist"], None, None),
    ]

    def _state_row(label, val, color=None, extra=None, last=False):
        return html.Tr([
            html.Td(label, style={
                "padding": "7px 12px", "fontSize": "12px", "color": "var(--t1)",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
            html.Td([
                html.Span(str(val), style={"color": color or "var(--t1)", "fontWeight": "500"}),
                html.Span(f" {extra}", style={"fontSize": "10px", "color": "var(--t3)"}) if extra else None,
            ], style={
                "padding": "7px 12px", "fontSize": "12px", "textAlign": "right",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
        ])

    breakdown_table = html.Div([
        html.Table([
            html.Thead(html.Tr([
                html.Th(f"ENHANCEMENTS ({d['enh_total']} TOTAL)",
                        colSpan=2, style={**_th_style("50%"), "color": "var(--t3)"}),
                html.Th(f"BUGS ({d['bugs_total']} TOTAL)",
                        colSpan=2, style={**_th_style("50%"), "color": "var(--t3)",
                                          "borderLeft": "1px solid var(--b1)"}),
            ]), style={"background": "var(--ra)", "borderBottom": "0.5px solid var(--b1)"}),
            html.Tbody([
                html.Tr([
                    html.Td(
                        html.Table([
                            html.Tbody([_state_row(r[0], r[1], r[2], None, i == len(enh_rows)-1)
                                        for i, r in enumerate(enh_rows)])
                        ], style={"width": "100%", "borderCollapse": "collapse"}),
                        style={"verticalAlign": "top", "width": "50%",
                               "borderBottom": "none"}
                    ),
                    html.Td(
                        html.Table([
                            html.Tbody([_state_row(r[0], r[1], r[2], r[3], i == len(bug_rows)-1)
                                        for i, r in enumerate(bug_rows)])
                        ], style={"width": "100%", "borderCollapse": "collapse"}),
                        style={"verticalAlign": "top", "width": "50%",
                               "borderLeft": "1px solid var(--b1)", "borderBottom": "none"}
                    ),
                ])
            ]),
        ], style={"width": "100%", "borderCollapse": "collapse"}),
    ], style={"border": "0.5px solid var(--b1)", "borderRadius": "7px",
              "overflow": "hidden", "marginBottom": "14px"})

    # Progress bars
    prev_m = d.get("prev_month_name", "April")
    progress_bars = html.Div([
        _progress_bar(f"Bug close rate ({d['bugs_closed']}/{d['bugs_total']})",
                      d["bugs_closed"], d["bugs_total"], d["bug_close_rate"], "var(--am)"),
        _progress_bar(f"Enhancement delivery ({d['enh_shipped']}/{d['enh_total']})",
                      d["enh_shipped"], d["enh_total"], 0 if d["enh_shipped"] == 0 else
                      round(d["enh_shipped"]/d["enh_total"]*100), "var(--re)"),
        _progress_bar(f"Estimation compliance ({d['active_nontas'] - d['unestimated']}/{d['active_nontas']})",
                      d["active_nontas"] - d["unestimated"], d["active_nontas"],
                      d["estimation_pct"], "var(--ac)"),
        _progress_bar(f"Gate compliance (0/{d['enh_total']})",
                      0, d["enh_total"], 0, "var(--re)"),
        _progress_bar(f"Checklist adherence ({d['checklist_with']}/{d['enh_total']})",
                      d["checklist_with"], d["enh_total"], d["checklist_pct"], "var(--re)"),
        _progress_bar(f"{prev_m} reference — enh delivered ({d['prev_delivered']} / {d['prev_total']})",
                      d["prev_delivered"], d["prev_total"], d["prev_pct"], "var(--gr)"),
    ], style={"padding": "14px 16px", "border": "0.5px solid var(--b1)",
              "borderRadius": "7px", "background": "var(--sf)", "marginBottom": "14px"})

    return html.Div([
        html.Div(style={"paddingTop": "24px"}),
        _section_header("2.0", "Sprint Composition & Progress"),
        mini_stats,
        breakdown_table,
        progress_bars,
    ])


def _mini_stat(value: str, label: str, color: str = "var(--t1)") -> html.Div:
    return html.Div([
        html.Div(value, style={
            "fontSize": "18px", "fontWeight": "500", "color": color,
            "fontVariantNumeric": "tabular-nums",
        }),
        html.Div(label, style={
            "fontSize": "9px", "textTransform": "uppercase",
            "letterSpacing": "0.04em", "color": "var(--t3)",
        }),
    ], style={
        "flex": "1", "padding": "12px", "background": "var(--sf)",
        "borderRight": "0.5px solid var(--b1)", "display": "flex",
        "flexDirection": "column", "gap": "3px",
    })


def _section_21(d: dict) -> html.Div:
    rows = [
        _metric_row("Sprint completion rate (closed / committed)", ">90%",
                    d["v_sprint_comp"],
                    f"RED — {d['sprint_close_pct']}%",
                    f"{d['items_closed']} items closed out of {d['total_sprint_items']} committed "
                    f"at Day {d['sprint_day']} of {d['sprint_total_days']}. "
                    "Even accounting for items in-flight, full completion is not achievable before sprint end."),
        _metric_row("Enhancement delivery rate", "100%",
                    d["v_enh_delivery"],
                    f"RED — {d['enh_shipped']}/{d['enh_total']}",
                    f"No enhancement has reached Closed state. {d['enh_devcomp']} in Dev Complete awaiting QA "
                    f"— with full QA + sign-off cycles needed in {d['days_left']} days, full delivery is extremely unlikely."),
        _metric_row("Spillover risk", "<10%",
                    d["v_spillover"],
                    "RED — HIGH",
                    f"All {d['enh_total']} enhancements at risk of spillover. "
                    f"{d.get('prev_month_name', 'April')} comparison: "
                    f"{d['prev_delivered']}/{d['prev_total']} ({d['prev_pct']}%). "
                    "The regression went unaddressed at sprint planning."),
        _metric_row("Mid-sprint scope injection", "0%",
                    d["v_scope_inj"],
                    f"RED — {d['scope_pct']}%",
                    f"{d['scope_injected']} items created after 1 May 2026. "
                    "No scope freeze policy is in operation. Sprint capacity is being diluted continuously, "
                    f"competing with the {d['scope_injected']} items already in-flight.",
                    last=True),
    ]
    return html.Div([
        html.Div(style={"paddingTop": "24px"}),
        _section_header("2.1", "Delivery Health", "RED"),
        _metric_table(rows),
    ])


def _section_22(d: dict) -> html.Div:
    p1_req_ids = d.get("p1_req_est_ids", [])
    p1_act_ids = d.get("p1_active_ids", [])
    p1_inf     = d.get("p1_inflight", [])

    # Mini stat cards
    mini_cards = html.Div([
        html.Div([
            html.Div("P1 BUGS STILL OPEN", style={
                "fontSize": "9px", "textTransform": "uppercase",
                "letterSpacing": "0.04em", "color": "var(--t3)", "marginBottom": "4px",
            }),
            html.Div(str(d["p1_open"]), style={
                "fontSize": "28px", "fontWeight": "500", "color": "var(--re)",
            }),
            html.Div(f"{len(p1_req_ids)} blocked in Request Estimate — cannot be worked",
                     style={"fontSize": "11px", "color": "var(--t3)"}),
        ], style={"flex": "1", "padding": "14px", "borderRight": "0.5px solid var(--b1)"}),
        html.Div([
            html.Div("ITEMS UNESTIMATED", style={
                "fontSize": "9px", "textTransform": "uppercase",
                "letterSpacing": "0.04em", "color": "var(--t3)", "marginBottom": "4px",
            }),
            html.Div(str(d["unestimated"]), style={
                "fontSize": "28px", "fontWeight": "500", "color": "var(--am)",
            }),
            html.Div(f"{d['req_est_stuck']} stuck in Request Estimate state at Day {d['sprint_day']}",
                     style={"fontSize": "11px", "color": "var(--t3)"}),
        ], style={"flex": "1", "padding": "14px", "borderRight": "0.5px solid var(--b1)"}),
        html.Div([
            html.Div("CAPACITY LOST TO OVERHEAD", style={
                "fontSize": "9px", "textTransform": "uppercase",
                "letterSpacing": "0.04em", "color": "var(--t3)", "marginBottom": "4px",
            }),
            html.Div(f"{d['overhead_pct']}%", style={
                "fontSize": "28px", "fontWeight": "500", "color": "var(--am)",
            }),
            html.Div(f"{d['overhead_hours']}h overhead vs {d['feature_hours']}h feature work team-wide",
                     style={"fontSize": "11px", "color": "var(--t3)"}),
        ], style={"flex": "1", "padding": "14px"}),
    ], style={
        "display": "flex", "border": "0.5px solid var(--b1)", "borderRadius": "7px",
        "overflow": "hidden", "marginBottom": "14px", "background": "var(--sf)",
    })

    # Build P1 open detail
    def _id_list(id_tuples):
        out = []
        for wid, area in id_tuples[:6]:
            out.append(_chip(wid))
        return out

    req_est_note = [
        f"Open P1s: ",
        *_id_list(p1_req_ids),
        f" (Request Estimate — {'/'.join({a for _,a in p1_req_ids if a})}); ",
        *_id_list(p1_act_ids),
        f" (Active/Clarification); ",
        *_id_list(p1_inf[:3]),
        " (Dev Review, not closed).",
    ]

    rows = [
        _metric_row("P1 bugs resolved before sprint end", "100%",
                    d["v_p1"],
                    f"RED — {d['p1_open']} open",
                    note_children=req_est_note if d["p1_open"] > 0 else None,
                    note=None if d["p1_open"] > 0 else "All P1 bugs resolved."),
        _metric_row("P1 bugs stuck without estimate", "0",
                    d["v_p1_req_est"],
                    f"RED — {len(p1_req_ids)} items" if p1_req_ids else "GREEN",
                    note_children=[
                        *[_chip(i) for i, _ in p1_req_ids],
                        " (all Credit Card/Xero). P1 classification requires estimate before "
                        "Dev assignment per triage framework — these are a direct contradiction.",
                    ] if p1_req_ids else None,
                    note="No P1 bugs stuck without estimate." if not p1_req_ids else None),
        _metric_row("Mid-sprint PO/P1 interruptions", "Track trend",
                    "AMBER",
                    "AMBER",
                    f"{d['scope_injected']} items injected mid-sprint; P0/P1 classification at injection "
                    "not recorded with timestamps — triage SLA cannot be computed. Gap in triage audit trail."),
        _metric_row("Overhead vs capacity (May, team-wide)", "Track",
                    d["v_overhead"],
                    "AMBER",
                    f"{d['overhead_hours']}h standalone overhead tasks vs {d['feature_hours']}h committed "
                    f"feature work across 10 developers. Overhead consuming {d['overhead_pct']}% of team capacity. "
                    "Notable: Jyoti Dahiya 291h, Pranjal Jindal 188h, Shivi Prajapati 161h — "
                    "all exceeding 180h monthly capacity before feature work is counted.",
                    last=True),
    ]
    return html.Div([
        html.Div(style={"paddingTop": "24px"}),
        _section_header("2.2", "Priority & Capacity Discipline", "RED"),
        mini_cards,
        _metric_table(rows),
    ])


def _section_23(d: dict) -> html.Div:
    rows = [
        _metric_row("Story Completion Checklist compliance", ">90%",
                    d["v_checklist"],
                    f"RED — {d['checklist_pct']}%",
                    f"{d['checklist_with']}/{d['enh_total']} enhancements have any tracker steps. "
                    "The remaining have zero recorded lifecycle activity."),
        _metric_row("Planning gate compliance (DoR / story-written / in-dev)", ">90%",
                    d["v_gate"],
                    f"RED — {d['gate_pct']}%",
                    note_children=[
                        f"0/{d['enh_total']} enhancements have any ",
                        _code("p_planning_gates"),
                        " field populated. No DoR, no story-written sign-off, "
                        "no in-dev gate recorded for any May enhancement.",
                    ]),
        _metric_row("Estimation compliance (active items)", ">95%",
                    d["v_estimation"],
                    f"AMBER — {d['estimation_pct']}%",
                    f"{d['active_nontas'] - d['unestimated']}/{d['active_nontas']} active items estimated. "
                    f"{d['unestimated']} unestimated: {d['req_est_stuck']} stuck in Request Estimate state, "
                    "remainder entered sprint without an estimate."),
        _metric_row("Maker Time violations", "<2/person/wk",
                    "UNKNOWN",
                    "UNKNOWN",
                    f"Not tracked. The {d['overhead_hours']}h overhead total suggests significant "
                    "non-feature activity but session-level Maker Time data is not captured in the system."),
        _metric_row("QA rework rate", "<15%",
                    d["v_qa_rework"],
                    f"AMBER — {d['qa_rework_pct']}%",
                    f"{d['bugs_clarif']} items in Clarification ({d['qa_rework_pct']}% of {d['total_sprint_items']}). "
                    "Within target directionally; full rework cycle data not available per item.",
                    last=True),
    ]
    return html.Div([
        html.Div(style={"paddingTop": "24px"}),
        _section_header("2.3", "Process Adherence & Working Rhythm", "RED"),
        _metric_table(rows),
    ])


def _section_24(d: dict) -> html.Div:
    prev_m = d.get("prev_month_name", "April")
    rows_data = [
        ("Planning honesty", "RED",
         f"{d['scope_injected']} of {d['total_sprint_items']} sprint items were created after sprint start. "
         "The sprint was not genuinely scoped at planning — demand is being loaded reactively throughout "
         "the iteration. This undermines capacity planning and commitment reliability."),
        ("Triage discipline", "RED",
         f"{len(d.get('p1_req_est_ids', []))} P1 bugs remain in \"Request Estimate\" state. P1 classification "
         "is being applied without completing mandatory triage (estimate before Dev assignment). "
         "P1 without an estimate is a contradiction in the priority framework."),
        ("Maker Time culture", "UNKNOWN",
         f"Not measurable from current system data. High standalone overhead ({d['overhead_hours']}h team-wide) "
         "suggests significant non-feature activity, but session-level interruption tracking is not in place."),
        ("Retrospective quality", "UNKNOWN",
         f"No retrospective action log found in system. {_code_str('p_audit_log')} has only 5 entries total. "
         f"{prev_m}'s lower-but-nonzero delivery rate ({d['prev_pct']}%) vs May's 0% suggests lessons from "
         f"{prev_m} were not actioned at sprint planning."),
        ("Process ownership", "RED",
         f"{d['enh_total'] - d['checklist_with']}/{d['enh_total']} enhancements have zero lifecycle tracking steps. "
         "The Story Completion Checklist and planning gates are not being enforced as entry criteria — "
         "process ownership has broken down at the team level."),
        ("Critical thinking", "AMBER",
         f"{prev_m} delivered {d['prev_delivered']}/{d['prev_total']} ({d['prev_pct']}%). May is on track for "
         f"0/{d['enh_total']} with no evidence of root cause analysis between sprints. The regression was "
         "visible and went unaddressed at sprint planning."),
    ]

    qual_rows = []
    for i, (area, verdict, obs) in enumerate(rows_data):
        last = (i == len(rows_data) - 1)
        qual_rows.append(html.Tr([
            html.Td(area, style={
                "width": "18%", "padding": "10px 12px", "fontSize": "12px",
                "fontWeight": "500", "color": "var(--t1)", "verticalAlign": "top",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
            html.Td(_badge(verdict), style={
                "width": "9%", "padding": "10px 12px", "verticalAlign": "top",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
            html.Td(obs, style={
                "width": "73%", "padding": "10px 12px", "fontSize": "11.5px",
                "color": "var(--t2)", "lineHeight": "1.6", "verticalAlign": "top",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
        ], style={"background": "var(--sf)"}))

    table = html.Div(html.Table([
        html.Thead(html.Tr([
            html.Th("AREA",        style=_th_style("18%")),
            html.Th("RATING",      style=_th_style("9%")),
            html.Th("OBSERVATION", style=_th_style("73%")),
        ]), style={"background": "var(--ra)", "borderBottom": "0.5px solid var(--b1)"}),
        html.Tbody(qual_rows),
    ], style={"width": "100%", "borderCollapse": "collapse"}),
    style={"border": "0.5px solid var(--b1)", "borderRadius": "7px",
           "overflow": "hidden", "marginBottom": "14px"})

    return html.Div([
        html.Div(style={"paddingTop": "24px"}),
        _section_header("2.4", "Qualitative — Team Discipline & Behaviour"),
        table,
    ])


def _code_str(t):
    return t  # plain text fallback for inside strings


def _section_25(d: dict) -> html.Div:
    v = d["overall_verdict"]
    vs = _rag_styles(v)
    return html.Div([
        html.Div(style={"paddingTop": "24px"}),
        _section_header("2.5", "Iteration Verdict"),
        html.Div([
            html.Div(
                f"ITERATION {d['ym_str'][:4]} {d['ym_str'][5:].zfill(2).upper()} · OVERALL RATING",
                style={"fontSize": "9px", "textTransform": "uppercase",
                       "letterSpacing": "0.05em", "color": "var(--t3)", "marginBottom": "8px"}
            ),
            html.Div([
                html.Span("●", style={"fontSize": "9px", "color": vs["color"],
                                      "marginRight": "6px"}),
                html.Span(v, style={"fontSize": "20px", "fontWeight": "500",
                                    "color": vs["color"]}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "12px"}),
            html.Div([
                _verdict_count("KPIS CONFIRMED RED",    str(d["kpis_red"]),   "var(--re)"),
                _verdict_count("KPIS AMBER",             str(d["kpis_amber"]), "var(--am)"),
                _verdict_count("QUALITATIVE RED FLAGS",  str(d["qual_red"]),   "var(--re)"),
                _verdict_count("DATA GAPS",              str(d["data_gaps"]),  "var(--t3)"),
            ], style={
                "display": "flex", "gap": "24px", "marginBottom": "12px",
                "paddingBottom": "12px", "borderBottom": "0.5px solid var(--b1)",
            }),
            html.Div(d["verdict_paragraph"], style={
                "fontSize": "12px", "color": "var(--t2)", "lineHeight": "1.65",
            }),
        ], style={
            "border": "0.5px solid var(--re-bd)",
            "borderLeft": "3px solid var(--re)",
            "borderRadius": "0 7px 7px 0",
            "background": "var(--sf)", "padding": "16px 20px", "marginBottom": "18px",
        }),
    ])


def _verdict_count(label: str, value: str, color: str) -> html.Div:
    return html.Div([
        html.Div(label, style={
            "fontSize": "9px", "textTransform": "uppercase",
            "letterSpacing": "0.04em", "color": "var(--t3)",
        }),
        html.Div(value, style={
            "fontSize": "18px", "fontWeight": "500",
            "color": color, "fontVariantNumeric": "tabular-nums",
        }),
    ])


def _data_gaps(d: dict) -> html.Div:
    gap_rows = []
    for i, row in enumerate(d.get("data_gaps_rows", [])):
        last = (i == len(d["data_gaps_rows"]) - 1)
        sev_color = ("var(--re)" if row["severity"] == "red" else
                     "var(--am)" if row["severity"] == "amber" else "var(--t2)")
        gap_rows.append(html.Tr([
            html.Td(row["gap"], style={
                "width": "28%", "padding": "10px 12px", "fontSize": "12px",
                "color": sev_color, "fontWeight": "500", "verticalAlign": "top",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
            html.Td(row["table_field"], style={
                "width": "24%", "padding": "10px 12px",
                "fontFamily": "'DM Mono', monospace", "fontSize": "11px",
                "color": "var(--t3)", "verticalAlign": "top",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
            html.Td(row["consequence"], style={
                "width": "48%", "padding": "10px 12px", "fontSize": "11.5px",
                "color": "var(--t3)", "verticalAlign": "top", "lineHeight": "1.55",
                "borderBottom": "none" if last else "0.5px solid var(--b1)",
            }),
        ], style={"background": "var(--sf)"}))

    table = html.Div(html.Table([
        html.Thead(html.Tr([
            html.Th("GAP",          style=_th_style("28%")),
            html.Th("TABLE / FIELD", style=_th_style("24%")),
            html.Th("CONSEQUENCE",  style=_th_style("48%")),
        ]), style={"background": "var(--ra)", "borderBottom": "0.5px solid var(--b1)"}),
        html.Tbody(gap_rows),
    ], style={"width": "100%", "borderCollapse": "collapse"}),
    style={"border": "0.5px solid var(--b1)", "borderRadius": "7px",
           "overflow": "hidden"})

    return html.Div([
        html.Div(style={"paddingTop": "24px"}),
        html.Div([
            html.Span("◎", style={"fontSize": "12px", "color": "var(--t3)",
                                   "marginRight": "8px"}),
            html.Span("Data Gaps Specific to Iteration Audit", style={
                "fontSize": "13px", "fontWeight": "500", "color": "var(--t1)",
            }),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"}),
        html.Div(
            "These gaps prevent full measurement. Each represents a decision not to record.",
            style={"fontSize": "12px", "color": "var(--t2)", "marginBottom": "12px"}
        ),
        table,
    ])


def _footer(d: dict) -> html.Div:
    return html.Div([
        html.Span("Expense On Demand · Iteration Audit · Internal Confidential",
                  style={"fontSize": "10px", "color": "var(--t3)",
                         "letterSpacing": "0.02em"}),
        html.Span(f"Generated from Azure DevOps live sync · {d.get('snapshot_date', '')}",
                  style={"fontSize": "10px", "color": "var(--t3)",
                         "letterSpacing": "0.02em"}),
    ], style={
        "borderTop": "0.5px solid var(--b1)", "padding": "14px 40px",
        "display": "flex", "justifyContent": "space-between",
        "background": "var(--sf)", "marginTop": "24px",
    })


# ── Main layout builder ───────────────────────────────────────────────────────

def build_layout(d: dict) -> html.Div:
    return html.Div([
        _cover(d),
        _stats_strip(d),
        html.Div([
            _sprint_summary(d),
            _section_20(d),
            _section_21(d),
            _section_22(d),
            _section_23(d),
            _section_24(d),
            _section_25(d),
            _data_gaps(d),
        ], style={"padding": "0 40px"}),
        _footer(d),
    ], style={"background": "var(--bg)", "minHeight": "100vh"})


def layout(**_):
    d = get_iteration_audit_data("May", 2026)
    return build_layout(d)
