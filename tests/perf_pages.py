"""
Page Performance Test Suite
============================
Measures where time is actually being lost across three layers.

Layer 1 — Python (no server): DB reads, load_data, key render functions
Layer 2 — HTTP (server needed): page load times, authenticated
Layer 3 — Dash callbacks (server needed): filter changes, tab switches

Run with server already started:
  cd C:/Python/Release
  .venv/Scripts/python tests/perf_pages.py

Run without server (layer 1 only):
  .venv/Scripts/python tests/perf_pages.py --no-server
"""

from __future__ import annotations
import sys, os, time, json, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE      = "http://127.0.0.1:8050"   # avoid Windows IPv6→IPv4 fallback (~2s penalty)
N_REPS    = 3
BAR       = "=" * 70
SEP       = "-" * 70
NO_SERVER = "--no-server" in sys.argv

# Password: pass --password=yourpassword  OR set env var PERF_PASSWORD
_pw_arg = next((a.split("=",1)[1] for a in sys.argv if a.startswith("--password=")), None)
CREDS = {
    "username": "mayank",
    "password": _pw_arg or os.environ.get("PERF_PASSWORD", ""),
}

# ── colour/tag helpers ─────────────────────────────────────────────────────────
def _tag(ms, warn=1000, bad=3000):
    if ms < warn:  return "[  OK  ]"
    if ms < bad:   return "[ SLOW ]"
    return                "[ VERY ]"

def _row(label, ms_list):
    avg = statistics.mean(ms_list)
    mn  = min(ms_list)
    mx  = max(ms_list)
    tag = _tag(avg)
    samples = "  ".join(f"{m:.0f}" for m in ms_list)
    print(f"  {tag}  {label:<52}  avg={avg:>6.0f}ms  [{samples}]")
    return avg

def _header(title):
    print(f"\n{BAR}")
    print(f"  {title}")
    print(BAR)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — Python benchmarks (always run)
# ══════════════════════════════════════════════════════════════════════════════

def layer1_python():
    _header("LAYER 1 — Python Function Benchmarks (no server)")

    import data.loader as _dl
    from data.loader import load_data, engine
    from sqlalchemy import text

    # ── load_data ─────────────────────────────────────────────────────────────
    print("\n  load_data() :")
    _dl._DATA_CACHE = None
    _dl._REL_MAP_CACHE = None
    t0 = time.perf_counter(); load_data(); cold = (time.perf_counter()-t0)*1000
    t0 = time.perf_counter(); load_data(); warm = (time.perf_counter()-t0)*1000
    print(f"    cold (DB + rel_map): {cold:.0f}ms")
    print(f"    warm (cache copy):   {warm:.0f}ms")

    # ── Key DB queries ─────────────────────────────────────────────────────────
    print("\n  DB queries (raw):")
    queries = {
        "work_items_main (full load)":
            "SELECT * FROM work_items_main WHERE created_date>='2025-01-01' OR closed_date>='2025-01-01' OR changed_date>='2025-01-01'",
        "agg_gantt_items":
            "SELECT * FROM agg_gantt_items",
        "agg_dev_monthly_capacity":
            "SELECT * FROM agg_dev_monthly_capacity",
        "agg_standalone_overhead":
            "SELECT * FROM agg_standalone_overhead",
        "p_dev_leaves + holidays":
            "SELECT COUNT(*) FROM p_dev_leaves; SELECT COUNT(*) FROM p_company_holidays",
    }
    for label, sql in queries.items():
        try:
            t0 = time.perf_counter()
            with engine.connect() as c:
                for s in sql.split(";"):
                    c.execute(text(s.strip())).fetchall()
            ms = (time.perf_counter()-t0)*1000
            print(f"    {_tag(ms,100,500)}  {label:<45}  {ms:>6.0f}ms")
        except Exception as e:
            print(f"    [ ERR ]  {label}: {e}")

    # ── Gantt builder ──────────────────────────────────────────────────────────
    print("\n  _build_gantt_html() :")
    try:
        import dash, dash_bootstrap_components as dbc
        _app = dash.Dash(
            "test", use_pages=True,
            pages_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages_dash"),
            external_stylesheets=[dbc.themes.DARKLY],
            suppress_callback_exceptions=True,
        )
        from pages_dash.enhancements.planning import _build_gantt_html, _gantt_window, _GANTT_CACHE

        _GANTT_CACHE["ts"] = 0.0
        ws, we, _ = _gantt_window("0-12")
        t0 = time.perf_counter()
        _build_gantt_html(ws, we, set(), set())
        cold = (time.perf_counter()-t0)*1000

        t0 = time.perf_counter()
        _build_gantt_html(ws, we, set(), set())
        warm = (time.perf_counter()-t0)*1000

        print(f"    cold (DB + build): {cold:.0f}ms")
        print(f"    warm (cache):      {warm:.0f}ms")
    except Exception as e:
        print(f"    [ ERR ]  {e}")

    # ── Capacity render ────────────────────────────────────────────────────────
    print("\n  capacity_planner helpers :")
    try:
        from pages_dash.enhancements.capacity_planner import (
            _load_cap_agg, _load_top_items,
            _load_standalone_data, _months012, _ym,
        )
        from datetime import date as _date
        m012 = _months012()
        yms  = [_ym(d) for d in m012]

        for label, fn in [
            ("_load_cap_agg (All)",      lambda: _load_cap_agg(yms, "All")),
            ("_load_cap_agg (Customer)", lambda: _load_cap_agg(yms, "Customer")),
            ("_load_top_items",          lambda: _load_top_items(yms)),
            ("_load_standalone_data",    lambda: _load_standalone_data(yms)),
        ]:
            t0 = time.perf_counter(); fn(); ms = (time.perf_counter()-t0)*1000
            print(f"    {_tag(ms,50,200)}  {label:<40}  {ms:>6.0f}ms")
    except Exception as e:
        print(f"    [ ERR ]  {e}")


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — HTTP page loads
# ══════════════════════════════════════════════════════════════════════════════

def layer2_http(session):
    _header("LAYER 2 — HTTP Page Load Times")

    pages = [
        ("/",               "Home"),
        ("/summary",        "Summary"),
        ("/planning",       "Planning Tool (initial HTML)"),
        ("/iteration-audit","Iteration Audit"),
        ("/leave-management","Leave Manager"),
        ("/reports",        "Reports"),
    ]

    print()
    for path, label in pages:
        times = []
        for _ in range(N_REPS):
            t0 = time.perf_counter()
            try:
                r = session.get(f"{BASE}{path}", timeout=30)
                times.append((time.perf_counter()-t0)*1000)
            except Exception as e:
                print(f"  [ ERR ]  {label}: {e}")
                break
        if times:
            _row(label, times)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Dash callback response times
# ══════════════════════════════════════════════════════════════════════════════

def _cb(session, output_id, output_prop, inputs, changed_id):
    """Fire a Dash callback and return (status_code, elapsed_ms, response_kb)."""
    import requests as _req
    body = {
        "output":          f"{output_id}.{output_prop}",
        "outputs":         {"id": output_id, "property": output_prop},
        "inputs":          inputs,
        "changedPropIds":  [changed_id],
        "state":           [],
    }
    time.sleep(0.3)   # small gap — debug server is single-threaded
    for attempt in range(3):
        try:
            t0 = time.perf_counter()
            r  = session.post(
                f"{BASE}/_dash-update-component",
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            ms = (time.perf_counter()-t0)*1000
            return r.status_code, ms, len(r.content)/1024
        except (_req.exceptions.ConnectionError, _req.exceptions.Timeout):
            if attempt == 2:
                return 0, -1, 0
            time.sleep(1)


def layer3_callbacks(session):
    _header("LAYER 3 — Dash Callback Response Times")

    print("\n  Planning Tool — tab switches:")

    # Tab switch: Developer Capacity
    tab_inputs = [
        {"id": "plan-main-tab", "property": "data", "value": "devcap"},
    ]
    times = []
    for _ in range(N_REPS):
        sc, ms, kb = _cb(
            session,
            "dcap-grid", "children",
            [{"id": "dcap-view",           "property": "data",  "value": "All"},
             {"id": "dcap-tab",            "property": "data",  "value": "012"},
             {"id": "dcap-gantt-show-all", "property": "data",  "value": False},
             {"id": "gantt-cust-filter",   "property": "value", "value": "all"},
             {"id": "plan-main-tab",       "property": "data",  "value": "devcap"}],
            "plan-main-tab.data",
        )
        times.append(ms)
    _row("Developer Capacity tab (first render)", times)

    # Capacity filter: Enhancements
    times = []
    for _ in range(N_REPS):
        sc, ms, kb = _cb(
            session,
            "dcap-grid", "children",
            [{"id": "dcap-view",           "property": "data",  "value": "Enhancements"},
             {"id": "dcap-tab",            "property": "data",  "value": "012"},
             {"id": "dcap-gantt-show-all", "property": "data",  "value": False},
             {"id": "gantt-cust-filter",   "property": "value", "value": "all"},
             {"id": "plan-main-tab",       "property": "data",  "value": "devcap"}],
            "dcap-view.data",
        )
        times.append(ms)
    _row("Capacity filter: All Work → Enhancements", times)

    # Customer/Internal filter
    times = []
    for _ in range(N_REPS):
        sc, ms, kb = _cb(
            session,
            "dcap-grid", "children",
            [{"id": "dcap-view",           "property": "data",  "value": "All"},
             {"id": "dcap-tab",            "property": "data",  "value": "012"},
             {"id": "dcap-gantt-show-all", "property": "data",  "value": False},
             {"id": "gantt-cust-filter",   "property": "value", "value": "Customer"},
             {"id": "plan-main-tab",       "property": "data",  "value": "devcap"}],
            "gantt-cust-filter.value",
        )
        times.append(ms)
    _row("Capacity filter: All → Customer", times)

    print("\n  Gantt chart:")
    gantt_inputs = [
        {"id": "gantt-view-select", "property": "value",  "value": "0-12"},
        {"id": "plan-main-tab",     "property": "data",   "value": "devcap"},
        {"id": "gantt-type-filter", "property": "value",  "value": "all"},
        {"id": "gantt-prio-filter", "property": "value",  "value": []},
    ]
    for label, changed, override in [
        ("Initial render (tab switch)",    "plan-main-tab.data",     {}),
        ("Filter: Enhancements only",      "gantt-type-filter.value",{"gantt-type-filter":"enh"}),
        ("Filter: back to All",            "gantt-type-filter.value",{"gantt-type-filter":"all"}),
        ("Window: 12-24M",                 "gantt-view-select.value",{"gantt-view-select":"12-24"}),
    ]:
        inp = [dict(i) for i in gantt_inputs]
        for item in inp:
            key = item["id"]
            if key in override:
                item["value"] = override[key]
        times = []
        for _ in range(N_REPS):
            sc, ms, kb = _cb(session, "gantt-chart", "children", inp, changed)
            times.append(ms)
        _row(label, times)

    print("\n  Summary page:")
    times = []
    for _ in range(N_REPS):
        sc, ms, kb = _cb(
            session, "summary-content", "children",
            [{"id": "url-location", "property": "pathname", "value": "/summary"}],
            "url-location.pathname",
        )
        times.append(ms)
    _row("Summary page render", times)


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def summary(results: dict):
    _header("SUMMARY — Bottleneck Ranking")
    print()
    ranked = sorted(results.items(), key=lambda x: -x[1])
    for label, ms in ranked:
        bar = "█" * min(int(ms / 100), 40)
        tag = _tag(ms)
        print(f"  {tag}  {ms:>6.0f}ms  {bar}  {label}")

    print(f"\n  Thresholds:  OK < 1000ms   SLOW < 3000ms   VERY >= 3000ms")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{BAR}")
    print("  Page Performance Test Suite — Release Analytics")
    print(f"  {'Python layer only' if NO_SERVER else 'All layers (server must be running)'}")
    print(BAR)

    layer1_python()

    if NO_SERVER:
        print(f"\n  Skipping HTTP/callback layers (--no-server).\n")
        sys.exit(0)

    # Check server
    import requests
    try:
        requests.get(f"{BASE}/login", timeout=3)
    except Exception:
        print(f"\n  Server not running on :8050")
        print(f"  Start with:  .venv/Scripts/python app.py")
        print(f"  Then re-run this script.\n")
        sys.exit(1)

    # Login
    session = requests.Session()
    print(f"\n  Logging in as '{CREDS['username']}'...")
    r = session.post(f"{BASE}/login", data=CREDS, allow_redirects=True, timeout=10)
    if "/login" in r.url:
        print("  Login failed — check CREDS at top of script.")
        sys.exit(1)
    print("  Logged in OK.\n")

    layer2_http(session)
    cb_results = {}

    layer3_callbacks(session)
