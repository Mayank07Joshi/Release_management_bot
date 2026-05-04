"""Epics — Platform management page"""

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, callback, ctx, no_update, MATCH
from flask_login import current_user

from db.platform_ops import get_all_epics, get_active_users, create_epic, update_epic, get_all_features

dash.register_page(__name__, path="/epics", name="Epics")


# ── Helpers ───────────────────────────────────────────────────────────────────

DONE_STATES = {"Done"}

def _badge(status):
    color = "#34d399" if status == "Active" else "#64748b"
    return html.Span(status, style={
        "fontSize": "11px", "fontWeight": "600", "padding": "2px 10px",
        "borderRadius": "20px", "background": f"{color}22",
        "color": color, "border": f"1px solid {color}55",
    })


def _state_chip(state):
    colors = {
        "Done":           "#34d399",
        "In Development": "#818cf8",
        "In QA":          "#fb923c",
        "In Planning":    "#60a5fa",
        "In Design":      "#c084fc",
        "On Hold":        "#f87171",
        "Rejected":       "#ef4444",
        "Backlog":        "#64748b",
    }
    c = colors.get(state, "#64748b")
    return html.Span(state, style={
        "fontSize": "10px", "padding": "1px 7px", "borderRadius": "4px",
        "background": f"{c}22", "color": c, "border": f"1px solid {c}44",
        "whiteSpace": "nowrap",
    })


def _progress_bar(done, total):
    pct = int(done / total * 100) if total else 0
    color = "#34d399" if pct == 100 else "#818cf8"
    return html.Div([
        html.Div(style={
            "height": "4px", "background": color,
            "width": f"{pct}%", "borderRadius": "2px",
            "transition": "width 0.3s",
        }),
    ], style={
        "background": "rgba(255,255,255,0.06)", "borderRadius": "2px",
        "height": "4px", "width": "100%", "overflow": "hidden",
    })


def _mini_feature_row(feat):
    rel_label = feat.get("release_ref") or "Unscheduled"
    return html.Div([
        html.Span(feat["feature_ref"], style={
            "fontFamily": "monospace", "fontSize": "11px", "color": "#818cf8",
            "fontWeight": "700", "marginRight": "8px", "minWidth": "52px",
        }),
        _state_chip(feat.get("state", "Backlog")),
        html.Span(feat["title"], style={
            "fontSize": "13px", "color": "#cbd5e1", "marginLeft": "10px", "flex": "1",
        }),
        html.Span(rel_label, style={
            "fontSize": "11px", "color": "#60a5fa", "marginLeft": "8px", "whiteSpace": "nowrap",
        }),
        html.Span(
            feat.get("assignee_name") or "—",
            style={"fontSize": "11px", "color": "#64748b", "marginLeft": "10px", "whiteSpace": "nowrap"},
        ),
    ], style={
        "display": "flex", "alignItems": "center", "padding": "6px 0",
        "borderBottom": "1px solid rgba(255,255,255,0.04)",
    })


def _empty_state():
    return html.Div([
        html.Div("🗂️", style={"fontSize": "40px", "marginBottom": "12px"}),
        html.Div("No epics yet", style={"color": "#e2e8f0", "fontWeight": "600", "fontSize": "15px"}),
        html.Div("Create your first epic to start organising work",
                 style={"color": "#64748b", "fontSize": "13px", "marginTop": "4px"}),
    ], style={"textAlign": "center", "padding": "60px 0", "color": "#64748b"})


def _epic_row(epic, features, can_edit):
    total = len(features)
    done  = sum(1 for f in features if f.get("state") in DONE_STATES)

    tags = [t.strip() for t in (epic.get("tags") or "").split(",") if t.strip()]
    tag_chips = [
        html.Span(t, style={
            "fontSize": "11px", "padding": "2px 8px", "borderRadius": "20px",
            "background": "rgba(129,140,248,0.15)", "color": "#818cf8",
            "border": "1px solid rgba(129,140,248,0.3)", "marginRight": "4px",
        }) for t in tags[:4]
    ]

    feature_list = html.Div([
        html.Div([
            html.Span("Features", style={"fontSize": "12px", "color": "#94a3b8", "fontWeight": "600"}),
            html.Span(f"{done} done / {total} total",
                      style={"fontSize": "12px", "color": "#64748b", "marginLeft": "8px"}),
        ], style={"marginBottom": "8px", "display": "flex", "gap": "4px", "alignItems": "center"}),
        *[_mini_feature_row(f) for f in features],
    ], style={"padding": "12px 0 4px 0"}) if features else html.Div(
        "No features linked to this epic yet.",
        style={"fontSize": "13px", "color": "#64748b", "padding": "12px 0 4px 0"},
    )

    return html.Div([
        # Row 1: ref + status + owner
        html.Div([
            html.Span(epic["epic_ref"], style={
                "fontFamily": "monospace", "fontSize": "12px", "color": "#818cf8",
                "fontWeight": "700", "marginRight": "10px",
            }),
            _badge(epic["status"]),
            html.Div(style={"flex": "1"}),
            html.Span("Owner: ", style={"color": "#64748b", "fontSize": "12px"}),
            html.Span(epic.get("owner_name") or "—", style={"color": "#94a3b8", "fontSize": "12px"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),

        # Row 2: title
        html.Div(epic["title"], style={
            "fontSize": "15px", "fontWeight": "600", "color": "#e2e8f0", "marginBottom": "4px",
        }),

        # Row 3: description
        html.Div(
            (epic.get("description") or "No description provided."),
            style={"fontSize": "13px", "color": "#8892a4", "marginBottom": "10px", "lineHeight": "1.5"},
        ),

        # Progress bar
        _progress_bar(done, total),

        # Row 4: tags + stats + buttons
        html.Div([
            html.Div(tag_chips, style={"display": "flex", "flexWrap": "wrap", "gap": "4px", "flex": "1"}),
            html.Span(
                f"{done}/{total} features done",
                style={"fontSize": "12px", "color": "#64748b", "whiteSpace": "nowrap"},
            ),
            dbc.Button(
                f"Features ({total})",
                id={"type": "epic-toggle-btn", "index": epic["epic_id"]},
                n_clicks=0, size="sm",
                style={
                    "fontSize": "12px", "padding": "4px 12px",
                    "background": "rgba(129,140,248,0.1)", "color": "#818cf8",
                    "border": "1px solid rgba(129,140,248,0.25)", "borderRadius": "6px",
                },
            ),
            dbc.Button("Edit",
                id={"type": "epic-edit-btn", "index": epic["epic_id"]},
                n_clicks=0, size="sm",
                style={
                    "fontSize": "12px", "padding": "4px 14px",
                    "background": "rgba(129,140,248,0.15)", "color": "#818cf8",
                    "border": "1px solid rgba(129,140,248,0.3)", "borderRadius": "6px",
                },
            ) if can_edit else html.Div(),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginTop": "10px"}),

        # Expandable feature list
        dbc.Collapse(
            html.Div(feature_list, style={
                "borderTop": "1px solid rgba(255,255,255,0.06)",
                "marginTop": "12px",
                "paddingTop": "4px",
            }),
            id={"type": "epic-collapse", "index": epic["epic_id"]},
            is_open=False,
        ),

    ], style={
        "background": "rgba(255,255,255,0.02)", "borderRadius": "10px",
        "border": "1px solid rgba(255,255,255,0.06)", "padding": "16px 20px",
        "marginBottom": "10px",
    })


def _owner_options(users):
    return [{"label": u["display_name"], "value": u["user_id"]} for u in users]


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    try:
        users = get_active_users()
    except Exception:
        users = []

    return html.Div([
        dcc.Store(id="epics-reload", data=0),
        dcc.Store(id="epic-editing-id", data=None),

        html.Div([
            html.Div([
                html.H1("Epics", className="page-title"),
                html.P("Product capability areas — long-lived themes that group Features and track strategic goals.",
                       className="page-subtitle"),
            ]),
            dbc.Button(
                [html.Span("+", style={"marginRight": "6px", "fontSize": "16px"}), "New Epic"],
                id="epic-new-btn",
                n_clicks=0,
                style={
                    "background": "linear-gradient(135deg,#6366f1,#818cf8)",
                    "border": "none", "borderRadius": "8px", "color": "white",
                    "fontSize": "13px", "fontWeight": "600", "padding": "8px 18px",
                },
            ),
        ], className="page-header", style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}),

        html.Div([
            dcc.RadioItems(
                id="epics-status-filter",
                options=[
                    {"label": "Active",   "value": "Active"},
                    {"label": "Archived", "value": "Archived"},
                    {"label": "All",      "value": "All"},
                ],
                value="Active",
                inline=True,
                inputStyle={"marginRight": "4px"},
                labelStyle={"marginRight": "20px", "color": "#8892a4", "fontSize": "13px", "cursor": "pointer"},
            ),
        ], style={"marginBottom": "20px"}),

        html.Div(id="epics-list"),

        # ── Modal ──────────────────────────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="epic-modal-title-label"), close_button=True),
            dbc.ModalBody([
                dbc.Label("Title *", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Input(
                    id="epic-modal-title",
                    placeholder="e.g. Customer Portal Overhaul",
                    style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                           "color": "#e2e8f0", "marginBottom": "16px"},
                ),
                dbc.Label("Description", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Textarea(
                    id="epic-modal-desc",
                    placeholder="What does this epic cover?",
                    rows=3,
                    style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                           "color": "#e2e8f0", "resize": "none", "marginBottom": "16px"},
                ),
                dbc.Label("Owner", style={"color": "#94a3b8", "fontSize": "13px"}),
                dcc.Dropdown(
                    id="epic-modal-owner",
                    options=_owner_options(users),
                    placeholder="Select owner...",
                    clearable=True,
                    style={"marginBottom": "16px"},
                    className="dark-dropdown",
                ),
                dbc.Label("Tags", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Input(
                    id="epic-modal-tags",
                    placeholder="Comma-separated: Portal, Mobile, API",
                    style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                           "color": "#e2e8f0", "marginBottom": "16px"},
                ),
                html.Div(id="epic-status-row", children=[
                    dbc.Label("Status", style={"color": "#94a3b8", "fontSize": "13px"}),
                    dcc.RadioItems(
                        id="epic-modal-status",
                        options=[{"label": "Active", "value": "Active"}, {"label": "Archived", "value": "Archived"}],
                        value="Active",
                        inline=True,
                        inputStyle={"marginRight": "4px"},
                        labelStyle={"marginRight": "16px", "color": "#94a3b8", "fontSize": "13px"},
                    ),
                ], style={"display": "none"}),
                html.Div(id="epic-modal-error",
                         style={"color": "#f87171", "fontSize": "13px", "marginTop": "12px"}),
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="epic-modal-cancel", color="secondary", outline=True, size="sm", n_clicks=0),
                dbc.Button("Save", id="epic-modal-save", n_clicks=0, size="sm",
                           style={"background": "linear-gradient(135deg,#6366f1,#818cf8)", "border": "none"}),
            ]),
        ], id="epic-modal", is_open=False, backdrop="static",
           style={"--bs-modal-bg": "#13132b", "--bs-modal-border-color": "rgba(255,255,255,0.1)"}),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("epics-list", "children"),
    Input("epics-status-filter", "value"),
    Input("epics-reload", "data"),
)
def _render_list(status_filter, _reload):
    try:
        epics = get_all_epics()
    except Exception as e:
        return html.Div(f"Error loading epics: {e}", style={"color": "#f87171"})

    can_edit = current_user.is_authenticated and current_user.can("edit_epic")

    if status_filter != "All":
        epics = [e for e in epics if e["status"] == status_filter]

    if not epics:
        return _empty_state()

    try:
        all_features = get_all_features()
    except Exception:
        all_features = []

    features_by_epic = {}
    for f in all_features:
        eid = f.get("epic_id")
        if eid:
            features_by_epic.setdefault(eid, []).append(f)

    return [_epic_row(e, features_by_epic.get(e["epic_id"], []), can_edit) for e in epics]


@callback(
    Output({"type": "epic-collapse", "index": MATCH}, "is_open"),
    Input({"type": "epic-toggle-btn", "index": MATCH}, "n_clicks"),
    State({"type": "epic-collapse", "index": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def _toggle_features(n_clicks, is_open):
    return not is_open


@callback(
    Output("epic-modal", "is_open"),
    Output("epic-modal-title-label", "children"),
    Output("epic-modal-title", "value"),
    Output("epic-modal-desc", "value"),
    Output("epic-modal-owner", "value"),
    Output("epic-modal-tags", "value"),
    Output("epic-modal-status", "value"),
    Output("epic-status-row", "style"),
    Output("epic-editing-id", "data"),
    Output("epic-modal-error", "children"),
    Input("epic-new-btn", "n_clicks"),
    Input({"type": "epic-edit-btn", "index": dash.ALL}, "n_clicks"),
    Input("epic-modal-cancel", "n_clicks"),
    State("epic-modal", "is_open"),
    prevent_initial_call=True,
)
def _toggle_modal(new_clicks, edit_clicks, cancel_clicks, is_open):
    triggered = ctx.triggered_id

    if triggered == "epic-modal-cancel":
        return False, no_update, no_update, no_update, no_update, no_update, no_update, no_update, None, ""

    if triggered == "epic-new-btn" and new_clicks:
        return True, "New Epic", "", "", None, "", "Active", {"display": "none"}, None, ""

    if isinstance(triggered, dict) and triggered.get("type") == "epic-edit-btn":
        epic_id = triggered["index"]
        try:
            epics = get_all_epics()
            epic  = next((e for e in epics if e["epic_id"] == epic_id), None)
            if epic:
                return (
                    True,
                    f"Edit {epic['epic_ref']}",
                    epic["title"],
                    epic.get("description") or "",
                    epic.get("owner_id"),
                    epic.get("tags") or "",
                    epic.get("status", "Active"),
                    {"display": "block"},
                    epic_id,
                    "",
                )
        except Exception as e:
            return True, "Error", "", str(e), None, "", "Active", {"display": "none"}, None, str(e)

    return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update


@callback(
    Output("epic-modal", "is_open", allow_duplicate=True),
    Output("epics-reload", "data"),
    Output("epic-modal-error", "children", allow_duplicate=True),
    Input("epic-modal-save", "n_clicks"),
    State("epic-modal-title", "value"),
    State("epic-modal-desc", "value"),
    State("epic-modal-owner", "value"),
    State("epic-modal-tags", "value"),
    State("epic-modal-status", "value"),
    State("epic-editing-id", "data"),
    State("epics-reload", "data"),
    prevent_initial_call=True,
)
def _save(save_clicks, title, desc, owner_id, tags, status, epic_id, reload_count):
    if not save_clicks:
        return no_update, no_update, no_update

    if not title or not title.strip():
        return no_update, no_update, "Title is required."

    user_id = current_user.id if current_user.is_authenticated else None

    try:
        if epic_id:
            update_epic(epic_id, {
                "title":       title.strip(),
                "description": desc or "",
                "owner_id":    owner_id,
                "tags":        tags or "",
                "status":      status,
            }, updated_by=user_id)
        else:
            create_epic(
                title=title.strip(),
                description=desc or "",
                owner_id=owner_id,
                tags=tags or "",
                created_by=user_id,
            )
    except Exception as e:
        return no_update, no_update, f"Error: {e}"

    return False, (reload_count or 0) + 1, ""
