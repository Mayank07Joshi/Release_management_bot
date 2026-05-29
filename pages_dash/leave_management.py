"""Leave Management — BA entry point for company holidays and developer leaves."""

from __future__ import annotations

from datetime import date, timedelta

import dash
import dash_bootstrap_components as dbc
from dash import (ALL, Input, Output, State, callback, ctx, dcc, html, no_update)
from flask_login import current_user

from config.dev_capacity import DEVELOPERS
from db.leaves import (
    add_dev_leave, add_holiday, delete_dev_leave, delete_holiday,
    get_dev_leaves, get_holidays, init_leave_tables, _workdays_in_range, _holiday_set,
)

dash.register_page(__name__, path="/leave-management", name="Leave Management")

# ── Colour tokens ─────────────────────────────────────────────────────────────
_BG   = "var(--bg-base)"
_CARD = "var(--bg-elevated)"
_BD   = "var(--border)"
_T1   = "var(--text-primary)"
_T2   = "var(--text-secondary)"
_GR   = "var(--green)"
_RE   = "var(--red)"
_AM   = "var(--amber)"
_BL   = "var(--blue)"
_PU   = "var(--purple)"

_DEV_OPTIONS = [{"label": d["name"], "value": d["name"]} for d in DEVELOPERS]

# ── Shared styles ─────────────────────────────────────────────────────────────
_CARD_STYLE = {
    "background": _CARD, "border": f"1px solid {_BD}",
    "borderRadius": "12px", "padding": "20px",
}
_LABEL = {
    "fontSize": "11px", "color": _T2, "textTransform": "uppercase",
    "letterSpacing": "0.8px", "marginBottom": "6px", "fontWeight": "600",
}
_INPUT = {
    "background": "var(--bg-hover)", "border": f"1px solid {_BD}",
    "borderRadius": "8px", "color": _T1, "fontSize": "13px",
    "padding": "8px 12px", "width": "100%",
}
_BTN = {
    "borderRadius": "8px", "fontSize": "13px", "fontWeight": "600",
    "padding": "8px 20px", "cursor": "pointer", "border": "none",
}


def _section_title(text: str, sub: str = ""):
    return html.Div([
        html.Div(text, style={"fontSize": "16px", "fontWeight": "700", "color": _T1}),
        html.Div(sub,  style={"fontSize": "12px", "color": _T2, "marginTop": "2px"}) if sub else None,
    ], style={"marginBottom": "16px"})


def _tag(label: str, color: str):
    return html.Span(label, style={
        "fontSize": "10px", "fontWeight": "700", "padding": "2px 7px",
        "borderRadius": "4px", "background": f"{color}22",
        "color": color, "border": f"0.5px solid {color}55",
    })


def _radio(id_: str, options: list, value: str):
    return dcc.RadioItems(
        id=id_, options=options, value=value, inline=True,
        inputStyle={"marginRight": "5px", "cursor": "pointer", "accentColor": "#818cf8"},
        labelStyle={"marginRight": "16px", "fontSize": "13px", "color": _T1, "cursor": "pointer"},
    )


# ── Holiday form ──────────────────────────────────────────────────────────────
def _holiday_form():
    return html.Div([
        _section_title("Company Holidays", "Public / office-wide holidays that reduce everyone's capacity"),

        html.Div("Date", style=_LABEL),
        dcc.DatePickerSingle(
            id="lm-hol-date",
            date=str(date.today()),
            display_format="DD MMM YYYY",
            style={"marginBottom": "12px"},
            className="dark-datepicker",
        ),

        html.Div("Holiday name", style={**_LABEL, "marginTop": "8px"}),
        dcc.Input(id="lm-hol-name", type="text", placeholder="e.g. Independence Day",
                  debounce=False, style={**_INPUT, "marginBottom": "14px"}),

        html.Button("Add Holiday", id="lm-hol-add", n_clicks=0, style={
            **_BTN, "background": _GR, "color": "#0f2a1f",
        }),
        html.Div(id="lm-hol-msg", style={"marginTop": "8px", "fontSize": "12px"}),
    ], style=_CARD_STYLE)


# ── Leave form ────────────────────────────────────────────────────────────────
def _leave_form():
    return html.Div([
        _section_title("Developer Leaves", "Planned and sick leaves taken by individual developers"),

        # Developer
        html.Div("Developer", style=_LABEL),
        dcc.Dropdown(
            id="lm-dev-select",
            options=_DEV_OPTIONS,
            placeholder="Select developer…",
            clearable=False,
            className="dark-dropdown",
            style={"marginBottom": "14px", "fontSize": "13px"},
        ),

        # Leave type
        html.Div("Leave type", style=_LABEL),
        _radio("lm-leave-type",
               [{"label": "Planned", "value": "planned"},
                {"label": "Sick",    "value": "sick"}],
               "planned"),

        # Duration
        html.Div("Duration", style={**_LABEL, "marginTop": "12px"}),
        _radio("lm-leave-duration",
               [{"label": "Full day (9h)", "value": "full"},
                {"label": "Half day (4.5h)", "value": "half"}],
               "full"),

        # Date mode
        html.Div("Date entry", style={**_LABEL, "marginTop": "12px"}),
        _radio("lm-date-mode",
               [{"label": "Single date", "value": "single"},
                {"label": "Date range",  "value": "range"}],
               "single"),

        # Date pickers (toggle between single / range)
        html.Div([
            # Single date picker
            html.Div([
                html.Div("Date", style={**_LABEL, "marginTop": "10px"}),
                dcc.DatePickerSingle(
                    id="lm-leave-single",
                    date=str(date.today()),
                    display_format="DD MMM YYYY",
                    className="dark-datepicker",
                ),
            ], id="lm-single-wrap"),

            # Range picker
            html.Div([
                html.Div("From – To", style={**_LABEL, "marginTop": "10px"}),
                dcc.DatePickerRange(
                    id="lm-leave-range",
                    start_date=str(date.today()),
                    end_date=str(date.today()),
                    display_format="DD MMM YYYY",
                    className="dark-datepicker",
                ),
                html.Div("Weekends and company holidays are skipped automatically.",
                         style={"fontSize": "11px", "color": _T2, "marginTop": "4px"}),
            ], id="lm-range-wrap", style={"display": "none"}),
        ]),

        html.Button("Add Leave", id="lm-leave-add", n_clicks=0, style={
            **_BTN, "background": _BL, "color": "#0f172a", "marginTop": "16px",
        }),
        html.Div(id="lm-leave-msg", style={"marginTop": "8px", "fontSize": "12px"}),
    ], style=_CARD_STYLE)


# ── Tables ─────────────────────────────────────────────────────────────────────
def _holiday_table():
    return html.Div([
        html.Div("Upcoming Holidays", style={
            "fontSize": "13px", "fontWeight": "700", "color": _T1, "marginBottom": "12px",
        }),
        html.Div(id="lm-hol-table", style={"minHeight": "60px"}),
    ], style={**_CARD_STYLE, "marginTop": "16px"})


def _leave_table():
    return html.Div([
        html.Div([
            html.Div("Recorded Leaves", style={
                "fontSize": "13px", "fontWeight": "700", "color": _T1,
            }),
            html.Div("Filter by developer:", style={
                **_LABEL, "marginBottom": "0", "marginRight": "8px", "alignSelf": "center",
            }),
            dcc.Dropdown(
                id="lm-leave-filter-dev",
                options=[{"label": "All developers", "value": "all"}] + _DEV_OPTIONS,
                value="all",
                clearable=False,
                className="dark-dropdown",
                style={"minWidth": "200px", "fontSize": "12px"},
            ),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "12px"}),
        html.Div(id="lm-leave-table", style={"minHeight": "60px"}),
    ], style={**_CARD_STYLE, "marginTop": "16px"})


# ── Layout ────────────────────────────────────────────────────────────────────
layout = html.Div([
    # Page header
    html.Div([
        html.Div("LEAVE MANAGEMENT", style={
            "fontSize": "11px", "fontWeight": "800", "color": _PU,
            "letterSpacing": "2px", "marginBottom": "4px",
        }),
        html.H1("Holidays & Developer Leaves", style={
            "fontSize": "26px", "fontWeight": "700", "color": _T1, "margin": "0 0 4px",
        }),
        html.Div("Track company holidays and individual developer leaves · "
                 "Capacity grid updates automatically",
                 style={"fontSize": "13px", "color": _T2}),
    ], style={"marginBottom": "28px"}),

    # Two-column form row
    html.Div([
        html.Div(_holiday_form(), style={"flex": "0 0 340px"}),
        html.Div(_leave_form(),   style={"flex": "1", "minWidth": "0"}),
    ], style={"display": "flex", "gap": "20px", "alignItems": "flex-start", "marginBottom": "4px"}),

    # Tables row
    html.Div([
        html.Div(_holiday_table(), style={"flex": "0 0 340px"}),
        html.Div(_leave_table(),   style={"flex": "1", "minWidth": "0"}),
    ], style={"display": "flex", "gap": "20px", "alignItems": "flex-start"}),

    # Refresh stores
    dcc.Store(id="lm-refresh-hol",   data=0),
    dcc.Store(id="lm-refresh-leave", data=0),
], style={"padding": "28px 32px", "maxWidth": "1400px", "margin": "0 auto"})


# ── Callbacks ─────────────────────────────────────────────────────────────────

# Toggle single / range picker
@callback(
    Output("lm-single-wrap", "style"),
    Output("lm-range-wrap",  "style"),
    Input("lm-date-mode", "value"),
)
def _toggle_date_mode(mode):
    show = {"display": "block"}
    hide = {"display": "none"}
    return (show, hide) if mode == "single" else (hide, show)


# Add holiday
@callback(
    Output("lm-hol-msg",       "children"),
    Output("lm-hol-msg",       "style"),
    Output("lm-refresh-hol",   "data"),
    Input("lm-hol-add",        "n_clicks"),
    State("lm-hol-date",       "date"),
    State("lm-hol-name",       "value"),
    prevent_initial_call=True,
)
def _add_holiday(n, hol_date, name):
    if not hol_date or not name or not name.strip():
        return "Date and name are required.", {"color": _RE}, no_update

    try:
        d = date.fromisoformat(hol_date)
    except ValueError:
        return "Invalid date.", {"color": _RE}, no_update

    user = current_user.display_name if current_user.is_authenticated else "system"
    added = add_holiday(d, name.strip(), user)
    if added:
        return f"Holiday '{name.strip()}' added for {d.strftime('%d %b %Y')}.", \
               {"color": _GR}, n
    return "That date already has a holiday entry.", {"color": _AM}, no_update


# Add developer leave
@callback(
    Output("lm-leave-msg",     "children"),
    Output("lm-leave-msg",     "style"),
    Output("lm-refresh-leave", "data"),
    Input("lm-leave-add",      "n_clicks"),
    State("lm-dev-select",     "value"),
    State("lm-leave-type",     "value"),
    State("lm-leave-duration", "value"),
    State("lm-date-mode",      "value"),
    State("lm-leave-single",   "date"),
    State("lm-leave-range",    "start_date"),
    State("lm-leave-range",    "end_date"),
    prevent_initial_call=True,
)
def _add_leave(n, dev, leave_type, duration, mode, single_d, range_start, range_end):
    if not dev:
        return "Please select a developer.", {"color": _RE}, no_update

    hours = 4.5 if duration == "half" else 9.0

    try:
        if mode == "single":
            dates = [date.fromisoformat(single_d)]
        else:
            s = date.fromisoformat(range_start)
            e = date.fromisoformat(range_end)
            if s > e:
                return "Start date must be before end date.", {"color": _RE}, no_update
            hols = _holiday_set()
            dates = _workdays_in_range(s, e, hols)
            if not dates:
                return "No working days in that range (all weekends or holidays).", \
                       {"color": _AM}, no_update
    except (TypeError, ValueError):
        return "Invalid date selection.", {"color": _RE}, no_update

    user = current_user.display_name if current_user.is_authenticated else "system"
    added = add_dev_leave(dev, dates, leave_type, hours, user)
    day_word = "day" if added == 1 else "days"
    return (f"{added} leave {day_word} added for {dev} "
            f"({'half' if duration == 'half' else 'full'} day · {leave_type})."), \
           {"color": _GR}, n


# Render holiday table
@callback(
    Output("lm-hol-table", "children"),
    Input("lm-refresh-hol", "data"),
    Input({"type": "lm-del-hol", "id": ALL}, "n_clicks"),
)
def _render_hol_table(refresh, del_clicks):
    # Handle delete
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "lm-del-hol":
        if any(c for c in (del_clicks or []) if c):
            delete_holiday(triggered["id"])

    rows = get_holidays()
    if not rows:
        return html.Div("No holidays recorded yet.",
                        style={"fontSize": "13px", "color": _T2, "padding": "8px 0"})

    today = date.today()
    upcoming = [r for r in rows if r["date"] >= today]
    past     = [r for r in rows if r["date"] < today]
    display  = upcoming + past

    items = []
    for r in display:
        is_past = r["date"] < today
        items.append(html.Div([
            html.Div([
                html.Div(r["date"].strftime("%d %b %Y"), style={
                    "fontSize": "12px", "fontWeight": "700",
                    "color": _T2 if is_past else _T1,
                    "width": "90px", "flexShrink": "0",
                }),
                html.Div(r["name"], style={
                    "fontSize": "13px", "color": _T2 if is_past else _T1,
                    "flex": "1",
                }),
            ], style={"display": "flex", "alignItems": "center", "gap": "10px", "flex": "1"}),
            html.Button("✕", id={"type": "lm-del-hol", "id": r["id"]}, n_clicks=0,
                        style={
                            "background": "none", "border": "none", "cursor": "pointer",
                            "color": _RE, "fontSize": "14px", "padding": "0 4px",
                        }),
        ], style={
            "display": "flex", "alignItems": "center", "justifyContent": "space-between",
            "padding": "8px 0",
            "borderBottom": f"0.5px solid {_BD}",
            "opacity": "0.5" if is_past else "1",
        }))

    return html.Div(items)


# Render leave table
@callback(
    Output("lm-leave-table",       "children"),
    Input("lm-refresh-leave",      "data"),
    Input("lm-leave-filter-dev",   "value"),
    Input({"type": "lm-del-leave", "id": ALL}, "n_clicks"),
)
def _render_leave_table(refresh, filter_dev, del_clicks):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "lm-del-leave":
        if any(c for c in (del_clicks or []) if c):
            delete_dev_leave(triggered["id"])

    dev = None if (not filter_dev or filter_dev == "all") else filter_dev
    rows = get_dev_leaves(developer_name=dev)

    if not rows:
        return html.Div("No leaves recorded yet.",
                        style={"fontSize": "13px", "color": _T2, "padding": "8px 0"})

    header = html.Div([
        html.Div("Date",       style={"width": "95px",  "flexShrink": "0", "fontSize": "10px", "color": _T2, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div("Developer",  style={"width": "140px", "flexShrink": "0", "fontSize": "10px", "color": _T2, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div("Type",       style={"width": "75px",  "flexShrink": "0", "fontSize": "10px", "color": _T2, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div("Duration",   style={"width": "85px",  "flexShrink": "0", "fontSize": "10px", "color": _T2, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div("Logged by",  style={"flex": "1", "fontSize": "10px", "color": _T2, "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div("",           style={"width": "30px"}),
    ], style={"display": "flex", "gap": "10px", "padding": "6px 0",
              "borderBottom": f"1px solid {_BD}", "marginBottom": "4px"})

    items = [header]
    today = date.today()
    for r in rows:
        is_past = r["date"] < today
        type_color = _BL if r["type"] == "planned" else _AM
        dur_label  = "Full day" if r["hours"] >= 9 else "Half day"
        items.append(html.Div([
            html.Div(r["date"].strftime("%d %b %Y"), style={
                "width": "95px", "flexShrink": "0", "fontSize": "12px",
                "color": _T2 if is_past else _T1, "fontWeight": "600",
            }),
            html.Div(r["developer"], style={
                "width": "140px", "flexShrink": "0", "fontSize": "12px",
                "color": _T2 if is_past else _T1,
                "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis",
            }),
            html.Div([_tag(r["type"].title(), type_color)],
                     style={"width": "75px", "flexShrink": "0"}),
            html.Div(dur_label, style={
                "width": "85px", "flexShrink": "0",
                "fontSize": "12px", "color": _T2 if is_past else _T1,
            }),
            html.Div(r["created_by"] or "—", style={
                "flex": "1", "fontSize": "11px", "color": _T2,
            }),
            html.Button("✕", id={"type": "lm-del-leave", "id": r["id"]}, n_clicks=0,
                        style={
                            "background": "none", "border": "none", "cursor": "pointer",
                            "color": _RE, "fontSize": "14px", "padding": "0 4px", "width": "30px",
                        }),
        ], style={
            "display": "flex", "alignItems": "center", "gap": "10px",
            "padding": "7px 0",
            "borderBottom": f"0.5px solid {_BD}",
            "opacity": "0.5" if is_past else "1",
        }))

    return html.Div(items)
