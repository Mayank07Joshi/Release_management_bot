"""Team Pulse — rolling 12-month capacity grid across all teams."""
from __future__ import annotations
import re
from datetime import date, timedelta

import dash
from dash import html, dcc, callback, Input, Output, ALL, ctx
from dash.exceptions import PreventUpdate
from sqlalchemy import text

from config.dev_capacity import DEVELOPERS
from data.loader import engine

dash.register_page(__name__, path="/team-pulse", name="Team Pulse")

# ── Theme ─────────────────────────────────────────────────────────────────────
_BG_PAGE = "rgb(10,13,21)"
_BG_CARD = "rgb(18,22,31)"
_BG_HEAD = "rgb(23,28,40)"
_BD      = "rgb(38,44,58)"
_BD_CELL = "rgb(30,36,51)"
_MT      = "rgb(139,146,164)"
_DIM     = "rgb(91,98,118)"
_FG      = "rgb(234,236,242)"
_INDIGO  = "rgb(110,118,241)"
_GREEN   = "rgb(70,194,142)"
_AMBER   = "rgb(224,162,60)"
_RED     = "rgb(239,110,99)"
_CYAN    = "rgb(63,182,201)"
_MONO    = "'JetBrains Mono','SF Mono',monospace"

# ── Team roster ───────────────────────────────────────────────────────────────
_TEAM_MAP: dict[str, str] = {}
for _d in DEVELOPERS:
    _TEAM_MAP[_d["name"]] = "Mobile Dev" if _d["team"] == "Mobile" else "Web Dev"

_TEAM_MAP.update({
    "Furquan Nayyar":  "Design",
    "Kaushik Awasthi": "Design",
    "Gagandeep Kaur":  "Design",
    "Sunil":           "QA",
    "Vineeta":         "QA",
    "Varun T":         "QA",
    "Chhavi Bhardwaj": "Story Writers",
    "Geetika Khanna":  "Story Writers",
})

_TEAM_ORDER  = ["Web Dev", "Mobile Dev", "Design", "QA", "Story Writers"]
_TEAM_COLORS = {
    "Web Dev":       _INDIGO,
    "Mobile Dev":    "rgb(251,146,60)",
    "Design":        "rgb(167,139,250)",
    "QA":            _GREEN,
    "Story Writers": _CYAN,
    "Other":         _DIM,
}

# ── Size bands (from estimate hours) ─────────────────────────────────────────
_ENH_SIZES   = ["Big", "Medium", "Small", "Very small", "Unsized"]
_PRI_LABELS  = ["P1", "P2", "P3", "Others"]

def _classify_size(h: float) -> str:
    if h >= 40:   return "Big"
    if h >= 16:   return "Medium"
    if h >= 8:    return "Small"
    if h >= 1:    return "Very small"
    return "Unsized"

def _classify_pri(priority) -> str:
    p = str(priority or "").strip()
    if p in ("1", "P1"):   return "P1"
    if p in ("2", "P2"):   return "P2"
    if p in ("3", "P3"):   return "P3"
    return "Others"

# ── Month helpers ─────────────────────────────────────────────────────────────
def _rolling_months(n: int = 12) -> list[tuple[int, int]]:
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out

def _month_label(y: int, m: int) -> str:
    return f"{date(y, m, 1).strftime('%b')}-{str(y)[2:]}"

def _month_key(y: int, m: int) -> str:
    return f"{y}-{m:02d}"

def _parse_iter_ym(path) -> tuple[int, int] | None:
    s = str(path or "").split("\\")[-1]
    mo = re.search(r'(\d{4})\s+(\d{2})-', s)
    return (int(mo.group(1)), int(mo.group(2))) if mo else None

def _horizon_months(horizon_d: int, all_months: list) -> set[str]:
    today = date.today()
    cutoff = today + timedelta(days=horizon_d)
    return {
        _month_key(y, m) for y, m in all_months
        if date(y, m, 1) <= cutoff
    }

# ── Data loading ──────────────────────────────────────────────────────────────
def _load_items() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                w.work_item_id,
                w.work_item_type,
                COALESCE(w.priority, '') AS priority,
                COALESCE(w.main_developer, '') AS main_developer,
                COALESCE(w.original_estimate, 0) AS orig_est,
                COALESCE(a.task_est_sum, 0)       AS task_est,
                w.iteration_path,
                COALESCE(a.est_status, 'unestimated') AS est_status
            FROM work_items_main w
            LEFT JOIN agg_story_estimation a ON a.work_item_id = w.work_item_id
            WHERE w.state NOT IN (
                'Closed','Resolved','Not Required','Not an issue',
                'No Customer Response','Not Specified','Userstory Update'
            )
            AND w.main_developer IS NOT NULL
            AND w.main_developer NOT IN ('', 'Unassigned', 'Not Specified')
            AND w.work_item_type IN ('Enhancement','User Story','Issue','Bug')
        """)).fetchall()

    items = []
    for r in rows:
        ym = _parse_iter_ym(r.iteration_path)
        if not ym:
            continue
        is_issue = r.work_item_type in ("Issue", "Bug")
        orig_h   = float(r.orig_est or 0)
        task_h   = float(r.task_est or 0)
        est_h    = task_h if task_h > 0 else orig_h
        estimated = r.est_status in ("estimated", "estimated_via_tasks")
        items.append({
            "type":      "issue" if is_issue else "enh",
            "pri":       _classify_pri(r.priority),
            "dev":       r.main_developer,
            "team":      _TEAM_MAP.get(r.main_developer, "Other"),
            "orig_h":    orig_h,
            "task_h":    task_h,
            "est_h":     est_h,
            "size":      _classify_size(est_h) if not is_issue else None,
            "ym":        ym,
            "mk":        _month_key(*ym),
            "estimated": estimated,
        })
    return items


# ── Table cells ───────────────────────────────────────────────────────────────
_TH_S = {
    "padding": "8px 10px", "fontSize": "10px", "fontWeight": "700",
    "color": _DIM, "textTransform": "uppercase", "letterSpacing": "0.4px",
    "whiteSpace": "nowrap", "background": _BG_HEAD, "verticalAlign": "middle",
    "borderBottom": f"1px solid {_BD}", "borderRight": f"1px solid {_BD_CELL}",
}
_TD_S = {
    "padding": "6px 10px", "fontSize": "12px", "verticalAlign": "middle",
    "borderBottom": f"1px solid {_BD_CELL}", "borderRight": f"1px solid {_BD_CELL}",
    "textAlign": "center",
}

def _num_cell(n: int, hi_thresh=25, red_thresh=32, style=None) -> html.Td:
    if n == 0:
        return html.Td("–", style={**_TD_S, "color": _DIM, **(style or {})})
    color = _RED if n >= red_thresh else (_AMBER if n >= hi_thresh else _FG)
    return html.Td(str(n), style={**_TD_S, "color": color,
                                   "fontWeight": "700" if color != _FG else "500",
                                   **(style or {})})

def _hours_cell(h: float, has_tasks: bool) -> html.Td:
    if h == 0 and not has_tasks:
        return html.Td("–", style={**_TD_S, "color": _DIM})
    color = _RED if h > 120 else (_AMBER if h > 60 else _FG)
    children: list = [html.Div(f"{int(h)}h", style={
        "color": color, "fontWeight": "700", "fontFamily": _MONO, "fontSize": "11px",
    })]
    if has_tasks and h == 0:
        children.append(html.Div("– – – –", style={
            "fontSize": "8.5px", "color": _DIM, "letterSpacing": "1.5px", "marginTop": "1px",
        }))
    return html.Td(children, style={**_TD_S, "padding": "4px 8px"})

def _eu_cell(est: int, unest: int) -> html.Td:
    total = est + unest
    if total == 0:
        return html.Td("–", style={**_TD_S, "color": _DIM})
    return html.Td([
        html.Div(str(total), style={"fontWeight": "700", "color": _FG, "fontSize": "12px"}),
        html.Div([
            html.Span(f"{est}e",   style={"color": _GREEN}),
            html.Span(" · ",       style={"color": _DIM}),
            html.Span(f"{unest}u", style={"color": _AMBER if unest else _DIM}),
        ], style={"fontSize": "9px", "marginTop": "1px", "fontFamily": _MONO}),
    ], style={**_TD_S, "padding": "4px 8px"})

def _label_cell(txt: str, style: dict | None = None) -> html.Td:
    return html.Td(txt, style={
        **_TD_S, "textAlign": "left", "color": _MT,
        "fontSize": "10px", "fontWeight": "600",
        "textTransform": "uppercase", "letterSpacing": "0.4px",
        "paddingLeft": "16px", **(style or {}),
    })

def _section_row(label: str, n_cols: int) -> html.Tr:
    return html.Tr(
        html.Td(label, colSpan=n_cols + 1, style={
            "padding": "5px 12px", "fontSize": "10.5px", "fontWeight": "700",
            "color": _FG, "background": _BG_HEAD, "textTransform": "uppercase",
            "letterSpacing": "0.5px",
            "borderTop": f"1px solid {_BD}", "borderBottom": f"1px solid {_BD}",
        })
    )


# ── Main grid builder ─────────────────────────────────────────────────────────
def _build_grid(items: list[dict], team_filter: str, horizon_d: int) -> html.Div:
    all_months  = _rolling_months(12)
    active_mks  = _horizon_months(horizon_d, all_months)
    months      = [(y, m) for y, m in all_months if _month_key(y, m) in active_mks]
    mks         = [_month_key(y, m) for y, m in months]
    today_mk    = _month_key(date.today().year, date.today().month)
    n_cols      = len(months)

    # Apply team filter
    if team_filter != "All":
        filtered = [x for x in items if x["team"] == team_filter]
    else:
        filtered = items

    # Apply horizon filter
    filtered = [x for x in filtered if x["mk"] in active_mks]

    # ── Aggregate: issues by priority × month ─────────────────────────────────
    iss_by_pri: dict[str, dict[str, int]] = {p: {mk: 0 for mk in mks} for p in _PRI_LABELS}
    for x in filtered:
        if x["type"] == "issue" and x["mk"] in mks:
            iss_by_pri[x["pri"]][x["mk"]] += 1

    # ── Aggregate: enhancements by size × month ───────────────────────────────
    enh_by_sz: dict[str, dict[str, int]] = {s: {mk: 0 for mk in mks} for s in _ENH_SIZES}
    for x in filtered:
        if x["type"] == "enh" and x["mk"] in mks and x["size"]:
            enh_by_sz[x["size"]][x["mk"]] += 1

    # ── Total per month ───────────────────────────────────────────────────────
    total_by_mk: dict[str, int] = {mk: 0 for mk in mks}
    for x in filtered:
        if x["mk"] in mks:
            total_by_mk[x["mk"]] += 1

    # ── Per-developer data ────────────────────────────────────────────────────
    # dev_data[dev][mk] = {"orig_h": 0, "has_tasks": False, "iss_e":0,"iss_u":0,"enh_e":0,"enh_u":0}
    dev_data: dict[str, dict[str, dict]] = {}
    for x in filtered:
        if x["mk"] not in mks:
            continue
        dev  = x["dev"]
        mk   = x["mk"]
        if dev not in dev_data:
            dev_data[dev] = {m: {"orig_h": 0.0, "has_tasks": False,
                                  "iss_e": 0, "iss_u": 0,
                                  "enh_e": 0, "enh_u": 0} for m in mks}
        if mk not in dev_data[dev]:
            dev_data[dev][mk] = {"orig_h": 0.0, "has_tasks": False,
                                  "iss_e": 0, "iss_u": 0,
                                  "enh_e": 0, "enh_u": 0}
        cell = dev_data[dev][mk]
        cell["orig_h"]    += x["est_h"]
        if x["task_h"] > 0 and x["orig_h"] == 0:
            cell["has_tasks"] = True  # task-only estimate → show dash indicator
        if x["type"] == "issue":
            if x["estimated"]: cell["iss_e"] += 1
            else:              cell["iss_u"] += 1
        else:
            if x["estimated"]: cell["enh_e"] += 1
            else:              cell["enh_u"] += 1

    # ── Sort developers by team order ─────────────────────────────────────────
    def _dev_sort_key(name):
        team = _TEAM_MAP.get(name, "Other")
        t_idx = _TEAM_ORDER.index(team) if team in _TEAM_ORDER else len(_TEAM_ORDER)
        return (t_idx, name)

    devs = sorted(dev_data.keys(), key=_dev_sort_key)

    # ── Build HTML table ──────────────────────────────────────────────────────
    # Header row
    head_cells = [html.Th("ALL TEAMS", style={**_TH_S, "textAlign": "left",
                                               "minWidth": "160px"})]
    for y, m in months:
        mk    = _month_key(y, m)
        lbl   = _month_label(y, m)
        is_now = mk == today_mk
        head_cells.append(html.Th(lbl, style={
            **_TH_S, "minWidth": "76px",
            "color": _INDIGO if is_now else _DIM,
            "borderBottom": f"2px solid {_INDIGO}" if is_now else f"1px solid {_BD}",
        }))

    rows: list = [html.Thead(html.Tr(head_cells),
                              style={"position": "sticky", "top": "0", "zIndex": "3"})]
    tbody_rows: list = []

    # ── Issues section ────────────────────────────────────────────────────────
    tbody_rows.append(_section_row("Issues", n_cols))
    for pri in _PRI_LABELS:
        cells = [_label_cell(pri)]
        for mk in mks:
            cells.append(_num_cell(iss_by_pri[pri][mk]))
        tbody_rows.append(html.Tr(cells))

    # ── Enhancements section ──────────────────────────────────────────────────
    tbody_rows.append(_section_row("Enhancements", n_cols))
    for sz in _ENH_SIZES:
        cells = [_label_cell(sz)]
        for mk in mks:
            cells.append(_num_cell(enh_by_sz[sz][mk]))
        tbody_rows.append(html.Tr(cells))

    # Total row
    total_cells = [html.Td("Total", style={
        **_TD_S, "textAlign": "left", "paddingLeft": "16px",
        "fontWeight": "700", "color": _FG, "fontSize": "12px",
        "background": _BG_HEAD,
        "borderTop": f"1px solid {_BD}",
    })]
    for mk in mks:
        n = total_by_mk[mk]
        total_cells.append(_num_cell(n, hi_thresh=24, red_thresh=32,
                                     style={"background": _BG_HEAD,
                                            "fontWeight": "700",
                                            "borderTop": f"1px solid {_BD}"}))
    tbody_rows.append(html.Tr(total_cells))

    # ── Developer rows ────────────────────────────────────────────────────────
    for dev in devs:
        team  = _TEAM_MAP.get(dev, "Other")
        tc    = _TEAM_COLORS.get(team, _DIM)
        r_tc  = tc  # re-use in badge

        # Dev header row
        name_cell = html.Td([
            html.Span(dev, style={"fontWeight": "700", "color": _FG,
                                   "fontSize": "12.5px", "marginRight": "8px"}),
            html.Span(team, style={
                "fontSize": "10px", "fontWeight": "700", "color": tc,
                "background": f"rgba({_rgb(tc)},0.13)",
                "border": f"1px solid rgba({_rgb(tc)},0.35)",
                "borderRadius": "5px", "padding": "2px 7px",
            }),
        ], style={**_TD_S, "textAlign": "left", "background": _BG_HEAD,
                   "padding": "6px 12px",
                   "borderTop": f"1px solid {_BD}"})
        dev_head_cols = [name_cell] + [
            html.Td("", style={**_TD_S, "background": _BG_HEAD,
                               "borderTop": f"1px solid {_BD}"})
            for _ in mks
        ]
        tbody_rows.append(html.Tr(dev_head_cols))

        # HOURS row
        h_cells = [_label_cell("Hours")]
        for mk in mks:
            c = dev_data[dev][mk]
            h_cells.append(_hours_cell(c["orig_h"], c["has_tasks"]))
        tbody_rows.append(html.Tr(h_cells))

        # ISSUES row
        i_cells = [_label_cell("Issues")]
        for mk in mks:
            c = dev_data[dev][mk]
            i_cells.append(_eu_cell(c["iss_e"], c["iss_u"]))
        tbody_rows.append(html.Tr(i_cells))

        # ENHANCEMENTS row
        e_cells = [_label_cell("Enhancements")]
        for mk in mks:
            c = dev_data[dev][mk]
            e_cells.append(_eu_cell(c["enh_e"], c["enh_u"]))
        tbody_rows.append(html.Tr(e_cells))

    rows.append(html.Tbody(tbody_rows))

    # Summary stats
    n_devs  = len(devs)
    n_items = len(filtered)
    n_hours = int(sum(x["orig_h"] for x in filtered))

    return html.Div([
        # Stats bar
        html.Div([
            html.Span(f"{n_devs} people · {n_items} items · {n_hours:,}h",
                      style={"fontSize": "11px", "color": _DIM, "fontFamily": _MONO}),
        ], style={"textAlign": "right", "padding": "6px 0 10px"}),

        # Table
        html.Div(
            html.Table(rows, style={
                "borderCollapse": "collapse", "width": "100%",
                "minWidth": f"{160 + n_cols * 80}px",
            }),
            style={
                "border": f"1px solid {_BD}", "borderRadius": "12px",
                "overflow": "auto", "maxHeight": "calc(100vh - 260px)",
            },
        ),

        # Legend
        html.Div([
            html.Span("Sizes from estimate hours: Big ≥ 40h · Medium 16–39h · "
                      "Small 8–15h · Very small 1–7h · Unsized = no estimate",
                      style={"marginRight": "18px"}),
            html.Span([
                html.Span("e", style={"color": _GREEN}),
                html.Span(" = estimated · ", style={"color": _DIM}),
                html.Span("u", style={"color": _AMBER}),
                html.Span(" = unestimated · amber/red totals = heavy months",
                          style={"color": _DIM}),
            ]),
        ], style={"fontSize": "10.5px", "color": _DIM, "padding": "10px 0 4px",
                  "borderTop": f"1px solid {_BD_CELL}", "marginTop": "10px"}),
    ])


def _rgb(c: str) -> str:
    m = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', c)
    return f"{m.group(1)},{m.group(2)},{m.group(3)}" if m else "139,146,164"


# ── Layout ────────────────────────────────────────────────────────────────────
def layout(**_):
    items      = _load_items()
    all_teams  = sorted({x["team"] for x in items}, key=lambda t: (
        _TEAM_ORDER.index(t) if t in _TEAM_ORDER else len(_TEAM_ORDER)
    ))
    team_counts = {t: len({x["dev"] for x in items if x["team"] == t})
                   for t in all_teams}
    total_devs  = len({x["dev"] for x in items})

    def _pill(label, count, tid):
        return html.Div(
            f"{label}  {count}",
            id={"type": "tp-team-pill", "team": tid},
            n_clicks=0,
            style={
                "padding": "5px 13px", "borderRadius": "8px",
                "cursor": "pointer", "fontSize": "12px",
                "fontWeight": "600", "whiteSpace": "nowrap",
                "background": f"rgba({_rgb(_INDIGO)},0.18)",
                "border": f"1px solid rgba({_rgb(_INDIGO)},0.5)",
                "color": _INDIGO,
            } if tid == "All" else {
                "padding": "5px 13px", "borderRadius": "8px",
                "cursor": "pointer", "fontSize": "12px",
                "fontWeight": "600", "whiteSpace": "nowrap",
                "background": "transparent",
                "border": f"1px solid {_BD}",
                "color": _MT,
            },
        )

    def _hpill(label, val, active):
        r = _rgb(_INDIGO)
        return html.Div(
            label,
            id={"type": "tp-horizon-pill", "val": val},
            n_clicks=0,
            style={
                "padding": "4px 10px", "borderRadius": "6px",
                "cursor": "pointer", "fontSize": "11px", "fontWeight": "600",
                "background": f"rgba({r},0.18)" if active else "transparent",
                "border": f"1px solid rgba({r},0.5)" if active else f"1px solid {_BD}",
                "color": _INDIGO if active else _DIM,
            },
        )

    pills = [_pill("All", total_devs, "All")]
    for team in all_teams:
        if team == "Other":
            continue
        tc  = _TEAM_COLORS.get(team, _DIM)
        r   = _rgb(tc)
        cnt = team_counts.get(team, 0)
        pills.append(html.Div(
            f"{team}  {cnt}",
            id={"type": "tp-team-pill", "team": team},
            n_clicks=0,
            style={
                "padding": "5px 13px", "borderRadius": "8px",
                "cursor": "pointer", "fontSize": "12px",
                "fontWeight": "600", "whiteSpace": "nowrap",
                "background": "transparent",
                "border": f"1px solid {_BD}", "color": _MT,
            },
        ))

    return html.Div([
        dcc.Store(id="tp-team-store",    data="All"),
        dcc.Store(id="tp-horizon-store", data=365),

        # ── Header ────────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Span("EOD · PLANNING", style={
                    "fontSize": "10px", "fontWeight": "700", "color": _INDIGO,
                    "textTransform": "uppercase", "letterSpacing": "1px",
                }),
                html.H1("Team Pulse", style={
                    "fontSize": "21px", "fontWeight": "700", "color": _FG,
                    "margin": "4px 0 0 0",
                }),
                html.Div("Rolling 12-month workload — issues by priority, "
                         "enhancements by size, hours per developer.",
                         style={"fontSize": "12px", "color": _MT, "marginTop": "5px"}),
            ]),
            html.Div(f"Monthly grid · {date.today().strftime('%b %Y')}",
                     style={
                         "fontSize": "11px", "color": _DIM, "fontFamily": _MONO,
                         "background": _BG_HEAD, "border": f"1px solid {_BD}",
                         "borderRadius": "8px", "padding": "7px 12px",
                     }),
        ], style={
            "padding": "18px 24px", "borderBottom": f"1px solid {_BD}",
            "display": "flex", "justifyContent": "space-between",
            "alignItems": "flex-start", "background": _BG_CARD,
        }),

        # ── Team filter bar ────────────────────────────────────────────────────
        html.Div([
            html.Div(pills, id="tp-team-pills",
                     style={"display": "flex", "flexWrap": "wrap", "gap": "8px",
                            "flex": "1"}),
        ], style={
            "padding": "12px 24px", "borderBottom": f"1px solid {_BD}",
            "background": _BG_CARD,
        }),

        # ── Horizon filter bar ─────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Span("Horizon", style={
                    "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                    "marginRight": "8px",
                }),
                html.Div(id="tp-horizon-pills",
                         children=[
                             _hpill("30d",  30,  False),
                             _hpill("90d",  90,  False),
                             _hpill("180d", 180, False),
                             _hpill("365d", 365, True),
                         ],
                         style={"display": "flex", "gap": "6px"}),
            ], style={"display": "flex", "alignItems": "center"}),
        ], style={
            "padding": "10px 24px", "borderBottom": f"1px solid {_BD}",
            "background": _BG_CARD,
        }),

        # ── Grid content ──────────────────────────────────────────────────────
        html.Div(id="tp-grid", style={"padding": "18px 24px"}),

    ], style={
        "display": "flex", "flexDirection": "column",
        "minHeight": "100vh", "background": _BG_PAGE,
    })


# ── Callbacks ─────────────────────────────────────────────────────────────────
@callback(
    Output("tp-team-store", "data"),
    Output("tp-team-pills", "children"),
    Input({"type": "tp-team-pill", "team": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_team(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    selected = tid["team"]

    items = _load_items()
    all_teams = sorted({x["team"] for x in items}, key=lambda t: (
        _TEAM_ORDER.index(t) if t in _TEAM_ORDER else len(_TEAM_ORDER)
    ))
    team_counts = {t: len({x["dev"] for x in items if x["team"] == t}) for t in all_teams}
    total_devs  = len({x["dev"] for x in items})

    def _pill(label, count, tid_val):
        active = tid_val == selected
        r = _rgb(_INDIGO)
        tc = _TEAM_COLORS.get(tid_val, _INDIGO) if tid_val != "All" else _INDIGO
        r2 = _rgb(tc)
        return html.Div(
            f"{label}  {count}",
            id={"type": "tp-team-pill", "team": tid_val},
            n_clicks=0,
            style={
                "padding": "5px 13px", "borderRadius": "8px",
                "cursor": "pointer", "fontSize": "12px",
                "fontWeight": "600", "whiteSpace": "nowrap",
                "background": f"rgba({r2},0.18)" if active else "transparent",
                "border": f"1px solid rgba({r2},0.5)" if active else f"1px solid {_BD}",
                "color": tc if active else _MT,
            },
        )

    pills = [_pill("All", total_devs, "All")]
    for team in all_teams:
        if team == "Other":
            continue
        cnt = team_counts.get(team, 0)
        pills.append(_pill(team, cnt, team))

    return selected, pills


@callback(
    Output("tp-horizon-store", "data"),
    Output("tp-horizon-pills", "children"),
    Input({"type": "tp-horizon-pill", "val": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_horizon(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    selected = tid["val"]

    def _hpill(label, val):
        active = val == selected
        r = _rgb(_INDIGO)
        return html.Div(
            label,
            id={"type": "tp-horizon-pill", "val": val},
            n_clicks=0,
            style={
                "padding": "4px 10px", "borderRadius": "6px",
                "cursor": "pointer", "fontSize": "11px", "fontWeight": "600",
                "background": f"rgba({r},0.18)" if active else "transparent",
                "border": f"1px solid rgba({r},0.5)" if active else f"1px solid {_BD}",
                "color": _INDIGO if active else _DIM,
            },
        )

    return selected, [
        _hpill("30d",  30),
        _hpill("90d",  90),
        _hpill("180d", 180),
        _hpill("365d", 365),
    ]


@callback(
    Output("tp-grid", "children"),
    Input("tp-team-store",    "data"),
    Input("tp-horizon-store", "data"),
)
def _render_grid(team, horizon):
    items = _load_items()
    return _build_grid(items, team or "All", horizon or 365)
