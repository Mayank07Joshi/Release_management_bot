"""
sync/ado_write.py
─────────────────
ADO Write-Back Module — Local → Azure DevOps

All mutations to ADO work items flow through here.

Public API:
  write_fields(ado_id, fields_dict)          → fire-and-forget (non-blocking)
  write_fields_sync(ado_id, fields_dict)     → blocking, returns (ok, error_msg)
  patch_work_item(ado_id, patches)           → raw PATCH with retry, returns (ok, error_msg)
  get_pending_failures()                     → list of recent failure dicts (for UI toasts)

Field names (keys in fields_dict) use platform naming conventions:
  title, state, priority, assigned_to, iteration,
  original_estimate, completed_work, remaining_work,
  area, main_developer, main_designer, tags

The module maps these to ADO field paths before sending.
"""

import os
import base64
import time
import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_ORG_URL  = os.getenv("ORGANIZATION_URL", "https://dev.azure.com/expenseondemand")
_PAT      = os.getenv("AZURE_DEVOPS_PAT", "")
_PROJECT  = os.getenv("PROJECT_NAME", "Solo Expenses")
_API_VER  = "7.1"

# ── Field name → ADO field path mapping ──────────────────────────────────────

FIELD_MAP: dict[str, str] = {
    "title":             "System.Title",
    "state":             "System.State",
    "priority":          "Microsoft.VSTS.Common.Priority",
    "assigned_to":       "System.AssignedTo",
    "iteration":         "System.IterationPath",
    "original_estimate": "Microsoft.VSTS.Scheduling.OriginalEstimate",
    "completed_work":    "Microsoft.VSTS.Scheduling.CompletedWork",
    "remaining_work":    "Microsoft.VSTS.Scheduling.RemainingWork",
    "area":              "Custom.Area",
    "main_developer":    "Custom.MainDevevloper",   # intentional typo — matches ADO field
    "main_designer":     "Custom.MainDesigner",
    "tags":              "System.Tags",
    "description":       "System.Description",
    # NOTE: verify exact ADO custom field name for your project before using
    "release_date":      "Custom.ReleaseDate",
}

# ── Internal: failure queue (capped, thread-safe via deque) ──────────────────

_failures: deque[dict] = deque(maxlen=50)
_successes: deque[dict] = deque(maxlen=20)
_failures_lock = threading.Lock()

# Background thread pool for fire-and-forget writes
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ado-write")


# ── Core HTTP layer ───────────────────────────────────────────────────────────

def _auth_header() -> dict[str, str]:
    """Build the Basic auth header from PAT."""
    token = base64.b64encode(f":{_PAT}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type":  "application/json-patch+json",
    }


def _build_url(ado_id: int) -> str:
    org = _ORG_URL.rstrip("/")
    project = requests.utils.quote(_PROJECT, safe="")
    return f"{org}/{project}/_apis/wit/workitems/{ado_id}?api-version={_API_VER}"


def patch_work_item(
    ado_id: int,
    patches: list[dict],
    retries: int = 3,
    backoff: float = 2.0,
) -> tuple[bool, str]:
    """
    Send a JSON-Patch array to ADO for a single work item.
    Retries up to `retries` times with exponential backoff.

    Returns:
        (True, "")              on success
        (False, error_message)  on permanent failure
    """
    if not _PAT:
        msg = "AZURE_DEVOPS_PAT not set — ADO write skipped"
        log.warning(msg)
        return False, msg

    if not patches:
        return True, ""

    url     = _build_url(ado_id)
    headers = _auth_header()

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(url, headers=headers, json=patches, timeout=10)

            if resp.status_code in (200, 201):
                log.info(f"[ado_write] PATCH {ado_id} OK (attempt {attempt})")
                return True, ""

            # 4xx client errors — don't retry (bad request or permissions)
            if 400 <= resp.status_code < 500:
                msg = f"ADO PATCH {ado_id} failed {resp.status_code}: {resp.text[:300]}"
                log.error(msg)
                return False, msg

            # 5xx or unexpected — retry
            msg = f"ADO PATCH {ado_id} got {resp.status_code} (attempt {attempt}/{retries})"
            log.warning(msg)

        except requests.exceptions.Timeout:
            msg = f"ADO PATCH {ado_id} timed out (attempt {attempt}/{retries})"
            log.warning(msg)
        except requests.exceptions.RequestException as e:
            msg = f"ADO PATCH {ado_id} network error: {e} (attempt {attempt}/{retries})"
            log.warning(msg)

        if attempt < retries:
            time.sleep(backoff ** (attempt - 1))

    final_msg = f"ADO write failed after {retries} attempts for work item {ado_id}"
    log.error(final_msg)
    return False, final_msg


# ── Field dict → patches builder ─────────────────────────────────────────────

def _build_patches(fields_dict: dict[str, Any]) -> list[dict]:
    """
    Convert platform field names to ADO JSON-Patch operations.
    Skips None values and unmapped fields.
    """
    patches = []
    for field, value in fields_dict.items():
        ado_path = FIELD_MAP.get(field)
        if ado_path is None:
            log.debug(f"[ado_write] no mapping for field '{field}' — skipped")
            continue
        if value is None:
            continue
        patches.append({
            "op":    "add",
            "path":  f"/fields/{ado_path}",
            "value": value,
        })
    return patches


# ── Public API ────────────────────────────────────────────────────────────────

def write_fields_sync(ado_id: int, fields_dict: dict[str, Any]) -> tuple[bool, str]:
    """
    Blocking write. Builds patch from fields_dict and calls patch_work_item.
    Returns (ok, error_msg).
    Use this when you need to confirm success before proceeding.
    """
    patches = _build_patches(fields_dict)
    if not patches:
        return True, ""
    return patch_work_item(ado_id, patches)


def _write_task(ado_id: int, fields_dict: dict[str, Any]) -> None:
    """Background thread target — runs write and records failures/successes."""
    ok, msg = write_fields_sync(ado_id, fields_dict)
    with _failures_lock:
        if ok:
            _successes.append({
                "ado_id": ado_id,
                "fields": list(fields_dict.keys()),
                "time":   time.strftime("%H:%M:%S"),
            })
        else:
            _failures.append({
                "ado_id":  ado_id,
                "fields":  list(fields_dict.keys()),
                "message": msg,
                "time":    time.strftime("%H:%M:%S"),
            })


def write_fields(ado_id: int, fields_dict: dict[str, Any]) -> None:
    """
    Fire-and-forget write. Returns immediately; write runs in background thread.
    Does NOT block the caller. Failures are queued for UI retrieval.

    Use this for all UI-triggered saves where local DB has already been updated.
    """
    if not ado_id:
        log.debug("[ado_write] write_fields called with no ado_id — skipped")
        return
    _executor.submit(_write_task, ado_id, fields_dict)


def get_pending_failures() -> list[dict]:
    """
    Return and clear all queued write failures.
    Each failure dict: {"ado_id": int, "fields": [str], "message": str, "time": str}
    """
    with _failures_lock:
        result = list(_failures)
        _failures.clear()
    return result


def get_pending_successes() -> list[dict]:
    """
    Return and clear all queued write successes.
    Each success dict: {"ado_id": int, "fields": [str], "time": str}
    """
    with _failures_lock:
        result = list(_successes)
        _successes.clear()
    return result


# ── Convenience wrappers ──────────────────────────────────────────────────────

def write_state(ado_id: int, state: str) -> None:
    """Fire-and-forget state change."""
    write_fields(ado_id, {"state": state})


def write_assignee(ado_id: int, display_name: str) -> None:
    """Fire-and-forget assignee change. display_name must match ADO identity."""
    write_fields(ado_id, {"assigned_to": display_name})


def write_iteration(ado_id: int, iteration_path: str) -> None:
    """
    Fire-and-forget iteration move.
    iteration_path must be the full ADO path e.g. 'Solo Expenses\\Iteration 2026 04-April'
    """
    write_fields(ado_id, {"iteration": iteration_path})


def write_estimate(ado_id: int, hours: float) -> None:
    """Fire-and-forget original estimate change."""
    write_fields(ado_id, {"original_estimate": hours})


# ── ADO item creation ─────────────────────────────────────────────────────────

# Platform entity → ADO work item type name
ENTITY_TYPE_MAP = {
    "feature": "Enhancement",
    "bug":     "Bug",
    "epic":    "Epic",
    "task":    "Task",
}

# Platform state → ADO state (Enhancement / Bug share similar states)
_STATE_MAP = {
    "Backlog":         "New",
    "In Planning":     "Active",
    "In Design":       "Active",
    "In Development":  "Active",
    "In QA":           "Active",
    "Done":            "Closed",
    "On Hold":         "Active",
    "Rejected":        "Closed",
    # Bug states — pass through directly
    "New":             "New",
    "Active":          "Active",
    "Resolved":        "Resolved",
    "Closed":          "Closed",
}


def _map_state(platform_state: str) -> str:
    return _STATE_MAP.get(platform_state, "Active")


def create_work_item(
    work_item_type: str,
    fields_dict: dict[str, Any],
    retries: int = 3,
    backoff: float = 2.0,
) -> tuple[int | None, str]:
    """
    Create a new work item in ADO and return its ID.

    work_item_type: ADO type string — "Enhancement", "Bug", "Epic"
    fields_dict: same platform field names as write_fields()

    Returns:
        (ado_id, "")           on success
        (None, error_message)  on failure
    """
    if not _PAT:
        return None, "AZURE_DEVOPS_PAT not set"

    patches = _build_patches(fields_dict)
    if not patches:
        return None, "No fields to write"

    # Map state through the state map if present
    for patch in patches:
        if patch["path"] == "/fields/System.State":
            patch["value"] = _map_state(patch["value"])

    org     = _ORG_URL.rstrip("/")
    wtype   = requests.utils.quote(work_item_type, safe="")
    project = requests.utils.quote(_PROJECT, safe="")
    url     = f"{org}/{project}/_apis/wit/workitems/${wtype}?api-version={_API_VER}"
    headers = _auth_header()

    for attempt in range(1, retries + 1):
        try:
            resp = requests.patch(url, headers=headers, json=patches, timeout=10)

            if resp.status_code in (200, 201):
                ado_id = resp.json().get("id")
                log.info(f"[ado_write] Created {work_item_type} → ADO #{ado_id}")
                return ado_id, ""

            if 400 <= resp.status_code < 500:
                msg = f"ADO create {work_item_type} failed {resp.status_code}: {resp.text[:300]}"
                log.error(msg)
                return None, msg

            log.warning(f"ADO create {work_item_type} got {resp.status_code} (attempt {attempt}/{retries})")

        except requests.exceptions.Timeout:
            log.warning(f"ADO create {work_item_type} timed out (attempt {attempt}/{retries})")
        except requests.exceptions.RequestException as e:
            log.warning(f"ADO create {work_item_type} error: {e} (attempt {attempt}/{retries})")

        if attempt < retries:
            time.sleep(backoff ** (attempt - 1))

    msg = f"ADO create failed after {retries} attempts for {work_item_type}"
    log.error(msg)
    return None, msg


def create_and_link_async(
    entity_type: str,
    local_id: int,
    fields_dict: dict[str, Any],
) -> None:
    """
    Fire-and-forget: create work item in ADO, then write ado_id back to local DB.

    entity_type: "feature" | "bug" | "epic"
    local_id:    the local DB primary key (feature_id / bug_id / epic_id)
    fields_dict: platform field names (same as write_fields)
    """
    work_item_type = ENTITY_TYPE_MAP.get(entity_type)
    if not work_item_type:
        log.warning(f"[ado_write] unknown entity_type '{entity_type}' — skipped")
        return

    def _task():
        ado_id, err = create_work_item(work_item_type, fields_dict)
        if ado_id:
            _link_ado_id(entity_type, local_id, ado_id)
        else:
            with _failures_lock:
                _failures.append({
                    "ado_id":  None,
                    "fields":  list(fields_dict.keys()),
                    "message": f"Create {work_item_type} failed: {err}",
                    "time":    time.strftime("%H:%M:%S"),
                })

    _executor.submit(_task)


def _link_ado_id(entity_type: str, local_id: int, ado_id: int) -> None:
    """Write the ADO-assigned ado_id back into the local DB record."""
    from data.loader import engine
    from sqlalchemy import text as _text

    table_map = {
        "feature": ("p_features", "feature_id"),
        "bug":     ("p_bugs",     "bug_id"),
        "epic":    ("p_epics",    "epic_id"),
        "task":    ("p_tasks",    "task_id"),
    }
    table, pk = table_map[entity_type]
    try:
        with engine.begin() as conn:
            conn.execute(
                _text(f"UPDATE {table} SET ado_id = :aid WHERE {pk} = :id"),
                {"aid": ado_id, "id": local_id}
            )
        log.info(f"[ado_write] Linked {entity_type} local#{local_id} → ADO#{ado_id}")
    except Exception as e:
        log.error(f"[ado_write] Failed to link ado_id: {e}")
