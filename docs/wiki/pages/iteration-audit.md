# Iteration Audit

- **Route / entry point**: `/iteration-audit`
- **Backing file(s)**: `pages_dash/misc/iteration_audit.py` (layout/rendering),
  `db/iteration_audit.py` (data fetch)
- **Nav location**: **not in nav.** Confirmed by reading `app.py`'s
  `_NAV_TREE` (`app.py:96-124`) end to end — no entry for `/iteration-audit`
  in any section. It is also not linked from anywhere else: a repo-wide search
  of `pages_dash/` for `iteration-audit` turns up only the
  `dash.register_page(...)` call in the file itself
  (`iteration_audit.py:13`) — no `dcc.Link`/`html.A` anywhere points at this
  route. **Orphan route** — registered with Dash but reachable only by typing
  the URL directly.

## What it does

Renders a static, read-only "Iteration Audit Report" for one sprint month —
formatted like a management post-mortem document rather than an interactive
dashboard: a cover page with an overall RED/AMBER/GREEN verdict, a stats
strip, a sprint-summary section (KPI cards, finding cards, "immediate actions
required" list), then numbered sections 2.0–2.5 (sprint composition & state
breakdown, delivery-health KPI table, priority & capacity discipline, process
adherence, qualitative team-discipline ratings, final iteration verdict), and
a closing "data gaps" table listing what the audit couldn't measure and why.

The sprint audited is **hardcoded**: `layout()` (`iteration_audit.py:989-991`)
calls `get_iteration_audit_data("May", 2026)` unconditionally — there is no
query-string parameter, dropdown, or other control to point it at a different
month.

## Why it exists

Gives leadership/PM a single narrative document per sprint — gate compliance,
P1 bug handling, scope injection, delivery vs. the prior month, all with
explicit RAG verdicts — instead of requiring someone to manually assemble
those numbers from several other dashboards (Estimation Status, Issue
Planning, Dev Capacity, etc.) after the fact.

## How it works

- **Data layer** (`db/iteration_audit.py::get_iteration_audit_data`, lines
  53-72) resolves the sprint month from a keyword ("May" → 5), computes
  working-day totals/elapsed/remaining for that month, and calls `_fetch()`
  (lines 83-421) — one function, one connection, doing everything:
  - Enhancement and Bug/Bug_UI/Bug_Text counts by `state`, filtered on
    `iteration_path ILIKE '%<keyword>%'` (not a strict iteration match — any
    iteration path containing the month name matches).
  - P1 bug detail rows, split into "stuck in Request Estimate", "Active/
    Clarification/New", and "in-flight but not closed" buckets — the
    partition is done once in the SQL `WHERE` clause (for exclusions) and
    again in Python list comprehensions (for the three buckets), so the two
    have to be kept in sync by hand if the state list ever changes.
  - Unestimated-active counts, a planning-gate "any gate signed off" % via a
    `LEFT JOIN p_planning_gates`, a checklist-compliance % via
    `LEFT JOIN p_tracker_steps`, scope-injection % (`created_date >=` sprint
    start), and an overhead-vs-feature-hours capacity split read from
    `agg_dev_monthly_capacity` and `agg_standalone_overhead` (the aggregate
    tables described in `db.md` §3 — this page reads them directly rather
    than recomputing rollups, per the caching convention in `master.md` §6).
  - A previous-month Enhancement delivery-rate comparison row for context.
  - ~11 threshold-based RAG verdicts (e.g. `v_gate = "RED" if gate_pct == 0
    else ...`, line 272) rolled into one `overall_verdict`.
  - On any exception, the whole call is caught, logged, and `_fetch()`'s
    result is replaced with `{}` (lines 64-70) — see Known issues.
- **Page module** (`pages_dash/misc/iteration_audit.py`) is pure rendering:
  `build_layout(d)` (lines 971-986) stitches together `_cover`, `_stats_strip`,
  `_sprint_summary`, `_section_20`..`_section_25`, and `_data_gaps`, each a
  plain function taking the same `d` dict and returning `html.Div` trees. Verdict
  narrative text (e.g. "May is on track for zero — a full unaddressed
  regression") is written directly into f-strings in both `_fetch()`
  (`verdict_paragraph`, `db/iteration_audit.py:383-392`) and the page module's
  section builders (`_sprint_summary`, `_section_20`) — it's a mix of computed
  numbers and hand-written commentary, not purely data-driven text.
- Cross-references `p_planning_gates` and `p_tracker_steps` (both from
  `db/planning.py`, per `db.md` §2) and the two `agg_*` tables above; does not
  touch `p_release_rows`/`p_release_stages` (Release Status) or any other
  `misc/` page's tables.

**Verified claim**: the module docstring says "Read-only display, no
callbacks." A full read of `pages_dash/misc/iteration_audit.py` confirms this
— there is not a single `@callback` decorator in the file; `layout(**_)` is
the only entry point and it's a pure function of the dict returned by
`get_iteration_audit_data()`.

## Known issues / quirks

- **Orphan route** — registered with Dash but not linked from the sidebar
  nor from any other page in `pages_dash/`; only reachable by typing the URL
  directly. See "Nav location" above for how this was verified.
- **Hardcoded to May 2026** (`iteration_audit.py:990`) — will keep rendering
  May 2026 data indefinitely; there's no mechanism (URL param, dropdown) to
  audit any other sprint without editing source.
- **No defensive handling for a failed data fetch.** `get_iteration_audit_data()`
  catches all DB exceptions and returns `{}` (`db/iteration_audit.py:68-70`),
  but `layout()` passes that straight into `build_layout(d)` with no guard —
  the very first section builder, `_cover(d)`, immediately does
  `d["overall_verdict"]` and would raise `KeyError` on an empty dict instead of
  showing a friendly error message.
- Confirmed zero `@callback`s — the docstring's claim is accurate (see above).
- Commentary strings are opinionated and specific to the May 2026 narrative
  (e.g. "a full unaddressed regression", "the quality gate process has
  stopped operating", `db/iteration_audit.py:383-392` and
  `iteration_audit.py:392-406`) rather than being generated purely from
  numbers — if this page is ever pointed at a different month, these phrases
  will still read as if they're about May unless someone edits them by hand.
- P1 bug bucketing logic (Request Estimate / Active-Clarification-New /
  in-flight) is expressed twice — once in the SQL exclusion list, once in
  Python filters over the same result set (`db/iteration_audit.py:156-158`,
  `361-364`) — a change to the state taxonomy in one place without the other
  would silently miscount a bucket.
