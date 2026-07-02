"""Team Pulse — rolling 12-month capacity grid across all teams."""
from __future__ import annotations
import re
from datetime import date, timedelta

import dash
from dash import html, dcc, callback, Input, Output, State, ALL, ctx, no_update
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

_STORY_SIZE_MAP = {
    "big": "Big", "medium": "Medium", "small": "Small",
    "very small": "Very small", "very_small": "Very small",
}

def _map_story_size(raw: str) -> str:
    return _STORY_SIZE_MAP.get(str(raw or "").strip().lower(), "Unsized")

def _classify_size(h: float) -> str:
    if h >= 40:   return "Big"
    if h >= 16:   return "Medium"
    if h >= 8:    return "Small"
    if h >= 1:    return "Very small"
    return "Unsized"

_BUG_TYPES = ("Issue", "Bug", "Bug_UI", "Bug_Text")

_MONTH_OPTIONS = [
    "Jan 2026","Feb 2026","Mar 2026","Apr 2026","May 2026","Jun 2026",
    "Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026",
    "Jan 2027","Feb 2027","Mar 2027","Apr 2027","May 2027","Jun 2027",
]

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
                COALESCE(w.priority, '')      AS priority,
                COALESCE(w.main_developer, '') AS main_developer,
                COALESCE(w.original_estimate, 0) AS orig_est,
                COALESCE(a.task_est_sum, 0)       AS task_est,
                w.iteration_path,
                COALESCE(a.est_status, 'unestimated') AS est_status,
                COALESCE(w.type, 'Internal')      AS cust_type,
                COALESCE(w.story_size, '')        AS story_size,
                COALESCE(w.release_date, '')      AS release_date
            FROM work_items_main w
            LEFT JOIN agg_story_estimation a ON a.work_item_id = w.work_item_id
            WHERE w.state NOT IN (
                'Closed','Resolved','Not Required','Not an issue',
                'No Customer Response','Not Specified','Userstory Update'
            )
            AND w.main_developer IS NOT NULL
            AND w.main_developer NOT IN ('', 'Unassigned', 'Not Specified')
            AND w.work_item_type IN ('Enhancement','User Story','Issue','Bug','Bug_UI','Bug_Text')
        """)).fetchall()

    items = []
    for r in rows:
        ym = _parse_iter_ym(r.iteration_path)
        if not ym:
            continue
        is_issue  = r.work_item_type in _BUG_TYPES
        orig_h    = float(r.orig_est or 0)
        task_h    = float(r.task_est or 0)
        est_h     = task_h if task_h > 0 else orig_h
        estimated = r.est_status in ("estimated", "estimated_via_tasks")
        team      = _TEAM_MAP.get(r.main_developer, "Other")
        platform  = "Mobile" if team == "Mobile Dev" else ("Web" if team == "Web Dev" else None)
        items.append({
            "wid":          int(r.work_item_id),
            "type":         "issue" if is_issue else "enh",
            "pri":          _classify_pri(r.priority),
            "dev":          r.main_developer,
            "team":         team,
            "orig_h":       orig_h,
            "task_h":       task_h,
            "est_h":        est_h,
            "size":         _map_story_size(r.story_size) if not is_issue else None,
            "ym":           ym,
            "mk":           _month_key(*ym),
            "estimated":    estimated,
            "cust_type":    str(r.cust_type or "Internal"),
            "platform":     platform,
            "release_date": str(r.release_date or ""),
        })
    return items


# ── Task-level hours loader ───────────────────────────────────────────────────
def _load_task_hours() -> list[dict]:
    """One record per ACTIVE Task (not Closed/Dev Complete/Resolved) under an Enhancement/Issue/Bug.
    Hours = remaining_work; fallback = original_estimate - completed_work (floor 0).
    Used to build both the hours row and issue/enh count rows for each developer."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                COALESCE(t.main_developer, '') AS main_developer,
                COALESCE(
                    t.remaining_work,
                    GREATEST(COALESCE(t.original_estimate, 0) - COALESCE(t.completed_work, 0), 0)
                )                            AS task_est,
                t.iteration_path             AS task_iter,
                COALESCE(w.type, 'Internal') AS cust_type,
                t.parent_id                  AS parent_id,
                w.work_item_type             AS parent_type
            FROM work_items_main t
            INNER JOIN work_items_main w ON w.work_item_id = t.parent_id
            WHERE t.work_item_type = 'Task'
            AND t.state NOT IN (
                'Closed','Resolved','Not Required','Not an issue'
            )
            AND w.work_item_type IN ('Enhancement','User Story','Issue','Bug','Bug_UI','Bug_Text')
            AND w.state NOT IN (
                'Closed','Resolved','Not Required','Not an issue',
                'No Customer Response','Not Specified','Userstory Update'
            )
            AND COALESCE(t.main_developer, '') NOT IN ('', 'Unassigned', 'Not Specified')
        """)).fetchall()

    result = []
    for r in rows:
        dev = str(r.main_developer or "").strip()
        if not dev:
            continue
        ym = _parse_iter_ym(r.task_iter)
        if not ym:
            continue
        team     = _TEAM_MAP.get(dev, "Other")
        platform = "Mobile" if team == "Mobile Dev" else ("Web" if team == "Web Dev" else None)
        result.append({
            "dev":         dev,
            "team":        team,
            "mk":          _month_key(*ym),
            "est_h":       float(r.task_est or 0),
            "cust_type":   str(r.cust_type or "Internal"),
            "platform":    platform,
            "parent_id":   int(r.parent_id) if r.parent_id else None,
            "parent_type": "issue" if str(r.parent_type or "") in _BUG_TYPES else "enh",
        })
    return result


# ── Dev-cell panel loader (task-based, matches grid logic) ────────────────────
def _dev_panel_load(mk: str, dev: str,
                    source_filter: str = "All",
                    platform_filter: str = "All") -> list[dict]:
    """Load parent stories for a developer by querying their TASKS in this month.
    Matches the grid: hours come from task.original_estimate, keyed by task iteration."""
    year, month = int(mk[:4]), int(mk[5:7])
    iter_pat = f"%{year} {month:02d}-%"
    team     = _TEAM_MAP.get(dev, "Other")
    platform = "Mobile" if team == "Mobile Dev" else ("Web" if team == "Web Dev" else None)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                w.work_item_id,
                COALESCE(w.title, '')        AS title,
                w.work_item_type,
                COALESCE(w.type, 'Internal') AS cust_type,
                COALESCE(w.priority, '')     AS priority,
                COALESCE(w.story_size, '')   AS story_size,
                COALESCE(w.release_date, '') AS release_date,
                CASE
                    WHEN ta.task_h IS NOT NULL THEN ta.task_h
                    ELSE COALESCE(
                        w.remaining_work,
                        GREATEST(COALESCE(w.original_estimate,0) - COALESCE(w.completed_work,0), 0)
                    )
                END AS task_h
            FROM work_items_main w
            LEFT JOIN (
                SELECT parent_id,
                       SUM(COALESCE(
                           remaining_work,
                           GREATEST(COALESCE(original_estimate,0) - COALESCE(completed_work,0), 0)
                       )) AS task_h
                FROM work_items_main
                WHERE work_item_type = 'Task'
                  AND main_developer  = :dev
                  AND iteration_path  LIKE :pat
                  AND state NOT IN ('Closed','Resolved','Not Required','Not an issue')
                GROUP BY parent_id
            ) ta ON ta.parent_id = w.work_item_id
            WHERE w.work_item_type IN ('Enhancement','User Story','Issue','Bug','Bug_UI','Bug_Text')
              AND w.state NOT IN (
                  'Closed','Resolved','Not Required','Not an issue',
                  'No Customer Response','Not Specified','Userstory Update'
              )
              AND (
                  -- Dev has active tasks for this item in this month
                  ta.parent_id IS NOT NULL
                  OR
                  -- Item is directly assigned to this dev in this month AND has no child tasks at all
                  (w.main_developer = :dev
                   AND w.iteration_path LIKE :pat
                   AND NOT EXISTS (
                       SELECT 1 FROM work_items_main tx
                       WHERE tx.parent_id = w.work_item_id AND tx.work_item_type = 'Task'
                   ))
              )
            GROUP BY w.work_item_id, w.title, w.work_item_type, w.type, w.priority,
                     w.story_size, w.release_date,
                     w.remaining_work, w.original_estimate, w.completed_work, ta.task_h
        """), {"dev": dev, "pat": iter_pat}).fetchall()

    result = []
    for r in rows:
        cust = str(r.cust_type or "Internal")
        if source_filter != "All" and cust != source_filter:
            continue
        if platform_filter != "All" and platform != platform_filter:
            continue
        is_issue = r.work_item_type in _BUG_TYPES
        est_h    = float(r.task_h or 0)
        result.append({
            "id":           r.work_item_id,
            "title":        r.title,
            "type":         "issue" if is_issue else "enh",
            "dev":          dev,
            "team":         team,
            "pri":          _classify_pri(r.priority),
            "size":         _map_story_size(r.story_size) if not is_issue else None,
            "est_h":        est_h,
            "estimated":    est_h > 0,
            "cust_type":    cust,
            "platform":     platform,
            "release_date": str(r.release_date or ""),
        })
    return result


# ── Panel data loader ────────────────────────────────────────────────────────
def _panel_load(mk: str, team_filter: str,
                source_filter: str = "All", platform_filter: str = "All") -> list[dict]:
    """All items for a given month key, with team/source/platform filters applied."""
    year, month = int(mk[:4]), int(mk[5:7])
    iter_pat = f"%{year} {month:02d}-%"
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                w.work_item_id,
                COALESCE(w.title, '') AS title,
                w.work_item_type,
                COALESCE(w.main_developer, '') AS main_developer,
                COALESCE(w.original_estimate, 0) AS orig_est,
                COALESCE(a.est_status, 'unestimated') AS est_status,
                COALESCE(w.type, 'Internal')      AS cust_type,
                COALESCE(w.priority, '')           AS priority,
                COALESCE(tk.iter_task_est, 0)     AS iter_task_est,
                COALESCE(ar.active_remaining, 0)  AS task_est_total,
                COALESCE(w.story_size, '')         AS story_size,
                COALESCE(w.release_date, '')       AS release_date
            FROM work_items_main w
            LEFT JOIN agg_story_estimation a ON a.work_item_id = w.work_item_id
            LEFT JOIN (
                SELECT parent_id,
                       SUM(COALESCE(remaining_work, original_estimate, 0)) AS iter_task_est
                FROM work_items_main
                WHERE work_item_type = 'Task'
                AND state NOT IN (
                    'Closed','Dev Complete','Resolved','Not Required','Not an issue'
                )
                AND iteration_path LIKE :pat
                GROUP BY parent_id
            ) tk ON tk.parent_id = w.work_item_id
            LEFT JOIN (
                SELECT parent_id,
                       SUM(COALESCE(remaining_work, original_estimate, 0)) AS active_remaining
                FROM work_items_main
                WHERE work_item_type = 'Task'
                AND state NOT IN (
                    'Closed','Dev Complete','Resolved','Not Required','Not an issue'
                )
                GROUP BY parent_id
            ) ar ON ar.parent_id = w.work_item_id
            WHERE w.state NOT IN (
                'Closed','Resolved','Not Required','Not an issue',
                'No Customer Response','Not Specified','Userstory Update'
            )
            AND w.main_developer IS NOT NULL
            AND w.main_developer NOT IN ('', 'Unassigned', 'Not Specified')
            AND w.work_item_type IN ('Enhancement','User Story','Issue','Bug','Bug_UI','Bug_Text')
            AND w.iteration_path LIKE :pat
        """), {"pat": iter_pat}).fetchall()
    result = []
    for r in rows:
        is_issue    = r.work_item_type in _BUG_TYPES
        orig_h      = float(r.orig_est or 0)
        iter_task_h  = float(r.iter_task_est or 0)
        all_task_h   = float(r.task_est_total or 0)
        # Prefer tasks scoped to this iteration; fall back to orig estimate; last resort all-time tasks
        est_h = iter_task_h if iter_task_h > 0 else (orig_h if orig_h > 0 else all_task_h)
        team     = _TEAM_MAP.get(r.main_developer, "Other")
        if team_filter != "All" and team != team_filter:
            continue
        if source_filter != "All" and str(r.cust_type or "Internal") != source_filter:
            continue
        if platform_filter != "All":
            plat = "Mobile" if team == "Mobile Dev" else ("Web" if team == "Web Dev" else None)
            if plat != platform_filter:
                continue
        result.append({
            "id":           int(r.work_item_id),
            "title":        str(r.title),
            "type":         "issue" if is_issue else "enh",
            "dev":          str(r.main_developer),
            "team":         team,
            "pri":          _classify_pri(r.priority),
            "size":         _map_story_size(r.story_size) if not is_issue else None,
            "est_h":        est_h,
            "estimated":    r.est_status in ("estimated", "estimated_via_tasks"),
            "cust_type":    str(r.cust_type or "Internal"),
            "release_date": str(r.release_date or ""),
        })
    return result


# ── Panel stub helper (hidden seed elements keep Dash callbacks registered) ───
_SEL_CYAN = "rgb(6,182,212)"

def _panel_stubs() -> list:
    """Return fresh hidden stub components so Dash can resolve panel callback IDs
    even before the panel has been opened for the first time."""
    return [
        html.Button(id="tp-sel-all",   n_clicks=0, style={"display": "none"}),
        html.Button(id="tp-sel-clear", n_clicks=0, style={"display": "none"}),
        html.Button(id="tp-move-btn",  n_clicks=0, style={"display": "none"}),
        dcc.Dropdown(id="tp-move-month", options=[], style={"display": "none"}),
    ]


# ── Panel content builder ─────────────────────────────────────────────────────

def _build_panel_content(panel_ctx: dict, team_filter: str,
                         source_filter: str = "All", platform_filter: str = "All",
                         selected_ids: list | None = None,
                         moved_items: dict | None = None) -> html.Div:
    kind = panel_ctx["kind"]
    key  = panel_ctx["key"]
    mk   = panel_ctx["mk"]

    # Developer cells: load by task assignee (matches grid logic).
    # Non-dev cells: load by story owner filtered to the month.
    if kind in ("dev_hours", "dev_issues", "dev_enhancements"):
        all_items = _dev_panel_load(mk, key, source_filter, platform_filter)
    else:
        all_items = _panel_load(mk, team_filter, source_filter, platform_filter)

    if kind == "issue_pri":
        items      = [x for x in all_items if x["type"] == "issue" and x["pri"] == key]
        title_txt  = f"{key} issues"
        type_label = "Issues"
    elif kind == "enh_size":
        items      = [x for x in all_items if x["type"] == "enh" and x["size"] == key]
        title_txt  = f"{key} enhancements"
        type_label = "Enhancements"
    elif kind == "dev_hours":
        items      = [x for x in all_items if x["dev"] == key]
        title_txt  = key
        type_label = "All work"
    elif kind == "dev_issues":
        items      = [x for x in all_items if x["dev"] == key and x["type"] == "issue"]
        title_txt  = key
        type_label = "Issues"
    elif kind == "dev_enhancements":
        items      = [x for x in all_items if x["dev"] == key and x["type"] == "enh"]
        title_txt  = key
        type_label = "Enhancements"
    else:
        return html.Div("Unknown context", style={"color": _DIM})

    sel     = set(selected_ids or [])
    n_sel   = len(sel)
    n_total = len(items)
    n_est   = sum(1 for x in items if x["estimated"])
    n_unest = n_total - n_est
    total_h = sum(x["est_h"] for x in items)
    y, m    = int(mk[:4]), int(mk[5:7])
    ml      = _month_label(y, m)
    tl      = team_filter if team_filter != "All" else "All teams"

    # Title row — dev kinds get a team badge
    title_children: list = [html.Span(title_txt, style={
        "fontSize": "17px", "fontWeight": "700", "color": _FG,
    })]
    if kind in ("dev_hours", "dev_issues", "dev_enhancements"):
        team = _TEAM_MAP.get(key, "Other")
        tc   = _TEAM_COLORS.get(team, _DIM)
        r    = _rgb(tc)
        title_children.append(html.Span(team, style={
            "fontSize": "10px", "fontWeight": "700", "color": tc,
            "background": f"rgba({r},0.13)", "border": f"1px solid rgba({r},0.35)",
            "borderRadius": "5px", "padding": "2px 7px", "marginLeft": "8px",
        }))
        subtitle = (f"{type_label} · {ml} · {n_total} item{'s' if n_total!=1 else ''} "
                    f"· {n_est} of {n_total} estimated")
    else:
        subtitle = (f"{ml} · {tl} · {n_total} item{'s' if n_total!=1 else ''} "
                    f"· {n_est} of {n_total} estimated")

    # ── Item row ──────────────────────────────────────────────────────────────
    def _item_row(x: dict, is_est: bool) -> html.Div:
        h_str   = f"{int(x['est_h'])}h" if x["est_h"] > 0 else "—"
        h_color = _FG if is_est else _AMBER
        is_sel  = x["id"] in sel
        row_bg  = (f"rgba({_rgb(_SEL_CYAN)},0.11)" if is_sel
                   else (f"rgba({_rgb(_AMBER)},0.08)" if not is_est else "transparent"))
        row_extra = ({"outline": f"rgba({_rgb(_SEL_CYAN)},0.4) solid 1px",
                      "outlineOffset": "-1px"} if is_sel else {})
        chk_style = {
            "width": "16px", "height": "16px", "borderRadius": "4px", "flexShrink": "0",
            "border": f"1.5px solid {_SEL_CYAN}",
            "background": _SEL_CYAN if is_sel else "transparent",
            "color": "rgb(11,17,32)", "fontSize": "11px", "fontWeight": "800",
            "display": "flex", "alignItems": "center", "justifyContent": "center",
        }
        return html.Div([
            html.Div("✓" if is_sel else "", style=chk_style),
            html.Span(f"#{x['id']}", style={
                "fontFamily": _MONO, "fontSize": "11px", "color": _DIM, "flexShrink": "0",
            }),
            html.Div([
                html.Div(x["title"], style={
                    "color": _FG, "fontSize": "12px",
                    "lineHeight": "1.35", "wordBreak": "break-word",
                }),
                html.Div(x["dev"], style={
                    "fontSize": "10px", "color": _DIM, "marginTop": "1px",
                }),
                *(
                    [
                        html.Span(
                            "No release date",
                            style={
                                "display": "inline-block", "marginTop": "4px",
                                "background": "rgba(251,191,36,0.12)",
                                "color": "rgb(251,191,36)",
                                "border": "1px solid rgba(251,191,36,0.3)",
                                "borderRadius": "4px", "padding": "1px 7px",
                                "fontSize": "10px", "fontWeight": "600",
                            }
                        ),
                        html.Div([
                            dcc.Dropdown(
                                id={"type": "tp-rd-sel", "wid": x["id"]},
                                options=[{"label": m, "value": m} for m in _MONTH_OPTIONS],
                                placeholder="Set release month…",
                                clearable=False,
                                style={"flex": "1", "fontSize": "11px", "minWidth": "0"},
                                className="tp-rd-dropdown",
                            ),
                            html.Button("Set", id={"type": "tp-rd-save", "wid": x["id"]},
                                        n_clicks=0,
                                        style={
                                            "flexShrink": "0", "padding": "3px 10px",
                                            "borderRadius": "5px", "fontSize": "11px",
                                            "fontWeight": "600", "cursor": "pointer",
                                            "background": "rgba(251,191,36,0.15)",
                                            "color": "rgb(251,191,36)",
                                            "border": "1px solid rgba(251,191,36,0.4)",
                                        }),
                        ], style={
                            "display": "flex", "gap": "4px", "marginTop": "5px",
                            "alignItems": "center",
                        }),
                    ]
                    if x.get("type") == "issue" and not x.get("release_date") else []
                ),
                *(
                    [html.Span(
                        f"Moved → {(moved_items or {}).get(str(x['id']))}",
                        style={
                            "display": "inline-block", "marginTop": "4px",
                            "background": "rgba(6,182,212,0.15)",
                            "color": "rgb(6,182,212)",
                            "border": "1px solid rgba(6,182,212,0.3)",
                            "borderRadius": "4px", "padding": "1px 7px",
                            "fontSize": "10px", "fontWeight": "600",
                        }
                    )]
                    if (moved_items and str(x["id"]) in moved_items) else []
                ),
            ], style={"minWidth": "0", "flex": "1"}),
            html.Span(h_str, style={
                "fontFamily": _MONO, "fontWeight": "600", "color": h_color,
                "minWidth": "42px", "textAlign": "right", "flexShrink": "0",
            }),
        ], id={"type": "tp-panel-item", "wid": x["id"]}, n_clicks=0, style={
            "display": "grid", "gridTemplateColumns": "22px 54px 1fr 55px",
            "gap": "0 6px",
            "padding": "7px 10px", "fontSize": "12px", "borderRadius": "6px",
            "alignItems": "flex-start", "cursor": "pointer",
            "background": row_bg,
            "borderBottom": f"1px solid rgba({_rgb(_BD_CELL)},0.5)",
            **row_extra,
        })

    # ── Section content ───────────────────────────────────────────────────────
    def _section_header(label: str, color: str, count: int, total: int) -> html.Div:
        r = _rgb(color)
        return html.Div([
            html.Div(style={"width": "6px", "height": "6px", "borderRadius": "50%",
                            "background": color, "flexShrink": "0"}),
            html.Span(label, style={"fontSize": "13px", "fontWeight": "600", "color": color}),
            html.Span(f"{count} / {total}", style={
                "fontSize": "10px", "padding": "2px 8px", "borderRadius": "10px",
                "fontWeight": "600", "fontFamily": _MONO,
                "background": f"rgba({r},0.12)", "color": color,
                "border": f"1px solid rgba({r},0.2)", "whiteSpace": "nowrap",
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                  "marginBottom": "10px"})

    def _total_line(label: str, h: float) -> html.Div:
        return html.Div([
            html.Span(label, style={"fontWeight": "600"}),
            html.Span(f"{int(h)}h", style={"fontFamily": _MONO, "fontWeight": "600"}),
        ], style={
            "display": "flex", "justifyContent": "space-between",
            "padding": "8px 10px", "fontSize": "13px",
            "borderTop": f"1px solid rgba({_rgb(_BD_CELL)},0.5)",
            "marginTop": "6px",
        })

    if kind == "dev_hours":
        # Group by issues / enhancements
        iss_items = sorted([x for x in items if x["type"] == "issue"],
                           key=lambda x: x["est_h"], reverse=True)
        enh_items = sorted([x for x in items if x["type"] == "enh"],
                           key=lambda x: x["est_h"], reverse=True)
        iss_h = sum(x["est_h"] for x in iss_items)
        enh_h = sum(x["est_h"] for x in enh_items)
        iss_est = sum(1 for x in iss_items if x["estimated"])
        enh_est = sum(1 for x in enh_items if x["estimated"])

        sections: list = []
        if iss_items:
            sections += [
                _section_header("Issues", _RED, iss_est, len(iss_items)),
                *[_item_row(x, x["estimated"]) for x in iss_items],
                _total_line("Hours on issues", iss_h),
                html.Div(style={"marginBottom": "16px"}),
            ]
        if enh_items:
            sections += [
                _section_header("Enhancements", _GREEN, enh_est, len(enh_items)),
                *[_item_row(x, x["estimated"]) for x in enh_items],
                _total_line("Hours on enhancements", enh_h),
                html.Div(style={"marginBottom": "8px"}),
            ]
        sections.append(_total_line("Total hours — all work", total_h))
    else:
        est_items   = sorted([x for x in items if x["estimated"]],
                             key=lambda x: x["est_h"], reverse=True)
        unest_items = [x for x in items if not x["estimated"]]
        sections = []
        if est_items:
            sections += [
                _section_header("Estimated", _GREEN, n_est, n_total),
                *[_item_row(x, True) for x in est_items],
                _total_line("Total hours", total_h),
            ]
        if unest_items:
            sections += [
                html.Div(style={"marginBottom": "16px"}),
                _section_header("Unestimated", _AMBER, n_unest, n_total),
                *[_item_row(x, False) for x in unest_items],
            ]

    # ── Customer / Internal pills ─────────────────────────────────────────────
    cust_counts: dict[str, int] = {}
    for x in items:
        cust_counts[x["cust_type"]] = cust_counts.get(x["cust_type"], 0) + 1
    _CUST_CLR = {
        "Customer": "rgb(6,182,212)",
        "Internal": "rgb(139,92,246)",
    }
    pills = [
        html.Span(f"{ct}: {cnt}", style={
            "fontSize": "10px", "padding": "3px 10px", "borderRadius": "12px",
            "fontWeight": "600",
            "background": f"rgba({_rgb(_CUST_CLR.get(ct,_DIM))},0.08)",
            "color": _CUST_CLR.get(ct, _DIM),
            "border": f"1px solid rgba({_rgb(_CUST_CLR.get(ct,_DIM))},0.2)",
        })
        for ct, cnt in sorted(cust_counts.items())
    ]

    return html.Div([
        # Header
        html.Div([
            html.Div([
                html.Div(title_children,
                         style={"display": "flex", "alignItems": "center", "gap": "8px"}),
                html.Div(subtitle, style={"fontSize": "13px", "color": _MT, "marginTop": "2px"}),
            ]),
            html.Button("✕", id="tp-panel-close", n_clicks=0, style={
                "background": "none", "border": "none", "color": _DIM,
                "cursor": "pointer", "fontSize": "20px", "padding": "4px 8px",
                "borderRadius": "6px", "lineHeight": "1",
            }),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "flex-start", "marginBottom": "20px"}),

        # KPI cards
        html.Div([
            html.Div([
                html.Div(f"{int(total_h)}h", style={
                    "fontFamily": _MONO, "fontSize": "28px", "fontWeight": "700",
                    "color": _FG,
                }),
                html.Div("Total hours", style={"fontSize": "11px", "color": _MT, "marginTop": "2px"}),
            ], style={
                "background": _BG_HEAD, "borderRadius": "10px",
                "padding": "14px 16px",
                "border": f"1px solid rgba({_rgb(_BD)},0.25)",
            }),
            html.Div([
                html.Div(f"{n_unest} / {n_total}", style={
                    "fontFamily": _MONO, "fontSize": "28px", "fontWeight": "700",
                    "color": _AMBER,
                }),
                html.Div("Unestimated", style={"fontSize": "11px", "color": _MT, "marginTop": "2px"}),
            ], style={
                "background": f"rgba({_rgb(_AMBER)},0.08)", "borderRadius": "10px",
                "padding": "14px 16px",
                "border": f"1px solid rgba({_rgb(_AMBER)},0.19)",
            }),
        ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                  "gap": "10px", "marginBottom": "20px"}),

        # Items
        html.Div(sections),

        # Move items section
        html.Div([
            html.Div([
                html.Span("Move items", style={"fontSize": "12px", "fontWeight": "700", "color": _FG}),
                html.Span(f"{n_sel} selected", style={
                    "fontSize": "11px", "fontFamily": _MONO, "color": _SEL_CYAN,
                }),
            ], style={"display": "flex", "alignItems": "center",
                      "justifyContent": "space-between", "marginBottom": "10px"}),
            html.Div([
                html.Button("Select all", id="tp-sel-all", n_clicks=0, style={
                    "fontSize": "11px", "fontWeight": "600", "color": _MT,
                    "background": "none", "border": f"1px solid {_BD}",
                    "borderRadius": "6px", "padding": "4px 9px", "cursor": "pointer",
                }),
                html.Button("Clear", id="tp-sel-clear", n_clicks=0, style={
                    "fontSize": "11px", "fontWeight": "600", "color": _MT,
                    "background": "none", "border": f"1px solid {_BD}",
                    "borderRadius": "6px", "padding": "4px 9px", "cursor": "pointer",
                }),
            ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "8px"}),
            html.Div([
                dcc.Dropdown(
                    id="tp-move-month",
                    options=[
                        {
                            "label": (_month_label(y2, m2) + (" (current)" if _month_key(y2, m2) == mk else "")),
                            "value": str(i),
                            "disabled": _month_key(y2, m2) == mk,
                        }
                        for i, (y2, m2) in enumerate(_rolling_months(12))
                    ],
                    placeholder="Move to month…",
                    clearable=False,
                    style={"flex": "1", "fontSize": "12.5px"},
                    className="tp-move-dropdown",
                ),
                html.Button("Move", id="tp-move-btn", n_clicks=0,
                            disabled=(n_sel == 0),
                            style={
                                "padding": "8px 16px", "borderRadius": "7px",
                                "fontSize": "12.5px", "fontWeight": "700",
                                "cursor": "pointer" if n_sel > 0 else "not-allowed",
                                "background": _SEL_CYAN if n_sel > 0 else _BG_PAGE,
                                "color": "rgb(11,17,32)" if n_sel > 0 else _DIM,
                                "border": f"1px solid {_BD}",
                                "whiteSpace": "nowrap",
                            }),
            ], style={"display": "flex", "alignItems": "center", "gap": "8px"}),
        ], style={
            "marginTop": "20px", "padding": "14px", "borderRadius": "10px",
            "background": _BG_HEAD, "border": f"1px solid rgba({_rgb(_BD)},0.314)",
        }),

        # Customer / Internal pills
        html.Div(pills, style={"display": "flex", "flexWrap": "wrap",
                               "gap": "6px", "marginTop": "20px"}),
    ])


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

def _num_cell(n: int, hi_thresh=25, red_thresh=32, style=None, cid=None, highlight=False) -> html.Td:
    hl = {"outline": f"2px solid {_INDIGO}", "outlineOffset": "-2px"} if highlight else {}
    if n == 0:
        return html.Td("–", style={**_TD_S, "color": _DIM, **(style or {}), **hl})
    color = _RED if n >= red_thresh else (_AMBER if n >= hi_thresh else _FG)
    fw    = "700" if color != _FG else "500"
    if cid:
        return html.Td(
            html.Div(str(n), id=cid, n_clicks=0,
                     style={"cursor": "pointer", "color": color, "fontWeight": fw}),
            style={**_TD_S, **(style or {}), **hl},
        )
    return html.Td(str(n), style={**_TD_S, "color": color, "fontWeight": fw, **(style or {}), **hl})

def _hours_cell(h: float, has_tasks: bool, cid=None, highlight=False) -> html.Td:
    hl = {"outline": f"2px solid {_INDIGO}", "outlineOffset": "-2px"} if highlight else {}
    if h == 0 and not has_tasks:
        return html.Td("–", style={**_TD_S, "color": _DIM, **hl})
    color = _RED if h > 120 else (_AMBER if h > 60 else _FG)
    inner: list = [html.Div(f"{int(h)}h", style={
        "color": color, "fontWeight": "700", "fontFamily": _MONO, "fontSize": "11px",
    })]
    if has_tasks and h == 0:
        inner.append(html.Div("– – – –", style={
            "fontSize": "8.5px", "color": _DIM, "letterSpacing": "1.5px", "marginTop": "1px",
        }))
    if cid:
        return html.Td(html.Div(inner, id=cid, n_clicks=0, style={"cursor": "pointer"}),
                       style={**_TD_S, "padding": "4px 8px", **hl})
    return html.Td(inner, style={**_TD_S, "padding": "4px 8px", **hl})

def _eu_cell(est: int, unest: int, cid=None, highlight=False) -> html.Td:
    hl    = {"outline": f"2px solid {_INDIGO}", "outlineOffset": "-2px"} if highlight else {}
    total = est + unest
    if total == 0:
        return html.Td("–", style={**_TD_S, "color": _DIM, **hl})
    inner = [
        html.Div(str(total), style={"fontWeight": "700", "color": _FG, "fontSize": "12px"}),
        html.Div([
            html.Span(f"{est}e",   style={"color": _GREEN}),
            html.Span(" · ",       style={"color": _DIM}),
            html.Span(f"{unest}u", style={"color": _AMBER if unest else _DIM}),
        ], style={"fontSize": "9px", "marginTop": "1px", "fontFamily": _MONO}),
    ]
    if cid:
        return html.Td(html.Div(inner, id=cid, n_clicks=0, style={"cursor": "pointer"}),
                       style={**_TD_S, "padding": "4px 8px", **hl})
    return html.Td(inner, style={**_TD_S, "padding": "4px 8px", **hl})

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


_PLAT_COLORS = {"Mobile": "rgb(6,182,212)", "Web": "rgb(139,92,246)"}


def _build_platform_table(plat_by_mk: dict, months: list, mks: list, today_mk: str) -> html.Div:
    head_cells = [html.Th("Items by Platform", style={
        **_TH_S, "textAlign": "left", "minWidth": "160px",
    })]
    for y, m in months:
        mk = _month_key(y, m)
        lbl = _month_label(y, m)
        is_now = mk == today_mk
        head_cells.append(html.Th(lbl, style={
            **_TH_S, "minWidth": "76px",
            "color": _INDIGO if is_now else _DIM,
            "borderBottom": f"2px solid {_INDIGO}" if is_now else f"1px solid {_BD}",
        }))
    tbody_rows = []
    for plat in ("Mobile", "Web"):
        color = _PLAT_COLORS[plat]
        r     = _rgb(color)
        name_cell = html.Td([
            html.Span(style={
                "display": "inline-block", "width": "7px", "height": "7px",
                "borderRadius": "2px", "background": color,
                "marginRight": "8px", "verticalAlign": "middle",
            }),
            plat,
        ], style={**_TD_S, "textAlign": "left", "color": color,
                  "fontWeight": "600", "paddingLeft": "12px"})
        cells = [name_cell]
        for mk in mks:
            n = plat_by_mk[plat].get(mk, 0)
            if n == 0:
                cells.append(html.Td("–", style={**_TD_S, "color": _DIM}))
            else:
                cells.append(html.Td(str(n), style={
                    **_TD_S, "color": color, "fontWeight": "600", "fontFamily": _MONO,
                }))
        tbody_rows.append(html.Tr(cells))
    return html.Div(
        html.Table([
            html.Thead(html.Tr(head_cells)),
            html.Tbody(tbody_rows),
        ], style={"borderCollapse": "collapse", "width": "100%",
                  "minWidth": f"{160 + len(mks) * 80}px"}),
        style={"border": f"1px solid {_BD}", "borderRadius": "10px",
               "overflow": "auto", "marginBottom": "16px"},
    )


# ── Main grid builder ─────────────────────────────────────────────────────────
def _build_grid(items: list[dict], team_filter: str, horizon_d: int,
                source_filter: str = "All", platform_filter: str = "All",
                panel_ctx: dict | None = None) -> html.Div:
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

    # Apply source filter
    if source_filter != "All":
        filtered = [x for x in filtered if x.get("cust_type") == source_filter]

    # Apply platform filter
    if platform_filter != "All":
        filtered = [x for x in filtered if x.get("platform") == platform_filter]

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

    # ── Platform counts per month ─────────────────────────────────────────────
    plat_by_mk: dict[str, dict[str, int]] = {
        "Mobile": {mk: 0 for mk in mks},
        "Web":    {mk: 0 for mk in mks},
    }
    for x in filtered:
        if x["mk"] in mks and x.get("platform") in ("Mobile", "Web"):
            plat_by_mk[x["platform"]][x["mk"]] += 1

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
        if x["task_h"] > 0:
            # Has child tasks — hours and issue/enh counts come from task_hours below.
            cell["has_tasks"] = True
        else:
            # Taskless story: hours from story estimate, count from story iteration.
            cell["orig_h"] += x["est_h"]
            if x["type"] == "issue":
                if x["estimated"]: cell["iss_e"] += 1
                else:              cell["iss_u"] += 1
            else:
                if x["estimated"]: cell["enh_e"] += 1
                else:              cell["enh_u"] += 1

    # ── Task-level hours + counts: overlay onto dev_data ─────────────────────
    # Hours and issue/enh counts for task-having items use each task's own
    # iteration_path so they land in the month the developer is actually working.
    task_hours = _load_task_hours()
    if team_filter != "All":
        task_hours = [t for t in task_hours if t["team"] == team_filter]
    task_hours = [t for t in task_hours if t["mk"] in active_mks]
    if source_filter != "All":
        task_hours = [t for t in task_hours if t.get("cust_type") == source_filter]
    if platform_filter != "All":
        task_hours = [t for t in task_hours if t.get("platform") == platform_filter]

    mks_set = set(mks)
    for th in task_hours:
        dev = th["dev"]
        mk  = th["mk"]
        if mk not in mks_set:
            continue
        if dev not in dev_data:
            dev_data[dev] = {m: {"orig_h": 0.0, "has_tasks": False,
                                  "iss_e": 0, "iss_u": 0,
                                  "enh_e": 0, "enh_u": 0} for m in mks}
        if mk not in dev_data[dev]:
            dev_data[dev][mk] = {"orig_h": 0.0, "has_tasks": False,
                                  "iss_e": 0, "iss_u": 0,
                                  "enh_e": 0, "enh_u": 0}
        dev_data[dev][mk]["orig_h"]    += th["est_h"]
        dev_data[dev][mk]["has_tasks"] = True

    # Rebuild issue/enh counts for task-based items (dedup by parent per dev×month).
    # This makes counts consistent with the panel, which also queries by task iteration.
    _counted_parents: set = set()
    for th in task_hours:
        dev = th["dev"]
        mk  = th["mk"]
        pid = th.get("parent_id")
        if not pid or mk not in mks_set:
            continue
        key3 = (dev, mk, pid)
        if key3 in _counted_parents:
            continue
        _counted_parents.add(key3)
        if dev not in dev_data or mk not in dev_data[dev]:
            continue
        cell = dev_data[dev][mk]
        est  = th["est_h"] > 0
        if th["parent_type"] == "issue":
            if est: cell["iss_e"] += 1
            else:   cell["iss_u"] += 1
        else:
            if est: cell["enh_e"] += 1
            else:   cell["enh_u"] += 1

    # ── Active cell check (for highlight) ────────────────────────────────────
    def _is_active(kind: str, key: str, mk: str) -> bool:
        if not panel_ctx:
            return False
        return (panel_ctx.get("kind") == kind and
                panel_ctx.get("key") == key and
                panel_ctx.get("mk") == mk)

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
            cells.append(_num_cell(
                iss_by_pri[pri][mk],
                cid={"type": "tp-cell", "kind": "issue_pri", "key": pri, "mk": mk},
                highlight=_is_active("issue_pri", pri, mk),
            ))
        tbody_rows.append(html.Tr(cells))

    # Issues sub-total row
    iss_sub_cells = [html.Td("Issues sub-total", style={
        **_TD_S, "textAlign": "left", "paddingLeft": "16px",
        "fontWeight": "700", "color": _RED, "fontSize": "11px",
        "background": _BG_HEAD, "borderTop": f"1px solid {_BD}",
    })]
    for mk in mks:
        n = sum(iss_by_pri[p][mk] for p in _PRI_LABELS)
        iss_sub_cells.append(_num_cell(n, style={
            "background": _BG_HEAD, "fontWeight": "700",
            "color": _RED, "borderTop": f"1px solid {_BD}",
        }))
    tbody_rows.append(html.Tr(iss_sub_cells))

    # ── Enhancements section ──────────────────────────────────────────────────
    tbody_rows.append(_section_row("Enhancements", n_cols))
    for sz in _ENH_SIZES:
        cells = [_label_cell(sz)]
        for mk in mks:
            cells.append(_num_cell(
                enh_by_sz[sz][mk],
                cid={"type": "tp-cell", "kind": "enh_size", "key": sz, "mk": mk},
                highlight=_is_active("enh_size", sz, mk),
            ))
        tbody_rows.append(html.Tr(cells))

    # Enhancements sub-total row
    enh_sub_cells = [html.Td("Enhancements sub-total", style={
        **_TD_S, "textAlign": "left", "paddingLeft": "16px",
        "fontWeight": "700", "color": _GREEN, "fontSize": "11px",
        "background": _BG_HEAD, "borderTop": f"1px solid {_BD}",
    })]
    for mk in mks:
        n = sum(enh_by_sz[s][mk] for s in _ENH_SIZES)
        enh_sub_cells.append(_num_cell(n, style={
            "background": _BG_HEAD, "fontWeight": "700",
            "color": _GREEN, "borderTop": f"1px solid {_BD}",
        }))
    tbody_rows.append(html.Tr(enh_sub_cells))

    # Grand total row
    total_cells = [html.Td("Grand Total", style={
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
            h_cells.append(_hours_cell(
                c["orig_h"], c["has_tasks"],
                cid={"type": "tp-cell", "kind": "dev_hours", "key": dev, "mk": mk},
                highlight=_is_active("dev_hours", dev, mk),
            ))
        tbody_rows.append(html.Tr(h_cells))

        # ISSUES row
        i_cells = [_label_cell("Issues")]
        for mk in mks:
            c = dev_data[dev][mk]
            i_cells.append(_eu_cell(
                c["iss_e"], c["iss_u"],
                cid={"type": "tp-cell", "kind": "dev_issues", "key": dev, "mk": mk},
                highlight=_is_active("dev_issues", dev, mk),
            ))
        tbody_rows.append(html.Tr(i_cells))

        # ENHANCEMENTS row
        e_cells = [_label_cell("Enhancements")]
        for mk in mks:
            c = dev_data[dev][mk]
            e_cells.append(_eu_cell(
                c["enh_e"], c["enh_u"],
                cid={"type": "tp-cell", "kind": "dev_enhancements", "key": dev, "mk": mk},
                highlight=_is_active("dev_enhancements", dev, mk),
            ))
        tbody_rows.append(html.Tr(e_cells))

    rows.append(html.Tbody(tbody_rows))

    # Summary stats
    n_devs  = len(devs)
    n_items = len(filtered)
    n_hours = int(sum(x["est_h"] for x in filtered))

    return html.Div([
        # Platform mini-table
        _build_platform_table(plat_by_mk, months, mks, today_mk),

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

    # Source counts
    source_counts: dict[str, int] = {}
    for x in items:
        ct = x.get("cust_type", "Internal")
        source_counts[ct] = source_counts.get(ct, 0) + 1
    total_items = len(items)

    # Platform counts
    platform_counts: dict[str, int] = {}
    for x in items:
        p = x.get("platform")
        if p in ("Mobile", "Web"):
            platform_counts[p] = platform_counts.get(p, 0) + 1

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

    def _fpill(label, count, pill_type, val, active, color):
        r = _rgb(color)
        return html.Div([
            html.Span(label, style={"marginRight": "5px"}),
            html.Span(str(count), style={
                "fontFamily": _MONO, "fontSize": "10px", "fontWeight": "700",
                "padding": "1px 6px", "borderRadius": "8px",
                "background": f"rgba({r},0.18)" if active else f"rgba({_rgb(_DIM)},0.22)",
                "color": color if active else _DIM,
            }),
        ], id={"type": pill_type, "val": val}, n_clicks=0, style={
            "display": "flex", "alignItems": "center", "gap": "2px",
            "padding": "4px 10px", "borderRadius": "16px",
            "cursor": "pointer", "fontSize": "11px", "fontWeight": "600",
            "background": f"rgba({r},0.1)" if active else "transparent",
            "border": f"1.5px solid rgba({r},0.45)" if active else f"1px solid {_BD}",
            "color": color if active else _MT, "whiteSpace": "nowrap",
        })

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
        dcc.Store(id="tp-team-store",       data="All"),
        dcc.Store(id="tp-horizon-store",   data=365),
        dcc.Store(id="tp-source-store",    data="All"),
        dcc.Store(id="tp-platform-store",  data="All"),
        dcc.Store(id="tp-panel-ctx",       data=None),
        dcc.Store(id="tp-panel-selection", data=[]),
        dcc.Store(id="tp-toast-store",     data=None),
        dcc.Store(id="tp-moved-store",     data={}),
        dcc.Store(id="tp-rd-refresh",      data=0),

        # ── Toast notification ────────────────────────────────────────────────
        html.Div(id="tp-toast", style={"display": "none"},
                 children="",
                 **{"data-toast": "1"}),

        # ── Drill-down panel (fixed right overlay) ────────────────────────────
        html.Div(
            id="tp-panel-wrap",
            style={"display": "none"},
            children=html.Div(
                id="tp-panel-body",
                style={
                    "position": "fixed", "top": "0", "right": "0",
                    "height": "100vh", "width": "760px",
                    "background": "rgb(17,24,39)",
                    "borderLeft": f"1px solid {_BD}",
                    "overflowY": "auto", "padding": "24px 20px",
                    "zIndex": "100",
                    "boxShadow": "-8px 0 32px rgba(0,0,0,0.6)",
                },
                children=_panel_stubs(),
            ),
        ),

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

        # ── Horizon / Source / Platform filter bar ────────────────────────────
        html.Div([
            # Horizon
            html.Span("Horizon", style={
                "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                "textTransform": "uppercase", "letterSpacing": "0.5px",
                "marginRight": "6px", "whiteSpace": "nowrap",
            }),
            html.Div(id="tp-horizon-pills",
                     children=[
                         _hpill("30d",  30,  False),
                         _hpill("90d",  90,  False),
                         _hpill("180d", 180, False),
                         _hpill("365d", 365, True),
                     ],
                     style={"display": "flex", "gap": "5px", "marginRight": "18px"}),
            # Source
            html.Span("Source", style={
                "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                "textTransform": "uppercase", "letterSpacing": "0.5px",
                "marginRight": "6px", "whiteSpace": "nowrap",
            }),
            html.Div(id="tp-source-pills",
                     children=[
                         _fpill("All",      total_items,                               "tp-source-pill",   "All",      True,  _FG),
                         _fpill("Customer", source_counts.get("Customer", 0),          "tp-source-pill",   "Customer", False, "rgb(6,182,212)"),
                         _fpill("Internal", source_counts.get("Internal", 0),          "tp-source-pill",   "Internal", False, "rgb(139,92,246)"),
                     ],
                     style={"display": "flex", "gap": "5px", "marginRight": "18px"}),
            # Platform
            html.Span("Platform", style={
                "fontSize": "10px", "fontWeight": "700", "color": _DIM,
                "textTransform": "uppercase", "letterSpacing": "0.5px",
                "marginRight": "6px", "whiteSpace": "nowrap",
            }),
            html.Div(id="tp-platform-pills",
                     children=[
                         _fpill("All",    total_items,                           "tp-platform-pill", "All",    True,  _FG),
                         _fpill("Mobile", platform_counts.get("Mobile", 0),      "tp-platform-pill", "Mobile", False, "rgb(6,182,212)"),
                         _fpill("Web",    platform_counts.get("Web",    0),      "tp-platform-pill", "Web",    False, "rgb(139,92,246)"),
                     ],
                     style={"display": "flex", "gap": "5px"}),
        ], style={
            "padding": "10px 24px", "borderBottom": f"1px solid {_BD}",
            "background": _BG_CARD, "display": "flex",
            "alignItems": "center", "flexWrap": "wrap", "gap": "6px",
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


def _make_fpill(label, count, pill_type, val, active, color):
    r = _rgb(color)
    return html.Div([
        html.Span(label, style={"marginRight": "5px"}),
        html.Span(str(count), style={
            "fontFamily": _MONO, "fontSize": "10px", "fontWeight": "700",
            "padding": "1px 6px", "borderRadius": "8px",
            "background": f"rgba({r},0.18)" if active else f"rgba({_rgb(_DIM)},0.22)",
            "color": color if active else _DIM,
        }),
    ], id={"type": pill_type, "val": val}, n_clicks=0, style={
        "display": "flex", "alignItems": "center", "gap": "2px",
        "padding": "4px 10px", "borderRadius": "16px",
        "cursor": "pointer", "fontSize": "11px", "fontWeight": "600",
        "background": f"rgba({r},0.1)" if active else "transparent",
        "border": f"1.5px solid rgba({r},0.45)" if active else f"1px solid {_BD}",
        "color": color if active else _MT, "whiteSpace": "nowrap",
    })


@callback(
    Output("tp-source-store",  "data"),
    Output("tp-source-pills",  "children"),
    Input({"type": "tp-source-pill", "val": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_source(clicks):
    if not any(clicks):
        raise PreventUpdate
    selected = ctx.triggered_id["val"]
    items = _load_items()
    sc: dict[str, int] = {}
    for x in items:
        ct = x.get("cust_type", "Internal")
        sc[ct] = sc.get(ct, 0) + 1
    total = len(items)
    return selected, [
        _make_fpill("All",      total,                  "tp-source-pill", "All",      selected == "All",      _FG),
        _make_fpill("Customer", sc.get("Customer", 0),  "tp-source-pill", "Customer", selected == "Customer", "rgb(6,182,212)"),
        _make_fpill("Internal", sc.get("Internal", 0),  "tp-source-pill", "Internal", selected == "Internal", "rgb(139,92,246)"),
    ]


@callback(
    Output("tp-platform-store",  "data"),
    Output("tp-platform-pills",  "children"),
    Input({"type": "tp-platform-pill", "val": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_platform(clicks):
    if not any(clicks):
        raise PreventUpdate
    selected = ctx.triggered_id["val"]
    items = _load_items()
    pc: dict[str, int] = {}
    for x in items:
        p = x.get("platform")
        if p in ("Mobile", "Web"):
            pc[p] = pc.get(p, 0) + 1
    total = len(items)
    return selected, [
        _make_fpill("All",    total,                "tp-platform-pill", "All",    selected == "All",    _FG),
        _make_fpill("Mobile", pc.get("Mobile", 0), "tp-platform-pill", "Mobile", selected == "Mobile", "rgb(6,182,212)"),
        _make_fpill("Web",    pc.get("Web",    0), "tp-platform-pill", "Web",    selected == "Web",    "rgb(139,92,246)"),
    ]


@callback(
    Output("tp-grid", "children"),
    Input("tp-team-store",     "data"),
    Input("tp-horizon-store",  "data"),
    Input("tp-source-store",   "data"),
    Input("tp-platform-store", "data"),
    Input("tp-panel-ctx",      "data"),
)
def _render_grid(team, horizon, source, platform, panel_ctx):
    items = _load_items()
    return _build_grid(items, team or "All", horizon or 365,
                       source or "All", platform or "All", panel_ctx)


@callback(
    Output("tp-moved-store", "data", allow_duplicate=True),
    Input("tp-panel-ctx", "data"),
    prevent_initial_call=True,
)
def _clear_moved_on_open(panel_ctx):
    # Reset move tags when a new panel cell is opened (new session).
    # Don't clear on close — panel disappears anyway.
    if panel_ctx is not None:
        return {}
    raise PreventUpdate


# ── Panel callbacks ───────────────────────────────────────────────────────────
@callback(
    Output("tp-panel-ctx", "data"),
    Input({"type": "tp-cell", "kind": ALL, "key": ALL, "mk": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _open_panel(clicks):
    if not any(clicks):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid:
        raise PreventUpdate
    return {"kind": tid["kind"], "key": tid["key"], "mk": tid["mk"]}


@callback(
    Output("tp-panel-ctx", "data", allow_duplicate=True),
    Input("tp-panel-close", "n_clicks"),
    prevent_initial_call=True,
)
def _close_panel(n):
    if not n:
        raise PreventUpdate
    return None


@callback(
    Output("tp-panel-wrap", "style"),
    Output("tp-panel-body", "children"),
    Input("tp-panel-ctx",       "data"),
    Input("tp-panel-selection", "data"),
    Input("tp-rd-refresh",      "data"),
    State("tp-team-store",     "data"),
    State("tp-source-store",   "data"),
    State("tp-platform-store", "data"),
    State("tp-moved-store",    "data"),
)
def _render_panel(panel_ctx, selection, _rd_refresh, team_filter, source_filter, platform_filter,
                  moved_items):
    _PANEL_STYLE = {
        "position": "fixed", "top": "0", "right": "0",
        "height": "100vh", "width": "760px",
        "background": "rgb(17,24,39)",
        "borderLeft": f"1px solid {_BD}",
        "overflowY": "auto", "padding": "24px 20px",
        "zIndex": "100",
        "boxShadow": "-8px 0 32px rgba(0,0,0,0.6)",
    }
    if not panel_ctx:
        return {"display": "none"}, _panel_stubs()
    # When the panel context changes, treat as fresh open (ignore stale selection)
    if ctx.triggered_id == "tp-panel-ctx":
        effective_sel = []
    else:
        effective_sel = selection or []
    content = _build_panel_content(panel_ctx, team_filter or "All",
                                   source_filter or "All", platform_filter or "All",
                                   selected_ids=effective_sel,
                                   moved_items=moved_items or {})
    return {"display": "block"}, html.Div(content, style=_PANEL_STYLE)


# ── Panel selection toggle ────────────────────────────────────────────────────
@callback(
    Output("tp-panel-selection", "data"),
    Input("tp-panel-ctx",      "data"),
    Input({"type": "tp-panel-item", "wid": ALL}, "n_clicks"),
    Input("tp-sel-all",   "n_clicks"),
    Input("tp-sel-clear", "n_clicks"),
    State("tp-panel-selection", "data"),
    State("tp-team-store",     "data"),
    State("tp-source-store",   "data"),
    State("tp-platform-store", "data"),
    prevent_initial_call=True,
)
def _panel_selection(panel_ctx, _item_clicks, _sel_all, _sel_clear,
                     current_sel, team, source, platform):
    trigger = ctx.triggered_id

    # New panel opened — reset selection
    if trigger == "tp-panel-ctx":
        return []

    if trigger == "tp-sel-clear":
        return []

    if trigger == "tp-sel-all":
        if not panel_ctx:
            return []
        kind, key = panel_ctx.get("kind"), panel_ctx.get("key")
        mk = panel_ctx.get("mk", "")
        if kind in ("dev_hours", "dev_issues", "dev_enhancements"):
            all_items = _dev_panel_load(mk, key, source or "All", platform or "All")
            if kind == "dev_issues":
                visible = [x for x in all_items if x["type"] == "issue"]
            elif kind == "dev_enhancements":
                visible = [x for x in all_items if x["type"] == "enh"]
            else:
                visible = all_items
        else:
            all_items = _panel_load(mk, team or "All", source or "All", platform or "All")
            if kind == "issue_pri":
                visible = [x for x in all_items if x["type"] == "issue" and x["pri"] == key]
            elif kind == "enh_size":
                visible = [x for x in all_items if x["type"] == "enh" and x["size"] == key]
            else:
                visible = all_items
        return [x["id"] for x in visible]

    # Item row click — toggle
    if isinstance(trigger, dict) and trigger.get("type") == "tp-panel-item":
        wid = trigger["wid"]
        sel = set(current_sel or [])
        if wid in sel:
            sel.discard(wid)
        else:
            sel.add(wid)
        return list(sel)

    return no_update


# ── Panel move items ──────────────────────────────────────────────────────────
@callback(
    Output("tp-panel-selection", "data", allow_duplicate=True),
    Output("tp-moved-store",     "data", allow_duplicate=True),
    Output("tp-grid",            "children", allow_duplicate=True),
    Input("tp-move-btn", "n_clicks"),
    State("tp-panel-selection", "data"),
    State("tp-move-month",     "value"),
    State("tp-panel-ctx",      "data"),
    State("tp-moved-store",    "data"),
    State("tp-team-store",     "data"),
    State("tp-horizon-store",  "data"),
    State("tp-source-store",   "data"),
    State("tp-platform-store", "data"),
    prevent_initial_call=True,
)
def _panel_move(n_clicks, selected_ids, month_idx, panel_ctx, moved_store,
                team, horizon, source, platform):
    if not n_clicks or not selected_ids or month_idx is None:
        raise PreventUpdate

    # Resolve target iteration month
    all_months = _rolling_months(12)
    y2, m2 = all_months[int(month_idx)]

    # Look up canonical iteration_path for that month from existing DB rows
    iter_pat = f"%{y2} {m2:02d}-%"
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT iteration_path FROM work_items_main
            WHERE iteration_path LIKE :pat AND iteration_path IS NOT NULL
            LIMIT 1
        """), {"pat": iter_pat}).fetchone()

    if row:
        new_iter = row.iteration_path
    else:
        from datetime import date as _date
        mn = _date(y2, m2, 1).strftime("%B")
        new_iter = f"Solo Expenses\\{y2}\\Iteration {y2} {m2:02d}-{mn}"

    # Write to ADO (fire-and-forget) and update local DB optimistically
    from sync.ado_write import write_iteration
    ids = [int(i) for i in selected_ids]
    for wid in ids:
        write_iteration(wid, new_iter)

    with engine.begin() as conn:
        for wid in ids:
            conn.execute(text("""
                UPDATE work_items_main SET iteration_path = :path
                WHERE work_item_id = :wid
            """), {"path": new_iter, "wid": wid})

    from datetime import date as _d
    label = _d(y2, m2, 1).strftime("%b-%y")
    updated = dict(moved_store or {})
    for wid in ids:
        updated[str(wid)] = label

    # Rebuild matrix inline — no panel-ctx change, so _render_grid won't fire;
    # this is the only callback touching tp-grid right now, no conflict.
    items = _load_items()
    grid  = _build_grid(items, team or "All", horizon or 365,
                        source or "All", platform or "All")
    return [], updated, grid


# ── Release date set ──────────────────────────────────────────────────────────
@callback(
    Output("tp-rd-refresh",  "data", allow_duplicate=True),
    Output("tp-toast-store", "data", allow_duplicate=True),
    Input({"type": "tp-rd-save", "wid": ALL}, "n_clicks"),
    State({"type": "tp-rd-sel",  "wid": ALL}, "value"),
    prevent_initial_call=True,
)
def _set_release_date(n_clicks_list, rd_vals):
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        raise PreventUpdate
    wid = int(triggered["wid"])
    # Find corresponding dropdown value
    idx = next(
        (i for i, inp in enumerate(ctx.inputs_list[0]) if inp["id"]["wid"] == wid),
        None,
    )
    rd = (rd_vals[idx] or "").strip() if idx is not None and idx < len(rd_vals) else ""
    if not rd:
        raise PreventUpdate
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE work_items_main SET release_date = :rd WHERE work_item_id = :wid"
        ), {"rd": rd, "wid": wid})
    from sync.ado_write import write_fields as _aw
    _aw(wid, {"release_date": rd})
    import time as _t
    return _t.time(), f"Release date set: #{wid} → {rd}"


# ── Toast notification (server-side: show for 3 s via interval) ───────────────
@callback(
    Output("tp-toast", "style"),
    Output("tp-toast", "children"),
    Input("tp-toast-store", "data"),
    prevent_initial_call=True,
)
def _show_toast(msg):
    if not msg:
        return {"display": "none"}, ""
    _TOAST_STYLE = {
        "display": "flex", "alignItems": "center", "gap": "8px",
        "position": "fixed", "bottom": "24px", "right": "28px",
        "background": "rgb(6,182,212)", "color": "rgb(11,17,32)",
        "fontWeight": "700", "fontSize": "13px",
        "padding": "10px 18px", "borderRadius": "10px",
        "boxShadow": "0 4px 20px rgba(0,0,0,0.5)",
        "zIndex": "9999",
    }
    return _TOAST_STYLE, f"+ {msg}"
