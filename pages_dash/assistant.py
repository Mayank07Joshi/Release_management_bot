"""ADO Assistant — Chat Interface"""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback
import json
from datetime import datetime

from data.loader import load_data, apply_filters, filter_activity_since
from components.bot.router import bot_answer
from config.settings import ANALYSIS_START_DATE

dash.register_page(__name__, path="/assistant", name="Assistant")

QUICK_PROMPTS = [
    "How many P1 bugs were created this month?",
    "Is the closing balance of bugs increasing over the last 3 months?",
    "Give me a summary for the selected team.",
    "Show me the trend of bugs.",
]


def layout():
    df = load_data()
    teams     = ["All"] + sorted(df["team"].dropna().unique().tolist()) if "team" in df.columns else ["All"]
    employees = ["All"] + sorted(df["assigned_to"].dropna().unique().tolist()) if "assigned_to" in df.columns else ["All"]

    fp = html.Div([
        html.Div("Context Filters", className="chart-title", style={"marginBottom": "12px"}),
        html.Div("Team", className="filter-label"),
        dcc.Dropdown(id="asst-team", options=[{"label": t, "value": t} for t in teams],
                     value="All", clearable=False, style={"fontSize": "12px"}),
        html.Div(style={"height": "10px"}),
        html.Div("Employee", className="filter-label"),
        dcc.Dropdown(id="asst-employee", options=[{"label": e, "value": e} for e in employees],
                     value="All", clearable=False, style={"fontSize": "12px"}),
        html.Div(style={"height": "14px"}),
        html.Hr(),
        html.Div("Quick Prompts", className="filter-label", style={"marginBottom": "8px"}),
        *[
            dbc.Button(p, id=f"qp-{i}", size="sm", color="light",
                       className="mb-2 w-100", style={"textAlign": "left", "fontSize": "11px"})
            for i, p in enumerate(QUICK_PROMPTS)
        ],
    ], className="filter-panel")

    return html.Div([
        html.Div([
            html.H1("🤖 ADO Assistant", className="page-title"),
            html.P("Ask questions about bugs, capacity, QA health, teams, and trends.",
                   className="page-subtitle"),
        ], className="page-header"),

        # Hidden store for chat history (list of {role, content})
        dcc.Store(id="asst-history", data=[]),

        dbc.Row([
            dbc.Col(fp, md=3),
            dbc.Col([
                html.Div(id="asst-chat-history", className="chat-history"),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(id="asst-input", placeholder="Ask me anything about your ADO data…",
                                  type="text", style={"fontSize": "13px"}),
                        width=10,
                    ),
                    dbc.Col(
                        dbc.Button("Send", id="asst-send", color="primary", n_clicks=0),
                        width=2,
                    ),
                ], className="g-2"),
            ], md=9),
        ]),
    ])


@callback(
    Output("asst-history",      "data"),
    Output("asst-chat-history", "children"),
    Output("asst-input",        "value"),
    Input("asst-send",  "n_clicks"),
    Input("qp-0", "n_clicks"), Input("qp-1", "n_clicks"),
    Input("qp-2", "n_clicks"), Input("qp-3", "n_clicks"),
    State("asst-input",   "value"),
    State("asst-history", "data"),
    State("asst-team",     "value"),
    State("asst-employee", "value"),
    prevent_initial_call=True,
)
def handle_chat(send_clicks, qp0, qp1, qp2, qp3, user_text, history, team, employee):
    from dash import ctx

    # Determine the message to send
    triggered = ctx.triggered_id
    if triggered and triggered.startswith("qp-"):
        idx = int(triggered.split("-")[1])
        msg = QUICK_PROMPTS[idx]
    else:
        msg = (user_text or "").strip()

    if not msg:
        raise dash.exceptions.PreventUpdate

    # Load filtered data
    df = load_data()
    df = apply_filters(df, team=team if team != "All" else None,
                       employee=employee if employee != "All" else None)
    df = filter_activity_since(df, ANALYSIS_START_DATE)

    # Get bot answer
    answer = bot_answer(msg, df)

    # Update history
    history = history or []
    history.append({"role": "user",      "content": msg})
    history.append({"role": "assistant", "content": answer})

    # Render chat bubbles
    bubbles = []
    for m in history:
        is_user = m["role"] == "user"
        bubbles.append(
            html.Div([
                html.Div("You" if is_user else "Assistant", className="chat-role"),
                html.Div(m["content"]),
            ], className="chat-msg-user" if is_user else "chat-msg-bot")
        )

    return history, bubbles, ""
