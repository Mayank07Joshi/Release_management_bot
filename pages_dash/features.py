"""Features — Platform management page"""

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, callback, ctx, no_update
from flask_login import current_user

from db.platform_ops import (
    get_all_features, get_active_users,
    get_all_epics, get_all_releases,
    create_feature, update_feature,
    create_tasks_from_templates, get_tasks_for_feature,
)
from db.templates import TEMPLATES, TEMPLATE_ORDER

dash.register_page(__name__, path="/features", name="Features")


# ── Constants ─────────────────────────────────────────────────────────────────

STATES = ["Backlog", "In Progress", "In Review", "Testing", "Done", "On Hold"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]

PRIORITY_MAP     = {"Critical": 1, "High": 2, "Medium": 3, "Low": 4}
INT_TO_PRIORITY  = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}

STATE_COLORS = {
    "Backlog":     "#64748b",
    "In Progress": "#818cf8",
    "In Review":   "#60a5fa",
    "Testing":     "#fb923c",
    "Done":        "#34d399",
    "On Hold":     "#f87171",
}

PRIORITY_COLORS = {
    "Critical": "#f87171",
    "High":     "#fb923c",
    "Medium":   "#fbbf24",
    "Low":      "#34d399",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state_badge(state):
    color = STATE_COLORS.get(state, "#64748b")
    return html.Span(state, style={
        "fontSize": "11px", "fontWeight": "600", "padding": "2px 10px",
        "borderRadius": "20px", "background": f"{color}22",
        "color": color, "border": f"1px solid {color}55",
    })


def _priority_dot(priority):
    color = PRIORITY_COLORS.get(priority, "#64748b")
    return html.Span(priority, style={
        "fontSize": "11px", "padding": "2px 8px", "borderRadius": "4px",
        "background": f"{color}22", "color": color,
        "border": f"1px solid {color}44",
    })


def _spill_badge():
    return html.Span("Spill-over", style={
        "fontSize": "10px", "padding": "2px 7px", "borderRadius": "20px",
        "background": "rgba(251,146,60,0.15)", "color": "#fb923c",
        "border": "1px solid rgba(251,146,60,0.3)", "marginLeft": "6px",
    })


def _empty_state():
    return html.Div([
        html.Div("📋", style={"fontSize": "40px", "marginBottom": "12px"}),
        html.Div("No features yet", style={"color": "#e2e8f0", "fontWeight": "600", "fontSize": "15px"}),
        html.Div("Create a feature to link an Epic with a Release",
                 style={"color": "#64748b", "fontSize": "13px", "marginTop": "4px"}),
    ], style={"textAlign": "center", "padding": "60px 0"})


def _feature_row(feat, can_edit):
    spill = feat.get("spill_over")
    return html.Div([
        # Row 1: ref + state + priority + spill
        html.Div([
            html.Span(feat["feature_ref"], style={
                "fontFamily": "monospace", "fontSize": "12px",
                "color": "#818cf8", "fontWeight": "700", "marginRight": "10px",
            }),
            _state_badge(feat.get("state", "Backlog")),
            html.Span(style={"marginLeft": "8px"}),
            _priority_dot(feat.get("priority", "Medium")),
            _spill_badge() if spill else html.Span(),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "5px"}),

        # Row 2: title
        html.Div(feat["title"], style={
            "fontSize": "15px", "fontWeight": "600", "color": "#e2e8f0", "marginBottom": "4px",
        }),

        # Row 3: epic + release chips
        html.Div([
            html.Span([
                html.Span("Epic: ", style={"color": "#64748b", "fontSize": "11px"}),
                html.Span(feat.get("epic_ref") or "—",
                          style={"color": "#818cf8", "fontSize": "11px", "fontWeight": "600"}),
                html.Span(f"  {feat.get('epic_title') or ''}", style={"color": "#64748b", "fontSize": "11px"}),
            ], style={
                "background": "rgba(129,140,248,0.08)", "border": "1px solid rgba(129,140,248,0.2)",
                "borderRadius": "6px", "padding": "2px 10px", "marginRight": "8px",
            }),
            html.Span([
                html.Span("Release: ", style={"color": "#64748b", "fontSize": "11px"}),
                html.Span(feat.get("release_ref") or "—",
                          style={"color": "#60a5fa", "fontSize": "11px", "fontWeight": "600"}),
                html.Span(f"  {feat.get('release_title') or ''}", style={"color": "#64748b", "fontSize": "11px"}),
            ], style={
                "background": "rgba(96,165,250,0.08)", "border": "1px solid rgba(96,165,250,0.2)",
                "borderRadius": "6px", "padding": "2px 10px", "marginRight": "8px",
            }),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": "4px", "marginBottom": "6px"}),

        # Row 4: assignee + dev + task count + edit
        html.Div([
            html.Div([
                html.Span("Assignee: ", style={"color": "#64748b", "fontSize": "12px"}),
                html.Span(feat.get("assignee_name") or "—", style={"color": "#94a3b8", "fontSize": "12px"}),
                html.Span("   Dev: ", style={"color": "#64748b", "fontSize": "12px"}),
                html.Span(feat.get("developer_name") or "—", style={"color": "#94a3b8", "fontSize": "12px"}),
            ], style={"flex": "1"}),
            # Task count badge
            html.Span(
                f"{feat.get('tasks_done', 0)}/{feat.get('task_count', 0)} tasks",
                style={
                    "fontSize": "11px", "padding": "2px 10px", "borderRadius": "20px",
                    "background": "rgba(52,211,153,0.1)", "color": "#34d399",
                    "border": "1px solid rgba(52,211,153,0.25)", "marginRight": "4px",
                }
            ) if feat.get("task_count", 0) > 0 else html.Span(),
            dbc.Button("Tasks",
                id={"type": "feat-tasks-btn", "index": feat["feature_id"]},
                n_clicks=0, size="sm",
                style={
                    "fontSize": "12px", "padding": "4px 14px",
                    "background": "rgba(52,211,153,0.08)", "color": "#34d399",
                    "border": "1px solid rgba(52,211,153,0.2)", "borderRadius": "6px",
                },
            ) if can_edit else html.Div(),
            dbc.Button("Edit",
                id={"type": "feat-edit-btn", "index": feat["feature_id"]},
                n_clicks=0, size="sm",
                style={
                    "fontSize": "12px", "padding": "4px 14px",
                    "background": "rgba(129,140,248,0.12)", "color": "#818cf8",
                    "border": "1px solid rgba(129,140,248,0.25)", "borderRadius": "6px",
                },
            ) if can_edit else html.Div(),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px"}),

    ], style={
        "background": "rgba(255,255,255,0.02)", "borderRadius": "10px",
        "border": "1px solid rgba(255,255,255,0.06)", "padding": "16px 20px",
        "marginBottom": "10px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    try:
        users    = get_active_users()
        epics    = get_all_epics()
        releases = get_all_releases(include_archived=False)
    except Exception:
        users, epics, releases = [], [], []

    epic_opts    = [{"label": f"{e['epic_ref']} — {e['title']}", "value": e["epic_id"]}    for e in epics]
    release_opts = [{"label": f"{r['release_ref']} — {r['title']}", "value": r["release_id"]} for r in releases]
    user_opts    = [{"label": u["display_name"], "value": u["user_id"]} for u in users]

    # Template selector options (built once at layout time)
    template_opts = [
        {"label": TEMPLATES[k]["label"], "value": k}
        for k in TEMPLATE_ORDER
    ]

    return html.Div([
        dcc.Store(id="features-reload",   data=0),
        dcc.Store(id="feat-editing-id",   data=None),
        dcc.Store(id="feat-just-created", data=None),  # {feature_id, feature_ref, feature_title}

        # Header
        html.Div([
            html.Div([
                html.H1("Features", className="page-title"),
                html.P("Work items that belong to an Epic and are planned for a Release.",
                       className="page-subtitle"),
            ]),
            dbc.Button(
                [html.Span("+", style={"marginRight": "6px", "fontSize": "16px"}), "New Feature"],
                id="feat-new-btn", n_clicks=0,
                style={
                    "background": "linear-gradient(135deg,#6366f1,#818cf8)",
                    "border": "none", "borderRadius": "8px", "color": "white",
                    "fontSize": "13px", "fontWeight": "600", "padding": "8px 18px",
                },
            ),
        ], className="page-header", style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}),

        # Filters
        html.Div([
            dcc.Dropdown(
                id="feat-filter-epic",
                options=[{"label": "All Epics", "value": "all"}] + epic_opts,
                value="all", clearable=False,
                className="dark-dropdown",
                style={"width": "260px", "marginRight": "12px"},
            ),
            dcc.Dropdown(
                id="feat-filter-release",
                options=[{"label": "All Releases", "value": "all"}] + release_opts,
                value="all", clearable=False,
                className="dark-dropdown",
                style={"width": "260px", "marginRight": "12px"},
            ),
            dcc.Dropdown(
                id="feat-filter-state",
                options=[{"label": "All States", "value": "all"}] + [{"label": s, "value": s} for s in STATES],
                value="all", clearable=False,
                className="dark-dropdown",
                style={"width": "180px"},
            ),
        ], style={"display": "flex", "marginBottom": "20px", "flexWrap": "wrap", "gap": "8px"}),

        html.Div(id="features-list"),

        # ── Modal ──────────────────────────────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="feat-modal-title-label"), close_button=True),
            dbc.ModalBody([
                # Title
                dbc.Label("Title *", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Input(id="feat-modal-title", placeholder="Feature title",
                          style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                 "color": "#e2e8f0", "marginBottom": "14px"}),
                # Description
                dbc.Label("Description", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Textarea(id="feat-modal-desc", placeholder="What does this feature deliver?", rows=2,
                             style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                    "color": "#e2e8f0", "resize": "none", "marginBottom": "14px"}),
                # Epic + Release
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Epic *", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="feat-modal-epic", options=epic_opts,
                                     placeholder="Select epic...", clearable=True,
                                     className="dark-dropdown"),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Planned Release *", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="feat-modal-release", options=release_opts,
                                     placeholder="Select release...", clearable=True,
                                     className="dark-dropdown"),
                    ], width=6),
                ], className="mb-3"),
                # Priority + State
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Priority", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="feat-modal-priority",
                                     options=[{"label": p, "value": p} for p in PRIORITIES],
                                     value="Medium", clearable=False, className="dark-dropdown"),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("State", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="feat-modal-state",
                                     options=[{"label": s, "value": s} for s in STATES],
                                     value="Backlog", clearable=False, className="dark-dropdown"),
                    ], width=6),
                ], className="mb-3"),
                # Assignee + Developer
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Assignee (PM/Owner)", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="feat-modal-assignee", options=user_opts,
                                     placeholder="Select...", clearable=True, className="dark-dropdown"),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Main Developer", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(id="feat-modal-dev", options=user_opts,
                                     placeholder="Select...", clearable=True, className="dark-dropdown"),
                    ], width=6),
                ], className="mb-3"),
                # Estimate + Iteration
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Original Estimate (hrs)", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dbc.Input(id="feat-modal-estimate", type="number", min=0, step=0.5,
                                  placeholder="e.g. 8",
                                  style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                         "color": "#e2e8f0"}),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Tags", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dbc.Input(id="feat-modal-tags", placeholder="Comma-separated",
                                  style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                         "color": "#e2e8f0"}),
                    ], width=6),
                ], className="mb-2"),
                html.Div(id="feat-modal-error",
                         style={"color": "#f87171", "fontSize": "13px", "marginTop": "10px"}),
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="feat-modal-cancel", color="secondary", outline=True, size="sm", n_clicks=0),
                dbc.Button("Save", id="feat-modal-save", n_clicks=0, size="sm",
                           style={"background": "linear-gradient(135deg,#6366f1,#818cf8)", "border": "none"}),
            ]),
        ], id="feat-modal", is_open=False, backdrop="static", size="lg",
           style={"--bs-modal-bg": "#13132b", "--bs-modal-border-color": "rgba(255,255,255,0.1)"}),

        # ── Template Selector Modal ────────────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="tmpl-modal-label"), close_button=True),
            dbc.ModalBody([
                html.P("Select task templates to auto-generate for this feature.",
                       style={"color": "#64748b", "fontSize": "13px", "marginBottom": "16px"}),
                dbc.Checklist(
                    id="tmpl-checklist",
                    options=template_opts,
                    value=[],
                    labelStyle={"display": "flex", "alignItems": "center", "gap": "8px",
                                "padding": "10px 14px", "borderRadius": "8px", "cursor": "pointer",
                                "border": "1px solid rgba(255,255,255,0.06)",
                                "marginBottom": "6px", "color": "#e2e8f0", "fontSize": "13px",
                                "background": "rgba(255,255,255,0.02)"},
                    inputStyle={"accentColor": "#6366f1"},
                ),
                html.Div(id="tmpl-modal-error",
                         style={"color": "#f87171", "fontSize": "13px", "marginTop": "10px"}),
            ]),
            dbc.ModalFooter([
                dbc.Button("Skip for now", id="tmpl-modal-skip", color="secondary",
                           outline=True, size="sm", n_clicks=0, style={"marginRight": "8px"}),
                dbc.Button("Add Selected Tasks", id="tmpl-modal-save", size="sm", n_clicks=0,
                           style={"background": "linear-gradient(135deg,#6366f1,#818cf8)",
                                  "border": "none", "color": "white", "fontWeight": "600"}),
            ]),
        ], id="tmpl-modal", is_open=False, backdrop="static", size="md",
           style={"--bs-modal-bg": "#13132b", "--bs-modal-border-color": "rgba(255,255,255,0.1)"}),

        # ── Task Panel Modal (view/manage tasks for a feature) ─────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="tasks-panel-label"), close_button=True),
            dbc.ModalBody([
                html.Div(id="tasks-panel-body"),
            ]),
            dbc.ModalFooter([
                dbc.Button("Add More Tasks", id="tasks-panel-add-btn", size="sm", n_clicks=0,
                           style={"background": "linear-gradient(135deg,#6366f1,#818cf8)",
                                  "border": "none", "color": "white", "fontWeight": "600",
                                  "marginRight": "8px"}),
                dbc.Button("Close", id="tasks-panel-close", color="secondary",
                           outline=True, size="sm", n_clicks=0),
            ]),
        ], id="tasks-panel", is_open=False, size="lg",
           style={"--bs-modal-bg": "#13132b", "--bs-modal-border-color": "rgba(255,255,255,0.1)"}),

        dcc.Store(id="tasks-panel-feature-id", data=None),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("features-list", "children"),
    Input("feat-filter-epic",    "value"),
    Input("feat-filter-release", "value"),
    Input("feat-filter-state",   "value"),
    Input("features-reload",     "data"),
)
def _render_list(epic_filter, release_filter, state_filter, _reload):
    try:
        epic_id    = None if epic_filter    == "all" else epic_filter
        release_id = None if release_filter == "all" else release_filter
        features   = get_all_features(epic_id=epic_id, release_id=release_id)
    except Exception as e:
        return html.Div(f"Error loading features: {e}", style={"color": "#f87171"})

    if state_filter != "all":
        features = [f for f in features if f.get("state") == state_filter]

    # Attach task counts
    for feat in features:
        try:
            tasks = get_tasks_for_feature(feat["feature_id"])
            feat["task_count"] = len(tasks)
            feat["tasks_done"] = sum(1 for t in tasks if t.get("state") == "Done")
        except Exception:
            feat["task_count"] = 0
            feat["tasks_done"] = 0

    try:
        can_edit = current_user.is_authenticated and current_user.can("edit_feature")
    except Exception:
        can_edit = False

    if not features:
        return _empty_state()

    return [_feature_row(f, can_edit) for f in features]


@callback(
    Output("feat-modal",             "is_open"),
    Output("feat-modal-title-label", "children"),
    Output("feat-modal-title",       "value"),
    Output("feat-modal-desc",        "value"),
    Output("feat-modal-epic",        "value"),
    Output("feat-modal-release",     "value"),
    Output("feat-modal-priority",    "value"),
    Output("feat-modal-state",       "value"),
    Output("feat-modal-assignee",    "value"),
    Output("feat-modal-dev",         "value"),
    Output("feat-modal-estimate",    "value"),
    Output("feat-modal-tags",        "value"),
    Output("feat-editing-id",        "data"),
    Output("feat-modal-error",       "children"),
    Input("feat-new-btn",  "n_clicks"),
    Input({"type": "feat-edit-btn", "index": dash.ALL}, "n_clicks"),
    Input("feat-modal-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def _toggle_modal(new_clicks, edit_clicks, cancel_clicks):
    triggered = ctx.triggered_id

    blank = (False, no_update, no_update, no_update, no_update, no_update,
             no_update, no_update, no_update, no_update, no_update, no_update, None, "")

    if triggered == "feat-modal-cancel":
        return blank

    if triggered == "feat-new-btn" and new_clicks:
        return (True, "New Feature", "", "", None, None,
                "Medium", "Backlog", None, None, None, "", None, "")

    if isinstance(triggered, dict) and triggered.get("type") == "feat-edit-btn":
        fid = triggered["index"]
        try:
            features = get_all_features()
            feat = next((f for f in features if f["feature_id"] == fid), None)
            if feat:
                return (
                    True,
                    f"Edit {feat['feature_ref']}",
                    feat["title"],
                    feat.get("description") or "",
                    feat.get("epic_id"),
                    feat.get("planned_release_id"),
                    INT_TO_PRIORITY.get(feat.get("priority"), "Medium"),
                    feat.get("state", "Backlog"),
                    feat.get("assigned_to_id"),
                    feat.get("main_developer_id"),
                    feat.get("original_estimate"),
                    feat.get("tags") or "",
                    fid,
                    "",
                )
        except Exception as e:
            return (True, "Error", "", "", None, None,
                    "Medium", "Backlog", None, None, None, "", None, str(e))

    return blank


@callback(
    Output("feat-modal",        "is_open",  allow_duplicate=True),
    Output("features-reload",   "data"),
    Output("feat-modal-error",  "children", allow_duplicate=True),
    Output("feat-just-created", "data"),
    Input("feat-modal-save",    "n_clicks"),
    State("feat-modal-title",    "value"),
    State("feat-modal-desc",     "value"),
    State("feat-modal-epic",     "value"),
    State("feat-modal-release",  "value"),
    State("feat-modal-priority", "value"),
    State("feat-modal-state",    "value"),
    State("feat-modal-assignee", "value"),
    State("feat-modal-dev",      "value"),
    State("feat-modal-estimate", "value"),
    State("feat-modal-tags",     "value"),
    State("feat-editing-id",     "data"),
    State("features-reload",     "data"),
    prevent_initial_call=True,
)
def _save(save_clicks, title, desc, epic_id, release_id, priority, state,
          assignee_id, dev_id, estimate, tags, feat_id, reload_count):
    if not save_clicks:
        return no_update, no_update, no_update, no_update

    if not title or not title.strip():
        return no_update, no_update, "Title is required.", no_update
    if not epic_id:
        return no_update, no_update, "Please select an Epic.", no_update
    if not release_id:
        return no_update, no_update, "Please select a Release.", no_update

    user_id = current_user.id if current_user.is_authenticated else None
    priority_int = PRIORITY_MAP.get(priority, 2)

    try:
        if feat_id:
            update_feature(feat_id, {
                "title":              title.strip(),
                "description":        desc or "",
                "epic_id":            epic_id,
                "planned_release_id": release_id,
                "priority":           priority_int,
                "state":              state,
                "assigned_to_id":     assignee_id,
                "main_developer_id":  dev_id,
                "original_estimate":  estimate,
                "tags":               tags or "",
            }, updated_by=user_id)
            # Edits don't trigger template selector
            return False, (reload_count or 0) + 1, "", None
        else:
            ref, new_id = create_feature(
                title=title.strip(),
                description=desc or "",
                epic_id=epic_id,
                planned_release_id=release_id,
                iteration=None,
                priority=priority_int,
                assigned_to_id=assignee_id,
                main_developer_id=dev_id,
                main_designer_id=None,
                original_estimate=estimate,
                area=None,
                func=None,
                tags=tags or "",
                created_by=user_id,
            )
            # Trigger template selector for new features
            created_info = {
                "feature_id":    new_id,
                "feature_ref":   ref,
                "feature_title": title.strip(),
                "assignee_id":   assignee_id,
            }
            return False, (reload_count or 0) + 1, "", created_info

    except Exception as e:
        return no_update, no_update, f"Error: {e}", no_update


# ── Template selector: open when a new feature is created ─────────────────────

@callback(
    Output("tmpl-modal",       "is_open"),
    Output("tmpl-modal-label", "children"),
    Output("tmpl-checklist",   "value"),
    Input("feat-just-created", "data"),
    prevent_initial_call=True,
)
def _open_template_modal(created_info):
    if not created_info:
        return False, no_update, []
    ref   = created_info.get("feature_ref", "")
    title = created_info.get("feature_title", "")
    label = f"Add tasks to {ref} — {title[:50]}"
    return True, label, []


# ── Template selector: create tasks or skip ───────────────────────────────────

@callback(
    Output("tmpl-modal",      "is_open",  allow_duplicate=True),
    Output("features-reload", "data",     allow_duplicate=True),
    Output("tmpl-modal-error","children"),
    Input("tmpl-modal-save",  "n_clicks"),
    Input("tmpl-modal-skip",  "n_clicks"),
    State("feat-just-created","data"),
    State("tmpl-checklist",   "value"),
    State("features-reload",  "data"),
    prevent_initial_call=True,
)
def _handle_templates(save_clicks, skip_clicks, created_info, selected_keys, reload_count):
    trigger = ctx.triggered_id
    if trigger == "tmpl-modal-skip" or not created_info:
        return False, no_update, ""

    if not selected_keys:
        return False, no_update, ""

    try:
        user_id = current_user.id if current_user.is_authenticated else None
        create_tasks_from_templates(
            feature_id=created_info["feature_id"],
            feature_ref=created_info["feature_ref"],
            feature_title=created_info["feature_title"],
            template_keys=selected_keys,
            assigned_to_id=created_info.get("assignee_id"),
            created_by=user_id,
        )
    except Exception as e:
        return no_update, no_update, f"Error creating tasks: {e}"

    return False, (reload_count or 0) + 1, ""


# ── Task panel: open for a feature ────────────────────────────────────────────

@callback(
    Output("tasks-panel",            "is_open"),
    Output("tasks-panel-label",      "children"),
    Output("tasks-panel-body",       "children"),
    Output("tasks-panel-feature-id", "data"),
    Input({"type": "feat-tasks-btn", "index": dash.ALL}, "n_clicks"),
    Input("tasks-panel-close",       "n_clicks"),
    prevent_initial_call=True,
)
def _open_tasks_panel(task_btn_clicks, close_clicks):
    trigger = ctx.triggered_id
    if trigger == "tasks-panel-close":
        return False, no_update, no_update, no_update

    if not isinstance(trigger, dict) or trigger.get("type") != "feat-tasks-btn":
        return False, no_update, no_update, no_update

    feature_id = trigger["index"]
    try:
        features = get_all_features()
        feat = next((f for f in features if f["feature_id"] == feature_id), None)
        tasks = get_tasks_for_feature(feature_id)
    except Exception as e:
        return True, "Error", html.Div(str(e), style={"color": "#f87171"}), None

    label = f"Tasks — {feat['feature_ref'] if feat else ''} {feat['title'][:50] if feat else ''}"

    TASK_STATE_COLORS = {
        "To Do":       "#64748b",
        "In Progress": "#818cf8",
        "Done":        "#34d399",
        "Blocked":     "#f87171",
    }

    if not tasks:
        body = html.Div([
            html.Div("No tasks yet.", style={"color": "#64748b", "textAlign": "center", "padding": "30px 0"}),
        ])
    else:
        rows = []
        for t in tasks:
            sc = TASK_STATE_COLORS.get(t.get("state", "To Do"), "#64748b")
            rows.append(html.Div([
                html.Div([
                    html.Span(t["task_ref"], style={
                        "fontFamily": "monospace", "fontSize": "11px",
                        "color": "#6366f1", "marginRight": "8px",
                    }),
                    html.Span(t.get("state", "To Do"), style={
                        "fontSize": "11px", "padding": "1px 8px", "borderRadius": "20px",
                        "background": f"{sc}22", "color": sc, "border": f"1px solid {sc}44",
                        "marginRight": "8px",
                    }),
                    html.Span(t.get("activity", ""), style={"fontSize": "11px", "color": "#64748b"}),
                ], style={"marginBottom": "3px"}),
                html.Div(t["title"], style={"fontSize": "13px", "color": "#e2e8f0", "marginBottom": "2px"}),
                html.Div([
                    html.Span(f"{t.get('original_estimate') or '—'} hrs estimated",
                              style={"fontSize": "11px", "color": "#64748b", "marginRight": "12px"}),
                    html.Span(f"Assignee: {t.get('assignee_name') or '—'}",
                              style={"fontSize": "11px", "color": "#64748b"}),
                ]),
            ], style={
                "padding": "12px 16px", "marginBottom": "6px", "borderRadius": "8px",
                "background": "rgba(255,255,255,0.02)", "border": "1px solid rgba(255,255,255,0.06)",
            }))
        body = html.Div(rows)

    return True, label, body, feature_id


# ── Task panel: "Add More Tasks" reopens template selector for same feature ───

@callback(
    Output("feat-just-created",  "data",    allow_duplicate=True),
    Output("tasks-panel",        "is_open", allow_duplicate=True),
    Input("tasks-panel-add-btn", "n_clicks"),
    State("tasks-panel-feature-id", "data"),
    State("features-reload",        "data"),
    prevent_initial_call=True,
)
def _add_more_tasks(n, feature_id, _reload):
    if not n or not feature_id:
        return no_update, no_update
    try:
        features = get_all_features()
        feat = next((f for f in features if f["feature_id"] == feature_id), None)
        if not feat:
            return no_update, no_update
        created_info = {
            "feature_id":    feature_id,
            "feature_ref":   feat["feature_ref"],
            "feature_title": feat["title"],
            "assignee_id":   feat.get("assigned_to_id"),
        }
        return created_info, False  # close task panel, open template modal
    except Exception:
        return no_update, no_update
