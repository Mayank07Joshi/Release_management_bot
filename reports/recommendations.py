"""
reports/recommendations.py
Contextual recommendations for each dashboard board.
Each function returns a list of dicts:
  {
    "type":    "critical" | "warning" | "positive",
    "title":   str,   # short label, 3-5 words
    "message": str,   # full sentence
    "metric":  str,   # key name for grouping
    "value":   any,   # raw value for reference (optional)
  }
Sorted order for display: critical → warning → positive.
"""

import pandas as pd
from datetime import date

# ── Closed state set (mirrors summarizer) ─────────────────────────────────────
CLOSED_STATES = {"Closed", "Not an issue", "Not Required", "Userstory Update", "No Customer Response"}
BUG_TYPES     = {"Bug", "Bug_UI", "Bug_Text"}

# ── Static thresholds ─────────────────────────────────────────────────────────
T = {
    # Capacity
    "util_critical":      130,   # % — team overcommitted
    "util_warning":       110,   # % — approaching limit
    "util_healthy_max":    90,   # % — upper bound of healthy range
    "util_healthy_min":    60,   # % — lower bound of healthy range
    "util_person_critical":130,  # % — individual overloaded
    "acc_low_warning":     70,   # % — team underestimating
    "acc_high_warning":   130,   # % — team overestimating
    "acc_healthy_min":     85,
    "acc_healthy_max":    115,

    # Bugs / QA
    "p1_aging_days":        3,   # days — P1 open past this → critical
    "p2_aging_days":        7,
    "reopen_rate_warning": 20,   # %
    "area_hotspot_pct":    30,   # % of bugs from one area
    "sla_breach_warning":  10,   # % overall breach rate
    "sla_breach_critical": 25,

    # Release
    "release_risk_buffer": 20,   # % behind schedule before warning
    "release_risk_critical":40,

    # Iteration
    "iter_not_started_pct": 30,  # % items not started at mid-iteration
    "iter_time_elapsed_pct":50,  # % of iteration elapsed to trigger check
}


def _sort(recs):
    order = {"critical": 0, "warning": 1, "positive": 2}
    return sorted(recs, key=lambda r: order.get(r["type"], 3))


# ══════════════════════════════════════════════════════════════════════════════
# CAPACITY
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations_capacity(df: pd.DataFrame, hours_day: int = 8) -> list:
    recs = []

    work = df.copy()
    if "original_estimate" not in work.columns:
        return recs

    work["original_estimate"] = pd.to_numeric(work["original_estimate"], errors="coerce").fillna(0)
    work["completed_work"]    = pd.to_numeric(work.get("completed_work", 0), errors="coerce").fillna(0)
    work = work[work["original_estimate"] > 0]
    if work.empty:
        return recs

    total_est  = work["original_estimate"].sum()
    total_comp = work["completed_work"].sum()
    util       = round(total_comp / total_est * 100, 1) if total_est > 0 else 0

    # ── Team-level utilisation ────────────────────────────────────────────────
    if util >= T["util_critical"]:
        recs.append({
            "type":    "critical",
            "title":   "Team overcommitted",
            "message": f"Team utilisation is at {util:.0f}% — significantly above capacity. Delivery slip is likely this iteration.",
            "metric":  "utilisation",
            "value":   util,
        })
    elif util >= T["util_warning"]:
        recs.append({
            "type":    "warning",
            "title":   "Approaching capacity limit",
            "message": f"Team utilisation is at {util:.0f}%. Leaves little buffer for unplanned work or blockers.",
            "metric":  "utilisation",
            "value":   util,
        })
    elif T["util_healthy_min"] <= util <= T["util_healthy_max"]:
        recs.append({
            "type":    "positive",
            "title":   "Utilisation healthy",
            "message": f"Team utilisation is at {util:.0f}% — well within the healthy 60–90% range.",
            "metric":  "utilisation",
            "value":   util,
        })
    elif util < T["util_healthy_min"] and util > 0:
        recs.append({
            "type":    "warning",
            "title":   "Team underloaded",
            "message": f"Utilisation is only {util:.0f}%. Either the team has unassigned capacity or estimates are missing.",
            "metric":  "utilisation",
            "value":   util,
        })

    # ── Estimation accuracy ───────────────────────────────────────────────────
    closed = work[work["state"].isin(CLOSED_STATES)]
    if len(closed) > 0:
        acc_df = closed[closed["completed_work"] > 0].copy()
        if len(acc_df) > 0:
            acc_df["ratio"] = acc_df["completed_work"] / acc_df["original_estimate"]
            over_est  = (acc_df["ratio"] < 0.5).sum()
            under_est = (acc_df["ratio"] > 1.5).sum()
            on_track  = len(acc_df) - over_est - under_est
            acc_pct   = round(on_track / len(acc_df) * 100, 1)

            if acc_pct >= T["acc_healthy_min"] and acc_pct <= T["acc_healthy_max"]:
                recs.append({
                    "type":    "positive",
                    "title":   "Estimation on track",
                    "message": f"{acc_pct:.0f}% of closed items completed within ±50% of estimate — team is sizing work well.",
                    "metric":  "accuracy",
                    "value":   acc_pct,
                })
            elif acc_pct < T["acc_low_warning"]:
                recs.append({
                    "type":    "warning",
                    "title":   "Team underestimating",
                    "message": f"Only {acc_pct:.0f}% of items complete within estimate. Work is consistently taking longer than planned.",
                    "metric":  "accuracy",
                    "value":   acc_pct,
                })
            elif acc_pct > T["acc_high_warning"]:
                recs.append({
                    "type":    "warning",
                    "title":   "Team overestimating",
                    "message": f"Estimates are significantly higher than actual effort ({acc_pct:.0f}% accuracy). Review sizing practices.",
                    "metric":  "accuracy",
                    "value":   acc_pct,
                })

    # ── Per-person overload ───────────────────────────────────────────────────
    person_col = "main_developer" if "main_developer" in work.columns else "assigned_to"
    if person_col in work.columns:
        person_stats = (
            work.groupby(person_col)
            .agg(est=("original_estimate", "sum"), comp=("completed_work", "sum"))
            .reset_index()
        )
        person_stats = person_stats[person_stats["est"] > 0]
        person_stats["util"] = person_stats["comp"] / person_stats["est"] * 100
        overloaded = person_stats[person_stats["util"] >= T["util_person_critical"]]
        if len(overloaded):
            names = ", ".join(overloaded[person_col].tolist()[:3])
            recs.append({
                "type":    "critical",
                "title":   "Individual overload detected",
                "message": f"{names} {'are' if len(overloaded) > 1 else 'is'} at ≥{T['util_person_critical']}% individual utilisation — burnout risk.",
                "metric":  "person_utilisation",
                "value":   overloaded["util"].max(),
            })

    return _sort(recs)


# ══════════════════════════════════════════════════════════════════════════════
# BUGS
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations_bugs(df: pd.DataFrame) -> list:
    recs = []

    bugs = df[df["work_item_type"].isin(BUG_TYPES)].copy()
    if bugs.empty:
        return recs

    open_bugs = bugs[~bugs["state"].isin(CLOSED_STATES)]
    today     = pd.Timestamp(date.today())

    # ── P1 open bug count ─────────────────────────────────────────────────────
    p1_open = open_bugs[open_bugs["priority"] == 1]
    p2_open = open_bugs[open_bugs["priority"] == 2]

    if len(p1_open) == 0:
        recs.append({
            "type":    "positive",
            "title":   "No open P1 bugs",
            "message": "Zero P1 bugs currently open — strong quality signal.",
            "metric":  "p1_open",
            "value":   0,
        })
    else:
        recs.append({
            "type":    "critical",
            "title":   f"{len(p1_open)} P1 bug{'s' if len(p1_open) > 1 else ''} open",
            "message": f"{len(p1_open)} critical P1 bug{'s are' if len(p1_open) > 1 else ' is'} still open and need immediate attention.",
            "metric":  "p1_open",
            "value":   len(p1_open),
        })

    # ── P1 aging ─────────────────────────────────────────────────────────────
    if "created_date" in p1_open.columns and len(p1_open):
        p1_open = p1_open.copy()
        p1_open["created_date"] = pd.to_datetime(p1_open["created_date"], errors="coerce")
        aging = p1_open[(today - p1_open["created_date"]).dt.days >= T["p1_aging_days"]]
        if len(aging):
            recs.append({
                "type":    "critical",
                "title":   "P1 bugs aging",
                "message": f"{len(aging)} P1 bug{'s have' if len(aging) > 1 else ' has'} been open for ≥{T['p1_aging_days']} days. Escalation may be needed.",
                "metric":  "p1_aging",
                "value":   len(aging),
            })

    # ── Unowned bugs ──────────────────────────────────────────────────────────
    if "assigned_to" in open_bugs.columns:
        high_prio = open_bugs[open_bugs["priority"].isin([1, 2])]
        unowned   = high_prio[high_prio["assigned_to"].isna() | (high_prio["assigned_to"].astype(str).str.strip() == "")]
        if len(unowned):
            recs.append({
                "type":    "warning",
                "title":   "High-priority bugs unassigned",
                "message": f"{len(unowned)} P1/P2 bug{'s have' if len(unowned) > 1 else ' has'} no owner. These will not get resolved without an assignee.",
                "metric":  "unassigned",
                "value":   len(unowned),
            })

    # ── Bug trend (last 30 vs prior 30 days) ─────────────────────────────────
    if "created_date" in bugs.columns:
        bugs["created_date"] = pd.to_datetime(bugs["created_date"], errors="coerce")
        last30  = len(bugs[(bugs["created_date"] >= today - pd.Timedelta(days=30)) & (bugs["created_date"] <= today)])
        prior30 = len(bugs[(bugs["created_date"] >= today - pd.Timedelta(days=60)) & (bugs["created_date"] < today - pd.Timedelta(days=30))])
        if prior30 > 0:
            change_pct = round((last30 - prior30) / prior30 * 100, 0)
            if change_pct >= 20:
                recs.append({
                    "type":    "warning",
                    "title":   "Bug intake increasing",
                    "message": f"Bug creation is up {change_pct:.0f}% this month vs last month ({last30} vs {prior30}). Quality may be degrading.",
                    "metric":  "bug_trend",
                    "value":   change_pct,
                })
            elif change_pct <= -20:
                recs.append({
                    "type":    "positive",
                    "title":   "Bug intake improving",
                    "message": f"Bug creation is down {abs(change_pct):.0f}% this month vs last month ({last30} vs {prior30}). Quality is trending up.",
                    "metric":  "bug_trend",
                    "value":   change_pct,
                })

    # ── Area hotspot ──────────────────────────────────────────────────────────
    area_col = next((c for c in ["area", "area_path", "func"] if c in open_bugs.columns), None)
    if area_col and len(open_bugs) >= 5:
        area_counts = open_bugs[area_col].dropna().value_counts()
        if len(area_counts):
            top_pct = round(area_counts.iloc[0] / len(open_bugs) * 100, 0)
            if top_pct >= T["area_hotspot_pct"]:
                recs.append({
                    "type":    "warning",
                    "title":   "Bug hotspot detected",
                    "message": f"{area_counts.index[0]!r} accounts for {top_pct:.0f}% of all open bugs — likely a systemic issue, not random noise.",
                    "metric":  "area_hotspot",
                    "value":   top_pct,
                })

    # ── Reopen rate ───────────────────────────────────────────────────────────
    if "state" in bugs.columns:
        reopened   = bugs[bugs["state"] == "Reopened"]
        total_closed = bugs[bugs["state"].isin(CLOSED_STATES)]
        if len(total_closed) > 0:
            reopen_rate = round(len(reopened) / len(total_closed) * 100, 1)
            if reopen_rate >= T["reopen_rate_warning"]:
                recs.append({
                    "type":    "warning",
                    "title":   "High reopen rate",
                    "message": f"{reopen_rate:.0f}% of closed bugs are being reopened. Fixes are not sticking — root causes may not be addressed.",
                    "metric":  "reopen_rate",
                    "value":   reopen_rate,
                })

    return _sort(recs)


# ══════════════════════════════════════════════════════════════════════════════
# QA HEALTH
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations_qa(df: pd.DataFrame) -> list:
    recs = []

    bugs = df[df["work_item_type"].isin(BUG_TYPES)].copy()
    if bugs.empty:
        return recs

    # ── SLA breach rate ───────────────────────────────────────────────────────
    SLA_DAYS = {1: 1, 2: 2, 3: 5, 4: 10}
    bc = bugs[bugs["closed_date"].notna() & bugs["created_date"].notna()].copy()
    if len(bc):
        bc["mttc"]      = (pd.to_datetime(bc["closed_date"]) - pd.to_datetime(bc["created_date"])).dt.days
        bc              = bc[bc["mttc"] >= 0]
        bc["sla_target"] = bc["priority"].map(SLA_DAYS).fillna(10)
        bc["breach"]     = bc["mttc"] > bc["sla_target"]
        breach_pct       = round(bc["breach"].mean() * 100, 1) if len(bc) else 0

        if breach_pct >= T["sla_breach_critical"]:
            recs.append({
                "type":    "critical",
                "title":   "SLA breach rate critical",
                "message": f"{breach_pct:.0f}% of closed bugs breached their SLA. Resolution times are significantly above targets.",
                "metric":  "sla_breach",
                "value":   breach_pct,
            })
        elif breach_pct >= T["sla_breach_warning"]:
            recs.append({
                "type":    "warning",
                "title":   "SLA breaches above target",
                "message": f"{breach_pct:.0f}% of bugs are exceeding their SLA resolution targets (goal: <{T['sla_breach_warning']}%).",
                "metric":  "sla_breach",
                "value":   breach_pct,
            })
        else:
            recs.append({
                "type":    "positive",
                "title":   "SLA compliance healthy",
                "message": f"Only {breach_pct:.0f}% of bugs breached SLA — team is resolving issues within target times.",
                "metric":  "sla_breach",
                "value":   breach_pct,
            })

    # ── Tester overload ───────────────────────────────────────────────────────
    open_bugs = bugs[~bugs["state"].isin(CLOSED_STATES)]
    if "assigned_to" in open_bugs.columns and len(open_bugs) > 0:
        load = open_bugs.groupby("assigned_to").size()
        avg  = load.mean()
        overloaded = load[load > avg * 1.5]
        if len(overloaded) and avg > 2:
            names = ", ".join(overloaded.index.tolist()[:2])
            recs.append({
                "type":    "warning",
                "title":   "Uneven tester workload",
                "message": f"{names} {'have' if len(overloaded) > 1 else 'has'} 50%+ more bugs than the team average ({avg:.0f}). Risk of bottleneck.",
                "metric":  "tester_load",
                "value":   overloaded.max(),
            })

    # ── Defect escape rate ────────────────────────────────────────────────────
    if "stage" in bugs.columns:
        prod_bugs = bugs[bugs["stage"] == "4 - PROD"]
        escape_pct = round(len(prod_bugs) / len(bugs) * 100, 1) if len(bugs) else 0
        if escape_pct > 10:
            recs.append({
                "type":    "warning",
                "title":   "High defect escape rate",
                "message": f"{escape_pct:.0f}% of bugs were found in PROD (target: <10%). QA coverage may need review.",
                "metric":  "escape_rate",
                "value":   escape_pct,
            })
        elif escape_pct <= 5 and len(bugs) >= 10:
            recs.append({
                "type":    "positive",
                "title":   "Low defect escape rate",
                "message": f"Only {escape_pct:.0f}% of bugs escaped to PROD — QA is catching issues early.",
                "metric":  "escape_rate",
                "value":   escape_pct,
            })

    return _sort(recs)


# ══════════════════════════════════════════════════════════════════════════════
# RELEASE OUTLOOK
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations_release(df: pd.DataFrame) -> list:
    recs = []

    if "release_date" not in df.columns:
        return recs

    releases = df[df["release_date"].notna() & (df["release_date"] != "Not Specified")].copy()
    if releases.empty:
        return recs

    at_risk_names  = []
    on_track_names = []

    for rel, grp in releases.groupby("release_date"):
        total      = len(grp)
        closed     = grp["state"].isin(CLOSED_STATES).sum()
        completion = round(closed / total * 100, 1) if total else 0

        open_bugs  = grp[grp["work_item_type"].isin(BUG_TYPES) & ~grp["state"].isin(CLOSED_STATES)]
        p1_open    = int((open_bugs["priority"] == 1).sum()) if len(open_bugs) else 0

        if completion >= 80 and p1_open == 0:
            on_track_names.append(rel)
        elif p1_open > 0 or completion < 50:
            at_risk_names.append(f"{rel} ({completion:.0f}% done, {p1_open} P1 open)")

    if at_risk_names:
        recs.append({
            "type":    "critical",
            "title":   f"{len(at_risk_names)} release{'s' if len(at_risk_names) > 1 else ''} at risk",
            "message": f"At-risk releases: {'; '.join(at_risk_names[:3])}. Low completion or open P1 bugs blocking ship.",
            "metric":  "release_health",
            "value":   len(at_risk_names),
        })

    if on_track_names:
        recs.append({
            "type":    "positive",
            "title":   f"{len(on_track_names)} release{'s' if len(on_track_names) > 1 else ''} on track",
            "message": f"{', '.join(on_track_names[:3])} {'are' if len(on_track_names) > 1 else 'is'} ≥80% complete with no open P1 bugs.",
            "metric":  "release_health",
            "value":   len(on_track_names),
        })

    # ── Total open P1 across all releases ────────────────────────────────────
    all_open_bugs = releases[releases["work_item_type"].isin(BUG_TYPES) & ~releases["state"].isin(CLOSED_STATES)]
    total_p1 = int((all_open_bugs["priority"] == 1).sum()) if len(all_open_bugs) else 0
    if total_p1 == 0 and len(releases) > 0:
        recs.append({
            "type":    "positive",
            "title":   "No P1 release blockers",
            "message": "No P1 bugs open across any active release. Ready to ship from a blocking-bug perspective.",
            "metric":  "total_p1",
            "value":   0,
        })

    return _sort(recs)


# ══════════════════════════════════════════════════════════════════════════════
# ITERATION BOARD
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations_iteration(df: pd.DataFrame, selected_iterations: list = None) -> list:
    recs = []

    if "iteration_path" not in df.columns:
        return recs

    work = df.copy()
    if selected_iterations:
        work = work[work["iteration_path"].isin(selected_iterations)]
    if work.empty:
        return recs

    total    = len(work)
    not_started_states = {"New", "Proposed"}
    not_started = work[work["state"].isin(not_started_states)]
    ns_pct   = round(len(not_started) / total * 100, 1) if total else 0

    # ── Not started mid-iteration ─────────────────────────────────────────────
    if ns_pct >= T["iter_not_started_pct"]:
        recs.append({
            "type":    "warning",
            "title":   "High not-started rate",
            "message": f"{ns_pct:.0f}% of iteration items haven't been started. Commitment may exceed actual capacity.",
            "metric":  "not_started",
            "value":   ns_pct,
        })
    elif ns_pct <= 10 and total >= 5:
        recs.append({
            "type":    "positive",
            "title":   "Good iteration progress",
            "message": f"Only {ns_pct:.0f}% of items not yet started — team has good momentum this iteration.",
            "metric":  "not_started",
            "value":   ns_pct,
        })

    # ── Completion rate ───────────────────────────────────────────────────────
    closed     = work[work["state"].isin(CLOSED_STATES)]
    comp_pct   = round(len(closed) / total * 100, 1) if total else 0

    if comp_pct >= 80:
        recs.append({
            "type":    "positive",
            "title":   "Strong iteration completion",
            "message": f"{comp_pct:.0f}% of items closed this iteration — excellent throughput.",
            "metric":  "completion",
            "value":   comp_pct,
        })
    elif comp_pct < 50 and total >= 5:
        recs.append({
            "type":    "warning",
            "title":   "Low iteration completion",
            "message": f"Only {comp_pct:.0f}% of items are closed. Review blockers or scope if this is near iteration end.",
            "metric":  "completion",
            "value":   comp_pct,
        })

    # ── Chronic spillover: items with no estimated date or stale ─────────────
    if "created_date" in work.columns:
        work["created_date"] = pd.to_datetime(work["created_date"], errors="coerce")
        today   = pd.Timestamp(date.today())
        stale   = work[
            (~work["state"].isin(CLOSED_STATES)) &
            ((today - work["created_date"]).dt.days >= 60)
        ]
        if len(stale) >= 3:
            recs.append({
                "type":    "warning",
                "title":   "Stale items in iteration",
                "message": f"{len(stale)} open items are 60+ days old. These may be stuck or chronically deferred.",
                "metric":  "spillover",
                "value":   len(stale),
            })

    return _sort(recs)


# ══════════════════════════════════════════════════════════════════════════════
# AGGREGATE (Summary / Executive page)
# ══════════════════════════════════════════════════════════════════════════════

def get_recommendations_all(df: pd.DataFrame) -> list:
    """Aggregate critical + warnings from all boards for the Summary page."""
    all_recs = []

    for fn, label in [
        (get_recommendations_bugs,     "Bugs"),
        (get_recommendations_qa,       "QA"),
        (get_recommendations_release,  "Release"),
        (get_recommendations_capacity, "Capacity"),
    ]:
        for rec in fn(df):
            rec = dict(rec)
            rec["board"] = label
            all_recs.append(rec)

    return _sort(all_recs)
