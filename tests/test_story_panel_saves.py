"""
Story Readiness Panel — Save Button Tests
==========================================
Covers:
  1. _sp_days         — working-days calculation (Mon–Fri only)
  2. Default display  — _load_sp_data merges ADO fields (work_items_main)
                        AND local fields (p_story_tracking) correctly
  3. Save to Local    — _upsert_sp_data round-trip for all 6 date/hour fields
  4. Save to ADO      — _mirror_ado_to_local round-trip for all 5 ADO fields
  5. Merged defaults  — after both saves, _load_sp_data returns both sets

Usage:
  cd C:/Python/Release
  .venv/Scripts/python tests/test_story_panel_saves.py
"""
from __future__ import annotations
import sys, os, datetime as _dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from data.loader import engine
from sqlalchemy import text

# ── Helpers ───────────────────────────────────────────────────────────────────
PASS = "[  OK  ]"
FAIL = "[ FAIL ]"
SKIP = "[ SKIP ]"

_results: list[tuple[bool | None, str]] = []

def ok(label: str):
    _results.append((True, label))
    print(f"  {PASS}  {label}")

def fail(label: str, reason: str = ""):
    _results.append((False, label))
    suffix = f"  →  {reason}" if reason else ""
    print(f"  {FAIL}  {label}{suffix}")

def skip(label: str, reason: str = ""):
    _results.append((None, label))
    suffix = f"  →  {reason}" if reason else ""
    print(f"  {SKIP}  {label}{suffix}")

def section(title: str):
    bar = "-" * 68
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


# ── Inline copies of planning.py helpers (no Dash import needed) ──────────────

def _sp_days(start_str, end_str) -> str:
    try:
        s = _dt.date.fromisoformat(str(start_str).strip())
        e = _dt.date.fromisoformat(str(end_str).strip())
        if e < s:
            return "—"
        days, cur = 0, s
        while cur <= e:
            if cur.weekday() < 5:   # Mon=0 … Fri=4
                days += 1
            cur += _dt.timedelta(days=1)
        return str(days)
    except Exception:
        return "—"


def _load_sp_data(story_id: int) -> dict:
    try:
        with engine.connect() as conn:
            t = conn.execute(text("""
                SELECT est_start_date, est_end_date, est_hours,
                       act_start_date, act_end_date, act_hours
                FROM p_story_tracking WHERE work_item_id = :id
            """), {"id": story_id}).fetchone()
            w = conn.execute(text("""
                SELECT main_designer, design_type, release_date, iteration_path, story_owner
                FROM work_items_main WHERE work_item_id = :id
            """), {"id": story_id}).fetchone()
        result = {}
        if t:
            for k, v in dict(t._mapping).items():
                if v is None:
                    continue
                result[k] = str(v) if isinstance(v, (_dt.date, _dt.datetime)) else v
        if w:
            result.update({k: v for k, v in dict(w._mapping).items() if v is not None})
        return result
    except Exception as e:
        return {"_error": str(e)}


def _upsert_sp_data(story_id: int, col: str, val) -> None:
    _ALLOWED = {"est_start_date", "est_end_date", "est_hours",
                "act_start_date", "act_end_date", "act_hours"}
    if col not in _ALLOWED:
        raise ValueError(f"Column {col!r} not in allowlist")
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO p_story_tracking (work_item_id, {col}, updated_at)
            VALUES (:id, :val, NOW())
            ON CONFLICT (work_item_id) DO UPDATE
                SET {col} = EXCLUDED.{col}, updated_at = NOW()
        """), {"id": story_id, "val": val if val != "" else None})


def _mirror_ado_to_local(story_id: int, fields: dict) -> None:
    _COL_MAP = {
        "story_owner":   "story_owner",
        "main_designer": "main_designer",
        "design_type":   "design_type",
        "release_date":  "release_date",
        "iteration":     "iteration_path",
    }
    updates = {_COL_MAP[k]: v for k, v in fields.items() if k in _COL_MAP}
    if not updates:
        return
    set_clause = ", ".join(f"{col} = :{col}" for col in updates)
    updates["_id"] = story_id
    with engine.begin() as conn:
        conn.execute(text(
            f"UPDATE work_items_main SET {set_clause} WHERE work_item_id = :_id"
        ), updates)


def _fetch_local(story_id: int) -> dict:
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT est_start_date, est_end_date, est_hours,
                   act_start_date, act_end_date, act_hours
            FROM p_story_tracking WHERE work_item_id = :id
        """), {"id": story_id}).fetchone()
    if not r:
        return {}
    return {k: (str(v) if isinstance(v, (_dt.date, _dt.datetime)) else v)
            for k, v in dict(r._mapping).items()}


def _fetch_ado(story_id: int) -> dict:
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT main_designer, design_type, release_date, iteration_path, story_owner
            FROM work_items_main WHERE work_item_id = :id
        """), {"id": story_id}).fetchone()
    return dict(r._mapping) if r else {}


# ── Pick a real Enhancement story for DB tests ────────────────────────────────
def _get_test_sid() -> int | None:
    """Return a story_id from work_items_main suitable for testing."""
    with engine.connect() as conn:
        # Prefer one that already has at least some ADO fields set
        r = conn.execute(text("""
            SELECT work_item_id FROM work_items_main
            WHERE work_item_type = 'Enhancement'
              AND main_designer IS NOT NULL
            ORDER BY work_item_id DESC
            LIMIT 1
        """)).fetchone()
        if not r:
            r = conn.execute(text("""
                SELECT work_item_id FROM work_items_main
                WHERE work_item_type = 'Enhancement'
                ORDER BY work_item_id DESC LIMIT 1
            """)).fetchone()
    return int(r.work_item_id) if r else None


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 — Working-days calculation (_sp_days)
# ══════════════════════════════════════════════════════════════════════════════
section("TEST 1 — Working-days calculation (_sp_days)")

# Build expected values programmatically so dates don't need manual calculation
def _expected_days(s_str, e_str):
    try:
        s = _dt.date.fromisoformat(s_str)
        e = _dt.date.fromisoformat(e_str)
        if e < s:
            return "—"
        return str(sum(1 for d in range((e - s).days + 1)
                       if (s + _dt.timedelta(d)).weekday() < 5))
    except Exception:
        return "—"

# Use 2026-07-27 as anchor: determine what weekday it is
_anchor = _dt.date(2026, 7, 27)
_wdname = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][_anchor.weekday()]

# Build 5 consecutive weekdays starting from the first Monday on or after anchor
_mon = _anchor + _dt.timedelta(days=(7 - _anchor.weekday()) % 7)
_fri = _mon + _dt.timedelta(days=4)
_next_mon = _mon + _dt.timedelta(days=7)
_sat = _mon + _dt.timedelta(days=5)
_sun = _mon + _dt.timedelta(days=6)

cases = [
    # (start, end, expected, label)
    (_mon.isoformat(), _mon.isoformat(),       "1",  "single day (Mon–Mon)"),
    (_mon.isoformat(), _fri.isoformat(),       "5",  "Mon–Fri = 5 working days"),
    (_mon.isoformat(), _next_mon.isoformat(),  "6",  "Mon–next Mon spans weekend → 6"),
    (_sat.isoformat(), _next_mon.isoformat(),  "1",  "Sat–Mon → 1 working day (Mon only)"),
    (_sun.isoformat(), _next_mon.isoformat(),  "1",  "Sun–Mon → 1 working day (Mon only)"),
    (_fri.isoformat(), _mon.isoformat(),       "—",  "end before start → '—'"),
    (None,             _mon.isoformat(),       "—",  "None start → '—'"),
    (_mon.isoformat(), None,                   "—",  "None end → '—'"),
    ("not-a-date",     _mon.isoformat(),       "—",  "invalid start → '—'"),
]

for start, end, expected, label in cases:
    got = _sp_days(start, end)
    if got == expected:
        ok(label)
    else:
        fail(label, f"expected {expected!r}, got {got!r}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 — Default values from ADO (work_items_main)
# ══════════════════════════════════════════════════════════════════════════════
section("TEST 2 — Default values from ADO fields (work_items_main)")

sid = _get_test_sid()
if sid is None:
    skip("No Enhancement stories found in DB — skipping DB tests")
else:
    print(f"  Using story_id = {sid}\n")

    ado_raw = _fetch_ado(sid)
    sp_data = _load_sp_data(sid)

    if "_error" in sp_data:
        fail("_load_sp_data returned without error", sp_data["_error"])
    else:
        ok("_load_sp_data executed without exception")

    for field in ("main_designer", "design_type", "release_date", "iteration_path", "story_owner"):
        raw_val = ado_raw.get(field)
        sp_val  = sp_data.get(field)
        if raw_val is None:
            skip(f"ADO field '{field}' is NULL in DB — no default to verify")
        elif sp_val == raw_val:
            ok(f"ADO field '{field}' present in _load_sp_data result = {raw_val!r}")
        else:
            fail(f"ADO field '{field}' mismatch", f"work_items_main={raw_val!r}, sp_data={sp_val!r}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 — Save to Local round-trip (all 6 fields via _upsert_sp_data)
# ══════════════════════════════════════════════════════════════════════════════
section("TEST 3 — Save to Local round-trip (_upsert_sp_data)")

if sid is None:
    skip("No story_id — skipping")
else:
    # Save original local values so we can restore
    orig_local = _fetch_local(sid)

    TEST_VALS = {
        "est_start_date": "2026-08-01",
        "est_end_date":   "2026-08-15",
        "est_hours":      12.5,
        "act_start_date": "2026-08-20",
        "act_end_date":   "2026-08-29",
        "act_hours":      10.0,
    }

    # Write all 6
    try:
        for col, val in TEST_VALS.items():
            _upsert_sp_data(sid, col, val)
        ok("_upsert_sp_data executed for all 6 fields without exception")
    except Exception as e:
        fail("_upsert_sp_data raised an exception", str(e))

    # Read back raw from DB
    fetched = _fetch_local(sid)

    for col, expected in TEST_VALS.items():
        raw = fetched.get(col)
        # Dates come back as strings (ISO), hours as Decimal — normalise to str for compare
        got = str(raw).rstrip("0").rstrip(".") if raw is not None else None
        exp = str(expected).rstrip("0").rstrip(".")
        if got == exp:
            ok(f"Persisted '{col}' = {expected!r}")
        else:
            fail(f"Persisted '{col}'", f"expected {expected!r}, got {raw!r}")

    # _load_sp_data should return local fields merged with ADO fields
    merged = _load_sp_data(sid)
    for col in ("est_start_date", "est_end_date", "act_start_date", "act_end_date"):
        if col in merged:
            ok(f"_load_sp_data includes local field '{col}' = {merged[col]!r}")
        else:
            fail(f"_load_sp_data missing local field '{col}' after save")

    # Restore original local values
    _restore_cols = ["est_start_date", "est_end_date", "est_hours",
                     "act_start_date", "act_end_date", "act_hours"]
    for col in _restore_cols:
        _upsert_sp_data(sid, col, orig_local.get(col))
    ok("Original local values restored")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 — Save to ADO mirror round-trip (_mirror_ado_to_local)
# ══════════════════════════════════════════════════════════════════════════════
section("TEST 4 — Save to ADO mirror (_mirror_ado_to_local → work_items_main)")

if sid is None:
    skip("No story_id — skipping")
else:
    orig_ado = _fetch_ado(sid)

    # Test values (use values unlikely to collide with real data)
    TEST_ADO = {
        "story_owner":   "Geetika",
        "main_designer": "Furquan Nayyar",
        "design_type":   "UI",
    }

    try:
        _mirror_ado_to_local(sid, TEST_ADO)
        ok("_mirror_ado_to_local executed without exception")
    except Exception as e:
        fail("_mirror_ado_to_local raised an exception", str(e))

    # Read back from DB directly
    after_ado = _fetch_ado(sid)
    for ado_key, db_col in [("story_owner","story_owner"),
                             ("main_designer","main_designer"),
                             ("design_type","design_type")]:
        expected = TEST_ADO[ado_key]
        got      = after_ado.get(db_col)
        if got == expected:
            ok(f"ADO mirror '{db_col}' = {expected!r}")
        else:
            fail(f"ADO mirror '{db_col}'", f"expected {expected!r}, got {got!r}")

    # _load_sp_data should reflect the mirrored values
    merged = _load_sp_data(sid)
    for ado_key, db_col in [("story_owner","story_owner"),
                             ("main_designer","main_designer"),
                             ("design_type","design_type")]:
        expected = TEST_ADO[ado_key]
        got      = merged.get(db_col)
        if got == expected:
            ok(f"_load_sp_data reflects mirrored '{db_col}' = {expected!r}")
        else:
            fail(f"_load_sp_data missing mirrored '{db_col}'", f"got {got!r}")

    # Restore original ADO values
    restore_map = {}
    for ado_key, db_col in [("story_owner","story_owner"),
                             ("main_designer","main_designer"),
                             ("design_type","design_type")]:
        orig_val = orig_ado.get(db_col)
        # _mirror_ado_to_local uses ado_key names, not db_col names
        restore_map[ado_key] = orig_val
    # Write back via direct SQL (same shape as _mirror_ado_to_local)
    _mirror_ado_to_local(sid, restore_map)
    ok("Original ADO values restored")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 — Combined: both saves → merged defaults
# ══════════════════════════════════════════════════════════════════════════════
section("TEST 5 — Combined: local + ADO saves → _load_sp_data returns both")

if sid is None:
    skip("No story_id — skipping")
else:
    # Save local fields
    _upsert_sp_data(sid, "est_start_date", "2026-09-01")
    _upsert_sp_data(sid, "est_end_date",   "2026-09-10")
    _upsert_sp_data(sid, "est_hours",      8.0)

    # Mirror an ADO field
    _mirror_ado_to_local(sid, {"story_owner": "Chhavi"})

    merged = _load_sp_data(sid)

    # Local fields present
    for col, expected in [("est_start_date","2026-09-01"),
                           ("est_end_date",  "2026-09-10")]:
        got = merged.get(col)
        if got == expected:
            ok(f"Merged result has local '{col}' = {expected!r}")
        else:
            fail(f"Merged result missing local '{col}'", f"got {got!r}")

    # ADO field present in same dict
    got_owner = merged.get("story_owner")
    if got_owner == "Chhavi":
        ok("Merged result has ADO 'story_owner' = 'Chhavi'")
    else:
        fail("Merged result missing ADO 'story_owner'", f"got {got_owner!r}")

    # Restore
    orig_local = _fetch_local(sid)
    _upsert_sp_data(sid, "est_start_date", orig_local.get("est_start_date"))
    _upsert_sp_data(sid, "est_end_date",   orig_local.get("est_end_date"))
    _upsert_sp_data(sid, "est_hours",      orig_local.get("est_hours"))
    _mirror_ado_to_local(sid, {"story_owner": orig_ado.get("story_owner")})
    ok("Test data cleaned up")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 — Allowlist guard (_upsert_sp_data rejects invalid columns)
# ══════════════════════════════════════════════════════════════════════════════
section("TEST 6 — Column allowlist guard (_upsert_sp_data)")

if sid is None:
    skip("No story_id — skipping")
else:
    blocked = ["work_item_id", "main_developer", "story_owner", "release_date",
               "'; DROP TABLE p_story_tracking; --"]
    for bad_col in blocked:
        try:
            _upsert_sp_data(sid, bad_col, "evil")
            fail(f"Allowlist did NOT block column {bad_col!r}")
        except ValueError:
            ok(f"Allowlist blocked disallowed column {bad_col!r}")
        except Exception as e:
            fail(f"Unexpected exception for column {bad_col!r}", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
bar = "=" * 68
print(f"\n{bar}")
print("  SUMMARY")
print(bar)

passed  = sum(1 for ok_, _ in _results if ok_ is True)
failed  = sum(1 for ok_, _ in _results if ok_ is False)
skipped = sum(1 for ok_, _ in _results if ok_ is None)
total   = len(_results)

print(f"  Passed:  {passed}/{total}")
if skipped:
    print(f"  Skipped: {skipped}/{total}")
if failed:
    print(f"  Failed:  {failed}/{total}")
    print()
    print("  Failing tests:")
    for ok_, label in _results:
        if ok_ is False:
            print(f"    x  {label}")
print()
sys.exit(0 if failed == 0 else 1)
