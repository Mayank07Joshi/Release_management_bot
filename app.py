"""Dash Release Management Analytics Dashboard — Entry Point"""

import dash
import dash_bootstrap_components as dbc
from dash import Dash, dcc, html, Input, Output, State, callback
import sys, os, logging, threading
import plotly.graph_objects as go
import plotly.io as pio

# Make project root importable
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ── Global Plotly dark template ───────────────────────────────────────────────
pio.templates["midnight"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color="#8892a4", size=12),
        colorway=["#818cf8", "#34d399", "#fb923c", "#f87171",
                  "#a78bfa", "#60a5fa", "#fbbf24", "#e879f9"],
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.05)",
            linecolor="rgba(255,255,255,0)",
            zerolinecolor="rgba(255,255,255,0.07)",
            tickfont=dict(color="#8892a4"),
            title_font=dict(color="#8892a4"),
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.05)",
            linecolor="rgba(255,255,255,0)",
            zerolinecolor="rgba(255,255,255,0.07)",
            tickfont=dict(color="#8892a4"),
            title_font=dict(color="#8892a4"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8892a4"),
        ),
        hoverlabel=dict(
            bgcolor="#151524",
            bordercolor="rgba(255,255,255,0.10)",
            font=dict(color="#e2e8f0", family="Inter, sans-serif"),
        ),
        title_font=dict(color="#e2e8f0", size=14, family="Inter, sans-serif"),
    )
)
pio.templates.default = "midnight"

from auth.manager import setup_login_manager
from auth.routes import register_auth_routes

app = Dash(
    __name__,
    use_pages=True,
    pages_folder="pages_dash",
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
    ],
    suppress_callback_exceptions=True,
    title="Release Analytics",
)

# ── Sidebar nav tree ───────────────────────────────────────────────────────────
# (section_label, section_dot_color, [(label, href, icon_char, is_built)])
_NAV_TREE = [
    (None, None, [
        ("Overview", "/overview", "▦", True),
    ]),
    ("TRENDS", "#34d399", [
        ("Addition & Deletion", "/addition-deletion", "◉", True),
    ]),
    ("ENHANCEMENTS", "#818cf8", [
        ("Unestimated Items",  "/unestimated",       "⊙", True),
        ("Story Readiness",    "/planning",           "✓", True),
        ("Designer Planning",  "/designer-planning",  "∖", False),
        ("Release Status",     "/release-status",     "▶", False),
    ]),
    ("BUGS & ISSUES", "#f87171", [
        ("Unestimated Bugs", "/bugs-unestimated", "⊙", True),
        ("Issue Planning",   "/issue-planning",   "≡", True),
    ]),
    ("CAPACITY", "#60a5fa", [
        ("Developer Capacity", "/dev-capacity", "≡", True),
        ("Admin Hours",        "/admin-hours",  "⊙", False),
    ]),
    ("REFERENCE", "#8892a4", [
        ("VSTS Focus Area", "/summary",  "◇", True),
        ("BA Team Brief",   "/ba-brief", "□", False),
    ]),
]


def _build_sidebar_nav(pathname):
    items = []
    for (section_label, dot_color, nav_items) in _NAV_TREE:
        if section_label:
            items.append(html.Div([
                html.Span(style={
                    "width": "6px", "height": "6px", "borderRadius": "2px",
                    "background": dot_color, "display": "inline-block",
                    "marginRight": "7px", "flexShrink": "0",
                }),
                html.Span(section_label, style={
                    "fontSize": "9.5px", "fontWeight": "700",
                    "color": "rgb(91,98,118)",
                    "textTransform": "uppercase", "letterSpacing": "0.7px",
                }),
            ], style={
                "display": "flex", "alignItems": "center",
                "padding": "0px 8px 6px", "marginTop": "12px",
            }))

        for (label, href, icon, built) in nav_items:
            is_active = (pathname or "/") == href
            trailing = []
            if not built:
                trailing = [html.Span(title="Placeholder", style={
                    "width": "6px", "height": "6px", "borderRadius": "50%",
                    "background": "rgb(224,162,60)", "opacity": "0.8",
                    "flexShrink": "0", "marginLeft": "auto",
                })]
            items.append(html.A([
                html.Span(icon, style={
                    "width": "18px", "textAlign": "center",
                    "color": "rgb(110,118,241)" if is_active else "rgb(139,146,164)",
                    "fontSize": "13px", "flexShrink": "0",
                }),
                html.Span(label, style={
                    "flex": "1", "fontSize": "12.5px",
                    "fontWeight": "700" if is_active else "500",
                    "color": "rgb(234,236,242)" if is_active else "rgb(139,146,164)",
                    "overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap",
                }),
                *trailing,
            ], href=href, style={
                "width": "100%", "display": "flex", "alignItems": "center", "gap": "10px",
                "padding": "8px 9px", "borderRadius": "8px", "cursor": "pointer",
                "textDecoration": "none", "marginBottom": "2px",
                "background": "rgba(110,118,241,0.11)" if is_active else "transparent",
                "border": "1px solid rgba(110,118,241,0.4)" if is_active else "1px solid transparent",
            }))

    # Bottom legend
    items.append(html.Div([
        html.Span(style={
            "display": "inline-block", "width": "6px", "height": "6px",
            "borderRadius": "50%", "background": "rgb(224,162,60)",
            "marginRight": "5px",
        }),
        "Amber dot = screen still a placeholder",
    ], style={
        "marginTop": "auto", "padding": "10px 8px 0px",
        "fontSize": "10px", "color": "rgb(91,98,118)",
        "lineHeight": "1.5", "borderTop": "1px solid rgb(30,36,51)",
    }))

    return items


sidebar = html.Div([
    # ── Branding ───────────────────────────────────────────────────────────────
    html.Div([
        html.Div("EOD · PLANNING", style={
            "fontSize": "11px", "fontWeight": "700",
            "color": "rgb(110,118,241)", "letterSpacing": "1.2px",
        }),
        html.Div("Product workspace", style={
            "fontSize": "12.5px", "color": "rgb(139,146,164)", "marginTop": "3px",
        }),
    ], style={"padding": "0px 8px 14px", "flexShrink": "0"}),

    # ── Nav (updated by callback on every URL change) ──────────────────────────
    html.Div(id="sidebar-nav", style={
        "flex": "1", "overflowY": "auto", "overflowX": "hidden",
        "display": "flex", "flexDirection": "column", "gap": "4px",
    }),

    # ── Bottom: freshness + theme + user ───────────────────────────────────────
    html.Div([
        html.Div(id="data-freshness-display", style={
            "fontSize": "10px", "color": "rgb(91,98,118)",
            "marginBottom": "10px", "whiteSpace": "nowrap",
        }),
        html.Div([
            html.Div(id="topnav-avatar-display", style={"flex": "1", "minWidth": "0"}),
            html.Button("☀", id="theme-toggle-btn", className="theme-toggle-btn",
                        title="Toggle light/dark theme", n_clicks=0, style={
                            "background": "transparent",
                            "border": "1px solid rgba(255,255,255,0.08)",
                            "color": "rgb(139,146,164)", "cursor": "pointer",
                            "fontSize": "13px", "padding": "4px 7px",
                            "borderRadius": "6px",
                        }),
        ], style={"display": "flex", "alignItems": "center",
                  "justifyContent": "space-between", "gap": "8px"}),
    ], style={
        "padding": "12px 8px",
        "borderTop": "1px solid rgb(30,36,51)",
        "flexShrink": "0",
    }),
], id="sidebar", style={
    "width": "232px", "minWidth": "232px",
    "background": "rgb(18,22,31)",
    "height": "100vh",
    "position": "fixed", "left": "0", "top": "0",
    "display": "flex", "flexDirection": "column",
    "borderRight": "1px solid rgb(38,44,58)",
    "padding": "18px 12px",
    "boxSizing": "border-box",
    "zIndex": "100",
    "overflowY": "auto",
})

# ── Auth setup ────────────────────────────────────────────────────────────────
app.server.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod-!@#$%")
setup_login_manager(app.server)
register_auth_routes(app.server)

app.layout = html.Div([
    dcc.Location(id="url-location"),
    dcc.Store(id="theme-store", storage_type="local", data="dark"),
    sidebar,
    html.Div(
        dash.page_container,
        className="main-content",
        id="main-content",
    ),
    # ── ADO write-back failure/success toasts + data freshness ───────────────
    dcc.Interval(id="ado-failure-poll", interval=5000, n_intervals=0),
    dcc.Interval(id="data-freshness-poll", interval=30000, n_intervals=0),
    html.Div(id="ado-failure-toast-container", style={
        "position": "fixed", "bottom": "24px", "right": "24px",
        "zIndex": 9999, "display": "flex", "flexDirection": "column", "gap": "10px",
        "maxWidth": "380px",
    }),
], className="app-wrapper")


@app.callback(
    Output("sidebar-nav", "children"),
    Input("url-location", "pathname"),
)
def _update_sidebar_nav(pathname):
    return _build_sidebar_nav(pathname)


@app.callback(
    Output("ado-failure-toast-container", "children"),
    Input("ado-failure-poll", "n_intervals"),
)
def _ado_failure_toast(n):
    from sync.ado_write import get_pending_failures, get_pending_successes
    failures = get_pending_failures()
    successes = get_pending_successes()
    if not failures and not successes:
        return []
    cards = []
    for s in successes:
        label = ", ".join(s["fields"][:3]) + ("…" if len(s["fields"]) > 3 else "")
        cards.append(html.Div([
            html.Div([
                html.Span("✓ ADO synced", style={
                    "fontWeight": "600", "fontSize": "13px", "color": "#34d399",
                }),
                html.Span(s["time"], style={"fontSize": "11px", "color": "#64748b", "marginLeft": "8px"}),
            ], style={"marginBottom": "4px"}),
            html.Div(f"Work item #{s['ado_id']} — {label}", style={
                "fontSize": "12px", "color": "#94a3b8",
            }),
        ], style={
            "background": "#0f2a1f", "border": "1px solid rgba(52,211,153,0.3)",
            "borderRadius": "10px", "padding": "12px 16px",
            "boxShadow": "0 4px 20px rgba(0,0,0,0.4)",
        }))
    for f in failures:
        cards.append(html.Div([
            html.Div([
                html.Span("⚠ ADO sync failed", style={
                    "fontWeight": "600", "fontSize": "13px", "color": "#f87171",
                }),
                html.Span(f["time"], style={"fontSize": "11px", "color": "#64748b", "marginLeft": "8px"}),
            ], style={"marginBottom": "4px"}),
            html.Div(f"Work item #{f['ado_id']} — {f['message'][:120]}", style={
                "fontSize": "12px", "color": "#94a3b8",
            }),
        ], style={
            "background": "#1e1e38", "border": "1px solid rgba(248,113,113,0.3)",
            "borderRadius": "10px", "padding": "12px 16px",
            "boxShadow": "0 4px 20px rgba(0,0,0,0.4)",
        }))
    return cards


@app.callback(
    Output("data-freshness-display", "children"),
    Input("data-freshness-poll", "n_intervals"),
    Input("url-location", "pathname"),
)
def _data_freshness(n, _path):
    from data.loader import get_last_load_time
    import time as _time
    t = get_last_load_time()
    if not t:
        return "data: loading…"
    age = int(_time.time() - t)
    if age < 60:
        label = f"{age}s ago"
    elif age < 3600:
        label = f"{age // 60}m ago"
    else:
        label = f"{age // 3600}h ago"
    return f"↻ {label}"


app.clientside_callback(
    """
    function(theme) {
        var t = theme || 'dark';
        document.documentElement.setAttribute('data-theme', t);
        return t === 'dark' ? '🌙' : '☀️';
    }
    """,
    Output("theme-toggle-btn", "children"),
    Input("theme-store", "data"),
)

@app.callback(
    Output("theme-store", "data", allow_duplicate=True),
    Input("theme-toggle-btn", "n_clicks"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def _toggle_theme(n, current):
    return "light" if (current or "dark") == "dark" else "dark"

@app.callback(
    Output("topnav-avatar-display", "children"),
    Input("url-location", "pathname"),
)
def _update_avatar(pathname):
    from flask_login import current_user
    if current_user and current_user.is_authenticated:
        initials = "".join(p[0].upper() for p in current_user.display_name.split()[:2])
        return html.Div([
            html.Div(initials, className="topnav-avatar", title=current_user.display_name),
            html.A("Logout", href="/logout", className="topnav-logout"),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px"})
    return html.A("Login", href="/login", className="topnav-logout")


if __name__ == "__main__":
    from apscheduler.schedulers.background import BackgroundScheduler
    from waitress import serve
    import atexit
    from sync.ado_sync import run_sync
    from db.planning import init_planning_tables

    try:
        init_planning_tables()
    except Exception as _e:
        logging.getLogger(__name__).warning("Planning table init failed: %s", _e)

    try:
        from db.standalone import init_standalone_table
        init_standalone_table()
    except Exception as _e:
        logging.getLogger(__name__).warning("Standalone table init failed: %s", _e)

    try:
        from db.focus import init_sprint_history_table
        init_sprint_history_table()
    except Exception as _e:
        logging.getLogger(__name__).warning("Sprint history table init failed: %s", _e)

    try:
        from db.leaves import init_leave_tables
        init_leave_tables()
    except Exception as _e:
        logging.getLogger(__name__).warning("Leave table init failed: %s", _e)

    try:
        from db.report_requests import init_table as _init_rq
        _init_rq()
    except Exception as _e:
        logging.getLogger(__name__).warning("Report requests table init failed: %s", _e)

    try:
        from db.aggregations import init_aggregation_tables
        init_aggregation_tables()
    except Exception as _e:
        logging.getLogger(__name__).warning("Aggregation table init failed: %s", _e)

    try:
        from db.issue_planning import init_issue_planning_tables
        init_issue_planning_tables()
    except Exception as _e:
        logging.getLogger(__name__).warning("Issue planning table init failed: %s", _e)

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(run_sync, "interval", minutes=15, id="ado_sync",
                      misfire_grace_time=60)
    scheduler.add_job(
        lambda: run_sync(full=True),
        "cron", hour=0, minute=0, id="ado_sync_full",
        misfire_grace_time=300,
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))

    threading.Thread(target=run_sync, daemon=True, name="ado-sync-startup").start()

    from data.loader import load_data as _load_data
    threading.Thread(target=_load_data, daemon=True, name="cache-warmup").start()

    if os.environ.get("PRODUCTION", "false").lower() == "true":
        logging.getLogger(__name__).info("Starting Waitress on http://0.0.0.0:8050")
        serve(app.server, host="0.0.0.0", port=8050, threads=8)
    else:
        app.run(host="0.0.0.0", port=8050, debug=True)
