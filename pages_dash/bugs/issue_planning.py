"""Bugs & Issues — Issue Planning"""
from __future__ import annotations

import re
import dash
from dash import dcc, html, Input, Output, State, callback, ALL, ctx, no_update
from dash.exceptions import PreventUpdate
import pandas as pd
from datetime import date
from sqlalchemy import text

from config.dev_capacity import DEV_NAMES, DESIGNER_NAMES, STORY_OWNER_NAMES
from data.loader import engine
from sync.ado_write import write_fields as _ado_write

dash.register_page(__name__, path="/issue-planning", name="Issue Planning")

_TX = "var(--text-primary)"
_MT = "var(--text-secondary)"
_BD = "var(--border)"
_C3 = "var(--bg-base)"
_C2 = "var(--bg-hover)"
_C1 = "var(--bg-surface)"

_PRI_COLORS = {"P1": "#ef6e63", "P2": "#e0a23c", "P3": "#6e76f1", "Other": "#8b92a4"}
_PRI_RGB    = {"P1": "239,110,99", "P2": "224,162,60", "P3": "110,118,241", "Other": "139,146,164"}
_SRC_COLORS = {"Customer": "rgb(240,137,122)", "Internal": "rgb(63,182,201)"}
_CAP_OPTIONS = [2, 4, 6, 8]

_SIZES = ["Big", "Medium", "Small", "Very Small"]
_SIZE_COLORS = {
    "Big":        "rgb(224,162,60)",
    "Medium":     "rgb(181,194,74)",
    "Small":      "rgb(70,194,142)",
    "Very Small": "rgb(63,182,201)",
}

def _current_ym():
    return date.today().strftime("%Y-%m")

_ALL_MONTH_OPTIONS = [
    "Jan 2026","Feb 2026","Mar 2026","Apr 2026","May 2026","Jun 2026",
    "Jul 2026","Aug 2026","Sep 2026","Oct 2026","Nov 2026","Dec 2026",
    "Jan 2027","Feb 2027","Mar 2027","Apr 2027","May 2027","Jun 2027",
]

_PANEL_BASE = {
    "position": "fixed", "top": "0", "right": "0", "height": "100vh", "width": "760px",
    "background": _C2, "borderLeft": "1px solid rgba(255,255,255,0.10)", "zIndex": "1060",
    "display": "flex", "flexDirection": "column", "boxShadow": "-16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_PANEL_OPEN   = dict(_PANEL_BASE, transform="translateX(0%)")
_PANEL_CLOSED = dict(_PANEL_BASE, transform="translateX(110%)")

_DEV_PANEL_BASE = {
    "position": "fixed", "top": "0", "right": "0", "height": "100vh", "width": "760px",
    "background": _C2, "borderLeft": "1px solid rgba(255,255,255,0.10)", "zIndex": "1070",
    "display": "flex", "flexDirection": "column", "boxShadow": "-16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
}
_DEV_PANEL_OPEN   = dict(_DEV_PANEL_BASE, transform="translateX(0%)")
_DEV_PANEL_CLOSED = dict(_DEV_PANEL_BASE, transform="translateX(110%)")

_BACKDROP_BASE = {
    "position": "fixed", "top": "0", "left": "0", "width": "100vw", "height": "100vh",
    "background": "rgba(0,0,0,0.50)", "zIndex": "1055", "transition": "opacity 0.28s ease",
}
_BACKDROP_OPEN   = dict(_BACKDROP_BASE, opacity="1",  pointerEvents="all")
_BACKDROP_CLOSED = dict(_BACKDROP_BASE, opacity="0",  pointerEvents="none")

_BTN = {
    "background": "none", "border": "none", "cursor": "pointer",
    "fontSize": "12px", "fontWeight": "600", "padding": "5px 14px",
    "borderRadius": "6px", "letterSpacing": "0.04em",
    "transition": "background 0.15s, color 0.15s",
}

# ── Data helpers ──────────────────────────────────────────────────────────────

def _clean_dev(name):
    return str(name or "").split(" <")[0].strip()

def _pri_label(n):
    try: n = int(n)
    except (TypeError, ValueError): return "Other"
    if n == 1: return "P1"
    if n == 2: return "P2"
    if n == 3: return "P3"
    return "Other"

def _pri_int(label):
    return {"P1": 1, "P2": 2, "P3": 3}.get(label, 4)

def _parse_release_ym(rd):
    s = str(rd).strip()
    if not s or s in ("None", "nan", ""):
        return ""
    # Handle "2026 March 2nd"-style strings with an ordinal day — drop from 3rd word
    parts = s.split()
    if len(parts) >= 3:
        s2 = " ".join(parts[:2])
        result = _parse_release_ym(s2)
        if result:
            return result
    for fmt in ("%Y %B", "%Y %b", "%b %Y", "%B %Y", "%b-%y", "%b-%Y", "%Y-%m-%d", "%Y-%m"):
        try: return pd.to_datetime(s, format=fmt).strftime("%Y-%m")
        except Exception: pass
    try: return pd.to_datetime(s).strftime("%Y-%m")
    except Exception: pass
    return ""

def _load_issues():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT work_item_id, title, work_item_type, state,
                   priority, assigned_to, COALESCE(type,'') AS source_type,
                   COALESCE(iteration_path,'') AS iteration,
                   COALESCE(release_date,'') AS release_date,
                   COALESCE(story_size,'') AS story_size,
                   COALESCE(story_owner,'') AS story_owner,
                   COALESCE(main_designer,'') AS main_designer
            FROM work_items_main
            WHERE work_item_type IN ('Bug','Bug_UI','Bug_Text')
              AND state IN (
                'New','Request Estimate','Estimated','Clarification',
                'Active','Dev InProgress','Dev Review','Dev Complete',
                'reopened'
              )
            ORDER BY priority NULLS LAST, work_item_id
        """)).fetchall()
    issues = []
    for r in rows:
        dev = _clean_dev(r.assigned_to)
        pri = _pri_label(r.priority)
        rd  = str(r.release_date or "")
        issues.append({
            "id":           int(r.work_item_id),
            "title":        str(r.title or "")[:120] or "(No title)",
            "type":         str(r.work_item_type or "Bug"),
            "state":        str(r.state or ""),
            "priority":     pri,
            "developer":    dev,
            "source":       str(r.source_type or "").capitalize(),
            "iteration":    str(r.iteration or ""),
            "release_date": rd,
            "release_ym":   _parse_release_ym(rd),
            "story_size":    str(r.story_size or ""),
            "story_owner":   str(r.story_owner or ""),
            "main_designer": str(r.main_designer or ""),
        })
    return issues

def _get_iterations():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT iteration_path FROM work_items_main"
            " WHERE iteration_path IS NOT NULL AND iteration_path != ''"
            " ORDER BY iteration_path"
        )).fetchall()
    return [r.iteration_path for r in rows]

def _update_issue_local(wid, fields):
    col_map = {
        "priority":     "priority",
        "developer":    "assigned_to",
        "iteration":    "iteration_path",
        "release_date": "release_date",
        "source":       "type",
        "story_size":   "story_size",
        "story_owner":  "story_owner",
        "main_designer": "main_designer",
    }
    sets, params = [], {"wid": wid}
    for k, v in fields.items():
        col = col_map.get(k)
        if col:
            sets.append(f"{col} = :{k}")
            params[k] = v
    if not sets:
        return
    with engine.connect() as conn:
        conn.execute(text(f"UPDATE work_items_main SET {', '.join(sets)} WHERE work_item_id = :wid"), params)
        conn.commit()

# ── UI helpers ────────────────────────────────────────────────────────────────

def _kpi_card(label, count, sub, color, filt_key):
    return html.Div([
        html.Div(str(count), style={"fontSize": "32px", "fontWeight": "800", "color": color, "lineHeight": "1"}),
        html.Div(label, style={"fontSize": "9px", "fontWeight": "700", "color": _MT, "letterSpacing": "0.10em", "marginTop": "4px"}),
        html.Div(sub,   style={"fontSize": "10px", "color": _MT, "marginTop": "2px"}),
    ], id={"type": "ip-kpi", "key": filt_key}, n_clicks=0, style={
        "background": _C1, "border": f"1px solid {_BD}", "borderRadius": "10px",
        "padding": "14px 18px", "cursor": "pointer", "flex": "1", "minWidth": "100px",
        "transition": "border-color .15s",
    })

def _build_kpi_row(issues):
    total      = len(issues)
    p1         = [x for x in issues if x["priority"] == "P1"]
    p2         = [x for x in issues if x["priority"] == "P2"]
    p3         = [x for x in issues if x["priority"] == "P3"]
    other      = [x for x in issues if x["priority"] == "Other"]
    unassigned = [x for x in issues if not x["developer"]]
    cur        = _current_ym()
    past_due   = [x for x in issues if x["release_ym"] and x["release_ym"] < cur]
    def _sub(lst):
        cust = sum(1 for x in lst if x["source"] == "Customer")
        intr = sum(1 for x in lst if x["source"] == "Internal")
        return f"{cust} customer  {intr} internal"
    return html.Div([
        _kpi_card("ALL ISSUES",  total,           _sub(issues),       _TX,                  "all"),
        _kpi_card("P1 ISSUES",   len(p1),         _sub(p1),           _PRI_COLORS["P1"],    "P1"),
        _kpi_card("P2 ISSUES",   len(p2),         _sub(p2),           _PRI_COLORS["P2"],    "P2"),
        _kpi_card("P3 ISSUES",   len(p3),         _sub(p3),           _PRI_COLORS["P3"],    "P3"),
        _kpi_card("OTHER",       len(other),      _sub(other),        _PRI_COLORS["Other"], "Other"),
        _kpi_card("UNASSIGNED",  len(unassigned), f"{total} total open", "#94a3b8",         "unassigned"),
        _kpi_card("PAST DUE",    len(past_due),   "release date in past", "#f59e0b",        "past_due"),
    ], style={"display": "flex", "gap": "12px", "marginBottom": "24px"})

_INDIGO = "#6e76f1"
_INDIGO_DIM = "rgb(23,28,40)"

def _build_dev_load(issues, dev_cfg, caps):
    total_cap = sum(caps.get(p, 4) for p in ("P1", "P2", "P3", "Other"))
    counts = {}
    for iss in issues:
        if iss["developer"]:
            counts[iss["developer"]] = counts.get(iss["developer"], 0) + 1

    cells = []
    for cfg in dev_cfg:
        dev   = cfg["developer"]
        order = cfg["priority_order"]
        cnt   = counts.get(dev, 0)
        pct   = min(cnt / total_cap, 1.0) if total_cap else 0
        # Determine bar color: green when under cap, amber when near, red when over
        if pct > 1.0:
            bar_c = "#f87171"
        elif pct >= 0.85:
            bar_c = "#f59e0b"
        else:
            bar_c = _INDIGO

        short_name = dev.split()[0]  # first name only for the button label

        cells.append(html.Div([
            # Dev button: order number + first name, click opens permissions panel
            html.Button([
                html.Span(str(order), style={
                    "color": _INDIGO, "fontFamily": "'JetBrains Mono','SF Mono',monospace",
                    "fontWeight": "700", "marginRight": "5px",
                }),
                short_name,
            ], id={"type": "ip-dev-load-btn", "dev": dev},
               n_clicks=0,
               title=f"Click to set developer priority & permissions",
               style={
                   "width": "122px", "flexShrink": "0", "textAlign": "left",
                   "padding": "3px 7px", "borderRadius": "6px", "cursor": "pointer",
                   "fontSize": "11.5px", "fontWeight": "600",
                   "fontFamily": "Inter, system-ui, sans-serif",
                   "background": _INDIGO_DIM, "color": _TX,
                   "border": f"1px solid {_BD}",
                   "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis",
               }),
            # Progress bar
            html.Div(
                html.Div(style={"width": f"{int(pct*100)}%", "height": "100%", "background": bar_c}),
                style={
                    "flex": "1", "minWidth": "24px", "height": "7px",
                    "borderRadius": "4px", "background": _INDIGO_DIM, "overflow": "hidden",
                }),
            # Count
            html.Span(f"{cnt}/{total_cap}", style={
                "width": "44px", "textAlign": "right",
                "fontFamily": "'JetBrains Mono','SF Mono',monospace",
                "fontSize": "11px", "fontWeight": "700",
                "color": "#f87171" if pct > 1.0 else _INDIGO,
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px"}))

    return html.Div([
        html.Div([
            html.Span("Developer load · total vs cap", style={
                "fontSize": "11px", "color": _MT, "textTransform": "uppercase",
                "letterSpacing": "0.6px", "fontWeight": "700",
            }),
            html.Span("Click a name for priority & permissions →", style={
                "fontSize": "10.5px", "color": "rgb(91,98,118)", "cursor": "pointer",
            }),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "baseline", "marginBottom": "9px"}),
        html.Div(cells, style={
            "display": "grid", "gridTemplateColumns": "repeat(2, 300px)",
            "gap": "8px 24px", "alignContent": "space-between",
        }),
    ], id="ip-dev-load-section", style={
        "background": "rgb(18,22,31)", "border": f"1px solid {_BD}",
        "borderRadius": "12px", "padding": "12px 14px",
        "display": "flex", "flexDirection": "column",
    })

def _build_caps_section(caps):
    total = sum(caps.get(p, 4) for p in ("P1", "P2", "P3", "Other"))

    def _cap_row(pri):
        cap     = caps.get(pri, 4)
        col     = _PRI_COLORS.get(pri, "#8b92a4")
        rgb     = _PRI_RGB.get(pri, "139,146,164")
        btns    = []
        for opt in _CAP_OPTIONS:
            active = (opt == cap)
            btns.append(html.Button(str(opt),
                id={"type": "ip-cap-btn", "pri": pri, "val": opt}, n_clicks=0,
                style={
                    "flex": "1", "padding": "4px 0", "borderRadius": "5px",
                    "cursor": "pointer", "fontSize": "11px", "fontWeight": "700",
                    "fontFamily": _MONO,
                    "border": f"1px solid {col}" if active else "1px solid rgb(38,44,58)",
                    "background": f"rgba({rgb},0.133)" if active else "rgb(23,28,40)",
                    "color": "rgb(234,236,242)" if active else "rgb(139,146,164)",
                }))
        return html.Div([
            html.Span(pri, style={
                "width": "34px", "flexShrink": "0",
                "fontSize": "10.5px", "fontWeight": "700", "color": col,
            }),
            html.Div(btns, style={"display": "flex", "gap": "3px", "flex": "1"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "7px"})

    return html.Div([
        html.Div("Caps per developer", style={
            "fontSize": "11px", "color": "rgb(139,146,164)",
            "textTransform": "uppercase", "letterSpacing": "0.6px",
            "fontWeight": "700", "marginBottom": "9px",
        }),
        # Single-column stack — panel is too narrow for 2-col grid
        html.Div([
            _cap_row("P1"), _cap_row("P2"),
            _cap_row("P3"), _cap_row("Other"),
        ], style={
            "display": "flex", "flexDirection": "column", "gap": "7px", "flex": "1",
        }),
        html.Div(style={"height": "1px", "background": "rgb(30,36,51)", "margin": "8px 0"}),
        # Total row — read-only computed sum
        html.Div([
            html.Span("Total", style={
                "width": "34px", "flexShrink": "0",
                "fontSize": "10px", "fontWeight": "700", "color": "rgb(234,236,242)",
                "textTransform": "uppercase", "letterSpacing": "0.2px",
            }),
            html.Div(html.Span(str(total), style={
                "fontFamily": _MONO, "fontSize": "13px", "fontWeight": "700",
                "color": "rgb(110,118,241)",
            }), style={"flex": "1", "display": "flex", "alignItems": "center"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "7px"}),
    ], id="ip-caps-section", style={
        "background": "rgb(18,22,31)", "border": "1px solid rgb(38,44,58)",
        "borderRadius": "12px", "padding": "12px 14px",
        "display": "flex", "flexDirection": "column", "flex": "1",
    })

_TH_BASE = {
    "padding": "9px 11px", "fontSize": "10px", "fontWeight": "700",
    "color": "rgb(91,98,118)", "textTransform": "uppercase",
    "letterSpacing": "0.4px", "whiteSpace": "nowrap",
    "background": "rgb(23,28,40)",
}
_TD_BASE = {
    "padding": "9px 11px", "borderBottom": "1px solid rgb(30,36,51)",
    "fontSize": "12.5px", "verticalAlign": "middle",
}
_MONO = "'JetBrains Mono','SF Mono',monospace"
_BG_ROW = "rgb(18,22,31)"

def _th(extra=None):
    s = dict(_TH_BASE)
    if extra:
        s.update(extra)
    return s

def _td(extra=None):
    s = dict(_TD_BASE)
    if extra:
        s.update(extra)
    return s

def _build_table(issues, active_filter="all"):
    cur = _current_ym()
    if active_filter and active_filter != "all":
        if active_filter == "unassigned":
            rows_data = [x for x in issues if not x["developer"]]
        elif active_filter == "past_due":
            rows_data = [x for x in issues if x["release_ym"] and x["release_ym"] < cur]
        else:
            rows_data = [x for x in issues if x["priority"] == active_filter]
    else:
        rows_data = issues

    release_yms = {x["release_ym"] for x in issues if x["release_ym"]}
    month_cols  = []
    for m in _ALL_MONTH_OPTIONS:
        try:
            ym = pd.to_datetime(m, format="%b %Y").strftime("%Y-%m")
        except Exception:
            continue
        if ym.startswith("2026") or ym in release_yms:
            month_cols.append((m[:3].upper() + "-" + m[-2:], ym))

    # ── Header ────────────────────────────────────────────────────────────────
    _SBG = "rgb(23,28,40)"  # sticky header background
    header_cells = [
        html.Th("#", style=_th({"textAlign": "center", "width": "40px",
            "position": "sticky", "left": "0", "zIndex": 3, "background": _SBG})),
        html.Th("VSTS ID", style=_th({"width": "60px",
            "position": "sticky", "left": "40px", "zIndex": 3, "background": _SBG})),
        html.Th("Item details", style=_th({"minWidth": "250px",
            "position": "sticky", "left": "100px", "zIndex": 3, "background": _SBG,
            "borderRight": "1px solid rgb(38,44,58)"})),
        html.Th("Priority",      style=_th({"textAlign": "center", "width": "66px"})),
        html.Th("Source",        style=_th({"width": "88px"})),
        html.Th("Developer",     style=_th({"width": "110px"})),
        html.Th("Iteration",     style=_th({"width": "92px"})),
        html.Th("Release month", style=_th({"width": "96px"})),
    ]
    for label, _ in month_cols:
        header_cells.append(html.Th(label, style=_th({
            "textAlign": "center", "minWidth": "60px",
            "borderLeft": "1px solid rgb(30,36,51)",
        })))

    # ── Rows ──────────────────────────────────────────────────────────────────
    trs = []
    for i, iss in enumerate(rows_data):
        pri     = iss["priority"]
        pri_col = _PRI_COLORS.get(pri, "#6b7280")
        pri_rgb = _PRI_RGB.get(pri, "107,114,128")
        dev     = iss["developer"] or "—"
        itr     = iss["iteration"].split("\\")[-1] if iss["iteration"] else "—"
        ym      = iss["release_ym"]
        src     = iss["source"] or "—"
        is_past = bool(ym and ym < cur)

        # Release month display label  e.g. "2026-01" → "Jan-26"
        rm_label = ""
        if ym:
            try:
                rm_label = pd.to_datetime(ym, format="%Y-%m").strftime("%b-%y")
            except Exception:
                rm_label = ym

        # Month matrix cells
        mo_cells = []
        for _, mc_ym in month_cols:
            if mc_ym == ym:
                if is_past:
                    mo_cells.append(html.Td(
                        html.Span(pri, style={"fontSize": "9.5px", "fontWeight": "700", "color": "#f59e0b"}),
                        style=_td({"textAlign": "center", "minWidth": "60px",
                            "borderLeft": "1px solid rgb(30,36,51)",
                            "background": "rgba(245,158,11,0.13)",
                            "boxShadow": "rgba(245,158,11,0.33) 0px 0px 0px 1px inset"}),
                    ))
                else:
                    mo_cells.append(html.Td(
                        html.Span(pri, style={"fontSize": "9.5px", "fontWeight": "700", "color": pri_col}),
                        style=_td({"textAlign": "center", "minWidth": "60px",
                            "borderLeft": "1px solid rgb(30,36,51)",
                            "background": f"rgba({pri_rgb},0.133)",
                            "boxShadow": f"rgba({pri_rgb},0.333) 0px 0px 0px 1px inset"}),
                    ))
            else:
                mo_cells.append(html.Td("", style=_td({
                    "textAlign": "center", "minWidth": "60px",
                    "borderLeft": "1px solid rgb(30,36,51)",
                    "background": "transparent", "boxShadow": "none",
                })))

        # Source badge color
        src_color = _SRC_COLORS.get(src, "rgb(139,146,164)")

        # Priority badge
        pri_badge = html.Span(pri, style={
            "fontSize": "11px", "fontWeight": "700",
            "padding": "2px 9px", "borderRadius": "5px",
            "background": f"rgba({pri_rgb},0.133)",
            "color": pri_col,
            "border": f"1px solid rgba({pri_rgb},0.333)",
        })

        trs.append(html.Tr([
            # # — sticky, left border = priority color
            html.Td(str(i + 1), style=_td({
                "textAlign": "center", "fontFamily": _MONO,
                "color": "rgb(91,98,118)", "fontSize": "11px",
                "position": "sticky", "left": "0", "zIndex": 2, "background": _BG_ROW,
                "borderLeft": f"2px solid {pri_col}",
            })),
            # VSTS ID — sticky indigo monospace
            html.Td(str(iss["id"]), style=_td({
                "fontFamily": _MONO, "color": "rgb(110,118,241)",
                "fontWeight": "700", "fontSize": "12.5px",
                "position": "sticky", "left": "40px", "zIndex": 2, "background": _BG_ROW,
            })),
            # Item details — sticky, title text
            html.Td(iss["title"], style=_td({
                "color": "rgb(234,236,242)",
                "position": "sticky", "left": "100px", "zIndex": 2, "background": _BG_ROW,
                "minWidth": "250px", "maxWidth": "340px",
                "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
                "borderRight": "1px solid rgb(38,44,58)",
            })),
            # Priority badge
            html.Td(pri_badge, style=_td({"textAlign": "center"})),
            # Source
            html.Td(html.Span(src, style={"fontSize": "11px", "fontWeight": "700", "color": src_color}),
                    style=_td()),
            # Developer
            html.Td(
                html.Span(dev, style={"color": "rgb(91,98,118)"}) if dev == "—"
                else dev,
                style=_td(),
            ),
            # Iteration
            html.Td(itr, style=_td({"fontSize": "11.5px", "color": "rgb(139,146,164)"})),
            # Release month
            html.Td(rm_label, style=_td({
                "fontSize": "11.5px", "color": "rgb(139,146,164)",
                "fontFamily": _MONO,
            })),
            *mo_cells,
        ], id={"type": "ip-row", "id": iss["id"]}, n_clicks=0,
           style={"cursor": "pointer", "background": "transparent"}))

    if not trs:
        trs = [html.Tr([html.Td("No open issues match this filter.",
            colSpan=8 + len(month_cols),
            style=_td({"textAlign": "center", "color": "rgb(91,98,118)", "padding": "32px"}))])]

    return html.Div(
        html.Table(
            [html.Thead(html.Tr(header_cells, style={"background": "rgb(23,28,40)"})),
             html.Tbody(trs)],
            style={"borderCollapse": "collapse", "width": "100%", "minWidth": "1400px"},
        ),
        style={
            "border": "1px solid rgb(38,44,58)", "borderRadius": "12px", "overflowX": "auto",
        },
    )

def _build_dev_panel_rows(dev_cfg):
    rows = []
    for cfg in dev_cfg:
        dev = cfg["developer"]
        toggles = []
        for pri_key, label in [("can_p1","P1"),("can_p2","P2"),("can_p3","P3"),("can_other","Other")]:
            on  = bool(cfg.get(pri_key, True))
            clr = _PRI_COLORS.get(label, "#6b7280")
            toggles.append(html.Button(label,
                id={"type": "ip-perm-toggle", "dev": dev, "pri": pri_key}, n_clicks=0,
                style=dict(_BTN,
                    padding="4px 8px",
                    color=clr if on else _MT,
                    background=f"{clr}22" if on else "rgba(255,255,255,0.04)",
                    border=f"1px solid {clr}55" if on else f"1px solid {_BD}",
                )))
        rows.append(html.Div([
            html.Div([
                html.Button("up",   id={"type": "ip-dev-up",   "dev": dev}, n_clicks=0,
                            style=dict(_BTN, padding="2px 6px", color=_MT, fontSize="10px")),
                html.Button("dn",   id={"type": "ip-dev-down", "dev": dev}, n_clicks=0,
                            style=dict(_BTN, padding="2px 6px", color=_MT, fontSize="10px")),
            ], style={"display": "flex", "flexDirection": "column", "gap": "2px", "marginRight": "8px"}),
            html.Span(str(cfg["priority_order"]), style={"fontSize": "11px", "color": _MT, "minWidth": "20px", "textAlign": "center", "fontWeight": "700"}),
            html.Span(dev, style={"flex": "1", "fontSize": "13px", "color": _TX, "fontWeight": "600", "marginLeft": "8px"}),
            html.Div(toggles, style={"display": "flex", "gap": "4px"}),
        ], style={"display": "flex", "alignItems": "center", "padding": "8px 0", "borderBottom": f"1px solid {_BD}"}))
    return rows

# ── Layout ────────────────────────────────────────────────────────────────────

def layout(**_):
    from db.issue_planning import load_caps, load_dev_config
    issues  = _load_issues()
    caps    = load_caps()
    dev_cfg = load_dev_config()
    iters   = _get_iterations()

    return html.Div([
        dcc.Store(id="ip-issues-store", data=issues),
        dcc.Store(id="ip-caps-store",   data=caps),
        dcc.Store(id="ip-devcfg-store", data=dev_cfg),
        dcc.Store(id="ip-iters-store",  data=iters),
        dcc.Store(id="ip-panel-id",     data=None),
        dcc.Store(id="ip-pending",      data={}),
        dcc.Store(id="ip-initial",      data={}),
        dcc.Store(id="ip-kpi-filter",   data="all"),
        dcc.Download(id="ip-past-due-download"),

        html.Div(id="ip-backdrop",     n_clicks=0, style=_BACKDROP_CLOSED),
        html.Div(id="ip-dev-backdrop", n_clicks=0, style=dict(_BACKDROP_CLOSED, zIndex="1065")),

        # Issue side panel
        html.Div([
            html.Div([
                html.Div(id="ip-panel-title", style={"fontWeight": "700", "fontSize": "14px", "color": _TX, "flex": "1"}),
                html.Button("X", id="ip-panel-close", n_clicks=0, style={"background": "none", "border": "none", "color": _MT, "fontSize": "18px", "cursor": "pointer", "padding": "2px 8px"}),
            ], style={"display": "flex", "alignItems": "center", "padding": "18px 20px 14px", "borderBottom": f"1px solid {_BD}", "flexShrink": "0"}),
            html.Div(id="ip-panel-body", style={"overflowY": "auto", "flex": "1", "padding": "16px 20px"}),
        ], id="ip-side-panel", style=_PANEL_CLOSED),

        # Dev permissions panel
        html.Div([
            html.Div([
                html.Div("DEVELOPER PRIORITY & PERMISSIONS", style={"fontWeight": "700", "fontSize": "12px", "letterSpacing": "0.08em", "color": _TX, "flex": "1"}),
                html.Button("X", id="ip-dev-panel-close", n_clicks=0, style={"background": "none", "border": "none", "color": _MT, "fontSize": "18px", "cursor": "pointer", "padding": "2px 8px"}),
            ], style={"display": "flex", "alignItems": "center", "padding": "18px 20px 14px", "borderBottom": f"1px solid {_BD}", "flexShrink": "0"}),
            html.Div("Top developers are assigned first. Toggle which priorities each developer can receive.",
                     style={"fontSize": "11px", "color": _MT, "padding": "10px 20px 6px", "flexShrink": "0"}),
            html.Div(id="ip-dev-panel-body", children=_build_dev_panel_rows(dev_cfg),
                     style={"overflowY": "auto", "flex": "1", "padding": "0 20px 16px"}),
        ], id="ip-dev-panel", style=_DEV_PANEL_CLOSED),

        # Header
        html.Div("BUGS & ISSUES  ISSUE PLANNING", style={"fontSize": "10px", "fontWeight": "700", "color": _MT, "letterSpacing": "0.12em", "marginBottom": "6px"}),
        html.Div([
            html.Div("Issue Planning", style={"fontSize": "26px", "fontWeight": "700", "color": _TX, "display": "inline", "marginRight": "12px"}),
            html.Span("LIVE", style={"fontSize": "11px", "fontWeight": "700", "color": "var(--green)", "background": "rgba(52,211,153,0.13)", "border": "1px solid rgba(52,211,153,0.35)", "borderRadius": "6px", "padding": "3px 10px", "verticalAlign": "middle"}),
            html.Button("AUTO-ASSIGN", id="ip-auto-assign-btn", n_clicks=0, style=dict(_BTN, color=_TX, fontWeight="700", background="rgba(52,211,153,0.15)", border="1px solid rgba(52,211,153,0.4)", marginLeft="16px", verticalAlign="middle")),
            html.Button("CLEAR ALL",   id="ip-clear-btn",       n_clicks=0, style=dict(_BTN, color="#f87171", fontWeight="700", background="rgba(248,113,113,0.12)", border="1px solid rgba(248,113,113,0.35)", marginLeft="8px", verticalAlign="middle")),
        ], style={"marginBottom": "6px"}),
        html.Div("Open bugs & issues — click any row to assign priority, developer, or iteration.",
                 style={"fontSize": "13px", "color": _MT, "marginBottom": "20px"}),

        html.Div(id="ip-kpi-row", children=_build_kpi_row(issues)),

        html.Div([
            _build_dev_load(issues, dev_cfg, caps),
            _build_caps_section(caps),
        ], style={"display": "flex", "gap": "16px", "marginBottom": "24px"}),

        html.Div(id="ip-table-wrap", children=_build_table(issues)),

    ], style={"padding": "24px 32px", "background": _C3, "minHeight": "100vh", "fontFamily": "Inter, system-ui, sans-serif"})

# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("ip-caps-store",   "data"),
    Output("ip-caps-section", "children"),
    Input({"type": "ip-cap-btn", "pri": ALL, "val": ALL}, "n_clicks"),
    State("ip-caps-store", "data"),
    prevent_initial_call=True,
)
def _cap_click(clicks, caps):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    from db.issue_planning import save_cap
    pri, val = tid["pri"], int(tid["val"])
    save_cap(pri, val)
    new_caps = dict(caps, **{pri: val})
    return new_caps, _build_caps_section(new_caps).children


@callback(
    Output("ip-kpi-filter", "data"),
    Output("ip-table-wrap", "children", allow_duplicate=True),
    Input({"type": "ip-kpi", "key": ALL}, "n_clicks"),
    State("ip-issues-store", "data"),
    State("ip-kpi-filter",   "data"),
    prevent_initial_call=True,
)
def _kpi_filter(clicks, issues, current_filt):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    new_filt = tid["key"]
    if new_filt == "past_due":
        raise PreventUpdate
    if new_filt == current_filt:
        new_filt = "all"
    return new_filt, _build_table(issues, new_filt)


@callback(
    Output("ip-past-due-download", "data"),
    Input({"type": "ip-kpi", "key": ALL}, "n_clicks"),
    State("ip-issues-store", "data"),
    prevent_initial_call=True,
)
def _past_due_download(clicks, issues):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict) or tid.get("key") != "past_due":
        raise PreventUpdate
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    import io, base64
    cur = _current_ym()
    rows = [
        x for x in (issues or [])
        if x["release_ym"] and x["release_ym"] < cur
    ]
    df = pd.DataFrame([{
        "ID":          r["id"],
        "Title":       r["title"],
        "State":       r["state"],
        "Priority":    r["priority"],
        "Assigned To": r["developer"] or "Unassigned",
        "Release YM":  r["release_ym"],
    } for r in rows])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode()
    return {
        "content":  encoded,
        "filename": "past_due_issues.xlsx",
        "type":     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "base64":   True,
    }


@callback(
    Output("ip-panel-id",   "data"),
    Output("ip-side-panel", "style"),
    Output("ip-backdrop",   "style"),
    Output("ip-pending",    "data"),
    Output("ip-initial",    "data"),
    Input({"type": "ip-row", "id": ALL}, "n_clicks"),
    Input("ip-panel-close", "n_clicks"),
    Input("ip-backdrop",    "n_clicks"),
    State("ip-panel-id",    "data"),
    State("ip-issues-store", "data"),
    prevent_initial_call=True,
)
def _toggle_issue_panel(row_clicks, close_clk, bd_clk, panel_id, issues):
    tid = ctx.triggered_id
    if tid in ("ip-panel-close", "ip-backdrop"):
        return None, _PANEL_CLOSED, _BACKDROP_CLOSED, {}, {}
    if isinstance(tid, dict) and tid.get("type") == "ip-row":
        # Guard: component recreated (n_clicks reset to 0) — not a real user click
        if not ctx.triggered[0]["value"]:
            raise PreventUpdate
        new_id = tid["id"]
        if new_id == panel_id:
            return None, _PANEL_CLOSED, _BACKDROP_CLOSED, {}, {}
        # Snapshot current DB values so dropdown callbacks can guard against initial render
        iss = next((x for x in (issues or []) if x["id"] == new_id), None)
        initial = {}
        if iss:
            initial["iteration"]    = (iss.get("iteration") or "").strip()
            initial["release_date"] = (iss.get("release_date") or "").strip()
        return new_id, _PANEL_OPEN, _BACKDROP_OPEN, {}, initial
    raise PreventUpdate


@callback(
    Output("ip-panel-title", "children"),
    Output("ip-panel-body",  "children"),
    Input("ip-panel-id",     "data"),
    Input("ip-pending",      "data"),
    State("ip-issues-store", "data"),
    State("ip-iters-store",  "data"),
)
def _render_issue_panel(panel_id, pending, issues, iters):
    if not panel_id:
        return "", []
    iss = next((x for x in issues if x["id"] == panel_id), None)
    if not iss:
        return f"#{panel_id}", [html.Div("Not found.", style={"color": _MT})]

    pending = pending or {}

    # Merge pending over stored values
    eff_pri      = pending.get("priority",     iss["priority"])
    eff_source   = pending.get("source",       iss["source"] or "Internal")
    eff_dev      = pending.get("developer",    iss["developer"] or "")
    eff_itr      = pending.get("iteration",    iss["iteration"])
    eff_rd       = pending.get("release_date", iss["release_date"] or "")
    eff_size     = pending.get("story_size",   iss["story_size"])
    eff_owner    = pending.get("story_owner",  iss["story_owner"] or "")
    eff_designer = pending.get("main_designer", iss["main_designer"] or "")
    n_pending    = len(pending)

    def _sec(label):
        return html.Div(label, style={
            "fontSize": "10px", "fontWeight": "700", "color": _MT,
            "letterSpacing": "0.08em", "marginBottom": "6px", "marginTop": "14px",
        })

    def _rgb_str(color: str) -> str:
        if color.startswith("#"):
            h = color.lstrip("#")
            return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
        m = re.search(r'(\d+),\s*(\d+),\s*(\d+)', color)
        return f"{m.group(1)},{m.group(2)},{m.group(3)}" if m else "96,165,250"

    def _tog_btn(label, id_dict, active, color="#60a5fa"):
        rgb_str = _rgb_str(color)
        return html.Button(label,
            id=id_dict, n_clicks=0,
            style=dict(_BTN, fontSize="12px",
                color=color if active else _MT,
                background=f"rgba({rgb_str},0.15)" if active else "rgba(255,255,255,0.04)",
                border=f"1px solid rgba({rgb_str},0.5)" if active else f"1px solid {_BD}",
            ))

    # Priority buttons
    pri_btns = [
        _tog_btn(opt, {"type": "ip-pri-toggle", "wid": panel_id, "opt": opt},
                 active=(opt == eff_pri), color=_PRI_COLORS.get(opt, "#8b92a4"))
        for opt in ["P1", "P2", "P3", "Other"]
    ]

    # Source buttons
    src_btns = [
        _tog_btn(opt, {"type": "ip-src-toggle", "wid": panel_id, "opt": opt},
                 active=(opt == eff_source), color=_SRC_COLORS.get(opt, "#60a5fa"))
        for opt in ["Customer", "Internal"]
    ]

    # Developer buttons
    dev_btns = []
    for d in list(DEV_NAMES) + ["Unassign"]:
        active = (d == eff_dev) or (d == "Unassign" and not eff_dev)
        dev_btns.append(_tog_btn(d, {"type": "ip-dev-toggle", "wid": panel_id, "opt": d},
                                 active=active, color="rgb(96,165,250)"))

    # Story Size buttons
    size_btns = [
        _tog_btn(sz, {"type": "ip-size-toggle", "wid": panel_id, "opt": sz},
                 active=(sz == eff_size), color=_SIZE_COLORS.get(sz, "#60a5fa"))
        for sz in _SIZES
    ]

    # User Story Owner buttons
    owner_btns = [
        _tog_btn(o, {"type": "ip-owner-toggle", "wid": panel_id, "opt": o},
                 active=(o == eff_owner), color="rgb(110,118,241)")
        for o in STORY_OWNER_NAMES
    ]

    # Main Designer buttons
    designer_btns = [
        _tog_btn(d.split()[0], {"type": "ip-designer-toggle", "wid": panel_id, "opt": d},
                 active=(d == eff_designer), color="rgb(63,182,201)")
        for d in DESIGNER_NAMES
    ]

    iter_opts  = [{"label": it.split("\\")[-1], "value": it} for it in (iters or [])]
    with engine.connect() as conn:
        _rd_rows = conn.execute(text(
            "SELECT DISTINCT release_date FROM work_items_main"
            " WHERE release_date IS NOT NULL AND release_date != ''"
            " ORDER BY release_date"
        )).fetchall()
    rd_vals    = [r.release_date for r in _rd_rows]
    month_opts = [{"label": v, "value": v} for v in rd_vals]

    _GREEN = "rgb(70,194,142)"
    _RED   = "rgb(239,110,99)"

    save_btn = html.Button("Save Changes",
        id="ip-move-btn", n_clicks=0,
        disabled=(n_pending == 0),
        style={
            "padding": "10px 20px", "borderRadius": "8px", "flex": "1",
            "background": "rgba(70,194,142,0.15)" if n_pending else "rgb(23,28,40)",
            "border": "1px solid rgba(70,194,142,0.5)" if n_pending else f"1px solid {_BD}",
            "color": _GREEN if n_pending else _MT,
            "cursor": "pointer" if n_pending else "default",
            "fontSize": "13px", "fontWeight": "700",
        },
    )
    clear_btn = html.Button("Clear",
        id="ip-clear-pending-btn", n_clicks=0,
        disabled=(n_pending == 0),
        style={
            "padding": "10px 16px", "borderRadius": "8px",
            "background": "transparent",
            "border": "1px solid rgba(239,110,99,0.4)" if n_pending else f"1px solid {_BD}",
            "color": _RED if n_pending else _MT,
            "cursor": "pointer" if n_pending else "default",
            "fontSize": "13px", "fontWeight": "600",
        },
    )

    return f"#{panel_id}  {iss['type']}", [
        html.Div(iss["title"], style={
            "fontSize": "13px", "color": _MT, "marginBottom": "16px",
            "paddingBottom": "14px", "borderBottom": f"1px solid {_BD}",
        }),

        _sec("PRIORITY"),
        html.Div(pri_btns, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

        _sec("SOURCE"),
        html.Div(src_btns, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

        _sec("STORY SIZE"),
        html.Div(size_btns, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

        _sec("DEVELOPER"),
        html.Div(dev_btns, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

        _sec("MAIN DESIGNER"),
        html.Div(designer_btns, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

        _sec("USER STORY OWNER"),
        html.Div(owner_btns, style={"display": "flex", "flexWrap": "wrap", "gap": "6px"}),

        _sec("ITERATION"),
        dcc.Dropdown(id={"type": "ip-iter-dd", "wid": panel_id},
            options=iter_opts, value=eff_itr if eff_itr else None,
            placeholder="Select iteration...", clearable=True,
            className="dark-dropdown", style={"fontSize": "12px"}),

        _sec("RELEASE MONTH"),
        dcc.Dropdown(id={"type": "ip-month-dd", "wid": panel_id},
            options=month_opts,
            value=eff_rd if eff_rd in rd_vals else None,
            placeholder="Select month...", clearable=True,
            className="dark-dropdown", style={"fontSize": "12px"}),

        # Save / Clear
        html.Div([save_btn, clear_btn], style={
            "display": "flex", "gap": "8px",
            "marginTop": "28px", "paddingTop": "16px",
            "borderTop": f"1px solid {_BD}",
        }),
    ]


# ── Pending-state select callbacks ────────────────────────────────────────────

@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-pri-toggle", "wid": ALL, "opt": ALL}, "n_clicks"),
    State("ip-pending", "data"),
    prevent_initial_call=True,
)
def _select_ip_pri(clicks, pending):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    p = dict(pending or {})
    p["priority"] = tid["opt"]
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-src-toggle", "wid": ALL, "opt": ALL}, "n_clicks"),
    State("ip-pending", "data"),
    prevent_initial_call=True,
)
def _select_ip_src(clicks, pending):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    p = dict(pending or {})
    p["source"] = tid["opt"]
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-dev-toggle", "wid": ALL, "opt": ALL}, "n_clicks"),
    State("ip-pending", "data"),
    prevent_initial_call=True,
)
def _select_ip_dev(clicks, pending):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    p = dict(pending or {})
    p["developer"] = "" if tid["opt"] == "Unassign" else tid["opt"]
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-size-toggle", "wid": ALL, "opt": ALL}, "n_clicks"),
    State("ip-pending", "data"),
    prevent_initial_call=True,
)
def _select_ip_size(clicks, pending):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    p = dict(pending or {})
    p["story_size"] = tid["opt"]
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-owner-toggle", "wid": ALL, "opt": ALL}, "n_clicks"),
    State("ip-pending", "data"),
    prevent_initial_call=True,
)
def _select_ip_owner(clicks, pending):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    p = dict(pending or {})
    p["story_owner"] = tid["opt"]
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-designer-toggle", "wid": ALL, "opt": ALL}, "n_clicks"),
    State("ip-pending", "data"),
    prevent_initial_call=True,
)
def _select_ip_designer(clicks, pending):
    if not any(n and n > 0 for n in (clicks or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    p = dict(pending or {})
    p["main_designer"] = tid["opt"]
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-iter-dd", "wid": ALL}, "value"),
    State("ip-pending", "data"),
    State("ip-initial", "data"),
    prevent_initial_call=True,
)
def _select_ip_iter(iter_vals, pending, initial):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    new_val = iter_vals[0] if iter_vals else None
    p = dict(pending or {})
    if p.get("iteration") == new_val:
        raise PreventUpdate
    if new_val == (initial or {}).get("iteration") and "iteration" not in p:
        raise PreventUpdate
    p["iteration"] = new_val or ""
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input({"type": "ip-month-dd", "wid": ALL}, "value"),
    State("ip-pending", "data"),
    State("ip-initial", "data"),
    prevent_initial_call=True,
)
def _select_ip_month(month_vals, pending, initial):
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    new_val = month_vals[0] if month_vals else None
    p = dict(pending or {})
    if p.get("release_date") == new_val:
        raise PreventUpdate
    if new_val == (initial or {}).get("release_date") and "release_date" not in p:
        raise PreventUpdate
    p["release_date"] = new_val or ""
    return p


@callback(
    Output("ip-pending", "data", allow_duplicate=True),
    Input("ip-clear-pending-btn", "n_clicks"),
    prevent_initial_call=True,
)
def _clear_ip_pending(n):
    if not n:
        raise PreventUpdate
    return {}


@callback(
    Output("ip-pending",          "data",     allow_duplicate=True),
    Output("ip-issues-store",     "data",     allow_duplicate=True),
    Output("ip-table-wrap",       "children", allow_duplicate=True),
    Output("ip-kpi-row",          "children", allow_duplicate=True),
    Output("ip-dev-load-section", "children", allow_duplicate=True),
    Input("ip-move-btn",          "n_clicks"),
    State("ip-pending",       "data"),
    State("ip-panel-id",      "data"),
    State("ip-issues-store",  "data"),
    State("ip-kpi-filter",    "data"),
    State("ip-caps-store",    "data"),
    State("ip-devcfg-store",  "data"),
    prevent_initial_call=True,
)
def _commit_ip_changes(n, pending, panel_id, issues, kpi_filt, caps, dev_cfg):
    if not n or not pending or not panel_id:
        raise PreventUpdate

    wid         = int(panel_id)
    db_fields:  dict = {}
    ado_fields: dict = {}

    if "priority" in pending:
        v = _pri_int(pending["priority"])
        db_fields["priority"]   = v
        ado_fields["priority"]  = v

    if "source" in pending:
        db_fields["source"] = pending["source"]  # maps to "type" column via _update_issue_local

    if "developer" in pending:
        v = pending["developer"]
        db_fields["developer"]   = v
        ado_fields["assigned_to"] = v

    if "iteration" in pending:
        v = pending["iteration"]
        db_fields["iteration"]   = v
        ado_fields["iteration"]  = v

    if "release_date" in pending:
        v = pending["release_date"]
        db_fields["release_date"]    = v
        ado_fields["release_date"]   = v

    if "story_size" in pending:
        v = pending["story_size"]
        db_fields["story_size"]   = v
        ado_fields["story_size"]  = v

    if "story_owner" in pending:
        v = pending["story_owner"]
        db_fields["story_owner"]  = v
        ado_fields["story_owner"] = v

    if "main_designer" in pending:
        v = pending["main_designer"]
        db_fields["main_designer"]   = v
        ado_fields["main_designer"]  = v

    _update_issue_local(wid, db_fields)
    if ado_fields:
        try:
            _ado_write(wid, ado_fields)
        except Exception:
            pass

    # Update the in-memory store
    new_issues = []
    for iss in issues:
        if iss["id"] == wid:
            iss = dict(iss)
            for k, v in db_fields.items():
                if k == "priority":
                    iss["priority"] = pending.get("priority", iss["priority"])
                elif k in iss:
                    iss[k] = v
            if "release_date" in db_fields:
                iss["release_ym"] = _parse_release_ym(db_fields["release_date"]) if db_fields["release_date"] else ""
        new_issues.append(iss)

    return (
        {},
        new_issues,
        _build_table(new_issues, kpi_filt),
        _build_kpi_row(new_issues),
        _build_dev_load(new_issues, dev_cfg, caps).children,
    )


@callback(
    Output("ip-dev-panel",    "style"),
    Output("ip-dev-backdrop", "style"),
    Input({"type": "ip-dev-load-btn", "dev": ALL}, "n_clicks"),
    Input("ip-dev-panel-close", "n_clicks"),
    Input("ip-dev-backdrop",    "n_clicks"),
    prevent_initial_call=True,
)
def _toggle_dev_panel(load_c, close_c, bd_c):
    tid = ctx.triggered_id
    if tid in ("ip-dev-panel-close", "ip-dev-backdrop"):
        return _DEV_PANEL_CLOSED, dict(_BACKDROP_CLOSED, zIndex="1065")
    if isinstance(tid, dict) and tid.get("type") == "ip-dev-load-btn":
        if any(n and n > 0 for n in (load_c or [])):
            return _DEV_PANEL_OPEN, dict(_BACKDROP_OPEN, zIndex="1065")
    raise PreventUpdate


@callback(
    Output("ip-devcfg-store",   "data"),
    Output("ip-dev-panel-body", "children"),
    Input({"type": "ip-perm-toggle", "dev": ALL, "pri": ALL}, "n_clicks"),
    Input({"type": "ip-dev-up",   "dev": ALL}, "n_clicks"),
    Input({"type": "ip-dev-down", "dev": ALL}, "n_clicks"),
    State("ip-devcfg-store", "data"),
    prevent_initial_call=True,
)
def _dev_perm_change(tog_c, up_c, dn_c, dev_cfg):
    if not any(n and n > 0 for n in (tog_c or []) + (up_c or []) + (dn_c or [])):
        raise PreventUpdate
    tid = ctx.triggered_id
    if not tid or not isinstance(tid, dict):
        raise PreventUpdate
    from db.issue_planning import save_dev_field, move_dev, load_dev_config
    kind = tid.get("type", "")
    dev  = tid.get("dev", "")
    if kind == "ip-perm-toggle":
        pri_key = tid.get("pri", "")
        cur = next((d.get(pri_key, True) for d in dev_cfg if d["developer"] == dev), True)
        save_dev_field(dev, **{pri_key: not cur})
    elif kind in ("ip-dev-up", "ip-dev-down"):
        move_dev(dev, "up" if kind == "ip-dev-up" else "down")
    new_cfg = load_dev_config()
    return new_cfg, _build_dev_panel_rows(new_cfg)


@callback(
    Output("ip-issues-store",     "data",     allow_duplicate=True),
    Output("ip-table-wrap",       "children", allow_duplicate=True),
    Output("ip-kpi-row",          "children", allow_duplicate=True),
    Output("ip-dev-load-section", "children", allow_duplicate=True),
    Input("ip-auto-assign-btn",   "n_clicks"),
    State("ip-issues-store",  "data"),
    State("ip-caps-store",    "data"),
    State("ip-devcfg-store",  "data"),
    State("ip-kpi-filter",    "data"),
    prevent_initial_call=True,
)
def _auto_assign(n, issues, caps, dev_cfg, kpi_filt):
    if not n:
        raise PreventUpdate
    sorted_devs = sorted(dev_cfg, key=lambda d: d["priority_order"])
    perm_map    = {d["developer"]: d for d in sorted_devs}
    counts      = {}
    for iss in issues:
        if iss["developer"]:
            counts[iss["developer"]] = counts.get(iss["developer"], 0) + 1
    total_cap = sum(caps.get(p, 4) for p in ("P1","P2","P3","Other"))

    def _can_take(dev, pri):
        if counts.get(dev, 0) >= total_cap:
            return False
        key_map = {"P1":"can_p1","P2":"can_p2","P3":"can_p3","Other":"can_other"}
        return bool(perm_map.get(dev, {}).get(key_map.get(pri, "can_other"), True))

    pri_order  = {"P1": 0, "P2": 1, "P3": 2, "Other": 3}
    unassigned = sorted(
        [x for x in issues if not x["developer"]],
        key=lambda x: (pri_order.get(x["priority"], 3), 0 if x["source"] == "Customer" else 1)
    )
    assigned_ids = {}
    for iss in unassigned:
        for d in sorted_devs:
            dev = d["developer"]
            if _can_take(dev, iss["priority"]):
                assigned_ids[iss["id"]] = dev
                counts[dev] = counts.get(dev, 0) + 1
                break

    if not assigned_ids:
        raise PreventUpdate

    new_issues = [
        dict(iss, developer=assigned_ids[iss["id"]]) if iss["id"] in assigned_ids else iss
        for iss in issues
    ]
    try:
        from sync.ado_write import write_fields
        for wid, dev in assigned_ids.items():
            _update_issue_local(wid, {"developer": dev})
            write_fields(wid, {"assigned_to": dev})
    except Exception:
        pass
    return (
        new_issues,
        _build_table(new_issues, kpi_filt),
        _build_kpi_row(new_issues),
        _build_dev_load(new_issues, dev_cfg, caps).children,
    )


@callback(
    Output("ip-issues-store",     "data",     allow_duplicate=True),
    Output("ip-table-wrap",       "children", allow_duplicate=True),
    Output("ip-kpi-row",          "children", allow_duplicate=True),
    Output("ip-dev-load-section", "children", allow_duplicate=True),
    Input("ip-clear-btn",        "n_clicks"),
    State("ip-issues-store",  "data"),
    State("ip-caps-store",    "data"),
    State("ip-devcfg-store",  "data"),
    State("ip-kpi-filter",    "data"),
    prevent_initial_call=True,
)
def _clear_all(n, issues, caps, dev_cfg, kpi_filt):
    if not n:
        raise PreventUpdate
    new_issues = [dict(iss, developer="") if iss["developer"] else iss for iss in issues]
    try:
        from sync.ado_write import write_fields
        for iss in issues:
            if iss["developer"]:
                _update_issue_local(iss["id"], {"developer": ""})
                write_fields(iss["id"], {"assigned_to": ""})
    except Exception:
        pass
    return (
        new_issues,
        _build_table(new_issues, kpi_filt),
        _build_kpi_row(new_issues),
        _build_dev_load(new_issues, dev_cfg, caps).children,
    )
