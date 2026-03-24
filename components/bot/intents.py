# components/bot/intents.py

def classify_intent(text: str, entities: dict):
    t = (text or "").lower()

    # Navigation
    if "go to" in t or "open " in t or "show me" in t or "navigate" in t:
        return "navigation"

    # Metric Q&A
    if "how many" in t or "count" in t or "number of" in t or "total " in t:
        return "metric_query"

    # Trend questions
    if "trend" in t or "increasing" in t or "decreasing" in t or "over time" in t:
        return "trend_query"

    # Help
    if "help" in t or "what can you do" in t:
        return "help"

    return "unknown"