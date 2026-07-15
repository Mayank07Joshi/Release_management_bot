"""Designer Planning — monthly design schedule & load tracker."""
from __future__ import annotations

import re
from datetime import date, datetime

import dash
from dash import html, dcc, callback, Input, Output, State, ctx, ALL
from dash.exceptions import PreventUpdate
from sqlalchemy import text

from config.dev_capacity import DEV_NAMES, DESIGNER_NAMES, STORY_OWNER_NAMES
from data.loader import engine
from sync.ado_write import write_fields

dash.register_page(__name__, path="/designer-planning", name="Designer Planning")

# ── Constants ─────────────────────────────────────────────────────────────────
_DEV_STATES = frozenset(["Active", "Dev InProgress", "Dev Review", "Dev Complete"])

_DESIGNERS    = DESIGNER_NAMES
_STORY_OWNERS = STORY_OWNER_NAMES
_SIZES        = ["Big", "Medium", "Small", "Very Small"]
_SIZE_PTS     = {"Big": 8, "Medium": 5, "Small": 3, "Very Small": 1}
_SIZE_COLORS  = {
    "Big":        "rgb(224,162,60)",
    "Medium":     "rgb(181,194,74)",
    "Small":      "rgb(70,194,142)",
    "Very Small": "rgb(63,182,201)",
}

_MONO    = "'JetBrains Mono','SF Mono',monospace"
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
_SALMON  = "rgb(240,137,122)"

_SIZE_ABBR  = {"Big": "B", "Medium": "M", "Small": "S", "Very Small": "VS"}
_TARGET_PTS = 20

_STATUS_COLORS = {
    "complete":   _GREEN,
    "overdue":    _RED,
    "due_now":    _AMBER,
    "scheduled":  _INDIGO,
    "not_in_dev": _DIM,
}
_STATUS_LABELS = {
    "complete":   "Complete",
    "overdue":    "Overdue",
    "due_now":    "Due now",
    "scheduled":  "Scheduled",
    "not_in_dev": "Planned",
}

_ITER_RE  = re.compile(r'\\(\d{4})\\Iteration \d{4} (\d{2})-')

_MONTH_OPTIONS = [
    "Jan 2026","Feb 2026","Mar 2026","Apr 2026","May 2026","Jun 2026",
    "Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026",
    "Jan 2027","Feb 2027","Mar 2027","Apr 2027","May 2027","Jun 2027",
]
_PRIORITIES = ["P1", "P2", "P3", "P4"]
_PRI_MAP    = {"P1": "1", "P2": "2", "P3": "3", "P4": "4"}
_PRI_COLORS = {"P1": "rgb(239,110,99)", "P2": "rgb(224,162,60)",
               "P3": "rgb(110,118,241)", "P4": "rgb(91,98,118)"}
_MON_ABBR = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
             7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_iter(path: str):
    m = _ITER_RE.search(path or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _des_ym(dev_year: int, dev_month: int):
    if dev_month == 1:
        return dev_year - 1, 12
    return dev_year, dev_month - 1


def _rgb(color_str: str) -> str:
    m = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color_str)
    return f"{m.group(1)},{m.group(2)},{m.group(3)}" if m else "139,146,164"


def _story_status_badge(wid: int):
    from data.loader import engine as _eng
    from sqlalchemy import text as _text
    with _eng.connect() as conn:
        g = conn.execute(_text("""
            SELECT claude_screens, text_written, our_screens, html_screens, sn_signoff
            FROM p_planning_gates WHERE work_item_id = :id
        """), {"id": wid}).fetchone()
    done  = sum([bool(g.claude_screens), bool(g.text_written), bool(g.our_screens),
                 bool(g.html_screens), bool(g.sn_signoff)]) if g else 0
    total = 5
    complete = done == total

    def _pill(label, active, color):
        r = _rgb(color)
        return html.Span(label, style={
            "fontSize": "12px", "fontWeight": "700" if active else "500",
            "color": color if active else _MT,
            "background": f"rgba({r},0.18)" if active else _BG_HEAD,
            "border": f"1px solid rgba({r},0.5)" if active else f"1px solid {_BD}",
            "borderRadius": "7px", "padding": "6px 13px", "cursor": "default",
        })

    return html.Div([
        html.Div([
            _pill("Complete",   complete,      _GREEN),
            _pill("Incomplete", not complete,  _AMBER),
        ], style={"display": "flex", "gap": "6px", "marginBottom": "6px"}),
        html.Div(
            f"{done}/{total} gates · Complete = design added to the story (Story Planning done).",
            style={"fontSize": "11px", "color": _DIM},
        ),
    ])


def _cell_status(story: dict, today: date) -> str:
    if story["design_done"]:
        return "complete"
    if not story["in_dev"]:
        return "not_in_dev"
    dy, dm = story["des_year"], story["des_month"]
    if   (dy, dm) <  (today.year, today.month): return "overdue"
    elif (dy, dm) == (today.year, today.month): return "due_now"
    return "scheduled"


def _fmt_release(rel) -> str:
    if not rel:
        return ""
    try:
        return datetime.fromisoformat(str(rel)[:10]).strftime("%Y %B")
    except Exception:
        return str(rel)[:10]


def _load_data():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT w.work_item_id, w.title, w.state, w.iteration_path,
                   w.main_designer, w.main_developer, w.story_owner,
                   w.release_date, w.work_item_type, w.priority,
                   COALESCE(w.story_size,   '') AS story_size,
                   COALESCE(w.story_status, '') AS story_status,
                   COALESCE(g.our_screens,  FALSE) AS our_screens,
                   COALESCE(g.html_screens, FALSE) AS html_screens
            FROM work_items_main w
            LEFT JOIN p_planning_gates g ON g.work_item_id = w.work_item_id
            WHERE w.work_item_type IN ('Enhancement','User Story')
              AND w.state NOT IN (
                'Closed','Not an issue','Not Required',
                'No Customer Response','Resolved','Userstory Update'
              )
              AND w.iteration_path ~ 'Iteration [0-9]{4} [0-9]{2}-'
        """)).fetchall()

        iter_paths = conn.execute(text("""
            SELECT DISTINCT iteration_path FROM work_items_main
            WHERE iteration_path ~ 'Iteration [0-9]{4} [0-9]{2}-'
        """)).fetchall()

    iter_map: dict[tuple, str] = {}
    for r in iter_paths:
        p = _parse_iter(r[0])
        if p:
            iter_map[p] = r[0]

    stories = []
    for r in rows:
        p = _parse_iter(r.iteration_path)
        if not p:
            continue
        dev_year, dev_month = p
        dy, dm = _des_ym(dev_year, dev_month)
        done = bool(r.our_screens) and bool(r.html_screens)

        def _clean(v):
            return (v or "").strip() if (v or "").strip() not in ("Unassigned", "") else None

        try:
            pri = int(r.priority) if r.priority else 99
        except (TypeError, ValueError):
            pri = 99
        stories.append({
            "id":          r.work_item_id,
            "title":       r.title or "",
            "state":       r.state or "",
            "iter_path":   r.iteration_path,
            "dev_year":    dev_year,
            "dev_month":   dev_month,
            "des_year":    dy,
            "des_month":   dm,
            "designer":    _clean(r.main_designer),
            "developer":   _clean(r.main_developer),
            "owner":       r.story_owner or "",
            "release":     r.release_date or "",
            "size":        (r.story_size or "").strip().title(),
            "design_done": done,
            "in_dev":      r.state in _DEV_STATES,
            "priority":    pri,
        })

    # Sort by dev month (year, month) first, then priority — groups all items for
    # the same calendar month together even when they span multiple sub-iterations
    stories.sort(key=lambda s: (s["dev_year"], s["dev_month"], s["priority"], s["id"]))
    return stories, iter_map


# ── KPI bar ───────────────────────────────────────────────────────────────────

def _kpi(label: str, value, sub: str = "", color: str = _FG):
    return html.Div([
        html.Div(label, style={
            "fontSize": "9.5px", "fontWeight": "700", "color": _MT,
            "textTransform": "uppercase", "letterSpacing": "0.6px",
            "marginBottom": "7px",
        }),
        html.Div([
            html.Span(str(value), style={
                "fontSize": "26px", "fontWeight": "700",
                "fontFamily": _MONO, "color": color, "lineHeight": "1",
            }),
            *([ html.Span(sub, style={"fontSize": "11px", "color": _DIM, "marginLeft": "6px"}) ]
              if sub else []),
        ], style={"display": "flex", "alignItems": "baseline"}),
    ], style={
        "background": _BG_CARD, "border": f"1px solid {_BD}",
        "borderRadius": "11px", "padding": "13px 16px", "flex": "1",
    })


def _build_kpis(stories: list, today: date):
    total      = len(stories)
    complete   = sum(1 for s in stories if s["design_done"])
    due_now    = sum(1 for s in stories
                     if not s["design_done"] and s["in_dev"]
                     and (s["des_year"], s["des_month"]) == (today.year, today.month))
    overdue    = sum(1 for s in stories
                     if not s["design_done"] and s["in_dev"]
                     and (s["des_year"], s["des_month"]) < (today.year, today.month))
    unassigned = sum(1 for s in stories if not s["designer"] and not s["design_done"])
    pct        = f"{round(complete / total * 100)}%" if total else "0%"

    return html.Div([
        _kpi("Design Due This Month", due_now,
             sub=f"start in {_MON_ABBR[today.month]}",
             color=_AMBER if due_now else _GREEN),
        _kpi("Overdue", overdue,
             sub="start month passed, not complete",
             color=_RED if overdue else _GREEN),
        _kpi("Designer Unassigned", unassigned,
             sub="open stories with no designer",
             color=_AMBER if unassigned else _GREEN),
        _kpi("Complete", complete,
             sub=f"{pct} · added to story",
             color=_GREEN if complete else _DIM),
        _kpi("Total Stories", total,
             sub="in this plan", color=_FG),
    ], style={
        "display": "flex", "gap": "12px",
        "padding": "16px 24px", "borderBottom": f"1px solid {_BD}",
    })


# ── Monthly design load table ─────────────────────────────────────────────────

def _build_summary_panels(stories: list, plan_months: list):
    plan_set = set(plan_months)

    # ── Monthly load table ─────────────────────────────────────────────────────
    _TH = {
        "padding": "6px 9px", "fontSize": "10.5px", "fontWeight": "700",
        "color": _DIM, "textAlign": "center", "whiteSpace": "nowrap",
    }
    _TD_SEP = {"borderTop": f"1px solid {_BD_CELL}"}

    def _cnt(sz, ym):
        return sum(1 for s in stories if s["size"] == sz
                   and (s["des_year"], s["des_month"]) == ym)

    def _v(n, color=None):
        if n:
            return html.Td(str(n), style={**_TD_SEP, "padding": "6px 9px",
                                          "fontSize": "12px", "textAlign": "center",
                                          "fontFamily": _MONO,
                                          "color": color or _FG, "fontWeight": "700" if color else "400"})
        return html.Td("·", style={**_TD_SEP, "padding": "6px 9px",
                                   "fontSize": "12px", "textAlign": "center",
                                   "fontFamily": _MONO, "color": _DIM})

    head = [html.Th("", style={**_TH, "textAlign": "left"})] + [
        html.Th(_MON_ABBR[m], style=_TH)
        for _, m in plan_months
    ]

    body_rows = []
    for sz in _SIZES:
        sc = _SIZE_COLORS[sz]
        cells = [html.Td(sz, style={**_TD_SEP, "padding": "6px 9px", "fontSize": "12px",
                                    "textAlign": "left", "color": sc, "fontWeight": "600"})]
        for ym in plan_months:
            cells.append(_v(_cnt(sz, ym)))
        body_rows.append(html.Tr(cells))

    total_cells = [html.Td("Total", style={**_TD_SEP, "padding": "6px 9px", "fontSize": "12px",
                                           "textAlign": "left", "color": _FG, "fontWeight": "700"})]
    for ym in plan_months:
        total_cells.append(_v(sum(_cnt(sz, ym) for sz in _SIZES)))
    body_rows.append(html.Tr(total_cells))

    pts_cells = [html.Td("Load pts", style={**_TD_SEP, "padding": "6px 9px", "fontSize": "12px",
                                            "textAlign": "left", "color": _AMBER, "fontWeight": "700"})]
    for ym in plan_months:
        pts_cells.append(_v(sum(_cnt(sz, ym) * _SIZE_PTS.get(sz, 0) for sz in _SIZES), color=_AMBER))
    body_rows.append(html.Tr(pts_cells))

    load_panel = html.Div([
        html.Div("Monthly design load · by start month", style={
            "fontSize": "11px", "color": _MT, "textTransform": "uppercase",
            "letterSpacing": "0.6px", "fontWeight": "700", "marginBottom": "10px",
        }),
        html.Table(
            [html.Thead(html.Tr(head)), html.Tbody(body_rows)],
            style={"borderCollapse": "collapse", "width": "100%"},
        ),
        html.Div(
            f"Counts by design-start month. "
            f"Load pts: Big {_SIZE_PTS['Big']} · Medium {_SIZE_PTS['Medium']} · "
            f"Small {_SIZE_PTS['Small']} · Very Small {_SIZE_PTS['Very Small']}.",
            style={"fontSize": "10.5px", "color": _DIM, "marginTop": "8px"},
        ),
    ], style={"background": _BG_CARD, "border": f"1px solid {_BD}",
              "borderRadius": "12px", "padding": "13px 15px"})

    # ── Designer load panel ────────────────────────────────────────────────────
    # Count stories per designer (using main_developer) across all planning months
    des_counts: dict[str, dict] = {d: {sz: 0 for sz in _SIZES} for d in _DESIGNERS}
    unassigned_counts: dict[str, int] = {sz: 0 for sz in _SIZES}

    for s in stories:
        if (s["des_year"], s["des_month"]) not in plan_set:
            continue
        sz = s.get("size") or ""
        if sz not in _SIZE_PTS:
            continue
        dev = s.get("developer") or ""
        if dev in _DESIGNERS:
            des_counts[dev][sz] += 1
        else:
            unassigned_counts[sz] += 1

    def _des_pts(counts):
        return sum(counts[sz] * _SIZE_PTS[sz] for sz in _SIZES)

    def _des_total(counts):
        return sum(counts[sz] for sz in _SIZES)

    all_pts = [_des_pts(des_counts[d]) for d in _DESIGNERS] + [_des_pts(unassigned_counts)]
    max_pts = max(all_pts) if any(all_pts) else 1

    def _badge(abbr, n, color):
        r = _rgb(color)
        return html.Span(f"{abbr}{n}", style={
            "fontSize": "9.5px", "fontWeight": "700", "color": color,
            "background": f"rgba({r},0.133)", "borderRadius": "3px", "padding": "1px 5px",
        })

    def _des_row(name: str, counts: dict, is_unassigned: bool = False):
        pts        = _des_pts(counts)
        total      = _des_total(counts)
        bar_color  = _SALMON if is_unassigned else _INDIGO
        bar_pct    = min(pts / max_pts * 100, 100) if max_pts else 0
        label      = name if is_unassigned else name.split()[0]

        badges = [
            _badge(_SIZE_ABBR[sz], counts[sz], _SIZE_COLORS[sz])
            for sz in _SIZES if counts[sz] > 0
        ]

        return html.Div([
            html.Div([
                html.Span(label, style={"fontSize": "12.5px", "fontWeight": "600", "color": _FG}),
                html.Span([
                    *badges,
                    html.Span(f"{total}·{pts}p", style={
                        "fontFamily": _MONO, "fontSize": "12px", "fontWeight": "700",
                        "color": _SALMON if is_unassigned else _INDIGO, "marginLeft": "4px",
                    }),
                ], style={"display": "flex", "gap": "5px", "alignItems": "center"}),
            ], style={"display": "flex", "justifyContent": "space-between",
                      "alignItems": "baseline", "marginBottom": "4px"}),
            html.Div(
                html.Div(style={"width": f"{bar_pct:.5f}%", "height": "100%",
                                "background": bar_color}),
                style={"height": "6px", "borderRadius": "3px",
                       "background": _BG_HEAD, "overflow": "hidden"},
            ),
        ])

    des_rows = [_des_row(d, des_counts[d]) for d in _DESIGNERS]
    des_rows.append(_des_row("Unassigned", unassigned_counts, is_unassigned=True))

    des_panel = html.Div([
        html.Div("Designer load · target 20p", style={
            "fontSize": "11px", "color": _MT, "textTransform": "uppercase",
            "letterSpacing": "0.6px", "fontWeight": "700", "marginBottom": "10px",
        }),
        html.Div(des_rows, style={"display": "flex", "flexDirection": "column", "gap": "9px"}),
    ], style={"background": _BG_CARD, "border": f"1px solid {_BD}",
              "borderRadius": "12px", "padding": "13px 15px"})

    return html.Div([load_panel, des_panel], style={
        "display": "grid", "gridTemplateColumns": "1.4fr 1fr",
        "gap": "12px", "marginBottom": "18px",
    })


# ── Balance designers panel ───────────────────────────────────────────────────

def _build_balance_panel(stories: list):
    des_stories: dict[str, list] = {d: [] for d in _DESIGNERS}
    unassigned_stories: list     = []

    for s in stories:
        if s["design_done"]:
            continue
        des = s.get("designer")
        if des in _DESIGNERS:
            des_stories[des].append(s)
        else:
            unassigned_stories.append(s)

    def _pts(slist):
        return sum(_SIZE_PTS.get(s["size"], 0) for s in slist)

    all_vals = [_pts(des_stories[d]) for d in _DESIGNERS] + [_pts(unassigned_stories)]
    max_pts  = max(max(all_vals), _TARGET_PTS, 1)
    tgt_pct  = _TARGET_PTS / max_pts * 100

    # ── Single bar row (used in the top summary block) ────────────────────────
    def _bar_row(label, pts, label_color=_FG):
        bar_pct   = min(pts / max_pts * 100, 100)
        delta     = pts - _TARGET_PTS
        if   delta > 0: dtxt, dcol = f"{delta}p OVER",  _RED
        elif delta < 0: dtxt, dcol = f"{-delta}p UNDER", _DIM
        else:           dtxt, dcol = "On target",        _GREEN

        return html.Div([
            html.Span(label, style={
                "fontSize": "12.5px", "fontWeight": "700",
                "color": label_color, "minWidth": "82px", "flexShrink": "0",
            }),
            html.Div([
                html.Div([                                       # track (overflow hidden)
                    html.Div(style={
                        "width": f"{bar_pct:.1f}%", "height": "100%",
                        "background": _INDIGO, "borderRadius": "3px",
                    }),
                ], style={
                    "height": "6px", "borderRadius": "3px",
                    "background": _BG_HEAD, "overflow": "hidden",
                }),
                html.Div(style={                                 # target line overlay
                    "position": "absolute", "left": f"{tgt_pct:.1f}%",
                    "top": "-3px", "height": "12px", "width": "2px",
                    "background": _FG, "opacity": "0.35",
                    "borderRadius": "1px", "transform": "translateX(-50%)",
                }),
            ], style={"position": "relative", "flex": "1"}),
            html.Span(dtxt, style={
                "fontSize": "10px", "fontWeight": "700", "color": dcol,
                "whiteSpace": "nowrap", "marginLeft": "10px",
                "minWidth": "64px", "textAlign": "right",
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "9px"})

    # ── Story row ─────────────────────────────────────────────────────────────
    def _story_row(s, current_designer):
        sz       = s.get("size") or ""
        abbr     = _SIZE_ABBR.get(sz, "?")
        sz_color = _SIZE_COLORS.get(sz, _MT)
        r        = _rgb(sz_color)
        t        = s["title"][:45] + ("…" if len(s["title"]) > 45 else "")
        start    = f"start {_MON_ABBR[s['des_month']]}"

        size_tag = html.Span(abbr, style={
            "fontSize": "10px", "fontWeight": "800",
            "color": sz_color,
            "background": f"rgba({r},0.18)",
            "border": f"1px solid rgba({r},0.35)",
            "borderRadius": "4px", "padding": "2px 6px",
            "flexShrink": "0", "minWidth": "22px", "textAlign": "center",
        })

        reassign_btns = []
        for d in _DESIGNERS:
            if d == current_designer:
                continue
            reassign_btns.append(html.Button(
                f"→ {d.split()[0]}",
                id={"type": "dp-reassign-btn", "story": str(s["id"]), "to": d},
                n_clicks=0,
                style={
                    "fontSize": "10px", "fontWeight": "600", "color": _CYAN,
                    "background": "transparent",
                    "border": f"1px solid rgba({_rgb(_CYAN)},0.3)",
                    "borderRadius": "4px", "padding": "2px 7px", "cursor": "pointer",
                },
            ))
        if current_designer:
            reassign_btns.append(html.Button(
                "✕",
                id={"type": "dp-unassign-btn", "story": str(s["id"])},
                n_clicks=0,
                style={
                    "fontSize": "12px", "color": _DIM,
                    "background": "transparent", "border": "none",
                    "cursor": "pointer", "padding": "2px 5px",
                },
            ))

        return html.Div([
            html.Div([
                size_tag,
                html.A(f"#{s['id']}",
                       href=(f"https://expenseondemand.visualstudio.com/"
                             f"Solo%20Expenses/_workitems/edit/{s['id']}"),
                       target="_blank",
                       style={
                           "color": _INDIGO, "fontFamily": _MONO,
                           "fontSize": "11px", "fontWeight": "700",
                           "textDecoration": "none", "flexShrink": "0",
                       }),
                html.Span(t, style={
                    "fontSize": "11.5px", "color": _MT, "flex": "1",
                    "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
                }),
                html.Span(start, style={
                    "fontSize": "10px", "color": _DIM, "flexShrink": "0", "whiteSpace": "nowrap",
                }),
            ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "5px"}),
            html.Div(reassign_btns, style={
                "display": "flex", "gap": "5px", "paddingLeft": "28px", "flexWrap": "wrap",
            }),
        ], style={"padding": "7px 0", "borderBottom": f"1px solid {_BD_CELL}"})

    # ── Top summary: all bars grouped ─────────────────────────────────────────
    bar_rows = [_bar_row(d.split()[0], _pts(des_stories[d])) for d in _DESIGNERS]

    summary_block = html.Div([
        *bar_rows,
        html.Div(
            f"Vertical line = target.  "
            f"Load pts: Big {_SIZE_PTS['Big']} · Medium {_SIZE_PTS['Medium']} · "
            f"Small {_SIZE_PTS['Small']} · Very Small {_SIZE_PTS['Very Small']}.",
            style={"fontSize": "10px", "color": _DIM, "marginTop": "4px"},
        ),
    ], style={
        "padding": "14px 16px 12px",
        "borderBottom": f"1px solid {_BD}",
    })

    # ── Per-designer story sections ───────────────────────────────────────────
    sections = []
    for d in _DESIGNERS:
        slist = des_stories[d]
        pts   = _pts(slist)
        sections.append(html.Div([
            html.Div([
                html.Span(d.split()[0], style={"fontSize": "13px", "fontWeight": "700", "color": _FG}),
                html.Span(f"{len(slist)} stories · {pts}p",
                          style={"fontSize": "11px", "color": _DIM, "marginLeft": "8px"}),
            ], style={"display": "flex", "alignItems": "baseline", "marginBottom": "8px"}),
            html.Div(
                [_story_row(s, d) for s in slist] if slist
                else [html.Div("No stories assigned.",
                               style={"fontSize": "11px", "color": _DIM})],
            ),
        ], style={"marginBottom": "20px"}))

    upts = _pts(unassigned_stories)
    sections.append(html.Div([
        html.Div([
            html.Span("Unassigned", style={"fontSize": "13px", "fontWeight": "700", "color": _SALMON}),
            html.Span(f"{len(unassigned_stories)} stories · {upts}p",
                      style={"fontSize": "11px", "color": _DIM, "marginLeft": "8px"}),
        ], style={"display": "flex", "alignItems": "baseline", "marginBottom": "8px"}),
        html.Div(
            [_story_row(s, None) for s in unassigned_stories] if unassigned_stories
            else [html.Div("All stories assigned.",
                           style={"fontSize": "11px", "color": _GREEN})],
        ),
    ]))

    return html.Div([
        # Header
        html.Div([
            html.Div([
                html.Div("BALANCE DESIGNERS", style={
                    "fontSize": "9.5px", "fontWeight": "700", "color": _CYAN,
                    "textTransform": "uppercase", "letterSpacing": "0.6px",
                }),
                html.Div(
                    f"Target ≈ {_TARGET_PTS} load pts per designer. Move stories to even out the load.",
                    style={"fontSize": "11.5px", "color": _MT, "marginTop": "4px"},
                ),
            ], style={"flex": "1"}),
            html.Button("✕", id="dp-panel-close", n_clicks=0, style={
                "background": "none", "border": "none", "color": _DIM,
                "fontSize": "18px", "cursor": "pointer", "padding": "0 0 0 10px",
                "lineHeight": "1",
            }),
        ], style={
            "display": "flex", "alignItems": "flex-start",
            "padding": "16px 16px 12px", "borderBottom": f"1px solid {_BD}",
        }),
        # Summary bars (always at top)
        summary_block,
        # Story sections (scrollable)
        html.Div([*sections], style={"padding": "16px 16px 24px"}),
    ])


# ── Story table ───────────────────────────────────────────────────────────────

_TH_B = {
    "padding": "9px 10px", "fontSize": "10px", "fontWeight": "700",
    "color": _DIM, "textTransform": "uppercase", "letterSpacing": "0.4px",
    "whiteSpace": "nowrap", "verticalAlign": "middle",
    "background": _BG_HEAD,
}
_TD_B = {
    "padding": "9px 10px",
    "borderBottom": f"1px solid {_BD_CELL}",
    "borderRight":  f"1px solid {_BD_CELL}",
    "fontSize": "12px", "verticalAlign": "middle",
}


def _size_badge(size_val: str):
    if not size_val:
        return html.Span("—", style={"color": _DIM, "fontSize": "12px"})
    c = _SIZE_COLORS.get(size_val, _MT)
    r = _rgb(c)
    return html.Span(size_val, style={
        "fontSize": "11px", "fontWeight": "700",
        "padding": "2px 8px", "borderRadius": "5px",
        "background": f"rgba({r},0.18)",
        "border": f"1px solid rgba({r},0.333)",
        "color": c, "whiteSpace": "nowrap",
    })


def _month_cell(story: dict, ym: tuple, today: date):
    year, month = ym
    is_des = (story["des_year"], story["des_month"]) == (year, month)
    is_dev = (story["dev_year"], story["dev_month"]) == (year, month)

    # Overdue stories whose design-start month is before today won't appear in any
    # visible column — bubble them into the current month cell instead.
    is_overdue_bubble = (
        not story["design_done"]
        and (story["des_year"], story["des_month"]) < (today.year, today.month)
        and (year, month) == (today.year, today.month)
    )

    cell_style = {**_TD_B, "minWidth": "84px", "textAlign": "center"}

    if not is_des and not is_overdue_bubble:
        if is_dev:
            return html.Td(
                html.Span("dev", style={"fontSize": "10px", "color": _DIM, "fontFamily": _MONO}),
                style=cell_style,
            )
        return html.Td("", style=cell_style)

    status = _cell_status(story, today)
    # Overdue-bubble always renders as overdue regardless of in_dev state
    if is_overdue_bubble and not is_des:
        status = "overdue"
    color  = _STATUS_COLORS[status]
    r      = _rgb(color)

    has_designer = bool(story.get("designer"))
    label       = story["designer"].split()[0] if has_designer else "assign"
    text_color  = _FG
    font_size   = "12px" if has_designer else "11px"
    font_weight = "700"  if has_designer else "600"

    return html.Td(
        html.Span(label, style={
            "fontSize": font_size, "fontWeight": font_weight, "color": text_color,
        }),
        style={**cell_style,
               "background": f"rgba({r},0.14)",
               "boxShadow": f"rgba({r},0.333) 0px 0px 0px 1px inset"},
    )


def _build_table(stories: list, plan_months: list, today: date):
    # Fixed column definitions: (label, extra_th_style)
    fixed_cols = [
        ("ID",           {"minWidth": "58px",  "position": "sticky", "left": "0px",
                          "zIndex": "3", "background": _BG_HEAD}),
        ("Title",        {"minWidth": "280px", "maxWidth": "340px",
                          "position": "sticky", "left": "58px",
                          "zIndex": "3", "background": _BG_HEAD}),
        ("Size",         {"minWidth": "84px",  "textAlign": "center"}),
        ("Dev Mo.",      {"minWidth": "64px",  "textAlign": "center"}),
        ("Design Start", {"minWidth": "92px",  "textAlign": "center"}),
        ("Status",       {"minWidth": "96px",  "textAlign": "center"}),
        ("Release",      {"minWidth": "110px"}),
        ("Owner",        {"minWidth": "78px"}),
    ]

    head_cells = [html.Th(col, style={**_TH_B, **extra}) for col, extra in fixed_cols]
    for y, m in plan_months:
        head_cells.append(html.Th(
            _MON_ABBR[m].upper(),
            style={**_TH_B, "textAlign": "center", "minWidth": "84px",
                   "color": _AMBER,
                   "background": f"rgba({_rgb(_AMBER)},0.15)"},
        ))

    body_rows = []
    for s in stories:
        status   = _cell_status(s, today)
        s_color  = _STATUS_COLORS[status]
        dev_abbr = f"{_MON_ABBR[s['dev_month']]} {str(s['dev_year'])[2:]}"
        des_abbr = f"{_MON_ABBR[s['des_month']]} {str(s['des_year'])[2:]}"
        dev_name = s["developer"].split()[0] if s.get("developer") else "—"
        release  = _fmt_release(s["release"])

        tr = html.Tr([
            # ID — sticky
            html.Td(
                html.A(str(s["id"]),
                       href=(f"https://expenseondemand.visualstudio.com/"
                             f"Solo%20Expenses/_workitems/edit/{s['id']}"),
                       target="_blank",
                       className="ado-vsts-link",
                       style={"color": _INDIGO, "fontFamily": _MONO, "fontSize": "11.5px",
                              "fontWeight": "700", "textDecoration": "none"}),
                style={**_TD_B, "position": "sticky", "left": "0px", "zIndex": "2",
                       "background": _BG_CARD},
            ),
            # Title — sticky
            html.Td(
                html.Span(s["title"], style={
                    "display": "block", "maxWidth": "340px", "overflow": "hidden",
                    "textOverflow": "ellipsis", "whiteSpace": "nowrap", "color": _FG,
                }),
                style={**_TD_B, "position": "sticky", "left": "58px", "zIndex": "2",
                       "background": _BG_CARD, "maxWidth": "340px"},
            ),
            # Size
            html.Td(_size_badge(s["size"]), style={**_TD_B, "textAlign": "center"}),
            # Dev Mo.
            html.Td(dev_abbr, style={**_TD_B, "color": _FG, "fontFamily": _MONO,
                                      "fontSize": "11.5px", "textAlign": "center"}),
            # Design Start — colored by status
            html.Td(des_abbr, style={**_TD_B, "color": s_color, "fontFamily": _MONO,
                                      "fontSize": "11.5px", "fontWeight": "700",
                                      "textAlign": "center"}),
            # Status — binary Complete / Incomplete
            html.Td(
                html.Span(
                    "Complete" if s["design_done"] else "Incomplete",
                    style={"fontSize": "11px", "fontWeight": "700",
                           "color": _GREEN if s["design_done"] else _MT},
                ),
                style={**_TD_B, "textAlign": "center"},
            ),
            # Release
            html.Td(release or "—", style={**_TD_B, "color": _MT,
                                            "fontSize": "11.5px", "whiteSpace": "nowrap"}),
            # Owner
            html.Td(s["owner"] or "—", style={**_TD_B, "color": _MT}),
            # Month cells
            *[_month_cell(s, ym, today) for ym in plan_months],
        ],
            id={"type": "dp-row", "key": str(s["id"])},
            n_clicks=0,
            style={"cursor": "pointer", "background": "transparent"},
        )
        body_rows.append(tr)

    legend = html.Div([
        html.Span("Design Start Cell", style={
            "fontSize": "10px", "fontWeight": "700", "color": _DIM,
            "textTransform": "uppercase", "letterSpacing": "0.5px", "marginRight": "14px",
        }),
        *[html.Span([
            html.Span(style={
                "width": "8px", "height": "8px", "borderRadius": "2px",
                "background": _STATUS_COLORS[k], "display": "inline-block",
                "marginRight": "5px", "opacity": "0.75",
            }),
            html.Span(v, style={"fontSize": "11px", "color": _MT, "marginRight": "12px"}),
        ]) for k, v in _STATUS_LABELS.items() if k != "not_in_dev"],
        html.Span("· designer shown one month before the dev month",
                  style={"fontSize": "10.5px", "color": _DIM}),
    ], style={"display": "flex", "alignItems": "center", "marginBottom": "9px",
              "flexWrap": "wrap", "gap": "2px"})

    return html.Div([
        legend,
        html.Div(
            html.Table(
                [html.Thead(html.Tr(head_cells),
                            style={"position": "sticky", "top": "0", "zIndex": "2"}),
                 html.Tbody(body_rows)],
                style={"borderCollapse": "collapse", "width": "100%", "minWidth": "1400px"},
            ),
            style={
                "border": f"1px solid {_BD}", "borderRadius": "12px",
                "overflow": "auto", "maxHeight": "calc(100vh - 450px)",
            },
        ),
        html.Div(
            "Click a row to assign a designer, adjust dev month, size, developer, or owner. "
            "All changes write back to ADO immediately.",
            style={"fontSize": "10.5px", "color": _DIM, "marginTop": "8px"},
        ),
    ])


# ── Panel helpers ─────────────────────────────────────────────────────────────

def _tog(label: str, btn_id: dict, active: bool, color: str = _INDIGO):
    r = _rgb(color)
    return html.Button(label, id=btn_id, n_clicks=0, style={
        "padding": "6px 13px", "borderRadius": "7px", "cursor": "pointer",
        "fontSize": "12px",
        "fontWeight": "700" if active else "500",
        "background": f"rgba({r},0.20)" if active else _BG_HEAD,
        "border": f"1px solid rgba({r},0.55)" if active else f"1px solid {_BD}",
        "color": color if active else "rgb(160,167,185)",
    })


def _sec(label: str):
    return html.Div(label, style={
        "fontSize": "9px", "fontWeight": "700", "color": _DIM,
        "textTransform": "uppercase", "letterSpacing": "0.9px",
        "marginBottom": "9px", "marginTop": "20px",
        "borderBottom": f"1px solid {_BD}",
        "paddingBottom": "6px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────

def layout(**_):
    today = date.today()

    plan_months = []
    for i in range(12):
        raw = today.month + i
        y   = today.year + (raw - 1) // 12
        m   = ((raw - 1) % 12) + 1
        plan_months.append((y, m))

    try:
        stories, iter_map = _load_data()
    except Exception:
        stories, iter_map = [], {}

    iter_map_store = {f"{y}_{m}": p for (y, m), p in iter_map.items()}

    return html.Div([
        dcc.Store(id="dp-iter-map", data=iter_map_store),

        # Header
        html.Div([
            html.Div([
                html.Span("EOD · DESIGN PLANNING", style={
                    "fontSize": "10px", "fontWeight": "700", "color": _INDIGO,
                    "textTransform": "uppercase", "letterSpacing": "1px",
                }),
                html.H1("Designer Planning", style={
                    "fontSize": "21px", "fontWeight": "700", "color": _FG,
                    "margin": "4px 0 0 0",
                }),
                html.Div(
                    "Designers start one month before the planned dev month. "
                    "A story counts as done once its design is added to the story.",
                    style={"fontSize": "12px", "color": _MT, "marginTop": "5px"},
                ),
                html.Div(
                    "ℹ Month columns = dev iteration months (sprint cadence), not release dates.",
                    style={"fontSize": "10px", "color": _MT, "marginTop": "2px",
                           "fontStyle": "italic"},
                ),
            ]),
            html.Div([
                html.Button([
                    html.Span("⚖", style={"marginRight": "6px"}),
                    "Balance designers",
                ], id="dp-balance-btn", n_clicks=0, style={
                    "padding": "8px 16px", "borderRadius": "8px",
                    "background": "transparent",
                    "border": f"1px solid rgba({_rgb(_CYAN)},0.5)",
                    "color": _CYAN, "cursor": "pointer",
                    "fontSize": "12.5px", "fontWeight": "600",
                }),
                html.Div(
                    f"Planning as of {_MON_ABBR[today.month]} {today.year}",
                    style={
                        "fontSize": "11px", "color": _DIM, "fontFamily": _MONO,
                        "background": _BG_HEAD, "border": f"1px solid {_BD}",
                        "borderRadius": "8px", "padding": "7px 12px",
                    },
                ),
            ], style={"display": "flex", "alignItems": "center", "gap": "10px"}),
        ], style={
            "padding": "18px 24px", "borderBottom": f"1px solid {_BD}",
            "display": "flex", "justifyContent": "space-between", "alignItems": "flex-start",
            "background": _BG_CARD,
        }),

        # KPIs
        _build_kpis(stories, today),

        # Body: load table + story table + side panel
        html.Div([
            html.Div([
                _build_summary_panels(stories, plan_months),
                _build_table(stories, plan_months, today),
            ], style={"flex": "1", "overflow": "auto", "padding": "20px 24px", "minWidth": "0"}),

        ], style={"display": "flex", "flex": "1", "overflow": "hidden", "minHeight": "0"}),

        # Side panel — fixed overlay, spans full viewport height
        html.Div([
            dcc.Store(id="dp-panel-store"),
            dcc.Store(id="dp-panel-visible", data=False),
            dcc.Store(id="dp-pending",       data={}),
            dcc.Store(id="dp-initial",       data={}),
            html.Div(id="dp-panel-content"),
        ], id="dp-panel-wrapper", style={
            "position": "fixed", "top": "0", "right": "0",
            "height": "100vh", "width": "760px",
            "background": _BG_CARD, "borderLeft": f"1px solid {_BD}",
            "overflowY": "auto", "zIndex": "41", "display": "none",
            "boxShadow": "rgba(0,0,0,0.467) -8px 0px 24px",
        }),

    ], style={
        "display": "flex", "flexDirection": "column",
        "height": "100vh", "background": _BG_PAGE, "overflow": "hidden",
    })


# ── Callbacks ─────────────────────────────────────────────────────────────────

_PENDING_LABELS = {
    "main_designer": "designer", "story_size": "size",
    "main_developer": "developer", "story_owner": "owner",
    "release_date": "release", "iteration_key": "iteration",
    "priority": "priority", "type": "type",
}


@callback(
    Output("dp-panel-wrapper",  "style"),
    Input("dp-panel-visible",   "data"),
)
def _panel_visibility(visible):
    base = {
        "position": "fixed", "top": "0", "right": "0",
        "height": "100vh", "width": "760px",
        "background": _BG_CARD, "borderLeft": f"1px solid {_BD}",
        "overflowY": "auto", "zIndex": "41",
        "boxShadow": "rgba(0,0,0,0.467) -8px 0px 24px",
    }
    return {**base, "display": "block" if visible else "none"}


@callback(
    Output("dp-panel-store",   "data"),
    Output("dp-panel-visible", "data"),
    Output("dp-pending",       "data"),
    Input({"type": "dp-row", "key": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _open_panel(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    story_id = int(tid["key"])
    return story_id, True, {}


@callback(
    Output("dp-panel-content", "children"),
    Output("dp-initial",       "data"),
    Input("dp-panel-store",    "data"),
    Input("dp-pending",        "data"),
    State("dp-iter-map",       "data"),
    prevent_initial_call=True,
)
def _render_panel(story_id, pending, iter_map_store):
    if story_id is None:
        raise PreventUpdate
    if story_id == "__balance__":
        try:
            stories, _ = _load_data()
        except Exception:
            stories = []
        return _build_balance_panel(stories), no_update
    today = date.today()

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT w.work_item_id, w.title, w.state, w.iteration_path,
                   w.main_designer, w.main_developer, w.story_owner,
                   w.release_date,
                   COALESCE(w.story_size,   '') AS story_size,
                   COALESCE(w.story_status, '') AS story_status,
                   COALESCE(w.priority,     '') AS priority,
                   COALESCE(w.type, 'Internal') AS cust_type,
                   COALESCE(g.our_screens,  FALSE) AS our_screens,
                   COALESCE(g.html_screens, FALSE) AS html_screens
            FROM work_items_main w
            LEFT JOIN p_planning_gates g ON g.work_item_id = w.work_item_id
            WHERE w.work_item_id = :id
        """), {"id": story_id}).fetchone()
        _rd_rows = conn.execute(text(
            "SELECT DISTINCT release_date FROM work_items_main"
            " WHERE release_date IS NOT NULL AND release_date != ''"
            " ORDER BY release_date"
        )).fetchall()
    dp_rd_vals = [r.release_date for r in _rd_rows]

    if not row:
        return html.Div("Story not found.", style={"padding": "20px", "color": _MT}), no_update

    p = _parse_iter(row.iteration_path or "")
    if not p:
        return html.Div("No parseable iteration.", style={"padding": "20px", "color": _MT}), no_update

    dev_year, dev_month = p
    dy, dm = _des_ym(dev_year, dev_month)
    done   = bool(row.our_screens) and bool(row.html_screens)
    in_dev = row.state in _DEV_STATES

    if done:
        sk = "complete"
    elif not in_dev:
        sk = "not_in_dev"
    elif (dy, dm) < (today.year, today.month):
        sk = "overdue"
    elif (dy, dm) == (today.year, today.month):
        sk = "due_now"
    else:
        sk = "scheduled"

    color = _STATUS_COLORS[sk]
    label = _STATUS_LABELS[sk]
    texts = {
        "scheduled":  (f"Dev month is {_MON_ABBR[dev_month]}, so design must start in "
                       f"{_MON_ABBR[dm]} (one month before)."),
        "due_now":    f"Design is due NOW — dev month is {_MON_ABBR[dev_month]}.",
        "overdue":    f"Design was due in {_MON_ABBR[dm]} — dev month {_MON_ABBR[dev_month]} has passed.",
        "complete":   (f"Dev month is {_MON_ABBR[dev_month]}, so design must start in "
                       f"{_MON_ABBR[dm]} (one month before). Design has been added to the story."),
        "not_in_dev": "Story is not yet in an active development state.",
    }

    def _clean(v):
        s = (v or "").strip()
        return s if s not in ("Unassigned", "") else None

    cur_designer     = _clean(row.main_designer)
    cur_developer    = _clean(row.main_developer)
    cur_owner        = (row.story_owner   or "").strip()
    cur_size         = (row.story_size or "").strip().title()
    cur_story_status = row.story_status   or ""
    cur_priority     = str(row.priority or "").strip()
    cur_cust_type    = (row.cust_type or "Internal").strip()
    cur_release      = str(row.release_date or "").strip()

    # Build iteration dropdown options from iter_map store
    _iter_opts = []
    if iter_map_store:
        for k in sorted(iter_map_store.keys()):
            try:
                y_s, m_s = k.split("_")
                _iter_opts.append({
                    "label": f"{_MON_ABBR[int(m_s)]} {y_s}",
                    "value": k,
                })
            except Exception:
                pass
    cur_iter_key = f"{dev_year}_{dev_month}"

    # Merge pending over DB values
    pending = pending or {}
    eff_designer  = pending.get("main_designer",  cur_designer)
    eff_size      = pending.get("story_size",      cur_size)
    eff_developer = pending.get("main_developer",  cur_developer)
    eff_owner     = pending.get("story_owner",     cur_owner)
    eff_release   = pending.get("release_date",
                                cur_release if cur_release in dp_rd_vals else None)
    eff_iter_key  = pending.get("iteration_key",   cur_iter_key)
    eff_priority  = pending.get("priority",        cur_priority)
    eff_type      = pending.get("type",            cur_cust_type)
    n_pending     = len(pending)

    # Extract platform prefix from title for a badge
    _title_raw = row.title or ""
    _plt_label = None
    _plt_color = _INDIGO
    for _pfx, _col in [("WEB | ", _INDIGO), ("Web | ", _INDIGO),
                        ("iOS | ", _CYAN), ("Android | ", _GREEN),
                        ("Mobile | ", _CYAN)]:
        if _title_raw.upper().startswith(_pfx.upper()):
            _plt_label = _pfx.strip(" |")
            _plt_color = _col
            break

    btn_label = "Save Changes"

    return html.Div([
        # Title bar
        html.Div([
            html.Div([
                html.Div([
                    html.Span(f"DESIGN PLAN · #{story_id}", style={
                        "fontSize": "9.5px", "fontWeight": "700", "color": _INDIGO,
                        "textTransform": "uppercase", "letterSpacing": "0.6px",
                    }),
                    *([html.Span(_plt_label, style={
                        "fontSize": "9px", "fontWeight": "700",
                        "color": _plt_color,
                        "background": f"rgba({_rgb(_plt_color)},0.15)",
                        "border": f"1px solid rgba({_rgb(_plt_color)},0.3)",
                        "borderRadius": "4px", "padding": "1px 7px",
                        "marginLeft": "9px", "verticalAlign": "middle",
                    })] if _plt_label else []),
                ], style={"display": "flex", "alignItems": "center"}),
                html.Div(_title_raw, style={
                    "fontSize": "13px", "fontWeight": "600", "color": _FG,
                    "marginTop": "6px", "lineHeight": "1.4",
                }),
                html.Div([
                    *([html.Span(cur_priority, style={
                        "background": {
                            "P1": "rgba(239,68,68,0.15)", "P2": "rgba(251,191,36,0.12)",
                            "P3": "rgba(52,211,153,0.10)",
                        }.get(cur_priority, "rgba(148,163,184,0.08)"),
                        "color": {
                            "P1": "rgb(239,68,68)", "P2": "rgb(251,191,36)",
                            "P3": "rgb(52,211,153)",
                        }.get(cur_priority, "rgb(148,163,184)"),
                        "border": "1px solid " + {
                            "P1": "rgba(239,68,68,0.35)", "P2": "rgba(251,191,36,0.30)",
                            "P3": "rgba(52,211,153,0.25)",
                        }.get(cur_priority, "rgba(148,163,184,0.20)"),
                        "borderRadius": "4px", "padding": "1px 6px",
                        "fontSize": "10px", "fontWeight": "600", "whiteSpace": "nowrap",
                    })] if cur_priority else []),
                    *([html.Span(cur_release, style={
                        "background": "rgba(6,182,212,0.10)",
                        "color": "rgb(6,182,212)",
                        "border": "1px solid rgba(6,182,212,0.25)",
                        "borderRadius": "4px", "padding": "1px 6px",
                        "fontSize": "10px", "fontWeight": "600", "whiteSpace": "nowrap",
                    })] if cur_release else []),
                ], style={
                    "display": "flex", "flexWrap": "wrap", "gap": "4px", "marginTop": "7px",
                }),
            ], style={"flex": "1"}),
            html.Button("✕", id="dp-panel-close", n_clicks=0, style={
                "background": f"rgba({_rgb(_DIM)},0.1)", "border": f"1px solid {_BD}",
                "borderRadius": "6px", "color": _MT,
                "fontSize": "14px", "cursor": "pointer", "padding": "4px 8px",
                "lineHeight": "1", "flexShrink": "0",
            }),
        ], style={"display": "flex", "alignItems": "flex-start",
                  "padding": "16px 16px 14px", "borderBottom": f"1px solid {_BD}"}),

        # Status banner
        html.Div([
            html.Div([
                html.Span("●", style={"marginRight": "6px", "fontSize": "10px"}),
                html.Span(label, style={"fontSize": "11px", "fontWeight": "700",
                                        "textTransform": "uppercase", "letterSpacing": "0.5px"}),
            ], style={
                "color": color, "marginBottom": "5px",
                "display": "flex", "alignItems": "center",
            }),
            html.Div(texts.get(sk, ""),
                     style={"fontSize": "12px", "color": _MT, "lineHeight": "1.5"}),
        ], style={
            "margin": "14px 16px 0", "padding": "11px 14px",
            "background": f"rgba({_rgb(color)},0.07)",
            "border": f"1px solid rgba({_rgb(color)},0.25)",
            "borderLeft": f"3px solid {color}",
            "borderRadius": "8px",
        }),

        html.Div([
            _sec("Designer"),
            html.Div([
                _tog(d.split()[0], {"type": "dp-designer-btn", "key": d},
                     active=(d == eff_designer), color=_CYAN)
                for d in _DESIGNERS
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

            _sec("Priority"),
            html.Div([
                _tog(pr, {"type": "dp-prio-btn", "key": _PRI_MAP[pr]},
                     active=(eff_priority == _PRI_MAP[pr]),
                     color=_PRI_COLORS[pr])
                for pr in _PRIORITIES
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

            _sec("Type"),
            html.Div([
                _tog(t, {"type": "dp-type-btn", "key": t},
                     active=(eff_type == t), color=_AMBER)
                for t in ("Customer", "Internal")
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

            _sec("Iteration"),
            dcc.Dropdown(
                id="dp-iter-dropdown",
                options=_iter_opts,
                value=eff_iter_key if eff_iter_key in {o["value"] for o in _iter_opts} else None,
                placeholder="Select iteration month…",
                clearable=False,
                className="dark-dropdown",
                style={"fontSize": "13px"},
            ),
            dcc.Store(id="dp-devmon-value", data={"year": dev_year, "month": dev_month}),

            _sec("Release Date"),
            dcc.Dropdown(
                id="dp-release-dd",
                options=[{"label": v, "value": v} for v in dp_rd_vals],
                value=eff_release if eff_release in dp_rd_vals else None,
                placeholder="Select release month…",
                clearable=True,
                className="dark-dropdown",
                style={"fontSize": "13px"},
            ),

            _sec("Story Size"),
            html.Div([
                _tog(sz, {"type": "dp-size-btn", "key": sz},
                     active=(sz == eff_size), color=_SIZE_COLORS.get(sz, _INDIGO))
                for sz in _SIZES
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

            _sec("Developer"),
            html.Div([
                _tog(d.split()[0], {"type": "dp-dev-btn", "key": d},
                     active=(d == eff_developer), color=_INDIGO)
                for d in DEV_NAMES
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

            _sec("User Story Owner"),
            html.Div([
                _tog(o, {"type": "dp-owner-btn", "key": o},
                     active=(o == eff_owner), color=_INDIGO)
                for o in _STORY_OWNERS
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

            _sec("Design Progress"),
            _story_status_badge(row.work_item_id),
            html.Div("Driven by Story Readiness gates. Set gates there to update.",
                     style={"fontSize": "11px", "color": _DIM, "marginTop": "5px"}),

            # ── Move / Clear buttons ───────────────────────────────────────────
            html.Div([
                html.Button(
                    btn_label,
                    id="dp-move-btn",
                    n_clicks=0,
                    disabled=(n_pending == 0),
                    style={
                        "padding": "10px 20px", "borderRadius": "8px", "flex": "1",
                        "background": f"rgba({_rgb(_GREEN)},0.15)" if n_pending else _BG_HEAD,
                        "border": (f"1px solid rgba({_rgb(_GREEN)},0.5)" if n_pending
                                   else f"1px solid {_BD}"),
                        "color": _GREEN if n_pending else _DIM,
                        "cursor": "pointer" if n_pending else "default",
                        "fontSize": "13px", "fontWeight": "700",
                    },
                ),
                html.Button(
                    "Clear",
                    id="dp-clear-btn",
                    n_clicks=0,
                    disabled=(n_pending == 0),
                    style={
                        "padding": "10px 16px", "borderRadius": "8px",
                        "background": "transparent",
                        "border": f"1px solid rgba({_rgb(_RED)},0.4)" if n_pending else f"1px solid {_BD}",
                        "color": _RED if n_pending else _DIM,
                        "cursor": "pointer" if n_pending else "default",
                        "fontSize": "13px", "fontWeight": "600",
                    },
                ),
            ], style={
                "display": "flex", "gap": "8px",
                "marginTop": "28px", "paddingTop": "16px",
                "borderTop": f"1px solid {_BD}",
            }),

        ], style={"padding": "4px 16px 32px"}),
    ]), {"iteration_key": cur_iter_key, "release_date": cur_release or ""}


@callback(
    Output("dp-panel-visible", "data", allow_duplicate=True),
    Output("dp-pending",       "data", allow_duplicate=True),
    Input("dp-panel-close", "n_clicks"),
    prevent_initial_call=True,
)
def _close_panel(n):
    if not n:
        raise PreventUpdate
    return False, {}


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input({"type": "dp-designer-btn", "key": ALL}, "n_clicks"),
    State("dp-pending", "data"),
    prevent_initial_call=True,
)
def _select_designer(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    p["main_designer"] = tid["key"]
    return p


@callback(
    Output("dp-devmon-value",   "data"),
    Output("dp-devmon-display", "children"),
    Input("dp-devmon-minus", "n_clicks"),
    Input("dp-devmon-plus",  "n_clicks"),
    State("dp-devmon-value",  "data"),
    State("dp-panel-store",   "data"),
    State("dp-iter-map",      "data"),
    prevent_initial_call=True,
)
def _change_dev_month(_, __, cur, story_id, iter_map):
    if not cur or not story_id:
        raise PreventUpdate
    y, m = cur["year"], cur["month"]
    delta = -1 if ctx.triggered_id == "dp-devmon-minus" else 1
    m += delta
    if m < 1:    y -= 1; m = 12
    elif m > 12: y += 1; m = 1
    key = f"{y}_{m}"
    if iter_map and key in iter_map:
        write_fields(story_id, {"iteration": iter_map[key]})
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE work_items_main SET iteration_path=:p WHERE work_item_id=:id"
            ), {"p": iter_map[key], "id": story_id})
    return {"year": y, "month": m}, f"{_MON_ABBR[m]} ({m:02d})"


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input({"type": "dp-size-btn", "key": ALL}, "n_clicks"),
    State("dp-pending", "data"),
    prevent_initial_call=True,
)
def _select_size(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    p["story_size"] = tid["key"]
    return p


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input({"type": "dp-dev-btn", "key": ALL}, "n_clicks"),
    State("dp-pending", "data"),
    prevent_initial_call=True,
)
def _select_developer(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    p["main_developer"] = tid["key"]
    return p


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input({"type": "dp-owner-btn", "key": ALL}, "n_clicks"),
    State("dp-pending", "data"),
    prevent_initial_call=True,
)
def _select_owner(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    p["story_owner"] = tid["key"]
    return p


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input("dp-release-dd",  "value"),
    State("dp-pending",     "data"),
    State("dp-initial",     "data"),
    prevent_initial_call=True,
)
def _select_release(rd, pending, initial):
    p = dict(pending or {})
    if p.get("release_date") == rd:
        raise PreventUpdate
    if rd == (initial or {}).get("release_date") and "release_date" not in p:
        raise PreventUpdate
    p["release_date"] = rd
    return p


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input("dp-iter-dropdown", "value"),
    State("dp-pending",       "data"),
    State("dp-initial",       "data"),
    prevent_initial_call=True,
)
def _select_iteration_dd(iter_key, pending, initial):
    if not iter_key:
        raise PreventUpdate
    p = dict(pending or {})
    if p.get("iteration_key") == iter_key:
        raise PreventUpdate
    if iter_key == (initial or {}).get("iteration_key") and "iteration_key" not in p:
        raise PreventUpdate
    p["iteration_key"] = iter_key
    return p


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input({"type": "dp-prio-btn", "key": ALL}, "n_clicks"),
    State("dp-pending", "data"),
    prevent_initial_call=True,
)
def _select_priority(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    p["priority"] = tid["key"]
    return p


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input({"type": "dp-type-btn", "key": ALL}, "n_clicks"),
    State("dp-pending", "data"),
    prevent_initial_call=True,
)
def _select_type(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    p["type"] = tid["key"]
    return p


@callback(
    Output("dp-pending", "data", allow_duplicate=True),
    Input("dp-clear-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _clear_pending(n):
    if not n:
        raise PreventUpdate
    return {}


@callback(
    Output("dp-pending",     "data",  allow_duplicate=True),
    Output("dp-panel-store", "data",  allow_duplicate=True),
    Input("dp-move-btn",     "n_clicks"),
    State("dp-pending",      "data"),
    State("dp-panel-store",  "data"),
    State("dp-iter-map",     "data"),
    prevent_initial_call=True,
)
def _commit_all_changes(n, pending, story_id, iter_map_store):
    if not n or not pending or not story_id or story_id == "__balance__":
        raise PreventUpdate
    sid        = int(story_id)
    ado_fields: dict = {}
    db_sets:    list = []
    db_params:  dict = {"id": sid}

    def _db(col, val):
        db_sets.append(f"{col}=:{col}")
        db_params[col] = val

    if "main_designer" in pending:
        v = pending["main_designer"]
        ado_fields["main_designer"] = v
        _db("main_designer", v)

    if "story_size" in pending:
        v = pending["story_size"]
        ado_fields["story_size"] = v
        _db("story_size", v)

    if "main_developer" in pending:
        v = pending["main_developer"]
        ado_fields["main_developer"] = v
        _db("main_developer", v)

    if "story_owner" in pending:
        v = pending["story_owner"]
        ado_fields["story_owner"] = v
        _db("story_owner", v)

    if "release_date" in pending:
        v = pending["release_date"]
        ado_fields["release_date"] = v or ""
        _db("release_date", v or None)

    if "iteration_key" in pending:
        full_path = (iter_map_store or {}).get(pending["iteration_key"])
        if full_path:
            ado_fields["iteration"] = full_path
            _db("iteration_path", full_path)

    if "priority" in pending:
        prio_int = int(pending["priority"])
        ado_fields["priority"] = prio_int
        _db("priority", prio_int)

    if "type" in pending:
        _db("type", pending["type"])

    if ado_fields:
        write_fields(sid, ado_fields)

    if db_sets:
        with engine.begin() as conn:
            conn.execute(text(
                f"UPDATE work_items_main SET {', '.join(db_sets)} WHERE work_item_id=:id"
            ), db_params)

    return {}, sid


@callback(
    Output("dp-panel-store",   "data",  allow_duplicate=True),
    Output("dp-panel-visible", "data",  allow_duplicate=True),
    Input("dp-balance-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _open_balance_panel(_):
    return "__balance__", True


@callback(
    Output("dp-panel-store", "data", allow_duplicate=True),
    Input({"type": "dp-reassign-btn", "story": ALL, "to": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _reassign_designer(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    story_id     = int(tid["story"])
    new_designer = tid["to"]
    write_fields(story_id, {"main_designer": new_designer})
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE work_items_main SET main_designer=:d WHERE work_item_id=:id"
        ), {"d": new_designer, "id": story_id})
    return "__balance__"


@callback(
    Output("dp-panel-store", "data", allow_duplicate=True),
    Input({"type": "dp-unassign-btn", "story": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _unassign_designer(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    story_id = int(tid["story"])
    write_fields(story_id, {"main_designer": "Unassigned"})
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE work_items_main SET main_designer=NULL WHERE work_item_id=:id"
        ), {"id": story_id})
    return "__balance__"
