"""Standalone task classifier — two-stage pipeline.

Stage 1: Rule-based keyword matching (fast, deterministic)
Stage 2: Ollama llama3.2:3b for titles that rules don't catch

Scope: Dev + Mobile team members only (CEO directive — scale to full team later).
Incremental: skips tasks already in standalone_task_classifications.

Entry point: run_classifier()
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

OLLAMA_MODEL = "llama3.2:3b"
DEV_TEAMS    = {"Development", "Mobile"}

CATEGORIES = [
    "Meetings & Calls",
    "Dev Overhead",
    "Research & Spikes",
    "Design & Docs",
    "Testing & QA",
    "Operations",
    "Other",
]

# (category, keywords) — checked in order, first match wins
_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("Meetings & Calls", [
        "standup", "stand-up", "stand up", "daily scrum", "retrospective", "retro",
        "sprint planning", "sprint review", "planning session", "sync call",
        "team meeting", "call with", "weekly call", "monthly call", "one on one",
        "1:1", "1-1", "kickoff", "kick-off", "showcase", "town hall", "townhall",
        "escalation", "review meeting", "status meeting", "catch up", "catch-up",
        "scrum", "grooming", "backlog grooming", "sprint ceremony",
        "demo session", "product demo", "project meeting", "scheduled call",
        "recurring call", "weekly meeting", "daily meeting", "client call",
        "management meeting", "monthly meeting",
    ]),
    ("Dev Overhead", [
        "optimization", "optimise", "optimize", "refactor", "refactoring",
        "code review", "code cleanup", "technical debt", "performance improvement",
        "performance tuning", "cleanup", "clean up", "ci/cd", "jenkins",
        "automation script", "build script", "devops", "workflow automation",
        "pr review", "pull request review", "merge conflict", "code audit",
        "linting", "static analysis",
    ]),
    ("Research & Spikes", [
        "spike", "poc", "proof of concept", "feasibility", "investigation",
        "research", "r&d", "evaluate", "exploration", "prototype",
        "technical investigation", "feasibility study", "analysis task",
    ]),
    ("Design & Docs", [
        "documentation", "document", "write docs", "update docs",
        "knowledge transfer", "kt session", "knowledge sharing",
        "training", "onboarding", "figma", "design review", "ux review",
        "wiki", "confluence", "readme", "release notes",
    ]),
    ("Testing & QA", [
        "test case", "test cases", "regression", "sanity", "smoke test",
        "exploratory testing", "test plan", "qa review", "manual testing",
        "test execution", "bug verification", "test script",
    ]),
    ("Operations", [
        "infrastructure", "server setup", "environment setup", "deployment",
        "release deployment", "hotfix deployment", "infra", "monitoring",
        "alert setup", "certificate", "ssl", "aws", "azure setup",
        "database migration", "db migration", "server maintenance",
        "environment config", "env setup",
    ]),
]

# ADO Activity field → category fallback (used when no keyword matches)
_ACTIVITY_FALLBACK: dict[str, str] = {
    "development":   "Dev Overhead",
    "testing":       "Testing & QA",
    "design":        "Design & Docs",
    "documentation": "Design & Docs",
    "requirements":  "Research & Spikes",
    "deployment":    "Operations",
}


def _classify_rules(title: str, activity: str) -> tuple[str, str] | None:
    """Return (category, confidence) if a rule matches, else None."""
    t = title.lower()
    for category, keywords in _KEYWORD_RULES:
        if any(kw in t for kw in keywords):
            return category, "high"
    a = (activity or "").lower().strip()
    if a in _ACTIVITY_FALLBACK:
        return _ACTIVITY_FALLBACK[a], "medium"
    return None


def _classify_ollama_batch(tasks: list[dict]) -> list[dict]:
    """Send each task to Ollama llama3.2:3b and return classification dicts."""
    try:
        import ollama
    except ImportError:
        log.warning("ollama package not importable — falling back for %d tasks", len(tasks))
        return [_fallback(t) for t in tasks]

    cats_str = "\n".join(f"- {c}" for c in CATEGORIES)
    results  = []

    for t in tasks:
        prompt = (
            "You classify software development work tasks for a product team.\n\n"
            f"Valid categories:\n{cats_str}\n\n"
            f"Task title: \"{t['title']}\"\n"
            f"ADO Activity field: \"{t.get('activity') or 'not set'}\"\n\n"
            "Rules:\n"
            "- Pick exactly ONE category from the list above.\n"
            "- If the title mentions a meeting, call, standup, or demo → Meetings & Calls.\n"
            "- Reply with ONLY valid JSON, no explanation outside the JSON.\n\n"
            'Format: {"category": "<category>", "confidence": "<high|medium|low>", '
            '"reasoning": "<one short sentence>"}'
        )
        try:
            resp = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1},
            )
            raw = resp["message"]["content"].strip()
            m   = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                cat    = parsed.get("category", "Other")
                if cat not in CATEGORIES:
                    cat = "Other"
                results.append({
                    "task_id":    t["work_item_id"],
                    "title":      t["title"],
                    "activity":   t.get("activity", ""),
                    "category":   cat,
                    "confidence": parsed.get("confidence", "low"),
                    "method":     "ollama",
                    "reasoning":  parsed.get("reasoning", ""),
                })
            else:
                log.warning("Ollama unparseable for #%s: %.120s", t["work_item_id"], raw)
                results.append(_fallback(t))
        except Exception as e:
            log.warning("Ollama error for #%s: %s", t["work_item_id"], e)
            results.append(_fallback(t))

    return results


def _fallback(t: dict) -> dict:
    return {
        "task_id":    t["work_item_id"],
        "title":      t["title"],
        "activity":   t.get("activity", ""),
        "category":   "Other",
        "confidence": "low",
        "method":     "fallback",
        "reasoning":  "No rule match; Ollama unavailable",
    }


def run_classifier() -> int:
    """
    Find unclassified standalone tasks for Dev+Mobile team, classify them,
    and persist results. Returns number of tasks classified.
    """
    from config.team_mapping import TEAM_MAPPING
    from db.standalone import (
        get_unclassified_standalone_tasks,
        save_classifications,
        init_standalone_table,
    )

    try:
        init_standalone_table()
    except Exception as e:
        log.warning("init_standalone_table failed (non-fatal): %s", e)
        return 0

    team_members = [n for n, team in TEAM_MAPPING.items() if team in DEV_TEAMS]
    if not team_members:
        log.info("Standalone classifier: no dev/mobile members in TEAM_MAPPING")
        return 0

    tasks = get_unclassified_standalone_tasks(team_members)
    if not tasks:
        log.info("Standalone classifier: nothing new to classify")
        return 0

    log.info("Standalone classifier: %d tasks to classify", len(tasks))

    rules_results: list[dict] = []
    ollama_queue:  list[dict] = []

    for t in tasks:
        hit = _classify_rules(t["title"], t.get("activity", ""))
        if hit:
            cat, conf = hit
            rules_results.append({
                "task_id":    t["work_item_id"],
                "title":      t["title"],
                "activity":   t.get("activity", ""),
                "category":   cat,
                "confidence": conf,
                "method":     "rules",
                "reasoning":  f"Keyword match → {cat}",
            })
        else:
            ollama_queue.append(t)

    log.info("Standalone classifier: %d by rules, %d to Ollama",
             len(rules_results), len(ollama_queue))

    ollama_results = _classify_ollama_batch(ollama_queue) if ollama_queue else []
    all_results    = rules_results + ollama_results

    saved = save_classifications(all_results)
    log.info("Standalone classifier: %d tasks saved", saved)
    return saved
