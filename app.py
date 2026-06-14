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

# ── Top nav structure ──────────────────────────────────────────────────────────
_NAV = [
    {"label": "Home",          "href": "/",                  "icon": "🏠"},
    {"label": "Summary",       "href": "/summary",           "icon": "📊"},
    {"label": "Planning Tool", "href": "/planning",          "icon": "📅"},
    {"label": "Leave Manager", "href": "/leave-management",  "icon": "📆"},
    {"label": "Reports",       "href": "/reports",           "icon": "📄"},
]

topnav = html.Div([
    # ── Left: logo + brand ────────────────────────────────────────────────────
    html.A([
        html.Div("RA", className="topnav-logo"),
        html.Div([
            html.Span("Release Analytics", className="topnav-brand-title"),
            html.Span("ADO Dashboard",     className="topnav-brand-sub"),
        ], className="topnav-brand-text"),
    ], href="/", className="topnav-brand"),

    # ── Center: page tabs ─────────────────────────────────────────────────────
    html.Nav([
        dbc.NavLink(
            [html.Span(item["icon"], className="topnav-tab-icon"), item["label"]],
            href=item["href"], active="exact", className="topnav-tab",
        )
        for item in _NAV
    ], className="topnav-tabs"),

    # ── Right: freshness + theme toggle + user avatar + logout ───────────────
    html.Div([
        html.Div(id="data-freshness-display", title="Time since last data sync",
                 style={"fontSize": "11px", "color": "var(--text-secondary, #64748b)",
                        "whiteSpace": "nowrap"}),
        html.Button("☀", id="theme-toggle-btn", className="theme-toggle-btn",
                    title="Toggle light/dark theme", n_clicks=0),
        html.Div(id="topnav-avatar-display"),
    ], className="topnav-right"),

], className="topnav", id="topnav")

# ── Auth setup ────────────────────────────────────────────────────────────────
app.server.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod-!@#$%")
setup_login_manager(app.server)
register_auth_routes(app.server)

app.layout = html.Div([
    dcc.Location(id="url-location"),
    dcc.Store(id="theme-store", storage_type="local", data="dark"),
    topnav,
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

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(run_sync, "interval", minutes=15, id="ado_sync",
                      misfire_grace_time=60)
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
