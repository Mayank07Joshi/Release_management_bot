"""Summary — VSTS Focus Area"""

import dash
from pages_dash.trends.focus import focus_tab_content

dash.register_page(__name__, path="/summary", name="Summary")


def layout(**_):
    return focus_tab_content()
