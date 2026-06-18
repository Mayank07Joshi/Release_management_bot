"""Bugs & Issues — Unestimated Bugs (standalone page)"""
import dash
from dash import dcc, html

dash.register_page(__name__, path="/bugs-unestimated", name="Unestimated Bugs")

# Style constants defined inline — avoids importing planning.py at module level
# (top-level cross-page imports cause Dash to double-register planning.py callbacks)
_TX = "var(--text-primary)"
_MT = "var(--text-secondary)"
_BD = "var(--border)"
_C3 = "var(--bg-base)"
_C2 = "var(--bg-hover)"

_PANEL_CLOSED = {
    "position": "fixed", "top": "0", "right": "0",
    "height": "100vh", "width": "500px",
    "background": _C2,
    "borderLeft": "1px solid rgba(255,255,255,0.10)",
    "zIndex": "1050",
    "display": "flex", "flexDirection": "column",
    "boxShadow": "-16px 0 60px rgba(0,0,0,0.80)",
    "transition": "transform 0.28s cubic-bezier(.4,0,.2,1)",
    "transform": "translateX(110%)",
}
_BACKDROP_CLOSED = {
    "position": "fixed", "top": "0", "left": "0",
    "width": "100vw", "height": "100vh",
    "background": "rgba(0,0,0,0.50)",
    "zIndex": "1049",
    "transition": "opacity 0.28s ease",
    "opacity": "0", "pointerEvents": "none",
}


def layout(**_):
    # Lazy import — planning.py is already in sys.modules when layout() is called
    from pages_dash.planning import _load_unestimated_data, _build_unest_tab

    all_items   = _load_unestimated_data()
    unest_items = [s for s in all_items if s["type"] == "Issue"]

    return html.Div([
        # ── Stores (same IDs as planning.py — only one page in DOM at a time) ──
        dcc.Store(id="plan-unest-store",   data=unest_items),
        dcc.Store(id="unest-panel-filter", data=None),
        dcc.Store(id="unest-active-kcard", data=None),

        # ── Side panel backdrop ────────────────────────────────────────────────
        html.Div(id="unest-backdrop", n_clicks=0, style=_BACKDROP_CLOSED),

        # ── Side panel (slide-in from right) ──────────────────────────────────
        html.Div([
            html.Div([
                html.Div(id="unest-panel-title", style={
                    "fontWeight": "700", "fontSize": "15px", "color": _TX, "flex": "1",
                }),
                html.Button("✕", id="unest-panel-close", n_clicks=0, style={
                    "background": "none", "border": "none", "color": _MT,
                    "fontSize": "20px", "cursor": "pointer", "padding": "2px 8px",
                    "lineHeight": "1", "transition": "color .15s",
                }),
            ], style={
                "display": "flex", "alignItems": "center",
                "padding": "18px 20px 14px",
                "borderBottom": f"1px solid {_BD}",
                "flexShrink": "0",
            }),
            html.Div(id="unest-panel-body", style={
                "overflowY": "auto", "flex": "1", "padding": "16px 20px",
            }),
        ], id="unest-side-panel", style=_PANEL_CLOSED),

        # ── Page header ───────────────────────────────────────────────────────
        html.Div("BUGS & ISSUES · ESTIMATION STATUS", style={
            "fontSize": "10px", "fontWeight": "700", "color": _MT,
            "letterSpacing": "0.12em", "marginBottom": "6px",
        }),
        html.Div([
            html.Div("Estimation Status", style={
                "fontSize": "26px", "fontWeight": "700", "color": _TX,
                "display": "inline", "marginRight": "12px",
            }),
            html.Span("LIVE", style={
                "fontSize": "11px", "fontWeight": "700", "color": "var(--green)",
                "background": "rgba(52,211,153,0.13)",
                "border": "1px solid rgba(52,211,153,0.35)",
                "borderRadius": "6px", "padding": "3px 10px",
                "verticalAlign": "middle",
            }),
        ], style={"marginBottom": "6px"}),
        html.Div(
            "2026 Bugs & Issues missing estimates — click any card or matrix cell for detail.",
            style={"fontSize": "13px", "color": _MT, "marginBottom": "24px"},
        ),

        # ── Main content ──────────────────────────────────────────────────────
        _build_unest_tab(unest_items),

    ], style={
        "padding": "24px 32px",
        "background": _C3,
        "minHeight": "100vh",
        "fontFamily": "Inter, system-ui, sans-serif",
    })
