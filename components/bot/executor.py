# components/bot/executor.py

import pandas as pd
from datetime import datetime, timedelta

def _metric_answer(df, entities):
    severity = entities.get("severity")
    time_period = entities.get("time_period")
    team = entities.get("team")
    work_item_type = entities.get("work_item_type")
    year = entities.get("year")

    d = df.copy()

    # Filter by work item type
    if work_item_type and "work_item_type" in d.columns:
        d = d[d["work_item_type"].str.contains(work_item_type, case=False, na=False)]

    # Filter by severity (P1/P2)
    if severity and "priority" in d.columns:
        d = d[d["priority"] == severity]

    # Filter by team
    if team and "team" in d.columns:
        d = d[d["team"].str.lower() == team.lower()]

    # Filter by year (from created_date)
    if year and "created_date" in d.columns:
        d["created_year"] = pd.to_datetime(d["created_date"], errors="coerce").dt.year
        d = d[d["created_year"] == year]

    # Time filters
    now = datetime.now()

    if time_period == "last_month":
        start = (now.replace(day=1) - pd.Timedelta(days=1)).replace(day=1)
        end = start + pd.offsets.MonthEnd()
        if "created_date" in d.columns:
            d = d[pd.to_datetime(d["created_date"], errors="coerce").between(start, end)]

    if time_period == "this_month":
        start = now.replace(day=1)
        if "created_date" in d.columns:
            d = d[pd.to_datetime(d["created_date"], errors="coerce") >= start]

    return {"count": len(d), "items": d}

def _trend_answer(df, entities):
    severity = entities.get("severity")
    work_item_type = entities.get("work_item_type")
    d = df.copy()

    if work_item_type and "work_item_type" in d.columns:
        d = d[d["work_item_type"].str.contains(work_item_type, case=False, na=False)]

    if severity and "priority" in d.columns:
        d = d[d["priority"] == severity]

    if "created_date" in d.columns:
        d["month"] = pd.to_datetime(d["created_date"], errors="coerce").dt.to_period("M")
        trend = d.groupby("month").size()
    else:
        trend = pd.Series()

    return {"trend": trend.to_dict()}

def _detect_page_from_query(text):
    """Detect which page to navigate to based on query text."""
    t = text.lower()
    if "summary" in t: return "pages/page1_summary.py"
    if "bugs" in t: return "pages/page2_bugs.py"
    if "capacity" in t: return "pages/page3_capacity.py"
    if "qa" in t: return "pages/page4_qa_health.py"
    if "team" in t: return "pages/page5_teams.py"
    return None



def execute_intent(intent: str, entities: dict, df: pd.DataFrame, user_query: str = ""):
    """
    This function decides WHICH internal function to call based on intent.
    """

    if intent == "navigation":
        # Navigation is simple — return a page name (you’ll implement switching later)
        return {"page": _detect_page_from_query(user_query)}

    if intent == "metric_query":
        # Anything like "how many P1 bugs"
        return _metric_answer(df, entities)

    if intent == "trend_query":
        # Anything like "trend of bugs"
        return _trend_answer(df, entities)

    if intent == "help":
        return {"help": True}

    return {"unknown": True}