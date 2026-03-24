# components/bot/formatter.py

def format_response(intent, result, entities):

    if intent == "metric_query":
        sev = entities.get("severity")
        sev_label = f"P{sev}" if sev else "all severities"
        item_type = entities.get("work_item_type", "items")
        year = entities.get("year")
        year_label = f" in {year}" if year else ""
        return f"There are **{result['count']}** {item_type}{year_label} for {sev_label} under the filters applied."

    if intent == "trend_query":
        trend = result["trend"]
        text = "Here is the month-by-month trend:\n"
        for month, val in trend.items():
            text += f"- **{month}**: {val}\n"
        return text

    if intent == "navigation":
        page = result.get("page")
        if page:
            return f"Navigating to {page}…"
        return "Navigating to the requested page…"

    if intent == "help":
        return (
            "I can help with:\n"
            "- Counting bugs/tasks (e.g., *how many P1 bugs last month?*)\n"
            "- Showing trends (e.g., *Is the closing balance rising?*)\n"
            "- Navigating the app (e.g., *Open Teams Dashboard*)\n"
            "Ask me anything!"
        )

    return "I’m not sure how to answer that yet. Try asking in a different way!"    