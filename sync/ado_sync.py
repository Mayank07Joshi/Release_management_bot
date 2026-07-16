"""
sync/ado_sync.py
────────────────
Incremental sync from Azure DevOps → PostgreSQL (work_items_main).

Public API:
  run_sync(full=False)   → sync changed items only (call on a schedule)
  run_sync(full=True)    → re-fetch everything from 2023 (use to rebuild)
  get_last_sync_result() → last status dict for UI display
"""

import os
import logging
import time
import urllib.parse
from datetime import datetime, timezone, timedelta

import pandas as pd
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_ORG_URL    = os.getenv("ORGANIZATION_URL", "https://dev.azure.com/expenseondemand")
_PAT        = os.getenv("AZURE_DEVOPS_PAT")
_PROJECT    = os.getenv("PROJECT_NAME", "Solo Expenses")
_DB_PASS    = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", "1234"))
_DB_CONN    = f"postgresql+psycopg2://postgres:{_DB_PASS}@localhost:5432/vsts_analytics"

_ITEM_TYPES = "'User Story', 'Bug', 'Bug_UI', 'Bug_Text', 'Task', 'Enhancement'"

# Fields fetched from ADO — mirrors your existing extraction script exactly
_FIELDS = [
    "System.Id",
    "System.Title",
    "System.AssignedTo",
    "System.State",
    "System.WorkItemType",
    "Microsoft.VSTS.Common.Priority",
    "Microsoft.VSTS.Common.Severity",
    "Microsoft.VSTS.Scheduling.OriginalEstimate",
    "Microsoft.VSTS.Scheduling.CompletedWork",
    "Microsoft.VSTS.Common.ClosedDate",
    "Microsoft.VSTS.Scheduling.RemainingWork",
    "Custom.function",
    "System.IterationPath",
    "Custom.MainDevevloper",
    "Custom.MainDesigner",
    "System.CreatedDate",
    "System.ChangedDate",
    "Custom.Releasedate",
    "Custom.Area",
    "Microsoft.VSTS.Scheduling.TargetDate",
    "System.Tags",
    "Custom.Stage",
    "Custom.Type",
    "Microsoft.VSTS.Scheduling.FinishDate",
    "Custom.Userstoryowner",
    "System.Parent",
    "Microsoft.VSTS.Common.Activity",
    "Microsoft.VSTS.Common.ActivatedDate",
    "Custom.StorySize",
    "Custom.StoryStatus",
]

# ── Engine (singleton) ────────────────────────────────────────────────────────
_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_DB_CONN, pool_size=5, max_overflow=10)
    return _engine


# ── ADO helpers ───────────────────────────────────────────────────────────────
def _get_wit_client():
    if not _PAT:
        raise ValueError("AZURE_DEVOPS_PAT not set in .env")
    creds = BasicAuthentication("", _PAT)
    conn  = Connection(base_url=_ORG_URL, creds=creds)
    return conn.clients.get_work_item_tracking_client()


def _get_person_name(field) -> str:
    if not field:
        return "Unassigned"
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return field.get("displayName", "Unassigned")
    return "Unassigned"


# ── Sync logic ────────────────────────────────────────────────────────────────
def _get_last_sync_time(engine) -> datetime:
    """
    Returns max(changed_date) from DB minus 1 hour as a safety buffer.
    Falls back to 2023-01-01 if the table is empty or unreachable.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT MAX(changed_date) FROM work_items_main")
            ).scalar()
        if result and pd.notna(result):
            ts = pd.Timestamp(result).to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts - timedelta(hours=1)
    except Exception as e:
        log.warning(f"Could not read last sync time from DB: {e}")
    return datetime(2023, 1, 1, tzinfo=timezone.utc)


def _fetch_changed_ids(wit_client, since: datetime) -> list:
    """Query ADO for all work item IDs changed after `since`."""
    # ADO WIQL only accepts date precision (no time component)
    since_str = since.strftime("%Y-%m-%d")
    wiql = {
        "query": f"""
        SELECT [System.Id]
        FROM WorkItems
        WHERE [System.TeamProject] = '{_PROJECT}'
          AND [System.ChangedDate] >= '{since_str}'
          AND [System.WorkItemType] IN ({_ITEM_TYPES})
        ORDER BY [System.Id]
        """
    }
    result = wit_client.query_by_wiql(wiql)
    ids = [item.id for item in result.work_items]
    log.info(f"ADO returned {len(ids)} items changed since {since_str}")
    return ids


def _fetch_all_open_task_ids(wit_client) -> list:
    """
    Always fetch ALL open Tasks from 2026 regardless of ChangedDate.

    ADO does not update System.ChangedDate when a parent-child link is
    added or removed, so incremental syncs miss reparented tasks.
    Re-syncing all open tasks on every cycle is cheap (bounded set) and
    guarantees parent_id is always current in work_items_main.
    """
    wiql = {
        "query": f"""
        SELECT [System.Id]
        FROM WorkItems
        WHERE [System.TeamProject] = '{_PROJECT}'
          AND [System.WorkItemType] = 'Task'
          AND [System.State] NOT IN ('Closed', 'Removed', 'Done')
          AND [System.CreatedDate] >= '2026-01-01'
        ORDER BY [System.Id]
        """
    }
    try:
        result = wit_client.query_by_wiql(wiql)
        ids = [item.id for item in result.work_items]
        log.info(f"ADO returned {len(ids)} open tasks (parent-link refresh)")
        return ids
    except Exception as exc:
        log.warning(f"Open-task refresh query failed (non-fatal): {exc}")
        return []


def _fetch_details(wit_client, ids: list) -> list:
    """Fetch full work item details in batches of 200 (ADO API limit)."""
    all_items = []
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        items = wit_client.get_work_items(ids=batch, fields=_FIELDS)
        all_items.extend(items)
    return all_items


def _transform(work_items) -> pd.DataFrame:
    """Convert ADO work items to a DataFrame matching work_items_main schema."""
    rows = []
    for item in work_items:
        f = item.fields

        # Release date: try custom field first, then fall back to target/finish
        release_date = ""
        for field_key in ("Custom.Releasedate",
                          "Microsoft.VSTS.Scheduling.TargetDate",
                          "Microsoft.VSTS.Scheduling.FinishDate"):
            val = f.get(field_key)
            if val:
                release_date = str(val)
                break

        # Priority: stored as float in ADO (e.g. 2.0) — normalise to string "2"
        prio_raw = f.get("Microsoft.VSTS.Common.Priority")
        priority = str(int(prio_raw)) if prio_raw is not None else "4"

        rows.append({
            "work_item_id":      item.id,
            "title":             f.get("System.Title", ""),
            "assigned_to":       _get_person_name(f.get("System.AssignedTo")),
            "state":             f.get("System.State", ""),
            "work_item_type":    f.get("System.WorkItemType", ""),
            "priority":          priority,
            "severity":          f.get("Microsoft.VSTS.Common.Severity", ""),
            "original_estimate": f.get("Microsoft.VSTS.Scheduling.OriginalEstimate") or 0,
            "completed_work":    f.get("Microsoft.VSTS.Scheduling.CompletedWork") or 0,
            "remaining_work":    f.get("Microsoft.VSTS.Scheduling.RemainingWork") or 0,
            "function":          f.get("Custom.function", "General"),
            "iteration_path":    f.get("System.IterationPath", ""),
            "main_developer":    _get_person_name(f.get("Custom.MainDevevloper")),
            "main_designer":     _get_person_name(f.get("Custom.MainDesigner")),
            "created_date":      f.get("System.CreatedDate"),
            "closed_date":       f.get("Microsoft.VSTS.Common.ClosedDate"),
            "changed_date":      f.get("System.ChangedDate"),
            "release_date":      release_date,
            "area":              f.get("Custom.Area", "Unassigned"),
            "tags":              f.get("System.Tags", ""),
            "type":              f.get("Custom.Type", ""),
            "stage":             f.get("Custom.Stage", "Unassigned"),
            "story_owner":       f.get("Custom.Userstoryowner", ""),
            "parent_id":         f.get("System.Parent"),   # int or None
            "activity":          f.get("Microsoft.VSTS.Common.Activity", ""),
            "activated_date":    f.get("Microsoft.VSTS.Common.ActivatedDate"),
            "story_size":        f.get("Custom.StorySize", ""),
            "story_status":      f.get("Custom.StoryStatus", ""),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Numeric columns
    for col in ("original_estimate", "completed_work", "remaining_work"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Datetime columns — strip timezone so PostgreSQL (no-tz) doesn't choke
    for col in ("created_date", "changed_date", "closed_date", "activated_date"):
        df[col] = (
            pd.to_datetime(df[col], errors="coerce", utc=True)
            .dt.tz_localize(None)
        )

    return df


def _upsert(df: pd.DataFrame, engine) -> int:
    """
    Delete-then-insert upsert (atomic transaction).
    Removes existing rows for the affected IDs, then inserts fresh data.
    work_items_main has a UNIQUE INDEX on work_item_id — concurrent sync
    runs will raise an IntegrityError instead of silently creating duplicates.
    """
    if df.empty:
        return 0

    ids = df["work_item_id"].tolist()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM work_items_main WHERE work_item_id = ANY(:ids)"),
            {"ids": ids},
        )
        df.to_sql("work_items_main", conn, if_exists="append", index=False, method="multi")

    return len(ids)


def _bust_loader_cache():
    """Force loader.py to re-query PostgreSQL on the next dashboard request."""
    try:
        import data.loader as loader_module
        loader_module._DATA_CACHE = None
    except Exception:
        pass


# ── Sprint iteration-history sync ─────────────────────────────────────────────

def _get_current_sprint_path(engine) -> str | None:
    """
    Find the iteration path for the current calendar month.
    Matches pattern %YYYY%MonthName% to handle formats like 'Iteration 2026 06-June'.
    """
    from datetime import date
    today      = date.today()
    month_name = today.strftime("%B")   # "June"
    year       = today.year             # 2026
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT iteration_path, COUNT(*) AS cnt "
                    "FROM work_items_main "
                    "WHERE iteration_path ILIKE :pattern "
                    "GROUP BY iteration_path ORDER BY cnt DESC LIMIT 1"
                ),
                {"pattern": f"%{year}%{month_name}%"},
            ).fetchall()
        if rows:
            return rows[0].iteration_path
    except Exception as e:
        log.warning("Could not determine current sprint path: %s", e)
    return None


def _sync_sprint_iteration_history(engine) -> None:
    """
    Populate p_sprint_item_history for every sprint month that has items in
    work_items_main but no entry in the history table yet.

    Added-at resolution order (all DB-based — no per-item ADO API calls):
      1. created_date falls within the sprint month  → use created_date
      2. item_state_history has a revision in this iteration path → use that date
      3. Fallback → sprint month start (item was carried in from a previous sprint)

    Runs in <1 second regardless of how many items are in the sprint.
    """
    from datetime import date
    from db.focus import bulk_upsert_sprint_history

    today = date.today()

    # Build list of (iteration_path, sprint_start) for all 2026 sprint months
    # so we backfill past months in one go and keep future syncs incremental.
    try:
        with engine.connect() as conn:
            path_rows = conn.execute(text("""
                SELECT DISTINCT iteration_path
                FROM work_items_main
                WHERE iteration_path ILIKE '%2026%'
                  AND iteration_path NOT ILIKE '%backlog%'
                  AND iteration_path NOT ILIKE '%unassigned%'
            """)).fetchall()
    except Exception as e:
        log.warning("Sprint history sync: could not list sprint paths: %s", e)
        return

    if not path_rows:
        log.info("Sprint history sync: no 2026 sprint paths found")
        return

    total_inserted = 0
    for (sprint_path,) in path_rows:
        # Derive sprint_start from path name — extract month number
        # Path format: "Solo Expenses\2026\Iteration 2026 06-June"
        import re
        m = re.search(r"(\d{4})[^\d]+(\d{2})-\w+", sprint_path)
        if m:
            year_n, month_n = int(m.group(1)), int(m.group(2))
        else:
            # Fallback: use current month
            year_n, month_n = today.year, today.month
        sprint_start = datetime(year_n, month_n, 1, tzinfo=timezone.utc)

        try:
            with engine.connect() as conn:
                # Items in this sprint not yet tracked
                new_rows = conn.execute(text("""
                    SELECT w.work_item_id, w.created_date
                    FROM work_items_main w
                    WHERE w.iteration_path = :path
                      AND w.work_item_id NOT IN (
                          SELECT work_item_id
                          FROM p_sprint_item_history
                          WHERE iteration_path = :path
                      )
                """), {"path": sprint_path}).fetchall()
        except Exception as e:
            log.warning("Sprint history sync: query failed for %s: %s", sprint_path, e)
            continue

        if not new_rows:
            continue

        # Work with tz-naive UTC throughout to avoid comparison errors
        sprint_start_naive = sprint_start.replace(tzinfo=None)

        def _naive_utc(ts):
            if ts is None:
                return None
            t = pd.Timestamp(ts)
            if t.tzinfo is not None:
                return t.tz_convert("UTC").tz_localize(None).to_pydatetime()
            return t.to_pydatetime()

        # Collect item_ids that were NOT created in this sprint month
        # (candidates for state-history lookup)
        moved_ids = [
            r.work_item_id for r in new_rows
            if r.created_date is None or
            (_naive_utc(r.created_date) or sprint_start_naive) < sprint_start_naive
        ]

        # Bulk look up most-recent state-history entry per item for this iteration
        state_hist: dict[int, datetime] = {}
        if moved_ids:
            try:
                with engine.connect() as conn:
                    hist_rows = conn.execute(text("""
                        SELECT DISTINCT ON (work_item_id) work_item_id, changed_at
                        FROM item_state_history
                        WHERE work_item_id = ANY(:ids)
                          AND iteration_path = :path
                          AND changed_at IS NOT NULL
                        ORDER BY work_item_id, changed_at DESC
                    """), {"ids": moved_ids, "path": sprint_path}).fetchall()
                state_hist = {r.work_item_id: _naive_utc(r.changed_at) for r in hist_rows if r.changed_at}
            except Exception as e:
                log.debug("Sprint history sync: state-history lookup failed: %s", e)

        records = []
        for row in new_rows:
            wid = row.work_item_id
            added_at: datetime | None = None

            cd = _naive_utc(row.created_date)
            if cd is not None and cd >= sprint_start_naive:
                # Created directly in this sprint
                added_at = cd

            if added_at is None:
                # Use state-history date if available (item moved in with a state change)
                added_at = state_hist.get(wid) or sprint_start_naive

            records.append({
                "work_item_id":   wid,
                "iteration_path": sprint_path,
                "added_at":       added_at,
            })

        bulk_upsert_sprint_history(records)
        total_inserted += len(records)
        log.info("Sprint history: %d new records for %s", len(records), sprint_path)

    log.info("Sprint history sync complete: %d total records upserted", total_inserted)


# ── State history sync ───────────────────────────────────────────────────────

def _sync_state_history(wit_client, engine, item_ids: list) -> int:
    """
    For each item_id, fetch ADO update revisions and persist any System.State
    transitions to item_state_history.  UNIQUE(work_item_id, revision) makes
    this idempotent — safe to re-run on the same items.

    Throttled to ~90 req/min to stay within ADO limits.
    Returns number of new rows inserted.
    """
    if not item_ids:
        return 0

    inserted = 0
    for idx, item_id in enumerate(item_ids):
        if idx > 0:
            time.sleep(0.67)
        try:
            updates = wit_client.get_updates(item_id) or []
        except Exception as exc:
            log.debug("state_history: get_updates(%s) failed: %s", item_id, exc)
            continue

        prev_state = None
        rows = []
        for upd in updates:
            if not upd.fields:
                continue
            state_change = upd.fields.get("System.State")
            if state_change is None:
                continue
            to_state = getattr(state_change, "new_value", None)
            if not to_state:
                continue

            revision    = getattr(upd, "rev", None) or 0
            changed_at  = getattr(upd, "revised_date", None)
            changed_by  = None
            if upd.revised_by:
                changed_by = getattr(upd.revised_by, "display_name", None)

            iter_change = upd.fields.get("System.IterationPath")
            iter_path   = getattr(iter_change, "new_value", None) if iter_change else None

            rows.append({
                "work_item_id":   item_id,
                "revision":       revision,
                "from_state":     prev_state,
                "to_state":       to_state,
                "changed_by":     changed_by,
                "changed_at":     changed_at,
                "iteration_path": iter_path,
            })
            prev_state = to_state

        if not rows:
            continue

        sql = text("""
            INSERT INTO item_state_history
                (work_item_id, revision, from_state, to_state, changed_by, changed_at, iteration_path)
            VALUES
                (:work_item_id, :revision, :from_state, :to_state, :changed_by, :changed_at, :iteration_path)
            ON CONFLICT (work_item_id, revision) DO NOTHING
        """)
        try:
            with engine.begin() as conn:
                result = conn.execute(sql, rows)
                inserted += result.rowcount
        except Exception as exc:
            log.warning("state_history: insert failed for item %s: %s", item_id, exc)

        if (idx + 1) % 50 == 0:
            log.info("  state_history: %d / %d items processed", idx + 1, len(item_ids))

    log.info("state_history sync: %d new rows for %d items", inserted, len(item_ids))
    return inserted


# ── Production bugs sync ──────────────────────────────────────────────────────

_BUG_TYPE_MAP = {
    "Bug":      "functional",
    "Bug_UI":   "ui",
    "Bug_Text": "text",
    "User Story": "functional",
}


def _sync_production_bugs(engine) -> int:
    """
    Upsert Bug/Bug_UI/Bug_Text items from work_items_main into p_bugs.

    Inclusion criteria (any of):
      - tags contain 'production' or 'hotfix' or 'customer' (case-insensitive)
      - priority = '1'  (P1 items are always tracked)

    Uses ado_id (= work_item_id) as the stable key for ON CONFLICT.
    Returns number of rows upserted.
    """
    sql_fetch = text("""
        SELECT
            work_item_id,
            title,
            work_item_type,
            priority,
            severity,
            state,
            assigned_to,
            main_developer,
            area,
            function,
            iteration_path,
            tags
        FROM work_items_main
        WHERE work_item_type IN ('Bug', 'Bug_UI', 'Bug_Text')
          AND (
              priority = '1'
              OR LOWER(COALESCE(tags, '')) LIKE '%production%'
              OR LOWER(COALESCE(tags, '')) LIKE '%hotfix%'
              OR LOWER(COALESCE(tags, '')) LIKE '%customer%'
          )
    """)

    sql_upsert = text("""
        INSERT INTO p_bugs
            (ado_id, bug_ref, title, bug_type, priority, severity, state,
             area, func, found_in_iteration)
        VALUES
            (:ado_id, :bug_ref, :title, :bug_type, :priority, :severity, :state,
             :area, :func, :found_in_iteration)
        ON CONFLICT (ado_id) WHERE ado_id IS NOT NULL DO UPDATE SET
            title              = EXCLUDED.title,
            state              = EXCLUDED.state,
            severity           = EXCLUDED.severity,
            found_in_iteration = EXCLUDED.found_in_iteration
    """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql_fetch).fetchall()
    except Exception as exc:
        log.warning("production_bugs: fetch failed: %s", exc)
        return 0

    if not rows:
        log.info("production_bugs: no qualifying bugs found in work_items_main")
        return 0

    # p_bugs.ado_id needs a UNIQUE constraint — add if missing
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE p_bugs ADD COLUMN IF NOT EXISTS ado_id INTEGER"
            ))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_p_bugs_ado_id ON p_bugs (ado_id) WHERE ado_id IS NOT NULL"
            ))
    except Exception as exc:
        log.warning("production_bugs: schema prep (non-fatal): %s", exc)

    records = [
        {
            "ado_id":             r.work_item_id,
            "bug_ref":            f"BUG-{r.work_item_id}",
            "title":              r.title,
            "bug_type":           _BUG_TYPE_MAP.get(r.work_item_type, "functional"),
            "priority":           r.priority,
            "severity":           r.severity or "",
            "state":              r.state,
            "area":               r.area or "",
            "func":               r.function or "",
            "found_in_iteration": r.iteration_path or "",
        }
        for r in rows
    ]

    try:
        with engine.begin() as conn:
            result = conn.execute(sql_upsert, records)
            count = result.rowcount
    except Exception as exc:
        log.warning("production_bugs: upsert failed: %s", exc)
        return 0

    log.info("production_bugs: %d rows upserted (P1 + tagged bugs)", count)
    return count


# ── Public API ────────────────────────────────────────────────────────────────
_last_sync_result: dict = {"status": "never", "timestamp": None, "count": 0}


def run_sync(full: bool = False) -> dict:
    """
    Execute one sync cycle.

    full=False (default) — incremental: only items changed since last run.
                           Typical runtime: 5-30 seconds.
    full=True            — complete re-fetch from 2023-01-01.
                           Use only to rebuild the DB from scratch.
                           Typical runtime: 5-10 minutes.
    """
    global _last_sync_result
    t0 = time.time()
    mode = "full" if full else "incremental"
    log.info(f"▶ ADO sync started [{mode}]")

    try:
        engine     = _get_engine()
        wit_client = _get_wit_client()

        # Ensure all columns exist before any upsert attempt
        _new_cols = [
            "ALTER TABLE work_items_main ADD COLUMN IF NOT EXISTS activity       VARCHAR(100) DEFAULT ''",
            "ALTER TABLE work_items_main ADD COLUMN IF NOT EXISTS activated_date TIMESTAMP",
            "ALTER TABLE work_items_main ADD COLUMN IF NOT EXISTS story_size     VARCHAR(50)  DEFAULT ''",
            "ALTER TABLE work_items_main ADD COLUMN IF NOT EXISTS story_status   VARCHAR(50)  DEFAULT ''",
            "ALTER TABLE work_items_main ADD COLUMN IF NOT EXISTS story_owner    VARCHAR(100) DEFAULT ''",
        ]
        try:
            with engine.begin() as conn:
                for _sql in _new_cols:
                    conn.execute(text(_sql))
        except Exception as _col_err:
            log.warning("column migration (non-fatal): %s", _col_err)

        since = (
            datetime(2023, 1, 1, tzinfo=timezone.utc)
            if full
            else _get_last_sync_time(engine)
        )

        ids = _fetch_changed_ids(wit_client, since)

        # Always merge in all open tasks so parent-link changes (which ADO
        # does not reflect in System.ChangedDate) are never missed.
        if not full:
            task_ids = _fetch_all_open_task_ids(wit_client)
            ids = list(dict.fromkeys(ids + task_ids))  # merge + deduplicate, preserve order

        if not ids:
            log.info("✅ No changes detected — DB is up to date")
            _last_sync_result = {
                "status":    "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "count":     0,
                "elapsed_s": round(time.time() - t0, 1),
                "mode":      mode,
            }
            return _last_sync_result

        items   = _fetch_details(wit_client, ids)
        df      = _transform(items)
        count   = _upsert(df, engine)

        try:
            _sync_sprint_iteration_history(engine)
        except Exception as _sh_err:
            log.warning("Sprint history sync failed (non-fatal): %s", _sh_err)

        try:
            # Limit state-history fetches to max 150 items per incremental sync
            # to avoid long runtimes. Full sync processes all changed items.
            history_ids = ids if full else ids[:150]
            _sync_state_history(wit_client, engine, history_ids)
        except Exception as _ish_err:
            log.warning("State history sync failed (non-fatal): %s", _ish_err)

        try:
            _sync_production_bugs(engine)
        except Exception as _pb_err:
            log.warning("Production bugs sync failed (non-fatal): %s", _pb_err)

        _bust_loader_cache()

        try:
            from sync.task_classifier import run_classifier
            run_classifier()
        except Exception as _cl_err:
            log.warning("Standalone classifier (non-fatal): %s", _cl_err)

        try:
            with engine.begin() as conn:
                pruned = conn.execute(text(
                    "DELETE FROM standalone_task_classifications "
                    "WHERE task_id NOT IN ("
                    "    SELECT work_item_id FROM work_items_main WHERE work_item_type = 'Task'"
                    ")"
                )).rowcount
                if pruned:
                    log.info("Pruned %d stale task classifications", pruned)
        except Exception as _prune_err:
            log.warning("Classification prune (non-fatal): %s", _prune_err)

        try:
            from sync.aggregator import run_aggregations
            run_aggregations()
        except Exception as _agg_err:
            log.warning("Aggregator (non-fatal): %s", _agg_err)

        elapsed = round(time.time() - t0, 1)
        log.info(f"✅ Sync complete — {count} items upserted in {elapsed}s")

        _last_sync_result = {
            "status":    "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count":     count,
            "elapsed_s": elapsed,
            "mode":      mode,
        }

    except Exception as e:
        log.exception(f"❌ Sync failed: {e}")
        _last_sync_result = {
            "status":    "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error":     str(e),
            "mode":      mode,
        }

    return _last_sync_result


def get_last_sync_result() -> dict:
    """Return the result of the most recent sync cycle."""
    return _last_sync_result
