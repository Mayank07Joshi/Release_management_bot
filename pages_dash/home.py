"""Home — landing page"""

import dash
from dash import html
import dash_bootstrap_components as dbc

dash.register_page(__name__, path="/", name="Home")

CARDS = [
    {
        "icon": "📊",
        "title": "Summary Dashboard",
        "desc": "KPIs, bug movement matrix, backlog trend, burn rate by priority.",
        "href": "/summary",
    },
    {
        "icon": "🐛",
        "title": "Bugs Dashboard",
        "desc": "Bug flow matrices, priority breakdown, monthly trend, top functions.",
        "href": "/bugs",
    },
    {
        "icon": "📈",
        "title": "Capacity Planning",
        "desc": "Team utilization, throughput, WIP trend, forecast, estimation accuracy.",
        "href": "/capacity",
    },
    {
        "icon": "🧪",
        "title": "QA Health",
        "desc": "QA throughput, SLA compliance, defect aging, severity heatmap.",
        "href": "/qa-health",
    },
    {
        "icon": "👥",
        "title": "Team Performance",
        "desc": "Per-team bug KPIs, member workload, throughput trends.",
        "href": "/teams",
    },
    {
        "icon": "🤖",
        "title": "ADO Assistant",
        "desc": "Ask questions about your data — metrics, trends, and navigation.",
        "href": "/assistant",
    },
]


def layout():
    return html.Div(
        [
            html.Div(
                [
                    html.H1("🚀 Release Analytics", className="page-title"),
                    html.P(
                        "Centralised analytics for Release Management — bugs, capacity, QA health, and team performance.",
                        className="page-subtitle",
                    ),
                ],
                className="page-header",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        html.A(
                            [
                                html.Div(card["icon"], className="home-card-icon"),
                                html.Div(card["title"], className="home-card-title"),
                                html.Div(card["desc"], className="home-card-desc"),
                            ],
                            href=card["href"],
                            className="home-card",
                        ),
                        md=4,
                        className="mb-4",
                    )
                    for card in CARDS
                ],
                className="g-4",
            ),
        ]
    )
