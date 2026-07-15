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
    "":            "rgb(38,44,58)",
}
_ST_LABEL = {"done": "Done", "wip": "WIP", "not_started": "Not started", "": "—"}

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


def _stage_cell(status, stage_date):
    if not status:
        return html.Td("", style={**_TD_B, "minWidth": "110px"})
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
              "boxShadow": f"rgba({r},0.333) 0px 0px 0px 1px inset"})


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

def _build_table(stories, stage_data, row_data, selected_id=None):
    fixed_cols = [
        ("Name of Story", {"minWidth": "200px", "position": "sticky", "left": "0px",
                           "zIndex": "3", "background": _BG_HEAD, "textAlign": "center"}),
        ("User Story Owner", {"minWidth": "85px"}),
        ("Developer",        {"minWidth": "85px"}),
        ("QA",               {"minWidth": "85px"}),
        ("Story Size",       {"minWidth": "78px"}),
        ("Story Status",     {"minWidth": "95px"}),
        ("Release Date",     {"minWidth": "115px",
                              "background": "rgba(239,110,99,0.2)", "color": _SALMON}),
    ]
    head_cells = [html.Th(c, style={**_TH_B, **ex}) for c, ex in fixed_cols]
    for _, lbl in _STAGES:
        head_cells.append(html.Th(lbl, style={**_TH_B, "minWidth": "96px"}))
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
        row_style = {
            "cursor": "pointer",
            "background": "rgba(110,118,241,0.09)" if is_selected else "transparent",
            "boxShadow": "inset 3px 0 0 rgb(110,118,241)" if is_selected else "none",
        }

        body_rows.append(html.Tr([
            # Name of Story — ID inline + title, single sticky column
            html.Td([
                html.Span(f"#{wid} ",
                          style={"fontFamily": _MONO, "fontSize": "10px",
                                 "color": _INDIGO, "marginRight": "6px",
                                 "fontWeight": "700"}),
                s["title"],
            ], style={**_TD_B, "position": "sticky", "left": "0px",
                      "zIndex": "2", "background": _BG_CARD,
                      "fontWeight": "600", "whiteSpace": "normal", "maxWidth": "200px"}),
            html.Td(s["story_owner"] or "—",
                    style={**_TD_B, "color": _FG, "fontSize": "12px",
                           "whiteSpace": "nowrap", "maxWidth": "85px"}),
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
            html.Td(s["release_date"] or "—",
                    style={**_TD_B, "color": _FG, "fontFamily": _MONO,
                           "fontSize": "12px", "whiteSpace": "nowrap",
                           "maxWidth": "115px"}),
            *[_stage_cell(s_stages.get(k, {}).get("status", ""),
                          s_stages.get(k, {}).get("date",   ""))
              for k, _ in _STAGES],
            html.Td(
                html.Span(comment[:40] + ("…" if len(comment) > 40 else ""),
                          style={"fontSize": "11px", "color": _DIM}) if comment
                else html.Span("—", style={"fontSize": "11px", "color": _DIM}),
                style={**_TD_B, "minWidth": "140px"},
            ),
        ],
            id={"type": "rs-row", "key": str(wid)},
            n_clicks=0,
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
                   COALESCE(release_date,  '') AS release_date
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

    def _lbl(t):
        return html.Div(t, style={
            "fontSize": "9.5px", "fontWeight": "700", "color": _DIM,
            "textTransform": "uppercase", "letterSpacing": "0.5px",
            "marginBottom": "5px",
        })

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

        def _sbtn(val, color):
            active = cur_st == val
            r = _rgb(color)
            return html.Button("✓" if active else "",
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

        return html.Div([
            html.Span(label, style={"flex": "1", "fontSize": "12px",
                                    "color": _FG, "lineHeight": "1.3"}),
            html.Div([
                _sbtn("done",        _GREEN),
                _sbtn("wip",         _AMBER),
                _sbtn("not_started", _RED),
            ], style={"display": "flex", "gap": "5px"}),
            dcc.Input(type="text", value=cur_dt, debounce=True,
                      placeholder="YYYY-MM-DD",
                      id={"type": "rs-stage-date", "stage": key},
                      style={
                          "width": "122px", "padding": "5px 6px",
                          "background": _BG_HEAD, "border": f"1px solid {_BD}",
                          "color": _FG, "borderRadius": "6px",
                          "fontSize": "11px", "fontFamily": _MONO,
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


# ── Layout ────────────────────────────────────────────────────────────────────
def layout(**_):
    releases = _get_releases()
    default  = releases[0] if releases else None

    return html.Div([
        dcc.Store(id="rs-release-store", data=default),
        dcc.Store(id="rs-panel-store"),
        dcc.Store(id="rs-panel-visible", data=False),
        dcc.Store(id="rs-initial", data={}),

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

        # Legend
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
                      style={"fontSize": "10.5px", "color": _DIM}),
        ], style={"display": "flex", "alignItems": "center",
                  "padding": "10px 24px", "flexWrap": "wrap"}),

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
)
def _render_table(release, selected_id, panel_visible):
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
    effective_id = selected_id if panel_visible else None
    return _build_table(stories, stage_data, row_data, selected_id=effective_id)


@callback(
    Output("rs-panel-store",   "data"),
    Output("rs-panel-visible", "data"),
    Output("rs-initial",       "data"),
    Input({"type": "rs-row", "key": ALL}, "n_clicks"),
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
    prevent_initial_call=True,
)
def _render_panel(story_id):
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
    Output("rs-panel-store", "data", allow_duplicate=True),
    Input("rs-save-btn",     "n_clicks"),
    State("rs-panel-store",  "data"),
    prevent_initial_call=True,
)
def _save_to_ado(n, story_id):
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
    return story_id


@callback(
    Output("rs-panel-visible", "data", allow_duplicate=True),
    Input("rs-delete-btn",    "n_clicks"),
    State("rs-panel-store",   "data"),
    prevent_initial_call=True,
)
def _delete_row(n, story_id):
    if not n or not story_id:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM p_release_stages WHERE work_item_id = :id"),
                     {"id": story_id})
        conn.execute(text("DELETE FROM p_release_rows   WHERE work_item_id = :id"),
                     {"id": story_id})
    return False
