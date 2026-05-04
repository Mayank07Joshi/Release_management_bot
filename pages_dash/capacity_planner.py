"""Developer Capacity & Work Allocation"""

import re
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback, ALL, no_update, ctx
import pandas as pd
from datetime import date
import calendar

from data.loader import load_data
from config.dev_capacity import DEVELOPERS, DEV_MAP
from config.settings import ADO_BASE_URL

dash.register_page(__name__, path="/dev-capacity", name="Developer Capacity")

_GOLD   = "#fbbf24"
_GREEN  = "#34d399"
_RED    = "#f87171"
_BLU    = "#818cf8"
_CARD   = "rgba(255,255,255,0.03)"
_BORDER = "rgba(255,255,255,0.07)"

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
_HOURS_PER_DAY   = 9.0


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
                  pressure_mode: bool = False, remaining_h: float = None):
    total  = enh_h + issue_h
    denom  = remaining_h if (pressure_mode and remaining_h is not None) else capacity

    if pressure_mode and (remaining_h is None or remaining_h == 0):
        # Month ended or no hours left — show dashes
        return html.Div([
            html.Div("—", style={"fontSize": "20px", "fontWeight": "700",
                                 "color": "#4b5563", "marginBottom": "2px"}),
            html.Div("0h left", style={"fontSize": "11px", "color": "#4b5563"}),
        ], style={"padding": "14px 16px"})

    pct    = round(total / denom * 100) if denom > 0 else 0
    pct_c  = _RED if pct > 100 else (_GOLD if pct >= 80 else _GREEN)
    ew     = min(enh_h   / denom * 100, 100) if denom > 0 else 0
    iw     = min(issue_h / denom * 100, 100) if denom > 0 else 0
    top    = sorted(items, key=lambda x: -x["dev_h"])[:2]
    extra  = len(items) - 2

    pills = []
    for i in top:
        clr = _GOLD if IS_ENH(i["type"]) else _GREEN
        txt = (i["title"][:32] + "…") if len(i["title"]) > 32 else i["title"]
        pills.append(html.Div([
            html.Span("• ", style={"color": clr}),
            html.Span(txt, style={"fontSize": "11px", "color": "#c8c8e0"}),
        ], style={"marginBottom": "2px"}))
    if extra > 0:
        pills.append(html.Div(
            f"+{extra} more",
            style={"fontSize": "11px", "color": "#4b5563"},
        ))

    subtitle = (
        f"{total:.0f}h open / {remaining_h:.0f}h left"
        if pressure_mode
        else f"{total:.0f}h / {capacity:.0f}h"
    )

    live_badge = html.Span(
        "LIVE", style={
            "fontSize": "9px", "fontWeight": "700", "letterSpacing": "0.8px",
            "color": "#0f0f1e", "background": pct_c,
            "borderRadius": "4px", "padding": "1px 5px", "marginLeft": "6px",
            "verticalAlign": "middle",
        }
    ) if pressure_mode else None

    return html.Div([
        html.Div([
            html.Span(f"{pct}%", style={
                "fontSize": "20px", "fontWeight": "700", "color": pct_c,
            }),
            *([live_badge] if live_badge else []),
        ], style={"marginBottom": "2px"}),
        html.Div(subtitle, style={
            "fontSize": "11px", "color": "#8892a4", "marginBottom": "6px",
        }),
        html.Div([
            html.Div(style={
                "height": "5px", "borderRadius": "3px",
                "background": _GOLD, "width": f"{ew:.0f}%", "marginBottom": "2px",
            }),
            html.Div(style={
                "height": "5px", "borderRadius": "3px",
                "background": _GREEN, "width": f"{iw:.0f}%",
            }),
        ], style={"width": "100%", "marginBottom": "8px"}),
        *pills,
    ], style={"padding": "14px 16px"})


# ── Grid renderers ────────────────────────────────────────────────────────────

def _render_m012_grid(df, devs, yms, month_labels, view):
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

    team_totals = [{"enh": 0.0, "iss": 0.0, "cap": 0.0, "rem": m0_remaining_h if i == 0 else 0.0}
                   for i in range(3)]
    dev_rows = []

    for dev in devs:
        cap = dev["capacity_h"]
        month_cells = []

        for m_idx, ym_str in enumerate(yms):
            is_m0 = (m_idx == 0)
            items = _dev_month_items(df, dev["name"], ym_str, open_only=is_m0)
            enh_items = [i for i in items if IS_ENH(i["type"])]
            iss_items = [i for i in items if IS_ISSUE(i["type"])]

            if view == "Enhancements":
                display = enh_items
                enh_h, iss_h = sum(i["dev_h"] for i in enh_items), 0.0
            elif view == "Issues":
                display = iss_items
                enh_h, iss_h = 0.0, sum(i["dev_h"] for i in iss_items)
            else:
                display = items
                enh_h = sum(i["dev_h"] for i in enh_items)
                iss_h = sum(i["dev_h"] for i in iss_items)

            team_totals[m_idx]["enh"] += enh_h
            team_totals[m_idx]["iss"] += iss_h
            team_totals[m_idx]["cap"] += cap

            month_cells.append(html.Div(
                _cell_content(
                    display, enh_h, iss_h, cap,
                    pressure_mode=is_m0,
                    remaining_h=m0_remaining_h if is_m0 else None,
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
        total_h  = t["enh"] + t["iss"]
        is_m0    = (t_idx == 0)
        denom    = (t["rem"] * len(devs)) if (is_m0 and t["rem"]) else t["cap"]
        pct      = round(total_h / denom * 100) if denom > 0 else 0
        pct_c    = _RED if pct > 100 else (_GOLD if pct >= 80 else _GREEN)
        sub_lbl  = f"{total_h:.0f}h open / {t['rem'] * len(devs):.0f}h left" if is_m0 else f"{total_h:.0f}h"
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


def _render_rest_grid(df, devs, view):
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
            items = _dev_month_items(df, dev["name"], ym_str)
            enh_h = sum(i["dev_h"] for i in items if IS_ENH(i["type"]))
            iss_h = sum(i["dev_h"] for i in items if IS_ISSUE(i["type"]))
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

def _render_gantt(df, eff, show_all):
    gantt_months = [
        (f"2026-{m:02d}", date(2026, m, 1).strftime("%b"))
        for m in range(4, 13)
    ]
    cur_ym = date.today().strftime("%Y-%m")
    cols   = "240px " + " ".join(["1fr"] * 9)

    enhs = df[
        df["work_item_type"].str.contains("Enhancement", na=False, case=False)
    ].drop_duplicates("work_item_id")

    rows_data = []
    for _, row in enhs.iterrows():
        eid = row["work_item_id"]
        h   = eff.get(eid, row["_est"])
        sz  = _size(h)
        if not show_all and sz == "Small":
            continue
        rdm = _parse_release_ym(str(row.get("release_date", "")))
        if not rdm or rdm < "2026-04" or rdm > "2026-12":
            continue
        rows_data.append({
            "title": row["title"], "eff_h": h, "size": sz,
            "rdm": rdm, "priority": row.get("priority", 4),
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


def _render_function_timeline(df, eff, size_filter="All"):
    timeline_months = [
        (f"2026-{m:02d}", date(2026, m, 1).strftime("%b"))
        for m in range(4, 13)
    ]
    cur_ym = date.today().strftime("%Y-%m")
    cols   = "200px " + " ".join(["1fr"] * 9)

    enhs = df[
        df["work_item_type"].str.contains("Enhancement", na=False, case=False)
    ].drop_duplicates("work_item_id")

    func_data: dict[str, dict] = {}
    for _, row in enhs.iterrows():
        func = str(row.get("function", "")).strip()
        if not func or func == "Not Specified":
            continue
        eid = row["work_item_id"]
        h   = eff.get(eid, row["_est"])
        if h == 0:
            continue
        sz = _size(h)
        if size_filter != "All" and sz != size_filter:
            continue
        rdm = _parse_release_ym(str(row.get("release_date", "")))
        if not rdm or rdm < "2026-04" or rdm > "2026-12":
            continue
        if func not in func_data:
            func_data[func] = {ym: [] for ym, _ in timeline_months}
        func_data[func][rdm].append({"id": eid, "title": row["title"], "size": sz, "h": h})

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

        # ── Top: VIEW filter (sticky) ─────────────────────────────────────────
        html.Div([
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
            html.Div([
                html.Span("■ ", style={"color": _GOLD, "fontSize": "10px"}),
                html.Span("Enh  ", style={"fontSize": "12px", "color": "#8892a4"}),
                html.Span("■ ", style={"color": _GREEN, "fontSize": "10px"}),
                html.Span("Issues  ", style={"fontSize": "12px", "color": "#8892a4"}),
                html.Span("· Click any cell for month detail",
                          style={"fontSize": "12px", "color": "#4b5563"}),
            ], style={"marginLeft": "auto", "display": "flex", "alignItems": "center"}),
        ], style={
            "display": "flex", "alignItems": "center",
            "position": "sticky", "top": "58px", "zIndex": "20",
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
    df  = _prep(load_data())
    eff = _eff_hours(df)
    return _render_function_timeline(df, eff, size_filter or "All")


@callback(
    Output("dcap-kpis",     "children"),
    Output("dcap-grid",     "children"),
    Output("dcap-gantt",    "children"),
    Output("dcap-subtitle", "children"),
    Input("dcap-view",           "data"),
    Input("dcap-tab",            "data"),
    Input("dcap-gantt-show-all", "data"),
)
def _render(view, tab, show_all):
    df   = _prep(load_data())
    eff  = _eff_hours(df)
    m012 = _months012()
    yms  = [_ym(d) for d in m012]
    lbls = [d.strftime("%b") for d in m012]
    devs = DEVELOPERS

    # KPIs
    m0_cap = sum(d["capacity_h"] for d in devs)
    m0_enh = 0.0
    m0_iss = 0.0
    for dev in devs:
        its = _dev_month_items(df, dev["name"], yms[0])
        m0_enh += sum(i["dev_h"] for i in its if IS_ENH(i["type"]))
        m0_iss += sum(i["dev_h"] for i in its if IS_ISSUE(i["type"]))

    fy_months    = [f"2026-{m:02d}" for m in range(4, 13)]
    fy_cap       = m0_cap * 9
    fy_committed = 0.0
    for dev in devs:
        for ym_str in fy_months:
            its = _dev_month_items(df, dev["name"], ym_str)
            fy_committed += sum(i["dev_h"] for i in its)
    fy_free = max(fy_cap - fy_committed, 0.0)

    kpis = [
        _kpi(f"{m0_cap:,}h",          "M0 Capacity",        f"180h × {len(devs)} devs", _GOLD),
        _kpi(f"{m0_enh:,.0f}h",       "M0 Enhancements",    f"{m0_enh/m0_cap*100:.0f}% of M0" if m0_cap else "—", _GREEN),
        _kpi(f"{m0_iss:,.0f}h",       "M0 Issues",          f"{m0_iss/m0_cap*100:.0f}% of M0" if m0_cap else "—", _GOLD),
        _kpi(f"{fy_cap:,}h",          "Full Year Capacity",  "Apr – Dec 2026", "#c084fc"),
        _kpi(f"{fy_committed:,.0f}h", "Full Year Committed", f"{fy_committed/fy_cap*100:.0f}% of year" if fy_cap else "—", "#60a5fa"),
        _kpi(f"{fy_free:,.0f}h",      "Full Year Free",      f"{fy_free/fy_cap*100:.0f}% headroom"    if fy_cap else "—", _GREEN),
    ]

    grid  = _render_m012_grid(df, devs, yms, lbls, view) if tab == "012" else _render_rest_grid(df, devs, view)
    gantt = _render_gantt(df, eff, bool(show_all))
    sub   = (f"{len(devs)} developers · 180h default monthly capacity · "
             "Click any cell for M0/M1/M2 detail")

    return kpis, grid, gantt, sub


@callback(
    Output("dcap-panel",     "is_open"),
    Output("dcap-sel-dev",   "data"),
    Output("dcap-sel-month", "data"),
    Input({"type": "dcap-cell", "dev": ALL, "month": ALL}, "n_clicks"),
    State({"type": "dcap-cell", "dev": ALL, "month": ALL}, "id"),
    prevent_initial_call=True,
)
def _open_panel(clicks, ids):
    for c, cid in zip(clicks, ids):
        if c:
            return True, cid["dev"], cid["month"]
    return no_update, no_update, no_update


@callback(
    Output("dcap-panel-body", "children"),
    Input("dcap-sel-dev",   "data"),
    Input("dcap-sel-month", "data"),
    Input("dcap-view",      "data"),
    prevent_initial_call=True,
)
def _panel_body(dev_name, ym_str, view):
    if not dev_name or not ym_str:
        return html.Div("Select a cell")

    df  = _prep(load_data())
    eff = _eff_hours(df)
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

    all_items  = _dev_month_items(df, dev_name, ym_str)
    open_items = _dev_month_items(df, dev_name, ym_str, open_only=True) if is_m0 else all_items
    open_ids   = {i["id"] for i in open_items}
    done_items = [i for i in all_items if i["id"] not in open_ids] if is_m0 else []

    def _filter_view(items):
        if view == "Enhancements": return [i for i in items if IS_ENH(i["type"])]
        if view == "Issues":       return [i for i in items if IS_ISSUE(i["type"])]
        return items

    open_display = _filter_view(open_items)
    done_display = _filter_view(done_items)

    open_enh = [i for i in open_display if IS_ENH(i["type"])]
    open_iss = [i for i in open_display if IS_ISSUE(i["type"])]
    enh_h    = sum(i["dev_h"] for i in open_enh)
    iss_h    = sum(i["dev_h"] for i in open_iss)

    remaining_h = _remaining_workday_hours(ym_str) if is_m0 else None
    display_cap = remaining_h if (is_m0 and remaining_h) else cap
    free_h      = max(display_cap - enh_h - iss_h, 0.0)
    ew          = min(enh_h / display_cap * 100, 100) if display_cap > 0 else 0
    iw          = min(iss_h / display_cap * 100, 100) if display_cap > 0 else 0

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

        badges = [html.Span(f"P{prio}", style={
            "fontSize": "10px", "fontWeight": "700", "color": p_clr,
            "background": p_bg, "padding": "2px 6px",
            "borderRadius": "4px", "marginRight": "6px",
        })]
        if show_size:
            sz     = _size(eff.get(item["id"], item["dev_h"]))
            s_bg, s_tc = _sz_clrs.get(sz, _sz_clrs["Small"])
            badges.append(html.Span(sz, style={
                "fontSize": "10px", "fontWeight": "700", "color": s_tc,
                "background": s_bg, "padding": "2px 6px",
                "borderRadius": "4px", "marginRight": "6px",
            }))
        badges.append(html.Span(f"{item['dev_h']:.0f}h",
                                style={"fontSize": "12px", "color": "#8892a4"}))
        if dimmed:
            badges.append(html.Span("✓", style={
                "fontSize": "11px", "color": "#34d399", "marginLeft": "6px", "fontWeight": "700",
            }))

        return html.A(
            href=f"{ADO_BASE_URL}{item['id']}", target="_blank",
            style={"textDecoration": "none", "display": "block", "marginBottom": "8px",
                   "opacity": "0.45" if dimmed else "1"},
            children=html.Div([
                html.Div(title_txt, style={
                    "fontSize": "13px", "color": "#e2e8f0",
                    "fontWeight": "600", "marginBottom": "6px", "lineHeight": "1.45",
                }),
                html.Div(badges),
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
            *[_item_card(i, True) for i in sorted(open_enh, key=lambda x: x.get("priority", 4))],
        ]
    if open_iss:
        lbl = f"ISSUE RESOLUTION · {iss_h:.0f}h" + (" OPEN" if is_m0 else "")
        iss_section = [
            html.Div(lbl, style={
                "fontSize": "10px", "color": _RED, "fontWeight": "700",
                "textTransform": "uppercase", "letterSpacing": "1px", "margin": "12px 0 8px",
            }),
            *[_item_card(i, False) for i in sorted(open_iss, key=lambda x: x.get("priority", 4))],
        ]

    # ── Done section (M0 only, collapsed) ────────────────────────────────────
    done_section = []
    if done_display:
        done_h = sum(i["dev_h"] for i in done_display)
        done_section = [html.Details([
            html.Summary(
                f"✓  COMPLETED  ·  {len(done_display)} items  ·  {done_h:.0f}h",
                style={"fontSize": "10px", "color": "#34d399", "fontWeight": "700",
                       "textTransform": "uppercase", "letterSpacing": "1px",
                       "cursor": "pointer", "margin": "16px 0 8px",
                       "listStyle": "none", "outline": "none"},
            ),
            *[_item_card(i, IS_ENH(i["type"]), dimmed=True)
              for i in sorted(done_display, key=lambda x: x.get("priority", 4))],
        ])]

    total_open  = len(open_display)
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
            _kpi_card(f"{free_h:.0f}h","Free",          _BLU),
        ], style={"display": "flex", "gap": "8px", "marginBottom": "16px"}),
        html.Div([
            html.Div(style={"flex": str(max(ew, 0.01)),          "background": _GREEN, "height": "16px"}),
            html.Div(style={"flex": str(max(iw, 0.01)),          "background": _RED,   "height": "16px"}),
            html.Div(style={"flex": str(max(100 - ew - iw, 0.01)),"background": "rgba(255,255,255,0.07)", "height": "16px"}),
        ], style={"display": "flex", "borderRadius": "8px", "overflow": "hidden", "marginBottom": "16px"}),
        html.Div(
            f"{total_open} OPEN ITEMS" if is_m0 else f"{total_open} ITEMS",
            style={"fontSize": "11px", "fontWeight": "700", "color": "#8892a4",
                   "textTransform": "uppercase", "letterSpacing": "1px", "marginBottom": "8px",
                   "borderTop": "1px solid rgba(255,255,255,0.07)", "paddingTop": "14px"},
        ),
        *enh_section,
        *iss_section,
        *done_section,
    ], style={"padding": "16px"})
