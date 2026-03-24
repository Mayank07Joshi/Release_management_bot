# components/bot/nlp.py

import re

def extract_entities(text: str):
    """Extract entities from user query."""
    text_low = text.lower()

    # Priority / Severity
    severity = None
    if "p1" in text_low: severity = 1
    elif "p2" in text_low: severity = 2
    elif "p3" in text_low: severity = 3
    elif "p4" in text_low: severity = 4

    # Work Item Type (Bug, Enhancement, Task, Story, User Story)
    work_item_type = None
    if "enhancement" in text_low:
        work_item_type = "Enhancement"
    elif "bug" in text_low:
        work_item_type = "Bug_UI"  # Or could be Bug_Functional, but default to UI
    elif "task" in text_low:
        work_item_type = "Task"
    elif "user story" in text_low or "story" in text_low:
        work_item_type = "User Story"

    # Time periods
    time_period = None
    if "last month" in text_low:
        time_period = "last_month"
    elif "this month" in text_low:
        time_period = "this_month"
    elif "last week" in text_low:
        time_period = "last_week"

    # Year extraction (2024, 2025, etc.)
    year = None
    year_match = re.search(r"\b(20\d{2})\b", text_low)
    if year_match:
        year = int(year_match.group(1))

    # Basic detection of team name
    team = None
    team_match = re.search(r"team\s+([a-zA-Z0-9_-]+)", text_low)
    if team_match:
        team = team_match.group(1)

    entities = {
        "severity": severity,
        "time_period": time_period,
        "team": team,
        "work_item_type": work_item_type,
        "year": year
    }
    return entities