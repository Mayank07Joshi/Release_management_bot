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
NAV_LEFT = [
    {"label": "Home",    "href": "/",        "icon": "🏠"},
    {"label": "Summary", "href": "/summary", "icon": "📊"},
]
NAV_PLANNING = [
    {"label": "Planning Tool",   "href": "/planning",        "icon": "📅"},
    {"label": "Capacity",        "href": "/capacity",        "icon": "📈"},
    {"label": "Release Outlook", "href": "/release-outlook", "icon": "🚀"},
]
NAV_RIGHT = [
    {"label": "Items",     "href": "/items",     "icon": "📋"},
    {"label": "Teams",     "href": "/teams",     "icon": "👥"},
    {"label": "Assistant", "href": "/assistant", "icon": "🤖"},
]
NAV_PLATFORM = [
    {"label": "Epics",       "href": "/epics",        "icon": "🗂️"},
    {"label": "Releases",    "href": "/releases",     "icon": "🚢"},
    {"label": "Features",    "href": "/features",     "icon": "📋"},
    {"label": "Bug Tracker", "href": "/bug-tracker",  "icon": "🐛"},
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
        *[
            dbc.NavLink(
                [html.Span(item["icon"], className="topnav-tab-icon"), item["label"]],
                href=item["href"], active="exact", className="topnav-tab",
            )
            for item in NAV_LEFT
        ],
        html.Details([
            html.Summary(
                [html.Span("📅", className="topnav-tab-icon"), " Planning ",
                 html.Span("▾", className="topnav-planning-arrow")],
                className="topnav-tab topnav-planning-toggle",
                id="planning-nav-btn",
            ),
            html.Div([
                html.A(
                    [html.Span(item["icon"], style={"marginRight": "8px"}), item["label"]],
                    href=item["href"],
                    className="topnav-dropdown-item",
                )
                for item in NAV_PLANNING
            ], className="topnav-planning-menu"),
        ], className="topnav-planning-wrapper"),
        *[
            dbc.NavLink(
                [html.Span(item["icon"], className="topnav-tab-icon"), item["label"]],
                href=item["href"], active="exact", className="topnav-tab",
            )
            for item in NAV_RIGHT
        ],
        html.Details([
            html.Summary(
                [html.Span("🏗️", className="topnav-tab-icon"), " Platform ",
                 html.Span("▾", className="topnav-planning-arrow")],
                className="topnav-tab topnav-planning-toggle",
                id="platform-nav-btn",
            ),
            html.Div([
                html.A(
                    [html.Span(item["icon"], style={"marginRight": "8px"}), item["label"]],
                    href=item["href"],
                    className="topnav-dropdown-item",
                )
                for item in NAV_PLATFORM
            ], className="topnav-planning-menu"),
        ], className="topnav-planning-wrapper"),
    ], className="topnav-tabs"),

    # ── Right: user avatar + logout ───────────────────────────────────────────
    html.Div([
        html.Div(id="topnav-avatar-display"),
    ], className="topnav-right"),

], className="topnav", id="topnav")

# ── Auth setup ────────────────────────────────────────────────────────────────
app.server.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod-!@#$%")
setup_login_manager(app.server)
register_auth_routes(app.server)

app.layout = html.Div([
    dcc.Location(id="url-location"),
    topnav,
    html.Div(
        dash.page_container,
        className="main-content",
        id="main-content",
    ),
    # ── ADO write-back failure toasts ─────────────────────────────────────────
    dcc.Interval(id="ado-failure-poll", interval=5000, n_intervals=0),
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
    from sync.ado_write import get_pending_failures
    failures = get_pending_failures()
    if not failures:
        return []
    cards = []
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


_PLANNING_PATHS = {"/planning", "/capacity", "/dev-capacity", "/release-outlook", "/focus"}
_PLATFORM_PATHS = {"/epics", "/releases", "/features", "/bug-tracker"}

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

@app.callback(
    Output("planning-nav-btn", "className"),
    Input("url-location", "pathname"),
)
def _planning_active(pathname):
    base = "topnav-tab topnav-planning-toggle"
    return base + " active" if pathname in _PLANNING_PATHS else base

@app.callback(
    Output("platform-nav-btn", "className"),
    Input("url-location", "pathname"),
)
def _platform_active(pathname):
    base = "topnav-tab topnav-planning-toggle"
    return base + " active" if pathname in _PLATFORM_PATHS else base


if __name__ == "__main__":
    _in_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    _debug_mode        = True

    if not _debug_mode or _in_reloader_child:
        from apscheduler.schedulers.background import BackgroundScheduler
        import atexit
        from sync.ado_sync import run_sync
        from db.planning import init_planning_tables

        # Ensure planning sign-off tables exist
        try:
            init_planning_tables()
        except Exception as _e:
            logging.getLogger(__name__).warning("Planning table init failed: %s", _e)

        # Ensure sprint iteration history table exists
        try:
            from db.focus import init_sprint_history_table
            init_sprint_history_table()
        except Exception as _e:
            logging.getLogger(__name__).warning("Sprint history table init failed: %s", _e)

        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(run_sync, "interval", minutes=15, id="ado_sync",
                          misfire_grace_time=60)
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))

        threading.Thread(target=run_sync, daemon=True, name="ado-sync-startup").start()

    app.run(host="0.0.0.0", port=8050, debug=False)
