"""EOD — Delivery Timeline
Three views on one page:
  - Month Grid  : CEO-facing, one row per story, chip in the DELIVERY (release) month
  - Gantt Chart : Developer / function bar-chart from planning.py
  - Planning    : Dev load heatmap + release readiness + risk matrix
"""
import re
import dash
import pandas as pd
import time as _time_mod
from datetime import date
from dash import dcc, html, Input, Output, State, callback, ctx, no_update, ALL
from sqlalchemy import text as _text
import plotly.graph_objects as go

from data.loader import engine

dash.register_page(__name__, path="/delivery-timeline", name="Delivery Timeline")

# ── Colour tokens ─────────────────────────────────────────────────────────────
TXT = "var(--text-primary)"
MT  = "var(--text-secondary)"
BD  = "var(--border)"
EL  = "var(--bg-elevated)"
HV  = "var(--bg-hover)"
P   = "var(--purple)"

_SIZE_META: dict[str, dict] = {
    "Big":        {"abbr": "B",  "color": "#f59e0b", "bg": "rgba(245,158,11,0.15)",  "brd": "rgba(245,158,11,0.45)"},
    "Medium":     {"abbr": "M",  "color": "#84cc16", "bg": "rgba(132,204,22,0.15)",  "brd": "rgba(132,204,22,0.45)"},
    "Small":      {"abbr": "S",  "color": "#22c55e", "bg": "rgba(34,197,94,0.15)",   "brd": "rgba(34,197,94,0.45)"},
    "Very Small": {"abbr": "VS", "color": "#06b6d4", "bg": "rgba(6,182,212,0.15)",   "brd": "rgba(6,182,212,0.45)"},
}
_ALL_SIZES = ["Big", "Medium", "Small", "Very Small"]

_LEFT_COLS = [
    ("STORY",        "minmax(220px,1fr)"),
    ("SIZE",         "88px"),
    ("STORY OWNER",  "115px"),
    ("DEVELOPER",    "115px"),
]
_COL_W = "62px"

_AREA_COLORS = {
    "Web": "#60a5fa", "Mobile": "#a78bfa",
    "iOS": "#34d399",  "Android": "#f59e0b", "API": "#22d3ee",
}

# ── Data layer ────────────────────────────────────────────────────────────────
_DT_CACHE: dict = {"df": None, "ts": 0.0, "bust": -1}
_DT_TTL = 300
_GRID_RENDER_CACHE: dict = {}   # filter_key → (bust, ts, grid_children)

_INSIGHTS_CACHE: dict = {"df": None, "ts": 0.0, "bust": -1}
_INSIGHTS_TTL = 180

# Chart palette (matches panel design standard)
_IC = {
    "bg":     "rgb(18,22,31)",
    "paper":  "rgb(13,17,27)",
    "grid":   "rgb(38,44,58)",
    "fg":     "rgb(234,236,242)",
    "mt":     "rgb(139,146,164)",
    "green":  "rgb(70,194,142)",
    "amber":  "rgb(224,162,60)",
    "red":    "rgb(239,110,99)",
    "indigo": "rgb(110,118,241)",
    "cyan":   "rgb(63,182,201)",
}

_MONTH_NUM = {
    "January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
    "July":7,"August":8,"September":9,"October":10,"November":11,"December":12,
}
_MON3 = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
         "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}


def _release_sort_key(label: str) -> tuple:
    m = re.match(r"(\d{4})\s+(\w+)", label or "")
    if m:
        return (int(m.group(1)), _MONTH_NUM.get(m.group(2).capitalize(), 0), label)
    return (9999, 0, label)


def _load_insights_data() -> pd.DataFrame:
    from data.loader import get_ui_cache_bust as _get_bust
    now = _time_mod.time()
    bust = _get_bust()
    if (_INSIGHTS_CACHE["df"] is not None
            and now - _INSIGHTS_CACHE["ts"] < _INSIGHTS_TTL
            and _INSIGHTS_CACHE["bust"] == bust):
        return _INSIGHTS_CACHE["df"]
    try:
        with engine.connect() as c:
            df = pd.read_sql(_text("""
                SELECT
                    w.work_item_id,
                    w.title,
                    COALESCE(NULLIF(TRIM(w.main_developer), ''), 'Unassigned') AS developer,
                    w.iteration_path,
                    COALESCE(NULLIF(TRIM(w.release_date),  ''), '') AS release_label,
                    COALESCE(NULLIF(TRIM(w.priority::TEXT), ''), '3') AS priority,
                    COALESCE(NULLIF(TRIM(w.story_size),    ''), 'Unknown') AS story_size,
                    COALESCE(NULLIF(TRIM(w.story_owner),   ''), '—')       AS story_owner,
                    COALESCE(w.original_estimate, 0)                AS est_hours,
                    (CASE WHEN COALESCE(pg.claude_screens,     FALSE) THEN 1 ELSE 0 END +
                     CASE WHEN COALESCE(pg.text_written,       FALSE) THEN 1 ELSE 0 END +
                     CASE WHEN COALESCE(pg.our_screens,        FALSE) THEN 1 ELSE 0 END +
                     CASE WHEN COALESCE(pg.sn_signoff,         FALSE) THEN 1 ELSE 0 END) AS gates_done,
                    (CASE WHEN COALESCE(pg.claude_screens_wip, FALSE) THEN 1 ELSE 0 END +
                     CASE WHEN COALESCE(pg.text_written_wip,   FALSE) THEN 1 ELSE 0 END +
                     CASE WHEN COALESCE(pg.our_screens_wip,    FALSE) THEN 1 ELSE 0 END +
                     CASE WHEN COALESCE(pg.sn_signoff_wip,     FALSE) THEN 1 ELSE 0 END) AS gates_wip
                FROM work_items_main w
                LEFT JOIN p_planning_gates pg USING (work_item_id)
                WHERE w.work_item_type = 'Enhancement'
                  AND w.state NOT IN (
                      'Done','Closed','Not an issue','Not Required',
                      'Userstory Update','No Customer Response','Resolved','Not Specified'
                  )
                  AND (
                      w.release_date   ~ '^202[6-9] [A-Za-z]'
                      OR w.iteration_path ~ 'Iteration 202[6-9]'
                  )
            """), c)
        df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(3).astype(int)
        _INSIGHTS_CACHE["df"] = df
        _INSIGHTS_CACHE["ts"] = now
        _INSIGHTS_CACHE["bust"] = bust
        return df
    except Exception:
        return pd.DataFrame()


def _dark_layout(**kw) -> dict:
    base = dict(
        plot_bgcolor=_IC["bg"], paper_bgcolor=_IC["paper"],
        font=dict(color=_IC["fg"], family="Inter, system-ui, sans-serif", size=12),
        hoverlabel=dict(bgcolor="rgb(23,28,40)", bordercolor=_IC["grid"],
                        font=dict(color=_IC["fg"], size=12)),
        legend=dict(font=dict(color=_IC["mt"], size=11)),
    )
    base.update(kw)
    return base


def _build_dev_load_chart(df: pd.DataFrame) -> dcc.Graph:
    """Heatmap: developer × sprint month, cell = story count."""
    df = df.copy()

    def _month_key(ip):
        m = re.search(r"Iteration (\d{4}) (\d{2})-(\w+)", ip or "")
        if m:
            return f"{m.group(3)[:3]} '{m.group(1)[2:]}"   # "Jul '26"
        return None

    df["month_key"] = df["iteration_path"].apply(_month_key)
    df = df[df["month_key"].notna()]
    if df.empty:
        return html.Div("No sprint data", style={"color": _IC["mt"], "padding": "20px"})

    def _mk_sort(mk):
        p = mk.split()
        return (int(p[1].strip("'")), _MON3.get(p[0], 0)) if len(p) == 2 else (99, 99)

    all_months = sorted(df["month_key"].unique(), key=_mk_sort)
    devs = sorted(df["developer"].unique())

    pivot = df.groupby(["developer", "month_key"]).size().reset_index(name="n")
    z = []
    for dev in devs:
        row = []
        for mo in all_months:
            v = pivot.loc[(pivot.developer == dev) & (pivot.month_key == mo), "n"]
            row.append(int(v.iloc[0]) if len(v) else 0)
        z.append(row)

    fig = go.Figure(go.Heatmap(
        z=z, x=all_months, y=devs,
        colorscale=[[0,"rgba(70,194,142,0.08)"],[0.3,_IC["amber"]],[1.0,_IC["red"]]],
        showscale=False,
        text=z, texttemplate="%{z}",
        textfont=dict(color=_IC["fg"], size=12),
        hovertemplate="<b>%{y}</b><br>%{x}: <b>%{z} stories</b><extra></extra>",
    ))
    fig.update_layout(**_dark_layout(
        height=max(260, 48 + len(devs) * 38),
        margin=dict(l=150, r=20, t=10, b=50),
        xaxis=dict(side="top", gridcolor=_IC["grid"], tickfont=dict(size=11)),
        yaxis=dict(gridcolor="rgba(0,0,0,0)", autorange="reversed",
                   tickfont=dict(size=11)),
    ))
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"width": "100%"})


def _build_release_scope_chart(df: pd.DataFrame) -> dcc.Graph:
    """Stacked bar per release: all done / in-progress / not started."""
    df = df[df["release_label"].str.match(r"^202[6-9] [A-Za-z]", na=False)].copy()
    if df.empty:
        return html.Div("No release data", style={"color": _IC["mt"], "padding": "20px"})

    def _cls(row):
        if row.gates_done == 5:             return "All gates done"
        if row.gates_done > 0 or row.gates_wip > 0: return "In progress"
        return "Not started"

    df["status"] = df.apply(_cls, axis=1)
    releases = sorted(df["release_label"].unique(), key=_release_sort_key)
    labels   = [r.replace("2026 ", "").replace("2027 ", "'27 ") for r in releases]

    cats = [("All gates done", _IC["green"]),
            ("In progress",    _IC["amber"]),
            ("Not started",    _IC["red"])]

    fig = go.Figure([
        go.Bar(
            name=name, x=labels,
            y=[len(df[(df.release_label == r) & (df.status == name)]) for r in releases],
            marker_color=color,
            hovertemplate="%{y} stories<extra>" + name + "</extra>",
        )
        for name, color in cats
    ])
    fig.update_layout(**_dark_layout(
        barmode="stack", height=360,
        margin=dict(l=50, r=20, t=10, b=80),
        xaxis=dict(tickangle=-35, gridcolor=_IC["grid"], tickfont=dict(size=11)),
        yaxis=dict(title="Stories", gridcolor=_IC["grid"]),
        legend=dict(orientation="h", y=1.06, x=0),
    ))
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"width": "100%"})


def _build_risk_scatter(df: pd.DataFrame) -> dcc.Graph:
    """Scatter: x=gates done, y=release (near=top), size=story size, color=priority."""
    df = df[df["release_label"].str.match(r"^202[6-9] [A-Za-z]", na=False)].copy()
    if df.empty:
        return html.Div("No data", style={"color": _IC["mt"], "padding": "20px"})

    releases = sorted(df["release_label"].unique(), key=_release_sort_key)
    rel_y = {r: i for i, r in enumerate(releases)}
    labels = [r.replace("2026 ", "").replace("2027 ", "'27 ") for r in releases]

    _sz  = {"Big": 22, "Medium": 15, "Small": 11, "Very Small": 8, "Unknown": 9}
    _col = {1: _IC["red"], 2: _IC["amber"], 3: _IC["green"]}

    fig = go.Figure()
    for pri in [1, 2, 3]:
        sub = df[df["priority"] == pri]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["gates_done"].astype(float),
            y=[rel_y[r] for r in sub["release_label"]],
            mode="markers",
            name=f"P{pri}",
            marker=dict(
                size=[_sz.get(s, 10) for s in sub["story_size"]],
                color=_col[pri], opacity=0.75,
                line=dict(width=1, color="rgba(255,255,255,0.12)"),
            ),
            text=sub["title"],
            customdata=sub[["developer", "release_label", "story_size", "gates_done"]].values,
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Dev: %{customdata[0]}<br>"
                "Release: %{customdata[1]}<br>"
                "Size: %{customdata[2]}  |  Gates: %{customdata[3]}/5"
                "<extra></extra>"
            ),
        ))

    # Danger zone annotation: bottom-left = urgent + not started
    fig.add_shape(type="rect", x0=-0.4, x1=1.4,
                  y0=-0.5, y1=len(releases) * 0.3,
                  fillcolor="rgba(239,110,99,0.06)",
                  line=dict(color="rgba(239,110,99,0.2)", width=1, dash="dot"))

    fig.update_layout(**_dark_layout(
        height=max(420, 80 + len(releases) * 44),
        margin=dict(l=140, r=20, t=30, b=50),
        xaxis=dict(title="Gates completed (0 = none, 5 = all done)",
                   range=[-0.5, 5.5], tickmode="linear", dtick=1,
                   gridcolor=_IC["grid"], tickfont=dict(size=11)),
        yaxis=dict(tickmode="array",
                   tickvals=list(range(len(releases))),
                   ticktext=labels,
                   gridcolor=_IC["grid"], tickfont=dict(size=11),
                   autorange="reversed"),
        legend=dict(orientation="h", y=1.04, x=0),
        annotations=[dict(
            x=0.5, y=-0.1, xref="paper", yref="paper", showarrow=False,
            text="← Risk zone (few gates, near release)       On track →",
            font=dict(size=10, color=_IC["mt"]),
        )],
    ))
    return dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"width": "100%"})


def _load_dt() -> pd.DataFrame:
    from data.loader import get_ui_cache_bust as _get_bust
    now = _time_mod.time()
    bust = _get_bust()
    if (_DT_CACHE["df"] is None or now - _DT_CACHE["ts"] > _DT_TTL
            or _DT_CACHE["bust"] != bust):
        _GRID_RENDER_CACHE.clear()
    if _DT_CACHE["df"] is None or now - _DT_CACHE["ts"] > _DT_TTL or _DT_CACHE["bust"] != bust:
        with engine.connect() as _c:
            df = pd.read_sql(_text("""
                SELECT
                    g.work_item_id,
                    g.title,
                    g.main_developer,
                    g.bar_start,
                    COALESCE(g.release_date, g.bar_end, g.bar_start) AS delivery_date,
                    COALESCE(NULLIF(TRIM(w.story_size),  ''), '—') AS story_size,
                    COALESCE(NULLIF(TRIM(w.story_owner), ''), '—') AS story_owner,
                    COALESCE(NULLIF(TRIM(w.area), ''), 'Unassigned') AS area
                FROM agg_gantt_items g
                LEFT JOIN work_items_main w ON w.work_item_id = g.work_item_id
                WHERE g.item_type = 'enh'
                ORDER BY g.bar_start, g.title
            """), _c)
        df["bar_start"]       = pd.to_datetime(df["bar_start"],    errors="coerce")
        df["delivery_date"]   = pd.to_datetime(df["delivery_date"], errors="coerce")
        df["month_key"]       = df["delivery_date"].dt.strftime("%b-%y")
        df["story_size_norm"] = df["story_size"].apply(_normalize_size)
        _DT_CACHE["df"] = df
        _DT_CACHE["ts"] = now
        _DT_CACHE["bust"] = bust
    return _DT_CACHE["df"].copy()


def _filter_key(rolling, sizes, owner, platform, search) -> tuple:
    return (
        rolling or "Rolling 12M",
        tuple(sorted(sizes or [])),
        owner or "All owners",
        platform or "All",
        (search or "").strip().lower(),
    )


def _apply_df_filters(df: pd.DataFrame, rolling: str, sizes: list,
                      owner: str, platform: str, search: str):
    months = _rolling_months(rolling)
    m_keys = {m.strftime("%b-%y") for m in months}
    df = df[df["month_key"].isin(m_keys)]
    if not (set(sizes) >= set(_ALL_SIZES)):
        df = df[df["story_size_norm"].isin(sizes)]
    if owner != "All owners":
        df = df[df["story_owner"].str.strip().str.startswith(owner)]
    if platform == "Mobile":
        df = df[df["area"].str.contains("Mobile", case=False, na=False)]
    elif platform == "Web":
        df = df[df["area"].str.lower().isin(["web", "web & mobile"])]
    if search and search.strip():
        q    = search.strip().lower()
        mask = (
            df["title"].str.lower().str.contains(q, na=False) |
            df["main_developer"].str.lower().str.contains(q, na=False) |
            df["story_owner"].str.lower().str.contains(q, na=False) |
            df["work_item_id"].astype(str).str.contains(q, na=False)
        )
        df = df[mask]
    return df, months


def _normalize_size(s: str) -> str:
    s  = (s or "").strip()
    lc = s.lower()
    if lc == "big":    return "Big"
    if lc == "medium": return "Medium"
    if lc == "small":  return "Small"
    if lc in ("very small", "very_small"): return "Very Small"
    return "—"


def _size_meta(sz: str) -> dict:
    return _SIZE_META.get(sz, _SIZE_META["Small"])


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _rolling_months(rolling: str) -> list[date]:
    n    = {"Rolling 3M": 3, "Rolling 6M": 6, "Rolling 12M": 12}.get(rolling, 12)
    base = date.today()
    base = date(base.year, base.month, 1)
    return [_add_months(base, i) for i in range(n)]


# ── Pill helpers ──────────────────────────────────────────────────────────────
def _pill(label: str, group: str, value: str, active: bool) -> html.Button:
    return html.Button(
        label,
        id={"type": "dt-pill", "group": group, "value": value},
        n_clicks=0,
        style={
            "padding": "4px 13px", "borderRadius": "20px", "fontSize": "12px",
            "fontWeight": "600" if active else "400",
            "color": TXT if active else MT,
            "background": "rgba(99,102,241,0.18)" if active else "transparent",
            "border": "1px solid rgba(99,102,241,0.5)" if active else f"1px solid {BD}",
            "cursor": "pointer", "whiteSpace": "nowrap",
        }
    )


def _size_pill(value: str, active: bool) -> html.Button:
    meta = _SIZE_META.get(value, {})
    c    = meta.get("color", "#818cf8")
    bg   = meta.get("bg",    "rgba(99,102,241,0.18)")
    brd  = meta.get("brd",   "rgba(99,102,241,0.5)")
    return html.Button(
        value,
        id={"type": "dt-pill", "group": "size", "value": value},
        n_clicks=0,
        style={
            "padding": "4px 13px", "borderRadius": "20px", "fontSize": "12px",
            "fontWeight": "600" if active else "400",
            "color": c if active else MT,
            "background": bg if active else "transparent",
            "border": f"1px solid {brd}" if active else f"1px solid {BD}",
            "cursor": "pointer", "whiteSpace": "nowrap",
        }
    )


def _build_filter_bar(rolling: str, sizes: list, owner: str, platform: str) -> html.Div:
    all_active = set(sizes or []) >= set(_ALL_SIZES)
    return html.Div([
        *[_pill(r, "rolling", r, r == rolling) for r in ("Rolling 12M", "Rolling 6M", "Rolling 3M")],
        html.Div(style={"width": "1px", "height": "20px", "background": BD, "margin": "0 4px"}),
        *[_size_pill(s, s in (sizes or [])) for s in _ALL_SIZES],
        _pill("All", "size", "All", all_active),
        html.Div(style={"width": "1px", "height": "20px", "background": BD, "margin": "0 4px"}),
        *[_pill(p, "platform", p, p == platform) for p in ("All", "Mobile", "Web")],
        html.Div(style={"width": "1px", "height": "20px", "background": BD, "margin": "0 4px"}),
        *[_pill(o, "owner", o, o == owner) for o in ("All owners", "Chhavi", "Geetika", "Sunil")],
    ], style={
        "display": "flex", "alignItems": "center", "gap": "6px",
        "flexWrap": "wrap", "marginBottom": "14px",
    })


# ── Month grid ────────────────────────────────────────────────────────────────
def _build_grid(df: pd.DataFrame, months: list[date], panel_wid) -> html.Div:
    today_key = date.today().strftime("%b-%y")
    cols_tpl  = " ".join(c[1] for c in _LEFT_COLS) + " " + " ".join([_COL_W] * len(months))

    month_counts = {m.strftime("%b-%y"): 0 for m in months}
    for mk in df["month_key"]:
        if mk in month_counts:
            month_counts[mk] += 1

    def _hdr_cell(txt: str, align: str = "left", today_col: bool = False) -> html.Div:
        return html.Div(txt, style={
            "padding": "9px 10px 8px", "fontSize": "10px", "fontWeight": "700",
            "letterSpacing": "0.07em", "textAlign": align,
            "color": "#a78bfa" if today_col else MT,
            "background": "rgba(167,139,250,0.07)" if today_col else EL,
        })

    header = html.Div(
        [_hdr_cell(lbl) for lbl, _ in _LEFT_COLS] +
        [_hdr_cell(m.strftime("%b-%y"), align="center",
                   today_col=(m.strftime("%b-%y") == today_key)) for m in months],
        style={"display": "grid", "gridTemplateColumns": cols_tpl,
               "borderBottom": f"1px solid {BD}",
               "position": "sticky", "top": "0", "zIndex": "3"},
    )

    rows: list = []
    for _, r in df.sort_values("delivery_date").iterrows():
        wid  = int(r["work_item_id"])
        sz   = r["story_size_norm"]
        mk   = r["month_key"]
        meta = _size_meta(sz)
        sel  = (wid == panel_wid)

        m_cells = []
        for m in months:
            m_key  = m.strftime("%b-%y")
            is_tc  = m_key == today_key
            inner  = html.Div(
                meta["abbr"],
                id={"type": "dt-cell", "wid": wid},
                n_clicks=0,
                style={
                    "width": "32px", "height": "32px", "borderRadius": "6px",
                    "fontSize": "11px", "fontWeight": "700",
                    "color": meta["color"], "background": meta["bg"],
                    "border": f"2px solid {meta['color']}" if sel else f"1.5px solid {meta['brd']}",
                    "display": "flex", "alignItems": "center", "justifyContent": "center",
                    "cursor": "pointer",
                }
            ) if m_key == mk else html.Div(style={"width": "32px", "height": "32px"})

            m_cells.append(html.Div(inner, style={
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "padding": "6px 2px", "borderRight": f"1px solid {BD}",
                "background": "rgba(167,139,250,0.04)" if is_tc else "transparent",
            }))

        cells = [
            html.Div([
                html.Div(r["title"], style={
                    "fontSize": "12px", "fontWeight": "500", "color": TXT,
                    "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
                }),
                html.Span(f"#{wid}  ·  {r['area']}",
                          style={"fontSize": "10px", "color": MT, "display": "block", "marginTop": "1px"}),
            ], style={"padding": "8px 10px", "overflow": "hidden", "borderRight": f"1px solid {BD}"}),

            html.Div(
                html.Span(sz, style={
                    "padding": "2px 7px", "borderRadius": "4px", "fontSize": "11px",
                    "fontWeight": "600", "color": meta["color"],
                    "background": meta["bg"], "border": f"1px solid {meta['brd']}",
                }) if sz != "—" else html.Span("—", style={"color": MT}),
                style={"padding": "7px 6px", "display": "flex", "alignItems": "center",
                       "justifyContent": "center", "borderRight": f"1px solid {BD}"},
            ),

            html.Div(
                str(r["story_owner"]).split()[0] if r["story_owner"] != "—" else "—",
                style={"padding": "8px 10px", "fontSize": "12px", "color": MT,
                       "textAlign": "center", "borderRight": f"1px solid {BD}"},
            ),

            html.Div(
                str(r["main_developer"] or "—").split()[0],
                style={"padding": "8px 10px", "fontSize": "12px", "color": MT,
                       "textAlign": "center", "borderRight": f"1px solid {BD}"},
            ),

            *m_cells,
        ]

        rows.append(html.Div(cells, style={
            "display": "grid", "gridTemplateColumns": cols_tpl,
            "borderBottom": f"1px solid {BD}",
            "background": "rgba(167,139,250,0.05)" if sel else "transparent",
        }))

    if not rows:
        rows = [html.Div("No stories match the current filters.",
                         style={"padding": "28px", "color": MT, "textAlign": "center"})]

    def _foot_cnt(m: date) -> html.Div:
        cnt = month_counts.get(m.strftime("%b-%y"), 0)
        return html.Div(str(cnt) if cnt else "", style={
            "padding": "8px 4px", "textAlign": "center", "fontSize": "11px",
            "fontWeight": "600", "color": "#a78bfa" if cnt else MT,
            "borderRight": f"1px solid {BD}",
        })

    footer = html.Div([
        html.Div("STORIES PER MONTH", style={
            "padding": "8px 10px", "fontSize": "9px", "fontWeight": "700",
            "color": MT, "letterSpacing": "0.07em", "textAlign": "right",
            "borderRight": f"1px solid {BD}",
        }),
        html.Div(style={"borderRight": f"1px solid {BD}"}),
        html.Div(style={"borderRight": f"1px solid {BD}"}),
        html.Div(style={"borderRight": f"1px solid {BD}"}),
        *[_foot_cnt(m) for m in months],
    ], style={
        "display": "grid", "gridTemplateColumns": cols_tpl,
        "borderTop": f"2px solid {BD}", "background": EL,
        "position": "sticky", "bottom": "0", "zIndex": "2",
    })

    return html.Div([header, *rows, footer], style={
        "borderRadius": "8px", "border": f"1px solid {BD}",
        "overflowX": "auto", "overflowY": "auto",
        "maxHeight": "calc(100vh - 240px)",
    })


# ── Side panel ────────────────────────────────────────────────────────────────
def _build_panel(r: pd.Series) -> html.Div:
    wid  = int(r["work_item_id"])
    sz   = r["story_size_norm"]
    meta = _size_meta(sz)
    area = str(r["area"])

    def _row(label: str, value) -> html.Div:
        val_el = value if not isinstance(value, str) else \
                 html.Span(value, style={"fontSize": "13px", "color": TXT})
        return html.Div([
            html.Span(label, style={
                "fontSize": "10px", "fontWeight": "700", "color": MT,
                "letterSpacing": "0.06em", "textTransform": "uppercase",
                "width": "110px", "flexShrink": "0",
            }),
            val_el,
        ], style={"display": "flex", "alignItems": "center",
                  "padding": "8px 0", "borderBottom": f"1px solid {BD}"})

    return html.Div([
        html.Div([
            html.Span(f"#{wid}", style={"fontSize": "11px", "color": MT}),
            html.Span(" · ", style={"color": MT}),
            html.Span(area, style={"fontSize": "11px", "fontWeight": "700",
                                    "color": _AREA_COLORS.get(area, MT)}),
            html.Button("✕", id="dt-panel-close", n_clicks=0, style={
                "marginLeft": "auto", "background": "transparent", "border": "none",
                "color": MT, "fontSize": "16px", "cursor": "pointer",
                "lineHeight": "1", "padding": "0 2px",
            }),
        ], style={"display": "flex", "alignItems": "center",
                  "gap": "4px", "marginBottom": "10px"}),

        html.Div(r["title"], style={
            "fontSize": "15px", "fontWeight": "700", "color": TXT,
            "lineHeight": "1.4", "marginBottom": "16px",
        }),

        _row("Size", html.Span(sz, style={
            "padding": "2px 8px", "borderRadius": "4px", "fontSize": "11px",
            "fontWeight": "700", "color": meta["color"],
            "background": meta["bg"], "border": f"1px solid {meta['brd']}",
        })),
        _row("Platform",       area),
        _row("Story owner",    str(r["story_owner"])),
        _row("Developer",      str(r["main_developer"] or "—")),
        _row("Dev iteration",  str(r["bar_start"].strftime("%b-%y"))
             if pd.notna(r.get("bar_start")) else "—"),
        _row("Release month",  str(r["month_key"])),
    ], style={
        "padding": "16px", "background": EL,
        "borderRadius": "10px", "border": f"1px solid {BD}",
        "width": "280px", "minWidth": "280px",
        "height": "fit-content", "alignSelf": "flex-start",
        "position": "sticky", "top": "0",
    })


# ── Tab button helper ─────────────────────────────────────────────────────────
def _tab_btn(label: str, tid: str, active: bool) -> html.Button:
    return html.Button(
        label,
        id={"type": "dt-tab-btn", "tab": tid},
        n_clicks=0,
        style={
            "background": "rgba(99,102,241,0.15)" if active else "transparent",
            "border": f"1px solid {'rgba(99,102,241,0.6)' if active else BD}",
            "borderRadius": "8px", "color": TXT if active else MT,
            "fontSize": "13px", "fontWeight": "600" if active else "400",
            "padding": "6px 18px", "cursor": "pointer", "marginRight": "6px",
        }
    )


# ── Layout ────────────────────────────────────────────────────────────────────
def layout(**_):
    return html.Div([
        dcc.Store(id="dt-rolling",   data="Rolling 12M"),
        dcc.Store(id="dt-sizes",     data=["Big", "Medium"]),
        dcc.Store(id="dt-owner",     data="All owners"),
        dcc.Store(id="dt-platform",  data="All"),
        dcc.Store(id="dt-panel-wid", data=None),
        dcc.Store(id="dt-view-tab",  data="grid"),      # "grid" | "gantt" | "planning"
        dcc.Store(id="dt-gantt-view", data="0-12"),     # for gantt window
        dcc.Store(id="dt-gantt-type", data="all"),      # for gantt type filter
        dcc.Store(id="gantt-expanded", data={"s": [], "t": []}),  # shared with gantt_toggle.js

        # Page header
        html.Div([
            html.Div([
                html.Div("EOD · PLANNING", style={
                    "fontSize": "10px", "fontWeight": "700", "color": P,
                    "letterSpacing": "1px", "textTransform": "uppercase", "marginBottom": "4px",
                }),
                html.Div([
                    html.Span("Delivery Timeline", style={
                        "fontSize": "20px", "fontWeight": "800", "color": TXT,
                    }),
                    html.Span(id="dt-subtitle",
                              style={"fontSize": "13px", "color": MT, "marginLeft": "10px"}),
                ], style={"display": "flex", "alignItems": "baseline"}),
            ]),
            dcc.Input(
                id="dt-search", type="text",
                placeholder="Search stories, id, owner, developer…",
                debounce=True,
                style={
                    "background": HV, "border": f"1px solid {BD}",
                    "borderRadius": "8px", "padding": "7px 14px",
                    "fontSize": "12px", "color": TXT, "width": "280px",
                },
            ),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "flex-start", "marginBottom": "16px"}),

        # Tab switcher
        html.Div([
            _tab_btn("Month Grid", "grid",     True),
            _tab_btn("Gantt",      "gantt",    False),
            _tab_btn("Planning",   "planning", False),
        ], id="dt-tab-row", style={
            "display": "flex", "alignItems": "center",
            "marginBottom": "14px", "borderBottom": f"1px solid {BD}",
            "paddingBottom": "12px",
        }),

        # ── Month Grid view ────────────────────────────────────────────────────
        html.Div(id="dt-grid-section", children=[
            html.Div(id="dt-filter-bar"),
            html.Div([
                dcc.Loading(
                    type="circle", color="#818cf8",
                    style={"flex": "1", "minWidth": "0"},
                    children=html.Div(id="dt-grid"),
                ),
                html.Div(id="dt-panel-wrap", style={"flexShrink": "0"}),
            ], style={"display": "flex", "gap": "16px"}),
        ]),

        # ── Gantt view ─────────────────────────────────────────────────────────
        html.Div(id="dt-gantt-section", style={"display": "none"}, children=[
            html.Div([
                html.Div([
                    dcc.Dropdown(
                        id="dt-gantt-view-select",
                        options=[
                            {"label": "Rolling 12M", "value": "0-12"},
                            {"label": "12 – 24M",    "value": "12-24"},
                            {"label": "24M+",        "value": "24+"},
                        ],
                        value="0-12",
                        clearable=False,
                        className="dark-dropdown",
                        style={"minWidth": "140px", "fontSize": "12px"},
                    ),
                    dcc.Dropdown(
                        id="dt-gantt-type-select",
                        options=[
                            {"label": "All work",     "value": "all"},
                            {"label": "Enhancements", "value": "enh"},
                            {"label": "Bugs",         "value": "bug"},
                        ],
                        value="all",
                        clearable=False,
                        className="dark-dropdown",
                        style={"minWidth": "140px", "fontSize": "12px"},
                    ),
                ], style={"display": "flex", "gap": "8px",
                          "padding": "0 16px 12px", "flexWrap": "wrap"}),
                dcc.Loading(
                    id="dt-gantt-loading",
                    type="default",
                    color="var(--accent)",
                    children=html.Div(id="dt-gantt-chart",
                                      style={"overflowY": "auto", "maxHeight": "680px"}),
                ),
            ], style={
                "background": "var(--bg-elevated)", "border": f"1px solid {BD}",
                "borderRadius": "12px", "padding": "14px 0 0",
                "overflow": "hidden",
            }),
        ]),

        # ── Planning / Insights view ───────────────────────────────────────────
        html.Div(id="dt-planning-section", style={"display": "none"}, children=[
            dcc.Loading(type="circle", color="#818cf8",
                        target_components={"dt-planning-charts": "children"},
                        children=html.Div(id="dt-planning-charts")),
        ]),

    ], style={"padding": "24px"})


# ── Callbacks ─────────────────────────────────────────────────────────────────

# Tab switcher
@callback(
    Output("dt-view-tab",           "data"),
    Output("dt-tab-row",            "children"),
    Output("dt-grid-section",       "style"),
    Output("dt-gantt-section",      "style"),
    Output("dt-planning-section",   "style"),
    Input({"type": "dt-tab-btn", "tab": ALL}, "n_clicks"),
    State("dt-view-tab", "data"),
    prevent_initial_call=True,
)
def _switch_tab(_clicks, current):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict) or not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update, no_update, no_update
    tab = tid.get("tab", current)
    btns = [
        _tab_btn("Month Grid", "grid",     tab == "grid"),
        _tab_btn("Gantt",      "gantt",    tab == "gantt"),
        _tab_btn("Planning",   "planning", tab == "planning"),
    ]
    show = {"display": "block"}
    hide = {"display": "none"}
    return (tab, btns,
            show if tab == "grid"     else hide,
            show if tab == "gantt"    else hide,
            show if tab == "planning" else hide)


# Filter pills → stores
@callback(
    Output("dt-rolling",  "data"),
    Output("dt-sizes",    "data"),
    Output("dt-owner",    "data"),
    Output("dt-platform", "data"),
    Input({"type": "dt-pill", "group": ALL, "value": ALL}, "n_clicks"),
    State("dt-rolling",  "data"),
    State("dt-sizes",    "data"),
    State("dt-owner",    "data"),
    State("dt-platform", "data"),
    prevent_initial_call=True,
)
def _update_filters(_clicks, rolling, sizes, owner, platform):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict) or not ctx.triggered[0]["value"]:
        return no_update, no_update, no_update, no_update
    group = tid.get("group")
    value = tid.get("value")
    if group == "rolling":
        return value, no_update, no_update, no_update
    if group == "size":
        if value == "All":
            return no_update, _ALL_SIZES[:], no_update, no_update
        cur = list(sizes or [])
        if value in cur:
            cur.remove(value)
            if not cur:
                cur = _ALL_SIZES[:]
        else:
            cur.append(value)
        return no_update, cur, no_update, no_update
    if group == "owner":
        return no_update, no_update, value, no_update
    if group == "platform":
        return no_update, no_update, no_update, value
    return no_update, no_update, no_update, no_update


# Cell click → panel
@callback(
    Output("dt-panel-wid", "data", allow_duplicate=True),
    Input({"type": "dt-cell", "wid": ALL}, "n_clicks"),
    State("dt-panel-wid", "data"),
    prevent_initial_call=True,
)
def _select_cell(_clicks, current_wid):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict) or not ctx.triggered[0]["value"]:
        return no_update
    wid = tid.get("wid")
    return None if wid == current_wid else wid


# Close panel
@callback(
    Output("dt-panel-wid", "data", allow_duplicate=True),
    Input("dt-panel-close", "n_clicks"),
    prevent_initial_call=True,
)
def _close_panel(_n):
    return None


# ── Callback 1: filter bar + subtitle (fast — no grid build) ──────────────────
@callback(
    Output("dt-filter-bar", "children"),
    Output("dt-subtitle",   "children"),
    Input("dt-rolling",  "data"),
    Input("dt-sizes",    "data"),
    Input("dt-owner",    "data"),
    Input("dt-platform", "data"),
    Input("dt-search",   "value"),
)
def _render_header(rolling, sizes, owner, platform, search):
    rolling  = rolling  or "Rolling 12M"
    sizes    = sizes    or ["Big", "Medium"]
    owner    = owner    or "All owners"
    platform = platform or "All"
    df, months = _apply_df_filters(_load_dt(), rolling, sizes, owner, platform, search)
    n        = len(df)
    subtitle = (f" · {months[0].strftime('%b-%y')} – {months[-1].strftime('%b-%y')}"
                f"  ·  {n} {'story' if n == 1 else 'stories'}")
    return _build_filter_bar(rolling, sizes, owner, platform), subtitle


# ── Callback 2: grid only (expensive; cached; never fires on panel changes) ───
@callback(
    Output("dt-grid", "children"),
    Input("dt-rolling",  "data"),
    Input("dt-sizes",    "data"),
    Input("dt-owner",    "data"),
    Input("dt-platform", "data"),
    Input("dt-search",   "value"),
)
def _render_grid_only(rolling, sizes, owner, platform, search):
    rolling  = rolling  or "Rolling 12M"
    sizes    = sizes    or ["Big", "Medium"]
    owner    = owner    or "All owners"
    platform = platform or "All"

    from data.loader import get_ui_cache_bust as _get_bust
    key = (_get_bust(),) + _filter_key(rolling, sizes, owner, platform, search)
    now = _time_mod.time()
    if key in _GRID_RENDER_CACHE:
        ts, cached = _GRID_RENDER_CACHE[key]
        if now - ts < _DT_TTL:
            return cached

    df, months = _apply_df_filters(_load_dt(), rolling, sizes, owner, platform, search)
    result = _build_grid(df, months, panel_wid=None)
    _GRID_RENDER_CACHE[key] = (now, result)
    return result


# ── Callback 3: panel only (fast; fires only on row click / close) ────────────
@callback(
    Output("dt-panel-wrap", "children"),
    Input("dt-panel-wid",  "data"),
    State("dt-rolling",    "data"),
    State("dt-sizes",      "data"),
    State("dt-owner",      "data"),
    State("dt-platform",   "data"),
    State("dt-search",     "value"),
)
def _render_panel_only(panel_wid, rolling, sizes, owner, platform, search):
    if panel_wid is None:
        return []
    rolling  = rolling  or "Rolling 12M"
    sizes    = sizes    or ["Big", "Medium"]
    owner    = owner    or "All owners"
    platform = platform or "All"
    df, _ = _apply_df_filters(_load_dt(), rolling, sizes, owner, platform, search)
    match = df[df["work_item_id"] == panel_wid]
    if match.empty:
        # item may be outside current filter window — look in full dataset
        match = _load_dt()
        match = match[match["work_item_id"] == panel_wid]
    if match.empty:
        return []
    return [_build_panel(match.iloc[0])]


# Gantt render (calls _build_gantt_html from planning.py)
@callback(
    Output("dt-gantt-chart",        "children"),
    Input("dt-view-tab",            "data"),
    Input("dt-gantt-view-select",   "value"),
    Input("dt-gantt-type-select",   "value"),
    State("gantt-expanded",         "data"),
    prevent_initial_call=True,
)
def _render_gantt(view_tab, gantt_view, gantt_type, expanded):
    if view_tab != "gantt":
        return no_update
    try:
        from pages_dash.enhancements.planning import _build_gantt_html, _gantt_window
        ws, we, _ = _gantt_window(gantt_view or "0-12")
        return _build_gantt_html(
            ws, we,
            expanded_sprints=set((expanded or {}).get("s", [])),
            expanded_items=set((expanded or {}).get("t", [])),
            dev_filter=None,
            type_filter=gantt_type or "all",
            prio_filter=None,
            year_filter=None,
            cust_filter="all",
        )
    except Exception as e:
        return html.Div(f"Gantt unavailable: {e}",
                        style={"padding": "20px", "color": MT, "fontSize": "13px"})


# Planning tab render
@callback(
    Output("dt-planning-charts", "children"),
    Input("dt-view-tab",         "data"),
    prevent_initial_call=True,
)
def _render_planning(view_tab):
    if view_tab != "planning":
        return no_update

    df = _load_insights_data()
    if df.empty:
        return html.Div("No data available — run a sync to populate stories.",
                        style={"padding": "40px", "color": MT, "fontSize": "13px"})

    def _card(title, chart, subtitle=""):
        return html.Div([
            html.Div([
                html.Span(title, style={
                    "fontSize": "11px", "fontWeight": "700",
                    "color": _IC["mt"], "textTransform": "uppercase",
                    "letterSpacing": "0.5px",
                }),
                html.Span(f" — {subtitle}", style={
                    "fontSize": "11px", "color": _IC["mt"],
                }) if subtitle else None,
            ], style={"marginBottom": "10px"}),
            chart,
        ], style={
            "background": _IC["bg"],
            "border": f"1px solid {_IC['grid']}",
            "borderRadius": "12px",
            "padding": "18px 16px 12px",
            "marginBottom": "20px",
        })

    total   = len(df)
    no_gate = len(df[df["gates_done"] == 0])
    p1_no_gate = len(df[(df["priority"] == 1) & (df["gates_done"] == 0)])

    summary = html.Div([
        _kpi("Total active stories", str(total)),
        _kpi("No gates started",     str(no_gate),     warn=no_gate > total * 0.5),
        _kpi("P1 with no gates",     str(p1_no_gate),  warn=p1_no_gate > 0),
    ], style={"display": "flex", "gap": "14px", "marginBottom": "20px",
              "flexWrap": "wrap"})

    return html.Div([
        summary,
        _card("Sign-Off Readiness by Release",
              _build_release_scope_chart(df),
              "green = all 5 gates done, amber = in progress, red = not started"),
        _card("Developer Sprint Load",
              _build_dev_load_chart(df),
              "story count per developer per sprint"),
        _card("Story Risk Matrix",
              _build_risk_scatter(df),
              "bottom-left = urgent stories with no sign-off progress"),
    ], style={"paddingTop": "4px"})


def _kpi(label: str, value: str, warn: bool = False) -> html.Div:
    color = _IC["red"] if warn else _IC["fg"]
    return html.Div([
        html.Div(value, style={
            "fontSize": "28px", "fontWeight": "800", "color": color,
            "lineHeight": "1",
        }),
        html.Div(label, style={
            "fontSize": "10px", "color": _IC["mt"],
            "textTransform": "uppercase", "letterSpacing": "0.4px",
            "marginTop": "4px",
        }),
    ], style={
        "background": _IC["bg"], "border": f"1px solid {_IC['grid']}",
        "borderRadius": "10px", "padding": "14px 18px",
        "minWidth": "140px",
    })
