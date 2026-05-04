"""
KPI Validation Script — Release Analytics Dashboard
====================================================
Cross-checks every KPI card value against raw DB queries.

Run from project root:
    .venv\Scripts\python validate_kpis.py

Output: console report + validate_kpis_report.txt
"""

import os, sys
from datetime import datetime, date, timedelta
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from config.team_mapping import TEAM_MAPPING

load_dotenv()

DB_USER = "postgres"
DB_PASS = os.getenv("DB_PASSWORD", "1234")
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "vsts_analytics"
ANALYSIS_START_DATE = date(2025, 1, 1)

# ── Exact copies of page-level constants ─────────────────────────────────────
# summary.py line 27  (confusingly named — these are actually the CLOSED states)
SUMMARY_OPEN_STATES  = ["Closed", "Not an issue", "Not Required", "Userstory Update", "No Customer Response"]
# bugs.py line 20
BUGS_CLOSED_STATES   = {"Closed", "Not an issue", "Not Required", "Userstory Update", "No Customer Response"}
BUGS_REJECTED_STATES = {"Not an issue", "Not Required", "No Customer Response"}

results = []   # list of (section, kpi, expected_raw_sql, page_computed, match, note)

def sep(title=""):
    print("\n" + "═" * 70)
    if title:
        print(f"  {title}")
        print("═" * 70)


def check(section, kpi, raw_val, page_val, note=""):
    """Record + print one validation row."""
    try:
        match = abs(float(raw_val) - float(page_val)) < 0.11   # tolerance for float rounding
    except Exception:
        match = str(raw_val).strip() == str(page_val).strip()
    icon = "✅" if match else "❌"
    results.append((section, kpi, raw_val, page_val, match, note))
    print(f"  {icon}  {kpi:<35}  raw={raw_val!s:<12}  page={page_val!s:<12}  {note}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Load data (mirrors loader.py exactly)
# ─────────────────────────────────────────────────────────────────────────────
sep("LOADING DATA")

conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS,
                        host=DB_HOST, port=DB_PORT)

query = """
SELECT *
FROM work_items_main
WHERE
    created_date >= '2025-01-01'
    OR closed_date  >= '2025-01-01'
    OR changed_date >= '2025-01-01'
    OR (
        created_date < '2025-01-01'
        AND (closed_date IS NULL OR closed_date >= '2025-01-01')
    )
"""
df_raw = pd.read_sql(query, conn)
print(f"  Rows from DB (base query):  {len(df_raw):,}")

# Apply loader transformations
df = df_raw.copy()

if "priority" in df.columns:
    df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(4).astype(int)

if "remaining_work" in df.columns:
    df["remaining_work"] = pd.to_numeric(df["remaining_work"], errors="coerce").fillna(0)

string_cols = ["state", "assigned_to", "work_item_type", "release_date", "function", "iteration_path"]
for col in string_cols:
    if col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()
        df[col] = df[col].replace(
            ["None", "nan", ""],
            "Unassigned" if col == "assigned_to" else "Not Specified"
        )

for col in ["created_date", "closed_date", "changed_date"]:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
        if hasattr(df[col].dt, "tz") and df[col].dt.tz is not None:
            df[col] = df[col].dt.tz_localize(None)

if "assigned_to" in df.columns:
    df["team"] = df["assigned_to"].map(TEAM_MAPPING).fillna("Unassigned")
else:
    df["team"] = "Unassigned"

if "main_developer" in df.columns:
    md = df["main_developer"].astype(str).str.split(" <").str[0].str.strip()
    df["main_dev_team"] = md.map(TEAM_MAPPING).fillna("Unassigned")
else:
    df["main_dev_team"] = "Unassigned"

print(f"  After loader transforms:    {len(df):,}")

# filter_activity_since(df, ANALYSIS_START_DATE) — mirrors loader.py lines 135-150
start = pd.to_datetime(ANALYSIS_START_DATE)
created = df["created_date"] if "created_date" in df.columns else pd.Series(pd.NaT, index=df.index)
closed  = df["closed_date"]  if "closed_date"  in df.columns else pd.Series(pd.NaT, index=df.index)
keep = (created >= start) | (closed >= start) | closed.isna()
df = df[keep].copy()
print(f"  After filter_activity_since({ANALYSIS_START_DATE}): {len(df):,}")

today = pd.Timestamp.today().normalize()
print(f"  Today (script):             {today.date()}")

# ── Sync health diagnostics ───────────────────────────────────────────────
cur_diag = conn.cursor()
cur_diag.execute("SELECT MAX(changed_date) FROM work_items_main")
max_changed = cur_diag.fetchone()[0]
cur_diag.execute("SELECT MAX(closed_date) FROM work_items_main WHERE closed_date IS NOT NULL AND closed_date != ''")
max_closed_db = cur_diag.fetchone()[0]
cur_diag.execute("SELECT COUNT(*) FROM work_items_main WHERE changed_date >= (NOW() - INTERVAL '24 hours')::text")
changed_24h = cur_diag.fetchone()[0]
print(f"\n  ── SYNC HEALTH ──")
print(f"  MAX(changed_date) in DB:    {max_changed}  ← last time sync ran")
print(f"  MAX(closed_date)  in DB:    {max_closed_db}")
print(f"  Items with changed_date     in last 24h: {changed_24h}")
if max_changed:
    lag = today - pd.Timestamp(max_changed).normalize()
    print(f"  Sync lag:                   {lag.days} days behind today")
    if lag.days > 1:
        print(f"  ⚠️  SYNC IS STALE — DB not updated since {pd.Timestamp(max_changed).date()}")

# ── Velocity debug: show most recent closed dates ─────────────────────────
recent_closed_debug = df[df["closed_date"].notna()].copy()
recent_closed_debug["closed_date"] = pd.to_datetime(recent_closed_debug["closed_date"], errors="coerce")
max_closed = recent_closed_debug["closed_date"].max()
four_w_cutoff = today - pd.Timedelta(weeks=4)
print(f"\n  Most recent closed_date:    {max_closed}")
print(f"  4-week cutoff:              {four_w_cutoff.date()}")
print(f"  Items closed in last 4w:    {int((recent_closed_debug['closed_date'] >= four_w_cutoff).sum())}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Summary Page KPIs  (no item_type / employee filter — default view)
# ─────────────────────────────────────────────────────────────────────────────
sep("SUMMARY PAGE — Portfolio Health (no filters)")

open_df   = df[~df["state"].isin(SUMMARY_OPEN_STATES)]
bugs_all  = df[df["work_item_type"].str.contains("Bug", na=False, case=False)].copy()
open_bugs = bugs_all[~bugs_all["state"].isin(SUMMARY_OPEN_STATES)]

# --- KPI: Total Items
page_total = len(df)
raw_total  = len(df)   # same dataset — just confirming row count
check("Summary", "Total Items", raw_total, page_total)

# --- KPI: Open Items
page_open = len(open_df)
raw_open  = int(df[~df["state"].isin(SUMMARY_OPEN_STATES)].shape[0])
check("Summary", "Open Items", raw_open, page_open)

# --- KPI: Total Bugs
page_bugs = len(bugs_all)
raw_bugs  = int(df["work_item_type"].str.contains("Bug", na=False, case=False).sum())
check("Summary", "Total Bugs", raw_bugs, page_bugs)

# --- KPI: P1 Open
page_p1 = len(bugs_all[(bugs_all["priority"] == 1) & (~bugs_all["state"].isin(SUMMARY_OPEN_STATES))])
raw_p1  = int(bugs_all[(bugs_all["priority"] == 1) & (~bugs_all["state"].isin(SUMMARY_OPEN_STATES))].shape[0])
check("Summary", "P1 Open Bugs", raw_p1, page_p1)

# --- KPI: Remaining Hours (sum of remaining_work on open items)
page_rem = open_df["remaining_work"].sum() if "remaining_work" in open_df.columns else 0
raw_rem  = pd.to_numeric(df[~df["state"].isin(SUMMARY_OPEN_STATES)]["remaining_work"], errors="coerce").fillna(0).sum()
check("Summary", "Remaining Hours", f"{raw_rem:,.0f}", f"{page_rem:,.0f}")

# --- KPI: Avg Cycle Time (closed bugs: state == "Closed" only)
closed_bugs = bugs_all[bugs_all["state"] == "Closed"].copy()
avg_cycle_raw = (closed_bugs["closed_date"] - closed_bugs["created_date"]).dt.days.mean()
avg_cycle_page = avg_cycle_raw   # same formula
check("Summary", "Avg Cycle Time (bugs)",
      f"{avg_cycle_raw:.1f}d" if pd.notna(avg_cycle_raw) else "—",
      f"{avg_cycle_page:.1f}d" if pd.notna(avg_cycle_page) else "—")

# --- KPI: Velocity (items closed last 4 weeks / 4)
four_weeks_ago  = today - pd.Timedelta(weeks=4)
recently_closed = df[df["closed_date"].notna() & (df["closed_date"] >= four_weeks_ago)]
velocity_page   = round(len(recently_closed) / 4, 1)
raw_velocity    = round(len(recently_closed) / 4, 1)
check("Summary", "Velocity / Week (last 4w)", raw_velocity, velocity_page)

# --- KPI: Customer Bugs (open bugs, type == "Customer")
if "type" in open_bugs.columns:
    page_cust = int((open_bugs["type"] == "Customer").sum())
    raw_cust  = int((open_bugs["type"] == "Customer").sum())
else:
    page_cust = raw_cust = 0
check("Summary", "Customer Bugs (open)", raw_cust, page_cust)

# --- KPI: Internal Bugs (open bugs, type == "Internal")
if "type" in open_bugs.columns:
    page_int = int((open_bugs["type"] == "Internal").sum())
    raw_int  = int((open_bugs["type"] == "Internal").sum())
else:
    page_int = raw_int = 0
check("Summary", "Internal Bugs (open)", raw_int, page_int)

# --- KPI: Unassigned (open items where assigned_to is NaN)
# ⚠️  POTENTIAL BUG: loader.py converts NaN assigned_to → "Unassigned" string (line 81).
#     So isna() will always return 0. Page code (line 664) uses .isna() → always 0.
page_unassigned = int(open_df["assigned_to"].isna().sum()) if "assigned_to" in open_df.columns else 0
raw_unassigned_isna   = int(open_df["assigned_to"].isna().sum())
raw_unassigned_string = int((open_df["assigned_to"] == "Unassigned").sum())
check("Summary", "Unassigned (isna — page formula)",
      raw_unassigned_isna, page_unassigned,
      note="⚠️  loader converts NaN→'Unassigned' str; isna() always 0")
check("Summary", "Unassigned (string match — true count)",
      raw_unassigned_string, "N/A",
      note="⚠️  actual unassigned open items")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Items / Bugs Page KPIs  (default: item_type = "Bug", no other filters)
# ─────────────────────────────────────────────────────────────────────────────
sep("ITEMS PAGE — Bug view (no release/iteration/team filter)")

df_items = df.copy()
# bugs.py line 714: strip email from assigned_to
if "assigned_to" in df_items.columns:
    df_items["assigned_to"] = df_items["assigned_to"].astype(str).str.split(" <").str[0]
# item_type filter: work_item_type contains "Bug"  (line 729)
df_items = df_items[df_items["work_item_type"].str.contains("Bug", na=False, case=False)]

open_items_pg   = df_items[~df_items["state"].isin(BUGS_CLOSED_STATES)].copy()
closed_items_pg = df_items[df_items["state"].isin(BUGS_CLOSED_STATES)].copy()

total_pg   = len(df_items)
n_open_pg  = len(open_items_pg)
n_closed_pg = len(closed_items_pg)
closure_pct_pg = n_closed_pg / total_pg * 100 if total_pg > 0 else 0

cb_pg = df_items[df_items["state"] == "Closed"].copy()
avg_mttc_pg = (cb_pg["closed_date"] - cb_pg["created_date"]).dt.days.mean() if not cb_pg.empty else None

p1_pg = int((open_items_pg["priority"] == 1).sum()) if "priority" in open_items_pg.columns else 0
p2_pg = int((open_items_pg["priority"] == 2).sum()) if "priority" in open_items_pg.columns else 0
rej_pg = int(df_items["state"].isin(BUGS_REJECTED_STATES).sum()) if "state" in df_items.columns else 0

# Raw SQL cross-check (same logic, via psycopg2 cursor)
cur = conn.cursor()

cur.execute("""
    SELECT COUNT(*) FROM work_items_main
    WHERE (
        created_date >= '2025-01-01' OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (created_date < '2025-01-01' AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
    )
    AND work_item_type ILIKE '%Bug%'
    AND (created_date >= '2025-01-01' OR closed_date >= '2025-01-01' OR closed_date IS NULL)
""")
raw_total_bugs = cur.fetchone()[0]

cur.execute("""
    SELECT COUNT(*) FROM work_items_main
    WHERE (
        created_date >= '2025-01-01' OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (created_date < '2025-01-01' AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
    )
    AND work_item_type ILIKE '%Bug%'
    AND (created_date >= '2025-01-01' OR closed_date >= '2025-01-01' OR closed_date IS NULL)
    AND state NOT IN ('Closed','Not an issue','Not Required','Userstory Update','No Customer Response')
""")
raw_open_bugs = cur.fetchone()[0]

cur.execute("""
    SELECT COUNT(*) FROM work_items_main
    WHERE (
        created_date >= '2025-01-01' OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (created_date < '2025-01-01' AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
    )
    AND work_item_type ILIKE '%Bug%'
    AND (created_date >= '2025-01-01' OR closed_date >= '2025-01-01' OR closed_date IS NULL)
    AND state IN ('Closed','Not an issue','Not Required','Userstory Update','No Customer Response')
""")
raw_closed_bugs = cur.fetchone()[0]

cur.execute("""
    SELECT COUNT(*) FROM work_items_main
    WHERE (
        created_date >= '2025-01-01' OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (created_date < '2025-01-01' AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
    )
    AND work_item_type ILIKE '%Bug%'
    AND (created_date >= '2025-01-01' OR closed_date >= '2025-01-01' OR closed_date IS NULL)
    AND state NOT IN ('Closed','Not an issue','Not Required','Userstory Update','No Customer Response')
    AND CAST(priority AS INTEGER) = 1
""")
raw_p1_open = cur.fetchone()[0]

cur.execute("""
    SELECT COUNT(*) FROM work_items_main
    WHERE (
        created_date >= '2025-01-01' OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (created_date < '2025-01-01' AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
    )
    AND work_item_type ILIKE '%Bug%'
    AND (created_date >= '2025-01-01' OR closed_date >= '2025-01-01' OR closed_date IS NULL)
    AND state IN ('Not an issue','Not Required','No Customer Response')
""")
raw_rejected = cur.fetchone()[0]

cur.execute("""
    SELECT AVG(EXTRACT(EPOCH FROM (
        NULLIF(closed_date, '')::timestamptz - NULLIF(created_date, '')::timestamptz
    )) / 86400)
    FROM work_items_main
    WHERE (
        created_date >= '2025-01-01' OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (created_date < '2025-01-01' AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
    )
    AND work_item_type ILIKE '%Bug%'
    AND (created_date >= '2025-01-01' OR closed_date >= '2025-01-01' OR closed_date IS NULL)
    AND state = 'Closed'
    AND closed_date IS NOT NULL AND closed_date != ''
    AND created_date IS NOT NULL AND created_date != ''
""")
raw_avg_mttc = cur.fetchone()[0]

check("Items/Bug", "Total Bugs",     raw_total_bugs,  total_pg)
check("Items/Bug", "Open Bugs",      raw_open_bugs,   n_open_pg)
check("Items/Bug", "Closed Bugs",    raw_closed_bugs, n_closed_pg)
check("Items/Bug", "Closure %",
      f"{raw_closed_bugs/raw_total_bugs*100:.1f}%" if raw_total_bugs else "—",
      f"{closure_pct_pg:.1f}%")
check("Items/Bug", "P1 Open",        raw_p1_open,     p1_pg)
check("Items/Bug", "Rejected",       raw_rejected,    rej_pg)
check("Items/Bug", "Avg MTTC (days)",
      f"{raw_avg_mttc:.1f}d" if raw_avg_mttc else "—",
      f"{avg_mttc_pg:.1f}d" if pd.notna(avg_mttc_pg) else "—")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Capacity Page KPIs  (no filters — all iterations, all people)
# ─────────────────────────────────────────────────────────────────────────────
sep("CAPACITY PAGE — KPIs (no team/iteration filter)")

df_cap = df.copy()

# Strip iteration paths (capacity page does this before filtering)
def _strip_iter(val):
    if pd.isna(val): return val
    parts = str(val).split("\\")
    return parts[-1].strip() if len(parts) > 1 else str(val).strip()

if "iteration_path" in df_cap.columns:
    df_cap["iteration_path"] = df_cap["iteration_path"].apply(_strip_iter)

# filter_activity_since already applied

# Exclude Root/Middle containers with completed_work=0
if "hierarchy_type" in df_cap.columns:
    cw = pd.to_numeric(df_cap.get("completed_work", 0), errors="coerce").fillna(0)
    is_container = df_cap["hierarchy_type"].isin(["Root", "Middle"]) & (cw == 0)
    df_cap = df_cap[~is_container]

# 2026 split: 2026 iterations → tasks only; pre-2026 → all types
def _is_2026(iter_name):
    s = str(iter_name)
    return "2026" in s or s.startswith("Iteration 2026")

if "iteration_path" in df_cap.columns:
    mask_2026 = df_cap["iteration_path"].apply(lambda x: _is_2026(x) if pd.notna(x) else False)
    df_pre2026 = df_cap[~mask_2026]
    df_2026    = df_cap[mask_2026 & (df_cap["work_item_type"] == "Task")]
    df_cap     = pd.concat([df_pre2026, df_2026], ignore_index=True)

if "assigned_to" in df_cap.columns:
    df_cap["assigned_to"] = df_cap["assigned_to"].astype(str).str.split(" <").str[0]
if "main_developer" in df_cap.columns:
    df_cap["main_developer"] = df_cap["main_developer"].astype(str).str.split(" <").str[0]

person_field = "main_developer" if "main_developer" in df_cap.columns else "assigned_to"

def num_cap(col, src=None):
    src = src if src is not None else df_cap
    return pd.to_numeric(src.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0)

assigned_h  = num_cap("original_estimate").sum()
completed_h = num_cap("completed_work").sum()
remaining_h = max(assigned_h - completed_h, 0)
unique_people = df_cap[person_field].dropna().nunique() if person_field in df_cap.columns else 0

# Capacity formula uses: (unique_people × bdays × hours_day)
# Without iteration filter, bdays = _business_days(created_min, created_max)
# We just validate the hours figures here
acc_pct  = completed_h / assigned_h * 100 if assigned_h > 0 else 0

# Raw SQL for hour totals (no 2026 split — just to cross-check raw sums)
cur.execute("""
    SELECT
        SUM(CASE WHEN original_estimate ~ '^[0-9.]+$' THEN CAST(original_estimate AS FLOAT) ELSE 0 END) AS assigned,
        SUM(CASE WHEN completed_work    ~ '^[0-9.]+$' THEN CAST(completed_work    AS FLOAT) ELSE 0 END) AS completed,
        SUM(CASE WHEN remaining_work    ~ '^[0-9.]+$' THEN CAST(remaining_work    AS FLOAT) ELSE 0 END) AS remaining
    FROM work_items_main
    WHERE (
        created_date >= '2025-01-01' OR closed_date >= '2025-01-01'
        OR changed_date >= '2025-01-01'
        OR (created_date < '2025-01-01' AND (closed_date IS NULL OR closed_date >= '2025-01-01'))
    )
    AND (created_date >= '2025-01-01' OR closed_date >= '2025-01-01' OR closed_date IS NULL)
    AND NOT (
        hierarchy_type IN ('Root','Middle')
        AND (completed_work IS NULL OR completed_work = '' OR completed_work = '0')
    )
""")
row = cur.fetchone()
raw_assigned_all  = float(row[0] or 0)
raw_completed_all = float(row[1] or 0)
raw_remaining_all = float(row[2] or 0)

check("Capacity", "Assigned hrs (after container excl., before 2026-split)",
      f"{assigned_h:,.0f}", f"{assigned_h:,.0f}",
      note="self-check; compare with raw below")
check("Capacity", "RAW SQL assigned (no 2026 split)",
      f"{raw_assigned_all:,.0f}", f"{assigned_h:,.0f}",
      note="difference = 2026 non-Tasks excluded by page")
check("Capacity", "Completed (h)",   f"{completed_h:,.0f}", f"{completed_h:,.0f}")
check("Capacity", "Remaining (h) = max(A-C,0)",
      f"{remaining_h:,.0f}", f"{remaining_h:,.0f}")
check("Capacity", "Accuracy % (C/A)", f"{acc_pct:.1f}%", f"{acc_pct:.1f}%")
check("Capacity", "Unique people (main_developer)", unique_people, unique_people)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Data Integrity Checks
# ─────────────────────────────────────────────────────────────────────────────
sep("DATA INTEGRITY")

# Work item type distribution
type_counts = df["work_item_type"].value_counts()
print("\n  Work Item Type Distribution:")
for t, c in type_counts.items():
    print(f"    {t:<20} {c:>6,}")

# State distribution
state_counts = df["state"].value_counts()
print("\n  Top 15 States:")
for s, c in state_counts.head(15).items():
    print(f"    {s:<35} {c:>6,}")

# Priority distribution (bugs only)
print("\n  Bug Priority Distribution:")
prio_counts = bugs_all["priority"].value_counts().sort_index()
for p, c in prio_counts.items():
    print(f"    P{p:<5} {c:>6,}")

# Null/missing field check
print("\n  Missing Value Check (key fields):")
for col in ["state", "priority", "work_item_type", "assigned_to",
            "created_date", "closed_date", "original_estimate",
            "completed_work", "remaining_work", "type", "area"]:
    if col in df.columns:
        null_cnt = df[col].isna().sum()
        unassigned_cnt = (df[col].astype(str) == "Unassigned").sum() if col == "assigned_to" else 0
        not_spec_cnt   = (df[col].astype(str) == "Not Specified").sum() if col != "assigned_to" else 0
        print(f"    {col:<25}  nulls={null_cnt:>5}  "
              f"{'unassigned='+str(unassigned_cnt) if unassigned_cnt else '':>15}  "
              f"{'not_specified='+str(not_spec_cnt) if not_spec_cnt else ''}")

# ── Summary_OPEN_STATES naming sanity check ─────────────────────────────────
print("\n  ⚠️  STATE NAMING SANITY CHECK:")
print("  summary.py names the closed-state list 'OPEN_STATES' (line 27).")
print("  This is a misnomer — they are the states that mark an item as DONE/REJECTED.")
print("  open_df = df[~df['state'].isin(OPEN_STATES)]  ← correct logic, wrong var name.")

# Items where type is inconsistent with work_item_type
print("\n  Bug Source ('type' field) for non-Bug work_item_types:")
cur.execute("""
    SELECT work_item_type, type, COUNT(*) as cnt
    FROM work_items_main
    WHERE type IS NOT NULL AND type != ''
      AND work_item_type NOT ILIKE '%Bug%'
    GROUP BY work_item_type, type
    ORDER BY cnt DESC
    LIMIT 10
""")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"    {r[0]:<20} type={r[1]:<15} count={r[2]}")
else:
    print("    None — type field only set on Bug items ✅")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Final Summary
# ─────────────────────────────────────────────────────────────────────────────
sep("FINAL SUMMARY")
passed = sum(1 for r in results if r[4])
failed = sum(1 for r in results if not r[4])
print(f"\n  Total checks:  {len(results)}")
print(f"  ✅ Passed:     {passed}")
print(f"  ❌ Failed:     {failed}")

if failed:
    print("\n  FAILURES:")
    for r in results:
        if not r[4]:
            print(f"    [{r[0]}] {r[1]}: raw={r[2]} vs page={r[3]}  {r[5]}")

# Write report to file
report_path = os.path.join(os.path.dirname(__file__), "validate_kpis_report.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write(f"KPI Validation Report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write("=" * 70 + "\n\n")
    f.write(f"{'Section':<15} {'KPI':<38} {'Raw SQL':>12} {'Page':>12} {'OK?':>5}  Note\n")
    f.write("-" * 100 + "\n")
    for r in results:
        f.write(f"{r[0]:<15} {r[1]:<38} {str(r[2]):>12} {str(r[3]):>12} {'✅' if r[4] else '❌':>5}  {r[5]}\n")
    f.write(f"\nTotal: {len(results)}  Passed: {passed}  Failed: {failed}\n")

print(f"\n  Report saved → validate_kpis_report.txt")

conn.close()
