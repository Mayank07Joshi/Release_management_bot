"""
db/templates.py
───────────────
Task Template Library — all template definitions from PRD Section 5.

Public API:
  TEMPLATES          — dict of key → template metadata
  TEMPLATE_ORDER     — display order for the selector UI
  generate_tasks(feature_ref, feature_title, template_keys)
                     → list of task dicts ready to pass to create_task()
"""

# ── Template definitions ──────────────────────────────────────────────────────
# Each entry defines what gets auto-filled when that template is selected.

TEMPLATES: dict[str, dict] = {

    # ── Feature-linked ────────────────────────────────────────────────────────

    "req_gathering": {
        "label":            "Req Gathering",
        "activity":         "Requirement/Analysis",
        "title_prefix":     "REQ",
        "default_estimate": 4.0,
        "default_priority": 2,
        "tags":             "Requirements",
        "description": (
            "Problem statement:\n\n"
            "Open questions:\n\n"
            "Stakeholders involved:\n\n"
            "Meeting notes:\n"
        ),
        "dod": "Requirements documented and approved by stakeholders.",
    },

    "design": {
        "label":            "Design Implementation",
        "activity":         "Design",
        "title_prefix":     "DESIGN",
        "default_estimate": 8.0,
        "default_priority": 2,
        "tags":             "Design",
        "description": (
            "Current behaviour:\n\n"
            "Proposed design:\n\n"
            "Impacted components:\n\n"
            "Risks:\n"
        ),
        "dod": "Design reviewed and signed-off.",
    },

    "development": {
        "label":            "Development",
        "activity":         "Development",
        "title_prefix":     "DEV",
        "default_estimate": 16.0,
        "default_priority": 2,
        "tags":             "Dev",
        "description": (
            "Scope of change:\n\n"
            "Files / modules affected:\n\n"
            "APIs / DB changes:\n\n"
            "Unit test plan:\n"
        ),
        "dod": "Code merged, unit tests added, and PR approved.",
    },

    "testing": {
        "label":            "Testing",
        "activity":         "Testing",
        "title_prefix":     "TEST",
        "default_estimate": 8.0,
        "default_priority": 2,
        "tags":             "Testing",
        "description": (
            "Test scope:\n\n"
            "Environments:\n\n"
            "Test data:\n\n"
            "Entry / exit criteria:\n\n"
            "Bugs logged:\n"
        ),
        "dod": "All test scenarios passed. Defects raised and linked.",
    },

    "review": {
        "label":            "Review / Playback",
        "activity":         "Meeting/Review",
        "title_prefix":     "REVIEW",
        "default_estimate": 2.0,
        "default_priority": 2,
        "tags":             "Review",
        "description": (
            "Meeting objective:\n\n"
            "Attendees:\n\n"
            "Agenda:\n\n"
            "Notes:\n\n"
            "Action items:\n"
        ),
        "dod": "Feedback addressed and follow-up tasks created.",
    },

    "test_cases": {
        "label":            "Test Case Authoring",
        "activity":         "Testing/Documentation",
        "title_prefix":     "TESTCASE",
        "default_estimate": 8.0,
        "default_priority": 3,
        "tags":             "TestCases",
        "description": (
            "Scope:\n\n"
            "Test design technique:\n\n"
            "Location of cases (link):\n\n"
            "Coverage summary:\n"
        ),
        "dod": "Test cases reviewed and approved.",
    },

    "automation": {
        "label":            "Automation / Sanity",
        "activity":         "Automation/Testing",
        "title_prefix":     "AUTOMATION",
        "default_estimate": 8.0,
        "default_priority": 3,
        "tags":             "Automation",
        "description": (
            "Scenarios to automate:\n\n"
            "Framework / repo path:\n\n"
            "Test data:\n\n"
            "CI job link:\n"
        ),
        "dod": "Scripts in repo and pipeline green.",
    },
}

# Display order for the template selector UI
TEMPLATE_ORDER = [
    "req_gathering",
    "design",
    "development",
    "testing",
    "review",
    "test_cases",
    "automation",
]


# ── Task generator ────────────────────────────────────────────────────────────

def generate_tasks(
    feature_ref: str,
    feature_title: str,
    template_keys: list[str],
) -> list[dict]:
    """
    Build a list of task dicts for the given template keys.
    Each dict maps directly to create_task() parameters.

    Title format: "<PREFIX> | <feature_ref> | <short feature title>"
    """
    short_title = feature_title[:40].rstrip()
    tasks = []
    for key in template_keys:
        t = TEMPLATES.get(key)
        if not t:
            continue
        tasks.append({
            "title":             f"{t['title_prefix']} | {feature_ref} | {short_title}",
            "activity":          t["activity"],
            "template_key":      key,
            "original_estimate": t.get("default_estimate"),
            "priority":          t.get("default_priority", 2),
            "description":       t.get("description", ""),
            "dod":               t.get("dod", ""),
            "tags":              t.get("tags", ""),
        })
    return tasks
