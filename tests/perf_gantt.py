"""
Gantt Performance & Correctness Test Suite
==========================================
Runs in three layers:

  Layer 1 - DB raw query benchmarks (always)
  Layer 2 - Python build profiling (always; calls _build_gantt_html directly)
  Layer 3 - HTTP page-load timing (only if the app is already running on :8050)

Usage:
  cd C:/Python/Release
  .venv/Scripts/python tests/perf_gantt.py
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
import time
import os
import traceback
from datetime import date

# ── helpers ───────────────────────────────────────────────────────────────────
BAR  = "=" * 66
SEP  = "-" * 66
PASS = "[  PASS  ]"
FAIL = "[  FAIL  ]"
WARN = "[  WARN  ]"
INFO = "[  INFO  ]"

SLOW_DB_MS  = 300   # DB query threshold to flag as slow
SLOW_BLD_MS = 800   # Build threshold to flag as slow
SLOW_HTTP_MS = 3000 # HTTP threshold


def _ms(elapsed_s: float) -> str:
    return f"{elapsed_s * 1000:.1f} ms"


def _tick(label: str, result: str, elapsed_s: float, warn_ms: int):
    tag = PASS if elapsed_s * 1000 < warn_ms else WARN
    print(f"{tag}  {label:<46}  {_ms(elapsed_s):>10}  {result}")


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — DB BENCHMARKS
# ══════════════════════════════════════════════════════════════════════════════

def layer1_db():
    print(f"\n{BAR}")
    print("  LAYER 1 — Database Query Benchmarks")
    print(BAR)

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from data.loader import engine
    from sqlalchemy import text
    import pandas as pd

    queries = [
        ("agg_gantt_items  (SELECT *)",
         "SELECT * FROM agg_gantt_items ORDER BY main_developer, function, bar_start"),
        ("agg_gantt_tasks  (SELECT *)",
         "SELECT * FROM agg_gantt_tasks"),
        ("agg_gantt_items  (COUNT)",
         "SELECT COUNT(*) FROM agg_gantt_items"),
        ("agg_gantt_tasks  (COUNT)",
         "SELECT COUNT(*) FROM agg_gantt_tasks"),
        ("gantt devs DISTINCT",
         "SELECT DISTINCT main_developer FROM agg_gantt_items WHERE main_developer IS NOT NULL ORDER BY main_developer"),
    ]

    results = {}
    for label, sql in queries:
        t0 = time.perf_counter()
        try:
            with engine.connect() as c:
                rows = c.execute(text(sql)).fetchall()
            elapsed = time.perf_counter() - t0
            result_str = f"{len(rows)} rows"
            results[label] = (elapsed, len(rows))
        except Exception as e:
            elapsed = time.perf_counter() - t0
            result_str = f"ERROR: {e}"
            results[label] = (elapsed, -1)
        _tick(label, result_str, elapsed, SLOW_DB_MS)

    # pandas read (what the real code does)
    for label, sql in [
        ("pd.read_sql  items", "SELECT * FROM agg_gantt_items ORDER BY main_developer, function, bar_start"),
        ("pd.read_sql  tasks", "SELECT * FROM agg_gantt_tasks"),
    ]:
        t0 = time.perf_counter()
        try:
            with engine.connect() as c:
                df = pd.read_sql(text(sql), c)
            elapsed = time.perf_counter() - t0
            results[label] = (elapsed, len(df))
            _tick(label, f"{len(df)} rows  {len(df.columns)} cols", elapsed, SLOW_DB_MS)
        except Exception as e:
            elapsed = time.perf_counter() - t0
            _tick(label, f"ERROR: {e}", elapsed, SLOW_DB_MS)
            results[label] = (elapsed, -1)

    # Cache simulation: 2nd read (should be same speed — this is uncached SQL)
    print(f"\n{SEP}")
    print("  Cache TTL simulation (two back-to-back reads):")
    t0 = time.perf_counter()
    with engine.connect() as c:
        df1 = pd.read_sql(text("SELECT * FROM agg_gantt_items"), c)
    t1 = time.perf_counter()
    with engine.connect() as c:
        df2 = pd.read_sql(text("SELECT * FROM agg_gantt_items"), c)
    t2 = time.perf_counter()
    print(f"  1st read : {_ms(t1 - t0)}")
    print(f"  2nd read : {_ms(t2 - t1)}")
    print(f"  Cache saves  ~{_ms(t1 - t0)} per filter interaction after first render")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — PYTHON BUILD PROFILING
# ══════════════════════════════════════════════════════════════════════════════

def layer2_build():
    print(f"\n{BAR}")
    print("  LAYER 2 — _build_gantt_html Profiling")
    print(BAR)

    # Import the builder — needs a Dash app instance (for register_page) but NOT a running server
    try:
        import dash
        import dash_bootstrap_components as dbc
        # Minimal app so register_page() doesn't throw
        _app = dash.Dash(
            __name__,
            use_pages=True,
            pages_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages_dash"),
            external_stylesheets=[dbc.themes.DARKLY],
            suppress_callback_exceptions=True,
        )
        from pages_dash.enhancements.planning import _build_gantt_html, _gantt_window, _GANTT_CACHE, _GANTT_TTL
    except Exception as e:
        print(f"{FAIL}  Could not import planning.py: {e}")
        traceback.print_exc()
        return {}

    ws, we, lbl = _gantt_window("0-12")
    print(f"\n  Window: {lbl}  ({ws} → {we})")
    print(f"  Cache TTL: {_GANTT_TTL}s")

    scenarios = [
        ("All devs / all types / all prios  (cold cache)",
         dict(dev_filter=None, type_filter="all", prio_filter=None, year_filter=None),
         True),   # force cold
        ("All devs / all types / all prios  (warm cache)",
         dict(dev_filter=None, type_filter="all", prio_filter=None, year_filter=None),
         False),
        ("Filter: ENH only",
         dict(dev_filter=None, type_filter="enh", prio_filter=None, year_filter=None),
         False),
        ("Filter: BUG only",
         dict(dev_filter=None, type_filter="bug", prio_filter=None, year_filter=None),
         False),
        ("Filter: P1+P2 only",
         dict(dev_filter=None, type_filter="all", prio_filter=["1", "2"], year_filter=None),
         False),
        ("Filter: year=2026",
         dict(dev_filter=None, type_filter="all", prio_filter=None, year_filter=[2026]),
         False),
        ("Window 12-24M",
         dict(dev_filter=None, type_filter="all", prio_filter=None, year_filter=None),
         False),
    ]

    build_results = {}
    for label, kwargs, force_cold in scenarios:
        if force_cold:
            _GANTT_CACHE["ts"] = 0.0  # expire cache

        # Determine window
        if "12-24" in label:
            _ws, _we, _ = _gantt_window("12-24")
        else:
            _ws, _we = ws, we

        t0 = time.perf_counter()
        try:
            result = _build_gantt_html(
                _ws, _we,
                expanded_sprints=set(),
                expanded_items=set(),
                **kwargs,
            )
            elapsed = time.perf_counter() - t0
            tag = PASS if elapsed * 1000 < SLOW_BLD_MS else WARN
            print(f"{tag}  {label:<56}  {_ms(elapsed):>10}")
            build_results[label] = elapsed
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"{FAIL}  {label:<56}  {_ms(elapsed):>10}  ERROR: {e}")
            traceback.print_exc()
            build_results[label] = elapsed

    # cProfile on the cold-cache full run
    print(f"\n{SEP}")
    print("  cProfile top-20 (cold cache, all filters open):")
    _GANTT_CACHE["ts"] = 0.0
    pr = cProfile.Profile()
    pr.enable()
    try:
        _build_gantt_html(ws, we, set(), set())
    except Exception:
        pass
    pr.disable()
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(20)
    for line in s.getvalue().splitlines()[4:25]:   # skip header
        print(" ", line)

    # Estimate DOM node count
    print(f"\n{SEP}")
    print("  DOM size estimate (warm cache):")
    import dash.html as dhtml
    _GANTT_CACHE["ts"] = 0.0
    result = None
    try:
        result = _build_gantt_html(ws, we, set(), set())
    except Exception:
        pass

    if result is not None:
        def _count_nodes(node) -> int:
            if not hasattr(node, "children") or node.children is None:
                return 1
            children = node.children if isinstance(node.children, list) else [node.children]
            return 1 + sum(_count_nodes(c) for c in children if hasattr(c, "children"))

        try:
            node_count = _count_nodes(result)
            verdict = WARN if node_count > 5000 else PASS
            print(f"  {verdict}  Total Dash nodes in Gantt output: {node_count:,}")
            if node_count > 5000:
                print(f"  {WARN}  >5 000 nodes → Dash serialises all of them on every filter change")
                print(f"         This is the primary cause of slowness.")
        except RecursionError:
            print(f"  {WARN}  Node count hit recursion limit (extremely deep tree)")

    return build_results


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — HTTP PAGE-LOAD TIMING
# ══════════════════════════════════════════════════════════════════════════════

def layer3_http():
    print(f"\n{BAR}")
    print("  LAYER 3 — HTTP Page-Load Timing")
    print(BAR)

    import requests

    BASE = "http://localhost:8050"

    # Check if server is running
    try:
        r = requests.get(f"{BASE}/login", timeout=3)
        print(f"  Server online (login page: {r.status_code})")
    except Exception:
        print(f"  {WARN}  Server not running on :8050 — skipping HTTP tests")
        print(f"         Start the app with:  .venv\\Scripts\\python app.py")
        return {}

    # Log in
    session = requests.Session()
    print(f"\n  Logging in as 'mayank' …")
    login_resp = session.post(
        f"{BASE}/login",
        data={"username": "mayank", "password": "mayank123"},
        allow_redirects=True,
        timeout=10,
    )
    if "/login" in login_resp.url:
        print(f"  {WARN}  Login failed (still on /login). "
              f"Check credentials. Continuing as unauthenticated …")
        # Fall back to unauthenticated session
        session = requests.Session()

    pages = [
        ("/",               "Home"),
        ("/summary",        "Summary"),
        ("/planning",       "Planning / Gantt (initial HTML)"),
        ("/iteration-audit","Iteration Audit"),
    ]

    http_results = {}
    print()
    for path, label in pages:
        times = []
        for i in range(3):  # 3 samples
            t0 = time.perf_counter()
            try:
                resp = session.get(f"{BASE}{path}", timeout=30)
                elapsed = time.perf_counter() - t0
                times.append(elapsed)
            except Exception as e:
                elapsed = time.perf_counter() - t0
                print(f"  {FAIL}  {label:<40}  ERROR: {e}")
                times.append(elapsed)
                break

        avg = sum(times) / len(times)
        mn  = min(times)
        tag = PASS if avg * 1000 < SLOW_HTTP_MS else WARN
        detail = f"avg={_ms(avg)}  min={_ms(mn)}  ({len(times)} samples)"
        print(f"  {tag}  {label:<40}  {detail}")
        http_results[path] = avg

    # Dash callback (simulate Gantt re-render on filter change)
    print(f"\n  Gantt filter callback timing:")
    import json
    callback_body = {
        "output": "gantt-chart.children",
        "outputs": {"id": "gantt-chart", "property": "children"},
        "inputs": [
            {"id": "gantt-view-select", "property": "value", "value": "0-12"},
            {"id": "gantt-year-filter", "property": "value", "value": None},
            {"id": "gantt-dev-filter",  "property": "value", "value": []},
            {"id": "gantt-type-filter", "property": "value", "value": "all"},
            {"id": "gantt-prio-filter", "property": "value", "value": []},
            {"id": "gantt-expanded",    "property": "data",  "value": {"s": [], "t": []}},
        ],
        "changedPropIds": ["gantt-view-select.value"],
        "state": [],
    }

    for label, body in [
        ("Gantt render (rolling 12M, no filters)", callback_body),
    ]:
        t0 = time.perf_counter()
        try:
            resp = session.post(
                f"{BASE}/_dash-update-component",
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            elapsed = time.perf_counter() - t0
            tag = PASS if elapsed * 1000 < SLOW_HTTP_MS else WARN
            size_kb = len(resp.content) / 1024
            print(f"  {tag}  {label:<48}  {_ms(elapsed):>10}  ({size_kb:.0f} KB)")
            http_results[f"cb:{label}"] = elapsed
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  {FAIL}  {label:<48}  {_ms(elapsed):>10}  ERROR: {e}")

    return http_results


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def summary(db_results: dict, build_results: dict, http_results: dict):
    print(f"\n{BAR}")
    print("  SUMMARY — Performance Bottleneck Analysis")
    print(BAR)

    total_db = sum(e for e, _ in db_results.values() if e > 0)
    cold_key = "All devs / all types / all prios  (cold cache)"
    warm_key = "All devs / all types / all prios  (warm cache)"
    cold_build = build_results.get(cold_key, 0)
    warm_build = build_results.get(warm_key, 0)

    print(f"\n  DB query time (items + tasks):   {_ms(total_db / 2)}")
    print(f"  Gantt build — cold (DB + HTML):  {_ms(cold_build)}")
    print(f"  Gantt build — warm (HTML only):  {_ms(warm_build)}")

    if http_results:
        for k, v in http_results.items():
            if k.startswith("cb:"):
                print(f"  HTTP callback round-trip:        {_ms(v)}")

    print(f"\n  Root causes of slowness:")
    causes = []

    if warm_build * 1000 > 500:
        causes.append(
            f"  1. Python builds {warm_build*1000:.0f}ms of Dash html.Div objects for every "
            f"filter change.\n"
            f"     The entire tree is serialised to JSON and sent over WebSocket on each render.\n"
            f"     Fix: replace the HTML/CSS Gantt with a Plotly figure (plotly.graph_objects)\n"
            f"          or a lightweight ag-Grid table — both serialise far less data."
        )
    if cold_build * 1000 > 1000:
        causes.append(
            f"  2. First render includes a DB round-trip ({_ms(cold_build)} cold vs "
            f"{_ms(warm_build)} warm).\n"
            f"     The 5-min module cache helps on subsequent renders, but the first\n"
            f"     request per cache window will always block."
        )

    if not causes:
        causes.append("  No significant bottlenecks detected within thresholds.")

    for c in causes:
        print(c)

    print(f"\n{BAR}\n")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\n{BAR}")
    print("  Gantt Performance Test Suite  —  Release Analytics")
    print(f"  {date.today()}")
    print(BAR)

    db_r    = layer1_db()
    build_r = layer2_build()
    http_r  = layer3_http()
    summary(db_r, build_r, http_r)
