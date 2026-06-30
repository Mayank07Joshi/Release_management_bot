"""EOD — Admin Hours
Per-developer overhead tracking for a sprint.
For Stories = capacity_h − admin_h − leave_h
"""
import dash
import json
from datetime import date, datetime
from dash import dcc, html, Input, Output, State, callback, ctx, no_update, ALL
from config.dev_capacity import DEVELOPERS, STAFF_MAP, DEFAULT_CAPACITY_H
from db.admin_hours import (
    get_admin_hours, upsert_admin_row,
    get_sprint_capacity, set_sprint_capacity,
)
from db.leaves import get_leave_capacity

dash.register_page(__name__, path="/admin-hours", name="Admin Hours")

# ── Theme ─────────────────────────────────────────────────────────────────────
TXT  = "var(--text-primary)"
MT   = "var(--text-secondary)"
BD   = "var(--border)"
EL   = "var(--bg-elevated)"
HV   = "var(--bg-hover)"
P    = "var(--purple)"
GOLD = "#f59e0b"
GRN  = "#22c55e"
RED  = "#f87171"
BLU  = "#60a5fa"
AMB  = "#fb923c"
MONO = "'JetBrains Mono', 'Fira Code', monospace"

# ── Staff to show ─────────────────────────────────────────────────────────────
_ROLE_LABEL = {
    "Development": "Web Dev",
    "Mobile":      "Mobile Dev",
    "QA":          "Story Owner",
    "Management":  "Story Owner",
}

_PLAN_DEVS = DEVELOPERS + [
    STAFF_MAP["Chhavi Bhardwaj"],
    STAFF_MAP["Geetika Khanna"],
]
_DEV_NAMES = [d["name"] for d in _PLAN_DEVS]

# ── Editable column keys ──────────────────────────────────────────────────────
_COLS = [
    ("meetings",    "MEETINGS"),
    ("ceremonies",  "CEREMONIES"),
    ("support",     "SUPPORT"),
    ("code_review", "CODE REVIEW"),
    ("interviews",  "INTERVIEWS"),
    ("training",    "TRAINING"),
    ("other",       "OTHER"),
]
_COL_KEYS = [k for k, _ in _COLS]

# ── Sprint helpers ────────────────────────────────────────────────────────────
def _current_sprint() -> str:
    return date.today().strftime("%b-%y")


def _sprint_options() -> list[str]:
    today = date.today()
    opts = []
    for i in range(5, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        opts.append(date(y, m, 1).strftime("%b-%y"))
    return opts


def _sprint_to_ym(sprint_key: str) -> str:
    return datetime.strptime(sprint_key, "%b-%y").strftime("%Y-%m")


def _load_leave_hours(sprint_key: str) -> dict[str, float]:
    ym = _sprint_to_ym(sprint_key)
    try:
        lc = get_leave_capacity([ym])
        return {
            dev: float(lc["leaves"].get((dev, ym), 0) + lc["holidays"].get(ym, 0))
            for dev in _DEV_NAMES
        }
    except Exception:
        return {dev: 0.0 for dev in _DEV_NAMES}


# ── KPI card helper ───────────────────────────────────────────────────────────
def _kpi(title: str, value_id: str, sub_id: str, color: str) -> html.Div:
    return html.Div([
        html.Div(title, style={
            "fontSize": "10px", "fontWeight": "700", "color": MT,
            "letterSpacing": "0.08em", "textTransform": "uppercase",
            "marginBottom": "6px",
        }),
        html.Div(id=value_id, style={
            "fontSize": "28px", "fontWeight": "700",
            "color": color, "lineHeight": "1.1", "fontFamily": MONO,
        }),
        html.Div(id=sub_id, style={"fontSize": "11px", "color": MT, "marginTop": "4px"}),
    ], style={
        "background": EL, "border": f"1px solid {BD}",
        "borderRadius": "10px", "padding": "18px 22px", "flex": "1",
    })


# ── Table helpers ─────────────────────────────────────────────────────────────
_HDR_STYLE = {
    "padding": "9px 8px", "fontSize": "9px", "fontWeight": "700",
    "color": MT, "letterSpacing": "0.07em", "textAlign": "center",
    "borderBottom": f"1px solid {BD}", "background": EL,
    "whiteSpace": "nowrap",
}
_CELL_STYLE = {
    "padding": "6px 4px", "borderBottom": f"1px solid {BD}",
    "textAlign": "center", "verticalAlign": "middle",
}


def _input_cell(dev: str, col: str, val: float) -> html.Td:
    return html.Td(
        dcc.Input(
            id={"type": "ah-cell", "dev": dev, "col": col},
            type="number", min=0, max=999, step=0.5,
            value=val, debounce=True,
            style={
                "width": "52px", "background": HV,
                "border": f"1px solid {BD}", "borderRadius": "5px",
                "color": TXT, "fontSize": "12px", "fontFamily": MONO,
                "textAlign": "center", "padding": "4px 0",
            },
        ),
        style=_CELL_STYLE,
    )


def _computed_cell(dev: str, col: str) -> html.Td:
    return html.Td(
        html.Span(id={"type": "ah-disp", "dev": dev, "col": col}, children="—"),
        style={**_CELL_STYLE, "fontFamily": MONO, "fontSize": "13px"},
    )


def _leave_cell(dev: str) -> html.Td:
    return html.Td(
        html.Span(
            id={"type": "ah-leave", "dev": dev},
            children="—",
            style={"color": BLU},
        ),
        style={**_CELL_STYLE, "fontFamily": MONO, "fontSize": "12px"},
    )


def _build_table(db_data: dict, capacity_h: float, leave_hours: dict) -> html.Table:
    # ── Header ────────────────────────────────────────────────────────────────
    hdr_cells = [
        html.Th("MEMBER", style={**_HDR_STYLE, "textAlign": "left",
                                  "minWidth": "160px", "paddingLeft": "14px"}),
        *[html.Th(lbl, style=_HDR_STYLE) for _, lbl in _COLS],
        html.Th("LEAVE H", style={**_HDR_STYLE, "color": BLU}),
        html.Th("ADMIN H", style={**_HDR_STYLE, "color": GOLD}),
        html.Th("% CAP",   style=_HDR_STYLE),
        html.Th("FOR STORIES", style={**_HDR_STYLE, "color": GRN}),
    ]
    header = html.Thead(html.Tr(hdr_cells))

    # ── Body ──────────────────────────────────────────────────────────────────
    rows: list = []
    team_totals: dict[str, float] = {k: 0.0 for k in _COL_KEYS + ["admin_h", "leave_h", "for_stories"]}

    for dev_info in _PLAN_DEVS:
        dev    = dev_info["name"]
        role   = _ROLE_LABEL.get(dev_info["team"], dev_info["team"])
        row_db = db_data.get(dev, {})
        lv_h   = leave_hours.get(dev, 0.0)
        admin_h = sum(float(row_db.get(c, 0)) for c in _COL_KEYS)
        for_st  = max(0.0, capacity_h - admin_h - lv_h)
        pct     = admin_h / capacity_h * 100 if capacity_h > 0 else 0

        for c in _COL_KEYS:
            team_totals[c] += float(row_db.get(c, 0))
        team_totals["admin_h"]     += admin_h
        team_totals["leave_h"]     += lv_h
        team_totals["for_stories"] += for_st

        pct_color = GRN if pct < 15 else (AMB if pct < 25 else RED)
        st_color  = GRN if for_st >= 150 else (AMB if for_st >= 120 else RED)

        row = html.Tr([
            # Member
            html.Td([
                html.Div(dev, style={"fontSize": "13px", "fontWeight": "600", "color": TXT}),
                html.Div(role, style={"fontSize": "10px", "color": MT, "marginTop": "1px"}),
            ], style={**_CELL_STYLE, "textAlign": "left", "paddingLeft": "14px"}),

            # Editable columns
            *[_input_cell(dev, col, float(row_db.get(col, 0))) for col in _COL_KEYS],

            # Leave H (read-only)
            html.Td(
                html.Span(
                    id={"type": "ah-leave", "dev": dev},
                    children=f"{lv_h:.0f}h" if lv_h else "—",
                    style={"color": BLU if lv_h else MT, "fontSize": "12px",
                           "fontFamily": MONO},
                ),
                style=_CELL_STYLE,
            ),

            # Admin H
            html.Td(
                html.Span(
                    id={"type": "ah-disp", "dev": dev, "col": "admin_h"},
                    children=f"{admin_h:.0f}h",
                    style={"color": GOLD, "fontWeight": "700", "fontFamily": MONO,
                           "fontSize": "13px"},
                ),
                style=_CELL_STYLE,
            ),

            # % Cap
            html.Td(
                html.Span(
                    id={"type": "ah-disp", "dev": dev, "col": "pct"},
                    children=f"{pct:.0f}%",
                    style={"color": pct_color, "fontWeight": "600",
                           "fontFamily": MONO, "fontSize": "12px"},
                ),
                style=_CELL_STYLE,
            ),

            # For Stories
            html.Td(
                html.Span(
                    id={"type": "ah-disp", "dev": dev, "col": "for_stories"},
                    children=f"{for_st:.0f}",
                    style={"color": st_color, "fontWeight": "700",
                           "fontFamily": MONO, "fontSize": "14px"},
                ),
                style=_CELL_STYLE,
            ),
        ], style={"background": "transparent"})
        rows.append(row)

    # ── Totals row ────────────────────────────────────────────────────────────
    n_devs    = len(_PLAN_DEVS)
    tot_admin = team_totals["admin_h"]
    tot_leave = team_totals["leave_h"]
    tot_for   = team_totals["for_stories"]
    tot_pct   = tot_admin / (n_devs * capacity_h) * 100 if capacity_h > 0 else 0
    tot_pct_c = GRN if tot_pct < 15 else (AMB if tot_pct < 25 else RED)

    total_row = html.Tr([
        html.Td("Team", style={
            **_CELL_STYLE, "textAlign": "left", "paddingLeft": "14px",
            "fontWeight": "700", "color": TXT, "fontSize": "13px",
        }),
        *[html.Td(
            f"{team_totals[c]:.0f}",
            style={**_CELL_STYLE, "fontFamily": MONO, "fontSize": "12px",
                   "color": MT, "fontWeight": "600"},
        ) for c in _COL_KEYS],
        html.Td(f"{tot_leave:.0f}h" if tot_leave else "—",
                style={**_CELL_STYLE, "fontFamily": MONO, "color": BLU,
                       "fontSize": "12px"}),
        html.Td(f"{tot_admin:.0f}h",
                style={**_CELL_STYLE, "fontFamily": MONO, "color": GOLD,
                       "fontWeight": "700", "fontSize": "13px"}),
        html.Td(f"{tot_pct:.0f}%",
                style={**_CELL_STYLE, "fontFamily": MONO, "color": tot_pct_c,
                       "fontWeight": "600"}),
        html.Td(f"{tot_for:.0f}",
                style={**_CELL_STYLE, "fontFamily": MONO, "color": GRN,
                       "fontWeight": "700", "fontSize": "14px"}),
    ], style={"background": "rgba(255,255,255,0.03)", "borderTop": f"2px solid {BD}"})

    return html.Table(
        [header, html.Tbody(rows + [total_row])],
        style={"borderCollapse": "collapse", "width": "100%"},
    )


# ── Layout ────────────────────────────────────────────────────────────────────
def layout(**_):
    sprint   = _current_sprint()
    cap_h    = get_sprint_capacity(sprint)
    db_data  = get_admin_hours(sprint)
    lv_hours = _load_leave_hours(sprint)

    n_devs    = len(_PLAN_DEVS)
    tot_admin = sum(
        sum(float(row.get(c, 0)) for c in _COL_KEYS)
        for row in db_data.values()
    )
    tot_leave = sum(lv_hours.values())
    tot_for   = sum(
        max(0.0, cap_h - sum(float(db_data.get(d["name"], {}).get(c, 0)) for c in _COL_KEYS)
            - float(lv_hours.get(d["name"], 0)))
        for d in _PLAN_DEVS
    )
    tot_pct   = tot_admin / (n_devs * cap_h) * 100 if cap_h > 0 else 0

    sprints   = _sprint_options()

    return html.Div([
        dcc.Store(id="ah-sprint",     data=sprint),
        dcc.Store(id="ah-capacity-h", data=cap_h),
        dcc.Store(id="ah-leave-data", data=lv_hours),

        # ── Header ────────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.Div("EOD · CAPACITY", style={
                    "fontSize": "10px", "fontWeight": "700", "color": P,
                    "letterSpacing": "1px", "textTransform": "uppercase",
                    "marginBottom": "4px",
                }),
                html.Div("Admin Hours", style={
                    "fontSize": "22px", "fontWeight": "800", "color": TXT,
                }),
                html.Div(
                    "Meetings, ceremonies, support and other overhead that reduces "
                    "each person's story-delivery capacity. Edit any cell to log hours.",
                    style={"fontSize": "12px", "color": MT, "marginTop": "4px",
                           "maxWidth": "620px"},
                ),
            ]),
            # Sprint selector
            dcc.Dropdown(
                id="ah-sprint-dropdown",
                options=[{"label": s, "value": s} for s in reversed(sprints)],
                value=sprint,
                clearable=False,
                className="dark-dropdown",
                style={"width": "130px", "fontSize": "13px"},
            ),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "flex-start", "marginBottom": "20px"}),

        # ── KPI cards ─────────────────────────────────────────────────────────
        html.Div([
            _kpi("Team Admin Hours",    "ah-kpi-v1", "ah-kpi-s1", GOLD),
            _kpi("Avg Per Person",      "ah-kpi-v2", "ah-kpi-s2", AMB),
            _kpi("% of Capacity",       "ah-kpi-v3", "ah-kpi-s3", RED),
            _kpi("Available for Stories", "ah-kpi-v4", "ah-kpi-s4", GRN),
        ], id="ah-kpis", style={"display": "flex", "gap": "14px", "marginBottom": "20px"}),

        # ── Capacity input ─────────────────────────────────────────────────────
        html.Div([
            html.Span("Capacity per person",
                      style={"fontSize": "13px", "color": MT, "marginRight": "10px"}),
            dcc.Input(
                id="ah-cap-input",
                type="number", min=1, max=500, step=1,
                value=cap_h, debounce=True,
                style={
                    "width": "70px", "background": HV,
                    "border": f"1px solid rgba(99,102,241,0.5)",
                    "borderRadius": "6px", "color": TXT,
                    "fontSize": "14px", "fontWeight": "700",
                    "fontFamily": MONO, "textAlign": "center", "padding": "5px 0",
                },
            ),
            html.Span("h / sprint",
                      style={"fontSize": "13px", "color": MT, "marginLeft": "8px"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "14px"}),

        # ── Table ─────────────────────────────────────────────────────────────
        html.Div(
            id="ah-table-wrap",
            children=_build_table(db_data, cap_h, lv_hours),
            style={
                "background": EL, "border": f"1px solid {BD}",
                "borderRadius": "10px", "overflowX": "auto",
            },
        ),

        # ── Footer note ───────────────────────────────────────────────────────
        html.Div(
            "Leave hours pulled from Leave Manager · "
            "Admin hours are saved on each cell edit (blur / Enter).",
            style={"fontSize": "11px", "color": MT, "marginTop": "10px",
                   "textAlign": "right"},
        ),

    ], style={"padding": "24px"})


# ── Callbacks ─────────────────────────────────────────────────────────────────

# Sprint dropdown → store
@callback(
    Output("ah-sprint", "data"),
    Input("ah-sprint-dropdown", "value"),
    prevent_initial_call=True,
)
def _set_sprint(sprint):
    return sprint or _current_sprint()


# Sprint store change → reload table, capacity, leave data
@callback(
    Output("ah-table-wrap",  "children"),
    Output("ah-capacity-h",  "data"),
    Output("ah-leave-data",  "data"),
    Output("ah-kpi-v1", "children"), Output("ah-kpi-s1", "children"),
    Output("ah-kpi-v2", "children"), Output("ah-kpi-s2", "children"),
    Output("ah-kpi-v3", "children"), Output("ah-kpi-s3", "children"),
    Output("ah-kpi-v4", "children"), Output("ah-kpi-s4", "children"),
    Input("ah-sprint", "data"),
)
def _load_sprint(sprint_key):
    sprint_key = sprint_key or _current_sprint()
    cap_h    = get_sprint_capacity(sprint_key)
    db_data  = get_admin_hours(sprint_key)
    lv_hours = _load_leave_hours(sprint_key)
    table    = _build_table(db_data, cap_h, lv_hours)
    v1, s1, v2, s2, v3, s3, v4, s4 = _calc_kpis(db_data, cap_h, lv_hours)
    return table, cap_h, lv_hours, v1, s1, v2, s2, v3, s3, v4, s4


# Capacity input change → save + update KPIs (table re-renders on next sprint load)
@callback(
    Output("ah-capacity-h", "data", allow_duplicate=True),
    Output("ah-table-wrap", "children", allow_duplicate=True),
    Output("ah-kpi-v1", "children", allow_duplicate=True), Output("ah-kpi-s1", "children", allow_duplicate=True),
    Output("ah-kpi-v2", "children", allow_duplicate=True), Output("ah-kpi-s2", "children", allow_duplicate=True),
    Output("ah-kpi-v3", "children", allow_duplicate=True), Output("ah-kpi-s3", "children", allow_duplicate=True),
    Output("ah-kpi-v4", "children", allow_duplicate=True), Output("ah-kpi-s4", "children", allow_duplicate=True),
    Input("ah-cap-input",  "value"),
    State("ah-sprint",     "data"),
    State("ah-leave-data", "data"),
    prevent_initial_call=True,
)
def _update_capacity(cap_val, sprint_key, leave_data):
    if cap_val is None or cap_val <= 0:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update
    cap_h = float(cap_val)
    sprint_key = sprint_key or _current_sprint()
    set_sprint_capacity(sprint_key, cap_h)
    db_data  = get_admin_hours(sprint_key)
    lv_hours = leave_data or {}
    table    = _build_table(db_data, cap_h, lv_hours)
    v1, s1, v2, s2, v3, s3, v4, s4 = _calc_kpis(db_data, cap_h, lv_hours)
    return cap_h, table, v1, s1, v2, s2, v3, s3, v4, s4


# Any cell edit → save row to DB + update display cells + KPIs
@callback(
    Output({"type": "ah-disp", "dev": ALL, "col": "admin_h"},    "children"),
    Output({"type": "ah-disp", "dev": ALL, "col": "pct"},        "children"),
    Output({"type": "ah-disp", "dev": ALL, "col": "for_stories"},"children"),
    Output("ah-kpi-v1", "children", allow_duplicate=True), Output("ah-kpi-s1", "children", allow_duplicate=True),
    Output("ah-kpi-v2", "children", allow_duplicate=True), Output("ah-kpi-s2", "children", allow_duplicate=True),
    Output("ah-kpi-v3", "children", allow_duplicate=True), Output("ah-kpi-s3", "children", allow_duplicate=True),
    Output("ah-kpi-v4", "children", allow_duplicate=True), Output("ah-kpi-s4", "children", allow_duplicate=True),
    Input({"type": "ah-cell", "dev": ALL, "col": ALL}, "value"),
    State("ah-sprint",     "data"),
    State("ah-capacity-h", "data"),
    State("ah-leave-data", "data"),
    prevent_initial_call=True,
)
def _save_and_recompute(all_values, sprint_key, capacity_h, leave_data):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        return [no_update] * (3 * len(_PLAN_DEVS) + 8)

    sprint_key = sprint_key or _current_sprint()
    cap_h      = float(capacity_h or DEFAULT_CAPACITY_H)
    lv_hours   = leave_data or {}

    # Build dict from pattern-matched inputs (order matches ctx.inputs_list)
    cell_data: dict[tuple, float] = {}
    for spec, val in zip(ctx.inputs_list[0], all_values):
        dev = spec["id"]["dev"]
        col = spec["id"]["col"]
        cell_data[(dev, col)] = float(val or 0)

    # Identify which dev was changed and save to DB
    tid = ctx.triggered_id
    if isinstance(tid, dict) and tid.get("type") == "ah-cell":
        changed_dev = tid["dev"]
        upsert_admin_row(
            changed_dev, sprint_key,
            meetings    = cell_data.get((changed_dev, "meetings"),    0),
            ceremonies  = cell_data.get((changed_dev, "ceremonies"),  0),
            support     = cell_data.get((changed_dev, "support"),     0),
            code_review = cell_data.get((changed_dev, "code_review"), 0),
            interviews  = cell_data.get((changed_dev, "interviews"),  0),
            training    = cell_data.get((changed_dev, "training"),    0),
            other       = cell_data.get((changed_dev, "other"),       0),
        )

    # Recompute per-dev display values
    # Order of ALL outputs matches order of _PLAN_DEVS (layout registration order)
    admin_h_vals, pct_vals, for_stories_vals = [], [], []
    tot_admin = 0.0
    tot_for   = 0.0

    for dev_info in _PLAN_DEVS:
        dev     = dev_info["name"]
        adm     = sum(cell_data.get((dev, c), 0) for c in _COL_KEYS)
        lv_h    = float(lv_hours.get(dev, 0))
        for_st  = max(0.0, cap_h - adm - lv_h)
        pct     = adm / cap_h * 100 if cap_h > 0 else 0

        pct_c   = GRN if pct < 15 else (AMB if pct < 25 else RED)
        st_c    = GRN if for_st >= 150 else (AMB if for_st >= 120 else RED)

        admin_h_vals.append(html.Span(f"{adm:.0f}h",   style={"color": GOLD, "fontWeight": "700", "fontFamily": MONO}))
        pct_vals.append(    html.Span(f"{pct:.0f}%",   style={"color": pct_c, "fontWeight": "600", "fontFamily": MONO}))
        for_stories_vals.append(html.Span(f"{for_st:.0f}", style={"color": st_c, "fontWeight": "700", "fontFamily": MONO, "fontSize": "14px"}))

        tot_admin += adm
        tot_for   += for_st

    # KPIs
    n_devs  = len(_PLAN_DEVS)
    tot_lv  = sum(float(lv_hours.get(d["name"], 0)) for d in _PLAN_DEVS)
    tot_pct = tot_admin / (n_devs * cap_h) * 100 if cap_h > 0 else 0
    v1, s1  = f"{tot_admin:.0f}h", f"across {n_devs} people"
    v2, s2  = f"{tot_admin / n_devs:.0f}h", f"of {cap_h:.0f}h capacity"
    v3, s3  = f"{tot_pct:.0f}%", f"{tot_admin:.0f} / {n_devs * cap_h:.0f}h"
    v4, s4  = f"{tot_for:.0f}h", "after admin & leave load"

    return (admin_h_vals, pct_vals, for_stories_vals,
            v1, s1, v2, s2, v3, s3, v4, s4)


# ── KPI computation helper ────────────────────────────────────────────────────
def _calc_kpis(db_data: dict, cap_h: float, lv_hours: dict):
    n_devs    = len(_PLAN_DEVS)
    tot_admin = sum(
        sum(float(db_data.get(d["name"], {}).get(c, 0)) for c in _COL_KEYS)
        for d in _PLAN_DEVS
    )
    tot_for = sum(
        max(0.0, cap_h
            - sum(float(db_data.get(d["name"], {}).get(c, 0)) for c in _COL_KEYS)
            - float(lv_hours.get(d["name"], 0)))
        for d in _PLAN_DEVS
    )
    tot_pct = tot_admin / (n_devs * cap_h) * 100 if cap_h > 0 else 0
    return (
        f"{tot_admin:.0f}h",    f"across {n_devs} people",
        f"{tot_admin / n_devs:.0f}h", f"of {cap_h:.0f}h capacity",
        f"{tot_pct:.0f}%",      f"{tot_admin:.0f} / {n_devs * cap_h:.0f}h",
        f"{tot_for:.0f}h",      "after admin & leave load",
    )
