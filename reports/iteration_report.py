"""
Iteration Report Generator
===========================
Generates a self-contained HTML management report for a given sprint month.

Usage
-----
    from reports.iteration_report import generate_iteration_report
    html = generate_iteration_report("2026-05")

The returned string is a complete HTML document ready to serve as a download
or open in a browser.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from data.loader import engine

# ── State groupings ────────────────────────────────────────────────────────────
_CLOSED = frozenset([
    "Closed", "Dev Review Completed", "Resolved", "Not Required",
    "Not an issue", "No Customer Response", "Userstory Update",
    "Waiting on Customer",
])
_INPROG = frozenset([
    "Dev InProgress", "Dev Complete", "Dev Review", "In QA",
    "Tester Assigned", "Active", "Approved", "Prioritised",
])
_OPEN = frozenset([
    "New", "Request Estimate", "Clarification", "Watch List",
    "On Hold", "Blocked", "Estimated",
])

_BUG_TYPES = {"Bug", "Bug_UI", "Bug_Text", "Bug_Watchlist"}
_ENH_TYPES = {"Enhancement"}


# ── Data loading ───────────────────────────────────────────────────────────────

def _load(ym_str: str) -> dict:
    year  = int(ym_str[:4])
    month = int(ym_str[5:7])
    sprint_start = date(year, month, 1)
    _, last_day  = calendar.monthrange(year, month)
    sprint_end   = date(year, month, last_day)
    month_name   = sprint_start.strftime("%B %Y")

    like_pat = f"%Iteration {year} {month:02d}-%"

    with engine.connect() as c:
        items = pd.read_sql(text("""
            SELECT work_item_id, title, work_item_type, state, priority,
                   original_estimate, completed_work, remaining_work,
                   main_developer, function, created_date, closed_date, type
            FROM work_items_main
            WHERE iteration_path LIKE :pat
              AND work_item_type IN (
                  'Enhancement','Bug','Bug_UI','Bug_Text','Bug_Watchlist'
              )
        """), c, params={"pat": like_pat})

        cap_rows = c.execute(text("""
            SELECT main_developer, item_type,
                   SUM(estimated_hours) estimated_hours
            FROM agg_dev_monthly_capacity
            WHERE ym_str = :ym
            GROUP BY main_developer, item_type
        """), {"ym": ym_str}).fetchall()

    if items.empty:
        return {"error": f"No items found for {ym_str}"}

    # Normalise
    items["state"]      = items["state"].fillna("").astype(str).str.strip()
    items["priority"]   = pd.to_numeric(items["priority"], errors="coerce").fillna(4).astype(int)
    items["original_estimate"] = pd.to_numeric(items["original_estimate"], errors="coerce").fillna(0)
    items["created_date"] = pd.to_datetime(items["created_date"], errors="coerce")
    items["main_developer"] = items["main_developer"].fillna("Unassigned").astype(str).str.strip()
    items["function"]   = items["function"].fillna("—").astype(str).str.strip()
    items["type"]       = items["type"].fillna("").astype(str).str.strip()

    items["is_closed"]  = items["state"].isin(_CLOSED)
    items["is_inprog"]  = items["state"].isin(_INPROG)
    items["is_open"]    = ~items["is_closed"] & ~items["is_inprog"]

    enhs = items[items["work_item_type"].isin(_ENH_TYPES)].copy()
    bugs = items[items["work_item_type"].isin(_BUG_TYPES)].copy()

    # Scope creep — items created after day 3 of sprint
    cutoff = sprint_start + timedelta(days=3)
    items["mid_sprint"] = items["created_date"].dt.date > cutoff
    mid_sprint_n = int(items["mid_sprint"].sum())

    # Developer summary
    dev_grp = items.groupby("main_developer").agg(
        total=("work_item_id", "count"),
        closed=("is_closed", "sum"),
        in_prog=("is_inprog", "sum"),
        open_=("is_open", "sum"),
        est_h=("original_estimate", "sum"),
    ).reset_index().sort_values("total", ascending=False)

    # Capacity
    cap_map: dict[tuple, float] = {}
    for row in cap_rows:
        cap_map[(row.main_developer, row.item_type)] = float(row.estimated_hours or 0)

    # P1/P2 bugs
    hi_prio_bugs = bugs[bugs["priority"] <= 2].copy()

    # Estimation
    unest = items[items["original_estimate"] == 0].copy()

    # Carry-forward
    carry = items[~items["is_closed"]].copy()

    return dict(
        ym_str=ym_str, month_name=month_name,
        sprint_start=sprint_start, sprint_end=sprint_end,
        items=items, enhs=enhs, bugs=bugs,
        total_n=len(items),
        enh_total=len(enhs), enh_closed=int(enhs["is_closed"].sum()),
        enh_inprog=int(enhs["is_inprog"].sum()), enh_open=int(enhs["is_open"].sum()),
        bug_total=len(bugs), bug_closed=int(bugs["is_closed"].sum()),
        bug_inprog=int(bugs["is_inprog"].sum()), bug_open=int(bugs["is_open"].sum()),
        mid_sprint_n=mid_sprint_n,
        dev_grp=dev_grp,
        cap_map=cap_map,
        hi_prio_bugs=hi_prio_bugs,
        unest=unest,
        carry=carry,
    )


# ── HTML helpers ───────────────────────────────────────────────────────────────

def _pct(n, d):
    return round(n / d * 100) if d else 0


def _rag(value, green_thresh, amber_thresh, invert=False):
    """Return (color_hex, bg_hex, label) for a RAG badge."""
    if invert:
        ok = value <= green_thresh
        warn = value <= amber_thresh
    else:
        ok = value >= green_thresh
        warn = value >= amber_thresh
    if ok:
        return "#059669", "#ECFDF5", "#166534", "GREEN"
    if warn:
        return "#D97706", "#FFFBEB", "#92400E", "AMBER"
    return "#DC2626", "#FEF2F2", "#991B1B", "RED"


def _badge(label, color, bg, text_color):
    return (f'<span style="display:inline-flex;align-items:center;gap:4px;'
            f'background:{bg};color:{text_color};border:1px solid {color}33;'
            f'border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600;'
            f'letter-spacing:0.03em;text-transform:uppercase;">'
            f'<span style="color:{color};font-size:8px;">●</span>{label}</span>')


def _kpi(label, value, sub, color):
    return f"""
    <div style="background:#fff;border:1px solid #E5E7EB;border-radius:12px;
                padding:22px 24px;border-top:3px solid {color};">
      <div style="font-size:11px;font-weight:700;color:#9CA3AF;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:6px;">{label}</div>
      <div style="font-size:32px;font-weight:800;color:#111827;line-height:1;
                  margin-bottom:6px;">{value}</div>
      <div style="font-size:12px;color:#6B7280;">{sub}</div>
    </div>"""


def _progress_bar(pct, color):
    capped = min(pct, 100)
    return (f'<div style="background:#F3F4F6;border-radius:4px;height:6px;'
            f'width:100%;margin-top:4px;">'
            f'<div style="background:{color};width:{capped}%;height:100%;'
            f'border-radius:4px;"></div></div>')


# ── Report sections ────────────────────────────────────────────────────────────

def _section(title: str, content: str, icon: str = "") -> str:
    return f"""
    <div style="margin-bottom:32px;">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;
                  padding-bottom:10px;border-bottom:2px solid #E5E7EB;">
        {f'<span style="font-size:18px;">{icon}</span>' if icon else ""}
        <h2 style="font-size:16px;font-weight:700;color:#1E3A5F;margin:0;
                   letter-spacing:0.01em;text-transform:uppercase;">{title}</h2>
      </div>
      {content}
    </div>"""


def _table(headers: list, rows: list, col_widths: list | None = None) -> str:
    w_attrs = [f' width="{w}"' if col_widths and i < len(col_widths) else ""
               for i, _ in enumerate(headers)]
    th_cells = "".join(
        f'<th style="background:#1E3A5F;color:#fff;padding:10px 14px;'
        f'text-align:left;font-size:11px;font-weight:600;'
        f'letter-spacing:0.05em;text-transform:uppercase;'
        f'white-space:nowrap;"{w_attrs[i]}>{h}</th>'
        for i, h in enumerate(headers)
    )
    tr_rows = ""
    for ri, row in enumerate(rows):
        bg = "#F8FAFF" if ri % 2 == 0 else "#FFFFFF"
        td_cells = "".join(
            f'<td style="padding:9px 14px;font-size:12px;color:#374151;'
            f'border-bottom:1px solid #F3F4F6;">{cell}</td>'
            for cell in row
        )
        tr_rows += f'<tr style="background:{bg};">{td_cells}</tr>'
    return (f'<div style="overflow-x:auto;border-radius:10px;'
            f'border:1px solid #E5E7EB;margin-bottom:16px;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr>{th_cells}</tr></thead>'
            f'<tbody>{tr_rows}</tbody>'
            f'</table></div>')


# ── Findings engine ────────────────────────────────────────────────────────────

def _findings(d: dict) -> list[dict]:
    findings = []

    enh_del = _pct(d["enh_closed"], d["enh_total"])
    bug_res = _pct(d["bug_closed"], d["bug_total"])
    scope_pct = _pct(d["mid_sprint_n"], d["total_n"])
    est_cov = _pct(d["total_n"] - len(d["unest"]), d["total_n"])
    carry_pct = _pct(len(d["carry"]), d["total_n"])
    hi_open = len(d["hi_prio_bugs"][~d["hi_prio_bugs"]["is_closed"]])

    # Enhancement delivery
    if enh_del < 30:
        findings.append(dict(
            level="HIGH", color="#DC2626", bg="#FEF2F2",
            title="Low Enhancement Delivery Rate",
            body=(f"Only {d['enh_closed']} of {d['enh_total']} enhancements reached a closed state "
                  f"this sprint ({enh_del}%). The majority remain in development or carry forward. "
                  f"Review sprint sizing and ensure stories are broken into completable units within a single sprint."),
            rec="Reduce sprint commitment to 60–70% of team capacity to build in buffer for bugs, scope changes, and review cycles."
        ))
    elif enh_del < 60:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Moderate Enhancement Completion",
            body=(f"{d['enh_closed']} of {d['enh_total']} enhancements closed ({enh_del}%). "
                  f"While progress is being made, a significant carry-forward load will impact next sprint planning."),
            rec="Triage carry-forward items early in the next sprint to ensure only genuinely in-scope work is carried."
        ))

    # Scope creep
    if scope_pct > 40:
        findings.append(dict(
            level="HIGH", color="#DC2626", bg="#FEF2F2",
            title="Significant Mid-Sprint Scope Injection",
            body=(f"{d['mid_sprint_n']} of {d['total_n']} items ({scope_pct}%) were added after sprint day 3. "
                  f"This level of scope injection destabilises sprint planning, inflates carry-forward, "
                  f"and prevents meaningful velocity tracking."),
            rec="Enforce a sprint freeze after Day 2 for all non-P1 Customer items. New work should queue for the next sprint unless a trade-off is explicitly agreed."
        ))
    elif scope_pct > 20:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Elevated Mid-Sprint Additions",
            body=(f"{d['mid_sprint_n']} items ({scope_pct}% of total scope) were added mid-sprint. "
                  f"This is above the recommended threshold of 15%."),
            rec="Review the sprint intake process. Items should be fully triaged and estimated before sprint start."
        ))

    # P1/P2 bugs
    if hi_open > 0:
        open_titles = d["hi_prio_bugs"][~d["hi_prio_bugs"]["is_closed"]]["title"].str[:60].tolist()
        sample = "; ".join(open_titles[:3])
        if len(open_titles) > 3:
            sample += f" (+{len(open_titles)-3} more)"
        findings.append(dict(
            level="HIGH", color="#DC2626", bg="#FEF2F2",
            title=f"Open P1/P2 Bugs Require Immediate Attention",
            body=(f"{hi_open} high-priority bug(s) remain unresolved: {sample}. "
                  f"Priority 1 and 2 bugs represent customer-critical or system-impacting issues "
                  f"and should be resolved before new feature work is started."),
            rec="Assign owners and target resolution dates for all open P1/P2 items. Escalate if blockers exist."
        ))

    # Estimation gaps
    if est_cov < 70:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Low Estimation Coverage",
            body=(f"Only {d['total_n'] - len(d['unest'])} of {d['total_n']} sprint items "
                  f"carry an original estimate ({est_cov}%). Without estimates, capacity planning and "
                  f"sprint velocity calculations are unreliable."),
            rec="Require estimates before items enter 'Active' or 'Dev InProgress'. Use the Unestimated Items view to identify gaps each sprint."
        ))

    # Carry-forward
    if carry_pct > 50:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="High Carry-Forward Volume",
            body=(f"{len(d['carry'])} of {d['total_n']} items ({carry_pct}%) are rolling forward into the next sprint. "
                  f"A sustained carry-forward rate above 40% indicates persistent over-commitment."),
            rec="Run a carry-forward triage session at sprint start — confirm each item still belongs in scope before re-committing."
        ))

    # Bug vs enhancement ratio
    if d["bug_total"] > d["enh_total"] * 1.5:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Bug Load Exceeding Enhancement Work",
            body=(f"Bugs ({d['bug_total']}) outnumber enhancements ({d['enh_total']}) "
                  f"by {round(d['bug_total']/max(d['enh_total'],1), 1)}× this sprint. "
                  f"A high bug load compresses time available for feature delivery and indicates "
                  f"quality debt accumulating from prior sprints."),
            rec="Conduct a root-cause review on top bug sources. Consider a dedicated 'bug-bash' sprint if the ratio persists above 1.5× for two consecutive sprints."
        ))

    if not findings:
        findings.append(dict(
            level="LOW", color="#059669", bg="#ECFDF5",
            title="No Critical Issues Identified",
            body="All key metrics are within acceptable thresholds for this sprint.",
            rec="Continue monitoring scope injection rate and estimation compliance."
        ))

    return findings


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_iteration_report(ym_str: str) -> str:
    d = _load(ym_str)
    if "error" in d:
        return f"<html><body><h1>Error: {d['error']}</h1></body></html>"

    today = date.today().strftime("%d %B %Y").lstrip("0")

    enh_del_pct = _pct(d["enh_closed"], d["enh_total"])
    bug_res_pct = _pct(d["bug_closed"], d["bug_total"])
    scope_pct   = _pct(d["mid_sprint_n"], d["total_n"])
    est_cov_pct = _pct(d["total_n"] - len(d["unest"]), d["total_n"])

    # ── KPI cards ────────────────────────────────────────────────────────────
    _, _, _, del_rag  = _rag(enh_del_pct, 70, 40)
    _, _, _, res_rag  = _rag(bug_res_pct, 70, 50)
    _, _, _, sc_rag   = _rag(scope_pct, 15, 35, invert=True)
    _, _, _, est_rag  = _rag(est_cov_pct, 80, 60)

    del_c  = "#059669" if del_rag == "GREEN" else "#D97706" if del_rag == "AMBER" else "#DC2626"
    res_c  = "#059669" if res_rag == "GREEN" else "#D97706" if res_rag == "AMBER" else "#DC2626"
    sc_c   = "#059669" if sc_rag  == "GREEN" else "#D97706" if sc_rag  == "AMBER" else "#DC2626"
    est_c  = "#059669" if est_rag == "GREEN" else "#D97706" if est_rag == "AMBER" else "#DC2626"

    kpis_html = f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:32px;">
      {_kpi("Enhancement Delivery", f"{enh_del_pct}%",
            f"{d['enh_closed']} of {d['enh_total']} enhancements closed", del_c)}
      {_kpi("Bug Resolution", f"{bug_res_pct}%",
            f"{d['bug_closed']} of {d['bug_total']} bugs resolved", res_c)}
      {_kpi("Scope Creep", f"{scope_pct}%",
            f"{d['mid_sprint_n']} of {d['total_n']} items added mid-sprint", sc_c)}
      {_kpi("Estimation Coverage", f"{est_cov_pct}%",
            f"{d['total_n'] - len(d['unest'])} of {d['total_n']} items estimated", est_c)}
    </div>"""

    # ── Sprint delivery table ────────────────────────────────────────────────
    def _state_row(label, total, closed, inprog, open_, color):
        if total == 0:
            return ""
        c_pct = _pct(closed, total)
        bar = _progress_bar(c_pct, color)
        return (f'<tr style="background:#fff;">'
                f'<td style="padding:12px 14px;font-weight:600;color:#111827;'
                f'font-size:13px;border-bottom:1px solid #F3F4F6;">{label}</td>'
                f'<td style="padding:12px 14px;font-size:13px;color:#374151;'
                f'border-bottom:1px solid #F3F4F6;text-align:center;">{total}</td>'
                f'<td style="padding:12px 14px;font-size:13px;color:#059669;font-weight:600;'
                f'border-bottom:1px solid #F3F4F6;text-align:center;">{closed}</td>'
                f'<td style="padding:12px 14px;font-size:13px;color:#2563EB;'
                f'border-bottom:1px solid #F3F4F6;text-align:center;">{inprog}</td>'
                f'<td style="padding:12px 14px;font-size:13px;color:#9CA3AF;'
                f'border-bottom:1px solid #F3F4F6;text-align:center;">{open_}</td>'
                f'<td style="padding:12px 20px;border-bottom:1px solid #F3F4F6;min-width:120px;">'
                f'<div style="font-size:11px;color:#6B7280;margin-bottom:2px;">{c_pct}% complete</div>'
                f'{bar}</td></tr>')

    delivery_table = f"""
    <div style="overflow-x:auto;border-radius:10px;border:1px solid #E5E7EB;margin-bottom:16px;">
    <table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      <th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:left;
                 font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;">
        Work Type</th>
      <th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:center;
                 font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;
                 width:80px;">Total</th>
      <th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:center;
                 font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;
                 width:80px;">Closed</th>
      <th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:center;
                 font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;
                 width:100px;">In Progress</th>
      <th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:center;
                 font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;
                 width:80px;">Open</th>
      <th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:left;
                 font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;
                 width:160px;">Completion</th>
    </tr></thead>
    <tbody>
      {_state_row("Enhancements", d["enh_total"], d["enh_closed"], d["enh_inprog"], d["enh_open"], "#2563EB")}
      {_state_row("Bugs & Issues", d["bug_total"], d["bug_closed"], d["bug_inprog"], d["bug_open"], "#DC2626")}
    </tbody>
    </table></div>"""

    # State breakdown for enhancements
    enh_states = d["enhs"].groupby("state").size().reset_index(name="n").sort_values("n", ascending=False)
    enh_state_rows = []
    for _, row in enh_states.iterrows():
        tag = ("CLOSED" if row["state"] in _CLOSED else
               "IN PROGRESS" if row["state"] in _INPROG else "OPEN")
        tc = "#059669" if tag == "CLOSED" else "#2563EB" if tag == "IN PROGRESS" else "#9CA3AF"
        enh_state_rows.append([
            row["state"],
            f'<span style="font-size:10px;color:{tc};font-weight:600;">{tag}</span>',
            f'<strong>{row["n"]}</strong>',
        ])

    delivery_detail = _table(["State", "Category", "Count"], enh_state_rows)

    delivery_content = f"""
    {delivery_table}
    <details style="margin-top:8px;">
      <summary style="cursor:pointer;font-size:12px;color:#2563EB;font-weight:600;
                      padding:6px 0;user-select:none;">
        ▸ Enhancement state breakdown</summary>
      <div style="margin-top:8px;">{delivery_detail}</div>
    </details>"""

    # ── Scope section ────────────────────────────────────────────────────────
    items_at_start = d["total_n"] - d["mid_sprint_n"]
    _, sc_bg, sc_tx, sc_lbl = _rag(scope_pct, 15, 35, invert=True)
    scope_badge = _badge(f"{scope_pct}% scope creep", "#DC2626" if sc_lbl=="RED" else "#D97706" if sc_lbl=="AMBER" else "#059669", sc_bg, sc_tx)

    # Mid-sprint additions by type
    mid = d["items"][d["items"]["mid_sprint"]]
    mid_by_type = mid.groupby("work_item_type").size().reset_index(name="n")
    mid_rows = [[row["work_item_type"], str(row["n"])] for _, row in mid_by_type.iterrows()]

    scope_content = f"""
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;">
      <div style="background:#F8FAFF;border:1px solid #E5E7EB;border-radius:10px;padding:16px 20px;">
        <div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;
                    letter-spacing:1px;margin-bottom:4px;">Items at Sprint Start</div>
        <div style="font-size:28px;font-weight:800;color:#111827;">{items_at_start}</div>
      </div>
      <div style="background:#F8FAFF;border:1px solid #E5E7EB;border-radius:10px;padding:16px 20px;">
        <div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;
                    letter-spacing:1px;margin-bottom:4px;">Added Mid-Sprint</div>
        <div style="font-size:28px;font-weight:800;color:#DC2626 if scope_pct>35 else '#D97706';">{d["mid_sprint_n"]}</div>
      </div>
      <div style="background:#F8FAFF;border:1px solid #E5E7EB;border-radius:10px;padding:16px 20px;">
        <div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;
                    letter-spacing:1px;margin-bottom:4px;">Sprint Close Total</div>
        <div style="font-size:28px;font-weight:800;color:#111827;">{d["total_n"]}</div>
      </div>
    </div>
    <p style="font-size:13px;color:#374151;margin-bottom:12px;">
      {scope_badge}&nbsp;
      Items added after sprint day 3 count as mid-sprint scope injection.
      A rate above 15% typically indicates insufficient pre-sprint grooming
      or uncontrolled reactive triage.
    </p>
    {_table(["Work Type", "Mid-Sprint Count"], mid_rows) if mid_rows else ""}"""

    # ── Capacity section ─────────────────────────────────────────────────────
    from config.dev_capacity import DEVELOPERS, DEV_MAP
    cap_rows_html = []
    for dev_cfg in DEVELOPERS:
        name = dev_cfg["name"]
        cap  = dev_cfg["capacity_h"]
        enh_h = d["cap_map"].get((name, "enhancement"), 0)
        bug_h = d["cap_map"].get((name, "bug"), 0)
        feat_h = enh_h + bug_h
        alloc_pct = _pct(feat_h, cap)
        alloc_c = "#059669" if alloc_pct <= 80 else "#D97706" if alloc_pct <= 100 else "#DC2626"
        cap_rows_html.append([
            f"<strong>{name}</strong>",
            f"{cap:.0f}h",
            f"{enh_h:.0f}h",
            f"{bug_h:.0f}h",
            f"{feat_h:.0f}h",
            f'<span style="color:{alloc_c};font-weight:700;">{alloc_pct}%</span>',
        ])

    capacity_content = _table(
        ["Developer", "Capacity", "Enhancements", "Bugs", "Total Feature", "Allocation %"],
        cap_rows_html
    )

    # ── Developer delivery ───────────────────────────────────────────────────
    dev_rows_html = []
    for _, row in d["dev_grp"].iterrows():
        if row["main_developer"] in ("Unassigned", "nan", ""):
            continue
        closed_pct = _pct(int(row["closed"]), int(row["total"]))
        bar = _progress_bar(closed_pct, "#2563EB")
        dev_rows_html.append([
            f"<strong>{row['main_developer']}</strong>",
            str(int(row["total"])),
            f'<span style="color:#059669;font-weight:600;">{int(row["closed"])}</span>',
            f'<span style="color:#2563EB;">{int(row["in_prog"])}</span>',
            f'<span style="color:#9CA3AF;">{int(row["open_"])}</span>',
            f"{row['est_h']:.0f}h",
            f'<div style="min-width:100px;">'
            f'<span style="font-size:11px;color:#6B7280;">{closed_pct}%</span>{bar}</div>',
        ])

    dev_content = _table(
        ["Developer", "Total", "Closed", "In Progress", "Open", "Est. Hours", "Completion"],
        dev_rows_html
    )

    # ── P1/P2 bugs ───────────────────────────────────────────────────────────
    hi_rows = []
    for _, row in d["hi_prio_bugs"].sort_values(["priority", "state"]).iterrows():
        status = "RESOLVED" if row["is_closed"] else "OPEN"
        s_color = "#059669" if row["is_closed"] else "#DC2626"
        prio_color = "#DC2626" if row["priority"] == 1 else "#D97706"
        hi_rows.append([
            f'<span style="font-weight:700;color:{prio_color};">P{int(row["priority"])}</span>',
            f'<span style="font-size:12px;">{str(row["title"])[:80]}</span>',
            row["state"],
            row["main_developer"],
            f'<span style="color:{s_color};font-weight:600;font-size:11px;">{status}</span>',
        ])

    if hi_rows:
        hiprio_content = _table(["Priority", "Title", "State", "Developer", "Status"], hi_rows)
    else:
        hiprio_content = '<p style="color:#059669;font-size:13px;">No P1/P2 bugs in this sprint. ✓</p>'

    # ── Estimation gaps ──────────────────────────────────────────────────────
    unest_rows = []
    for _, row in d["unest"].sort_values("main_developer").head(20).iterrows():
        unest_rows.append([
            row["work_item_type"],
            f'<span style="font-size:12px;">{str(row["title"])[:70]}</span>',
            row["main_developer"],
            row["state"],
        ])
    if unest_rows:
        est_content = (f'<p style="font-size:13px;color:#374151;margin-bottom:12px;">'
                       f'{len(d["unest"])} item(s) have no original estimate. '
                       f'{"Showing top 20." if len(d["unest"]) > 20 else ""}</p>'
                       + _table(["Type", "Title", "Developer", "State"], unest_rows))
    else:
        est_content = '<p style="color:#059669;font-size:13px;">All sprint items carry an estimate. ✓</p>'

    # ── Carry-forward ────────────────────────────────────────────────────────
    carry_rows = []
    for _, row in d["carry"].sort_values(["main_developer", "state"]).head(25).iterrows():
        carry_rows.append([
            row["work_item_type"],
            f'<span style="font-size:12px;">{str(row["title"])[:70]}</span>',
            row["state"],
            row["main_developer"],
            f'{row["original_estimate"]:.0f}h',
        ])
    if carry_rows:
        carry_content = (f'<p style="font-size:13px;color:#374151;margin-bottom:12px;">'
                         f'{len(d["carry"])} item(s) carry forward to the next sprint. '
                         f'{"Showing top 25." if len(d["carry"]) > 25 else ""}</p>'
                         + _table(["Type", "Title", "State", "Developer", "Est."], carry_rows))
    else:
        carry_content = '<p style="color:#059669;font-size:13px;">All sprint items resolved. ✓</p>'

    # ── Findings & recommendations ───────────────────────────────────────────
    findings_list = _findings(d)
    findings_html = ""
    for i, f in enumerate(findings_list, 1):
        level_color = f["color"]
        level_bg    = f["bg"]
        findings_html += f"""
        <div style="border-left:4px solid {level_color};background:{level_bg};
                    border-radius:0 10px 10px 0;padding:16px 20px;margin-bottom:14px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
            <span style="background:{level_color};color:#fff;border-radius:20px;
                         padding:2px 10px;font-size:10px;font-weight:700;
                         letter-spacing:0.05em;text-transform:uppercase;">{f["level"]}</span>
            <strong style="font-size:14px;color:#111827;">{i}. {f["title"]}</strong>
          </div>
          <p style="font-size:13px;color:#374151;margin-bottom:8px;line-height:1.6;">
            {f["body"]}</p>
          <div style="font-size:12px;color:{level_color};font-weight:600;">
            ▸ Recommendation: <span style="color:#374151;font-weight:400;">{f["rec"]}</span>
          </div>
        </div>"""

    # ── Assemble full HTML ───────────────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sprint Report — {d["month_name"]} | Expense On Demand</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
        rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
      background: #F9FAFB;
      color: #111827;
      font-size: 14px;
      line-height: 1.5;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .page {{ max-width: 1100px; margin: 0 auto; padding: 0 32px 60px; }}
    details summary::-webkit-details-marker {{ display: none; }}
    @media print {{
      body {{ background: #fff; }}
      .page {{ padding: 0 20px 40px; }}
      details {{ open: true; }}
    }}
  </style>
</head>
<body>
  <!-- Cover -->
  <div style="background:linear-gradient(135deg,#1E3A5F 0%,#2563EB 100%);
              color:#fff;padding:48px 64px 40px;margin-bottom:0;">
    <div style="max-width:1100px;margin:0 auto;">
      <div style="font-size:11px;font-weight:700;letter-spacing:3px;
                  text-transform:uppercase;opacity:0.7;margin-bottom:12px;">
        EXPENSE ON DEMAND · INTERNAL MANAGEMENT REPORT
      </div>
      <h1 style="font-size:36px;font-weight:800;margin-bottom:8px;line-height:1.1;">
        Sprint Iteration Report
      </h1>
      <div style="font-size:20px;opacity:0.85;font-weight:500;margin-bottom:32px;">
        {d["month_name"]}
      </div>
      <div style="display:flex;gap:48px;flex-wrap:wrap;border-top:1px solid rgba(255,255,255,0.2);
                  padding-top:24px;">
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                      opacity:0.6;margin-bottom:4px;">Sprint Period</div>
          <div style="font-size:14px;font-weight:600;">
            {d["sprint_start"].strftime("%d %b").lstrip("0")} – {d["sprint_end"].strftime("%d %b %Y").lstrip("0")}
          </div>
        </div>
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                      opacity:0.6;margin-bottom:4px;">Prepared</div>
          <div style="font-size:14px;font-weight:600;">{today}</div>
        </div>
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                      opacity:0.6;margin-bottom:4px;">Total Sprint Items</div>
          <div style="font-size:14px;font-weight:600;">{d["total_n"]}</div>
        </div>
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                      opacity:0.6;margin-bottom:4px;">Classification</div>
          <div style="font-size:14px;font-weight:600;">INTERNAL — MANAGEMENT</div>
        </div>
      </div>
    </div>
  </div>

  <div class="page">
    <div style="height:32px;"></div>

    <!-- Executive Summary -->
    {_section("Executive Summary", kpis_html, "📊")}

    <!-- Sprint Delivery -->
    {_section("Sprint Delivery", delivery_content, "📦")}

    <!-- Scope Management -->
    {_section("Scope Management", scope_content, "🎯")}

    <!-- Capacity -->
    {_section("Capacity & Allocation", capacity_content, "⚡")}

    <!-- Developer Breakdown -->
    {_section("Developer Delivery Breakdown", dev_content, "👥")}

    <!-- P1/P2 Bugs -->
    {_section("Priority Bug Status (P1 & P2)", hiprio_content, "🔴")}

    <!-- Estimation -->
    {_section("Estimation Compliance", est_content, "📏")}

    <!-- Carry-Forward -->
    {_section("Carry-Forward Items", carry_content, "➜")}

    <!-- Findings -->
    {_section("Key Findings & Recommendations", findings_html, "💡")}

    <!-- Footer -->
    <div style="border-top:1px solid #E5E7EB;padding-top:20px;margin-top:40px;
                display:flex;justify-content:space-between;align-items:center;">
      <div style="font-size:11px;color:#9CA3AF;">
        Expense On Demand · Release Analytics · {d["month_name"]} Sprint Report
      </div>
      <div style="font-size:11px;color:#9CA3AF;">
        Generated {today} · INTERNAL — NOT FOR DISTRIBUTION
      </div>
    </div>
  </div>
</body>
</html>"""
