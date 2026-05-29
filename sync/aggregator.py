"""
sync/aggregator.py
──────────────────
Data pipeline aggregator — runs after each ADO sync.

Reads raw work_items_main (+ platform tables) and writes to the agg_* tables
defined in db/aggregations.py.  The UI reads only from agg_* tables;
no runtime computation happens at page-render time.

Public API
----------
  run_aggregations()   Build / refresh all aggregate tables. Called by run_sync().
"""
from __future__ import annotations

import calendar
import logging
import re
import time
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import text

from data.loader import engine
from config.team_mapping import TEAM_MAPPING

log = logging.getLogger(__name__)

# ── Shared constants ──────────────────────────────────────────────────────────

_BUG_TYPES    = {"Bug", "Bug_UI", "Bug_Text"}
_ITEM_TYPES   = {"Enhancement"} | _BUG_TYPES

_CLOSED_STATES = {
    "Closed", "Not an issue", "Not Required",
    "Userstory Update", "No Customer Response", "Resolved",
}
# States that mean "done, nothing left to plan"
_DONE_STATES = {"Done", "Watch List"} | _CLOSED_STATES

# States that are terminal for estimation purposes (different from done — On Hold still needs estimation)
_TERMINAL_EST = _CLOSED_STATES | {"Done"}

_ITER_RE = re.compile(r"Iteration 2026 (\d{2})-(\w+)")

_MONTH_NAMES = {
    1: "January", 2: "February",  3: "March",    4: "April",
    5: "May",     6: "June",      7: "July",      8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}
_MONTH_ABBR = {k: v[:3] for k, v in _MONTH_NAMES.items()}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _m0_month() -> int:
    """
    Return the month number that M0 refers to.
    M0 = current month, except after the last working day of the month
    where it flips to the next month.
    """
    today = date.today()
    y, m = today.year, today.month
    last_day = calendar.monthrange(y, m)[1]
    last_working = last_day
    while calendar.weekday(y, m, last_working) >= 5:
        last_working -= 1
    if today.day > last_working:
        return m % 12 + 1  # next month (wraps Dec→Jan)
    return m


def _month_key(month_num: int, m0: int) -> str:
    """Convert a month number to M0/M1/M2 or abbreviated month name."""
    delta = (month_num - m0) % 12
    if delta == 0:
        return "M0"
    if delta == 1:
        return "M1"
    if delta == 2:
        return "M2"
    return _MONTH_ABBR.get(month_num, str(month_num))


def _extract_month_num(iteration_path: str) -> int | None:
    m = _ITER_RE.search(str(iteration_path))
    return int(m.group(1)) if m else None


def _extract_month_label(iteration_path: str) -> str | None:
    m = _ITER_RE.search(str(iteration_path))
    return m.group(2) if m else None


def _parse_release_date(rd_str) -> date | None:
    """Parse free-text release_date ('2026 July', '2026-07-31', …) → date or None."""
    if not rd_str or str(rd_str).strip() in ("", "Not Specified", "nan", "None"):
        return None
    s = str(rd_str).strip()
    # "YYYY MonthName" → last day of that month
    m = re.match(r"^(\d{4})\s+([A-Za-z]+)$", s)
    if m:
        try:
            ts = pd.to_datetime(f"1 {m.group(2)} {m.group(1)}")
            last = calendar.monthrange(ts.year, ts.month)[1]
            return date(ts.year, ts.month, last)
        except Exception:
            pass
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def _working_days(year: int, month: int) -> int:
    """Count weekdays (Mon–Fri) in a given month."""
    return sum(
        1 for d in range(1, calendar.monthrange(year, month)[1] + 1)
        if calendar.weekday(year, month, d) < 5
    )


def _strip_dev(raw) -> str:
    """'First Last <email>' → 'First Last'"""
    return str(raw or "").split(" <")[0].strip()


# ── Table builders ────────────────────────────────────────────────────────────

def _build_item_month_keys(df: pd.DataFrame, conn, m0: int) -> int:
    rows = []
    for _, r in df[["work_item_id", "iteration_path"]].drop_duplicates("work_item_id").iterrows():
        ip  = str(r["iteration_path"] or "")
        mn  = _extract_month_num(ip)
        lbl = _extract_month_label(ip)
        rows.append({
            "work_item_id":   int(r["work_item_id"]),
            "iteration_path": ip,
            "month_num":      mn,
            "month_label":    lbl,
            "month_key":      _month_key(mn, m0) if mn else None,
            "ym_str":         f"2026-{mn:02d}" if mn else None,
            "is_2026":        mn is not None,
        })

    conn.execute(text("TRUNCATE agg_item_month_keys"))
    if rows:
        conn.execute(
            text("""
                INSERT INTO agg_item_month_keys
                    (work_item_id, iteration_path, month_num, month_label,
                     month_key, ym_str, is_2026, refreshed_at)
                VALUES
                    (:work_item_id, :iteration_path, :month_num, :month_label,
                     :month_key, :ym_str, :is_2026, NOW())
            """),
            rows,
        )
    return len(rows)


def _build_gantt_items(df: pd.DataFrame, conn, m0: int) -> int:
    items = df[
        df["work_item_type"].isin(_ITEM_TYPES) &
        (~df["state"].isin(_DONE_STATES)) &
        df["iteration_path"].str.contains(_ITER_RE.pattern, regex=True, na=False)
    ].copy()

    # Task rollup
    tasks = df[df["work_item_type"] == "Task"].copy()
    tasks["completed_work"]  = pd.to_numeric(tasks["completed_work"],  errors="coerce").fillna(0)
    tasks["remaining_work"]  = pd.to_numeric(tasks["remaining_work"],  errors="coerce").fillna(0)
    rollup = (
        tasks.groupby("parent_id")[["completed_work", "remaining_work"]]
        .sum()
        .rename(columns={"completed_work": "t_done", "remaining_work": "t_rem"})
    )
    items = items.join(rollup, on="work_item_id", how="left")
    items["t_done"] = items["t_done"].fillna(0)
    items["t_rem"]  = items["t_rem"].fillna(0)

    def _pct(r):
        total = r["t_done"] + r["t_rem"]
        if total > 0:
            return int(r["t_done"] / total * 100)
        cw = float(r.get("completed_work") or 0)
        rw = float(r.get("remaining_work") or 0)
        return int(cw / (cw + rw) * 100) if (cw + rw) > 0 else 0

    items["pct"] = items.apply(_pct, axis=1)
    items = items[items["pct"] < 100]
    items = items.drop_duplicates(subset="work_item_id")
    if items.empty:
        conn.execute(text("TRUNCATE agg_gantt_items"))
        return 0

    # Dates
    items["_end"] = items["release_date"].apply(_parse_release_date)
    items = items[items["_end"].notna()].copy()

    def _bar_start(r):
        ad = r.get("activated_date")
        if ad is not None and pd.notna(ad):
            return pd.Timestamp(ad).date()
        mn = _extract_month_num(str(r["iteration_path"]))
        return date(2026, mn, 1) if mn else date.today()

    items["_start"] = items.apply(_bar_start, axis=1)
    items = items[items.apply(lambda r: r["_start"] < r["_end"], axis=1)].copy()

    task_parent_ids = set(tasks["parent_id"].dropna().astype(int))

    rows = []
    for _, r in items.iterrows():
        mn = _extract_month_num(str(r["iteration_path"]))
        rows.append({
            "work_item_id":      int(r["work_item_id"]),
            "title":             str(r.get("title") or ""),
            "work_item_type":    str(r["work_item_type"]),
            "item_type":         "bug" if r["work_item_type"] in _BUG_TYPES else "enh",
            "state":             str(r.get("state") or ""),
            "iteration_path":    str(r.get("iteration_path") or ""),
            "month_num":         mn,
            "month_label":       _extract_month_label(str(r["iteration_path"])),
            "main_developer":    _strip_dev(r.get("main_developer")),
            "assigned_to":       _strip_dev(r.get("assigned_to")),
            "release_date":      r["_end"],
            "bar_start":         r["_start"],
            "bar_end":           r["_end"],
            "original_estimate": float(r.get("original_estimate") or 0),
            "t_done":            float(r["t_done"]),
            "t_rem":             float(r["t_rem"]),
            "pct":               int(r["pct"]),
            "has_tasks":         int(r["work_item_id"]) in task_parent_ids,
            "function":          str(r.get("function") or "").replace("Not Specified", "").strip(),
            "priority":          int(float(r.get("priority") or 4)) if r.get("priority") else 4,
            "customer_type":     str(r.get("type") or "") or None,
        })

    conn.execute(text("TRUNCATE agg_gantt_items"))
    if rows:
        conn.execute(
            text("""
                INSERT INTO agg_gantt_items
                    (work_item_id, title, work_item_type, item_type, state,
                     iteration_path, month_num, month_label, main_developer,
                     assigned_to, release_date, bar_start, bar_end,
                     original_estimate, t_done, t_rem, pct, has_tasks, function, priority,
                     customer_type, refreshed_at)
                VALUES
                    (:work_item_id, :title, :work_item_type, :item_type, :state,
                     :iteration_path, :month_num, :month_label, :main_developer,
                     :assigned_to, :release_date, :bar_start, :bar_end,
                     :original_estimate, :t_done, :t_rem, :pct, :has_tasks, :function, :priority,
                     :customer_type, NOW())
            """),
            rows,
        )
    return len(rows)


def _build_gantt_tasks(df: pd.DataFrame, conn) -> int:
    # Parent release dates for task bar_end fallback
    parent_ends: dict[int, date] = {}
    for _, r in df[df["work_item_type"].isin(_ITEM_TYPES)].iterrows():
        d = _parse_release_date(r.get("release_date"))
        if d:
            parent_ends[int(r["work_item_id"])] = d

    tasks = df[
        (df["work_item_type"] == "Task") &
        df["parent_id"].notna()
    ].copy()
    tasks["completed_work"] = pd.to_numeric(tasks["completed_work"], errors="coerce").fillna(0)
    tasks["remaining_work"] = pd.to_numeric(tasks["remaining_work"], errors="coerce").fillna(0)

    rows = []
    for _, r in tasks.iterrows():
        try:
            pid = int(r["parent_id"])
        except (TypeError, ValueError):
            continue
        if pid not in parent_ends:
            continue

        state   = str(r.get("state") or "To Do")
        done    = float(r["completed_work"])
        rem     = float(r["remaining_work"])
        total_t = done + rem
        pct     = int(done / total_t * 100) if total_t > 0 else (
                  100 if state in ("Done", "Closed") else 0)

        ad      = r.get("activated_date")
        t_start = pd.Timestamp(ad).date() if (ad is not None and pd.notna(ad)) else None
        if t_start is None:
            mn = _extract_month_num(str(r.get("iteration_path", "")))
            t_start = date(2026, mn, 1) if mn else (parent_ends[pid] - pd.Timedelta(days=30))

        cd    = r.get("closed_date")
        t_end = (pd.Timestamp(cd).date()
                 if state in ("Done", "Closed") and cd is not None and pd.notna(cd)
                 else parent_ends[pid])

        if t_start >= t_end:
            continue

        rows.append({
            "task_id":        int(r["work_item_id"]),
            "parent_id":      pid,
            "title":          str(r.get("title") or ""),
            "state":          state,
            "pct":            pct,
            "bar_start":      t_start,
            "bar_end":        t_end,
            "completed_work": done,
            "remaining_work": rem,
        })

    conn.execute(text("TRUNCATE agg_gantt_tasks"))
    if rows:
        conn.execute(
            text("""
                INSERT INTO agg_gantt_tasks
                    (task_id, parent_id, title, state, pct,
                     bar_start, bar_end, completed_work, remaining_work, refreshed_at)
                VALUES
                    (:task_id, :parent_id, :title, :state, :pct,
                     :bar_start, :bar_end, :completed_work, :remaining_work, NOW())
            """),
            rows,
        )
    return len(rows)


def _build_story_estimation(df: pd.DataFrame, conn, m0: int) -> int:
    enhs = df[
        df["work_item_type"].isin(_ITEM_TYPES) &
        (~df["state"].isin(_CLOSED_STATES)) &
        df["iteration_path"].str.contains(_ITER_RE.pattern, regex=True, na=False)
    ].copy()

    tasks = df[df["work_item_type"] == "Task"].copy()
    tasks["original_estimate"] = pd.to_numeric(tasks["original_estimate"], errors="coerce").fillna(0)
    task_groups = (
        tasks.groupby("parent_id")
        .agg(
            task_count        =("work_item_id",      "count"),
            task_missing_count=("original_estimate", lambda x: (x == 0).sum()),
            task_est_sum      =("original_estimate", "sum"),
        )
        .reset_index()
    )
    enhs = enhs.merge(task_groups, left_on="work_item_id", right_on="parent_id", how="left")
    enhs["task_count"]         = enhs["task_count"].fillna(0).astype(int)
    enhs["task_missing_count"] = enhs["task_missing_count"].fillna(0).astype(int)
    enhs["task_est_sum"]       = enhs["task_est_sum"].fillna(0)

    def _est_status(r) -> str:
        if float(r.get("original_estimate") or 0) > 0:
            return "estimated"
        tc = int(r["task_count"])
        tm = int(r["task_missing_count"])
        if tc > 0 and tm == 0:
            return "estimated_via_tasks"
        if tc > 0 and tm < tc:
            return "partial"
        return "unestimated"

    enhs["est_status"] = enhs.apply(_est_status, axis=1)

    rows = []
    for _, r in enhs.iterrows():
        mn = _extract_month_num(str(r["iteration_path"]))
        try:
            pri = int(float(r.get("priority") or 4))
        except (TypeError, ValueError):
            pri = 4
        dev = _strip_dev(r.get("main_developer"))
        rows.append({
            "work_item_id":        int(r["work_item_id"]),
            "title":               str(r.get("title") or ""),
            "work_item_type":      str(r["work_item_type"]),
            "state":               str(r.get("state") or ""),
            "iteration_path":      str(r.get("iteration_path") or ""),
            "month_key":           _month_key(mn, m0) if mn else None,
            "main_developer":      dev,
            "story_owner":         str(r.get("story_owner") or ""),
            "original_estimate":   float(r.get("original_estimate") or 0),
            "priority":            pri,
            "function":            str(r.get("function") or "").replace("Not Specified", "").strip(),
            "team":                TEAM_MAPPING.get(dev, ""),
            "task_count":          int(r["task_count"]),
            "task_missing_count":  int(r["task_missing_count"]),
            "task_est_sum":        float(r["task_est_sum"]),
            "est_status":          r["est_status"],
        })

    conn.execute(text("TRUNCATE agg_story_estimation"))
    if rows:
        conn.execute(
            text("""
                INSERT INTO agg_story_estimation
                    (work_item_id, title, work_item_type, state, iteration_path,
                     month_key, main_developer, story_owner, original_estimate,
                     priority, function, team, task_count, task_missing_count, task_est_sum,
                     est_status, refreshed_at)
                VALUES
                    (:work_item_id, :title, :work_item_type, :state, :iteration_path,
                     :month_key, :main_developer, :story_owner, :original_estimate,
                     :priority, :function, :team, :task_count, :task_missing_count, :task_est_sum,
                     :est_status, NOW())
            """),
            rows,
        )
    return len(rows)


def _build_dev_monthly_capacity(df: pd.DataFrame, conn, m0: int) -> int:
    cap = df[
        df["work_item_type"].isin(_ITEM_TYPES) &
        df["iteration_path"].str.contains(_ITER_RE.pattern, regex=True, na=False)
    ].copy()

    cap["_dev"] = cap["main_developer"].apply(_strip_dev)
    cap["_mn"]  = cap["iteration_path"].apply(_extract_month_num)
    cap = cap[cap["_mn"].notna() & (cap["_dev"] != "")].copy()
    cap["_ym"]  = cap["_mn"].apply(lambda n: f"2026-{int(n):02d}")

    def _bucket(r):
        if r["state"] == "Watch List":
            return "watchlist"
        if r["work_item_type"] in _BUG_TYPES:
            return "bug"
        return "enhancement"

    cap["_bucket"] = cap.apply(_bucket, axis=1)
    cap["original_estimate"] = pd.to_numeric(cap["original_estimate"], errors="coerce").fillna(0)

    # Task rollup: if an item has tasks, use sum of task estimates instead of story estimate
    tasks = df[df["work_item_type"] == "Task"].copy()
    tasks["_pid"] = pd.to_numeric(tasks["parent_id"], errors="coerce")
    tasks = tasks[tasks["_pid"].notna()].copy()
    tasks["_pid"] = tasks["_pid"].astype(int)
    tasks["original_estimate"] = pd.to_numeric(tasks["original_estimate"], errors="coerce").fillna(0)
    task_rollup: dict[int, float] = tasks.groupby("_pid")["original_estimate"].sum().to_dict()

    cap["_eff_h"] = cap.apply(
        lambda r: float(task_rollup.get(int(r["work_item_id"]), 0)) or float(r["original_estimate"]),
        axis=1,
    )

    grouped = (
        cap.groupby(["_dev", "_ym", "_mn", "_bucket"])
        .agg(item_count=("work_item_id", "count"), estimated_hours=("_eff_h", "sum"))
        .reset_index()
    )

    # Working days cache
    wd_cache: dict[str, int] = {}
    def _wd(ym: str) -> int:
        if ym not in wd_cache:
            y, mo = int(ym[:4]), int(ym[5:])
            wd_cache[ym] = _working_days(y, mo)
        return wd_cache[ym]

    rows = []
    for _, r in grouped.iterrows():
        mn   = int(r["_mn"])
        ym   = str(r["_ym"])
        wd   = _wd(ym)
        rows.append({
            "main_developer":  str(r["_dev"]),
            "ym_str":          ym,
            "month_key":       _month_key(mn, m0),
            "item_type":       str(r["_bucket"]),
            "item_count":      int(r["item_count"]),
            "estimated_hours": float(r["estimated_hours"]),
            "working_days":    wd,
            "capacity_hours":  wd * 9.0,
        })

    conn.execute(text("TRUNCATE agg_dev_monthly_capacity"))
    if rows:
        conn.execute(
            text("""
                INSERT INTO agg_dev_monthly_capacity
                    (main_developer, ym_str, month_key, item_type,
                     item_count, estimated_hours, working_days, capacity_hours, refreshed_at)
                VALUES
                    (:main_developer, :ym_str, :month_key, :item_type,
                     :item_count, :estimated_hours, :working_days, :capacity_hours, NOW())
            """),
            rows,
        )
    return len(rows)


def _build_sprint_daily_activity(conn) -> int:
    today   = date.today()
    ym_str  = today.strftime("%Y-%m")
    month   = today.month
    year    = today.year

    # Load sprint history for current month
    with engine.connect() as rc:
        history = pd.read_sql(
            text("""
                SELECT work_item_id, added_to_iteration_at
                FROM p_sprint_item_history
                WHERE EXTRACT(MONTH FROM added_to_iteration_at::timestamptz) = :m
                  AND EXTRACT(YEAR  FROM added_to_iteration_at::timestamptz) = :y
            """),
            rc, params={"m": month, "y": year},
        )
        closed_df = pd.read_sql(
            text("""
                SELECT closed_date
                FROM work_items_main
                WHERE closed_date IS NOT NULL AND closed_date <> ''
                  AND EXTRACT(MONTH FROM closed_date::timestamptz) = :m
                  AND EXTRACT(YEAR  FROM closed_date::timestamptz) = :y
            """),
            rc, params={"m": month, "y": year},
        )

    history["added_to_iteration_at"] = pd.to_datetime(
        history["added_to_iteration_at"], errors="coerce"
    )
    added_by_day: dict[date, int] = {}
    for _, r in history.iterrows():
        if pd.notna(r["added_to_iteration_at"]):
            d = r["added_to_iteration_at"].date()
            added_by_day[d] = added_by_day.get(d, 0) + 1

    closed_df["closed_date"] = pd.to_datetime(closed_df["closed_date"], errors="coerce")
    closed_by_day: dict[date, int] = {}
    for _, r in closed_df.iterrows():
        if pd.notna(r["closed_date"]):
            d = r["closed_date"].date()
            closed_by_day[d] = closed_by_day.get(d, 0) + 1

    days  = pd.date_range(date(year, month, 1), today, freq="D")
    rows  = []
    for d in days:
        d_date = d.date()
        added  = added_by_day.get(d_date, 0)
        closed = closed_by_day.get(d_date, 0)
        rows.append({
            "ym_str":       ym_str,
            "day_date":     d_date,
            "added_count":  added,
            "closed_count": closed,
            "net_change":   added - closed,
        })

    # Only delete this month's rows (keep history for other months)
    conn.execute(text("DELETE FROM agg_sprint_daily_activity WHERE ym_str = :ym"), {"ym": ym_str})
    if rows:
        conn.execute(
            text("""
                INSERT INTO agg_sprint_daily_activity
                    (ym_str, day_date, added_count, closed_count, net_change, refreshed_at)
                VALUES
                    (:ym_str, :day_date, :added_count, :closed_count, :net_change, NOW())
            """),
            rows,
        )
    return len(rows)


def _build_standalone_overhead(conn) -> int:
    with engine.connect() as rc:
        df = pd.read_sql(
            text("""
                SELECT
                    stc.task_id,
                    stc.category,
                    wi.assigned_to,
                    wi.iteration_path,
                    COALESCE(wi.original_estimate, 0) AS original_estimate
                FROM standalone_task_classifications stc
                JOIN work_items_main wi ON wi.work_item_id = stc.task_id
                WHERE wi.iteration_path IS NOT NULL
            """),
            rc,
        )

    if df.empty:
        conn.execute(text("TRUNCATE agg_standalone_overhead"))
        return 0

    df["_mn"]  = df["iteration_path"].apply(_extract_month_num)
    df["_ym"]  = df["_mn"].apply(lambda n: f"2026-{int(n):02d}" if pd.notna(n) else None)
    df["assigned_to"] = df["assigned_to"].apply(_strip_dev)
    df["original_estimate"] = pd.to_numeric(df["original_estimate"], errors="coerce").fillna(0)
    df = df[df["_ym"].notna() & (df["assigned_to"] != "")].copy()

    grouped = (
        df.groupby(["assigned_to", "_ym", "category"])
        .agg(total_hours=("original_estimate", "sum"), task_count=("task_id", "count"))
        .reset_index()
    )

    rows = [
        {
            "assigned_to": str(r["assigned_to"]),
            "ym_str":      str(r["_ym"]),
            "category":    str(r["category"]),
            "total_hours": float(r["total_hours"]),
            "task_count":  int(r["task_count"]),
        }
        for _, r in grouped.iterrows()
    ]

    conn.execute(text("TRUNCATE agg_standalone_overhead"))
    if rows:
        conn.execute(
            text("""
                INSERT INTO agg_standalone_overhead
                    (assigned_to, ym_str, category, total_hours, task_count, refreshed_at)
                VALUES
                    (:assigned_to, :ym_str, :category, :total_hours, :task_count, NOW())
            """),
            rows,
        )
    return len(rows)


# ── Public entry point ────────────────────────────────────────────────────────

def _build_qa_rework(conn) -> int:
    """
    Compute per-story QA rework cycles from item_state_history.

    A rework = transition where from_state is a QA/testing state and
    to_state is a dev state (story sent back from QA to dev).

    Writes to agg_qa_rework — one row per work_item_id with:
      rework_cycles, first_qa_at, last_rework_at, iteration_path
    """
    conn.execute(text("CREATE TABLE IF NOT EXISTS agg_qa_rework ("
        "work_item_id   INTEGER PRIMARY KEY, "
        "iteration_path TEXT, "
        "rework_cycles  INTEGER NOT NULL DEFAULT 0, "
        "first_qa_at    TIMESTAMPTZ, "
        "last_rework_at TIMESTAMPTZ, "
        "updated_at     TIMESTAMPTZ DEFAULT NOW()"
        ")"))

    conn.execute(text("TRUNCATE agg_qa_rework"))

    # Rows from item_state_history where story moved back from QA → Dev
    result = conn.execute(text("""
        WITH rework AS (
            SELECT
                ish.work_item_id,
                COUNT(*) FILTER (
                    WHERE ish.from_state IN (
                        'Dev Complete', 'Tester Assigned', 'Dev Review Completed'
                    )
                    AND ish.to_state IN (
                        'Active', 'Dev InProgress', 'Dev Review', 'Estimated',
                        'Clarification'
                    )
                ) AS rework_cycles,
                MIN(ish.changed_at) FILTER (
                    WHERE ish.to_state IN (
                        'Dev Complete', 'Tester Assigned', 'Dev Review Completed'
                    )
                ) AS first_qa_at,
                MAX(ish.changed_at) FILTER (
                    WHERE ish.from_state IN (
                        'Dev Complete', 'Tester Assigned', 'Dev Review Completed'
                    )
                    AND ish.to_state IN (
                        'Active', 'Dev InProgress', 'Dev Review', 'Estimated',
                        'Clarification'
                    )
                ) AS last_rework_at,
                wim.iteration_path
            FROM item_state_history ish
            JOIN work_items_main wim USING (work_item_id)
            WHERE wim.work_item_type IN ('Enhancement', 'User Story', 'Bug', 'Bug_UI', 'Bug_Text')
            GROUP BY ish.work_item_id, wim.iteration_path
        )
        INSERT INTO agg_qa_rework
            (work_item_id, iteration_path, rework_cycles, first_qa_at, last_rework_at)
        SELECT work_item_id, iteration_path, rework_cycles, first_qa_at, last_rework_at
        FROM rework
        WHERE rework_cycles > 0
    """))
    return result.rowcount


def run_aggregations() -> None:
    """
    Rebuild all aggregate tables from current raw data.
    Called by run_sync() after each successful ADO sync.
    Failures are non-fatal — logged as warnings so sync still completes.
    """
    t0  = time.time()
    m0  = _m0_month()
    log.info("▶ Aggregator started (M0 = month %d)", m0)

    # Load the full working dataset once — shared across all builders
    with engine.connect() as rc:
        df = pd.read_sql(
            text("""
                SELECT work_item_id, title, work_item_type, state, priority,
                       created_date, closed_date, activated_date,
                       assigned_to, main_developer, story_owner,
                       iteration_path, release_date, function,
                       original_estimate, completed_work, remaining_work,
                       parent_id
                FROM work_items_main
                WHERE created_date >= '2025-01-01'
                   OR closed_date  >= '2025-01-01'
                   OR changed_date >= '2025-01-01'
                   OR (created_date < '2025-01-01'
                       AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
            """),
            rc,
        )

    # Normalise types once
    df["state"]            = df["state"].fillna("").astype(str).str.strip()
    df["iteration_path"]   = df["iteration_path"].fillna("").astype(str).str.strip()
    df["work_item_type"]   = df["work_item_type"].fillna("").astype(str).str.strip()
    df["function"]         = df["function"].fillna("").astype(str).str.strip()
    df["original_estimate"]= pd.to_numeric(df["original_estimate"], errors="coerce").fillna(0)
    df["completed_work"]   = pd.to_numeric(df["completed_work"],    errors="coerce").fillna(0)
    df["remaining_work"]   = pd.to_numeric(df["remaining_work"],    errors="coerce").fillna(0)
    for col in ("created_date", "closed_date", "activated_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce")

    results: dict[str, int] = {}

    with engine.begin() as conn:
        steps = [
            ("item_month_keys",      lambda: _build_item_month_keys(df, conn, m0)),
            ("gantt_items",          lambda: _build_gantt_items(df, conn, m0)),
            ("gantt_tasks",          lambda: _build_gantt_tasks(df, conn)),
            ("story_estimation",     lambda: _build_story_estimation(df, conn, m0)),
            ("dev_monthly_capacity", lambda: _build_dev_monthly_capacity(df, conn, m0)),
            ("standalone_overhead",  lambda: _build_standalone_overhead(conn)),
            ("qa_rework",            lambda: _build_qa_rework(conn)),
        ]
        for name, fn in steps:
            try:
                with conn.begin_nested():
                    results[name] = fn()
            except Exception as exc:
                log.warning("Aggregator step '%s' failed (non-fatal): %s", name, exc)
                results[name] = -1

    # Sprint daily activity uses its own connection internally
    try:
        with engine.begin() as conn:
            results["sprint_daily_activity"] = _build_sprint_daily_activity(conn)
    except Exception as exc:
        log.warning("Aggregator step 'sprint_daily_activity' failed (non-fatal): %s", exc)
        results["sprint_daily_activity"] = -1

    elapsed = round(time.time() - t0, 2)
    summary = ", ".join(f"{k}={v}" for k, v in results.items())
    log.info("✅ Aggregator complete in %ss — %s", elapsed, summary)
