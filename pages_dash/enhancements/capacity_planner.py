"""Developer Capacity & Work Allocation"""

import re
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback, ALL, no_update, ctx
from dash.exceptions import PreventUpdate
import pandas as pd
from datetime import date
import calendar

from config.dev_capacity import DEVELOPERS, DEV_MAP
from config.settings import ADO_BASE_URL

# ── UI render cache ───────────────────────────────────────────────────────────
# Keyed on (view, tab, show_all, cust_key, bust_counter).
# The bust counter comes from data.loader.get_ui_cache_bust() — increments
# every time the aggregator runs or leave data changes.  Old keys are simply
# never hit; _prune() clears them to avoid unbounded growth.
_RENDER_CACHE: dict = {}


def _prune(current_bust: int) -> None:
    stale = [k for k in _RENDER_CACHE if k[-1] != current_bust]
    for k in stale:
        del _RENDER_CACHE[k]

dash.register_page(__name__, path="/dev-capacity", name="Developer Capacity")

_GOLD   = "var(--gold)"
_GREEN  = "var(--green)"
_RED    = "var(--red)"
_BLU    = "var(--purple)"
_CARD   = "var(--bg-elevated)"
_BORDER = "var(--border)"

# ── Month helpers ─────────────────────────────────────────────────────────────

def _months012():
    t = date.today()
    y, m = t.year, t.month
    result = []
    for _ in range(3):
        result.append(date(y, m, 1))
        m += 1
        if m > 12:
            m = 1; y += 1
    return result

def _ym(d: date) -> str:
    return d.strftime("%Y-%m")

def _iter_ym(path) -> str | None:
    s = str(path).split("\\")[-1] if path else ""
    m = re.search(r"(\d{4})\s+(\d{2})-", s)
    return f"{m.group(1)}-{m.group(2)}" if m else None

def _parse_release_ym(rd: str) -> str | None:
    if not rd or str(rd).lower() in (
        "not specified", "nan", "", "hotfix", "hot fix", "tbd", "n/a", "none"
    ):
        return None
    for fmt in ("%b %Y", "%B %Y"):
        try:
            return pd.to_datetime(rd, format=fmt).strftime("%Y-%m")
        except Exception:
            pass
    try:
        ts = pd.to_datetime(rd, errors="coerce")
        if pd.notna(ts):
            return ts.strftime("%Y-%m")
    except Exception:
        pass
    return None


# ── Constants ─────────────────────────────────────────────────────────────────

_TERMINAL_STATES = {"Closed", "Dev Complete", "Resolved", "Not Required", "Not an issue"}
_HOURS_PER_DAY   = 10.0


def _remaining_workday_hours(ym_str: str) -> float:
    """Remaining weekday hours from today to end of month (inclusive). Returns
    full month hours for future months, 0 for past months."""
    today = date.today()
    year, month = int(ym_str[:4]), int(ym_str[5:7])
    cur_ym = today.strftime("%Y-%m")
    _, last_day = calendar.monthrange(year, month)

    if ym_str > cur_ym:
        start_day = 1
    elif ym_str < cur_ym:
        return 0.0
    else:
        start_day = today.day

    count = sum(
        1 for d in range(start_day, last_day + 1)
        if date(year, month, d).weekday() < 5
    )
    return count * _HOURS_PER_DAY


# ── Data helpers ──────────────────────────────────────────────────────────────

def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "iteration_path" in df.columns:
        df["iteration_path"] = df["iteration_path"].apply(
            lambda x: str(x).split("\\")[-1]
            if pd.notna(x) and str(x) not in ("Not Specified", "")
            else str(x)
        )
    if "main_developer" in df.columns:
        df["main_developer"] = (
            df["main_developer"].astype(str).str.split(" <").str[0].str.strip()
        )
    df["_est"] = pd.to_numeric(
        df.get("original_estimate", 0), errors="coerce"
    ).fillna(0)
    _rem = pd.to_numeric(df.get("remaining_work", 0), errors="coerce").fillna(0)
    df["_live_est"] = _rem.where(_rem > 0, df["_est"])
    df["_ym"] = df["iteration_path"].apply(_iter_ym)
    df["parent_id"] = pd.to_numeric(df.get("parent_id", pd.NA), errors="coerce")
    return df


def _eff_hours(df: pd.DataFrame) -> dict:
    """Effective hours per enhancement: sum child task estimates, or own estimate."""
    enhs = df[df["work_item_type"].str.contains("Enhancement", na=False, case=False)]
    tasks = df[df["work_item_type"] == "Task"]
    task_sums = (
        tasks.groupby("parent_id")["_est"].sum()
        if not tasks.empty
        else pd.Series(dtype=float)
    )
    result = {}
    for _, row in enhs.iterrows():
        eid = row["work_item_id"]
        ts  = task_sums.get(eid, 0)
        result[eid] = ts if ts > 0 else row["_est"]
    return result


def IS_ENH(t: str) -> bool:
    return "Enhancement" in str(t) or str(t) == "User Story"


def IS_ISSUE(t: str) -> bool:
    return str(t) in ("Bug", "Bug_UI", "Bug_Text")


def _prio_clr(p) -> str:
    try:
        p = int(p)
    except Exception:
        return "#64748b"
    return {1: _RED, 2: "#fb923c", 3: _BLU}.get(p, "#64748b")


def _size(h: float) -> str:
    return "Big" if h >= 120 else ("Medium" if h >= 40 else "Small")


def _ctrl_bar_dcap(pri_opt: str, srt_opt: str) -> "html.Div":
    from dash import html as _html, dcc as _dcc
    _PRI_OPTS = [{"label": l, "value": v} for l, v in
                 [("All", "all"), ("P1", "p1"), ("P2", "p2"), ("P3", "p3")]]
    _SRT_OPTS = [{"label": l, "value": v} for l, v in
                 [("Priority", "pri"), ("Hours ↓", "hours"), ("Release", "rd")]]
    _lbl = {"fontSize": "10px", "color": "#6b7280", "fontWeight": "600", "marginBottom": "3px"}

    return _html.Div([
        _html.Div([
            _html.Div("Filter", style=_lbl),
            _dcc.Dropdown(id={"type": "dcap-flt-dd", "k": "pri"},
                          options=_PRI_OPTS, value=pri_opt, clearable=False,
                          style={"minWidth": "100px", "fontSize": "11px"}),
        ]),
        _html.Div([
            _html.Div("Sort", style=_lbl),
            _dcc.Dropdown(id={"type": "dcap-flt-dd", "k": "srt"},
                          options=_SRT_OPTS, value=srt_opt, clearable=False,
                          style={"minWidth": "120px", "fontSize": "11px"}),
        ]),
    ], style={"display": "flex", "gap": "10px", "alignItems": "flex-end", "marginBottom": "12px"})


def _dev_month_items(df: pd.DataFrame, dev: str, ym_str: str, open_only: bool = False) -> list[dict]:
    """Items for a dev in a month, with tasks rolled up to their parent."""
    dev_df = df[(df["_ym"] == ym_str) & (df["main_developer"] == dev)]
    if open_only and "state" in dev_df.columns:
        dev_df = dev_df[~dev_df["state"].isin(_TERMINAL_STATES)]
    if dev_df.empty:
        return []

    est_col = "_live_est" if open_only else "_est"

    items: dict[int, dict] = {}

    # Tasks → roll up to parent
    tasks = dev_df[dev_df["work_item_type"] == "Task"]
    if not tasks.empty:
        for pid, grp in tasks.groupby("parent_id"):
            if pd.isna(pid):
                continue
            pid_i = int(pid)
            dev_h = grp[est_col].sum()
            pr = df[df["work_item_id"] == pid_i]
            if not pr.empty:
                r = pr.iloc[0]
                t, wt, prio = r["title"], r["work_item_type"], r.get("priority", 4)
            else:
                t, wt, prio = f"#{pid_i}", "Enhancement", 4
            items[pid_i] = {
                "id": pid_i, "title": t, "type": wt,
                "dev_h": dev_h, "priority": prio,
            }

    # Direct non-task items (old-style enhancements + bugs)
    for _, row in dev_df[dev_df["work_item_type"] != "Task"].iterrows():
        eid = int(row["work_item_id"])
        if eid not in items:
            items[eid] = {
                "id": eid, "title": row["title"],
                "type": row["work_item_type"],
                "dev_h": row[est_col],
                "priority": row.get("priority", 4),
            }

    return list(items.values())


# ── Standalone task data ──────────────────────────────────────────────────────

def _load_standalone_data(yms: list[str]) -> dict:
    """
    Returns {dev_name: {ym: {"total_h": float, "by_category": {cat: float}}}}
    from the pre-computed agg_standalone_overhead table.
    """
    from data.loader import engine
    from sqlalchemy import text as _text
    if not yms:
        return {}
    ym_list = ", ".join(f"'{y}'" for y in yms)
    try:
        with engine.connect() as _conn:
            rows = _conn.execute(_text(
                f"SELECT assigned_to, ym_str, category, total_hours "
                f"FROM agg_standalone_overhead WHERE ym_str IN ({ym_list})"
            )).fetchall()
    except Exception:
        return {}
    result: dict = {}
    for dev, ym, cat, h in rows:
        if not dev:
            continue
        h = float(h or 0)
        result.setdefault(dev, {}).setdefault(ym, {"total_h": 0.0, "by_category": {}})
        result[dev][ym]["total_h"] += h
        result[dev][ym]["by_category"][cat] = result[dev][ym]["by_category"].get(cat, 0.0) + h
    return result


def _load_cap_agg(yms: list[str], cust_filter: str = "All") -> dict:
    """Capacity hours per (dev, ym_str, item_type).

    cust_filter "All"      → use pre-computed agg_dev_monthly_capacity (fast)
    cust_filter "Customer" → filter agg_gantt_items by customer_type='Customer'
    cust_filter "Internal" → filter agg_gantt_items by customer_type='Internal'
    """
    from data.loader import engine
    from sqlalchemy import text as _text
    if not yms:
        return {}
    ym_list = ", ".join(f"'{y}'" for y in yms)

    try:
        with engine.connect() as _conn:
            if cust_filter in ("Customer", "Internal"):
                # Query work_items_main directly so closed/done items are included.
                # (agg_gantt_items only holds open items — near month-end M0 shows 0.)
                # Use LIKE for month extraction; regex fails on backslashes in path.
                month_case = " ".join(
                    f"WHEN iteration_path LIKE '%Iteration 2026 {ym[5:]}-%%' THEN '{ym}'"
                    for ym in yms
                )
                rows = _conn.execute(_text(f"""
                    SELECT
                        COALESCE(main_developer, 'Unassigned') AS main_developer,
                        CASE {month_case} END                  AS ym_str,
                        CASE WHEN work_item_type IN
                                  ('Bug','Bug_UI','Bug_Text','Bug_Watchlist')
                             THEN 'bug' ELSE 'enhancement' END AS item_type,
                        COUNT(*)                               AS item_count,
                        SUM(COALESCE(original_estimate, 0))   AS estimated_hours
                    FROM work_items_main
                    WHERE work_item_type IN
                          ('Enhancement','Bug','Bug_UI','Bug_Text','Bug_Watchlist')
                      AND type = '{cust_filter}'
                      AND main_developer IS NOT NULL
                      AND (
                          {'OR '.join(f"iteration_path LIKE '%Iteration 2026 {ym[5:]}-%%'" for ym in yms)}
                      )
                    GROUP BY main_developer, ym_str, item_type
                    HAVING CASE {month_case} END IN ({ym_list})
                """)).fetchall()
            else:
                rows = _conn.execute(_text(
                    f"SELECT main_developer, ym_str, item_type, item_count, estimated_hours "
                    f"FROM agg_dev_monthly_capacity WHERE ym_str IN ({ym_list})"
                )).fetchall()
    except Exception:
        return {}

    # agg_gantt_items uses "enh"; capacity grid expects "enhancement"
    _ITYPE = {"enh": "enhancement"}
    result: dict = {}
    for dev, ym, itype, cnt, hrs in rows:
        key = (dev, ym, _ITYPE.get(itype, itype))
        result[key] = {
            "item_count": int(cnt or 0),
            "estimated_hours": float(hrs or 0),
        }
    return result


def _load_top_items(yms: list[str]) -> dict:
    """Top work items per (dev, ym) for cell pills.
    Returns {(dev, ym_str): [{"title": str, "type": str, "dev_h": float}, ...]}.
    """
    from data.loader import engine
    from sqlalchemy import text as _text
    if not yms:
        return {}
    ym_list = ", ".join(f"'{y}'" for y in yms)
    _TYPE_MAP = {"enh": "Enhancement", "bug": "Bug"}
    try:
        with engine.connect() as _conn:
            rows = _conn.execute(_text(
                f"SELECT main_developer, "
                f"  '2026-' || LPAD(month_num::TEXT, 2, '0') AS ym_str, "
                f"  title, item_type, COALESCE(original_estimate, 0) AS dev_h "
                f"FROM agg_gantt_items "
                f"WHERE '2026-' || LPAD(month_num::TEXT, 2, '0') IN ({ym_list}) "
                f"  AND main_developer IS NOT NULL "
                f"ORDER BY main_developer, month_num, COALESCE(original_estimate, 0) DESC"
            )).fetchall()
    except Exception:
        return {}
    result: dict = {}
    for dev, ym, title, itype, dev_h in rows:
        result.setdefault((dev, ym), []).append({
            "title": title or "",
            "type": _TYPE_MAP.get(itype, "Enhancement"),
            "dev_h": float(dev_h or 0),
        })
    return result


def _load_task_dev_data(yms: list[str], cust_filter: str = "All") -> tuple[dict, dict]:
    """Task-based drop-in for _load_cap_agg + _load_top_items.

    Uses task assignments (not story main_developer) to attribute hours:
      – Part 1: task dev × task iteration → parent enhancement/bug
      – Part 2: directly assigned, no child tasks at all (bugs, standalone enhs)

    Returns
    -------
    cap_data  : {(dev, ym_str, item_type): {"item_count": int, "estimated_hours": float}}
    top_items : {(dev, ym_str): [{"title": str, "type": str, "dev_h": float}, ...]}
    item_type = "enhancement" | "bug"
    """
    from data.loader import engine as _eng
    from sqlalchemy import text as _t
    import logging
    if not yms:
        return {}, {}

    ym_set = set(yms)
    cust_clause = f"AND w.type = '{cust_filter}'" if cust_filter in ("Customer", "Internal") else ""

    try:
        with _eng.connect() as conn:
            rows = conn.execute(_t(f"""
                SELECT
                    t.main_developer  AS dev,
                    t.iteration_path  AS iter_path,
                    w.work_item_id,
                    w.title,
                    w.work_item_type,
                    SUM(COALESCE(
                        t.remaining_work,
                        GREATEST(COALESCE(t.original_estimate,0) - COALESCE(t.completed_work,0), 0)
                    )) AS dev_h
                FROM work_items_main t
                JOIN work_items_main w ON w.work_item_id = t.parent_id
                WHERE t.work_item_type = 'Task'
                  AND t.state NOT IN ('Closed','Resolved','Not Required','Not an issue')
                  AND w.work_item_type IN ('Enhancement','User Story','Issue','Bug')
                  AND w.state NOT IN (
                      'Closed','Resolved','Not Required','Not an issue',
                      'No Customer Response','Not Specified','Userstory Update'
                  )
                  AND COALESCE(t.main_developer,'') NOT IN ('','Unassigned','Not Specified')
                  AND t.iteration_path LIKE '%Iteration 2026 %'
                  {cust_clause}
                GROUP BY t.main_developer, t.iteration_path, w.work_item_id, w.title, w.work_item_type

                UNION ALL

                SELECT
                    w.main_developer  AS dev,
                    w.iteration_path  AS iter_path,
                    w.work_item_id,
                    w.title,
                    w.work_item_type,
                    COALESCE(
                        w.remaining_work,
                        GREATEST(COALESCE(w.original_estimate,0) - COALESCE(w.completed_work,0), 0)
                    ) AS dev_h
                FROM work_items_main w
                WHERE w.work_item_type IN ('Enhancement','User Story','Issue','Bug')
                  AND w.state NOT IN (
                      'Closed','Resolved','Not Required','Not an issue',
                      'No Customer Response','Not Specified','Userstory Update'
                  )
                  AND COALESCE(w.main_developer,'') NOT IN ('','Unassigned','Not Specified')
                  AND w.iteration_path LIKE '%Iteration 2026 %'
                  {cust_clause}
                  AND NOT EXISTS (
                      SELECT 1 FROM work_items_main tx
                      WHERE tx.parent_id = w.work_item_id AND tx.work_item_type = 'Task'
                  )
            """)).fetchall()
    except Exception as exc:
        logging.getLogger(__name__).error("_load_task_dev_data failed: %s", exc)
        return {}, {}

    _BUG_WTYPES = {"Bug", "Bug_UI", "Bug_Text", "Issue"}
    cap_data:  dict = {}
    top_items: dict = {}

    for r in rows:
        dev = str(r.dev or "").strip().split(" <")[0].strip()
        if not dev or dev in ("Unassigned", "Not Specified"):
            continue
        ym = _iter_ym(str(r.iter_path or ""))
        if not ym or ym not in ym_set:
            continue

        wtype = str(r.work_item_type or "")
        itype = "bug" if wtype in _BUG_WTYPES else "enhancement"
        dev_h = float(r.dev_h or 0)

        key = (dev, ym, itype)
        if key not in cap_data:
            cap_data[key] = {"item_count": 0, "estimated_hours": 0.0}
        cap_data[key]["item_count"]      += 1
        cap_data[key]["estimated_hours"] += dev_h

        top_items.setdefault((dev, ym), []).append({
            "title": str(r.title or ""),
            "type":  "Bug" if itype == "bug" else "Enhancement",
            "dev_h": dev_h,
        })

    return cap_data, top_items


_CAT_CLR = {
    "Meetings & Calls":  "#60a5fa",
    "Dev Overhead":      "#a78bfa",
    "Research & Spikes": "#fbbf24",
    "Design & Docs":     "#f472b6",
    "Testing & QA":      "#34d399",
    "Operations":        "#fb923c",
    "Other":             "#6b7280",
}


def _render_overhead_section(standalone_data: dict, devs: list, ym_str: str) -> html.Div:
    """Standalone task overhead breakdown card for a given month."""
    _OH = "#a78bfa"

    # Aggregate per-dev and per-category
    dev_rows = []
    cat_totals: dict[str, float] = {}
    grand_total = 0.0

    for dev in devs:
        dm = standalone_data.get(dev["name"], {}).get(ym_str, {})
        h  = dm.get("total_h", 0.0)
        by_cat = dm.get("by_category", {})
        if h == 0:
            continue
        grand_total += h
        for cat, ch in by_cat.items():
            cat_totals[cat] = cat_totals.get(cat, 0.0) + ch

        cat_pills = [
            html.Span(f"{cat}: {ch:.0f}h", style={
                "fontSize": "10px", "background": f"{_CAT_CLR.get(cat, '#6b7280')}22",
                "color": _CAT_CLR.get(cat, "#6b7280"), "padding": "2px 7px",
                "borderRadius": "4px", "marginRight": "4px",
                "border": f"1px solid {_CAT_CLR.get(cat, '#6b7280')}44",
            })
            for cat, ch in sorted(by_cat.items(), key=lambda x: -x[1])
        ]
        cap = dev.get("capacity_h", 180)
        oh_pct = round(h / cap * 100) if cap else 0
        dev_rows.append(html.Div([
            html.Div([
                html.Span(dev["name"], style={
                    "fontWeight": "600", "fontSize": "13px", "color": "#e2e8f0",
                    "minWidth": "140px",
                }),
                html.Span(f"{h:.0f}h", style={
                    "fontWeight": "700", "color": _OH,
                    "fontSize": "14px", "marginRight": "8px", "minWidth": "44px",
                }),
                html.Span(f"({oh_pct}% of cap)", style={
                    "fontSize": "11px", "color": "#6b7280", "marginRight": "12px",
                }),
                *cat_pills,
            ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "4px"}),
        ], style={
            "padding": "10px 14px",
            "borderBottom": "1px solid rgba(255,255,255,0.05)",
        }))

    if not dev_rows:
        return html.Div(
            "No standalone tasks found for this period. Run a sync to classify new tasks.",
            style={"color": "#4b5563", "fontSize": "13px", "padding": "20px 0"},
        )

    # Category summary bar
    cat_bar = []
    if grand_total > 0:
        for cat, h in sorted(cat_totals.items(), key=lambda x: -x[1]):
            w = h / grand_total * 100
            cat_bar.append(html.Div(
                title=f"{cat}: {h:.0f}h",
                style={
                    "width": f"{w:.1f}%", "height": "100%",
                    "background": _CAT_CLR.get(cat, "#6b7280"),
                },
            ))

    return html.Div([
        html.Div([
            html.Div([
                html.Div(f"{grand_total:.0f}h total overhead", style={
                    "fontSize": "20px", "fontWeight": "700", "color": _OH,
                }),
                html.Div("standalone tasks not linked to any story or bug", style={
                    "fontSize": "11px", "color": "#6b7280", "marginTop": "2px",
                }),
            ]),
            html.Div([
                *[
                    html.Span([
                        html.Span("■ ", style={"color": _CAT_CLR.get(c, "#6b7280"), "fontSize": "10px"}),
                        html.Span(f"{c}  ", style={"fontSize": "11px", "color": "#8892a4"}),
                    ])
                    for c in _CAT_CLR
                ],
            ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap", "gap": "2px"}),
        ], style={
            "display": "flex", "justifyContent": "space-between",
            "alignItems": "flex-start", "marginBottom": "14px",
        }),
        # Category colour bar
        html.Div(cat_bar, style={
            "display": "flex", "height": "6px", "borderRadius": "4px",
            "overflow": "hidden", "marginBottom": "16px",
            "background": "rgba(255,255,255,0.05)",
        }),
        *dev_rows,
    ])


# ── UI primitives ─────────────────────────────────────────────────────────────

def _kpi(value, label, sub, clr):
    return html.Div([
        html.Div(value, style={
            "fontSize": "26px", "fontWeight": "700",
            "color": clr, "lineHeight": "1.1",
        }),
        html.Div(label, style={
            "fontSize": "10px", "textTransform": "uppercase",
            "letterSpacing": "1px", "color": "#6b7280", "marginTop": "4px",
        }),
        html.Div(sub, style={
            "fontSize": "12px", "color": "#8892a4", "marginTop": "2px",
        }),
    ], style={
        "background": _CARD, "border": f"1px solid {_BORDER}",
        "borderRadius": "12px", "padding": "18px 20px", "flex": "1",
    })


def _cell_content(items: list, enh_h: float, issue_h: float, capacity: float,
                  pressure_mode: bool = False, remaining_h: float = None,
                  standalone_h: float = 0.0):
    total  = enh_h + issue_h + standalone_h
    denom  = remaining_h if (pressure_mode and remaining_h is not None) else capacity

    if pressure_mode and (remaining_h is None or remaining_h == 0):
        return html.Div([
            html.Div("—", style={"fontSize": "20px", "fontWeight": "700",
                                 "color": "#4b5563", "marginBottom": "2px"}),
            html.Div("0h left", style={"fontSize": "11px", "color": "#4b5563"}),
        ], style={"padding": "14px 16px"})

    pct   = round(total / denom * 100) if denom > 0 else 0
    pct_c = _RED if pct > 100 else (_GOLD if pct >= 80 else _GREEN)

    feat_h = enh_h + issue_h
    free_h = denom - feat_h - standalone_h  # negative = over-allocated

    top   = sorted(items, key=lambda x: -x["dev_h"])[:2]
    extra = len(items) - 2

    pills = []
    for i in top:
        clr = _GOLD if IS_ENH(i["type"]) else _GREEN
        txt = (i["title"][:32] + "…") if len(i["title"]) > 32 else i["title"]
        pills.append(html.Div([
            html.Span("• ", style={"color": clr}),
            html.Span(txt, style={"fontSize": "11px", "color": "#c8c8e0"}),
        ], style={"marginBottom": "2px"}))
    if extra > 0:
        pills.append(html.Div(f"+{extra} more",
                               style={"fontSize": "11px", "color": "#4b5563"}))

    live_badge = html.Span(
        "LIVE", style={
            "fontSize": "9px", "fontWeight": "700", "letterSpacing": "0.8px",
            "color": "#0f0f1e", "background": pct_c,
            "borderRadius": "4px", "padding": "1px 5px", "marginLeft": "6px",
            "verticalAlign": "middle",
        }
    ) if pressure_mode else None

    def _section_row(label, h, clr):
        w = min(h / denom * 100, 100) if denom > 0 else 0
        return html.Div([
            html.Span(label, style={
                "fontSize": "9px", "color": "#6b7280", "letterSpacing": "0.5px",
                "textTransform": "uppercase", "width": "80px", "flexShrink": "0",
            }),
            html.Span(f"{h:.0f}h", style={
                "fontSize": "12px", "fontWeight": "700", "color": clr,
                "width": "34px", "textAlign": "right", "flexShrink": "0",
            }),
            html.Div(
                html.Div(style={"width": f"{w:.0f}%", "height": "100%",
                                "background": clr, "borderRadius": "2px"}),
                style={
                    "flex": "1", "height": "4px", "borderRadius": "2px",
                    "background": "rgba(255,255,255,0.05)",
                    "margin": "0 8px", "alignSelf": "center",
                }
            ),
            html.Span(f"{round(w)}%", style={
                "fontSize": "10px", "color": "#4b5563",
                "width": "26px", "textAlign": "right", "flexShrink": "0",
            }),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "5px"})

    if free_h < 0:
        remaining_row = html.Div([
            html.Span("Remaining", style={
                "fontSize": "9px", "color": "#6b7280", "letterSpacing": "0.5px",
                "textTransform": "uppercase", "width": "80px", "flexShrink": "0",
            }),
            html.Span(f"{free_h:.0f}h", style={
                "fontSize": "12px", "fontWeight": "700", "color": _RED,
                "width": "34px", "textAlign": "right", "flexShrink": "0",
            }),
            html.Span("OVER-ALLOC", style={
                "flex": "1", "fontSize": "8px", "color": _RED,
                "fontWeight": "700", "letterSpacing": "0.8px", "margin": "0 8px",
            }),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "5px"})
    else:
        remaining_row = _section_row("Remaining", free_h, "#60a5fa")

    return html.Div([
        html.Div([
            html.Span(f"{pct}%", style={
                "fontSize": "20px", "fontWeight": "700", "color": pct_c,
            }),
            *([live_badge] if live_badge else []),
        ], style={"marginBottom": "8px"}),
        html.Div([
            _section_row("Feature Work",   feat_h,       _GOLD),
            _section_row("Admin Overhead", standalone_h, "#a78bfa"),
            remaining_row,
        ], style={
            "borderTop":    "1px solid rgba(255,255,255,0.05)",
            "borderBottom": "1px solid rgba(255,255,255,0.05)",
            "paddingTop": "7px", "paddingBottom": "3px",
            "marginBottom": "8px",
        }),
        *pills,
    ], style={"padding": "14px 16px"})


# ── Grid renderers ────────────────────────────────────────────────────────────

def _render_m012_grid(cap_data, top_items, devs, yms, month_labels, view, standalone_data=None, leave_data=None):
    cols = "180px 1fr 1fr 1fr"

    banner = html.Div(
        "← 1+2 PLANNING WINDOW — M0 · M1 · M2 →",
        style={
            "fontSize": "10px", "color": "#4b5563", "textAlign": "center",
            "letterSpacing": "1.5px", "padding": "5px",
            "borderBottom": "1px solid rgba(255,255,255,0.05)",
        },
    )
    banner_row = html.Div(
        [html.Div(), banner],
        style={"display": "grid", "gridTemplateColumns": "180px 1fr"},
    )

    # Pre-compute M0 remaining hours (needed by _mhdr below)
    m0_remaining_h = _remaining_workday_hours(yms[0])

    def _mhdr(lbl, idx):
        sub = html.Div(
            f"LIVE · {m0_remaining_h:.0f}h left" if idx == 0 else f"M{idx}",
            style={"fontSize": "9px", "color": _GOLD if idx == 0 else "#4b5563",
                   "textAlign": "center", "letterSpacing": "0.6px"},
        )
        return html.Div([
            sub,
            html.Div(lbl, style={
                "fontSize": "14px", "fontWeight": "600", "textAlign": "center",
                "color": _GOLD if idx == 0 else "#c8c8e0",
            }),
        ], style={
            "padding": "8px 16px",
            "borderBottom": "1px solid rgba(255,255,255,0.07)",
        })

    col_hdr = html.Div([
        html.Div("DEVELOPER", style={
            "fontSize": "10px", "color": "#4b5563", "textTransform": "uppercase",
            "letterSpacing": "1px", "padding": "8px 16px", "fontWeight": "700",
            "borderBottom": "1px solid rgba(255,255,255,0.07)",
        }),
        *[_mhdr(lbl, i) for i, lbl in enumerate(month_labels)],
    ], style={"display": "grid", "gridTemplateColumns": cols})

    sd = standalone_data or {}
    team_totals = [{"enh": 0.0, "iss": 0.0, "oh": 0.0, "cap": 0.0, "rem": m0_remaining_h if i == 0 else 0.0}
                   for i in range(3)]
    dev_rows = []

    ld = leave_data or {"leaves": {}, "holidays": {}}

    for dev in devs:
        cap = dev["capacity_h"]
        month_cells = []

        for m_idx, ym_str in enumerate(yms):
            is_m0 = (m_idx == 0)
            enh_h = cap_data.get((dev["name"], ym_str, "enhancement"), {}).get("estimated_hours", 0.0)
            iss_h = cap_data.get((dev["name"], ym_str, "bug"),          {}).get("estimated_hours", 0.0)
            all_pills = top_items.get((dev["name"], ym_str), [])

            if view == "Enhancements":
                display = [i for i in all_pills if IS_ENH(i["type"])]
                iss_h = 0.0
            elif view == "Issues":
                display = [i for i in all_pills if IS_ISSUE(i["type"])]
                enh_h = 0.0
            else:
                display = all_pills

            oh_h      = sd.get(dev["name"], {}).get(ym_str, {}).get("total_h", 0.0)
            leave_h   = ld["leaves"].get((dev["name"], ym_str), 0.0)
            holiday_h = ld["holidays"].get(ym_str, 0.0)
            eff_cap   = max(0.0, cap - leave_h - holiday_h)
            eff_rem   = max(0.0, m0_remaining_h - leave_h - holiday_h) if is_m0 else None

            team_totals[m_idx]["enh"] += enh_h
            team_totals[m_idx]["iss"] += iss_h
            team_totals[m_idx]["oh"]  += oh_h
            team_totals[m_idx]["cap"] += eff_cap

            month_cells.append(html.Div(
                _cell_content(
                    display, enh_h, iss_h, eff_cap,
                    pressure_mode=is_m0,
                    remaining_h=eff_rem,
                    standalone_h=oh_h,
                ),
                id={"type": "dcap-cell", "dev": dev["name"], "month": ym_str},
                n_clicks=0,
                style={
                    "cursor": "pointer",
                    "borderLeft": "1px solid rgba(255,255,255,0.05)",
                },
            ))

        dev_info = html.Div([
            html.Div(dev["name"], style={
                "fontWeight": "700", "fontSize": "14px",
                "color": "#e2e8f0", "marginBottom": "2px",
            }),
            html.Div(dev.get("role", "Developer"), style={
                "fontSize": "11px", "color": "#6b7280", "marginBottom": "2px",
            }),
            html.Div(f"{cap}h/mo", style={"fontSize": "11px", "color": _GOLD}),
        ], style={"padding": "16px", "minHeight": "120px"})

        dev_rows.append(html.Div(
            [dev_info, *month_cells],
            style={
                "display": "grid", "gridTemplateColumns": cols,
                "borderBottom": "1px solid rgba(255,255,255,0.05)",
            },
        ))

    # Team total row
    total_cells = [html.Div("TEAM TOTAL", style={
        "padding": "16px", "fontSize": "12px", "fontWeight": "700",
        "color": "#6b7280", "textTransform": "uppercase", "letterSpacing": "1px",
    })]
    for t_idx, t in enumerate(team_totals):
        total_h  = t["enh"] + t["iss"] + t["oh"]
        is_m0    = (t_idx == 0)
        denom    = (t["rem"] * len(devs)) if (is_m0 and t["rem"]) else t["cap"]
        pct      = round(total_h / denom * 100) if denom > 0 else 0
        pct_c    = _RED if pct > 100 else (_GOLD if pct >= 80 else _GREEN)
        oh_lbl   = f" + {t['oh']:.0f}h OH" if t["oh"] > 0 else ""
        sub_lbl  = (f"{t['enh']+t['iss']:.0f}h story{oh_lbl} / {t['rem']*len(devs):.0f}h left"
                    if is_m0 else f"{t['enh']+t['iss']:.0f}h story{oh_lbl}")
        total_cells.append(html.Div([
            html.Div(f"{pct}%", style={
                "fontSize": "18px", "fontWeight": "700", "color": pct_c,
            }),
            html.Div(sub_lbl, style={"fontSize": "12px", "color": "#6b7280"}),
        ], style={
            "padding": "16px",
            "borderLeft": "1px solid rgba(255,255,255,0.05)",
        }))

    total_row = html.Div(total_cells, style={
        "display": "grid", "gridTemplateColumns": cols,
        "background": "rgba(255,255,255,0.02)",
    })

    return html.Div([banner_row, col_hdr, *dev_rows, total_row])


def _render_rest_grid(cap_data, devs, view):
    rest_months = [
        (f"2026-{m:02d}", date(2026, m, 1).strftime("%b"))
        for m in range(7, 13)
    ]
    cols = "180px " + " ".join(["1fr"] * 6)

    hdr = html.Div([
        html.Div("DEVELOPER", style={
            "padding": "8px 16px", "fontSize": "10px", "color": "#4b5563",
            "textTransform": "uppercase", "letterSpacing": "1px", "fontWeight": "700",
            "borderBottom": "1px solid rgba(255,255,255,0.07)",
        }),
        *[html.Div(lbl, style={
            "padding": "8px", "textAlign": "center",
            "fontSize": "12px", "color": "#6b7280",
            "borderBottom": "1px solid rgba(255,255,255,0.07)",
        }) for _, lbl in rest_months],
    ], style={"display": "grid", "gridTemplateColumns": cols})

    rows = []
    for dev in devs:
        cells = [html.Div([
            html.Div(dev["name"], style={"fontWeight": "600", "fontSize": "13px", "color": "#e2e8f0"}),
            html.Div(dev.get("role", ""), style={"fontSize": "11px", "color": "#6b7280"}),
        ], style={"padding": "12px 16px"})]

        for ym_str, _ in rest_months:
            enh_h = cap_data.get((dev["name"], ym_str, "enhancement"), {}).get("estimated_hours", 0.0)
            iss_h = cap_data.get((dev["name"], ym_str, "bug"),          {}).get("estimated_hours", 0.0)
            if view == "Enhancements": iss_h = 0.0
            elif view == "Issues":     enh_h = 0.0
            total = enh_h + iss_h
            cap   = dev["capacity_h"]
            pct   = round(total / cap * 100) if cap > 0 else 0
            pct_c = _RED if pct > 100 else (_GOLD if pct >= 80 else _GREEN)
            cells.append(html.Div([
                html.Div(f"{pct}%", style={
                    "fontSize": "16px", "fontWeight": "700",
                    "color": pct_c, "textAlign": "center",
                }),
                html.Div(f"{total:.0f}h", style={
                    "fontSize": "11px", "color": "#6b7280", "textAlign": "center",
                }),
            ], style={
                "padding": "12px 8px",
                "borderLeft": "1px solid rgba(255,255,255,0.05)",
            }))

        rows.append(html.Div(cells, style={
            "display": "grid", "gridTemplateColumns": cols,
            "borderBottom": "1px solid rgba(255,255,255,0.05)",
        }))

    return html.Div([hdr, *rows])


# ── Gantt ─────────────────────────────────────────────────────────────────────

def _render_gantt(show_all):
    from data.loader import engine as _engine
    from sqlalchemy import text as _text

    gantt_months = [
        (f"2026-{m:02d}", date(2026, m, 1).strftime("%b"))
        for m in range(4, 13)
    ]
    cur_ym = date.today().strftime("%Y-%m")
    cols   = "240px " + " ".join(["1fr"] * 9)

    try:
        with _engine.connect() as _conn:
            _rows = _conn.execute(_text(
                "SELECT title, original_estimate, t_done, t_rem, has_tasks, bar_end "
                "FROM agg_gantt_items WHERE item_type = 'enh' ORDER BY bar_end"
            )).fetchall()
    except Exception:
        _rows = []

    rows_data = []
    for row in _rows:
        h = float((row.t_done or 0) + (row.t_rem or 0)) if row.has_tasks else float(row.original_estimate or 0)
        sz = _size(h)
        if not show_all and sz == "Small":
            continue
        try:
            rdm = pd.Timestamp(row.bar_end).strftime("%Y-%m")
        except Exception:
            continue
        if rdm < "2026-04" or rdm > "2026-12":
            continue
        rows_data.append({
            "title": str(row.title or ""), "eff_h": h, "size": sz, "rdm": rdm,
        })

    if not rows_data:
        return html.Div(
            "No Big or Medium enhancements with Apr–Dec 2026 release dates.",
            style={
                "color": "#4b5563", "padding": "20px", "fontSize": "13px",
                "background": _CARD, "border": f"1px solid {_BORDER}",
                "borderRadius": "14px", "marginTop": "28px",
            },
        )

    rows_data.sort(key=lambda r: (r["rdm"], 0 if r["size"] == "Big" else 1))
    big_ct = sum(1 for r in rows_data if r["size"] == "Big")
    med_ct = sum(1 for r in rows_data if r["size"] == "Medium")

    hdr_cells = [html.Div("ENHANCEMENT", style={
        "padding": "8px 12px", "fontSize": "10px", "color": "#4b5563",
        "textTransform": "uppercase", "letterSpacing": "1px", "fontWeight": "700",
    })]
    for ym_str, lbl in gantt_months:
        is_cur = ym_str == cur_ym
        hdr_cells.append(html.Div([
            html.Span(lbl),
            html.Span(" ◄", style={"color": _GOLD, "fontSize": "9px"}) if is_cur else html.Span(),
        ], style={
            "padding": "8px 6px", "textAlign": "center", "fontSize": "12px",
            "color": _GOLD if is_cur else "#6b7280",
            "fontWeight": "600" if is_cur else "400",
        }))

    data_rows = []
    for i, r in enumerate(rows_data):
        bg     = "rgba(255,255,255,0.02)" if i % 2 == 0 else "transparent"
        is_big = r["size"] == "Big"
        p_bg   = "rgba(248,113,113,0.15)" if is_big else "rgba(251,191,36,0.12)"
        p_clr  = _RED if is_big else _GOLD
        p_bdr  = "rgba(248,113,113,0.25)" if is_big else "rgba(251,191,36,0.2)"
        title_txt = (r["title"][:40] + "…") if len(r["title"]) > 40 else r["title"]

        row_cells = [html.Div([
            html.Span("● ", style={"color": p_clr, "fontSize": "8px"}),
            html.Span(title_txt, style={"fontSize": "12px", "color": "#c8c8e0"}),
        ], style={
            "padding": "10px 12px", "background": bg,
            "display": "flex", "alignItems": "center",
        })]

        for ym_str, _ in gantt_months:
            if r["rdm"] == ym_str:
                row_cells.append(html.Div(
                    html.Span(r["size"].upper(), style={
                        "fontSize": "10px", "fontWeight": "700", "color": p_clr,
                        "padding": "3px 12px", "background": p_bg,
                        "border": f"1px solid {p_bdr}", "borderRadius": "4px",
                    }),
                    style={
                        "padding": "10px 6px", "background": bg,
                        "display": "flex", "alignItems": "center",
                        "justifyContent": "center",
                    },
                ))
            else:
                row_cells.append(html.Div(style={"background": bg}))

        data_rows.append(html.Div(row_cells, style={
            "display": "grid", "gridTemplateColumns": cols,
        }))

    legend = html.Div([
        html.Span([html.Span("■ ", style={"color": _RED}), "Big"], style={
            "marginRight": "16px", "fontSize": "12px", "color": "#6b7280",
        }),
        html.Span([html.Span("■ ", style={"color": _GOLD}), "Medium"], style={
            "marginRight": "16px", "fontSize": "12px", "color": "#6b7280",
        }),
        html.Span("Big: 120–160h · Medium: 40–80h",
                  style={"fontSize": "12px", "color": "#4b5563"}),
    ], style={"display": "flex", "alignItems": "center", "marginTop": "16px"})

    return html.Div([
        html.Div([
            html.Div([
                html.Div("Big & Medium Enhancements · Apr – Dec 2026", style={
                    "fontSize": "15px", "fontWeight": "700", "color": "#e2e8f0",
                }),
                html.Div(f"{big_ct} Big, {med_ct} Medium", style={
                    "fontSize": "12px", "color": "#6b7280", "marginTop": "4px",
                }),
            ]),
            html.Button(
                ["○  ", "Show All Sizes" if not show_all else "Big & Medium Only"],
                id="dcap-gantt-toggle", n_clicks=0,
                style={
                    "background": "transparent",
                    "border": "1px solid rgba(251,191,36,0.3)",
                    "color": _GOLD, "borderRadius": "6px",
                    "padding": "6px 14px", "fontSize": "12px", "cursor": "pointer",
                },
            ),
        ], style={
            "display": "flex", "justifyContent": "space-between",
            "alignItems": "flex-start", "marginBottom": "20px",
        }),
        html.Div(hdr_cells, style={"display": "grid", "gridTemplateColumns": cols}),
        html.Div(data_rows),
        legend,
    ], style={
        "background": _CARD, "border": f"1px solid {_BORDER}",
        "borderRadius": "14px", "padding": "24px", "marginTop": "28px",
    })


# ── Function Timeline ────────────────────────────────────────────────────────

_SIZE_CLR = {
    "Big":    (_RED,  "rgba(248,113,113,0.15)", "rgba(248,113,113,0.3)"),
    "Medium": (_GOLD, "rgba(251,191,36,0.12)",  "rgba(251,191,36,0.25)"),
    "Small":  (_BLU,  "rgba(129,140,248,0.12)", "rgba(129,140,248,0.25)"),
}

_SIZE_ORDER = {"Big": 0, "Medium": 1, "Small": 2}


def _render_function_timeline(size_filter="All"):
    from data.loader import engine as _engine
    from sqlalchemy import text as _text

    timeline_months = [
        (f"2026-{m:02d}", date(2026, m, 1).strftime("%b"))
        for m in range(4, 13)
    ]
    cur_ym = date.today().strftime("%Y-%m")
    cols   = "200px " + " ".join(["1fr"] * 9)

    try:
        with _engine.connect() as _conn:
            _rows = _conn.execute(_text(
                "SELECT work_item_id, title, function, original_estimate, "
                "       t_done, t_rem, has_tasks, bar_end "
                "FROM agg_gantt_items WHERE item_type = 'enh' "
                "  AND function IS NOT NULL AND function != '' "
                "ORDER BY bar_end"
            )).fetchall()
    except Exception:
        _rows = []

    func_data: dict[str, dict] = {}
    for row in _rows:
        func = str(row.function or "").strip()
        if not func or func == "Not Specified":
            continue
        h = float((row.t_done or 0) + (row.t_rem or 0)) if row.has_tasks else float(row.original_estimate or 0)
        if h == 0:
            continue
        sz = _size(h)
        if size_filter != "All" and sz != size_filter:
            continue
        try:
            rdm = pd.Timestamp(row.bar_end).strftime("%Y-%m")
        except Exception:
            continue
        if rdm < "2026-04" or rdm > "2026-12":
            continue
        if func not in func_data:
            func_data[func] = {ym: [] for ym, _ in timeline_months}
        func_data[func][rdm].append({
            "id": int(row.work_item_id), "title": str(row.title or ""), "size": sz, "h": h,
        })

    if not func_data:
        label = f"{size_filter} " if size_filter != "All" else ""
        return html.Div(
            f"No {label}enhancements with function tags and Apr–Dec 2026 release dates.",
            style={
                "color": "#4b5563", "padding": "20px", "fontSize": "13px",
            },
        )

    def _first_month(f):
        for ym, _ in timeline_months:
            if func_data[f][ym]:
                return ym
        return "9999-99"

    sorted_funcs = sorted(func_data.keys(), key=_first_month)

    hdr_cells = [html.Div("FUNCTION", style={
        "padding": "8px 12px", "fontSize": "10px", "color": "#4b5563",
        "textTransform": "uppercase", "letterSpacing": "1px", "fontWeight": "700",
        "borderBottom": "1px solid rgba(255,255,255,0.07)",
    })]
    for ym_str, lbl in timeline_months:
        is_cur = ym_str == cur_ym
        hdr_cells.append(html.Div([
            html.Span(lbl),
            html.Span(" ◄", style={"color": _GOLD, "fontSize": "9px"}) if is_cur else html.Span(),
        ], style={
            "padding": "8px 6px", "textAlign": "center", "fontSize": "12px",
            "color": _GOLD if is_cur else "#6b7280",
            "fontWeight": "600" if is_cur else "400",
            "borderBottom": "1px solid rgba(255,255,255,0.07)",
        }))

    data_rows = []
    for i, func in enumerate(sorted_funcs):
        row_bg = "rgba(255,255,255,0.02)" if i % 2 == 0 else "transparent"
        row_cells = [html.Div(func, style={
            "padding": "10px 12px", "fontSize": "13px", "fontWeight": "600",
            "color": "#e2e8f0", "background": row_bg,
            "borderBottom": "1px solid rgba(255,255,255,0.04)",
        })]
        for ym_str, _ in timeline_months:
            items = func_data[func][ym_str]
            if items:
                dom_sz  = min(items, key=lambda x: _SIZE_ORDER.get(x["size"], 9))["size"]
                clr, bg_clr, bdr_clr = _SIZE_CLR[dom_sz]
                cnt     = len(items)
                abbr    = {"Big": "BIG", "Medium": "MED", "Small": "SML"}[dom_sz]
                tag_txt = f"{cnt}× {abbr}" if cnt > 1 else abbr
                row_cells.append(html.Div(
                    html.Span(tag_txt, style={
                        "fontSize": "10px", "fontWeight": "700", "color": clr,
                        "padding": "3px 10px", "background": bg_clr,
                        "border": f"1px solid {bdr_clr}", "borderRadius": "4px",
                        "whiteSpace": "nowrap",
                    }),
                    style={
                        "padding": "8px 4px", "background": row_bg,
                        "display": "flex", "alignItems": "center",
                        "justifyContent": "center",
                        "borderBottom": "1px solid rgba(255,255,255,0.04)",
                    },
                ))
            else:
                row_cells.append(html.Div(
                    html.Div(style={
                        "height": "1px", "background": "rgba(255,255,255,0.04)",
                        "margin": "0 8px",
                    }),
                    style={
                        "background": row_bg, "display": "flex", "alignItems": "center",
                        "borderBottom": "1px solid rgba(255,255,255,0.04)",
                    },
                ))
        data_rows.append(html.Div(row_cells, style={
            "display": "grid", "gridTemplateColumns": cols,
        }))

    total = sum(len(v) for fd in func_data.values() for v in fd.values())
    return html.Div([
        html.Div(f"{len(sorted_funcs)} functions · {total} enhancements scheduled", style={
            "fontSize": "12px", "color": "#6b7280", "marginBottom": "12px",
        }),
        html.Div(hdr_cells, style={"display": "grid", "gridTemplateColumns": cols}),
        *data_rows,
    ])


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    today = date.today()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    sprint_meta = (
        f"{today.strftime('%b %Y')} · Sprint 1 · "
        f"Day {today.day} of {days_in_month} · Default: 180h/person"
    )

    return html.Div([
        dcc.Store(id="dcap-view",           data="All"),
        dcc.Store(id="dcap-tab",            data="012"),
        dcc.Store(id="dcap-gantt-show-all", data=False),
        dcc.Store(id="dcap-sel-dev",        data=None),
        dcc.Store(id="dcap-sel-month",      data=None),
        dcc.Store(id="dcap-func-size-filter", data="All"),
        dcc.Store(id="dcap-flt",              data={"pri": "all", "srt": "pri"}),

        # ── Top: VIEW filter (sticky) ─────────────────────────────────────────
        html.Div([
            # Work item type buttons
            html.Span("VIEW", style={
                "fontSize": "11px", "color": "#6b7280", "marginRight": "8px",
                "textTransform": "uppercase", "letterSpacing": "1px",
            }),
            html.Button("All Work",     id="dcap-btn-all", n_clicks=0,
                        className="dcap-view-btn dcap-view-active"),
            html.Button("Enhancements", id="dcap-btn-enh", n_clicks=0,
                        className="dcap-view-btn"),
            html.Button("Issues",       id="dcap-btn-iss", n_clicks=0,
                        className="dcap-view-btn"),

            # Divider
            html.Div(style={
                "width": "1px", "height": "16px",
                "background": "rgba(255,255,255,0.08)",
                "margin": "0 12px",
            }),

            # Customer / Internal radio buttons
            html.Span("TYPE", style={
                "fontSize": "11px", "color": "#6b7280", "marginRight": "8px",
                "textTransform": "uppercase", "letterSpacing": "1px",
            }),
            dcc.RadioItems(
                id="gantt-cust-filter",
                options=[
                    {"label": "All",      "value": "all"},
                    {"label": "Customer", "value": "Customer"},
                    {"label": "Internal", "value": "Internal"},
                ],
                value="all",
                inline=True,
                inputStyle={"marginRight": "5px", "cursor": "pointer", "accentColor": "#818cf8"},
                labelStyle={
                    "marginRight": "14px", "fontSize": "12px",
                    "color": "#c8c8e0", "cursor": "pointer",
                },
            ),

            # Legend (right-aligned)
            html.Div([
                html.Span("■ ", style={"color": _GOLD, "fontSize": "10px"}),
                html.Span("Enh  ", style={"fontSize": "12px", "color": "#8892a4"}),
                html.Span("■ ", style={"color": _GREEN, "fontSize": "10px"}),
                html.Span("Issues  ", style={"fontSize": "12px", "color": "#8892a4"}),
                html.Span("■ ", style={"color": "#a78bfa", "fontSize": "10px"}),
                html.Span("Overhead  ", style={"fontSize": "12px", "color": "#8892a4"}),
                html.Span("· Click any cell for month detail",
                          style={"fontSize": "12px", "color": "#4b5563"}),
            ], style={"marginLeft": "auto", "display": "flex", "alignItems": "center"}),
        ], style={
            "display": "flex", "alignItems": "center",
            "position": "sticky", "top": "0", "zIndex": "20",
            "background": "#0f0f1a",
            "paddingTop": "8px", "paddingBottom": "8px",
            "marginBottom": "6px",
            "boxShadow": "0 4px 20px rgba(0,0,0,0.45)",
        }),

        html.Div(sprint_meta, style={
            "textAlign": "right", "fontSize": "11px",
            "color": "#4b5563", "marginBottom": "20px",
        }),

        # ── Breadcrumb + title ────────────────────────────────────────────────
        html.Div([
            html.Span("DEVELOPER CAPACITY", style={
                "color": _GOLD, "fontSize": "11px",
                "letterSpacing": "1.5px", "fontWeight": "600",
            }),
            html.Span(" · SPRINT ALLOCATION", style={
                "color": "#4b5563", "fontSize": "11px", "letterSpacing": "1.5px",
            }),
        ], style={"marginBottom": "8px"}),
        html.H2("Developer Capacity & Work Allocation", style={
            "fontSize": "22px", "fontWeight": "700",
            "color": "#e2e8f0", "marginBottom": "4px", "marginTop": "0",
        }),
        html.Div(id="dcap-subtitle", style={
            "fontSize": "13px", "color": "#8892a4", "marginBottom": "24px",
        }),

        # ── KPI cards ─────────────────────────────────────────────────────────
        html.Div(id="dcap-kpis", style={"display": "flex", "gap": "12px", "marginBottom": "28px"}),

        # ── Tabbed grid panel ─────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Button("1+2 Planning · M0/M1/M2",
                            id="dcap-tab-012",  n_clicks=0,
                            className="dcap-subtab dcap-subtab-active"),
                html.Button("Rest of 2026",
                            id="dcap-tab-rest", n_clicks=0,
                            className="dcap-subtab"),
            ], style={
                "display": "flex",
                "borderBottom": "1px solid rgba(255,255,255,0.08)",
                "marginBottom": "20px",
            }),
            html.Div(id="dcap-grid"),
        ], style={
            "background": _CARD, "border": f"1px solid {_BORDER}",
            "borderRadius": "14px", "padding": "24px",
        }),

        # ── Gantt ─────────────────────────────────────────────────────────────
        html.Div(id="dcap-gantt"),

        # ── Standalone Task Overhead ──────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("STANDALONE TASK OVERHEAD", style={
                    "fontSize": "9px", "fontWeight": "700", "color": "#a78bfa",
                    "letterSpacing": "1.6px", "textTransform": "uppercase",
                    "marginBottom": "6px",
                }),
                html.Div("Tasks not linked to any story or bug · Dev & Mobile team", style={
                    "fontSize": "22px", "fontWeight": "700", "color": "#e2e8f0",
                    "marginBottom": "4px",
                }),
                html.Div(
                    "Classified by keyword rules + Ollama llama3.2:3b · "
                    "Re-classified on every ADO sync · Purple bar = overhead",
                    style={"fontSize": "12px", "color": "#6b7280"},
                ),
            ], style={"marginBottom": "20px"}),
            html.Div(id="dcap-overhead"),
        ], style={
            "background": _CARD, "border": "1px solid rgba(167,139,250,0.2)",
            "borderRadius": "14px", "padding": "24px", "marginTop": "28px",
        }),

        # ── Function Delivery Timeline ────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div([
                    html.Div("Function Delivery Timeline · Apr – Dec 2026", style={
                        "fontSize": "15px", "fontWeight": "700", "color": "#e2e8f0",
                    }),
                    html.Div("Enhancements grouped by product function", style={
                        "fontSize": "12px", "color": "#6b7280", "marginTop": "4px",
                    }),
                ]),
                html.Div([
                    html.Span("SIZE", style={
                        "fontSize": "10px", "color": "#6b7280", "marginRight": "10px",
                        "textTransform": "uppercase", "letterSpacing": "1px",
                    }),
                    html.Button("All",    id="dcap-func-sz-all",    n_clicks=0,
                                className="dcap-view-btn dcap-view-active"),
                    html.Button("Big",    id="dcap-func-sz-big",    n_clicks=0,
                                className="dcap-view-btn"),
                    html.Button("Medium", id="dcap-func-sz-medium", n_clicks=0,
                                className="dcap-view-btn"),
                    html.Button("Small",  id="dcap-func-sz-small",  n_clicks=0,
                                className="dcap-view-btn"),
                ], style={"display": "flex", "alignItems": "center"}),
            ], style={
                "display": "flex", "justifyContent": "space-between",
                "alignItems": "flex-start", "marginBottom": "20px",
            }),
            html.Div(id="dcap-func-timeline"),
        ], style={
            "background": _CARD, "border": f"1px solid {_BORDER}",
            "borderRadius": "14px", "padding": "24px", "marginTop": "28px",
        }),

        # ── Detail panel (Offcanvas) ───────────────────────────────────────────
        dbc.Offcanvas(
            id="dcap-panel",
            placement="end",
            is_open=False,
            title="",
            style={
                "width": "560px",
                "background": "#0f0f1e",
                "borderLeft": "1px solid rgba(255,255,255,0.1)",
            },
            children=html.Div(id="dcap-panel-body"),
        ),

        # ── Footer ────────────────────────────────────────────────────────────
        html.Div([
            html.Span(
                f"ExpenseOnDemand · Planning Tool v1 · {today.strftime('%b %Y')}",
                style={"color": "#2d3748"},
            ),
            html.Span(
                "Default: 180h/person · VSTS: expenseondemand / Solo Expenses",
                style={"color": "#2d3748", "marginLeft": "auto"},
            ),
        ], style={
            "display": "flex", "fontSize": "11px",
            "borderTop": "1px solid rgba(255,255,255,0.05)",
            "paddingTop": "16px", "marginTop": "32px",
        }),
    ], style={"padding": "24px 28px"})


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("dcap-view",    "data"),
    Output("dcap-btn-all", "className"),
    Output("dcap-btn-enh", "className"),
    Output("dcap-btn-iss", "className"),
    Input("dcap-btn-all", "n_clicks"),
    Input("dcap-btn-enh", "n_clicks"),
    Input("dcap-btn-iss", "n_clicks"),
    prevent_initial_call=True,
)
def _set_view(a, e, i):
    trig   = ctx.triggered_id
    active = "dcap-view-btn dcap-view-active"
    base   = "dcap-view-btn"
    if trig == "dcap-btn-all": return "All",          active, base,   base
    if trig == "dcap-btn-enh": return "Enhancements", base,   active, base
    if trig == "dcap-btn-iss": return "Issues",        base,   base,   active
    return no_update, no_update, no_update, no_update


@callback(
    Output("dcap-tab",      "data"),
    Output("dcap-tab-012",  "className"),
    Output("dcap-tab-rest", "className"),
    Input("dcap-tab-012",  "n_clicks"),
    Input("dcap-tab-rest", "n_clicks"),
    prevent_initial_call=True,
)
def _set_tab(a, b):
    trig = ctx.triggered_id
    act  = "dcap-subtab dcap-subtab-active"
    base = "dcap-subtab"
    if trig == "dcap-tab-012":  return "012",  act,  base
    if trig == "dcap-tab-rest": return "rest", base, act
    return no_update, no_update, no_update


@callback(
    Output("dcap-gantt-show-all", "data"),
    Input("dcap-gantt-toggle", "n_clicks"),
    State("dcap-gantt-show-all", "data"),
    prevent_initial_call=True,
)
def _toggle_gantt(n, current):
    return not bool(current)


@callback(
    Output("dcap-func-size-filter",  "data"),
    Output("dcap-func-sz-all",       "className"),
    Output("dcap-func-sz-big",       "className"),
    Output("dcap-func-sz-medium",    "className"),
    Output("dcap-func-sz-small",     "className"),
    Input("dcap-func-sz-all",    "n_clicks"),
    Input("dcap-func-sz-big",    "n_clicks"),
    Input("dcap-func-sz-medium", "n_clicks"),
    Input("dcap-func-sz-small",  "n_clicks"),
    prevent_initial_call=True,
)
def _set_func_size(a, b, m, s):
    trig   = ctx.triggered_id
    active = "dcap-view-btn dcap-view-active"
    base   = "dcap-view-btn"
    mapping = {
        "dcap-func-sz-all":    ("All",    active, base,   base,   base),
        "dcap-func-sz-big":    ("Big",    base,   active, base,   base),
        "dcap-func-sz-medium": ("Medium", base,   base,   active, base),
        "dcap-func-sz-small":  ("Small",  base,   base,   base,   active),
    }
    if trig in mapping:
        return mapping[trig]
    return no_update, no_update, no_update, no_update, no_update


@callback(
    Output("dcap-func-timeline", "children"),
    Input("dcap-func-size-filter", "data"),
)
def _render_func_timeline(size_filter):
    return _render_function_timeline(size_filter or "All")


@callback(
    Output("dcap-kpis",     "children"),
    Output("dcap-grid",     "children"),
    Output("dcap-gantt",    "children"),
    Output("dcap-subtitle", "children"),
    Output("dcap-overhead", "children"),
    Input("dcap-view",           "data"),
    Input("dcap-tab",            "data"),
    Input("dcap-gantt-show-all", "data"),
    Input("gantt-cust-filter",   "value"),
)
def _render(view, tab, show_all, cust_filter):
    cust_filter = cust_filter or "all"
    cust_key = {"customer": "Customer", "internal": "Internal"}.get(cust_filter.lower(), "All")

    # ── Cache check ───────────────────────────────────────────────────────────
    from data.loader import get_ui_cache_bust
    bust = get_ui_cache_bust()
    cache_key = (view, tab, bool(show_all), cust_key, bust)
    if cache_key in _RENDER_CACHE:
        _prune(bust)
        return _RENDER_CACHE[cache_key]
    # ─────────────────────────────────────────────────────────────────────────

    m012 = _months012()
    yms  = [_ym(d) for d in m012]
    lbls = [d.strftime("%b") for d in m012]
    devs = DEVELOPERS

    fy_months = [f"2026-{m:02d}" for m in range(4, 13)]
    all_yms   = list(dict.fromkeys([*yms, *fy_months]))  # M012 first, then rest, deduped

    # Task-based capacity + item lists (replaces story-level pre-computed tables)
    cap_data, top_items = _load_task_dev_data(all_yms, cust_key)

    # Load standalone overhead + leave data
    standalone_data = _load_standalone_data(yms)
    try:
        from db.leaves import get_leave_capacity
        leave_data = get_leave_capacity(yms)
    except Exception:
        leave_data = {"leaves": {}, "holidays": {}}

    # KPIs — read from pre-computed table
    m0_cap = sum(d["capacity_h"] for d in devs)
    m0_enh = sum(
        cap_data.get((d["name"], yms[0], "enhancement"), {}).get("estimated_hours", 0.0)
        for d in devs
    )
    m0_iss = sum(
        cap_data.get((d["name"], yms[0], "bug"), {}).get("estimated_hours", 0.0)
        for d in devs
    )
    m0_oh  = sum(
        standalone_data.get(d["name"], {}).get(yms[0], {}).get("total_h", 0.0)
        for d in devs
    )

    fy_cap       = m0_cap * 9
    fy_committed = sum(
        cap_data.get((d["name"], ym, it), {}).get("estimated_hours", 0.0)
        for d in devs
        for ym in fy_months
        for it in ("enhancement", "bug")
    )
    fy_free = max(fy_cap - fy_committed, 0.0)

    oh_pct   = round(m0_oh / m0_cap * 100) if m0_cap else 0
    feat_pct = round((m0_enh + m0_iss) / m0_cap * 100) if m0_cap else 0

    kpis = [
        _kpi(f"{m0_cap:,}h",          "M0 Capacity",        f"180h × {len(devs)} devs", _GOLD),
        _kpi(f"{m0_enh:,.0f}h",       "M0 Enhancements",    f"{m0_enh/m0_cap*100:.0f}% of M0" if m0_cap else "—", _GREEN),
        _kpi(f"{m0_iss:,.0f}h",       "M0 Issues",          f"{m0_iss/m0_cap*100:.0f}% of M0" if m0_cap else "—", _GOLD),
        _kpi(f"{m0_oh:,.0f}h",        "M0 Overhead",        f"{oh_pct}% standalone tasks", "#a78bfa"),
        _kpi(f"{feat_pct}%",          "Feature Work",        f"{oh_pct}% overhead · {100-feat_pct-oh_pct}% unallocated", _GREEN),
        _kpi(f"{fy_free:,.0f}h",      "Full Year Free",      f"{fy_free/fy_cap*100:.0f}% headroom" if fy_cap else "—", _GREEN),
    ]

    grid     = _render_m012_grid(cap_data, top_items, devs, yms, lbls, view, standalone_data, leave_data) if tab == "012" \
               else _render_rest_grid(cap_data, devs, view)
    gantt    = _render_gantt(bool(show_all))
    sub      = (f"{len(devs)} developers · 180h default monthly capacity · "
                "Click any cell for M0/M1/M2 detail · Purple bar = standalone overhead · "
                "ℹ M0/M1/M2 = iteration months (sprint cadence), not release dates")
    overhead = _render_overhead_section(standalone_data, devs, yms[0])

    result = kpis, grid, gantt, sub, overhead
    _RENDER_CACHE[cache_key] = result
    _prune(bust)
    return result


@callback(
    Output("dcap-panel",     "is_open"),
    Output("dcap-sel-dev",   "data"),
    Output("dcap-sel-month", "data"),
    Output("dcap-flt",       "data", allow_duplicate=True),
    Input({"type": "dcap-cell", "dev": ALL, "month": ALL}, "n_clicks"),
    State({"type": "dcap-cell", "dev": ALL, "month": ALL}, "id"),
    prevent_initial_call=True,
)
def _open_panel(clicks, ids):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    # Guard: n_clicks=0 means initial mount / navigation artifact, not a real click
    click_val = next((c for c, i in zip(clicks, ids) if i == tid), 0)
    if not click_val:
        raise PreventUpdate
    return True, tid["dev"], tid["month"], {"pri": "all", "srt": "pri"}


@callback(
    Output("dcap-panel",     "is_open",  allow_duplicate=True),
    Output("dcap-sel-dev",   "data",     allow_duplicate=True),
    Output("dcap-sel-month", "data",     allow_duplicate=True),
    Input("url-location",    "pathname"),
    prevent_initial_call=True,
)
def _close_panel_on_navigate(_pathname):
    # Both /dev-capacity and /planning embed the same dcap-panel component.
    # React reuses the component between navigations, preserving is_open=True.
    # Explicitly reset on every URL change so the panel starts closed.
    return False, None, None


def _standalone_section(items: list, is_m0: bool) -> list:
    """Render standalone overhead task cards for the side panel."""
    if not items:
        return []

    _OH = "#a78bfa"
    total_h = sum(float(r.get("original_estimate") or 0) for r in items)
    label   = f"STANDALONE OVERHEAD · {total_h:.0f}h" + (" OPEN" if is_m0 else "")

    cards = []
    for r in sorted(items, key=lambda x: -float(x.get("original_estimate") or 0)):
        cat   = r.get("category", "Other")
        h     = float(r.get("original_estimate") or 0)
        meth  = r.get("method", "")
        tid   = r.get("task_id")
        title = r.get("title", f"#{tid}")
        cat_c = _CAT_CLR.get(cat, "#6b7280")

        method_badge = html.Span(
            "rules" if meth == "rules" else "AI",
            style={
                "fontSize": "9px", "fontWeight": "700",
                "color": "#0f0f1e" if meth == "rules" else "#e2e8f0",
                "background": "#34d399" if meth == "rules" else "#818cf8",
                "padding": "1px 5px", "borderRadius": "3px",
                "marginLeft": "6px", "letterSpacing": "0.5px",
            }
        )

        cards.append(
            html.A(
                href=f"{ADO_BASE_URL}{tid}", target="_blank",
                style={"textDecoration": "none", "display": "block", "marginBottom": "8px"},
                children=html.Div([
                    html.Div(title, style={
                        "fontSize": "13px", "color": "#e2e8f0",
                        "fontWeight": "600", "marginBottom": "6px", "lineHeight": "1.45",
                    }),
                    html.Div([
                        html.Span(cat, style={
                            "fontSize": "10px", "fontWeight": "700", "color": cat_c,
                            "background": f"{cat_c}22", "padding": "2px 7px",
                            "borderRadius": "4px", "marginRight": "6px",
                            "border": f"1px solid {cat_c}44",
                        }),
                        html.Span(f"{h:.0f}h", style={
                            "fontSize": "12px", "color": "#8892a4", "marginRight": "4px",
                        }),
                        method_badge,
                    ]),
                ], style={
                    "background": f"{_OH}08",
                    "border": f"1px solid {_OH}33",
                    "borderRadius": "8px", "padding": "10px 12px",
                })
            )
        )

    return [
        html.Div(label, style={
            "fontSize": "10px", "color": _OH, "fontWeight": "700",
            "textTransform": "uppercase", "letterSpacing": "1px",
            "margin": "16px 0 8px",
            "borderTop": "1px solid rgba(255,255,255,0.07)", "paddingTop": "14px",
        }),
        *cards,
    ]


@callback(
    Output("dcap-panel-body", "children"),
    Input("dcap-sel-dev",   "data"),
    Input("dcap-sel-month", "data"),
    Input("dcap-view",      "data"),
    Input("dcap-flt",       "data"),
    prevent_initial_call=True,
)
def _panel_body(dev_name, ym_str, view, flt):
    if not dev_name or not ym_str:
        return html.Div("Select a cell")

    from data.loader import engine as _engine
    from sqlalchemy import text as _text

    dev = DEV_MAP.get(dev_name, {"name": dev_name, "capacity_h": 180, "role": ""})
    cap = dev["capacity_h"]

    try:
        mo_date  = date(int(ym_str[:4]), int(ym_str[5:7]), 1)
        mo_label = mo_date.strftime("%B %Y")
        today    = date.today()
        mo_idx   = (mo_date.year - today.year) * 12 + (mo_date.month - today.month)
        mo_tag   = f"M{mo_idx}" if 0 <= mo_idx <= 2 else mo_date.strftime("%b")
    except Exception:
        mo_label, mo_tag, mo_idx = ym_str, "", 999

    is_m0 = (mo_idx == 0)
    mn    = int(ym_str[5:7]) if len(ym_str) >= 7 else None

    # Load open items via task assignments (task-based — matches who actually has work)
    open_items: list[dict] = []
    if mn:
        try:
            iter_pat = f"%Iteration 2026 {mn:02d}-%"
            with _engine.connect() as _conn:
                _rows = _conn.execute(_text("""
                    SELECT
                        w.work_item_id,
                        w.title,
                        w.work_item_type,
                        w.priority,
                        COALESCE(w.iteration_path, '') AS iteration_path,
                        COALESCE(w.release_date,   '') AS release_date,
                        CASE
                            WHEN ta.task_h IS NOT NULL THEN ta.task_h
                            ELSE COALESCE(
                                w.remaining_work,
                                GREATEST(COALESCE(w.original_estimate,0) - COALESCE(w.completed_work,0), 0)
                            )
                        END AS dev_h,
                        COALESCE(td.done_count, 0) AS done_task_count
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
                    LEFT JOIN (
                        SELECT parent_id, COUNT(*) AS done_count
                        FROM work_items_main
                        WHERE work_item_type = 'Task'
                          AND main_developer  = :dev
                          AND iteration_path  LIKE :pat
                          AND state IN ('Closed','Resolved','Dev Complete',
                                        'Not Required','Not an issue')
                        GROUP BY parent_id
                    ) td ON td.parent_id = w.work_item_id
                    WHERE w.work_item_type IN ('Enhancement','User Story','Issue','Bug')
                      AND w.state NOT IN (
                          'Closed','Resolved','Not Required','Not an issue',
                          'No Customer Response','Not Specified','Userstory Update'
                      )
                      AND (
                          ta.parent_id IS NOT NULL
                          OR td.parent_id IS NOT NULL
                          OR (
                              w.main_developer = :dev
                              AND w.iteration_path LIKE :pat
                              AND NOT EXISTS (
                                  SELECT 1 FROM work_items_main tx
                                  WHERE tx.parent_id = w.work_item_id AND tx.work_item_type = 'Task'
                              )
                          )
                      )
                    GROUP BY w.work_item_id, w.title, w.work_item_type, w.priority,
                             w.iteration_path, w.release_date,
                             w.remaining_work, w.original_estimate, w.completed_work,
                             ta.task_h, td.done_count
                """), {"dev": dev_name, "pat": iter_pat}).fetchall()
            for r in _rows:
                open_items.append({
                    "id":            int(r.work_item_id),
                    "title":         str(r.title or ""),
                    "type":          str(r.work_item_type or "Enhancement"),
                    "dev_h":         float(r.dev_h or 0),
                    "priority":      int(float(r.priority)) if r.priority else 4,
                    "done_tasks":    int(r.done_task_count or 0),
                    "iteration_path": str(r.iteration_path or ""),
                    "release_date":  str(r.release_date or ""),
                })
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("panel items query failed: %s", exc)

    done_items: list[dict] = []  # done items not tracked in agg_gantt_items

    # Standalone tasks for this dev + month
    try:
        from db.standalone import load_all_classifications
        _all_sa = load_all_classifications()
        standalone_items = [
            r for r in _all_sa
            if str(r.get("assigned_to", "")).split(" <")[0].strip() == dev_name
            and _iter_ym(r.get("iteration_path", "")) == ym_str
        ]
    except Exception:
        standalone_items = []

    def _filter_view(items):
        if view == "Enhancements": return [i for i in items if IS_ENH(i["type"])]
        if view == "Issues":       return [i for i in items if IS_ISSUE(i["type"])]
        return items

    all_display  = _filter_view(open_items)

    # Three-bucket classification
    todo_display  = [i for i in all_display if i["dev_h"] > 0]
    done_display  = [i for i in all_display if i["dev_h"] == 0 and i.get("done_tasks", 0) > 0]
    noest_display = [i for i in all_display if i["dev_h"] == 0 and i.get("done_tasks", 0) == 0]

    open_enh = [i for i in todo_display if IS_ENH(i["type"])]
    open_iss = [i for i in todo_display if IS_ISSUE(i["type"])]
    enh_h    = sum(i["dev_h"] for i in open_enh)
    iss_h    = sum(i["dev_h"] for i in open_iss)

    # Apply filter / sort for display (KPI totals use unfiltered open_enh/open_iss)
    _flt  = flt or {"pri": "all", "srt": "pri"}
    _pri  = _flt.get("pri", "all")
    _srt  = _flt.get("srt", "pri")
    if _pri != "all":
        _p = int(_pri[1]) if len(_pri) == 2 and _pri[1].isdigit() else 99
        open_enh = [i for i in open_enh if i.get("priority", 4) == _p]
        open_iss = [i for i in open_iss if i.get("priority", 4) == _p]
    if _srt == "hours":
        open_enh = sorted(open_enh, key=lambda x: -x["dev_h"])
        open_iss = sorted(open_iss, key=lambda x: -x["dev_h"])
    elif _srt == "rd":
        open_enh = sorted(open_enh, key=lambda x: (x.get("release_date") or "zzz", x["id"]))
        open_iss = sorted(open_iss, key=lambda x: (x.get("release_date") or "zzz", x["id"]))
    else:  # pri (default)
        open_enh = sorted(open_enh, key=lambda x: (x.get("priority", 4), x["id"]))
        open_iss = sorted(open_iss, key=lambda x: (x.get("priority", 4), x["id"]))

    remaining_h = _remaining_workday_hours(ym_str) if is_m0 else None
    display_cap = remaining_h if (is_m0 and remaining_h) else cap
    oh_h        = sum(float(r.get("original_estimate") or 0) for r in standalone_items)
    free_h      = max(display_cap - enh_h - iss_h - oh_h, 0.0)
    ew          = min(enh_h / display_cap * 100, 100) if display_cap > 0 else 0
    iw          = min(iss_h / display_cap * 100, 100) if display_cap > 0 else 0
    ow          = min(oh_h  / display_cap * 100, 100) if display_cap > 0 else 0

    _sz_clrs = {
        "Big":    ("rgba(248,113,113,0.15)", _RED),
        "Medium": ("rgba(251,191,36,0.12)",  _GOLD),
        "Small":  ("rgba(129,140,248,0.12)", _BLU),
    }
    _p_bgs = {
        1: "rgba(248,113,113,0.15)",
        2: "rgba(251,191,36,0.12)",
        3: "rgba(129,140,248,0.12)",
    }

    def _item_card(item, show_size, dimmed=False):
        prio      = item.get("priority", 4)
        p_clr     = _prio_clr(prio)
        p_bg      = _p_bgs.get(int(prio) if str(prio).isdigit() else 4, "rgba(100,116,139,0.15)")
        title_txt = item["title"]
        item_id   = item["id"]
        rel_date  = item.get("release_date", "")

        badges = [
            html.Span(f"#{item_id}", style={
                "fontSize": "10px", "fontWeight": "600", "color": "#64748b",
                "marginRight": "8px", "fontFamily": "monospace",
            }),
            html.Span(f"P{prio}", style={
                "fontSize": "10px", "fontWeight": "700", "color": p_clr,
                "background": p_bg, "padding": "2px 6px",
                "borderRadius": "4px", "marginRight": "6px",
            }),
        ]
        if show_size:
            sz     = _size(item["dev_h"])
            s_bg, s_tc = _sz_clrs.get(sz, _sz_clrs["Small"])
            badges.append(html.Span(sz, style={
                "fontSize": "10px", "fontWeight": "700", "color": s_tc,
                "background": s_bg, "padding": "2px 6px",
                "borderRadius": "4px", "marginRight": "6px",
            }))
        badges.append(html.Span(f"{item['dev_h']:.0f}h",
                                style={"fontSize": "12px", "color": "#8892a4"}))
        if rel_date:
            badges.append(html.Span(rel_date, style={
                "fontSize": "10px", "fontWeight": "600",
                "color": "rgb(6,182,212)",
                "background": "rgba(6,182,212,0.10)",
                "border": "1px solid rgba(6,182,212,0.25)",
                "borderRadius": "4px", "padding": "1px 6px", "marginLeft": "6px",
            }))
        if dimmed:
            badges.append(html.Span("✓", style={
                "fontSize": "11px", "color": "#34d399", "marginLeft": "6px", "fontWeight": "700",
            }))

        return html.A(
            href=f"{ADO_BASE_URL}{item_id}", target="_blank",
            style={"textDecoration": "none", "display": "block", "marginBottom": "8px",
                   "opacity": "0.45" if dimmed else "1"},
            children=html.Div([
                html.Div(title_txt, style={
                    "fontSize": "13px", "color": "#e2e8f0",
                    "fontWeight": "600", "marginBottom": "6px", "lineHeight": "1.45",
                }),
                html.Div(badges, style={"display": "flex", "flexWrap": "wrap",
                                        "alignItems": "center", "gap": "2px"}),
            ], style={
                "background": "rgba(255,255,255,0.03)", "borderRadius": "8px",
                "padding": "10px 12px", "border": "1px solid rgba(255,255,255,0.06)",
                "cursor": "pointer",
            })
        )

    # ── Open items sections ───────────────────────────────────────────────────
    enh_section, iss_section = [], []
    if open_enh:
        lbl = f"ENHANCEMENTS · {enh_h:.0f}h" + (" OPEN" if is_m0 else "")
        enh_section = [
            html.Div(lbl, style={
                "fontSize": "10px", "color": _GREEN, "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "1px", "margin": "12px 0 8px",
            }),
            *[_item_card(i, True) for i in open_enh],
        ]
    if open_iss:
        lbl = f"ISSUE RESOLUTION · {iss_h:.0f}h" + (" OPEN" if is_m0 else "")
        iss_section = [
            html.Div(lbl, style={
                "fontSize": "10px", "color": _RED, "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "1px", "margin": "12px 0 8px",
            }),
            *[_item_card(i, False) for i in open_iss],
        ]

    # ── Done section (collapsed) ──────────────────────────────────────────────
    done_section = []
    if done_display:
        done_section = [html.Details([
            html.Summary(
                f"✓  COMPLETED  ·  {len(done_display)} items",
                style={"fontSize": "10px", "color": "#34d399", "fontWeight": "700",
                       "textTransform": "uppercase", "letterSpacing": "1px",
                       "cursor": "pointer", "margin": "16px 0 8px",
                       "listStyle": "none", "outline": "none"},
            ),
            *[_item_card(i, IS_ENH(i["type"]), dimmed=True)
              for i in sorted(done_display, key=lambda x: (x.get("iteration_path", ""), x.get("priority", 4)))],
        ])]

    # ── No-estimate section (collapsed) ──────────────────────────────────────
    noest_section = []
    if noest_display:
        noest_section = [html.Details([
            html.Summary(
                f"⚠  NEEDS ESTIMATION  ·  {len(noest_display)} items",
                style={"fontSize": "10px", "color": _GOLD, "fontWeight": "700",
                       "textTransform": "uppercase", "letterSpacing": "1px",
                       "cursor": "pointer", "margin": "16px 0 8px",
                       "listStyle": "none", "outline": "none"},
            ),
            *[_item_card(i, IS_ENH(i["type"]))
              for i in sorted(noest_display, key=lambda x: (x.get("iteration_path", ""), x.get("priority", 4)))],
        ])]

    total_open  = len(todo_display)
    header_tag  = "LIVE · CAPACITY DETAIL" if is_m0 else "CAPACITY DETAIL"
    cap_label   = f"Hours Left" if is_m0 else "Capacity"
    cap_val     = f"{display_cap:.0f}h"

    def _kpi_card(val, label, color):
        return html.Div([
            html.Div(val,   style={"fontSize": "36px", "fontWeight": "800", "color": color,
                                   "textAlign": "center", "lineHeight": "1"}),
            html.Div(label, style={"fontSize": "10px", "fontWeight": "700", "color": "#8892a4",
                                   "textTransform": "uppercase", "letterSpacing": "0.8px",
                                   "marginTop": "8px", "textAlign": "center"}),
        ], style={"flex": "1", "display": "flex", "flexDirection": "column",
                  "alignItems": "center", "justifyContent": "center",
                  "padding": "20px 6px", "borderRadius": "12px",
                  "background": f"{color}12", "border": f"1px solid {color}44",
                  "borderBottom": f"3px solid {color}"})

    return html.Div([
        html.Div(header_tag, style={
            "fontSize": "10px", "color": _GOLD if is_m0 else "#8892a4",
            "textTransform": "uppercase", "letterSpacing": "1.5px", "marginBottom": "4px",
        }),
        html.Div(dev_name, style={"fontSize": "16px", "fontWeight": "700", "color": "#e2e8f0"}),
        html.Div(f"{mo_tag} · {mo_label}", style={
            "fontSize": "12px", "color": "#8892a4", "marginBottom": "16px",
        }),
        html.Div([
            _kpi_card(cap_val,          cap_label,      _GOLD),
            _kpi_card(f"{enh_h:.0f}h", "Enhancements", _GREEN),
            _kpi_card(f"{iss_h:.0f}h", "Issues",        _RED),
            _kpi_card(f"{oh_h:.0f}h",  "Overhead",     "#a78bfa"),
            _kpi_card(f"{free_h:.0f}h","Free",          _BLU),
        ], style={"display": "flex", "gap": "8px", "marginBottom": "16px"}),
        html.Div([
            html.Div(style={"flex": str(max(ew, 0.01)),                    "background": _GREEN,    "height": "16px"}),
            html.Div(style={"flex": str(max(iw, 0.01)),                    "background": _RED,      "height": "16px"}),
            html.Div(style={"flex": str(max(ow, 0.01)),                    "background": "#a78bfa", "height": "16px"}),
            html.Div(style={"flex": str(max(100 - ew - iw - ow, 0.01)),   "background": "rgba(255,255,255,0.07)", "height": "16px"}),
        ], style={"display": "flex", "borderRadius": "8px", "overflow": "hidden", "marginBottom": "16px"}),
        html.Div(
            f"{total_open} OPEN ITEMS" + (f"  ·  {len(done_display)}✓  ·  {len(noest_display)}⚠" if (done_display or noest_display) else ""),
            style={"fontSize": "11px", "fontWeight": "700", "color": "#8892a4",
                   "textTransform": "uppercase", "letterSpacing": "1px", "marginBottom": "8px",
                   "borderTop": "1px solid rgba(255,255,255,0.07)", "paddingTop": "14px"},
        ),
        _ctrl_bar_dcap(_pri, _srt),
        *enh_section,
        *iss_section,
        *done_section,
        *noest_section,
        *_standalone_section(standalone_items, is_m0),
    ], style={"padding": "16px"})


# ── Dev-capacity panel filter / sort ─────────────────────────────────────────
@callback(
    Output("dcap-flt", "data", allow_duplicate=True),
    Input({"type": "dcap-flt-dd", "k": ALL}, "value"),
    State({"type": "dcap-flt-dd", "k": ALL}, "id"),
    State("dcap-flt", "data"),
    prevent_initial_call=True,
)
def _dcap_update_flt(values, dd_ids, current):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict) or tid.get("type") != "dcap-flt-dd":
        raise PreventUpdate
    flt = dict(current or {"pri": "all", "srt": "pri"})
    k   = tid["k"]
    val = next((v for v, i in zip(values, dd_ids) if i == tid), None)
    if val is None or flt.get(k) == val:
        raise PreventUpdate
    flt[k] = val
    return flt
