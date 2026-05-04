"""Bug Tracker — Platform management page"""

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, callback, ctx, no_update
from flask_login import current_user

from db.platform_ops import (
    get_all_bugs, get_active_users,
    get_all_features, get_all_releases,
    create_bug, update_bug,
)

dash.register_page(__name__, path="/bug-tracker", name="Bug Tracker")


# ── Constants ─────────────────────────────────────────────────────────────────

STATES     = ["New", "Active", "Resolved", "Closed", "Rejected"]
BUG_TYPES  = ["Bug", "Bug_UI", "Bug_Text"]
SEVERITIES = ["Critical", "High", "Medium", "Low"]
PRIORITIES = [1, 2, 3, 4]
PRIORITY_LABELS = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}

STATE_COLORS = {
    "New":      "#818cf8",
    "Active":   "#60a5fa",
    "Resolved": "#34d399",
    "Closed":   "#64748b",
    "Rejected": "#f87171",
}

PRIORITY_COLORS = {
    1: "#f87171",
    2: "#fb923c",
    3: "#fbbf24",
    4: "#34d399",
}

TYPE_COLORS = {
    "Bug":      "#f87171",
    "Bug_UI":   "#c084fc",
    "Bug_Text": "#60a5fa",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state_badge(state):
    color = STATE_COLORS.get(state, "#64748b")
    return html.Span(state, style={
        "fontSize": "11px", "fontWeight": "600", "padding": "2px 10px",
        "borderRadius": "20px", "background": f"{color}22",
        "color": color, "border": f"1px solid {color}55",
    })


def _priority_badge(priority):
    label = PRIORITY_LABELS.get(priority, str(priority))
    color = PRIORITY_COLORS.get(priority, "#64748b")
    return html.Span(f"P{priority} {label}", style={
        "fontSize": "11px", "padding": "2px 8px", "borderRadius": "4px",
        "background": f"{color}22", "color": color,
        "border": f"1px solid {color}44",
    })


def _type_badge(bug_type):
    color = TYPE_COLORS.get(bug_type, "#64748b")
    return html.Span(bug_type, style={
        "fontSize": "11px", "padding": "2px 8px", "borderRadius": "4px",
        "background": f"{color}22", "color": color,
        "border": f"1px solid {color}44",
    })


def _pool_badge():
    return html.Span("Bug Pool", style={
        "fontSize": "10px", "padding": "2px 7px", "borderRadius": "20px",
        "background": "rgba(251,191,36,0.12)", "color": "#fbbf24",
        "border": "1px solid rgba(251,191,36,0.3)", "marginLeft": "6px",
    })


def _empty_state():
    return html.Div([
        html.Div("🐛", style={"fontSize": "40px", "marginBottom": "12px"}),
        html.Div("No bugs logged", style={"color": "#e2e8f0", "fontWeight": "600", "fontSize": "15px"}),
        html.Div("Log a bug to link it to a feature, or add it to the Bug Pool",
                 style={"color": "#64748b", "fontSize": "13px", "marginTop": "4px"}),
    ], style={"textAlign": "center", "padding": "60px 0"})


def _bug_row(bug, can_edit):
    is_pool = bug.get("linked_feature_id") is None
    return html.Div([
        # Row 1: ref + state + priority + type + pool badge
        html.Div([
            html.Span(bug["bug_ref"], style={
                "fontFamily": "monospace", "fontSize": "12px",
                "color": "#f87171", "fontWeight": "700", "marginRight": "10px",
            }),
            _state_badge(bug.get("state", "New")),
            html.Span(style={"marginLeft": "8px"}),
            _priority_badge(bug.get("priority", 2)),
            html.Span(style={"marginLeft": "8px"}),
            _type_badge(bug.get("bug_type", "Bug")),
            _pool_badge() if is_pool else html.Span(),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "5px"}),

        # Row 2: title
        html.Div(bug["title"], style={
            "fontSize": "15px", "fontWeight": "600", "color": "#e2e8f0", "marginBottom": "4px",
        }),

        # Row 3: linked feature + found in release/iteration
        html.Div([
            html.Span([
                html.Span("Feature: ", style={"color": "#64748b", "fontSize": "11px"}),
                html.Span(
                    bug.get("feature_ref") or "—",
                    style={"color": "#818cf8", "fontSize": "11px", "fontWeight": "600"}
                ),
                html.Span(f"  {bug.get('feature_title') or ''}", style={"color": "#64748b", "fontSize": "11px"}),
            ], style={
                "background": "rgba(129,140,248,0.08)", "border": "1px solid rgba(129,140,248,0.2)",
                "borderRadius": "6px", "padding": "2px 10px", "marginRight": "8px",
            }),
            html.Span([
                html.Span("Found: ", style={"color": "#64748b", "fontSize": "11px"}),
                html.Span(
                    bug.get("found_in_iteration") or "—",
                    style={"color": "#94a3b8", "fontSize": "11px"}
                ),
            ], style={
                "background": "rgba(255,255,255,0.04)", "border": "1px solid rgba(255,255,255,0.08)",
                "borderRadius": "6px", "padding": "2px 10px",
            }) if bug.get("found_in_iteration") else html.Span(),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "4px", "marginBottom": "6px"}),

        # Row 4: assignee + developer + edit
        html.Div([
            html.Div([
                html.Span("Assignee: ", style={"color": "#64748b", "fontSize": "12px"}),
                html.Span(bug.get("assignee_name") or "—", style={"color": "#94a3b8", "fontSize": "12px"}),
                html.Span("   Developer: ", style={"color": "#64748b", "fontSize": "12px"}),
                html.Span(bug.get("main_developer_name") or "—", style={"color": "#94a3b8", "fontSize": "12px"}),
            ], style={"flex": "1"}),
            dbc.Button("Edit",
                id={"type": "bug-edit-btn", "index": bug["bug_id"]},
                n_clicks=0, size="sm",
                style={
                    "fontSize": "12px", "padding": "4px 14px",
                    "background": "rgba(248,113,113,0.10)", "color": "#f87171",
                    "border": "1px solid rgba(248,113,113,0.25)", "borderRadius": "6px",
                },
            ) if can_edit else html.Div(),
        ], style={"display": "flex", "alignItems": "center", "gap": "12px"}),

    ], style={
        "background": "rgba(255,255,255,0.02)", "borderRadius": "10px",
        "border": "1px solid rgba(255,255,255,0.06)", "padding": "16px 20px",
        "marginBottom": "10px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    try:
        users    = get_active_users()
        features = get_all_features()
        releases = get_all_releases(include_archived=False)
    except Exception:
        users, features, releases = [], [], []

    feature_opts = [{"label": f"{f['feature_ref']} — {f['title']}", "value": f["feature_id"]} for f in features]
    release_opts = [{"label": f"{r['release_ref']} — {r['title']}", "value": r["release_id"]} for r in releases]
    user_opts    = [{"label": u["display_name"], "value": u["user_id"]} for u in users]

    return html.Div([
        dcc.Store(id="bugs-reload", data=0),
        dcc.Store(id="bug-editing-id", data=None),

        # Header
        html.Div([
            html.Div([
                html.H1("Bug Tracker", className="page-title"),
                html.P("Log and manage bugs. Link them to features or keep them in the Bug Pool.",
                       className="page-subtitle"),
            ]),
            dbc.Button(
                [html.Span("+", style={"marginRight": "6px", "fontSize": "16px"}), "Log Bug"],
                id="bug-new-btn", n_clicks=0,
                style={
                    "background": "linear-gradient(135deg,#f87171,#fb923c)",
                    "border": "none", "borderRadius": "8px", "color": "white",
                    "fontSize": "13px", "fontWeight": "600", "padding": "8px 18px",
                },
            ),
        ], className="page-header", style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}),

        # Filters
        html.Div([
            dcc.Dropdown(
                id="bug-filter-feature",
                options=[{"label": "All Features", "value": "all"},
                         {"label": "Bug Pool (no feature)", "value": "pool"}] + feature_opts,
                value="all", clearable=False,
                className="dark-dropdown",
                style={"width": "280px", "marginRight": "12px"},
            ),
            dcc.Dropdown(
                id="bug-filter-state",
                options=[{"label": "All States", "value": "all"}] + [{"label": s, "value": s} for s in STATES],
                value="all", clearable=False,
                className="dark-dropdown",
                style={"width": "160px", "marginRight": "12px"},
            ),
            dcc.Dropdown(
                id="bug-filter-priority",
                options=[{"label": "All Priorities", "value": "all"}] + [
                    {"label": f"P{p} {PRIORITY_LABELS[p]}", "value": p} for p in PRIORITIES
                ],
                value="all", clearable=False,
                className="dark-dropdown",
                style={"width": "160px", "marginRight": "12px"},
            ),
            dcc.Dropdown(
                id="bug-filter-type",
                options=[{"label": "All Types", "value": "all"}] + [{"label": t, "value": t} for t in BUG_TYPES],
                value="all", clearable=False,
                className="dark-dropdown",
                style={"width": "150px"},
            ),
        ], style={"display": "flex", "marginBottom": "20px", "flexWrap": "wrap", "gap": "8px"}),

        html.Div(id="bugs-list"),

        # ── Modal ──────────────────────────────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="bug-modal-title-label"), close_button=True),
            dbc.ModalBody([

                # Title
                dbc.Label("Title *", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Input(id="bug-modal-title", placeholder="Describe the bug briefly",
                          style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                 "color": "#e2e8f0", "marginBottom": "14px"}),

                # Bug Type + Priority + Severity
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Bug Type", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-type",
                                     options=[{"label": t, "value": t} for t in BUG_TYPES],
                                     value="Bug", clearable=False, className="dark-dropdown"),
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Priority", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-priority",
                                     options=[{"label": f"P{p} — {PRIORITY_LABELS[p]}", "value": p} for p in PRIORITIES],
                                     value=2, clearable=False, className="dark-dropdown"),
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Severity", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-severity",
                                     options=[{"label": s, "value": s} for s in SEVERITIES],
                                     value="High", clearable=False, className="dark-dropdown"),
                    ], width=4),
                ], className="mb-3"),

                # State + Linked Feature
                dbc.Row([
                    dbc.Col([
                        dbc.Label("State", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-state",
                                     options=[{"label": s, "value": s} for s in STATES],
                                     value="New", clearable=False, className="dark-dropdown"),
                    ], width=4),
                    dbc.Col([
                        dbc.Label("Linked Feature (optional)", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-feature",
                                     options=feature_opts,
                                     placeholder="Leave blank for Bug Pool",
                                     clearable=True, className="dark-dropdown"),
                    ], width=8),
                ], className="mb-3"),

                # Found in Iteration + Found in Release
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Found in Iteration", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dbc.Input(id="bug-modal-iteration", placeholder="e.g. 2026.04",
                                  style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                         "color": "#e2e8f0"}),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Found in Release", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-release",
                                     options=release_opts,
                                     placeholder="Select release...",
                                     clearable=True, className="dark-dropdown"),
                    ], width=6),
                ], className="mb-3"),

                # Assignee + Developer
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Assignee", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-assignee", options=user_opts,
                                     placeholder="Select assignee...", clearable=True,
                                     className="dark-dropdown"),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Developer", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="bug-modal-developer", options=user_opts,
                                     placeholder="Select developer...", clearable=True,
                                     className="dark-dropdown"),
                    ], width=6),
                ], className="mb-3"),

                # Area + Function
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Area", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dbc.Input(id="bug-modal-area", placeholder="e.g. Billing",
                                  style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                         "color": "#e2e8f0"}),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Function", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dbc.Input(id="bug-modal-func", placeholder="e.g. Export",
                                  style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                         "color": "#e2e8f0"}),
                    ], width=6),
                ], className="mb-3"),

                # ADO ID
                dbc.Label("ADO Work Item ID (optional)", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Input(id="bug-modal-ado", placeholder="e.g. 12345", type="number",
                          style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                 "color": "#e2e8f0", "marginBottom": "14px"}),

                # Repro Steps
                dbc.Label("Repro Steps", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Textarea(id="bug-modal-repro", placeholder="Steps to reproduce...", rows=3,
                             style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                    "color": "#e2e8f0", "resize": "none", "marginBottom": "4px"}),

                html.Div(id="bug-modal-error", style={"color": "#f87171", "fontSize": "13px", "marginTop": "8px"}),
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="bug-modal-cancel", color="secondary", size="sm",
                           style={"marginRight": "8px"}),
                dbc.Button("Save Bug", id="bug-modal-save", size="sm",
                           style={
                               "background": "linear-gradient(135deg,#f87171,#fb923c)",
                               "border": "none", "color": "white", "fontWeight": "600",
                           }),
            ]),
        ], id="bug-modal", is_open=False, size="lg", backdrop="static"),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("bugs-list", "children"),
    Input("bugs-reload", "data"),
    Input("bug-filter-feature", "value"),
    Input("bug-filter-state", "value"),
    Input("bug-filter-priority", "value"),
    Input("bug-filter-type", "value"),
)
def refresh_list(_, filter_feature, filter_state, filter_priority, filter_type):
    try:
        if filter_feature == "pool":
            bugs = get_all_bugs(pool_only=True)
        elif filter_feature and filter_feature != "all":
            bugs = get_all_bugs(linked_feature_id=int(filter_feature))
        else:
            bugs = get_all_bugs()
    except Exception:
        bugs = []

    if filter_state and filter_state != "all":
        bugs = [b for b in bugs if b.get("state") == filter_state]
    if filter_priority and filter_priority != "all":
        bugs = [b for b in bugs if b.get("priority") == filter_priority]
    if filter_type and filter_type != "all":
        bugs = [b for b in bugs if b.get("bug_type") == filter_type]

    if not bugs:
        return _empty_state()

    try:
        can_edit = current_user.is_authenticated
    except Exception:
        can_edit = False

    return [_bug_row(b, can_edit) for b in bugs]


@callback(
    Output("bug-modal", "is_open"),
    Output("bug-modal-title-label", "children"),
    Output("bug-editing-id", "data"),
    Output("bug-modal-title", "value"),
    Output("bug-modal-type", "value"),
    Output("bug-modal-priority", "value"),
    Output("bug-modal-severity", "value"),
    Output("bug-modal-state", "value"),
    Output("bug-modal-feature", "value"),
    Output("bug-modal-iteration", "value"),
    Output("bug-modal-release", "value"),
    Output("bug-modal-assignee", "value"),
    Output("bug-modal-developer", "value"),
    Output("bug-modal-area", "value"),
    Output("bug-modal-func", "value"),
    Output("bug-modal-ado", "value"),
    Output("bug-modal-repro", "value"),
    Output("bug-modal-error", "children"),
    Input("bug-new-btn", "n_clicks"),
    Input({"type": "bug-edit-btn", "index": dash.ALL}, "n_clicks"),
    Input("bug-modal-cancel", "n_clicks"),
    State("bug-editing-id", "data"),
    prevent_initial_call=True,
)
def open_modal(new_clicks, edit_clicks, cancel_clicks, editing_id):
    trigger = ctx.triggered_id
    _blank = (None, "", "Bug", 2, "High", "New", None, "", None, None, None, "", "", None, "", "")

    if trigger == "bug-new-btn":
        return (True, "Log New Bug") + _blank

    if trigger == "bug-modal-cancel":
        return (False, no_update) + _blank

    if isinstance(trigger, dict) and trigger.get("type") == "bug-edit-btn":
        bug_id = trigger["index"]
        from db.platform_ops import get_bug
        b = get_bug(bug_id)
        if not b:
            return (False, no_update) + _blank
        return (
            True,
            f"Edit Bug — {b['bug_ref']}",
            bug_id,
            b.get("title", ""),
            b.get("bug_type", "Bug"),
            b.get("priority", 2),
            b.get("severity", "High"),
            b.get("state", "New"),
            b.get("linked_feature_id"),
            b.get("found_in_iteration", ""),
            b.get("found_in_release_id"),
            b.get("assigned_to_id"),
            b.get("main_developer_id"),
            b.get("area", ""),
            b.get("func", ""),
            b.get("ado_id"),
            b.get("repro_steps", ""),
            "",
        )

    return (False, no_update) + _blank


@callback(
    Output("bugs-reload", "data"),
    Output("bug-modal", "is_open", allow_duplicate=True),
    Output("bug-modal-error", "children", allow_duplicate=True),
    Input("bug-modal-save", "n_clicks"),
    State("bug-editing-id", "data"),
    State("bug-modal-title", "value"),
    State("bug-modal-type", "value"),
    State("bug-modal-priority", "value"),
    State("bug-modal-severity", "value"),
    State("bug-modal-state", "value"),
    State("bug-modal-feature", "value"),
    State("bug-modal-iteration", "value"),
    State("bug-modal-release", "value"),
    State("bug-modal-assignee", "value"),
    State("bug-modal-developer", "value"),
    State("bug-modal-area", "value"),
    State("bug-modal-func", "value"),
    State("bug-modal-ado", "value"),
    State("bug-modal-repro", "value"),
    State("bugs-reload", "data"),
    prevent_initial_call=True,
)
def save_bug(n, editing_id, title, bug_type, priority, severity, state,
             feature_id, iteration, release_id, assignee_id, developer_id,
             area, func, ado_id, repro_steps, reload_ctr):
    if not n:
        return no_update, no_update, no_update

    if not title or not title.strip():
        return no_update, no_update, "Title is required."

    try:
        user_id = current_user.id if current_user.is_authenticated else 1
    except Exception:
        user_id = 1

    try:
        if editing_id:
            fields = {
                "title": title.strip(),
                "bug_type": bug_type,
                "linked_feature_id": feature_id,
                "priority": priority,
                "severity": severity,
                "state": state,
                "assigned_to_id": assignee_id,
                "main_developer_id": developer_id,
                "area": area or None,
                "func": func or None,
                "found_in_iteration": iteration or None,
                "found_in_release_id": release_id,
                "repro_steps": repro_steps or None,
            }
            update_bug(editing_id, fields, user_id)
        else:
            create_bug(
                title=title.strip(),
                bug_type=bug_type,
                linked_feature_id=feature_id,
                priority=priority,
                severity=severity,
                assigned_to_id=assignee_id,
                main_developer_id=developer_id,
                area=area or None,
                func=func or None,
                found_in_iteration=iteration or None,
                found_in_release_id=release_id,
                repro_steps=repro_steps or None,
                created_by=user_id,
            )
    except Exception as e:
        return no_update, no_update, f"Error saving bug: {e}"

    return (reload_ctr or 0) + 1, False, ""
