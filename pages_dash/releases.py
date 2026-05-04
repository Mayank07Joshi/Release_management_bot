"""Releases — Platform management page"""

import json
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, callback, ctx, no_update, MATCH
from flask_login import current_user

from db.platform_ops import get_all_releases, get_active_users, create_release, update_release, get_all_features

dash.register_page(__name__, path="/releases", name="Releases")


# ── Constants ─────────────────────────────────────────────────────────────────

STATUS_COLORS = {
    "Planning":    "#818cf8",
    "In Progress": "#34d399",
    "Released":    "#60a5fa",
    "On Hold":     "#fb923c",
    "Archived":    "#64748b",
}
STATUS_OPTIONS = ["Planning", "In Progress", "Released", "On Hold", "Archived"]

DONE_STATES   = {"Done"}
ACTIVE_STATES = {"In Planning", "In Design", "In Development", "In QA"}

STATE_COLORS = {
    "Done":           "#34d399",
    "In Development": "#818cf8",
    "In QA":          "#fb923c",
    "In Planning":    "#60a5fa",
    "In Design":      "#c084fc",
    "On Hold":        "#f87171",
    "Rejected":       "#ef4444",
    "Backlog":        "#64748b",
}


def _get_iteration_options():
    try:
        from data.loader import load_data
        df = load_data()
        if "iteration_path" not in df.columns:
            return []
        iters = (
            df["iteration_path"]
            .dropna()
            .apply(lambda x: x.split("\\")[-1].strip())
            .unique()
            .tolist()
        )
        iters = sorted([i for i in iters if i and not i.lower().startswith("backlog") and len(i) > 3])
        return [{"label": i, "value": i} for i in iters]
    except Exception:
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status_badge(status):
    color = STATUS_COLORS.get(status, "#64748b")
    return html.Span(status, style={
        "fontSize": "11px", "fontWeight": "600", "padding": "2px 10px",
        "borderRadius": "20px", "background": f"{color}22",
        "color": color, "border": f"1px solid {color}55",
    })


def _state_chip(state):
    c = STATE_COLORS.get(state, "#64748b")
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
        }),
    ], style={
        "background": "rgba(255,255,255,0.06)", "borderRadius": "2px",
        "height": "4px", "width": "100%", "overflow": "hidden",
    })


def _empty_state():
    return html.Div([
        html.Div("🚀", style={"fontSize": "40px", "marginBottom": "12px"}),
        html.Div("No releases yet", style={"color": "#e2e8f0", "fontWeight": "600", "fontSize": "15px"}),
        html.Div("Create a release to start planning delivery",
                 style={"color": "#64748b", "fontSize": "13px", "marginTop": "4px"}),
    ], style={"textAlign": "center", "padding": "60px 0"})


def _iter_chips(iterations_json):
    if not iterations_json:
        return []
    try:
        iters = json.loads(iterations_json) if iterations_json.startswith("[") else [iterations_json]
    except Exception:
        iters = [iterations_json]
    return [
        html.Span(i, style={
            "fontSize": "11px", "padding": "2px 8px", "borderRadius": "20px",
            "background": "rgba(96,165,250,0.12)", "color": "#60a5fa",
            "border": "1px solid rgba(96,165,250,0.25)", "marginRight": "4px",
        }) for i in iters[:5]
    ]


def _mini_feature_row(feat):
    epic_label = feat.get("epic_ref") or "—"
    return html.Div([
        html.Span(feat["feature_ref"], style={
            "fontFamily": "monospace", "fontSize": "11px", "color": "#818cf8",
            "fontWeight": "700", "marginRight": "8px", "minWidth": "52px",
        }),
        _state_chip(feat.get("state", "Backlog")),
        html.Span(feat["title"], style={
            "fontSize": "13px", "color": "#cbd5e1", "marginLeft": "10px", "flex": "1",
        }),
        html.Span(epic_label, style={
            "fontSize": "11px", "color": "#818cf8", "marginLeft": "8px", "whiteSpace": "nowrap",
        }),
        html.Span(
            feat.get("assignee_name") or "—",
            style={"fontSize": "11px", "color": "#64748b", "marginLeft": "10px", "whiteSpace": "nowrap"},
        ),
    ], style={
        "display": "flex", "alignItems": "center", "padding": "6px 0",
        "borderBottom": "1px solid rgba(255,255,255,0.04)",
    })


def _scope_stat(label, value, color="#94a3b8"):
    return html.Div([
        html.Div(str(value), style={"fontSize": "18px", "fontWeight": "700", "color": color}),
        html.Div(label, style={"fontSize": "11px", "color": "#64748b", "marginTop": "1px"}),
    ], style={"textAlign": "center", "minWidth": "50px"})


def _release_row(rel, features, can_edit):
    target = rel.get("target_date")
    target_str = target.strftime("%d %b %Y") if target else "No target date"

    total    = len(features)
    done     = sum(1 for f in features if f.get("state") in DONE_STATES)
    active   = sum(1 for f in features if f.get("state") in ACTIVE_STATES)
    backlog  = total - done - active

    feature_list = html.Div([
        html.Div([
            html.Span("Features in scope", style={"fontSize": "12px", "color": "#94a3b8", "fontWeight": "600"}),
            html.Span(f"{done} done / {total} total",
                      style={"fontSize": "12px", "color": "#64748b", "marginLeft": "8px"}),
        ], style={"marginBottom": "8px", "display": "flex", "alignItems": "center"}),
        *[_mini_feature_row(f) for f in features],
    ], style={"padding": "12px 0 4px 0"}) if features else html.Div(
        "No features assigned to this release yet.",
        style={"fontSize": "13px", "color": "#64748b", "padding": "12px 0 4px 0"},
    )

    return html.Div([
        # Row 1: ref + status + date
        html.Div([
            html.Span(rel["release_ref"], style={
                "fontFamily": "monospace", "fontSize": "12px", "color": "#60a5fa",
                "fontWeight": "700", "marginRight": "10px",
            }),
            _status_badge(rel["status"]),
            html.Span(target_str, style={"fontSize": "12px", "color": "#64748b", "marginLeft": "12px"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),

        # Row 2: title
        html.Div(rel["title"], style={
            "fontSize": "15px", "fontWeight": "600", "color": "#e2e8f0", "marginBottom": "4px",
        }),

        # Row 3: description
        html.Div(
            rel.get("description") or "No description provided.",
            style={"fontSize": "13px", "color": "#8892a4", "marginBottom": "10px", "lineHeight": "1.5"},
        ),

        # Scope stats + progress
        html.Div([
            _scope_stat("Total", total),
            html.Div(style={"width": "1px", "background": "rgba(255,255,255,0.06)", "margin": "0 8px", "height": "30px"}),
            _scope_stat("Done", done, "#34d399"),
            _scope_stat("Active", active, "#818cf8"),
            _scope_stat("Backlog", backlog, "#64748b"),
            html.Div(style={"flex": "1"}),
            html.Div([
                html.Div(
                    f"{int(done/total*100) if total else 0}% complete",
                    style={"fontSize": "11px", "color": "#94a3b8", "marginBottom": "4px", "textAlign": "right"},
                ),
                _progress_bar(done, total),
            ], style={"width": "140px"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px", "marginBottom": "10px"}),

        # Iter chips + owner + buttons
        html.Div([
            html.Div(_iter_chips(rel.get("iterations")),
                     style={"display": "flex", "flexWrap": "wrap", "gap": "4px", "flex": "1"}),
            html.Div([
                html.Span("Owner: ", style={"color": "#64748b", "fontSize": "12px"}),
                html.Span(rel.get("owner_name") or "—", style={"color": "#94a3b8", "fontSize": "12px"}),
            ]),
            dbc.Button(
                f"Scope ({total})",
                id={"type": "rel-toggle-btn", "index": rel["release_id"]},
                n_clicks=0, size="sm",
                style={
                    "fontSize": "12px", "padding": "4px 12px",
                    "background": "rgba(96,165,250,0.1)", "color": "#60a5fa",
                    "border": "1px solid rgba(96,165,250,0.25)", "borderRadius": "6px",
                },
            ),
            dbc.Button("Edit",
                id={"type": "rel-edit-btn", "index": rel["release_id"]},
                n_clicks=0, size="sm",
                style={
                    "fontSize": "12px", "padding": "4px 14px",
                    "background": "rgba(96,165,250,0.12)", "color": "#60a5fa",
                    "border": "1px solid rgba(96,165,250,0.25)", "borderRadius": "6px",
                },
            ) if can_edit else html.Div(),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px"}),

        # Expandable scope list
        dbc.Collapse(
            html.Div(feature_list, style={
                "borderTop": "1px solid rgba(255,255,255,0.06)",
                "marginTop": "12px", "paddingTop": "4px",
            }),
            id={"type": "rel-collapse", "index": rel["release_id"]},
            is_open=False,
        ),

    ], style={
        "background": "rgba(255,255,255,0.02)", "borderRadius": "10px",
        "border": "1px solid rgba(255,255,255,0.06)", "padding": "16px 20px",
        "marginBottom": "10px",
    })


# ── Layout ────────────────────────────────────────────────────────────────────

def layout():
    try:
        users = get_active_users()
    except Exception:
        users = []

    try:
        iter_opts = _get_iteration_options()
    except Exception:
        iter_opts = []

    return html.Div([
        dcc.Store(id="releases-reload", data=0),
        dcc.Store(id="rel-editing-id", data=None),

        html.Div([
            html.Div([
                html.H1("Releases", className="page-title"),
                html.P("Time-boxed deliveries — plan iterations, set targets, track progress.",
                       className="page-subtitle"),
            ]),
            dbc.Button(
                [html.Span("+", style={"marginRight": "6px", "fontSize": "16px"}), "New Release"],
                id="rel-new-btn",
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
                id="rel-status-filter",
                options=[
                    {"label": "Active", "value": "active"},
                    {"label": "All",    "value": "all"},
                ],
                value="active",
                inline=True,
                inputStyle={"marginRight": "4px"},
                labelStyle={"marginRight": "20px", "color": "#8892a4", "fontSize": "13px", "cursor": "pointer"},
            ),
        ], style={"marginBottom": "20px"}),

        html.Div(id="releases-list"),

        # ── Modal ──────────────────────────────────────────────────────────
        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle(id="rel-modal-title-label"), close_button=True),
            dbc.ModalBody([
                dbc.Label("Title *", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Input(
                    id="rel-modal-title",
                    placeholder="e.g. v2.4 — April 2026 Release",
                    style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                           "color": "#e2e8f0", "marginBottom": "16px"},
                ),
                dbc.Label("Description", style={"color": "#94a3b8", "fontSize": "13px"}),
                dbc.Textarea(
                    id="rel-modal-desc",
                    placeholder="What's planned for this release?",
                    rows=3,
                    style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                           "color": "#e2e8f0", "resize": "none", "marginBottom": "16px"},
                ),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Target Date", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dbc.Input(
                            id="rel-modal-date",
                            type="date",
                            style={"background": "#1e1e38", "border": "1px solid rgba(255,255,255,0.1)",
                                   "color": "#e2e8f0", "colorScheme": "dark"},
                        ),
                    ], width=6),
                    dbc.Col([
                        dbc.Label("Owner", style={"color": "#94a3b8", "fontSize": "13px"}),
                        dcc.Dropdown(
                            id="rel-modal-owner",
                            options=[{"label": u["display_name"], "value": u["user_id"]} for u in users],
                            placeholder="Select owner...",
                            clearable=True,
                            className="dark-dropdown",
                        ),
                    ], width=6),
                ], className="mb-3"),
                dbc.Label("Iterations", style={"color": "#94a3b8", "fontSize": "13px"}),
                dcc.Dropdown(
                    id="rel-modal-iterations",
                    options=iter_opts,
                    placeholder="Select iterations included in this release...",
                    multi=True,
                    clearable=True,
                    className="dark-dropdown",
                    style={"marginBottom": "16px"},
                ),
                html.Div(id="rel-status-row", children=[
                    dbc.Label("Status", style={"color": "#94a3b8", "fontSize": "13px"}),
                    dcc.Dropdown(
                        id="rel-modal-status",
                        options=[{"label": s, "value": s} for s in STATUS_OPTIONS],
                        value="Planning",
                        clearable=False,
                        className="dark-dropdown",
                    ),
                ], style={"display": "none"}),
                html.Div(id="rel-modal-error",
                         style={"color": "#f87171", "fontSize": "13px", "marginTop": "12px"}),
            ]),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="rel-modal-cancel", color="secondary", outline=True, size="sm", n_clicks=0),
                dbc.Button("Save", id="rel-modal-save", n_clicks=0, size="sm",
                           style={"background": "linear-gradient(135deg,#6366f1,#818cf8)", "border": "none"}),
            ]),
        ], id="rel-modal", is_open=False, backdrop="static",
           style={"--bs-modal-bg": "#13132b", "--bs-modal-border-color": "rgba(255,255,255,0.1)"}),
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("releases-list", "children"),
    Input("rel-status-filter", "value"),
    Input("releases-reload", "data"),
)
def _render_list(status_filter, _reload):
    try:
        include_archived = (status_filter == "all")
        releases = get_all_releases(include_archived=include_archived)
    except Exception as e:
        return html.Div(f"Error loading releases: {e}", style={"color": "#f87171"})

    can_edit = current_user.is_authenticated and current_user.can("edit_release")

    if not releases:
        return _empty_state()

    try:
        all_features = get_all_features()
    except Exception:
        all_features = []

    features_by_release = {}
    for f in all_features:
        rid = f.get("planned_release_id")
        if rid:
            features_by_release.setdefault(rid, []).append(f)

    return [_release_row(r, features_by_release.get(r["release_id"], []), can_edit) for r in releases]


@callback(
    Output({"type": "rel-collapse", "index": MATCH}, "is_open"),
    Input({"type": "rel-toggle-btn", "index": MATCH}, "n_clicks"),
    State({"type": "rel-collapse", "index": MATCH}, "is_open"),
    prevent_initial_call=True,
)
def _toggle_scope(n_clicks, is_open):
    return not is_open


@callback(
    Output("rel-modal", "is_open"),
    Output("rel-modal-title-label", "children"),
    Output("rel-modal-title", "value"),
    Output("rel-modal-desc", "value"),
    Output("rel-modal-date", "value"),
    Output("rel-modal-owner", "value"),
    Output("rel-modal-iterations", "value"),
    Output("rel-modal-status", "value"),
    Output("rel-status-row", "style"),
    Output("rel-editing-id", "data"),
    Output("rel-modal-error", "children"),
    Input("rel-new-btn", "n_clicks"),
    Input({"type": "rel-edit-btn", "index": dash.ALL}, "n_clicks"),
    Input("rel-modal-cancel", "n_clicks"),
    State("rel-modal", "is_open"),
    prevent_initial_call=True,
)
def _toggle_modal(new_clicks, edit_clicks, cancel_clicks, is_open):
    triggered = ctx.triggered_id

    if triggered == "rel-modal-cancel":
        return False, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, None, ""

    if triggered == "rel-new-btn" and new_clicks:
        return True, "New Release", "", "", None, None, [], "Planning", {"display": "none"}, None, ""

    if isinstance(triggered, dict) and triggered.get("type") == "rel-edit-btn":
        rel_id = triggered["index"]
        try:
            releases = get_all_releases(include_archived=True)
            rel = next((r for r in releases if r["release_id"] == rel_id), None)
            if rel:
                iters = []
                if rel.get("iterations"):
                    try:
                        iters = json.loads(rel["iterations"]) if rel["iterations"].startswith("[") else [rel["iterations"]]
                    except Exception:
                        iters = []
                target = str(rel["target_date"]) if rel.get("target_date") else None
                return (
                    True,
                    f"Edit {rel['release_ref']}",
                    rel["title"],
                    rel.get("description") or "",
                    target,
                    rel.get("owner_id"),
                    iters,
                    rel.get("status", "Planning"),
                    {"display": "block"},
                    rel_id,
                    "",
                )
        except Exception as e:
            return True, "Error", "", "", None, None, [], "Planning", {"display": "none"}, None, str(e)

    return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update


@callback(
    Output("rel-modal", "is_open", allow_duplicate=True),
    Output("releases-reload", "data"),
    Output("rel-modal-error", "children", allow_duplicate=True),
    Input("rel-modal-save", "n_clicks"),
    State("rel-modal-title", "value"),
    State("rel-modal-desc", "value"),
    State("rel-modal-date", "value"),
    State("rel-modal-owner", "value"),
    State("rel-modal-iterations", "value"),
    State("rel-modal-status", "value"),
    State("rel-editing-id", "data"),
    State("releases-reload", "data"),
    prevent_initial_call=True,
)
def _save(save_clicks, title, desc, target_date, owner_id, iterations, status, rel_id, reload_count):
    if not save_clicks:
        return no_update, no_update, no_update

    if not title or not title.strip():
        return no_update, no_update, "Title is required."

    user_id = current_user.id if current_user.is_authenticated else None
    iters_json = json.dumps(iterations) if iterations else None

    try:
        if rel_id:
            update_release(rel_id, {
                "title":       title.strip(),
                "description": desc or "",
                "target_date": target_date or None,
                "owner_id":    owner_id,
                "iterations":  iters_json,
                "status":      status,
            }, updated_by=user_id)
        else:
            create_release(
                title=title.strip(),
                description=desc or "",
                target_date=target_date or None,
                owner_id=owner_id,
                iterations=iters_json,
                created_by=user_id,
            )
    except Exception as e:
        return no_update, no_update, f"Error: {e}"

    return False, (reload_count or 0) + 1, ""
