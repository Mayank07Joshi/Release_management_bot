"""Dash Release Management Analytics Dashboard — Entry Point"""

import dash
import dash_bootstrap_components as dbc
from dash import Dash, dcc, html, Input, Output, State
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

# ── Top nav items ─────────────────────────────────────────────────────────────
NAV_ITEMS = [
    {"label": "Home",            "href": "/",                "icon": "🏠"},
    {"label": "Summary",         "href": "/summary",         "icon": "📊"},
    {"label": "Release Outlook", "href": "/release-outlook", "icon": "🚀"},
    {"label": "Iteration Board", "href": "/iteration",       "icon": "🔄"},
    {"label": "Bugs",            "href": "/bugs",            "icon": "🐛"},
    {"label": "Capacity",        "href": "/capacity",        "icon": "📈"},
    {"label": "QA Health",       "href": "/qa-health",       "icon": "🧪"},
    {"label": "Teams",           "href": "/teams",           "icon": "👥"},
    {"label": "Assistant",       "href": "/assistant",       "icon": "🤖"},
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
            href=item["href"],
            active="exact",
            className="topnav-tab",
        )
        for item in NAV_ITEMS
    ], className="topnav-tabs"),

    # ── Right: avatar placeholder ─────────────────────────────────────────────
    html.Div([
        html.Div("RM", className="topnav-avatar"),
    ], className="topnav-right"),

], className="topnav", id="topnav")

app.layout = html.Div([
    dcc.Location(id="url-location"),
    topnav,
    html.Div(
        dash.page_container,
        className="main-content",
        id="main-content",
    ),
], className="app-wrapper")


if __name__ == "__main__":
    _in_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    _debug_mode        = True

    if not _debug_mode or _in_reloader_child:
        from apscheduler.schedulers.background import BackgroundScheduler
        import atexit
        from sync.ado_sync import run_sync

        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(run_sync, "interval", minutes=15, id="ado_sync",
                          misfire_grace_time=60)
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown(wait=False))

        threading.Thread(target=run_sync, daemon=True, name="ado-sync-startup").start()

    app.run(debug=True, port=8050)
