"""Trends — Addition & Deletion"""
import dash
from pages_dash.focus import focus_tab_content

dash.register_page(__name__, path="/addition-deletion", name="Addition & Deletion")


def layout(**_):
    return focus_tab_content(default_tab="sprint", tabs_visible=False)
