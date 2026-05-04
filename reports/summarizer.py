"""
reports/summarizer.py
Computes structured summary dicts from the ADO dataframe for each board.
Each function returns a dict that formatter.py turns into readable output.
"""

import pandas as pd
import numpy as np
from datetime import datetime, date

# ── Thresholds (targets) ──────────────────────────────────────────────────────
TARGETS = {
    "defect_escape_rate_pct": 10,      # % bugs found in PROD
    "customer_open_bugs":     30,
    "enh_bug_ratio":          1.0,
    "open_bug_backlog":       150,
    "open_critical_bugs":     5,
    "bugs_per_iter":          15,
    "mttc_critical_days":     3,
    "mttc_high_days":         7,
    "mttc_medium_days":       14,
    "release_completion_pct": 80,      # % closed items per release
    "sla_breach_rate_pct":    10,      # % bugs breaching SLA
    "capacity_utilisation":   85,      # % target utilisation
}

CLOSED_STATES   = {"Closed", "Not an issue", "Not Required", "Userstory Update", "No Customer Response"}
BUG_TYPES       = {"Bug", "Bug_UI", "Bug_Text"}


def _is_open(df):
    return ~df["state"].isin(CLOSED_STATES)


def _safe_pct(num, denom):
    if denom == 0:
        return 0.0
    return round(num / denom * 100, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# BUGS BOARD
# ═══════════════════════════════════════════════════════════════════════════════

def summarize_bugs(df: pd.DataFrame) -> dict:
    bugs = df[df["work_item_type"].isin(BUG_TYPES)].copy()
    enh  = df[df["work_item_type"] == "Enhancement"]
    open_bugs = bugs[_is_open(bugs)]

    total       = len(bugs)
    total_open  = len(open_bugs)
    total_closed = total - total_open

    # Priority breakdown
    p1 = len(open_bugs[open_bugs["priority"] == 1])
    p2 = len(open_bugs[open_bugs["priority"] == 2])
    p3 = len(open_bugs[open_bugs["priority"] == 3])
    p4 = len(open_bugs[open_bugs["priority"] == 4])

    # Stage breakdown (defect escape)
    dev_bugs  = len(bugs[bugs.get("stage", pd.Series(dtype=str)) == "2 - Dev"]) if "stage" in bugs.columns else 0
    qa_bugs   = len(bugs[bugs.get("stage", pd.Series(dtype=str)) == "3 - QA"])  if "stage" in bugs.columns else 0
    prod_bugs = len(bugs[bugs.get("stage", pd.Series(dtype=str)) == "4 - PROD"]) if "stage" in bugs.columns else 0
    escape_rate = _safe_pct(prod_bugs, total) if total else 0

    # Customer bugs
    cust_bugs  = bugs[bugs.get("type", pd.Series(dtype=str)) == "Customer"] if "type" in bugs.columns else pd.DataFrame()
    open_cust  = cust_bugs[_is_open(cust_bugs)] if len(cust_bugs) else pd.DataFrame()
    cust_pct_prod = _safe_pct(
        len(bugs[(bugs.get("stage", pd.Series(dtype=str)) == "4 - PROD") & (bugs.get("type", pd.Series(dtype=str)) == "Customer")]),
        prod_bugs
    ) if "stage" in bugs.columns and "type" in bugs.columns and prod_bugs else 0

    # MTTC
    bc = bugs[bugs["closed_date"].notna() & bugs["created_date"].notna()].copy()
    bc["mttc"] = (pd.to_datetime(bc["closed_date"]) - pd.to_datetime(bc["created_date"])).dt.days
    bc = bc[bc["mttc"] >= 0]
    def mttc_for(p):
        sub = bc[bc["priority"] == p]
        return (round(sub["mttc"].median(), 0) if len(sub) else None,
                round(sub["mttc"].mean(), 0) if len(sub) else None,
                len(sub))
    mttc = {p: mttc_for(p) for p in [1, 2, 3, 4]}

    # Bugs per iteration (2025/2026)
    recent = bugs[bugs["iteration_path"].astype(str).str.contains("2025|2026", na=False)]
    if len(recent):
        def _iter_label(x):
            parts = str(x).split("\\")
            return parts[-1]
        recent = recent.copy()
        recent["iter_label"] = recent["iteration_path"].apply(_iter_label)
        per_iter = recent.groupby("iter_label").size().sort_values(ascending=False)
        avg_per_iter  = round(per_iter.mean(), 0)
        worst_iter    = per_iter.index[0] if len(per_iter) else "—"
        worst_iter_n  = int(per_iter.iloc[0]) if len(per_iter) else 0
    else:
        avg_per_iter = worst_iter = worst_iter_n = None

    # Enh:Bug ratio
    enh_bug_ratio = round(len(enh) / total, 2) if total else 0

    # Trend: bugs created last 30 days vs prior 30 days
    today = pd.Timestamp(date.today())
    if "created_date" in bugs.columns:
        bugs["created_date"] = pd.to_datetime(bugs["created_date"], errors="coerce")
        last30  = len(bugs[(bugs["created_date"] >= today - pd.Timedelta(days=30)) & (bugs["created_date"] <= today)])
        prior30 = len(bugs[(bugs["created_date"] >= today - pd.Timedelta(days=60)) & (bugs["created_date"] < today - pd.Timedelta(days=30))])
        trend_pct = _safe_pct(last30 - prior30, prior30) if prior30 else None
    else:
        last30 = prior30 = trend_pct = None

    return {
        "board": "bugs",
        "as_of": datetime.now().strftime("%d %b %Y %H:%M"),
        "total": total,
        "total_open": total_open,
        "total_closed": total_closed,
        "open_p1": p1, "open_p2": p2, "open_p3": p3, "open_p4": p4,
        "escape_rate_pct": escape_rate,
        "dev_bugs": dev_bugs, "qa_bugs": qa_bugs, "prod_bugs": prod_bugs,
        "customer_total": len(cust_bugs),
        "customer_open":  len(open_cust),
        "customer_pct_prod": cust_pct_prod,
        "mttc": mttc,                  # {1: (median, mean, n), ...}
        "avg_per_iter": avg_per_iter,
        "worst_iter": worst_iter,
        "worst_iter_n": worst_iter_n,
        "enh_bug_ratio": enh_bug_ratio,
        "total_enh": len(enh),
        "bugs_last30": last30,
        "bugs_prior30": prior30,
        "trend_pct": trend_pct,
        "targets": TARGETS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# QA HEALTH BOARD
# ═══════════════════════════════════════════════════════════════════════════════

SLA_DAYS = {1: 1, 2: 2, 3: 5, 4: 10}

def summarize_qa(df: pd.DataFrame) -> dict:
    bugs = df[df["work_item_type"].isin(BUG_TYPES)].copy()

    # QA-found bugs
    qa_found = bugs[bugs.get("stage", pd.Series(dtype=str)) == "3 - QA"] if "stage" in bugs.columns else pd.DataFrame()

    # SLA compliance (closed bugs only)
    bc = bugs[bugs["closed_date"].notna() & bugs["created_date"].notna()].copy()
    bc["mttc"] = (pd.to_datetime(bc["closed_date"]) - pd.to_datetime(bc["created_date"])).dt.days
    bc = bc[bc["mttc"] >= 0]
    bc["sla_days"] = bc["priority"].map(SLA_DAYS).fillna(10)
    bc["sla_breach"] = bc["mttc"] > bc["sla_days"]
    sla_compliance = {}
    for p in [1, 2, 3, 4]:
        sub = bc[bc["priority"] == p]
        if len(sub):
            breaches = int(sub["sla_breach"].sum())
            sla_compliance[p] = {
                "total": len(sub),
                "breaches": breaches,
                "breach_pct": _safe_pct(breaches, len(sub)),
                "sla_target": SLA_DAYS[p],
            }

    overall_breaches = int(bc["sla_breach"].sum()) if len(bc) else 0
    overall_breach_pct = _safe_pct(overall_breaches, len(bc)) if len(bc) else 0

    # Open bugs by tester / assigned_to
    open_bugs = bugs[_is_open(bugs)]
    if "assigned_to" in open_bugs.columns:
        assignee_load = (
            open_bugs.groupby("assigned_to").size()
            .sort_values(ascending=False)
            .head(5)
            .to_dict()
        )
    else:
        assignee_load = {}

    # Rejection rate
    rejected = bugs[bugs["state"].isin({"Not an issue", "Not Required"})]
    rejection_rate = _safe_pct(len(rejected), len(bugs)) if len(bugs) else 0

    # Reopened bugs
    reopened = bugs[bugs["state"] == "Reopened"] if "state" in bugs.columns else pd.DataFrame()

    return {
        "board": "qa",
        "as_of": datetime.now().strftime("%d %b %Y %H:%M"),
        "total_bugs": len(bugs),
        "qa_found": len(qa_found),
        "open_bugs": len(open_bugs),
        "sla_compliance": sla_compliance,
        "overall_breach_pct": overall_breach_pct,
        "overall_breaches": overall_breaches,
        "assignee_load": assignee_load,
        "rejection_rate": rejection_rate,
        "reopened_count": len(reopened),
        "targets": TARGETS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RELEASE OUTLOOK BOARD
# ═══════════════════════════════════════════════════════════════════════════════

def summarize_releases(df: pd.DataFrame) -> dict:
    if "release_date" not in df.columns:
        return {"board": "releases", "error": "No release_date column"}

    releases = df[df["release_date"].notna() & (df["release_date"] != "Not Specified")].copy()
    rel_summary = []

    for rel, grp in releases.groupby("release_date"):
        total   = len(grp)
        closed  = grp["state"].isin(CLOSED_STATES).sum()
        bugs    = grp["work_item_type"].isin(BUG_TYPES).sum()
        open_b  = grp[grp["work_item_type"].isin(BUG_TYPES) & ~grp["state"].isin(CLOSED_STATES)]
        p1_open = int((open_b["priority"] == 1).sum()) if len(open_b) else 0
        p2_open = int((open_b["priority"] == 2).sum()) if len(open_b) else 0
        completion = _safe_pct(closed, total)

        # Health signal
        if completion >= 80 and p1_open == 0:
            health = "green"
        elif p1_open > 0 or completion < 50:
            health = "red"
        else:
            health = "amber"

        rel_summary.append({
            "release":     rel,
            "total":       total,
            "closed":      int(closed),
            "completion":  completion,
            "bugs":        int(bugs),
            "open_bugs":   len(open_b),
            "p1_open":     p1_open,
            "p2_open":     p2_open,
            "health":      health,
        })

    rel_summary.sort(key=lambda x: x["release"])

    at_risk    = [r for r in rel_summary if r["health"] == "red"]
    on_track   = [r for r in rel_summary if r["health"] == "green"]
    caution    = [r for r in rel_summary if r["health"] == "amber"]
    total_open_p1 = sum(r["p1_open"] for r in rel_summary)

    return {
        "board": "releases",
        "as_of": datetime.now().strftime("%d %b %Y %H:%M"),
        "releases": rel_summary,
        "at_risk": at_risk,
        "on_track": on_track,
        "caution": caution,
        "total_open_p1": total_open_p1,
        "targets": TARGETS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CAPACITY BOARD
# ═══════════════════════════════════════════════════════════════════════════════

def summarize_capacity(df: pd.DataFrame) -> dict:
    COMPLETED = {"Closed"}

    if "original_estimate" not in df.columns or "completed_work" not in df.columns:
        return {"board": "capacity", "error": "Missing estimate/completed columns"}

    work = df[df["original_estimate"].notna() & (df["original_estimate"] > 0)].copy()
    total_est    = round(work["original_estimate"].sum(), 0)
    total_comp   = round(work["completed_work"].fillna(0).sum(), 0) if "completed_work" in work.columns else 0
    total_rem    = round(work["remaining_work"].fillna(0).sum(), 0) if "remaining_work" in work.columns else 0
    utilisation  = _safe_pct(total_comp, total_est)

    # By team
    team_col = "main_dev_team" if "main_dev_team" in work.columns else "team"
    team_stats = []
    if team_col in work.columns:
        for team, grp in work.groupby(team_col):
            if team in ("Unassigned", "Not Specified"):
                continue
            est  = round(grp["original_estimate"].sum(), 0)
            comp = round(grp["completed_work"].fillna(0).sum(), 0) if "completed_work" in grp.columns else 0
            rem  = round(grp["remaining_work"].fillna(0).sum(), 0) if "remaining_work" in grp.columns else 0
            util = _safe_pct(comp, est)
            team_stats.append({"team": team, "est": est, "comp": comp, "rem": rem, "util": util})
        team_stats.sort(key=lambda x: -x["util"])

    # Accuracy: closed items where estimate was set
    closed = work[work["state"].isin(COMPLETED)]
    if len(closed) and "completed_work" in closed.columns:
        acc_df = closed[closed["completed_work"].notna() & (closed["completed_work"] > 0)].copy()
        acc_df["ratio"] = acc_df["completed_work"] / acc_df["original_estimate"]
        over_est  = int((acc_df["ratio"] < 0.5).sum())   # done in less than half estimate
        under_est = int((acc_df["ratio"] > 1.5).sum())   # took 50% more than estimated
        accuracy_pct = _safe_pct(len(acc_df) - over_est - under_est, len(acc_df))
    else:
        over_est = under_est = 0
        accuracy_pct = None

    # Missing estimates: open items with no original_estimate
    open_df = df[~df["state"].isin(CLOSED_STATES)] if "state" in df.columns else df.copy()
    missing_mask = open_df["original_estimate"].isna() | (open_df["original_estimate"] == 0)
    missing = open_df[missing_mask].copy()

    person_col = "main_developer" if "main_developer" in missing.columns else "assigned_to"
    def _clean_name(n):
        s = str(n)
        return s.split(" <")[0].strip() if " <" in s else s

    if person_col in missing.columns:
        missing["_dev_disp"] = missing[person_col].apply(_clean_name)
        missing_by_person = (
            missing[~missing["_dev_disp"].isin({"Unassigned", "Not Specified", "nan", "None", ""})]
            .groupby("_dev_disp").size()
            .sort_values(ascending=False)
            .to_dict()
        )
    else:
        missing_by_person = {}

    if "iteration_path" in missing.columns:
        missing_by_iter = (
            missing.groupby("iteration_path").size()
            .sort_values(ascending=False)
            .to_dict()
        )
    else:
        missing_by_iter = {}

    _scols = ["work_item_id", "title", "work_item_type", "state", "iteration_path", "_dev_disp"]
    _avail = [c for c in _scols if c in missing.columns]
    missing_items = missing[_avail].head(25).to_dict("records")

    return {
        "board": "capacity",
        "as_of": datetime.now().strftime("%d %b %Y %H:%M"),
        "total_est": total_est,
        "total_comp": total_comp,
        "total_rem": total_rem,
        "utilisation_pct": utilisation,
        "team_stats": team_stats,
        "over_estimated": over_est,
        "under_estimated": under_est,
        "accuracy_pct": accuracy_pct,
        "missing_est_count": len(missing),
        "missing_by_person": missing_by_person,
        "missing_by_iter":   missing_by_iter,
        "missing_items":     missing_items,
        "targets": TARGETS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CEO / EXECUTIVE SUMMARY  (aggregates all boards)
# ═══════════════════════════════════════════════════════════════════════════════

def summarize_executive(df: pd.DataFrame) -> dict:
    bugs_s    = summarize_bugs(df)
    qa_s      = summarize_qa(df)
    rel_s     = summarize_releases(df)
    cap_s     = summarize_capacity(df)

    # Headline RAG status for each area
    def rag(value, target, lower_is_better=True):
        if value is None:
            return "grey"
        if lower_is_better:
            return "green" if value <= target else ("amber" if value <= target * 1.5 else "red")
        else:
            return "green" if value >= target else ("amber" if value >= target * 0.75 else "red")

    scorecard = [
        {
            "area": "Defect Escape Rate",
            "now": f"{bugs_s['escape_rate_pct']}%",
            "target": f"<{TARGETS['defect_escape_rate_pct']}%",
            "status": rag(bugs_s["escape_rate_pct"], TARGETS["defect_escape_rate_pct"]),
        },
        {
            "area": "Open Critical Bugs",
            "now": str(bugs_s["open_p1"]),
            "target": f"<{TARGETS['open_critical_bugs']}",
            "status": rag(bugs_s["open_p1"], TARGETS["open_critical_bugs"]),
        },
        {
            "area": "Open Bug Backlog",
            "now": str(bugs_s["total_open"]),
            "target": f"<{TARGETS['open_bug_backlog']}",
            "status": rag(bugs_s["total_open"], TARGETS["open_bug_backlog"]),
        },
        {
            "area": "Customer Open Issues",
            "now": str(bugs_s["customer_open"]),
            "target": f"<{TARGETS['customer_open_bugs']}",
            "status": rag(bugs_s["customer_open"], TARGETS["customer_open_bugs"]),
        },
        {
            "area": "Enh : Bug Ratio",
            "now": f"{bugs_s['enh_bug_ratio']}:1",
            "target": f"≥{TARGETS['enh_bug_ratio']}:1",
            "status": rag(bugs_s["enh_bug_ratio"], TARGETS["enh_bug_ratio"], lower_is_better=False),
        },
        {
            "area": "SLA Breach Rate",
            "now": f"{qa_s['overall_breach_pct']}%",
            "target": f"<{TARGETS['sla_breach_rate_pct']}%",
            "status": rag(qa_s["overall_breach_pct"], TARGETS["sla_breach_rate_pct"]),
        },
        {
            "area": "Releases On Track",
            "now": f"{len(rel_s.get('on_track', []))} / {len(rel_s.get('releases', []))}",
            "target": "All green",
            "status": "green" if not rel_s.get("at_risk") else ("amber" if len(rel_s.get("at_risk", [])) <= 1 else "red"),
        },
    ]

    return {
        "board": "executive",
        "as_of": datetime.now().strftime("%d %b %Y %H:%M"),
        "scorecard": scorecard,
        "bugs": bugs_s,
        "qa": qa_s,
        "releases": rel_s,
        "capacity": cap_s,
    }
