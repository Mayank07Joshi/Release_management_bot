"""Home — landing page"""

import dash
from dash import html
import dash_bootstrap_components as dbc

dash.register_page(__name__, path="/", name="Home")

CARDS = [
    {
        "icon": "📊",
        "title": "Summary",
        "desc": "VSTS Focus Area — sprint activity, task classification, and data load validation.",
        "href": "/summary",
        "group": None,
    },
    {
        "icon": "📅",
        "title": "Planning Tool",
        "desc": "Story readiness, BA sign-off, capacity matrix, and release pipeline health.",
        "href": "/planning",
        "group": None,
    },
]

CARD_GROUPS = [
    {"label": None, "cards": CARDS},
]


_GROUP_LABEL_STYLE = {
    "fontSize": "11px", "fontWeight": "700", "textTransform": "uppercase",
    "letterSpacing": "1px", "color": "#5a6270", "marginBottom": "12px",
    "marginTop": "8px", "paddingLeft": "4px",
}


def _card(c):
    return dbc.Col(
        html.A(
            [
                html.Div(c["icon"], className="home-card-icon"),
                html.Div(c["title"], className="home-card-title"),
                html.Div(c["desc"], className="home-card-desc"),
            ],
            href=c["href"],
            className="home-card",
        ),
        md=4,
        className="mb-4",
    )


def layout():
    sections = []
    for group in CARD_GROUPS:
        if not group["cards"]:
            continue
        if group["label"]:
            sections.append(html.Div(group["label"], style=_GROUP_LABEL_STYLE))
        sections.append(dbc.Row([_card(c) for c in group["cards"]], className="g-4 mb-2"))

    return html.Div([
        html.Div([
            html.H1("Release Analytics", className="page-title"),
            html.P(
                "Centralised analytics for Release Management — items, capacity, QA health, and team performance.",
                className="page-subtitle",
            ),
        ], className="page-header"),
        *sections,
    ])
