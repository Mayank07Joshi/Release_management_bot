"""Enhancements — Designer Planning"""
import dash
from dash import html

dash.register_page(__name__, path="/designer-planning", name="Designer Planning")

_CARD = "var(--bg-elevated)"
_BD   = "var(--border)"
_MT   = "var(--text-secondary)"
_TXT  = "var(--text-primary)"

def layout(**_):
    return html.Div([
        html.Div("EOD · DESIGN PLANNING", style={
            "fontSize": "10px", "fontWeight": "700", "color": "var(--purple)",
            "letterSpacing": "0.12em", "marginBottom": "10px",
        }),
        html.Div([
            html.Div("Designer Planning", style={
                "fontSize": "30px", "fontWeight": "700", "color": _TXT,
                "display": "inline", "marginRight": "12px",
            }),
            html.Span("PLACEHOLDER", style={
                "fontSize": "11px", "fontWeight": "700", "color": "var(--amber)",
                "background": "rgba(251,146,60,0.13)",
                "border": "1px solid rgba(251,146,60,0.35)",
                "borderRadius": "6px", "padding": "3px 10px",
                "verticalAlign": "middle",
            }),
        ], style={"marginBottom": "6px"}),
        html.Div("Designers start one month before the planned dev month.", style={
            "fontSize": "13px", "color": _MT, "marginBottom": "32px",
        }),
        html.Div([
            html.Div([
                html.Div(style={
                    "width": "8px", "height": "8px", "borderRadius": "50%",
                    "background": "var(--purple)", "marginRight": "8px",
                }),
                html.Span("Not designed yet — placeholder in the structure so the workflow is complete.", style={
                    "fontSize": "13px", "color": _MT,
                }),
                html.Span(" To be built.", style={
                    "fontSize": "13px", "color": "var(--amber)", "fontWeight": "600",
                }),
            ], style={"display": "flex", "alignItems": "center"}),
        ], style={
            "background": _CARD, "border": f"1px solid {_BD}",
            "borderRadius": "12px", "padding": "20px 24px",
        }),
    ], style={"padding": "36px 40px"})
