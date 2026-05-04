"""
reports/formatter.py
Turns summary dicts from summarizer.py into Dash HTML components for the report modal.
"""

from dash import html
import dash_bootstrap_components as dbc


# ── Palette ───────────────────────────────────────────────────────────────────
_C = {
    "good":    "#34d399",   # green
    "warn":    "#fbbf24",   # amber
    "bad":     "#f87171",   # red
    "neutral": "#8892a4",   # grey
    "purple":  "#818cf8",
    "text":    "#e2e8f0",
    "subtext": "#8892a4",
    "bg":      "rgba(255,255,255,0.03)",
    "border":  "rgba(255,255,255,0.07)",
}

_RAG = {
    "green": _C["good"],
    "amber": _C["warn"],
    "red":   _C["bad"],
    "grey":  _C["neutral"],
}


# ── Micro-components ──────────────────────────────────────────────────────────

def _section(title, children):
    return html.Div([
        html.Div(title, style={
            "fontSize": "11px", "fontWeight": "700", "textTransform": "uppercase",
            "letterSpacing": "0.7px", "color": _C["purple"],
            "marginBottom": "10px", "marginTop": "18px",
            "borderBottom": f"1px solid {_C['border']}", "paddingBottom": "6px",
        }),
        *children,
    ])


def _row(label, value, color=None, subtext=None):
    return html.Div([
        html.Span(label, style={"color": _C["subtext"], "fontSize": "12px", "flex": "1"}),
        html.Div([
            html.Span(value, style={
                "color": color or _C["text"], "fontWeight": "600", "fontSize": "13px",
            }),
            html.Span(f"  {subtext}", style={"color": _C["subtext"], "fontSize": "11px"}) if subtext else None,
        ], style={"textAlign": "right"}),
    ], style={
        "display": "flex", "justifyContent": "space-between", "alignItems": "center",
        "padding": "5px 0", "borderBottom": f"1px solid rgba(255,255,255,0.03)",
    })


def _rag_dot(status):
    c = _RAG.get(status, _C["neutral"])
    return html.Span(style={
        "display": "inline-block", "width": "8px", "height": "8px",
        "borderRadius": "50%", "background": c, "marginRight": "6px",
        "flexShrink": "0",
    })


def _suggestion(icon, text):
    return html.Div([
        html.Span(icon, style={"marginRight": "8px", "fontSize": "14px"}),
        html.Span(text, style={"fontSize": "12px", "color": _C["text"], "lineHeight": "1.5"}),
    ], style={
        "display": "flex", "alignItems": "flex-start",
        "padding": "8px 12px", "marginBottom": "6px",
        "background": "rgba(129,140,248,0.07)", "borderRadius": "8px",
        "border": f"1px solid rgba(129,140,248,0.15)",
    })


def _metric_badge(value, label, color):
    return html.Div([
        html.Div(value, style={"fontSize": "22px", "fontWeight": "700", "color": color}),
        html.Div(label, style={"fontSize": "10px", "color": _C["subtext"], "textTransform": "uppercase",
                               "letterSpacing": "0.5px", "marginTop": "2px"}),
    ], style={
        "background": _C["bg"], "border": f"1px solid {_C['border']}",
        "borderRadius": "10px", "padding": "12px 16px", "textAlign": "center",
        "flex": "1", "minWidth": "100px",
    })


def _vs_target(now_val, target_str, is_good):
    c = _C["good"] if is_good else _C["bad"]
    arrow = "▼" if is_good else "▲"
    return html.Span([
        html.Span(f"  {arrow} target: {target_str}",
                  style={"fontSize": "10px", "color": c, "marginLeft": "6px"}),
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# BUGS BOARD
# ═══════════════════════════════════════════════════════════════════════════════

def format_bugs(s: dict) -> html.Div:
    T = s["targets"]

    def _color(val, tgt, lower=True):
        if val is None: return _C["neutral"]
        return _C["good"] if (val <= tgt if lower else val >= tgt) else _C["bad"]

    # Top KPI strip
    kpis = html.Div([
        _metric_badge(str(s["total_open"]),
                      "Open Bugs",
                      _color(s["total_open"], T["open_bug_backlog"])),
        _metric_badge(str(s["open_p1"]),
                      "Critical Open",
                      _color(s["open_p1"], T["open_critical_bugs"])),
        _metric_badge(f"{s['escape_rate_pct']}%",
                      "Escape Rate",
                      _color(s["escape_rate_pct"], T["defect_escape_rate_pct"])),
        _metric_badge(f"{s['enh_bug_ratio']}:1",
                      "Enh:Bug Ratio",
                      _color(s["enh_bug_ratio"], T["enh_bug_ratio"], lower=False)),
    ], style={"display": "flex", "gap": "10px", "marginBottom": "4px", "flexWrap": "wrap"})

    # Open bugs detail
    open_detail = _section("Open Bug Backlog", [
        _row("Total open",   str(s["total_open"]),  _color(s["total_open"], T["open_bug_backlog"])),
        _row("P1 Critical",  str(s["open_p1"]),     _color(s["open_p1"],    T["open_critical_bugs"])),
        _row("P2 High",      str(s["open_p2"]),     _C["warn"] if s["open_p2"] > 0 else _C["good"]),
        _row("P3 Medium",    str(s["open_p3"]),     _C["text"]),
        _row("P4 Low",       str(s["open_p4"]),     _C["subtext"]),
    ])

    # Escape rate
    stage_detail = _section("Defect Escape Rate", [
        _row("Found in Dev",      f"{s['dev_bugs']} bugs",  _C["good"]),
        _row("Found in QA",       f"{s['qa_bugs']} bugs",   _C["text"]),
        _row("Escaped to PROD",   f"{s['prod_bugs']} bugs ({s['escape_rate_pct']}%)",
             _color(s["escape_rate_pct"], T["defect_escape_rate_pct"]),
             f"target <{T['defect_escape_rate_pct']}%"),
    ])

    # Customer issues
    cust_detail = _section("Customer Issues", [
        _row("Open customer bugs",    str(s["customer_open"]),
             _color(s["customer_open"], T["customer_open_bugs"]),
             f"target <{T['customer_open_bugs']}"),
        _row("Customer % of PROD bugs", f"{s['customer_pct_prod']}%", _C["text"]),
        _row("All-time customer bugs",  str(s["customer_total"]),     _C["subtext"]),
    ])

    # MTTC
    mttc_rows = []
    labels = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
    tgt_map = {1: T["mttc_critical_days"], 2: T["mttc_high_days"], 3: T["mttc_medium_days"]}
    for p in [1, 2, 3, 4]:
        med, mean, n = s["mttc"].get(p, (None, None, 0))
        if med is None or n == 0:
            continue
        tgt = tgt_map.get(p)
        c   = _color(med, tgt) if tgt else _C["text"]
        t   = f"target <{tgt}d" if tgt else None
        mttc_rows.append(_row(f"{labels[p]} (n={n})", f"median {int(med)}d / mean {int(mean)}d", c, t))
    mttc_section = _section("Mean Time to Close", mttc_rows)

    # Iteration trend
    iter_rows = []
    if s["avg_per_iter"] is not None:
        iter_rows.append(_row("Avg bugs per iteration", str(int(s["avg_per_iter"])),
                              _color(s["avg_per_iter"], T["bugs_per_iter"]),
                              f"target <{T['bugs_per_iter']}"))
        iter_rows.append(_row("Worst iteration", f"{s['worst_iter']}  ({s['worst_iter_n']} bugs)", _C["warn"]))
    iter_rows.append(_row("Enh:Bug ratio", f"{s['enh_bug_ratio']}:1",
                          _color(s["enh_bug_ratio"], T["enh_bug_ratio"], lower=False),
                          f"target ≥{T['enh_bug_ratio']}:1"))
    if s["trend_pct"] is not None:
        trend_c = _C["good"] if s["trend_pct"] < 0 else _C["bad"]
        trend_arrow = "▼" if s["trend_pct"] < 0 else "▲"
        iter_rows.append(_row("Bug creation trend (30d)",
                              f"{trend_arrow} {abs(s['trend_pct'])}% vs prior 30d", trend_c))
    iter_section = _section("Trend & Velocity", iter_rows)

    # Suggestions
    suggestions = []
    if s["escape_rate_pct"] > T["defect_escape_rate_pct"]:
        suggestions.append(_suggestion("🚨", (
            f"Defect escape rate is {s['escape_rate_pct']}% — "
            f"{round(s['escape_rate_pct']/T['defect_escape_rate_pct'],1)}× above target. "
            "Introduce a mandatory QA sign-off gate before PROD deployments."
        )))
    if s["open_p1"] > T["open_critical_bugs"]:
        suggestions.append(_suggestion("🔥", (
            f"{s['open_p1']} critical (P1) bugs are open — target is <{T['open_critical_bugs']}. "
            "Schedule a P1 war-room to clear these before the next release."
        )))
    if s["customer_open"] > T["customer_open_bugs"]:
        suggestions.append(_suggestion("👥", (
            f"{s['customer_open']} customer-reported issues still open. "
            "Prioritise the customer queue in the next two sprints to protect NPS."
        )))
    if s["enh_bug_ratio"] < T["enh_bug_ratio"]:
        suggestions.append(_suggestion("⚖️", (
            f"Enhancement-to-Bug ratio is {s['enh_bug_ratio']}:1 (target ≥1:1). "
            "Allocate at least 50% of sprint capacity to feature work to rebalance the product roadmap."
        )))
    mttc_crit = s["mttc"].get(1, (None, None, 0))
    if mttc_crit[0] and mttc_crit[0] > T["mttc_critical_days"]:
        suggestions.append(_suggestion("⏱️", (
            f"Critical bug MTTC is {int(mttc_crit[0])}d — target is <{T['mttc_critical_days']}d. "
            "Set up same-day triage and dedicated on-call rotation for P1 issues."
        )))
    if s["avg_per_iter"] and s["avg_per_iter"] > T["bugs_per_iter"]:
        suggestions.append(_suggestion("📉", (
            f"Averaging {int(s['avg_per_iter'])} bugs per iteration (target <{T['bugs_per_iter']}). "
            "Run root-cause analysis on the top defect injection areas and add unit tests."
        )))
    if not suggestions:
        suggestions.append(_suggestion("✅", "All key metrics are within target. Keep monitoring for regression."))

    sugg_section = _section("Recommendations", suggestions)

    return html.Div([
        kpis, open_detail, stage_detail, cust_detail, mttc_section, iter_section, sugg_section,
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# QA HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

def format_qa(s: dict) -> html.Div:
    T = s["targets"]

    def _color(val, tgt, lower=True):
        if val is None: return _C["neutral"]
        return _C["good"] if (val <= tgt if lower else val >= tgt) else _C["bad"]

    kpis = html.Div([
        _metric_badge(str(s["open_bugs"]), "Open Bugs", _C["text"]),
        _metric_badge(f"{s['overall_breach_pct']}%", "SLA Breach Rate",
                      _color(s["overall_breach_pct"], T["sla_breach_rate_pct"])),
        _metric_badge(f"{s['rejection_rate']}%", "Bug Rejection Rate", _C["text"]),
        _metric_badge(str(s["reopened_count"]), "Reopened", _C["warn"] if s["reopened_count"] > 0 else _C["good"]),
    ], style={"display": "flex", "gap": "10px", "marginBottom": "4px", "flexWrap": "wrap"})

    sla_rows = []
    labels = {1: "P1 Critical", 2: "P2 High", 3: "P3 Medium", 4: "P4 Low"}
    for p in [1, 2, 3, 4]:
        if p not in s["sla_compliance"]:
            continue
        sc = s["sla_compliance"][p]
        c  = _color(sc["breach_pct"], T["sla_breach_rate_pct"])
        sla_rows.append(_row(
            labels[p],
            f"{sc['breaches']}/{sc['total']} breached ({sc['breach_pct']}%)",
            c,
            f"SLA = {sc['sla_target']}d"
        ))
    sla_section = _section("SLA Compliance by Priority", sla_rows)

    assignee_rows = [
        _row(name, f"{count} open bugs", _C["warn"] if count > 10 else _C["text"])
        for name, count in list(s["assignee_load"].items())[:5]
    ] if s["assignee_load"] else [html.Div("No data", style={"color": _C["subtext"], "fontSize": "12px"})]
    assignee_section = _section("Heaviest Open-Bug Load", assignee_rows)

    # Suggestions
    suggestions = []
    if s["overall_breach_pct"] > T["sla_breach_rate_pct"]:
        suggestions.append(_suggestion("⏱️", (
            f"SLA breach rate is {s['overall_breach_pct']}% — target <{T['sla_breach_rate_pct']}%. "
            "Review triage process: ensure P1s are assigned within 1 hour of creation."
        )))
    if s["reopened_count"] > 5:
        suggestions.append(_suggestion("🔁", (
            f"{s['reopened_count']} bugs have been reopened. "
            "Add a peer verification step before marking bugs as Closed to reduce rework."
        )))
    if s["rejection_rate"] > 15:
        suggestions.append(_suggestion("❌", (
            f"{s['rejection_rate']}% of bugs are rejected (Not an issue / Not Required). "
            "Improve bug reporting templates to reduce invalid tickets."
        )))
    if not suggestions:
        suggestions.append(_suggestion("✅", "QA SLA metrics are within acceptable range."))
    sugg_section = _section("Recommendations", suggestions)

    return html.Div([kpis, sla_section, assignee_section, sugg_section])


# ═══════════════════════════════════════════════════════════════════════════════
# RELEASE OUTLOOK
# ═══════════════════════════════════════════════════════════════════════════════

def format_releases(s: dict) -> html.Div:
    if "error" in s:
        return html.Div(s["error"], style={"color": _C["bad"]})

    T = s["targets"]
    rels = s["releases"]

    # Summary strip
    kpis = html.Div([
        _metric_badge(str(len(rels)),           "Total Releases", _C["text"]),
        _metric_badge(str(len(s["on_track"])),  "On Track",       _C["good"]),
        _metric_badge(str(len(s["caution"])),   "Caution",        _C["warn"]),
        _metric_badge(str(len(s["at_risk"])),   "At Risk",        _C["bad"] if s["at_risk"] else _C["text"]),
    ], style={"display": "flex", "gap": "10px", "marginBottom": "4px", "flexWrap": "wrap"})

    rel_rows = []
    for r in rels:
        color_map = {"green": _C["good"], "amber": _C["warn"], "red": _C["bad"]}
        c = color_map.get(r["health"], _C["neutral"])
        rel_rows.append(html.Div([
            _rag_dot(r["health"]),
            html.Span(r["release"], style={"color": _C["text"], "fontSize": "12px", "flex": "1"}),
            html.Span(f"{r['completion']}% done", style={"color": c, "fontSize": "12px", "fontWeight": "600"}),
            html.Span(f"  {r['open_bugs']} open bugs", style={"color": _C["subtext"], "fontSize": "11px", "marginLeft": "10px"}),
            html.Span(f"  P1:{r['p1_open']}", style={"color": _C["bad"] if r["p1_open"] else _C["subtext"],
                                                     "fontSize": "11px", "marginLeft": "6px"}),
        ], style={"display": "flex", "alignItems": "center", "padding": "5px 0",
                  "borderBottom": f"1px solid rgba(255,255,255,0.03)"}))
    rel_table = _section("Release Health Overview", rel_rows if rel_rows else [
        html.Div("No releases found", style={"color": _C["subtext"], "fontSize": "12px"})
    ])

    # Suggestions
    suggestions = []
    if s["at_risk"]:
        names = ", ".join(r["release"] for r in s["at_risk"][:3])
        suggestions.append(_suggestion("🚨", (
            f"{len(s['at_risk'])} release(s) are at risk: {names}. "
            "Review open P1 bugs and completion percentages immediately."
        )))
    if s["total_open_p1"] > 0:
        suggestions.append(_suggestion("🔥", (
            f"{s['total_open_p1']} P1 bugs are open across active releases. "
            "Block release signoff until all P1 issues are resolved."
        )))
    if any(r["completion"] < 50 and r["total"] > 5 for r in rels):
        low = [r["release"] for r in rels if r["completion"] < 50 and r["total"] > 5]
        suggestions.append(_suggestion("📋", (
            f"{', '.join(low[:2])} {'are' if len(low) > 1 else 'is'} below 50% completion. "
            "Consider scope reduction or release date adjustment."
        )))
    if not suggestions:
        suggestions.append(_suggestion("✅", "All releases are progressing well with no critical blockers."))
    sugg_section = _section("Recommendations", suggestions)

    return html.Div([kpis, rel_table, sugg_section])


# ═══════════════════════════════════════════════════════════════════════════════
# CAPACITY
# ═══════════════════════════════════════════════════════════════════════════════

def format_capacity(s: dict) -> html.Div:
    if "error" in s:
        return html.Div(s["error"], style={"color": _C["bad"]})

    T = s["targets"]

    def _color(val, tgt, lower=True):
        if val is None: return _C["neutral"]
        return _C["good"] if (val <= tgt if lower else val >= tgt) else _C["bad"]

    kpis = html.Div([
        _metric_badge(f"{s['total_est']:.0f}h",  "Total Estimated", _C["text"]),
        _metric_badge(f"{s['total_comp']:.0f}h", "Completed",       _C["good"]),
        _metric_badge(f"{s['total_rem']:.0f}h",  "Remaining",       _C["warn"]),
        _metric_badge(f"{s['utilisation_pct']}%","Utilisation",
                      _color(s["utilisation_pct"], T["capacity_utilisation"], lower=False)),
    ], style={"display": "flex", "gap": "10px", "marginBottom": "4px", "flexWrap": "wrap"})

    team_rows = [
        _row(ts["team"],
             f"{ts['util']}% utilised",
             _color(ts["util"], T["capacity_utilisation"], lower=False),
             f"{ts['comp']:.0f}h / {ts['est']:.0f}h")
        for ts in s["team_stats"]
    ] if s["team_stats"] else [html.Div("No team data", style={"color": _C["subtext"], "fontSize": "12px"})]
    team_section = _section("Team Utilisation", team_rows)

    acc_rows = []
    if s["accuracy_pct"] is not None:
        acc_rows.append(_row("Estimate accuracy", f"{s['accuracy_pct']}%",
                             _C["good"] if s["accuracy_pct"] >= 70 else _C["warn"]))
    if s["over_estimated"]:
        acc_rows.append(_row("Over-estimated items (done in <50% time)", str(s["over_estimated"]), _C["subtext"]))
    if s["under_estimated"]:
        acc_rows.append(_row("Under-estimated items (took >150% time)", str(s["under_estimated"]),
                             _C["warn"] if s["under_estimated"] > 5 else _C["text"]))
    if acc_rows:
        team_section.children.extend(acc_rows)

    suggestions = []
    if s["utilisation_pct"] < T["capacity_utilisation"]:
        suggestions.append(_suggestion("📊", (
            f"Overall utilisation is {s['utilisation_pct']}% — target ≥{T['capacity_utilisation']}%. "
            "Review whether estimates are being entered correctly or if sprint capacity is underloaded."
        )))
    if s["under_estimated"] and s["under_estimated"] > 10:
        suggestions.append(_suggestion("⏱️", (
            f"{s['under_estimated']} items took >150% of estimated time. "
            "Introduce planning poker or historical velocity benchmarks to improve accuracy."
        )))
    me = s.get("missing_est_count", 0)
    if me > 0:
        suggestions.append(_suggestion("📝", (
            f"{me} open item{'s' if me > 1 else ''} {'have' if me > 1 else 'has'} no original estimate. "
            "Estimates are required for accurate capacity tracking — see Missing Estimates section below."
        )))
    if not suggestions:
        suggestions.append(_suggestion("✅", "Capacity utilisation is within target range."))
    sugg_section = _section("Recommendations", suggestions)

    # ── Missing Estimates section ──────────────────────────────────────────────
    me_color = _C["bad"] if me > 20 else (_C["warn"] if me > 5 else (_C["good"] if me == 0 else _C["text"]))
    me_children = [_row("Open items without estimate", str(me), me_color)]

    by_person = s.get("missing_by_person", {})
    if by_person:
        me_children.append(html.Div("By developer", style={
            "fontSize": "10px", "color": _C["subtext"], "textTransform": "uppercase",
            "letterSpacing": "0.5px", "marginTop": "10px", "marginBottom": "4px",
        }))
        for name, cnt in list(by_person.items())[:8]:
            me_children.append(_row(name, f"{cnt} item{'s' if cnt > 1 else ''}", _C["warn"]))

    items = s.get("missing_items", [])
    if items:
        _th = {"padding": "5px 8px", "fontSize": "10px", "color": _C["subtext"],
               "textTransform": "uppercase", "letterSpacing": "0.5px",
               "borderBottom": f"1px solid {_C['border']}", "fontWeight": "600", "textAlign": "left"}
        _td_sub  = {"padding": "4px 8px", "fontSize": "11px", "color": _C["subtext"], "whiteSpace": "nowrap"}
        _td_text = {"padding": "4px 8px", "fontSize": "11px", "color": _C["text"],
                    "maxWidth": "220px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}
        _td_iter = {"padding": "4px 8px", "fontSize": "11px", "color": _C["subtext"],
                    "maxWidth": "160px", "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}
        _tr_style = {"borderBottom": f"1px solid rgba(255,255,255,0.02)"}

        tbl_header = html.Tr([
            html.Th(h, style=_th)
            for h in ["ID", "Title", "Type", "Developer", "Iteration", "State"]
        ])
        tbl_rows = [
            html.Tr([
                html.Td(str(rec.get("work_item_id", "—")),                                style=_td_sub),
                html.Td(str(rec.get("title", "—"))[:55],                                  style=_td_text),
                html.Td(str(rec.get("work_item_type", "—")),                              style=_td_sub),
                html.Td(str(rec.get("_dev_disp", rec.get("main_developer", "—")))[:25],   style=_td_text),
                html.Td(str(rec.get("iteration_path", "—")),                              style=_td_iter),
                html.Td(str(rec.get("state", "—")),                                       style=_td_sub),
            ], style=_tr_style)
            for rec in items[:20]
        ]
        me_children.append(html.Div("Items missing estimate", style={
            "fontSize": "10px", "color": _C["subtext"], "textTransform": "uppercase",
            "letterSpacing": "0.5px", "marginTop": "12px", "marginBottom": "6px",
        }))
        me_children.append(html.Div(
            html.Table(
                [html.Thead(tbl_header), html.Tbody(tbl_rows)],
                style={"width": "100%", "borderCollapse": "collapse"},
            ),
            style={"overflowX": "auto", "borderRadius": "6px",
                   "border": f"1px solid {_C['border']}", "marginTop": "4px"},
        ))

    me_title = f"Missing Estimates  ({me})" if me > 0 else "Missing Estimates"
    missing_section = _section(me_title, me_children)

    return html.Div([kpis, team_section, missing_section, sugg_section])


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTIVE SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

def format_executive(s: dict) -> html.Div:
    # Scorecard table
    scorecard_rows = []
    for item in s["scorecard"]:
        c = _RAG.get(item["status"], _C["neutral"])
        scorecard_rows.append(html.Tr([
            html.Td([_rag_dot(item["status"]),
                     html.Span(item["area"], style={"fontSize": "12px", "color": _C["text"]})],
                    style={"padding": "7px 10px", "verticalAlign": "middle"}),
            html.Td(item["now"],    style={"padding": "7px 10px", "color": c, "fontWeight": "600",
                                           "fontSize": "13px", "textAlign": "center"}),
            html.Td(item["target"], style={"padding": "7px 10px", "color": _C["subtext"],
                                           "fontSize": "12px", "textAlign": "center"}),
        ], style={"borderBottom": f"1px solid {_C['border']}"}))

    scorecard_table = html.Table([
        html.Thead(html.Tr([
            html.Th("Area",   style={"padding": "8px 10px", "fontSize": "10px", "color": _C["subtext"],
                                     "textTransform": "uppercase", "letterSpacing": "0.5px",
                                     "borderBottom": f"1px solid {_C['border']}"}),
            html.Th("Now",    style={"padding": "8px 10px", "fontSize": "10px", "color": _C["subtext"],
                                     "textTransform": "uppercase", "textAlign": "center",
                                     "borderBottom": f"1px solid {_C['border']}"}),
            html.Th("Target", style={"padding": "8px 10px", "fontSize": "10px", "color": _C["subtext"],
                                     "textTransform": "uppercase", "textAlign": "center",
                                     "borderBottom": f"1px solid {_C['border']}"}),
        ])),
        html.Tbody(scorecard_rows),
    ], style={"width": "100%", "borderCollapse": "collapse", "marginBottom": "8px"})

    scorecard_section = _section("Executive Scorecard", [scorecard_table])

    # Per-board highlights
    b = s["bugs"]
    highlights = _section("Key Highlights", [
        _row("Open critical bugs",    str(b["open_p1"]),        _C["bad"] if b["open_p1"] > 5 else _C["good"]),
        _row("Defect escape to PROD", f"{b['escape_rate_pct']}%", _C["bad"] if b["escape_rate_pct"] > 10 else _C["good"]),
        _row("Customer open issues",  str(b["customer_open"]),  _C["bad"] if b["customer_open"] > 30 else _C["good"]),
        _row("Enh:Bug ratio",         f"{b['enh_bug_ratio']}:1", _C["bad"] if b["enh_bug_ratio"] < 1 else _C["good"]),
        _row("Releases at risk",      str(len(s["releases"].get("at_risk", []))),
             _C["bad"] if s["releases"].get("at_risk") else _C["good"]),
        _row("SLA breach rate",       f"{s['qa']['overall_breach_pct']}%",
             _C["bad"] if s["qa"]["overall_breach_pct"] > 10 else _C["good"]),
    ])

    return html.Div([scorecard_section, highlights])


# ═══════════════════════════════════════════════════════════════════════════════
# DISPATCH
# ═══════════════════════════════════════════════════════════════════════════════

_FORMATTERS = {
    "bugs":      format_bugs,
    "qa":        format_qa,
    "releases":  format_releases,
    "capacity":  format_capacity,
    "executive": format_executive,
}


def format_report(summary: dict) -> html.Div:
    """Main entry point — dispatch to the correct formatter."""
    board = summary.get("board", "")
    fn    = _FORMATTERS.get(board)
    if fn is None:
        return html.Div(f"No formatter for board: {board}", style={"color": _C["bad"]})
    return fn(summary)
