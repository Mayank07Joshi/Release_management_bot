"""
Iteration Report Generator
===========================
Generates a self-contained HTML management report for a given sprint month.

Usage
-----
    from reports.iteration_report import generate_iteration_report
    html = generate_iteration_report("2026-05")
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from data.loader import engine
from config.settings import ADO_BASE_URL

# ── State buckets (confirmed with team) ───────────────────────────────────────
_PLANNING    = frozenset(["New", "Estimated", "Clarification",
                           "Request Estimate", "On Hold"])
_DEV_ACTIVE  = frozenset(["Active", "Dev InProgress", "Dev Review", "Reopened"])
_DEV_DONE    = frozenset(["Dev Complete", "Dev Review Completed"])
_QA_ACTIVE   = frozenset(["Tester Assigned", "Watch List"])
_FULLY_DONE  = frozenset(["Closed", "Resolved", "Not Required", "Not an issue",
                           "Userstory Update", "No Customer Response",
                           "Waiting on Customer"])

# Dev has finished their part = DEV_DONE + QA_ACTIVE + FULLY_DONE
_DEV_DELIVERED = _DEV_DONE | _QA_ACTIVE | _FULLY_DONE

_BUG_TYPES = {"Bug", "Bug_UI", "Bug_Text", "Bug_Watchlist"}
_ENH_TYPES = {"Enhancement"}
_ALL_WORK   = _BUG_TYPES | _ENH_TYPES | {"Task"}


# ── Data loading ───────────────────────────────────────────────────────────────

def _load(ym_str: str) -> dict:
    year  = int(ym_str[:4])
    month = int(ym_str[5:7])
    sprint_start = date(year, month, 1)
    _, last_day  = calendar.monthrange(year, month)
    sprint_end   = date(year, month, last_day)
    month_name   = sprint_start.strftime("%B %Y")
    like_pat     = f"%Iteration {year} {month:02d}-%"

    with engine.connect() as c:
        # Enhancements + Bugs (for delivery metrics)
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

        # All work types including Tasks — for capacity breakdown
        all_items = pd.read_sql(text("""
            SELECT work_item_id, work_item_type, state,
                   original_estimate, completed_work, remaining_work,
                   main_developer
            FROM work_items_main
            WHERE iteration_path LIKE :pat
              AND work_item_type IN (
                  'Enhancement','Bug','Bug_UI','Bug_Text','Bug_Watchlist','Task'
              )
        """), c, params={"pat": like_pat})

    if items.empty:
        return {"error": f"No items found for {ym_str}"}

    # ── Normalise ─────────────────────────────────────────────────────────────
    for df in (items, all_items):
        df["state"]      = df["state"].fillna("").astype(str).str.strip()
        df["main_developer"] = df["main_developer"].fillna("Unassigned").astype(str).str.strip()
        df["original_estimate"] = pd.to_numeric(
            df["original_estimate"], errors="coerce").fillna(0)

    items["priority"]     = pd.to_numeric(items["priority"], errors="coerce").fillna(4).astype(int)
    items["created_date"] = pd.to_datetime(items["created_date"], errors="coerce")
    items["function"]     = items["function"].fillna("—").astype(str).str.strip()
    items["type"]         = items["type"].fillna("").astype(str).str.strip()

    # ── State flags ───────────────────────────────────────────────────────────
    items["is_planning"]   = items["state"].isin(_PLANNING)
    items["is_dev_active"] = items["state"].isin(_DEV_ACTIVE)
    items["is_dev_done"]   = items["state"].isin(_DEV_DONE)
    items["is_qa_active"]  = items["state"].isin(_QA_ACTIVE)
    items["is_fully_done"] = items["state"].isin(_FULLY_DONE)
    items["is_dev_delivered"] = items["state"].isin(_DEV_DELIVERED)
    items["is_reopened"]   = items["state"] == "Reopened"

    enhs = items[items["work_item_type"].isin(_ENH_TYPES)].copy()
    bugs = items[items["work_item_type"].isin(_BUG_TYPES)].copy()

    # ── Scope creep (created after day 3) ────────────────────────────────────
    cutoff = sprint_start + timedelta(days=3)
    items["mid_sprint"] = items["created_date"].dt.date > cutoff
    mid_sprint_n = int(items["mid_sprint"].sum())

    # ── Capacity breakdown (Tasks + Bugs + Enhancements) ─────────────────────
    # Group all work by developer and type
    cap_by_dev_type = (
        all_items.groupby(["main_developer", "work_item_type"])["original_estimate"]
        .sum()
        .reset_index()
    )
    # Pivot: developer → {Task, Bug+variants, Enhancement} hours
    dev_cap: dict[str, dict] = {}
    for _, row in cap_by_dev_type.iterrows():
        dev = row["main_developer"]
        wt  = row["work_item_type"]
        h   = float(row["original_estimate"])
        if dev not in dev_cap:
            dev_cap[dev] = {"task": 0.0, "bug": 0.0, "enh": 0.0}
        if wt == "Task":
            dev_cap[dev]["task"] += h
        elif wt in _BUG_TYPES:
            dev_cap[dev]["bug"] += h
        elif wt in _ENH_TYPES:
            dev_cap[dev]["enh"] += h

    # ── Developer summary ─────────────────────────────────────────────────────
    dev_grp = items.groupby("main_developer").agg(
        total        =("work_item_id",     "count"),
        dev_delivered=("is_dev_delivered", "sum"),
        dev_active   =("is_dev_active",    "sum"),
        in_qa        =("is_qa_active",     "sum"),
        planning     =("is_planning",      "sum"),
        reopened_n   =("is_reopened",      "sum"),
        est_h        =("original_estimate","sum"),
    ).reset_index().sort_values("total", ascending=False)

    # ── P1/P2 bugs ────────────────────────────────────────────────────────────
    hi_prio_bugs = bugs[bugs["priority"] <= 2].copy()

    # ── Estimation gaps ───────────────────────────────────────────────────────
    unest = items[items["original_estimate"] == 0].copy()

    # ── Carry-forward (items not fully done) ─────────────────────────────────
    carry = items[~items["is_fully_done"]].copy()

    # ── Reopened items ────────────────────────────────────────────────────────
    reopened = items[items["is_reopened"]].copy()

    return dict(
        ym_str=ym_str, month_name=month_name,
        sprint_start=sprint_start, sprint_end=sprint_end,
        items=items, enhs=enhs, bugs=bugs,
        total_n       = len(items),
        # Enhancements
        enh_total     = len(enhs),
        enh_delivered = int(enhs["is_dev_delivered"].sum()),
        enh_dev_active= int(enhs["is_dev_active"].sum()),
        enh_qa        = int(enhs["is_qa_active"].sum()),
        enh_planning  = int(enhs["is_planning"].sum()),
        enh_done      = int(enhs["is_fully_done"].sum()),
        # Bugs
        bug_total     = len(bugs),
        bug_delivered = int(bugs["is_dev_delivered"].sum()),
        bug_dev_active= int(bugs["is_dev_active"].sum()),
        bug_qa        = int(bugs["is_qa_active"].sum()),
        bug_planning  = int(bugs["is_planning"].sum()),
        bug_done      = int(bugs["is_fully_done"].sum()),
        # Scope
        mid_sprint_n  = mid_sprint_n,
        # Capacity
        dev_cap       = dev_cap,
        # Dev summary
        dev_grp       = dev_grp,
        # Special
        hi_prio_bugs  = hi_prio_bugs,
        unest         = unest,
        carry         = carry,
        reopened      = reopened,
    )


# ── HTML helpers ───────────────────────────────────────────────────────────────

def _pct(n, d):
    return round(n / d * 100) if d else 0


def _rag(value, green_thresh, amber_thresh, invert=False):
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


def _ado_link(work_item_id, label=None):
    url = f"{ADO_BASE_URL}{work_item_id}"
    text_= label or f"#{work_item_id}"
    return (f'<a href="{url}" target="_blank" '
            f'style="color:#2563EB;text-decoration:none;font-size:11px;'
            f'font-weight:600;white-space:nowrap;">{text_}</a>')


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


def _table(headers: list, rows: list) -> str:
    th = "".join(
        f'<th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:left;'
        f'font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;'
        f'white-space:nowrap;">{h}</th>'
        for h in headers
    )
    body = ""
    for ri, row in enumerate(rows):
        bg = "#F8FAFF" if ri % 2 == 0 else "#FFFFFF"
        tds = "".join(
            f'<td style="padding:9px 14px;font-size:12px;color:#374151;'
            f'border-bottom:1px solid #F3F4F6;">{cell}</td>'
            for cell in row
        )
        body += f'<tr style="background:{bg};">{tds}</tr>'
    return (f'<div style="overflow-x:auto;border-radius:10px;border:1px solid #E5E7EB;'
            f'margin-bottom:16px;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>')


# ── Findings ───────────────────────────────────────────────────────────────────

def _findings(d: dict) -> list[dict]:
    findings = []

    enh_del_pct = _pct(d["enh_delivered"], d["enh_total"])
    bug_del_pct = _pct(d["bug_delivered"], d["bug_total"])
    scope_pct   = _pct(d["mid_sprint_n"],  d["total_n"])
    est_cov_pct = _pct(d["total_n"] - len(d["unest"]), d["total_n"])
    carry_pct   = _pct(len(d["carry"]),    d["total_n"])
    hi_open     = len(d["hi_prio_bugs"][~d["hi_prio_bugs"]["is_dev_delivered"]])
    reop_n      = len(d["reopened"])

    # Dev delivery rate
    if enh_del_pct < 40:
        findings.append(dict(
            level="HIGH", color="#DC2626", bg="#FEF2F2",
            title="Low Enhancement Dev Delivery Rate",
            body=(f"Only {d['enh_delivered']} of {d['enh_total']} enhancements ({enh_del_pct}%) "
                  f"reached Dev Complete or beyond this sprint. The remaining "
                  f"{d['enh_total'] - d['enh_delivered']} items are still in active "
                  f"development or planning. Note: items in Dev Complete/QA stages will "
                  f"proceed to full closure in the following iteration."),
            rec="Review sprint commitment sizing. Target 70–80% of items reaching Dev Complete by sprint close, leaving buffer for QA and scope changes."
        ))
    elif enh_del_pct < 70:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Moderate Enhancement Dev Delivery",
            body=(f"{d['enh_delivered']} of {d['enh_total']} enhancements ({enh_del_pct}%) "
                  f"have been handed off to QA or closed. "
                  f"{d['enh_total'] - d['enh_delivered']} items remain in dev."),
            rec="Confirm carry-forward items are triaged and assigned before the next sprint starts."
        ))

    # Scope creep
    if scope_pct > 40:
        findings.append(dict(
            level="HIGH", color="#DC2626", bg="#FEF2F2",
            title="Significant Mid-Sprint Scope Injection",
            body=(f"{d['mid_sprint_n']} of {d['total_n']} items ({scope_pct}%) were added after "
                  f"sprint day 3. This compresses dev time and inflates carry-forward volume."),
            rec="Enforce sprint freeze after Day 2 for non-P1 Customer items. All new work should queue for the next sprint unless an explicit trade-off is agreed."
        ))
    elif scope_pct > 20:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Elevated Mid-Sprint Additions",
            body=(f"{d['mid_sprint_n']} items ({scope_pct}% of scope) were added mid-sprint "
                  f"— above the recommended 15% threshold."),
            rec="Tighten the sprint intake process. Items should be fully groomed and estimated before sprint start."
        ))

    # Reopened items
    if reop_n > 0:
        reop_titles = d["reopened"]["title"].str[:55].tolist()
        sample = "; ".join(reop_titles[:3])
        if len(reop_titles) > 3:
            sample += f" (+{len(reop_titles)-3} more)"
        findings.append(dict(
            level="HIGH", color="#DC2626", bg="#FEF2F2",
            title=f"Reopened Items Indicate Quality Regression ({reop_n})",
            body=(f"{reop_n} item(s) were reopened this sprint: {sample}. "
                  f"Reopened items signal issues that passed QA but failed in production or "
                  f"a later environment. Each reopened item represents a QA process gap."),
            rec="Conduct a root-cause review on each reopened item. Identify the environment where the regression was missed and add regression coverage."
        ))

    # P1/P2 bugs
    if hi_open > 0:
        open_titles = d["hi_prio_bugs"][~d["hi_prio_bugs"]["is_dev_delivered"]]["title"].str[:55].tolist()
        sample = "; ".join(open_titles[:3])
        if len(open_titles) > 3:
            sample += f" (+{len(open_titles)-3} more)"
        findings.append(dict(
            level="HIGH", color="#DC2626", bg="#FEF2F2",
            title=f"Open P1/P2 Bugs Require Immediate Attention ({hi_open})",
            body=f"{hi_open} high-priority bug(s) not yet handed to QA: {sample}.",
            rec="Assign owners and target Dev Complete dates immediately. P1/P2 bugs should take priority over all new feature development."
        ))

    # Estimation
    if est_cov_pct < 70:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Low Estimation Coverage",
            body=(f"Only {d['total_n'] - len(d['unest'])} of {d['total_n']} sprint items "
                  f"carry an estimate ({est_cov_pct}%). Unestimated items make capacity "
                  f"planning unreliable."),
            rec="Require estimates before any item moves to Active or Dev InProgress. Use the Unestimated Items view to track this each sprint."
        ))

    # Bug load vs enhancements
    if d["bug_total"] > d["enh_total"] * 1.5:
        findings.append(dict(
            level="MEDIUM", color="#D97706", bg="#FFFBEB",
            title="Bug Load Outpacing Enhancement Work",
            body=(f"Bugs ({d['bug_total']}) are {round(d['bug_total']/max(d['enh_total'],1), 1)}× "
                  f"the enhancement count ({d['enh_total']}). Sustained bug debt compresses "
                  f"feature delivery capacity."),
            rec="Review top bug sources. If the ratio exceeds 1.5× for two consecutive sprints, consider a dedicated bug-reduction sprint."
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

    enh_del_pct = _pct(d["enh_delivered"], d["enh_total"])
    bug_del_pct = _pct(d["bug_delivered"], d["bug_total"])
    scope_pct   = _pct(d["mid_sprint_n"],  d["total_n"])
    est_cov_pct = _pct(d["total_n"] - len(d["unest"]), d["total_n"])

    # ── KPI cards ────────────────────────────────────────────────────────────
    _, _, _, del_rag = _rag(enh_del_pct, 70, 40)
    _, _, _, bug_rag = _rag(bug_del_pct, 70, 50)
    _, _, _, sc_rag  = _rag(scope_pct,   15, 35, invert=True)
    _, _, _, est_rag = _rag(est_cov_pct, 80, 60)

    _c = lambda r: "#059669" if r=="GREEN" else "#D97706" if r=="AMBER" else "#DC2626"
    del_c, bug_c, sc_c, est_c = _c(del_rag), _c(bug_rag), _c(sc_rag), _c(est_rag)

    kpis_html = f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:32px;">
      {_kpi("Dev Delivery — Enhancements", f"{enh_del_pct}%",
            f"{d['enh_delivered']} of {d['enh_total']} handed to QA or closed", del_c)}
      {_kpi("Dev Delivery — Bugs", f"{bug_del_pct}%",
            f"{d['bug_delivered']} of {d['bug_total']} handed to QA or closed", bug_c)}
      {_kpi("Scope Creep", f"{scope_pct}%",
            f"{d['mid_sprint_n']} of {d['total_n']} items added mid-sprint", sc_c)}
      {_kpi("Estimation Coverage", f"{est_cov_pct}%",
            f"{d['total_n'] - len(d['unest'])} of {d['total_n']} items estimated", est_c)}
    </div>"""

    # ── Reopened alert strip ─────────────────────────────────────────────────
    reop_strip = ""
    if len(d["reopened"]) > 0:
        items_list = ", ".join(
            f'{_ado_link(r["work_item_id"])} {str(r["title"])[:40]}'
            for _, r in d["reopened"].head(5).iterrows()
        )
        if len(d["reopened"]) > 5:
            items_list += f" +{len(d['reopened'])-5} more"
        reop_strip = f"""
        <div style="background:#FEF2F2;border:1px solid #FECACA;border-left:4px solid #DC2626;
                    border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:20px;
                    display:flex;align-items:flex-start;gap:12px;">
          <span style="font-size:18px;flex-shrink:0;">⚠️</span>
          <div>
            <div style="font-size:13px;font-weight:700;color:#991B1B;margin-bottom:4px;">
              {len(d["reopened"])} Reopened Item(s) — Quality Regression Flag</div>
            <div style="font-size:12px;color:#7F1D1D;">{items_list}</div>
          </div>
        </div>"""

    # ── Sprint delivery table ────────────────────────────────────────────────
    def _delivery_row(label, total, delivered, dev_active, in_qa, planning, fully_done, color):
        if total == 0:
            return ""
        del_pct = _pct(delivered, total)
        bar = _progress_bar(del_pct, color)
        def _col(v, c="#374151", bold=False):
            fw = "font-weight:700;" if bold else ""
            return (f'<td style="padding:10px 14px;font-size:13px;color:{c};'
                    f'{fw}border-bottom:1px solid #F3F4F6;text-align:center;">{v}</td>')
        return (
            f'<tr style="background:#fff;">'
            f'<td style="padding:10px 14px;font-weight:600;color:#111827;font-size:13px;'
            f'border-bottom:1px solid #F3F4F6;">{label}</td>'
            + _col(total)
            + _col(fully_done, "#059669", bold=True)
            + _col(in_qa,      "#7C3AED")
            + _col(dev_active  - (1 if False else 0), "#2563EB")   # dev active
            + _col(planning,   "#9CA3AF")
            + f'<td style="padding:10px 20px;border-bottom:1px solid #F3F4F6;min-width:140px;">'
              f'<div style="display:flex;justify-content:space-between;'
              f'align-items:baseline;margin-bottom:2px;">'
              f'<span style="font-size:12px;color:{color};font-weight:700;">{del_pct}% dev delivered</span>'
              f'</div>{bar}</td>'
            f'</tr>'
        )

    delivery_table = f"""
    <div style="overflow-x:auto;border-radius:10px;border:1px solid #E5E7EB;margin-bottom:8px;">
    <table style="width:100%;border-collapse:collapse;">
    <thead><tr>
      {''.join(f'<th style="background:#1E3A5F;color:#fff;padding:10px 14px;text-align:{"left" if i==0 else "center"};font-size:11px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;white-space:nowrap;">{h}</th>'
               for i,h in enumerate(["Work Type","Total","Fully Closed","In QA","In Dev","Planning","Dev Delivery"]))}
    </tr></thead>
    <tbody>
      {_delivery_row("Enhancements", d["enh_total"], d["enh_delivered"],
                     d["enh_dev_active"], d["enh_qa"], d["enh_planning"],
                     d["enh_done"], "#2563EB")}
      {_delivery_row("Bugs & Issues", d["bug_total"], d["bug_delivered"],
                     d["bug_dev_active"], d["bug_qa"], d["bug_planning"],
                     d["bug_done"], "#DC2626")}
    </tbody></table></div>
    <p style="font-size:11px;color:#9CA3AF;margin-top:4px;">
      Dev Delivery = items in Dev Complete, Dev Review Completed, In QA (Tester Assigned / Watch List), or Fully Closed.
      Full closure occurs in the following iteration once QA is complete.
    </p>"""

    # Enhancement state detail
    enh_states = d["enhs"].groupby("state").size().reset_index(name="n").sort_values("n", ascending=False)
    enh_state_rows = []
    for _, row in enh_states.iterrows():
        st = row["state"]
        bucket = ("PLANNING" if st in _PLANNING else
                  "DEV ACTIVE" if st in _DEV_ACTIVE else
                  "DEV DONE" if st in _DEV_DONE else
                  "IN QA" if st in _QA_ACTIVE else
                  "CLOSED")
        bc = {"PLANNING": "#9CA3AF", "DEV ACTIVE": "#2563EB", "DEV DONE": "#7C3AED",
              "IN QA": "#D97706", "CLOSED": "#059669"}[bucket]
        flag = ' <span style="color:#DC2626;font-size:10px;font-weight:700;">⚠ REGRESSION</span>' if st == "Reopened" else ""
        enh_state_rows.append([
            st + flag,
            f'<span style="font-size:10px;color:{bc};font-weight:600;">{bucket}</span>',
            f"<strong>{row['n']}</strong>",
        ])
    delivery_detail = _table(["State", "Bucket", "Count"], enh_state_rows)

    delivery_content = f"""
    {reop_strip}
    {delivery_table}
    <details style="margin-top:8px;">
      <summary style="cursor:pointer;font-size:12px;color:#2563EB;font-weight:600;
                      padding:6px 0;user-select:none;">▸ Enhancement state breakdown</summary>
      <div style="margin-top:8px;">{delivery_detail}</div>
    </details>"""

    # ── Scope management ─────────────────────────────────────────────────────
    items_at_start = d["total_n"] - d["mid_sprint_n"]
    _, sc_bg, sc_tx, sc_lbl = _rag(scope_pct, 15, 35, invert=True)
    scope_badge = _badge(
        f"{scope_pct}% scope creep",
        "#DC2626" if sc_lbl=="RED" else "#D97706" if sc_lbl=="AMBER" else "#059669",
        sc_bg, sc_tx,
    )
    mid = d["items"][d["items"]["mid_sprint"]]
    mid_by_type = mid.groupby("work_item_type").size().reset_index(name="n")
    scope_content = f"""
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;">
      <div style="background:#F8FAFF;border:1px solid #E5E7EB;border-radius:10px;padding:16px 20px;">
        <div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">At Sprint Start</div>
        <div style="font-size:28px;font-weight:800;color:#111827;">{items_at_start}</div>
      </div>
      <div style="background:#F8FAFF;border:1px solid #E5E7EB;border-radius:10px;padding:16px 20px;">
        <div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Added Mid-Sprint</div>
        <div style="font-size:28px;font-weight:800;color:{'#DC2626' if scope_pct>35 else '#D97706' if scope_pct>15 else '#059669'};">{d["mid_sprint_n"]}</div>
      </div>
      <div style="background:#F8FAFF;border:1px solid #E5E7EB;border-radius:10px;padding:16px 20px;">
        <div style="font-size:11px;color:#9CA3AF;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Sprint Close Total</div>
        <div style="font-size:28px;font-weight:800;color:#111827;">{d["total_n"]}</div>
      </div>
    </div>
    <p style="font-size:13px;color:#374151;margin-bottom:12px;">
      {scope_badge}&nbsp; Items created after sprint day 3.
    </p>
    {_table(["Work Type","Mid-Sprint Count"],[[r["work_item_type"],str(r["n"])] for _,r in mid_by_type.iterrows()]) if len(mid_by_type) else ""}"""

    # ── Capacity — all work types ─────────────────────────────────────────────
    from config.dev_capacity import DEVELOPERS
    cap_rows = []
    for dev_cfg in DEVELOPERS:
        name  = dev_cfg["name"]
        cap   = dev_cfg["capacity_h"]
        hours = d["dev_cap"].get(name, {"task": 0.0, "bug": 0.0, "enh": 0.0})
        task_h = hours["task"]; bug_h = hours["bug"]; enh_h = hours["enh"]
        total_h = task_h + bug_h + enh_h
        alloc_pct = _pct(total_h, cap)
        ac = "#059669" if alloc_pct <= 80 else "#D97706" if alloc_pct <= 100 else "#DC2626"
        cap_rows.append([
            f"<strong>{name}</strong>",
            f"{cap:.0f}h",
            f"{task_h:.0f}h",
            f"{bug_h:.0f}h",
            f"{enh_h:.0f}h",
            f"<strong>{total_h:.0f}h</strong>",
            f'<span style="color:{ac};font-weight:700;">{alloc_pct}%</span>',
        ])
    capacity_content = (
        '<p style="font-size:13px;color:#374151;margin-bottom:12px;">'
        'Estimated hours from all sprint items (Tasks + Bugs + Enhancements) '
        'assigned to each developer. Capacity is 180h/month default.</p>'
        + _table(["Developer","Capacity","Tasks","Bugs","Enhancements","Total Est.","Allocation %"], cap_rows)
    )

    # ── Developer delivery ───────────────────────────────────────────────────
    dev_rows = []
    for _, row in d["dev_grp"].iterrows():
        if row["main_developer"] in ("Unassigned", "nan", ""):
            continue
        del_pct = _pct(int(row["dev_delivered"]), int(row["total"]))
        bar = _progress_bar(del_pct, "#2563EB")
        reop_flag = (f' <span style="color:#DC2626;font-size:10px;font-weight:700;">'
                     f'({int(row["reopened_n"])} reopened)</span>') if row["reopened_n"] > 0 else ""
        dev_rows.append([
            f"<strong>{row['main_developer']}</strong>{reop_flag}",
            str(int(row["total"])),
            f'<span style="color:#059669;font-weight:600;">{int(row["dev_delivered"])}</span>',
            f'<span style="color:#2563EB;">{int(row["dev_active"])}</span>',
            f'<span style="color:#7C3AED;">{int(row["in_qa"])}</span>',
            f'<span style="color:#9CA3AF;">{int(row["planning"])}</span>',
            f"{row['est_h']:.0f}h",
            f'<div style="min-width:100px;"><span style="font-size:11px;color:#6B7280;">'
            f'{del_pct}%</span>{bar}</div>',
        ])
    dev_content = (
        '<p style="font-size:13px;color:#374151;margin-bottom:12px;">'
        'Dev Delivered = items in Dev Complete, Dev Review Completed, In QA, or Closed.</p>'
        + _table(["Developer","Total","Dev Delivered","In Dev","In QA","Planning",
                  "Est. Hours","Dev Delivery"], dev_rows)
    )

    # ── P1/P2 bugs ───────────────────────────────────────────────────────────
    hi_rows = []
    for _, row in d["hi_prio_bugs"].sort_values(["priority","state"]).iterrows():
        delivered = row["is_dev_delivered"]
        s_color   = "#059669" if delivered else "#DC2626"
        p_color   = "#DC2626" if row["priority"] == 1 else "#D97706"
        status    = "DEV DELIVERED" if delivered else "OPEN — DEV PENDING"
        hi_rows.append([
            f'<span style="font-weight:700;color:{p_color};">P{int(row["priority"])}</span>',
            f'{_ado_link(row["work_item_id"])} <span style="font-size:12px;">{str(row["title"])[:72]}</span>',
            row["state"],
            row["main_developer"],
            f'<span style="color:{s_color};font-weight:600;font-size:11px;">{status}</span>',
        ])
    hiprio_content = (
        _table(["Priority","Title","State","Developer","Status"], hi_rows)
        if hi_rows else
        '<p style="color:#059669;font-size:13px;">No P1/P2 bugs in this sprint. ✓</p>'
    )

    # ── Estimation gaps ──────────────────────────────────────────────────────
    unest_rows = []
    for _, row in d["unest"].sort_values("main_developer").head(25).iterrows():
        unest_rows.append([
            row["work_item_type"],
            f'{_ado_link(row["work_item_id"])} <span style="font-size:12px;">{str(row["title"])[:68]}</span>',
            row["main_developer"],
            row["state"],
        ])
    est_content = (
        f'<p style="font-size:13px;color:#374151;margin-bottom:12px;">'
        f'{len(d["unest"])} item(s) have no estimate. '
        f'{"Showing top 25." if len(d["unest"]) > 25 else ""}</p>'
        + _table(["Type","Title","Developer","State"], unest_rows)
        if unest_rows else
        '<p style="color:#059669;font-size:13px;">All sprint items carry an estimate. ✓</p>'
    )

    # ── Carry-forward ────────────────────────────────────────────────────────
    carry_rows = []
    for _, row in d["carry"].sort_values(["main_developer","state"]).head(30).iterrows():
        bucket = ("DEV ACTIVE" if row["state"] in _DEV_ACTIVE else
                  "DEV DONE"   if row["state"] in _DEV_DONE else
                  "IN QA"      if row["state"] in _QA_ACTIVE else "PLANNING")
        bc = {"PLANNING":"#9CA3AF","DEV ACTIVE":"#2563EB","DEV DONE":"#7C3AED","IN QA":"#D97706"}[bucket]
        carry_rows.append([
            row["work_item_type"],
            f'{_ado_link(row["work_item_id"])} <span style="font-size:12px;">{str(row["title"])[:65]}</span>',
            f'<span style="color:{bc};font-size:10px;font-weight:600;">{bucket}</span>',
            row["state"],
            row["main_developer"],
            f'{row["original_estimate"]:.0f}h',
        ])
    carry_content = (
        f'<p style="font-size:13px;color:#374151;margin-bottom:8px;">'
        f'{len(d["carry"])} item(s) not yet fully closed — assigned to the '
        f'{d["month_name"]} sprint but will complete in the following iteration. '
        f'{"Showing top 30." if len(d["carry"]) > 30 else ""}</p>'
        f'<p style="font-size:11px;color:#9CA3AF;margin-bottom:12px;">'
        f'Note: items already moved to the next sprint iteration by the team are not shown here.</p>'
        + _table(["Type","Title","Dev Stage","State","Developer","Est."], carry_rows)
        if carry_rows else
        '<p style="color:#059669;font-size:13px;">All sprint items fully closed. ✓</p>'
    )

    # ── Findings ─────────────────────────────────────────────────────────────
    findings_html = ""
    for i, f in enumerate(_findings(d), 1):
        findings_html += f"""
        <div style="border-left:4px solid {f["color"]};background:{f["bg"]};
                    border-radius:0 10px 10px 0;padding:16px 20px;margin-bottom:14px;">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
            <span style="background:{f["color"]};color:#fff;border-radius:20px;
                         padding:2px 10px;font-size:10px;font-weight:700;
                         letter-spacing:0.05em;text-transform:uppercase;">{f["level"]}</span>
            <strong style="font-size:14px;color:#111827;">{i}. {f["title"]}</strong>
          </div>
          <p style="font-size:13px;color:#374151;margin-bottom:8px;line-height:1.6;">{f["body"]}</p>
          <div style="font-size:12px;font-weight:600;color:{f["color"]};">
            ▸ Recommendation: <span style="color:#374151;font-weight:400;">{f["rec"]}</span>
          </div>
        </div>"""

    # ── Full HTML ─────────────────────────────────────────────────────────────
    sprint_period = (
        f"{d['sprint_start'].strftime('%d %b').lstrip('0')} – "
        f"{d['sprint_end'].strftime('%d %b %Y').lstrip('0')}"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sprint Report — {d["month_name"]} | Expense On Demand</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
      background: #F9FAFB; color: #111827; font-size: 14px; line-height: 1.5;
      -webkit-print-color-adjust: exact; print-color-adjust: exact;
    }}
    .page {{ max-width: 1100px; margin: 0 auto; padding: 0 32px 60px; }}
    details summary::-webkit-details-marker {{ display: none; }}
    a {{ color: #2563EB; }}
    @media print {{
      body {{ background: #fff; }}
      .page {{ padding: 0 20px 40px; }}
    }}
  </style>
</head>
<body>
  <div style="background:linear-gradient(135deg,#1E3A5F 0%,#2563EB 100%);
              color:#fff;padding:48px 64px 40px;">
    <div style="max-width:1100px;margin:0 auto;">
      <div style="font-size:11px;font-weight:700;letter-spacing:3px;
                  text-transform:uppercase;opacity:0.7;margin-bottom:12px;">
        EXPENSE ON DEMAND · INTERNAL MANAGEMENT REPORT
      </div>
      <h1 style="font-size:36px;font-weight:800;margin-bottom:8px;line-height:1.1;">
        Sprint Iteration Report</h1>
      <div style="font-size:20px;opacity:0.85;font-weight:500;margin-bottom:32px;">
        {d["month_name"]}</div>
      <div style="display:flex;gap:48px;flex-wrap:wrap;border-top:1px solid rgba(255,255,255,0.2);
                  padding-top:24px;">
        <div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                          opacity:0.6;margin-bottom:4px;">Sprint Period</div>
             <div style="font-size:14px;font-weight:600;">{sprint_period}</div></div>
        <div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                          opacity:0.6;margin-bottom:4px;">Prepared</div>
             <div style="font-size:14px;font-weight:600;">{today}</div></div>
        <div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                          opacity:0.6;margin-bottom:4px;">Sprint Items (Enh + Bug)</div>
             <div style="font-size:14px;font-weight:600;">{d["total_n"]}</div></div>
        <div><div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;
                          opacity:0.6;margin-bottom:4px;">Classification</div>
             <div style="font-size:14px;font-weight:600;">INTERNAL — MANAGEMENT</div></div>
      </div>
    </div>
  </div>

  <div class="page">
    <div style="height:32px;"></div>
    {_section("Executive Summary", kpis_html, "📊")}
    {_section("Sprint Delivery", delivery_content, "📦")}
    {_section("Scope Management", scope_content, "🎯")}
    {_section("Capacity & Allocation (All Work)", capacity_content, "⚡")}
    {_section("Developer Delivery Breakdown", dev_content, "👥")}
    {_section("Priority Bug Status (P1 & P2)", hiprio_content, "🔴")}
    {_section("Estimation Compliance", est_content, "📏")}
    {_section("Carry-Forward Items", carry_content, "➜")}
    {_section("Key Findings & Recommendations", findings_html, "💡")}
    <div style="border-top:1px solid #E5E7EB;padding-top:20px;margin-top:40px;
                display:flex;justify-content:space-between;align-items:center;">
      <div style="font-size:11px;color:#9CA3AF;">
        Expense On Demand · Release Analytics · {d["month_name"]} Sprint Report</div>
      <div style="font-size:11px;color:#9CA3AF;">
        Generated {today} · INTERNAL — NOT FOR DISTRIBUTION</div>
    </div>
  </div>
</body>
</html>"""
