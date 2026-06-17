"""
Plotly Gantt Prototype — Release Analytics
===========================================
Generates  gantt_prototype.html  at the project root.
Open that file in any browser to preview the chart.

Run:
  cd C:/Python/Release
  .venv/Scripts/python tests/gantt_prototype.py

What this shows
---------------
* One horizontal bar per work item (filtered to rolling 12-month window)
* Progress split: green (done) + type-coloured overlay (remaining)
* Developer sections: alternating tinted backgrounds + left-edge labels
* Today line, R1-R4 release lines
* Hover: title / dev / function / state / progress / priority / sprint
* P1/P2 items get a diamond marker at their end date
* Build + payload size compared to current HTML Gantt printed to stdout
"""

from __future__ import annotations
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from data.loader import engine
from sqlalchemy import text

# ── Window ─────────────────────────────────────────────────────────────────────
def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)

today   = date.today()
WS      = date(today.year, today.month, 1)
WE      = _add_months(WS, 12)
DAY_MS  = 86_400_000

RELEASES = {
    "R1": date(2026, 3, 31),
    "R2": date(2026, 6, 30),
    "R3": date(2026, 9, 30),
    "R4": date(2026, 12, 18),
}

# ── Load data ──────────────────────────────────────────────────────────────────
t_load = time.perf_counter()
with engine.connect() as c:
    items = pd.read_sql(
        text("SELECT * FROM agg_gantt_items ORDER BY main_developer, function, bar_start"),
        c,
    )
load_ms = (time.perf_counter() - t_load) * 1000
print(f"DB load   : {load_ms:.0f} ms  ({len(items)} rows)")

# ── Vectorised data prep ───────────────────────────────────────────────────────
t_prep = time.perf_counter()

# Parse dates once as datetime64
items["bar_start"] = pd.to_datetime(items["bar_start"], errors="coerce")
items["bar_end"]   = pd.to_datetime(items["bar_end"],   errors="coerce")

# Normalise fields
items["main_developer"] = items["main_developer"].fillna("Unassigned").astype(str)
items["function"]       = items["function"].fillna("—").astype(str)
items["pct"]            = pd.to_numeric(items["pct"], errors="coerce").fillna(0).astype(int)
items["item_type"]      = items["item_type"].fillna("enh").astype(str)
items["priority"]       = pd.to_numeric(items["priority"], errors="coerce").fillna(3).astype(int)
items["state"]          = items["state"].fillna("—").astype(str)
items["iteration_path"] = items["iteration_path"].fillna("—").astype(str)
items["title"]          = items["title"].fillna("").astype(str)

# Filter: only rows that overlap the window
WS_ts = pd.Timestamp(WS)
WE_ts = pd.Timestamp(WE)
items = items[items["bar_end"].notna() & items["bar_start"].notna()]
items = items[(items["bar_end"] > WS_ts) & (items["bar_start"] < WE_ts)].copy()

# Clip to window (vectorised)
items["s"] = items["bar_start"].clip(lower=WS_ts, upper=WE_ts)
items["e"] = items["bar_end"].clip(lower=WS_ts,   upper=WE_ts)
items = items[items["s"] < items["e"]].reset_index(drop=True)

# Duration + progress split (all vectorised)
dur_days        = (items["e"] - items["s"]).dt.days
done_days       = (dur_days * items["pct"] / 100).astype(int)
rem_days        = dur_days - done_days
done_end        = items["s"] + pd.to_timedelta(done_days, unit="D")

# Pre-convert dates to ISO strings once (avoids per-row str() calls in trace building)
items["s_str"]        = items["s"].dt.strftime("%Y-%m-%d")
items["done_end_str"] = done_end.dt.strftime("%Y-%m-%d")
items["dur_days"]     = dur_days
items["done_days"]    = done_days
items["rem_days"]     = rem_days

# Sort: dev → func → bar_start
items = items.sort_values(["main_developer", "function", "s"]).reset_index(drop=True)
n = len(items)

# Y positions (numeric — lets shapes position precisely)
items["y_pos"] = np.arange(n)

# Y tick labels (list comp over .values is ~5× faster than .apply)
type_arr  = items["item_type"].values
title_arr = items["title"].values
items["y_tick"] = [
    f"[{'BUG' if t == 'bug' else 'ENH'}]  {tl[:48]}"
    for t, tl in zip(type_arr, title_arr)
]

# Developer group extents for background shapes
dev_groups: dict[str, tuple[int, int]] = {}
for dev, grp in items.groupby("main_developer", sort=False):
    dev_groups[str(dev)] = (int(grp["y_pos"].min()), int(grp["y_pos"].max()))

prep_ms = (time.perf_counter() - t_prep) * 1000
print(f"Data prep : {prep_ms:.0f} ms  ({n} items in window)")

# ── Colours ────────────────────────────────────────────────────────────────────
ENH_REM  = "rgba(107,158,208,0.60)"
BUG_REM  = "rgba(211,111,104,0.60)"
DONE_CLR = "rgba(52,211,153,0.85)"
DEV_BG   = ["rgba(0,0,0,0)", "rgba(107,158,208,0.03)"]
TODAY_CLR = "rgba(117,168,177,0.9)"
REL_CLR   = "rgba(211,111,104,0.55)"
GRID_CLR  = "rgba(255,255,255,0.04)"
BORDER_CLR = "rgba(255,255,255,0.06)"

# ── Build figure ───────────────────────────────────────────────────────────────
t_fig = time.perf_counter()
fig = go.Figure()

# Customdata matrix built once, shared across traces via .loc slicing
CD_COLS = ["title", "main_developer", "function", "state",
           "pct", "priority", "work_item_id", "iteration_path"]
HOVER = (
    "<b>%{customdata[0]}</b><br>"
    "Dev: <b>%{customdata[1]}</b>  ·  Func: %{customdata[2]}<br>"
    "State: %{customdata[3]}  ·  Progress: <b>%{customdata[4]}%</b><br>"
    "Priority: P%{customdata[5]}  ·  Sprint: %{customdata[7]}<br>"
    "<span style='color:#64748b'>ADO #%{customdata[6]}</span>"
    "<extra></extra>"
)

for itype, rem_color, legend_label in [
    ("enh", ENH_REM, "ENH remaining"),
    ("bug", BUG_REM, "BUG remaining"),
]:
    mask      = items["item_type"] == itype
    grp       = items[mask]
    cd        = grp[CD_COLS].to_numpy()

    # ── Remaining portion ──────────────────────────────────────────────────
    rem_mask  = grp["rem_days"] > 0
    rem       = grp[rem_mask]
    if len(rem):
        fig.add_trace(go.Bar(
            name=legend_label,
            y=rem["y_pos"].to_numpy(),
            x=rem["rem_days"].to_numpy() * DAY_MS,
            base=rem["done_end_str"].to_numpy(),
            orientation="h",
            marker=dict(color=rem_color, line_width=0),
            customdata=rem[CD_COLS].to_numpy(),
            hovertemplate=HOVER,
        ))

    # ── Done (green) portion ───────────────────────────────────────────────
    done_mask = grp["done_days"] > 0
    done      = grp[done_mask]
    if len(done):
        fig.add_trace(go.Bar(
            name="Done" if itype == "enh" else None,
            showlegend=(itype == "enh"),
            y=done["y_pos"].to_numpy(),
            x=done["done_days"].to_numpy() * DAY_MS,
            base=done["s_str"].to_numpy(),
            orientation="h",
            marker=dict(color=DONE_CLR, line_width=0),
            hovertemplate="<extra></extra>",
        ))

# P1/P2 priority diamonds
hp = items[items["priority"] <= 2]
if len(hp):
    fig.add_trace(go.Scatter(
        name="P1/P2",
        y=hp["y_pos"].to_numpy(),
        x=hp["e"].dt.strftime("%Y-%m-%d").to_numpy(),
        mode="markers",
        marker=dict(
            symbol="diamond",
            size=[10 if p == 1 else 8 for p in hp["priority"]],
            color=[BUG_REM if t == "bug" else ENH_REM for t in hp["item_type"]],
            line=dict(color="rgba(255,255,255,0.6)", width=1),
        ),
        customdata=hp[["priority", "title"]].to_numpy(),
        hovertemplate="<b>P%{customdata[0]}</b>: %{customdata[1]}<extra></extra>",
    ))

# ── Shapes ────────────────────────────────────────────────────────────────────
shapes: list[dict] = []

for i, (dev, (y0, y1)) in enumerate(dev_groups.items()):
    shapes.append(dict(
        type="rect", layer="below",
        xref="paper", yref="y",
        x0=0, x1=1,
        y0=y0 - 0.5, y1=y1 + 0.5,
        fillcolor=DEV_BG[i % 2],
        line_width=0,
    ))
    if i > 0:
        shapes.append(dict(
            type="line", layer="above",
            xref="paper", yref="y",
            x0=0, x1=1, y0=y0 - 0.5, y1=y0 - 0.5,
            line=dict(color=BORDER_CLR, width=1),
        ))

if WS <= today <= WE:
    shapes.append(dict(
        type="line", xref="x", yref="paper",
        x0=str(today), x1=str(today), y0=0, y1=1,
        line=dict(color=TODAY_CLR, width=2),
    ))

for lbl, rd in RELEASES.items():
    if WS <= rd <= WE:
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=str(rd), x1=str(rd), y0=0, y1=1,
            line=dict(color=REL_CLR, width=1.5, dash="dot"),
        ))

# ── Annotations ───────────────────────────────────────────────────────────────
annotations: list[dict] = []

for dev, (y0, y1) in dev_groups.items():
    annotations.append(dict(
        xref="paper", yref="y",
        x=-0.005, y=(y0 + y1) / 2,
        text=(
            f"<b style='color:#e2e8f0;font-size:11px'>{dev[:18]}</b>"
            f"<br><span style='color:#475569;font-size:9px'>{y1-y0+1} items</span>"
        ),
        showarrow=False, xanchor="right", align="right",
        font=dict(size=11),
    ))

if WS <= today <= WE:
    annotations.append(dict(
        xref="x", yref="paper", x=str(today), y=1.015,
        text="<b>TODAY</b>", showarrow=False, xanchor="center",
        font=dict(size=9, color=TODAY_CLR),
    ))

for lbl, rd in RELEASES.items():
    if WS <= rd <= WE:
        annotations.append(dict(
            xref="x", yref="paper", x=str(rd), y=1.015,
            text=f"<b>{lbl}</b>", showarrow=False, xanchor="center",
            font=dict(size=9, color="rgba(211,111,104,0.9)", family="monospace"),
        ))

# ── Layout ────────────────────────────────────────────────────────────────────
BAR_PX  = 22           # px per row — readable at this height
CHART_H = n * BAR_PX + 120  # exact: no "max" squish

fig.update_layout(
    barmode="overlay",
    plot_bgcolor="#1a1a2e",
    paper_bgcolor="#151524",
    font=dict(family="Inter, system-ui, sans-serif", color="#8892a4", size=11),
    height=CHART_H,
    margin=dict(l=340, r=40, t=45, b=30),

    xaxis=dict(
        type="date",
        range=[WS.isoformat(), WE.isoformat()],
        gridcolor=GRID_CLR,
        tickformat="%b %Y",
        tickfont=dict(color="#475569", size=10),
        dtick="M1",
        showline=False, zeroline=False,
    ),

    yaxis=dict(
        tickvals=items["y_pos"].tolist(),
        ticktext=items["y_tick"].tolist(),
        tickfont=dict(size=9, color="#64748b"),
        showgrid=False,
        range=[n - 0.5, -0.5],   # explicit reversed: y=0 at top, y=n-1 at bottom
        showline=False, zeroline=False,
        ticklen=0,
    ),

    shapes=shapes,
    annotations=annotations,

    legend=dict(
        orientation="h",
        yanchor="bottom", y=1.02, xanchor="right", x=1,
        font=dict(size=10, color="#8892a4"),
        bgcolor="rgba(0,0,0,0)", borderwidth=0,
    ),

    hovermode="closest",
    hoverlabel=dict(
        bgcolor="#1e1e38",
        bordercolor="rgba(255,255,255,0.12)",
        font=dict(color="#e2e8f0", family="Inter, sans-serif", size=12),
    ),
)

fig_ms = (time.perf_counter() - t_fig) * 1000
print(f"Fig build  : {fig_ms:.0f} ms  (vs ~272 ms HTML Gantt warm-cache)")

# ── Write HTML ─────────────────────────────────────────────────────────────────
t_write = time.perf_counter()
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gantt_prototype.html")
fig.write_html(
    out,
    include_plotlyjs="cdn",
    default_height=f"{CHART_H}px",   # force exact height; browser scrolls
)
write_ms = (time.perf_counter() - t_write) * 1000

file_kb = os.path.getsize(out) / 1024
print(f"Write HTML : {write_ms:.0f} ms  →  {file_kb:.0f} KB on disk")
print(f"Total      : {(time.perf_counter()-t_load)*1000:.0f} ms")
print()
print(f"HTML Gantt comparison  build ~272 ms  payload ~800 KB")
print(f"Plotly fig comparison  build ~{fig_ms:.0f} ms  payload ~{file_kb:.0f} KB  (browser renders the rest)")
print()
print(f"Open in browser:  {out}")

# ══════════════════════════════════════════════════════════════════════════════
# DROP-IN REPLACEMENT FOR _build_gantt_html  (paste into planning.py)
# ══════════════════════════════════════════════════════════════════════════════
#
# Swap the callback Output from "gantt-chart.children" → "gantt-chart.figure"
# (or keep the children output but return dcc.Graph(figure=fig) instead of html.Div).
#
# def _build_gantt_fig(
#     window_start, window_end,
#     expanded_sprints, expanded_items,   # ignored — no expand/collapse in Plotly
#     dev_filter=None, type_filter="all",
#     prio_filter=None, year_filter=None,
# ):
#     from data.loader import engine
#     from sqlalchemy import text as _text
#     import numpy as np, pandas as pd, plotly.graph_objects as go
#     from dash import dcc
#
#     # ── Cache (same as HTML version) ──────────────────────────────────────────
#     _now = _time_mod.time()
#     if _GANTT_CACHE["items"] is None or _now - _GANTT_CACHE["ts"] > _GANTT_TTL:
#         with engine.connect() as _c:
#             _GANTT_CACHE["items"] = pd.read_sql(
#                 _text("SELECT * FROM agg_gantt_items ORDER BY main_developer, function, bar_start"), _c)
#             _GANTT_CACHE["tasks"] = pd.read_sql(_text("SELECT * FROM agg_gantt_tasks"), _c)
#         _GANTT_CACHE["ts"] = _now
#     df = _GANTT_CACHE["items"].copy()
#
#     # ── Apply filters (same logic as HTML version) ────────────────────────────
#     df["bar_start"] = pd.to_datetime(df["bar_start"], errors="coerce")
#     df["bar_end"]   = pd.to_datetime(df["bar_end"],   errors="coerce")
#     df["main_developer"] = df["main_developer"].fillna("Unassigned").astype(str)
#     df["function"]  = df["function"].fillna("—").astype(str)
#     df["pct"]       = pd.to_numeric(df["pct"], errors="coerce").fillna(0).astype(int)
#     if dev_filter:
#         df = df[df["main_developer"].isin(dev_filter)]
#     if type_filter == "enh":
#         df = df[df["item_type"] == "enh"]
#     elif type_filter == "bug":
#         df = df[df["item_type"] == "bug"]
#     # ... prio_filter, year_filter same as HTML version ...
#     if df.empty:
#         return dcc.Graph(figure=go.Figure(), style={"height": "200px"})
#
#     # ── Clip + progress split (vectorised) ───────────────────────────────────
#     WS_ts = pd.Timestamp(window_start); WE_ts = pd.Timestamp(window_end)
#     df["s"] = df["bar_start"].clip(lower=WS_ts, upper=WE_ts)
#     df["e"] = df["bar_end"].clip(lower=WS_ts,   upper=WE_ts)
#     df = df[df["s"] < df["e"]].reset_index(drop=True)
#     dur = (df["e"] - df["s"]).dt.days
#     done_d = (dur * df["pct"] / 100).astype(int)
#     df["rem_days"]      = dur - done_d
#     df["done_days"]     = done_d
#     df["s_str"]         = df["s"].dt.strftime("%Y-%m-%d")
#     df["done_end_str"]  = (df["s"] + pd.to_timedelta(done_d, unit="D")).dt.strftime("%Y-%m-%d")
#
#     # ── Sort + Y positions ────────────────────────────────────────────────────
#     df = df.sort_values(["main_developer", "function", "s"]).reset_index(drop=True)
#     df["y_pos"]  = np.arange(len(df))
#     df["y_tick"] = [f"[{'BUG' if t=='bug' else 'ENH'}]  {tl[:48]}"
#                     for t, tl in zip(df["item_type"].values, df["title"].fillna("").values)]
#
#     # ── Figure (same trace logic as prototype above) ──────────────────────────
#     fig = go.Figure()
#     # ... add traces, shapes, annotations ...
#     # ... update_layout ...
#
#     CHART_H = max(500, len(df) * 18 + 80)
#     return dcc.Graph(
#         figure=fig,
#         config={"displayModeBar": False, "scrollZoom": False},
#         style={"height": f"{CHART_H}px", "overflowY": "auto"},
#     )
