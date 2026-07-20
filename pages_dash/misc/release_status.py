"""Release Status — per-story pipeline stage tracker."""
from __future__ import annotations
import re
from datetime import date

import dash
from dash import html, dcc, callback, Input, Output, State, ctx, ALL
from dash.exceptions import PreventUpdate
from sqlalchemy import text

from config.dev_capacity import DEV_NAMES, QA_NAMES, STORY_OWNER_NAMES
from data.loader import engine
from sync.ado_write import write_fields

dash.register_page(__name__, path="/release-status", name="Release Status")

# ── Stage definitions ─────────────────────────────────────────────────────────
_STAGES = [
    ("dev_status",     "Development Status"),
    ("testing_demo",   "Testing on Demo"),
    ("qa_sign_off",    "QA Sign Off"),
    ("sunil_sign_off", "Sunil's Sign Off"),
    ("final_demo_1",   "Final Demo 1 (Demo env)"),
    ("deploy_dev",     "Deployment on Dev"),
    ("dev_env",        "Dev Env."),
    ("deploy_qa",      "Deployment on QA"),
    ("final_demo_2",   "Final Demo 2 (QA env)"),
    ("qa_env",         "QA Env."),
    ("live",           "Live"),
    ("overall_status", "Overall Status"),
]
_STAGE_KEYS = [k for k, _ in _STAGES]

_QA_NAMES     = QA_NAMES
_STORY_OWNERS = STORY_OWNER_NAMES
_SIZES        = ["Big", "Medium", "Small", "Very Small"]

_ST_COLOR = {
    "done":        "rgb(70,194,142)",
    "wip":         "rgb(224,162,60)",
    "not_started": "rgb(239,110,99)",
    "n_a":         "rgb(148,163,184)",
    "":            "rgb(38,44,58)",
}
_ST_LABEL = {"done": "Done", "wip": "WIP", "not_started": "Not started", "n_a": "N/A", "": "—"}

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

_SIZE_COLORS = {
    "Big":        "rgb(224,162,60)",
    "Medium":     "rgb(181,194,74)",
    "Small":      "rgb(70,194,142)",
    "Very Small": "rgb(63,182,201)",
}

_TH_B = {
    "padding": "9px 10px", "fontSize": "10px", "fontWeight": "700",
    "color": _DIM, "textTransform": "uppercase", "letterSpacing": "0.4px",
    "whiteSpace": "nowrap", "verticalAlign": "middle", "background": _BG_HEAD,
}
_TD_B = {
    "padding": "9px 10px",
    "borderBottom": f"1px solid {_BD_CELL}",
    "borderRight":  f"1px solid {_BD_CELL}",
    "fontSize": "12px", "verticalAlign": "middle",
}


# ── DB bootstrap ──────────────────────────────────────────────────────────────
def _ensure_tables():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS p_release_rows (
                work_item_id  INTEGER PRIMARY KEY,
                qa_person     TEXT DEFAULT '',
                comment       TEXT DEFAULT '',
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS p_release_stages (
                work_item_id  INTEGER NOT NULL,
                stage_key     TEXT    NOT NULL,
                status        TEXT    NOT NULL DEFAULT 'not_started',
                stage_date    DATE,
                PRIMARY KEY (work_item_id, stage_key)
            )
        """))

try:
    _ensure_tables()
except Exception:
    pass


# ── Data loaders ──────────────────────────────────────────────────────────────
_MONTH_NUM = {
    'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
}

def _kpi_card(label, value, total, color):
    pct = round(value / total * 100) if total else 0
    return html.Div([
        html.Div(str(value), style={
            "fontSize": "30px", "fontWeight": "700", "color": color,
            "lineHeight": "1",
        }),
        html.Div(f"of {total}  ·  {pct}%", style={
            "fontSize": "10px", "color": _DIM, "marginTop": "3px",
            "fontFamily": _MONO,
        }),
        html.Div(label, style={
            "fontSize": "10px", "fontWeight": "700", "color": _MT,
            "marginTop": "8px", "textTransform": "uppercase",
            "letterSpacing": "0.6px",
        }),
    ], style={
        "background": _BG_CARD,
        "border": f"1px solid {_BD}",
        "borderTop": f"3px solid {color}",
        "borderRadius": "10px",
        "padding": "16px 20px",
        "flex": "1",
        "minWidth": "130px",
    })


def _build_kpi_strip(stories: list, stage_data: dict) -> html.Div:
    total = len(stories)
    if not total:
        return html.Div()

    def _stage_done(wid, key):
        return stage_data.get(wid, {}).get(key, {}).get("status") == "done"

    dev_done   = sum(1 for s in stories if _stage_done(s["work_item_id"], "dev_status"))
    qa_done    = sum(1 for s in stories if _stage_done(s["work_item_id"], "qa_sign_off"))
    complete   = sum(1 for s in stories if (s.get("story_status") or "").strip() == "Complete")
    live       = sum(1 for s in stories if _stage_done(s["work_item_id"], "live"))

    # Size breakdown
    size_counts = {}
    for s in stories:
        sz = (s.get("story_size") or "").strip().title() or "Unknown"
        size_counts[sz] = size_counts.get(sz, 0) + 1

    _size_order = ["Very Small", "Small", "Medium", "Big"]
    size_pills = []
    for sz in _size_order:
        if sz not in size_counts:
            continue
        col = _SIZE_COLORS.get(sz, _MT)
        size_pills.append(html.Span([
            html.Span(sz, style={"color": col, "fontWeight": "600"}),
            html.Span(f" {size_counts[sz]}", style={"color": _FG}),
        ], style={"marginRight": "16px", "fontSize": "11px"}))
    for sz, cnt in size_counts.items():
        if sz not in _size_order:
            size_pills.append(html.Span([
                html.Span(sz, style={"color": _MT, "fontWeight": "600"}),
                html.Span(f" {cnt}", style={"color": _FG}),
            ], style={"marginRight": "16px", "fontSize": "11px"}))

    return html.Div([
        # KPI cards row
        html.Div([
            _kpi_card("Total Stories",    total,    total,   _INDIGO),
            _kpi_card("Dev Complete",     dev_done, total,   _GREEN),
            _kpi_card("QA Signed Off",    qa_done,  total,   _CYAN),
            _kpi_card("Story Complete",   complete, total,   _AMBER),
            _kpi_card("Live",             live,     total,   "rgb(167,139,250)"),
        ], style={
            "display": "flex", "gap": "12px", "flexWrap": "wrap",
        }),
        # Size strip
        html.Div([
            html.Span("Size breakdown  ", style={
                "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                "textTransform": "uppercase", "letterSpacing": "0.5px",
                "marginRight": "8px",
            }),
            *size_pills,
        ], style={
            "display": "flex", "alignItems": "center", "marginTop": "12px",
            "flexWrap": "wrap",
        }),
    ], style={
        "padding": "14px 24px 16px",
        "borderBottom": f"1px solid {_BD}",
        "background": _BG_PAGE,
    })


def _release_sort_key(r: str) -> tuple:
    parts = r.split()
    year   = int(parts[0]) if parts and parts[0].isdigit() else 9999
    month  = _MONTH_NUM.get(parts[1].lower(), 0) if len(parts) > 1 else 0
    suffix = parts[2].lower() if len(parts) > 2 else ''  # '' sorts before 'hotfix'
    return (year, month, suffix)

def _get_releases():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT release_date FROM work_items_main
            WHERE release_date IS NOT NULL AND release_date != ''
              AND work_item_type IN ('Enhancement','User Story')
              AND state NOT IN ('Closed','Not an issue','Not Required',
                                'No Customer Response','Resolved','Userstory Update')
        """)).fetchall()
    releases = [r[0] for r in rows if r[0]]
    return sorted(releases, key=_release_sort_key)


def _load_stories(release: str) -> list:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT work_item_id, title, state,
                   COALESCE(story_owner,    '') AS story_owner,
                   COALESCE(main_developer, '') AS main_developer,
                   COALESCE(story_size,     '') AS story_size,
                   COALESCE(story_status,   '') AS story_status,
                   COALESCE(release_date,   '') AS release_date
            FROM work_items_main
            WHERE release_date = :rel
              AND work_item_type IN ('Enhancement','User Story')
              AND state NOT IN ('Closed','Not an issue','Not Required',
                                'No Customer Response','Resolved','Userstory Update')
            ORDER BY work_item_id
        """), {"rel": release}).fetchall()
    return [dict(r._mapping) for r in rows]


def _load_stage_data(ids: list) -> dict:
    if not ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT work_item_id, stage_key, status, stage_date
            FROM p_release_stages WHERE work_item_id = ANY(:ids)
        """), {"ids": ids}).fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r.work_item_id, {})[r.stage_key] = {
            "status": r.status or "",
            "date":   str(r.stage_date)[:10] if r.stage_date else "",
        }
    return result


def _load_row_data(ids: list) -> dict:
    if not ids:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT work_item_id, qa_person, comment
            FROM p_release_rows WHERE work_item_id = ANY(:ids)
        """), {"ids": ids}).fetchall()
    return {r.work_item_id: {"qa": r.qa_person or "", "comment": r.comment or ""}
            for r in rows}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _rgb(c):
    m = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', c)
    return f"{m.group(1)},{m.group(2)},{m.group(3)}" if m else "139,146,164"


def _size_badge(size_val):
    if not size_val:
        return html.Span("—", style={"color": _DIM})
    c = _SIZE_COLORS.get(size_val, _MT)
    r = _rgb(c)
    return html.Span(size_val, style={
        "fontSize": "11px", "fontWeight": "700",
        "padding": "2px 8px", "borderRadius": "5px",
        "background": f"rgba({r},0.18)", "border": f"1px solid rgba({r},0.333)",
        "color": c, "whiteSpace": "nowrap",
    })


def _stage_cell(status, stage_date, wid=None, stage_key=None):
    click_id = ({"type": "rs-row", "key": str(wid), "stage": stage_key or ""}
                if wid else None)
    click_style_extra = {"cursor": "pointer"} if click_id else {}
    click_props = {"id": click_id, "n_clicks": 0} if click_id else {}

    if not status:
        return html.Td("", style={**_TD_B, "minWidth": "110px",
                                  **click_style_extra}, **click_props)
    if status == "n_a":
        return html.Td(
            html.Div("N/A", style={"fontSize": "10px", "color": _DIM,
                                   "fontWeight": "600", "fontStyle": "italic"}),
            style={**_TD_B, "minWidth": "110px", **click_style_extra}, **click_props)
    color = _ST_COLOR.get(status, _ST_COLOR[""])
    r     = _rgb(color)
    return html.Td([
        html.Div(str(stage_date)[:10] if stage_date else "",
                 style={"fontFamily": _MONO, "fontSize": "10.5px",
                        "color": _FG, "fontWeight": "600"}),
        html.Div(_ST_LABEL.get(status, ""),
                 style={"fontSize": "10px", "color": color,
                        "fontWeight": "700", "marginTop": "2px"}),
    ], style={**_TD_B, "minWidth": "110px",
              "background": f"rgba({r},0.14)",
              "boxShadow": f"rgba({r},0.333) 0px 0px 0px 1px inset",
              **click_style_extra}, **click_props)


def _tog(label, btn_id, active, color=_INDIGO):
    r = _rgb(color)
    return html.Button(label, id=btn_id, n_clicks=0, style={
        "padding": "6px 12px", "borderRadius": "7px", "cursor": "pointer",
        "fontSize": "12px", "fontWeight": "600",
        "background": f"rgba({r},0.133)" if active else "transparent",
        "border": f"1px solid rgba({r},0.5)" if active else f"1px solid {_BD}",
        "color": color if active else _MT,
    })


def _story_status_badge(wid: int):
    with engine.connect() as conn:
        g = conn.execute(text("""
            SELECT claude_screens, text_written, our_screens, html_screens, sn_signoff
            FROM p_planning_gates WHERE work_item_id = :id
        """), {"id": wid}).fetchone()
    done  = sum([bool(g.claude_screens), bool(g.text_written), bool(g.our_screens),
                 bool(g.html_screens), bool(g.sn_signoff)]) if g else 0
    total = 5
    complete = done == total
    c = _GREEN if complete else (_AMBER if done > 0 else _DIM)
    r = _rgb(c)
    return html.Div([
        html.Span("Complete" if complete else "Incomplete",
                  style={"fontSize": "12px", "fontWeight": "700", "color": c}),
        html.Span(f"  {done}/{total} gates",
                  style={"fontSize": "10.5px", "color": _DIM, "marginLeft": "6px"}),
    ], style={
        "padding": "6px 10px", "borderRadius": "7px",
        "background": f"rgba({r},0.1)", "border": f"1px solid rgba({r},0.25)",
        "display": "inline-flex", "alignItems": "center",
    })


def _sec(label):
    return html.Div(label, style={
        "fontSize": "9.5px", "fontWeight": "700", "color": _DIM,
        "textTransform": "uppercase", "letterSpacing": "0.6px",
        "marginBottom": "8px", "marginTop": "14px",
    })


def _lbl(t):
    return html.Div(t, style={
        "fontSize": "9.5px", "fontWeight": "700", "color": _DIM,
        "textTransform": "uppercase", "letterSpacing": "0.5px",
        "marginBottom": "5px",
    })


# ── Release pills ─────────────────────────────────────────────────────────────
def _build_pills(releases, selected):
    if not releases:
        return [html.Span("No releases found.", style={"fontSize": "12px", "color": _DIM})]
    r = _rgb(_INDIGO)
    return [
        html.Div(rel, id={"type": "rs-release-pill", "rel": rel}, n_clicks=0, style={
            "padding": "6px 14px", "borderRadius": "8px", "cursor": "pointer",
            "fontSize": "12px", "fontWeight": "600", "whiteSpace": "nowrap",
            "background": f"rgba({r},0.18)" if rel == selected else "transparent",
            "border": f"1px solid rgba({r},0.5)" if rel == selected else f"1px solid {_BD}",
            "color": _INDIGO if rel == selected else _MT,
        })
        for rel in releases
    ]


# ── Table ─────────────────────────────────────────────────────────────────────
_SALMON = "rgb(240,137,122)"

_ADO_BASE = "https://dev.azure.com/expenseondemand/Solo%20Expenses/_workitems/edit"

# ── Sort helpers ──────────────────────────────────────────────────────────────
_REL_MONTHS = {
    "January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
    "July":7,"August":8,"September":9,"October":10,"November":11,"December":12,
}
_SIZE_RANK = {"Big": 0, "Medium": 1, "Small": 2, "Very Small": 3}
_ST_RANK   = {"done": 0, "wip": 1, "not_started": 2, "n_a": 3}


def _sort_th(lbl, col_key, sort_col, sort_dir):
    """Sortable <th> inner content: label + indicator chip."""
    if sort_col == col_key:
        ind, ind_c = ("↑", _INDIGO) if sort_dir == "asc" else ("↓", _INDIGO)
    else:
        ind, ind_c = "⇅", _BD
    return html.Div(
        [html.Span(lbl),
         html.Span(ind, style={"fontSize": "8px", "color": ind_c,
                               "marginLeft": "3px", "lineHeight": "1"})],
        id={"type": "rs-sort-th", "col": col_key},
        n_clicks=0,
        style={"display": "inline-flex", "alignItems": "center",
               "cursor": "pointer", "userSelect": "none", "gap": "1px"},
    )


def _sort_stories(stories, stage_data, row_data, col, direction):
    """Return stories sorted by col/direction; no-op when col or direction is None."""
    if not col or not direction:
        return stories

    def _rel_date_key(s):
        parts = (s.get("release_date") or "").strip().split()
        year = int(parts[0]) if parts and parts[0].isdigit() else 9999
        mon  = _REL_MONTHS.get(parts[1], 0) if len(parts) > 1 else 0
        return (year, mon)

    if col == "work_item_id":
        key_fn = lambda s: s["work_item_id"]
    elif col == "title":
        key_fn = lambda s: (s.get("title") or "").lower()
    elif col == "story_owner":
        key_fn = lambda s: (s.get("story_owner") or "").lower()
    elif col == "main_developer":
        key_fn = lambda s: (s.get("main_developer") or "").lower()
    elif col == "qa_person":
        key_fn = lambda s: (row_data.get(s["work_item_id"], {}).get("qa", "") or "").lower()
    elif col == "story_size":
        key_fn = lambda s: _SIZE_RANK.get((s.get("story_size") or "").strip().title(), 99)
    elif col == "story_status":
        key_fn = lambda s: (s.get("story_status") or "").lower()
    elif col == "release_date":
        key_fn = _rel_date_key
    elif col.startswith("stage_"):
        sk = col[6:]
        def _stage_key(s):
            info   = stage_data.get(s["work_item_id"], {}).get(sk, {})
            status = info.get("status") or "not_started"
            return (_ST_RANK.get(status, 4), str(info.get("date") or ""))
        key_fn = _stage_key
    else:
        return stories

    return sorted(stories, key=key_fn, reverse=(direction == "desc"))


def _build_table(stories, stage_data, row_data, selected_id=None, selected_ids=None,
                 sort_col=None, sort_dir=None):
    sel_set = set(selected_ids or [])
    all_ids = [s["work_item_id"] for s in stories]
    all_checked = bool(all_ids) and set(all_ids) <= sel_set

    # Select-all checkbox header
    chk_th = html.Th(
        html.Div(
            "✓" if all_checked else "",
            id="rs-select-all-btn",
            n_clicks=0,
            style={
                "width": "16px", "height": "16px", "borderRadius": "4px",
                "border": f"2px solid {_INDIGO if all_checked else _DIM}",
                "background": f"rgba({_rgb(_INDIGO)},0.25)" if all_checked else "transparent",
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "color": _INDIGO, "fontSize": "10px", "fontWeight": "800",
                "cursor": "pointer", "margin": "auto",
            },
        ),
        style={**_TH_B, "width": "28px", "position": "sticky", "left": "0px",
               "zIndex": "3", "background": _BG_HEAD, "textAlign": "center"},
    )

    # (label, sort_col_key, extra_th_styles)
    fixed_cols = [
        ("ID",               "work_item_id",   {"width": "58px",    "position": "sticky", "left": "28px",
                                                 "zIndex": "3", "background": _BG_HEAD, "textAlign": "center"}),
        ("Name of Story",    "title",          {"minWidth": "200px", "position": "sticky", "left": "86px",
                                                 "zIndex": "3", "background": _BG_HEAD}),
        ("User Story Owner", "story_owner",    {"minWidth": "85px"}),
        ("Developer",        "main_developer", {"minWidth": "85px"}),
        ("QA",               "qa_person",      {"minWidth": "85px"}),
        ("Story Size",       "story_size",     {"minWidth": "78px"}),
        ("Story Status",     "story_status",   {"minWidth": "95px"}),
        ("Release Date",     "release_date",   {"minWidth": "115px",
                                                 "background": "rgba(239,110,99,0.2)", "color": _SALMON}),
    ]
    head_cells = [chk_th] + [
        html.Th(_sort_th(lbl, ck, sort_col, sort_dir), style={**_TH_B, **ex})
        for lbl, ck, ex in fixed_cols
    ]
    for sk, lbl in _STAGES:
        head_cells.append(html.Th(
            _sort_th(lbl, f"stage_{sk}", sort_col, sort_dir),
            style={**_TH_B, "minWidth": "96px"},
        ))
    head_cells.append(html.Th("Comment", style={**_TH_B, "minWidth": "150px"}))

    body_rows = []
    for s in stories:
        wid      = s["work_item_id"]
        s_stages = stage_data.get(wid, {})
        s_row    = row_data.get(wid, {})
        comment  = s_row.get("comment", "")
        qa_val   = s_row.get("qa", "")
        sz       = s["story_size"].strip().title() if s["story_size"] else ""
        sz_color = _SIZE_COLORS.get(sz, _MT)
        sc       = _GREEN if s["story_status"] == "Complete" else _MT

        is_selected = (wid == selected_id)
        row_bg = "rgba(110,118,241,0.09)" if is_selected else "transparent"
        row_shadow = "inset 3px 0 0 rgb(110,118,241)" if is_selected else "none"
        row_style = {"background": row_bg, "boxShadow": row_shadow}

        is_checked = wid in sel_set
        chk_td = html.Td(
            html.Div(
                "✓" if is_checked else "",
                id={"type": "rs-row-check", "key": str(wid)},
                n_clicks=0,
                style={
                    "width": "16px", "height": "16px", "borderRadius": "4px",
                    "border": f"2px solid {_INDIGO if is_checked else _DIM}",
                    "background": f"rgba({_rgb(_INDIGO)},0.25)" if is_checked else "transparent",
                    "display": "flex", "alignItems": "center", "justifyContent": "center",
                    "color": _INDIGO, "fontSize": "10px", "fontWeight": "800",
                    "cursor": "pointer", "margin": "auto",
                },
            ),
            style={**_TD_B, "position": "sticky", "left": "0px", "zIndex": "2",
                   "background": _BG_CARD, "width": "28px", "textAlign": "center"},
        )

        body_rows.append(html.Tr([
            chk_td,
            # ID column — sticky, ADO link
            html.Td(
                html.A(f"#{wid}",
                       href=f"{_ADO_BASE}/{wid}",
                       target="_blank",
                       style={"fontFamily": _MONO, "fontSize": "10px",
                              "color": _INDIGO, "fontWeight": "700",
                              "textDecoration": "none"},
                       **{"className": "ado-vsts-link"}),
                style={**_TD_B, "position": "sticky", "left": "28px", "zIndex": "2",
                       "background": _BG_CARD, "textAlign": "center",
                       "width": "58px", "whiteSpace": "nowrap"},
            ),
            # Name of Story — sticky, offset by checkbox + ID width; click → open panel
            html.Td(
                s["title"],
                id={"type": "rs-row", "key": str(wid), "stage": ""},
                n_clicks=0,
                style={**_TD_B, "position": "sticky", "left": "86px",
                       "zIndex": "2", "background": _BG_CARD,
                       "fontWeight": "600", "whiteSpace": "normal", "maxWidth": "200px",
                       "cursor": "pointer"},
            ),
            html.Td(
                html.Div(s["story_owner"] or "—",
                         style={"overflow": "hidden", "textOverflow": "ellipsis",
                                "whiteSpace": "nowrap"}),
                style={**_TD_B, "color": _FG, "fontSize": "12px", "maxWidth": "85px"}),
            html.Td(
                s["main_developer"].split()[0] if s["main_developer"] else "—",
                style={**_TD_B, "color": _FG, "fontSize": "12px",
                       "whiteSpace": "nowrap", "maxWidth": "85px"}),
            html.Td(
                qa_val.split()[0] if qa_val else "—",
                style={**_TD_B, "color": _FG, "fontSize": "12px",
                       "whiteSpace": "nowrap", "maxWidth": "85px"}),
            html.Td(sz or "—",
                    style={**_TD_B, "color": sz_color if sz else _MT,
                           "fontSize": "12px", "whiteSpace": "nowrap",
                           "maxWidth": "78px"}),
            html.Td(
                html.Span(s["story_status"] or "—",
                          style={"fontSize": "11px", "fontWeight": "700", "color": sc}),
                style={**_TD_B, "textAlign": "center"}),
            html.Td(
                html.Div(s["release_date"] or "—",
                         style={"overflow": "hidden", "textOverflow": "ellipsis",
                                "whiteSpace": "nowrap"}),
                style={**_TD_B, "color": _FG, "fontFamily": _MONO,
                       "fontSize": "12px", "maxWidth": "115px"}),
            *[_stage_cell(s_stages.get(k, {}).get("status", ""),
                          s_stages.get(k, {}).get("date",   ""),
                          wid=wid, stage_key=k)
              for k, _ in _STAGES],
            html.Td(
                html.Span(comment[:40] + ("…" if len(comment) > 40 else ""),
                          style={"fontSize": "11px", "color": _DIM}) if comment
                else html.Span("—", style={"fontSize": "11px", "color": _DIM}),
                style={**_TD_B, "minWidth": "140px"},
            ),
        ],
            style=row_style,
        ))

    return html.Div(
        html.Table(
            [html.Thead(html.Tr(head_cells),
                        style={"position": "sticky", "top": "0", "zIndex": "2"}),
             html.Tbody(body_rows)],
            style={"borderCollapse": "collapse", "width": "100%", "minWidth": "2200px"},
        ),
        style={
            "border": f"1px solid {_BD}", "borderRadius": "12px",
            "overflow": "auto", "maxHeight": "calc(100vh - 310px)",
        },
    )


# ── Side panel ────────────────────────────────────────────────────────────────
def _build_panel(wid: int):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT work_item_id, title,
                   COALESCE(story_owner,   '') AS story_owner,
                   COALESCE(main_developer,'') AS main_developer,
                   COALESCE(story_size,    '') AS story_size,
                   COALESCE(story_status,  '') AS story_status,
                   COALESCE(release_date,  '') AS release_date,
                   COALESCE(priority,      '') AS priority
            FROM work_items_main WHERE work_item_id = :id
        """), {"id": wid}).fetchone()
        stage_rows = conn.execute(text("""
            SELECT stage_key, status, stage_date FROM p_release_stages
            WHERE work_item_id = :id
        """), {"id": wid}).fetchall()
        rrow = conn.execute(text("""
            SELECT qa_person, comment FROM p_release_rows WHERE work_item_id = :id
        """), {"id": wid}).fetchone()

    if not row:
        return html.Div("Story not found.", style={"padding": "20px", "color": _MT})

    stages_db = {
        r.stage_key: {"status": r.status or "",
                      "date":   str(r.stage_date)[:10] if r.stage_date else ""}
        for r in stage_rows
    }
    qa_val  = (rrow.qa_person if rrow else "") or ""
    comment = (rrow.comment   if rrow else "") or ""
    cur_sz  = (row.story_size or "").strip().title()
    cur_dev = row.main_developer or ""
    cur_own = row.story_owner    or ""
    cur_sts = row.story_status   or ""

    _inp_style = {
        "width": "100%", "padding": "8px 10px",
        "background": _BG_HEAD, "border": f"1px solid {_BD}",
        "borderRadius": "7px", "color": _FG,
        "fontSize": "12.5px", "boxSizing": "border-box",
    }

    def _stage_row(key, label):
        sd     = stages_db.get(key, {})
        cur_st = sd.get("status", "")
        cur_dt = sd.get("date",   "")

        _NA_COLOR = "rgb(148,163,184)"

        def _sbtn(val, color):
            active = cur_st == val
            r = _rgb(color)
            icon = "—" if val == "n_a" else "✓"
            return html.Button(icon if active else "",
                               id={"type": "rs-stage-btn", "stage": key, "val": val},
                               n_clicks=0, style={
                "width": "22px", "height": "22px", "borderRadius": "50%",
                "cursor": "pointer", "padding": "0",
                "background": color if active else "transparent",
                "border": f"2px solid {color}" if active else f"2px solid rgba({r},0.4)",
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "color": _BG_PAGE, "fontSize": "11px", "fontWeight": "800",
                "lineHeight": "1",
            })

        date_opacity = "0.35" if cur_st == "n_a" else "1"
        return html.Div([
            html.Span(label, style={"flex": "1", "fontSize": "12px",
                                    "color": _FG, "lineHeight": "1.3"}),
            html.Div([
                _sbtn("done",        _GREEN),
                _sbtn("wip",         _AMBER),
                _sbtn("not_started", _RED),
                _sbtn("n_a",         _NA_COLOR),
            ], style={"display": "flex", "gap": "5px"}),
            dcc.Input(type="text", value=cur_dt, debounce=True,
                      placeholder="YYYY-MM-DD",
                      id={"type": "rs-stage-date", "stage": key},
                      style={
                          "width": "122px", "padding": "5px 6px",
                          "background": _BG_HEAD, "border": f"1px solid {_BD}",
                          "color": _FG, "borderRadius": "6px",
                          "fontSize": "11px", "fontFamily": _MONO,
                          "opacity": date_opacity,
                      }),
        ], style={
            "display": "flex", "alignItems": "center", "gap": "7px",
            "padding": "6px 8px", "borderRadius": "7px",
            "border": f"1px solid {_BD_CELL}",
            "marginBottom": "4px",
        })

    _divider = html.Div(style={
        "borderTop": f"1px solid {_BD_CELL}", "margin": "13px 0 10px",
    })

    return html.Div([
        # ── Header ──────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("Edit release row", style={
                    "fontSize": "9.5px", "fontWeight": "700", "color": _INDIGO,
                    "textTransform": "uppercase", "letterSpacing": "0.6px",
                }),
                html.Div(row.title or "", style={
                    "fontSize": "14px", "fontWeight": "700", "color": _FG,
                    "marginTop": "4px", "lineHeight": "1.4",
                }),
                html.Div(f"#{wid} · {cur_dev or '—'}", style={
                    "fontSize": "11px", "color": _MT, "marginTop": "3px",
                    "fontFamily": _MONO,
                }),
                html.Div([
                    *([html.Span(row.priority, style={
                        "background": {
                            "P1": "rgba(239,68,68,0.15)", "P2": "rgba(251,191,36,0.12)",
                            "P3": "rgba(52,211,153,0.10)",
                        }.get(row.priority, "rgba(148,163,184,0.08)"),
                        "color": {
                            "P1": "rgb(239,68,68)", "P2": "rgb(251,191,36)",
                            "P3": "rgb(52,211,153)",
                        }.get(row.priority, "rgb(148,163,184)"),
                        "border": "1px solid " + {
                            "P1": "rgba(239,68,68,0.35)", "P2": "rgba(251,191,36,0.30)",
                            "P3": "rgba(52,211,153,0.25)",
                        }.get(row.priority, "rgba(148,163,184,0.20)"),
                        "borderRadius": "4px", "padding": "1px 6px",
                        "fontSize": "10px", "fontWeight": "600", "whiteSpace": "nowrap",
                    })] if row.priority else []),
                    *([html.Span(row.release_date, style={
                        "background": "rgba(6,182,212,0.10)",
                        "color": "rgb(6,182,212)",
                        "border": "1px solid rgba(6,182,212,0.25)",
                        "borderRadius": "4px", "padding": "1px 6px",
                        "fontSize": "10px", "fontWeight": "600", "whiteSpace": "nowrap",
                    })] if row.release_date else []),
                ], style={
                    "display": "flex", "flexWrap": "wrap", "gap": "4px", "marginTop": "7px",
                }),
            ], style={"flex": "1"}),
            html.Button("✕", id="rs-panel-close", n_clicks=0, style={
                "background": "none", "border": "none", "color": _DIM,
                "fontSize": "20px", "cursor": "pointer", "padding": "0 0 0 12px",
                "lineHeight": "1",
            }),
        ], style={
            "display": "flex", "alignItems": "flex-start",
            "padding": "18px 20px 14px", "borderBottom": f"1px solid {_BD}",
        }),

        # ── Fields ──────────────────────────────────────────────────────────
        html.Div([

            # Story Owner + Developer — dropdowns
            html.Div([
                html.Div([
                    _lbl("Story Owner"),
                    dcc.Dropdown(
                        id="rs-owner-dd",
                        options=[{"label": o, "value": o} for o in _STORY_OWNERS],
                        value=cur_own or None,
                        placeholder="Select owner…",
                        clearable=True,
                        style={"fontSize": "12.5px"},
                    ),
                ], style={"flex": "1", "minWidth": "0"}),
                html.Div([
                    _lbl("Developer"),
                    dcc.Dropdown(
                        id="rs-dev-dd",
                        options=[{"label": d, "value": d} for d in sorted(DEV_NAMES)],
                        value=cur_dev or None,
                        placeholder="Select developer…",
                        clearable=True,
                        style={"fontSize": "12.5px"},
                    ),
                ], style={"flex": "1", "minWidth": "0"}),
            ], style={"display": "flex", "gap": "10px", "marginBottom": "14px"}),

            # QA
            html.Div([
                _lbl("QA"),
                html.Div([
                    html.Div([
                        _tog(q, {"type": "rs-qa-btn", "key": q},
                             active=(q == qa_val), color=_CYAN)
                        for q in _QA_NAMES
                    ], style={"display": "flex", "flexWrap": "wrap",
                              "gap": "6px", "flex": "1"}),
                    html.Button("View all QA load", n_clicks=0, style={
                        "padding": "6px 10px", "borderRadius": "7px",
                        "background": "transparent", "border": f"1px solid {_RED}",
                        "color": _RED, "cursor": "pointer", "fontSize": "11px",
                        "fontWeight": "600", "whiteSpace": "nowrap", "flexShrink": "0",
                    }),
                ], style={"display": "flex", "gap": "8px",
                          "alignItems": "flex-start", "flexWrap": "wrap"}),
            ], style={"marginBottom": "14px"}),

            # Story Size
            html.Div([
                _lbl("Story Size"),
                html.Div([
                    _tog(sz, {"type": "rs-size-btn", "key": sz},
                         active=(sz == cur_sz),
                         color=_SIZE_COLORS.get(sz, _INDIGO))
                    for sz in _SIZES
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),
            ], style={"marginBottom": "14px"}),

            # Story Status + Release Date — side by side
            html.Div([
                html.Div([
                    _lbl("Story Status"),
                    _story_status_badge(wid),
                ], style={"flex": "1", "minWidth": "0"}),
                html.Div([
                    _lbl("Release date"),
                    dcc.Dropdown(
                        id="rs-release-date-dd",
                        options=[{"label": r, "value": r} for r in _get_releases()],
                        value=row.release_date or None,
                        placeholder="Select release…",
                        clearable=True,
                        style={"fontSize": "12.5px"},
                    ),
                ], style={"flex": "1", "minWidth": "0"}),
            ], style={"display": "flex", "gap": "10px", "marginBottom": "12px"}),

            # Save to ADO button
            html.Button("Save to ADO", id="rs-save-btn", n_clicks=0, style={
                "width": "100%", "padding": "9px", "borderRadius": "8px",
                "background": "rgba(110,118,241,0.133)",
                "border": f"1px solid rgba(110,118,241,0.5)",
                "color": _INDIGO, "cursor": "pointer",
                "fontSize": "12px", "fontWeight": "700",
                "marginBottom": "4px",
            }),

            _divider,

            # Stages header + legend
            html.Div([
                html.Span("Stages · set status & date", style={
                    "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                }),
                html.Div([
                    html.Span([
                        html.Span(style={
                            "width": "10px", "height": "10px", "borderRadius": "50%",
                            "border": f"2px solid {c}", "display": "inline-block",
                            "marginRight": "4px",
                        }),
                        html.Span(lbl, style={"fontSize": "10px", "color": _DIM}),
                    ], style={"display": "inline-flex", "alignItems": "center",
                              "marginLeft": "10px"})
                    for lbl, c in [("Done", _GREEN), ("WIP", _AMBER),
                                   ("Not started", _RED)]
                ], style={"display": "flex"}),
            ], style={
                "display": "flex", "justifyContent": "space-between",
                "alignItems": "center", "marginBottom": "9px",
            }),

            # Stage rows
            html.Div([_stage_row(k, lbl) for k, lbl in _STAGES]),

            _divider,

            # Comment
            html.Div([
                _lbl("Comment"),
                dcc.Textarea(id="rs-comment-input", value=comment,
                             placeholder="Add a note…", style={
                    "width": "100%", "minHeight": "68px",
                    "background": _BG_HEAD, "border": f"1px solid {_BD}",
                    "color": _FG, "borderRadius": "8px", "padding": "10px",
                    "fontSize": "12px", "resize": "vertical",
                    "boxSizing": "border-box",
                }),
                html.Button("Save comment", id="rs-comment-save", n_clicks=0, style={
                    "marginTop": "7px", "padding": "5px 13px", "borderRadius": "7px",
                    "background": "transparent", "border": f"1px solid {_BD}",
                    "color": _DIM, "cursor": "pointer", "fontSize": "11px",
                }),
            ], style={"marginBottom": "14px"}),

            # Delete story row
            html.Button("Delete story row", id="rs-delete-btn", n_clicks=0, style={
                "width": "100%", "padding": "9px", "borderRadius": "8px",
                "background": "transparent", "border": f"1px solid {_RED}",
                "color": _RED, "cursor": "pointer", "fontSize": "12px",
                "fontWeight": "600",
            }),

        ], style={"padding": "18px 20px 28px"}),
    ])


# ── Bulk edit panel ───────────────────────────────────────────────────────────
def _build_bulk_panel(selected_ids: list, pending: dict):
    n = len(selected_ids)
    _NA_COLOR = "rgb(148,163,184)"
    _divider = html.Div(style={"borderTop": f"1px solid {_BD_CELL}", "margin": "13px 0 10px"})

    def _bulk_sbtn(stage_key, val, color):
        active = pending.get(f"s_{stage_key}") == val
        r = _rgb(color)
        icon = "—" if val == "n_a" else "✓"
        return html.Button(icon if active else "",
                           id={"type": "rs-bulk-stage-btn", "stage": stage_key, "val": val},
                           n_clicks=0, style={
            "width": "22px", "height": "22px", "borderRadius": "50%",
            "cursor": "pointer", "padding": "0",
            "background": color if active else "transparent",
            "border": f"2px solid {color}" if active else f"2px solid rgba({r},0.4)",
            "display": "flex", "alignItems": "center", "justifyContent": "center",
            "color": _BG_PAGE, "fontSize": "11px", "fontWeight": "800",
            "lineHeight": "1",
        })

    def _bulk_stage_row(key, label):
        d_opacity = "0.35" if pending.get(f"s_{key}") == "n_a" else "1"
        return html.Div([
            html.Span(label, style={"flex": "1", "fontSize": "12px",
                                    "color": _FG, "lineHeight": "1.3"}),
            html.Div([
                _bulk_sbtn(key, "done",        _GREEN),
                _bulk_sbtn(key, "wip",         _AMBER),
                _bulk_sbtn(key, "not_started", _RED),
                _bulk_sbtn(key, "n_a",         _NA_COLOR),
            ], style={"display": "flex", "gap": "5px"}),
            dcc.Input(type="text", value=pending.get(f"d_{key}", ""), debounce=True,
                      placeholder="YYYY-MM-DD",
                      id={"type": "rs-bulk-stage-date", "stage": key},
                      style={
                          "width": "122px", "padding": "5px 6px",
                          "background": _BG_HEAD, "border": f"1px solid {_BD}",
                          "color": _FG, "borderRadius": "6px",
                          "fontSize": "11px", "fontFamily": _MONO,
                          "opacity": d_opacity,
                      }),
        ], style={
            "display": "flex", "alignItems": "center", "gap": "7px",
            "padding": "6px 8px", "borderRadius": "7px",
            "border": f"1px solid {_BD_CELL}",
            "marginBottom": "4px",
        })

    cur_qa = pending.get("qa_person")
    cur_sz = pending.get("story_size")

    return html.Div([
        # Header
        html.Div([
            html.Div([
                html.Div("Bulk Edit", style={
                    "fontSize": "9.5px", "fontWeight": "700", "color": _AMBER,
                    "textTransform": "uppercase", "letterSpacing": "0.6px",
                }),
                html.Div(f"{n} {'story' if n == 1 else 'stories'} selected", style={
                    "fontSize": "14px", "fontWeight": "700", "color": _FG,
                    "marginTop": "4px",
                }),
                html.Div("Only filled fields are applied — blanks are skipped.",
                         style={"fontSize": "11px", "color": _MT, "marginTop": "3px"}),
            ], style={"flex": "1"}),
            html.Div([
                html.Button("Clear selection", id="rs-bulk-clear", n_clicks=0, style={
                    "background": "transparent", "border": f"1px solid {_BD}",
                    "color": _MT, "fontSize": "11px", "cursor": "pointer",
                    "padding": "4px 10px", "borderRadius": "6px", "marginRight": "8px",
                }),
                html.Button("✕", id="rs-bulk-close", n_clicks=0, style={
                    "background": "none", "border": "none", "color": _DIM,
                    "fontSize": "20px", "cursor": "pointer", "padding": "0",
                    "lineHeight": "1",
                }),
            ], style={"display": "flex", "alignItems": "center"}),
        ], style={
            "display": "flex", "alignItems": "flex-start",
            "padding": "18px 20px 14px", "borderBottom": f"1px solid {_BD}",
        }),

        # Body
        html.Div([
            # QA
            html.Div([
                _lbl("QA Person"),
                html.Div([
                    _tog(q, {"type": "rs-bulk-qa-btn", "key": q},
                         active=(q == cur_qa), color=_CYAN)
                    for q in _QA_NAMES
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),
            ], style={"marginBottom": "14px"}),

            # Story Size
            html.Div([
                _lbl("Story Size"),
                html.Div([
                    _tog(sz, {"type": "rs-bulk-size-btn", "key": sz},
                         active=(sz == cur_sz),
                         color=_SIZE_COLORS.get(sz, _INDIGO))
                    for sz in _SIZES
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),
            ], style={"marginBottom": "14px"}),

            # Release Date
            html.Div([
                _lbl("Release Date"),
                dcc.Dropdown(
                    id="rs-bulk-release-dd",
                    options=[{"label": r, "value": r} for r in _get_releases()],
                    value=pending.get("release_date"),
                    placeholder="Select release…",
                    clearable=True,
                    style={"fontSize": "12.5px"},
                ),
            ], style={"marginBottom": "14px"}),

            # Apply button
            html.Button(f"Apply to {n} {'story' if n == 1 else 'stories'}",
                        id="rs-bulk-apply", n_clicks=0, style={
                "width": "100%", "padding": "9px", "borderRadius": "8px",
                "background": f"rgba({_rgb(_AMBER)},0.133)",
                "border": f"1px solid rgba({_rgb(_AMBER)},0.5)",
                "color": _AMBER, "cursor": "pointer",
                "fontSize": "12px", "fontWeight": "700",
                "marginBottom": "4px",
            }),

            _divider,

            # Stages legend
            html.Div([
                html.Span("Stages · set status & date", style={
                    "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                    "textTransform": "uppercase", "letterSpacing": "0.5px",
                }),
                html.Div([
                    html.Span([
                        html.Span(style={
                            "width": "10px", "height": "10px", "borderRadius": "50%",
                            "border": f"2px solid {c}", "display": "inline-block",
                            "marginRight": "4px",
                        }),
                        html.Span(lbl, style={"fontSize": "10px", "color": _DIM}),
                    ], style={"display": "inline-flex", "alignItems": "center",
                              "marginLeft": "10px"})
                    for lbl, c in [("Done", _GREEN), ("WIP", _AMBER),
                                   ("Not started", _RED), ("N/A", _NA_COLOR)]
                ], style={"display": "flex", "flexWrap": "wrap"}),
            ], style={
                "display": "flex", "justifyContent": "space-between",
                "alignItems": "center", "marginBottom": "9px", "flexWrap": "wrap", "gap": "6px",
            }),

            # Stage rows
            html.Div([_bulk_stage_row(k, lbl) for k, lbl in _STAGES]),

            _divider,

            # Comment
            html.Div([
                _lbl("Comment"),
                dcc.Textarea(id="rs-bulk-comment-inp",
                             value=pending.get("comment", ""),
                             placeholder="Add a note to all selected stories…", style={
                    "width": "100%", "minHeight": "60px",
                    "background": _BG_HEAD, "border": f"1px solid {_BD}",
                    "color": _FG, "borderRadius": "8px", "padding": "10px",
                    "fontSize": "12px", "resize": "vertical",
                    "boxSizing": "border-box",
                }),
            ], style={"marginBottom": "14px"}),

            # Selected IDs summary
            html.Div([
                _lbl("Selected"),
                html.Div(
                    ", ".join(f"#{i}" for i in selected_ids[:20]) +
                    (f" … +{len(selected_ids) - 20} more" if len(selected_ids) > 20 else ""),
                    style={"fontSize": "11px", "color": _MT, "fontFamily": _MONO,
                           "lineHeight": "1.6"},
                ),
            ]),
        ], style={"padding": "18px 20px 28px"}),
    ])


# ── Layout ────────────────────────────────────────────────────────────────────
def layout(**_):
    releases = _get_releases()
    default  = releases[0] if releases else None

    return html.Div([
        dcc.Store(id="rs-release-store", data=default),
        dcc.Store(id="rs-panel-store"),
        dcc.Store(id="rs-panel-visible", data=False),
        dcc.Store(id="rs-initial", data={}),
        dcc.Store(id="rs-selected-ids", data=[]),
        dcc.Store(id="rs-bulk-pending",  data={}),
        dcc.Store(id="rs-sort-store",   data={"col": None, "dir": None}),

        # Header
        html.Div([
            html.Div([
                html.Span("EOD · PLANNING", style={
                    "fontSize": "10px", "fontWeight": "700", "color": _INDIGO,
                    "textTransform": "uppercase", "letterSpacing": "1px",
                }),
                html.H1("Release Status", style={
                    "fontSize": "21px", "fontWeight": "700", "color": _FG,
                    "margin": "4px 0 0 0",
                }),
                html.Div(
                    "Release readiness across each environment and sign-off stage. "
                    "Click a row to set stage status and date.",
                    style={"fontSize": "12px", "color": _MT, "marginTop": "5px"},
                ),
                html.Div(
                    "ℹ Release date = ADO release date field on the work item (not iteration month).",
                    style={"fontSize": "10px", "color": _MT, "marginTop": "2px",
                           "fontStyle": "italic"},
                ),
            ]),
            html.Div(f"Planning as of {date.today().strftime('%b %Y')}",
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

        # Release picker
        html.Div([
            html.Span("Release", style={
                "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                "textTransform": "uppercase", "letterSpacing": "0.5px",
                "marginRight": "12px", "flexShrink": "0",
            }),
            html.Div(_build_pills(releases, default),
                     id="rs-release-picker",
                     style={"display": "flex", "flexWrap": "wrap", "gap": "8px"}),
        ], style={
            "display": "flex", "alignItems": "center",
            "padding": "12px 24px", "borderBottom": f"1px solid {_BD}",
            "background": _BG_CARD,
        }),

        # Legend + search
        html.Div([
            *[html.Span([
                html.Span(style={
                    "width": "8px", "height": "8px", "borderRadius": "2px",
                    "background": col, "display": "inline-block",
                    "marginRight": "5px", "opacity": "0.85",
                }),
                html.Span(lbl, style={"fontSize": "11px", "color": _MT,
                                      "marginRight": "14px"}),
            ]) for lbl, col in [("Done", _GREEN), ("WIP", _AMBER), ("Not started", _RED)]],
            html.Span("· each stage cell also carries a delivery date",
                      style={"fontSize": "10.5px", "color": _DIM, "flex": "1"}),
            dcc.Input(
                id="rs-search",
                type="text",
                placeholder="Search by ID or title…",
                debounce=True,
                style={
                    "background": _BG_CARD, "border": f"1px solid {_BD}",
                    "borderRadius": "7px", "color": _FG,
                    "fontSize": "12px", "padding": "5px 11px",
                    "outline": "none", "width": "220px",
                },
            ),
        ], style={"display": "flex", "alignItems": "center",
                  "padding": "10px 24px", "flexWrap": "wrap", "gap": "8px"}),

        # KPI strip
        html.Div(id="rs-kpi-strip"),

        # Table
        html.Div(id="rs-table-wrapper",
                 style={"padding": "0 24px 24px", "overflow": "auto"}),

        # Panel overlay
        html.Div([
            html.Div(id="rs-panel-content"),
        ], id="rs-panel-wrapper", style={
            "position": "fixed", "top": "0", "right": "0",
            "height": "100vh", "width": "760px",
            "background": _BG_CARD, "borderLeft": f"1px solid {_BD}",
            "overflowY": "auto", "zIndex": "41", "display": "none",
            "boxShadow": "rgba(0,0,0,0.467) -8px 0px 24px",
        }),

    ], style={
        "display": "flex", "flexDirection": "column",
        "minHeight": "100vh", "background": _BG_PAGE,
    })


# ── Callbacks ─────────────────────────────────────────────────────────────────
@callback(
    Output("rs-panel-wrapper", "style"),
    Input("rs-panel-visible",  "data"),
    Input("rs-selected-ids",   "data"),
)
def _panel_visibility(visible, selected_ids):
    show = bool(visible) or bool(selected_ids)
    base = {
        "position": "fixed", "top": "0", "right": "0",
        "height": "100vh", "width": "760px",
        "background": _BG_CARD, "borderLeft": f"1px solid {_BD}",
        "overflowY": "auto", "zIndex": "41",
        "boxShadow": "rgba(0,0,0,0.467) -8px 0px 24px",
    }
    return {**base, "display": "block" if show else "none"}


@callback(
    Output("rs-release-store",  "data"),
    Output("rs-release-picker", "children"),
    Input({"type": "rs-release-pill", "rel": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_release(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    selected = tid["rel"]
    return selected, _build_pills(_get_releases(), selected)


@callback(
    Output("rs-table-wrapper", "children"),
    Input("rs-release-store",  "data"),
    Input("rs-panel-store",    "data"),
    Input("rs-panel-visible",  "data"),
    Input("rs-search",         "value"),
    Input("rs-selected-ids",   "data"),
    Input("rs-sort-store",     "data"),
)
def _render_table(release, selected_id, panel_visible, search, selected_ids, sort_state):
    if not release:
        return html.Div("Select a release above to view stories.",
                        style={"padding": "40px", "color": _MT, "textAlign": "center"})
    stories    = _load_stories(release)
    ids        = [s["work_item_id"] for s in stories]
    stage_data = _load_stage_data(ids)
    row_data   = _load_row_data(ids)
    if not stories:
        return html.Div(f"No active stories found for: {release}",
                        style={"padding": "40px", "color": _MT, "textAlign": "center"})
    q = (search or "").strip().lower()
    if q:
        stories = [s for s in stories
                   if q in str(s["work_item_id"]) or q in s["title"].lower()]
    if not stories and q:
        return html.Div(f"No stories match \"{search}\".",
                        style={"padding": "40px", "color": _MT, "textAlign": "center"})
    sort_col = (sort_state or {}).get("col")
    sort_dir = (sort_state or {}).get("dir")
    stories  = _sort_stories(stories, stage_data, row_data, sort_col, sort_dir)
    effective_id = selected_id if panel_visible else None
    return _build_table(stories, stage_data, row_data,
                        selected_id=effective_id, selected_ids=selected_ids,
                        sort_col=sort_col, sort_dir=sort_dir)


@callback(
    Output("rs-sort-store", "data"),
    Input({"type": "rs-sort-th", "col": ALL}, "n_clicks"),
    State("rs-sort-store", "data"),
    prevent_initial_call=True,
)
def _update_sort(all_clicks, current):
    if not any(all_clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    col     = tid["col"]
    current = current or {}
    cur_col = current.get("col")
    cur_dir = current.get("dir")
    if cur_col == col:
        new_dir = "desc" if cur_dir == "asc" else (None if cur_dir == "desc" else "asc")
    else:
        new_dir = "asc"
    return {"col": col if new_dir else None, "dir": new_dir}


@callback(
    Output("rs-kpi-strip", "children"),
    Input("rs-release-store", "data"),
)
def _render_kpi_strip(release):
    if not release:
        return []
    stories    = _load_stories(release)
    ids        = [s["work_item_id"] for s in stories]
    stage_data = _load_stage_data(ids)
    return _build_kpi_strip(stories, stage_data)


@callback(
    Output("rs-panel-store",   "data"),
    Output("rs-panel-visible", "data"),
    Output("rs-initial",       "data"),
    Input({"type": "rs-row", "key": ALL, "stage": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _open_panel(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    wid = int(tid["key"])
    with engine.connect() as conn:
        snap = conn.execute(text("""
            SELECT COALESCE(story_owner,   '') AS story_owner,
                   COALESCE(main_developer,'') AS main_developer,
                   COALESCE(release_date,  '') AS release_date
            FROM work_items_main WHERE work_item_id = :id
        """), {"id": wid}).fetchone()
    initial = {}
    if snap:
        initial = {
            "story_owner":    snap.story_owner,
            "main_developer": snap.main_developer,
            "release_date":   snap.release_date,
        }
    return wid, True, initial


@callback(
    Output("rs-panel-visible", "data", allow_duplicate=True),
    Input("rs-panel-close", "n_clicks"),
    prevent_initial_call=True,
)
def _close_panel(n):
    if not n:
        raise PreventUpdate
    return False


@callback(
    Output("rs-panel-content", "children"),
    Input("rs-panel-store",    "data"),
    Input("rs-selected-ids",   "data"),
    Input("rs-bulk-pending",   "data"),
    prevent_initial_call=True,
)
def _render_panel(story_id, selected_ids, bulk_pending):
    if selected_ids:
        return _build_bulk_panel(selected_ids, bulk_pending or {})
    if story_id is None:
        raise PreventUpdate
    return _build_panel(story_id)


@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input("rs-owner-dd", "value"),
    State("rs-panel-store", "data"),
    State("rs-initial",     "data"),
    prevent_initial_call=True,
)
def _save_owner(val, story_id, initial):
    if not story_id or not val:
        raise PreventUpdate
    if val == (initial or {}).get("story_owner"):
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("UPDATE work_items_main SET story_owner=:o WHERE work_item_id=:id"),
                     {"o": val, "id": story_id})
    return story_id


@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input("rs-dev-dd", "value"),
    State("rs-panel-store", "data"),
    State("rs-initial",     "data"),
    prevent_initial_call=True,
)
def _save_developer(val, story_id, initial):
    if not story_id or not val:
        raise PreventUpdate
    if val == (initial or {}).get("main_developer"):
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("UPDATE work_items_main SET main_developer=:d WHERE work_item_id=:id"),
                     {"d": val, "id": story_id})
    return story_id


@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input({"type": "rs-qa-btn", "key": ALL}, "n_clicks"),
    State("rs-panel-store", "data"),
    prevent_initial_call=True,
)
def _save_qa(clicks, story_id):
    if not story_id or not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_release_rows (work_item_id, qa_person, updated_at)
            VALUES (:id, :qa, NOW())
            ON CONFLICT (work_item_id) DO UPDATE
            SET qa_person = EXCLUDED.qa_person, updated_at = NOW()
        """), {"id": story_id, "qa": tid["key"]})
    return story_id


@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input({"type": "rs-size-btn", "key": ALL}, "n_clicks"),
    State("rs-panel-store", "data"),
    prevent_initial_call=True,
)
def _save_size(clicks, story_id):
    if not story_id or not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("UPDATE work_items_main SET story_size=:s WHERE work_item_id=:id"),
                     {"s": tid["key"], "id": story_id})
    return story_id



@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input({"type": "rs-stage-btn", "stage": ALL, "val": ALL}, "n_clicks"),
    State("rs-panel-store", "data"),
    prevent_initial_call=True,
)
def _save_stage_status(clicks, story_id):
    if not story_id or not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_release_stages (work_item_id, stage_key, status)
            VALUES (:id, :key, :status)
            ON CONFLICT (work_item_id, stage_key) DO UPDATE
            SET status = EXCLUDED.status
        """), {"id": story_id, "key": tid["stage"], "status": tid["val"]})
    return story_id


@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input({"type": "rs-stage-date", "stage": ALL}, "value"),
    State("rs-panel-store", "data"),
    prevent_initial_call=True,
)
def _save_stage_date(dates, story_id):
    if not story_id:
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    stage_key = tid["stage"]
    try:
        date_val = dates[_STAGE_KEYS.index(stage_key)]
    except (ValueError, IndexError):
        raise PreventUpdate
    if not date_val:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_release_stages (work_item_id, stage_key, stage_date, status)
            VALUES (:id, :key, :date, 'not_started')
            ON CONFLICT (work_item_id, stage_key) DO UPDATE
            SET stage_date = EXCLUDED.stage_date
        """), {"id": story_id, "key": stage_key, "date": date_val})
    return story_id


@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input("rs-comment-save",    "n_clicks"),
    State("rs-comment-input",   "value"),
    State("rs-panel-store",     "data"),
    prevent_initial_call=True,
)
def _save_comment(n, comment, story_id):
    if not n or not story_id:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO p_release_rows (work_item_id, comment, updated_at)
            VALUES (:id, :c, NOW())
            ON CONFLICT (work_item_id) DO UPDATE
            SET comment = EXCLUDED.comment, updated_at = NOW()
        """), {"id": story_id, "c": comment or ""})
    return story_id


@callback(
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input("rs-release-date-dd", "value"),
    State("rs-panel-store",     "data"),
    State("rs-initial",         "data"),
    prevent_initial_call=True,
)
def _save_release_date(val, story_id, initial):
    if not story_id or not val:
        raise PreventUpdate
    if val == (initial or {}).get("release_date"):
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("UPDATE work_items_main SET release_date=:d WHERE work_item_id=:id"),
                     {"d": val, "id": story_id})
    return story_id


@callback(
    Output("rs-panel-store", "data",      allow_duplicate=True),
    Output("notif-store",    "data",      allow_duplicate=True),
    Input("rs-save-btn",     "n_clicks"),
    State("rs-panel-store",  "data"),
    prevent_initial_call=True,
)
def _save_to_ado(n, story_id):
    import time as _t
    if not n or not story_id:
        raise PreventUpdate
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT story_owner, main_developer, story_size, release_date
            FROM work_items_main WHERE work_item_id = :id
        """), {"id": story_id}).fetchone()
    if not row:
        raise PreventUpdate
    fields = {}
    if row.story_owner:    fields["story_owner"]    = row.story_owner
    if row.main_developer: fields["main_developer"] = row.main_developer
    if row.story_size:     fields["story_size"]     = row.story_size
    if row.release_date:   fields["release_date"]   = row.release_date
    if fields:
        write_fields(story_id, fields)
    notif = {"msg": f"Saved #{story_id} to ADO", "type": "success", "ts": _t.time()}
    return story_id, notif


@callback(
    Output("rs-panel-visible", "data",      allow_duplicate=True),
    Output("notif-store",      "data",      allow_duplicate=True),
    Input("rs-delete-btn",     "n_clicks"),
    State("rs-panel-store",    "data"),
    prevent_initial_call=True,
)
def _delete_row(n, story_id):
    import time as _t
    if not n or not story_id:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM p_release_stages WHERE work_item_id = :id"),
                     {"id": story_id})
        conn.execute(text("DELETE FROM p_release_rows   WHERE work_item_id = :id"),
                     {"id": story_id})
    notif = {"msg": f"Entry #{story_id} deleted", "type": "info", "ts": _t.time()}
    return False, notif


# ── Bulk select callbacks ─────────────────────────────────────────────────────

@callback(
    Output("rs-selected-ids", "data", allow_duplicate=True),
    Input({"type": "rs-row-check", "key": ALL}, "n_clicks"),
    State("rs-selected-ids", "data"),
    prevent_initial_call=True,
)
def _toggle_row_check(clicks, selected_ids):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    wid = int(tid["key"])
    sel = list(selected_ids or [])
    if wid in sel:
        sel.remove(wid)
    else:
        sel.append(wid)
    return sel


@callback(
    Output("rs-selected-ids", "data", allow_duplicate=True),
    Input("rs-select-all-btn", "n_clicks"),
    State("rs-release-store",  "data"),
    State("rs-search",         "value"),
    State("rs-selected-ids",   "data"),
    prevent_initial_call=True,
)
def _select_all_rows(n, release, search, selected_ids):
    if not n or not release:
        raise PreventUpdate
    stories = _load_stories(release)
    q = (search or "").strip().lower()
    if q:
        stories = [s for s in stories
                   if q in str(s["work_item_id"]) or q in s["title"].lower()]
    all_ids = [s["work_item_id"] for s in stories]
    if set(all_ids) <= set(selected_ids or []):
        return []
    return all_ids


@callback(
    Output("rs-selected-ids",  "data", allow_duplicate=True),
    Output("rs-bulk-pending",  "data", allow_duplicate=True),
    Input("rs-bulk-clear",     "n_clicks"),
    Input("rs-bulk-close",     "n_clicks"),
    prevent_initial_call=True,
)
def _bulk_close(n_clear, n_close):
    if not n_clear and not n_close:
        raise PreventUpdate
    return [], {}


# ── Bulk pending-store callbacks ──────────────────────────────────────────────

@callback(
    Output("rs-bulk-pending", "data", allow_duplicate=True),
    Input({"type": "rs-bulk-stage-btn", "stage": ALL, "val": ALL}, "n_clicks"),
    State("rs-bulk-pending", "data"),
    prevent_initial_call=True,
)
def _bulk_stage_click(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    p[f"s_{tid['stage']}"] = tid["val"]
    return p


@callback(
    Output("rs-bulk-pending", "data", allow_duplicate=True),
    Input({"type": "rs-bulk-stage-date", "stage": ALL}, "value"),
    State("rs-bulk-pending", "data"),
    prevent_initial_call=True,
)
def _bulk_stage_date(dates, pending):
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    stage_key = tid["stage"]
    try:
        val = dates[_STAGE_KEYS.index(stage_key)]
    except (ValueError, IndexError):
        raise PreventUpdate
    if not val:
        raise PreventUpdate
    p = dict(pending or {})
    p[f"d_{stage_key}"] = val
    return p


@callback(
    Output("rs-bulk-pending", "data", allow_duplicate=True),
    Input({"type": "rs-bulk-qa-btn", "key": ALL}, "n_clicks"),
    State("rs-bulk-pending", "data"),
    prevent_initial_call=True,
)
def _bulk_qa_click(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    # toggle off if same clicked again
    if p.get("qa_person") == tid["key"]:
        p.pop("qa_person", None)
    else:
        p["qa_person"] = tid["key"]
    return p


@callback(
    Output("rs-bulk-pending", "data", allow_duplicate=True),
    Input({"type": "rs-bulk-size-btn", "key": ALL}, "n_clicks"),
    State("rs-bulk-pending", "data"),
    prevent_initial_call=True,
)
def _bulk_size_click(clicks, pending):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    p = dict(pending or {})
    if p.get("story_size") == tid["key"]:
        p.pop("story_size", None)
    else:
        p["story_size"] = tid["key"]
    return p


@callback(
    Output("rs-bulk-pending", "data", allow_duplicate=True),
    Input("rs-bulk-release-dd", "value"),
    State("rs-bulk-pending",    "data"),
    prevent_initial_call=True,
)
def _bulk_release_change(val, pending):
    p = dict(pending or {})
    if val:
        p["release_date"] = val
    else:
        p.pop("release_date", None)
    return p


# ── Bulk apply ────────────────────────────────────────────────────────────────

@callback(
    Output("rs-selected-ids",    "data",      allow_duplicate=True),
    Output("rs-bulk-pending",    "data",      allow_duplicate=True),
    Output("notif-store",        "data",      allow_duplicate=True),
    Input("rs-bulk-apply",       "n_clicks"),
    State("rs-selected-ids",     "data"),
    State("rs-bulk-pending",     "data"),
    State("rs-bulk-comment-inp", "value"),
    prevent_initial_call=True,
)
def _apply_bulk_changes(n, selected_ids, pending, comment_val):
    import time as _t, threading
    if not n or not selected_ids:
        raise PreventUpdate

    p = dict(pending or {})
    if comment_val:
        p["comment"] = comment_val

    qa_val  = p.get("qa_person")
    cmt_val = p.get("comment")
    sz_val  = p.get("story_size")
    rd_val  = p.get("release_date")

    with engine.begin() as conn:
        for wid in selected_ids:
            if sz_val:
                conn.execute(
                    text("UPDATE work_items_main SET story_size=:s WHERE work_item_id=:id"),
                    {"s": sz_val, "id": wid})
            if rd_val:
                conn.execute(
                    text("UPDATE work_items_main SET release_date=:d WHERE work_item_id=:id"),
                    {"d": rd_val, "id": wid})
            if qa_val or cmt_val:
                conn.execute(text("""
                    INSERT INTO p_release_rows (work_item_id, qa_person, comment, updated_at)
                    VALUES (:id, COALESCE(:qa,''), COALESCE(:c,''), NOW())
                    ON CONFLICT (work_item_id) DO UPDATE
                    SET qa_person  = CASE WHEN :qa IS NOT NULL THEN :qa
                                         ELSE p_release_rows.qa_person END,
                        comment    = CASE WHEN :c  IS NOT NULL THEN :c
                                         ELSE p_release_rows.comment END,
                        updated_at = NOW()
                """), {"id": wid, "qa": qa_val, "c": cmt_val})
            for stage_key in _STAGE_KEYS:
                status   = p.get(f"s_{stage_key}")
                date_val = p.get(f"d_{stage_key}")
                if status or date_val:
                    conn.execute(text("""
                        INSERT INTO p_release_stages (work_item_id, stage_key, status, stage_date)
                        VALUES (:id, :key, COALESCE(:status,'not_started'), :date)
                        ON CONFLICT (work_item_id, stage_key) DO UPDATE
                            SET status     = COALESCE(:status, p_release_stages.status),
                                stage_date = COALESCE(:date,   p_release_stages.stage_date)
                    """), {"id": wid, "key": stage_key, "status": status, "date": date_val})

    # Write ADO fields in background (best-effort, don't block UI)
    ado_fields = {}
    if sz_val: ado_fields["story_size"]  = sz_val
    if rd_val: ado_fields["release_date"] = rd_val
    if ado_fields:
        ids_snap = list(selected_ids)
        def _bg_ado(ids, fields):
            for wid in ids:
                try:
                    write_fields(wid, fields)
                except Exception:
                    pass
        threading.Thread(target=_bg_ado, args=(ids_snap, ado_fields), daemon=True).start()

    ns = len(selected_ids)
    notif = {"msg": f"Applied to {ns} {'story' if ns == 1 else 'stories'}",
             "type": "success", "ts": _t.time()}
    return [], {}, notif
