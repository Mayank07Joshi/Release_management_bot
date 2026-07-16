"""
scripts/sync_validation.py
--------------------------
ADO <-> DB data integrity validator + writeback/readback test.

Usage:
    python scripts/sync_validation.py              # all tests
    python scripts/sync_validation.py --quick      # field-check only (no writeback)
    python scripts/sync_validation.py --item 41015 # target a specific item for writeback
    python scripts/sync_validation.py --sample 50  # larger field-accuracy sample
"""
# -*- coding: utf-8 -*-
import sys, os, argparse, random, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import pandas as pd
from sqlalchemy import text

from sync.ado_sync  import _get_engine, _get_wit_client, _fetch_details, _transform, _upsert
from sync.ado_write import write_fields_sync

_PROJECT = os.getenv("PROJECT_NAME", "Solo Expenses")

_results = []


def _report(label, status, detail=""):
    icon = {"pass": "PASS", "fail": "FAIL", "warn": "WARN"}[status]
    print("  [%s]  %s" % (icon, label))
    if detail:
        for line in detail.splitlines():
            print("        %s" % line)
    _results.append({"label": label, "status": status, "detail": detail})


# -- Test 1: Count sanity -------------------------------------------------

def test_count(engine, wit_client):
    print("\n-- [1] Item Count: ADO vs DB ------------------------------------")

    with engine.connect() as conn:
        db_count = conn.execute(text(
            "SELECT COUNT(*) FROM work_items_main "
            "WHERE EXTRACT(YEAR FROM created_date) >= 2024"
        )).scalar() or 0

    types = "'User Story','Bug','Bug_UI','Bug_Text','Task','Enhancement'"
    wiql = {
        "query": (
            "SELECT [System.Id] FROM WorkItems "
            "WHERE [System.TeamProject] = '%s' "
            "  AND [System.WorkItemType] IN (%s) "
            "  AND [System.CreatedDate] >= '2024-01-01' "
            "ORDER BY [System.Id]"
        ) % (_PROJECT, types)
    }
    ado_ids = [i.id for i in wit_client.query_by_wiql(wiql).work_items]
    ado_count = len(ado_ids)

    diff = abs(db_count - ado_count)
    pct  = round(diff / ado_count * 100, 1) if ado_count else 0

    detail = "ADO=%d  DB=%d  diff=%d (%.1f%%)" % (ado_count, db_count, diff, pct)
    if pct < 2:
        _report("Count (2024+ items)", "pass", detail)
    elif pct < 10:
        _report("Count (2024+ items)", "warn", detail + " -- sync may be behind")
    else:
        _report("Count (2024+ items)", "fail", detail + " -- large gap, investigate")

    return ado_ids


# -- Test 2: Field accuracy -----------------------------------------------

def test_field_accuracy(engine, wit_client, ado_ids, sample_n=30):
    print("\n-- [2] Field Accuracy (sample=%d) --------------------------------" % sample_n)

    sample_ids = random.sample(ado_ids, min(sample_n, len(ado_ids)))

    ado_items = _fetch_details(wit_client, sample_ids)
    ado_df    = _transform(ado_items).set_index("work_item_id")

    id_csv = ", ".join(str(i) for i in sample_ids)
    with engine.connect() as conn:
        db_df = pd.read_sql(
            text(
                "SELECT work_item_id, title, state, priority, assigned_to, "
                "iteration_path FROM work_items_main "
                "WHERE work_item_id IN (%s)" % id_csv
            ),
            conn
        ).set_index("work_item_id")

    FIELDS = ["title", "state", "priority", "assigned_to", "iteration_path"]
    mismatches = []

    for wid in sample_ids:
        if wid not in db_df.index:
            mismatches.append("#%d: not in DB" % wid)
            continue
        if wid not in ado_df.index:
            mismatches.append("#%d: not returned by ADO (closed/deleted?)" % wid)
            continue
        for f in FIELDS:
            av = str(ado_df.loc[wid, f] if f in ado_df.columns else "").strip()
            dv = str(db_df.loc[wid,  f] if f in db_df.columns  else "").strip()
            if av != dv:
                mismatches.append("#%d [%s]: ADO=%r  DB=%r" % (wid, f, av, dv))

    total_checks = len(sample_ids) * len(FIELDS)
    if not mismatches:
        _report("Field accuracy (%d checks)" % total_checks, "pass")
    elif len(mismatches) <= 5:
        _report("Field accuracy (%d checks)" % total_checks, "warn",
                "%d mismatch(es):\n" % len(mismatches) + "\n".join(mismatches))
    else:
        _report("Field accuracy (%d checks)" % total_checks, "fail",
                "%d mismatches (showing 10):\n" % len(mismatches) + "\n".join(mismatches[:10]))


# -- Test 3: Parent-link integrity ----------------------------------------

def test_parent_links(engine, wit_client, sample_n=25):
    print("\n-- [3] Parent-Link Integrity (sample=%d tasks) ------------------" % sample_n)

    with engine.connect() as conn:
        tasks = pd.read_sql(
            text(
                "SELECT work_item_id, parent_id FROM work_items_main "
                "WHERE work_item_type = 'Task' "
                "AND parent_id IS NOT NULL "
                "AND state NOT IN ('Closed', 'Removed', 'Done') "
                "AND EXTRACT(YEAR FROM created_date) >= 2026 "
                "ORDER BY RANDOM() LIMIT :n"
            ),
            conn, params={"n": sample_n}
        )

    if tasks.empty:
        _report("Parent-link integrity", "warn", "No 2026 tasks with parent_id found")
        return

    task_ids  = tasks["work_item_id"].tolist()
    try:
        ado_items = _fetch_details(wit_client, task_ids)
    except Exception:
        # Batch failed — one or more items deleted in ADO. Fetch individually.
        ado_items, skipped = [], []
        for tid in task_ids:
            try:
                ado_items.extend(_fetch_details(wit_client, [tid]))
            except Exception:
                skipped.append(tid)
        if skipped:
            print("     Note: %d item(s) skipped (deleted in ADO): %s"
                  % (len(skipped), skipped))
    ado_df    = _transform(ado_items).set_index("work_item_id")
    db_df     = tasks.set_index("work_item_id")

    mismatches = []
    for wid in task_ids:
        if wid not in ado_df.index:
            continue
        ado_p = ado_df.loc[wid, "parent_id"]
        db_p  = db_df.loc[wid,  "parent_id"]
        ado_p = int(ado_p) if pd.notna(ado_p) else None
        db_p  = int(db_p)  if pd.notna(db_p)  else None
        if ado_p != db_p:
            mismatches.append("#%d: ADO parent=%s  DB parent=%s" % (wid, ado_p, db_p))

    if not mismatches:
        _report("Parent-link integrity (%d tasks)" % len(task_ids), "pass")
    else:
        _report("Parent-link integrity (%d tasks)" % len(task_ids), "fail",
                "\n".join(mismatches))


# -- Test 4: Estimation consistency ---------------------------------------

def test_estimation(engine, wit_client, sample_n=20):
    print("\n-- [4] Estimation Consistency (sample=%d stories) ---------------" % sample_n)

    with engine.connect() as conn:
        stories = pd.read_sql(
            text(
                "SELECT work_item_id, original_estimate FROM work_items_main "
                "WHERE work_item_type IN ('User Story','Enhancement','Bug','Bug_UI','Bug_Text') "
                "AND original_estimate > 0 "
                "AND EXTRACT(YEAR FROM created_date) >= 2026 "
                "ORDER BY RANDOM() LIMIT :n"
            ),
            conn, params={"n": sample_n}
        )

    if stories.empty:
        _report("Estimation consistency", "warn", "No estimated 2026 items in DB")
        return

    ids = stories["work_item_id"].tolist()
    try:
        ado_items = _fetch_details(wit_client, ids)
    except Exception as exc:
        _report("Estimation consistency", "warn",
                "ADO batch fetch failed (some items may be deleted): %s" % exc)
        return
    ado_df = _transform(ado_items).set_index("work_item_id")
    db_df     = stories.set_index("work_item_id")

    mismatches = []
    for wid in ids:
        if wid not in ado_df.index:
            continue
        av = round(float(ado_df.loc[wid, "original_estimate"] or 0), 2)
        dv = round(float(db_df.loc[wid,  "original_estimate"] or 0), 2)
        if abs(av - dv) > 0.01:
            mismatches.append("#%d: ADO=%.2fh  DB=%.2fh" % (wid, av, dv))

    if not mismatches:
        _report("Estimation consistency (%d items)" % len(ids), "pass")
    else:
        _report("Estimation consistency (%d items)" % len(ids), "fail",
                "\n".join(mismatches))


# -- Test 5: Writeback (idempotent write) ---------------------------------

def test_writeback(engine, wit_client, target_id=None):
    print("\n-- [5] Write-Back Test ------------------------------------------")

    with engine.connect() as conn:
        if target_id:
            row = pd.read_sql(
                text(
                    "SELECT work_item_id, original_estimate FROM work_items_main "
                    "WHERE work_item_id = :wid"
                ),
                conn, params={"wid": target_id}
            )
        else:
            row = pd.read_sql(
                text(
                    "SELECT work_item_id, original_estimate FROM work_items_main "
                    "WHERE work_item_type = 'Task' "
                    "AND original_estimate > 0 "
                    "AND EXTRACT(YEAR FROM created_date) >= 2026 "
                    "ORDER BY RANDOM() LIMIT 1"
                ),
                conn
            )

    if row.empty:
        _report("Write-back (idempotent estimate write)", "warn",
                "No suitable target task found")
        return None

    wid = int(row.iloc[0]["work_item_id"])
    est = float(row.iloc[0]["original_estimate"] or 0)

    print("     Target: #%d  estimate=%.1fh  (writing same value -- no-op change in ADO)" % (wid, est))

    t0 = time.time()
    ok, err = write_fields_sync(wid, {"original_estimate": est})
    elapsed = round(time.time() - t0, 2)

    if ok:
        _report("Write-back (#%d est=%.1fh idempotent)" % (wid, est), "pass",
                "HTTP 200 in %.2fs" % elapsed)
        return wid
    else:
        _report("Write-back (#%d)" % wid, "fail", err)
        return None


# -- Test 6: Readback after targeted sync ---------------------------------

def test_readback(engine, wit_client, wid):
    print("\n-- [6] Read-Back After Targeted Sync ----------------------------")

    if wid is None:
        _report("Read-back after sync", "warn", "Skipped -- write-back did not succeed")
        return

    print("     Fetching #%d from ADO and upserting into DB..." % wid)
    ado_items = _fetch_details(wit_client, [wid])
    if not ado_items:
        _report("Read-back (#%d)" % wid, "fail", "ADO returned no data for this ID")
        return

    df = _transform(ado_items)
    _upsert(df, engine)

    ado_df = df.set_index("work_item_id")

    with engine.connect() as conn:
        db_row = pd.read_sql(
            text(
                "SELECT work_item_id, original_estimate, state, assigned_to, "
                "priority, iteration_path FROM work_items_main "
                "WHERE work_item_id = :wid"
            ),
            conn, params={"wid": wid}
        )

    if db_row.empty:
        _report("Read-back (#%d)" % wid, "fail", "Item not found in DB after upsert")
        return

    db_row = db_row.set_index("work_item_id")

    FIELDS = ["state", "assigned_to", "priority", "iteration_path", "original_estimate"]
    mismatches = []
    for f in FIELDS:
        if f not in ado_df.columns or f not in db_row.columns:
            continue
        av = str(ado_df.loc[wid, f] or "").strip()
        dv = str(db_row.loc[wid, f] or "").strip()
        if f == "original_estimate":
            try:
                av = str(round(float(av or 0), 2))
                dv = str(round(float(dv or 0), 2))
            except ValueError:
                pass
        if av != dv:
            mismatches.append("[%s]: ADO=%r  DB=%r" % (f, av, dv))

    if not mismatches:
        _report("Read-back (#%d) all fields match post-sync" % wid, "pass")
    else:
        _report("Read-back (#%d)" % wid, "fail", "\n".join(mismatches))


# -- Summary --------------------------------------------------------------

def print_summary():
    passed = sum(1 for r in _results if r["status"] == "pass")
    warned = sum(1 for r in _results if r["status"] == "warn")
    failed = sum(1 for r in _results if r["status"] == "fail")
    total  = len(_results)

    print("\n" + "=" * 60)
    print("  RESULT  %d/%d passed   %d warn   %d fail" % (passed, total, warned, failed))
    print("=" * 60)

    if failed:
        print("\n  Failed tests:")
        for r in _results:
            if r["status"] == "fail":
                print("    [FAIL]  %s" % r["label"])
    if warned:
        print("\n  Warnings:")
        for r in _results:
            if r["status"] == "warn":
                print("    [WARN]  %s" % r["label"])

    return failed == 0


# -- Entry point ----------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Sync validation: ADO <-> DB")
    ap.add_argument("--quick",  action="store_true",
                    help="Skip writeback/readback tests")
    ap.add_argument("--item",   type=int, default=None,
                    help="Specific work item ID for writeback test")
    ap.add_argument("--sample", type=int, default=30,
                    help="Field-accuracy sample size (default 30)")
    args = ap.parse_args()

    print("=" * 60)
    print("  ADO <-> DB Sync Validation")
    print("=" * 60)

    t0 = time.time()
    engine     = _get_engine()
    wit_client = _get_wit_client()

    ado_ids = test_count(engine, wit_client)

    if ado_ids:
        test_field_accuracy(engine, wit_client, ado_ids, sample_n=args.sample)

    test_parent_links(engine, wit_client)
    test_estimation(engine, wit_client)

    if not args.quick:
        wb_id = test_writeback(engine, wit_client, target_id=args.item)
        test_readback(engine, wit_client, wb_id)
    else:
        print("\n-- [5+6] Writeback/Readback -- skipped (--quick) ----------------")

    elapsed = round(time.time() - t0, 1)
    print("\n  Total time: %.1fs" % elapsed)

    ok = print_summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
