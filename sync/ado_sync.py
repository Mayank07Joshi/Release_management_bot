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
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Numeric columns
    for col in ("original_estimate", "completed_work", "remaining_work"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Datetime columns — strip timezone so PostgreSQL (no-tz) doesn't choke
    for col in ("created_date", "changed_date", "closed_date"):
        df[col] = (
            pd.to_datetime(df[col], errors="coerce", utc=True)
            .dt.tz_localize(None)
        )

    return df


def _upsert(df: pd.DataFrame, engine) -> int:
    """
    Delete-then-insert upsert.
    Removes existing rows for the affected IDs, then inserts the fresh data.
    No primary-key constraint required on the table.
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
    Find the iteration path for the current calendar month by querying
    work_items_main for the most-populated path matching 'Month YYYY'.
    Returns None if nothing matches.
    """
    from datetime import date
    month_name = date.today().strftime("%B %Y")   # e.g. "April 2026"
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT iteration_path, COUNT(*) AS cnt "
                    "FROM work_items_main "
                    "WHERE iteration_path ILIKE :pattern "
                    "GROUP BY iteration_path ORDER BY cnt DESC LIMIT 1"
                ),
                {"pattern": f"%{month_name}%"},
            ).fetchall()
        if rows:
            return rows[0].iteration_path
    except Exception as e:
        log.warning("Could not determine current sprint path: %s", e)
    return None


def _find_iteration_added_date(wit_client, item_id: int, sprint_path: str):
    """
    Return the datetime when item_id was LAST moved into sprint_path,
    by scanning its ADO update revisions for a System.IterationPath change.
    Returns None if no such revision is found (item may have been created
    directly in the sprint — caller applies created_date fallback).
    """
    try:
        updates = wit_client.get_updates(item_id)
        last_added = None
        for update in (updates or []):
            if not update.fields:
                continue
            iter_change = update.fields.get("System.IterationPath")
            if iter_change is None:
                continue
            new_val = getattr(iter_change, "new_value", None)
            if new_val == sprint_path:
                last_added = getattr(update, "revised_date", None)
        return last_added
    except Exception as e:
        log.debug("Could not fetch updates for item %s: %s", item_id, e)
        return None


def _sync_sprint_iteration_history(wit_client, engine) -> None:
    """
    For every item currently in the sprint that we haven't tracked yet,
    fetch its ADO revision history, detect when it entered the sprint,
    and persist to p_sprint_item_history.

    Only processes *new* items (not already in the history table) to keep
    incremental sync fast.  Falls back to created_date when no explicit
    IterationPath change revision exists (item was created directly in sprint).
    """
    from datetime import date
    from db.focus import load_sprint_history, bulk_upsert_sprint_history

    sprint_path = _get_current_sprint_path(engine)
    if not sprint_path:
        log.info("Sprint history sync: no current sprint path found, skipping")
        return

    log.info("Sprint history sync: sprint path = %s", sprint_path)

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT work_item_id, created_date "
                    "FROM work_items_main "
                    "WHERE iteration_path = :path"
                ),
                {"path": sprint_path},
            ).fetchall()
    except Exception as e:
        log.warning("Sprint history sync: could not query sprint items: %s", e)
        return

    if not rows:
        log.info("Sprint history sync: no items in current sprint")
        return

    existing = load_sprint_history(sprint_path)
    new_rows  = [r for r in rows if r.work_item_id not in existing]

    if not new_rows:
        log.info("Sprint history sync: all %d items already tracked", len(rows))
        return

    log.info("Sprint history sync: fetching revision history for %d new items", len(new_rows))

    today = date.today()
    sprint_start_ts = pd.Timestamp(datetime(today.year, today.month, 1, tzinfo=timezone.utc))

    records = []
    for i, row in enumerate(new_rows):
        if i > 0:
            time.sleep(0.65)   # throttle: ~92 req/min, well under ADO limit

        item_id  = row.work_item_id
        added_at = _find_iteration_added_date(wit_client, item_id, sprint_path)

        # Fallback: item created directly into sprint (no IterationPath change revision)
        if added_at is None and row.created_date is not None:
            cd = pd.Timestamp(row.created_date)
            if cd.tzinfo is None:
                cd = cd.tz_localize("UTC")
            if cd >= sprint_start_ts:
                added_at = cd.to_pydatetime()

        records.append({
            "work_item_id":  item_id,
            "iteration_path": sprint_path,
            "added_at":      added_at,
        })

        if (i + 1) % 25 == 0:
            log.info("  sprint history: %d / %d processed", i + 1, len(new_rows))

    bulk_upsert_sprint_history(records)
    log.info("Sprint history sync complete: %d records upserted for %s", len(records), sprint_path)


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

        since = (
            datetime(2023, 1, 1, tzinfo=timezone.utc)
            if full
            else _get_last_sync_time(engine)
        )

        ids = _fetch_changed_ids(wit_client, since)

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
            _sync_sprint_iteration_history(wit_client, engine)
        except Exception as _sh_err:
            log.warning("Sprint history sync failed (non-fatal): %s", _sh_err)

        _bust_loader_cache()

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
