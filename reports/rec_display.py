"""
reports/rec_display.py
Renders recommendation lists as Dash HTML components.

Design intent:
- Compact pill cards in a horizontal wrap strip
- Critical = red, Warning = amber, Positive = green
- Icon prefix only, no heavy borders or big banners
- Sits just below the page header / filter bar — contextual, not intrusive
- Clicking a pill expands an inline tooltip via title= attribute (no modal)
"""

from dash import html


# ── Palette ───────────────────────────────────────────────────────────────────
_STYLES = {
    "critical": {
        "bg":     "rgba(248,113,113,0.12)",
        "border": "rgba(248,113,113,0.35)",
        "color":  "#f87171",
        "icon":   "🔴",
    },
    "warning": {
        "bg":     "rgba(251,191,36,0.10)",
        "border": "rgba(251,191,36,0.35)",
        "color":  "#fbbf24",
        "icon":   "⚠️",
    },
    "positive": {
        "bg":     "rgba(52,211,153,0.10)",
        "border": "rgba(52,211,153,0.30)",
        "color":  "#34d399",
        "icon":   "✅",
    },
}

_STRIP_STYLE = {
    "display":        "flex",
    "flexWrap":       "wrap",
    "gap":            "8px",
    "marginBottom":   "20px",
    "alignItems":     "center",
}

_LABEL_STYLE = {
    "fontSize":      "11px",
    "fontWeight":    "600",
    "letterSpacing": "0.6px",
    "textTransform": "uppercase",
    "color":         "#64748b",
    "marginRight":   "4px",
    "whiteSpace":    "nowrap",
    "alignSelf":     "center",
}


def rec_pill(rec: dict) -> html.Div:
    """Single pill card for one recommendation."""
    s = _STYLES.get(rec["type"], _STYLES["warning"])
    board_tag = f"[{rec['board']}]  " if "board" in rec else ""
    return html.Div(
        [
            html.Span(s["icon"], style={"marginRight": "5px", "fontSize": "12px"}),
            html.Span(rec["title"], style={"fontWeight": "600", "fontSize": "12px"}),
        ],
        title=f"{board_tag}{rec['message']}",   # native tooltip on hover
        style={
            "display":       "inline-flex",
            "alignItems":    "center",
            "background":    s["bg"],
            "border":        f"1px solid {s['border']}",
            "borderRadius":  "20px",
            "padding":       "5px 12px",
            "color":         s["color"],
            "cursor":        "default",
            "whiteSpace":    "nowrap",
            "userSelect":    "none",
            "lineHeight":    "1.3",
        },
    )


def rec_strip(recs: list, label: str = "Insights") -> html.Div:
    """
    Full horizontal strip of recommendation pills.
    Returns an empty Div (zero height) when there are no recommendations.
    """
    if not recs:
        return html.Div()

    pills = [
        html.Span(label, style=_LABEL_STYLE),
    ] + [rec_pill(r) for r in recs]

    return html.Div(pills, style=_STRIP_STYLE)


def rec_strip_for_page(df, fn, **kwargs) -> html.Div:
    """
    Convenience wrapper — calls the recommendation function and renders the strip.
    fn: one of the get_recommendations_* functions from recommendations.py
    kwargs: extra args passed to fn (e.g. hours_day for capacity)
    """
    try:
        recs = fn(df, **kwargs)
    except Exception:
        return html.Div()
    return rec_strip(recs)
