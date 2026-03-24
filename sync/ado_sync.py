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
