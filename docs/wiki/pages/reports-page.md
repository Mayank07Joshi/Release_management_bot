# Reports

- **Route / entry point**: `/reports`
- **Backing file(s)**: `pages_dash/misc/reports.py`
- **Nav location**: **not in nav.** Confirmed by reading `app.py`'s
  `_NAV_TREE` (`app.py:96-124`) — no entry for `/reports` in any section.
  A repo-wide search of `pages_dash/` for `/reports` finds only the
  `dash.register_page(...)` call in this file (`reports.py:17`) — no
  `dcc.Link`/`html.A` anywhere else points at this route. **Orphan route** —
  registered with Dash but not linked from the sidebar or from any other
  page; only reachable by typing the URL directly.

> For the LLM pipeline this page fronts (intake -> plan -> research -> build,
> local Ollama models, the two approval checkpoints), see
> [`reports.md`](../reports.md) — this page is UI only and doesn't run any of
> that logic itself.

## What it does

Three stacked panels on one page:

1. **Sprint Iteration Reports** — a dropdown of available 2026 sprint months
   (derived from `iteration_path` values actually present in the data) and a
   "Download Report" link that opens a generated HTML report for that month
   in a new tab.
2. **Request Custom Analysis** — a free-text query box plus an email field.
   Submitting adds a row to a request queue for the agent pipeline to pick
   up.
3. **Request Queue** (admin-facing) — auto-polls every 8 seconds and lists
   every request with a status badge and status-specific action buttons
   (Run / Approve Plan / Approve Build / Download / Cancel), plus inline
   detail panels: the AI's parsed intake spec and planned SQL queries while
   awaiting Checkpoint 1 approval, a preview of gathered data while awaiting
   Checkpoint 2 approval, and a tail of the pipeline's log while it's
   actively running.

## Why it exists

Front-end for two report-delivery mechanisms the docstring summarizes as
"sprint downloads, custom analysis requests, and admin queue": a canned,
on-demand sprint report generator, and an ad hoc "ask a question in plain
English, an LLM pipeline builds you a report" workflow — gated behind two
human-in-the-loop checkpoints so nobody ships an LLM-authored report without
a person reviewing the query plan and the data it produced first.

## How it works

- **Sprint download.** `_available_sprints()` (`reports.py:29-64`) queries
  `DISTINCT` `iteration_path` values matching `'Iteration 2026 NN-%'`,
  restricted to `work_item_type IN ('Enhancement','Bug','Bug_UI','Bug_Text')`,
  and maps each to a `YYYY-MM` value / "Month YYYY" label. Selecting a month
  sets the download link's `href` to `/download-report?sprint=YYYY-MM`
  (`_update_link`, lines 412-424). That route is registered in
  **`auth/routes.py:154`** (`download_report()`) — it requires login, calls
  `reports.iteration_report.generate_iteration_report(ym_str)`, and streams
  the resulting HTML back as an attachment.
- **Custom analysis request.** `_submit_request()` (lines 427-449) validates
  a non-empty query and a bare `"@" in email` check, then calls
  `db.report_requests.add_request(email, query)`, which inserts a row into
  `report_requests` (`status='pending'`) — the queue table defined in
  `db/report_requests.py:39-57` per `db.md` §2.
- **Admin queue.** `_refresh_queue()` (lines 452-467) re-renders on the
  8-second `dcc.Interval` or whenever a `refresh-store` counter bumps, via
  `db.report_requests.get_all_requests(limit=50)`. Each row is rendered by
  `_render_queue_row()` with a status badge from
  `db.report_requests.status_label()`.
- **Actions.**
  - "Run" (`_handle_run`, lines 470-488) lazily imports
    `agents.pipeline.start_pipeline(req_id)` and calls it, then flips status
    to `"running"`.
  - "Approve Plan" / "Approve Build" (`_handle_approve`, lines 491-512)
    advance status `cp1 -> cp1_approved` or `cp2 -> cp2_approved` — the two
    checkpoints where the pipeline pauses for a human to review, described in
    detail in [`reports.md`](../reports.md).
  - "Cancel" sets `status = cancelled`.
  - A completed request (`status = done` with a `report_path`) gets a
    "Download" link to `/download-generated?id={id}`, registered in
    **`auth/routes.py:173`** (`download_generated()`) — it requires login,
    looks up the row via `db.report_requests.get_request()`, resolves
    `report_path` relative to the repo root, and streams the file if it still
    exists on disk.
- This page never executes SQL against `work_items_main` for the custom
  -analysis feature and never calls an LLM itself — it only reads/writes
  `report_requests` columns (`intake_spec`, `query_plan`, `data_findings`,
  `agent_log`, `report_path`) that `agents/pipeline.py`'s background thread
  populates. See `reports.md` for what happens between submission and
  "done."

## Known issues / quirks

- **Orphan route** — see "Nav location" above; not in the sidebar and not
  linked from any other page under `pages_dash/`.
- Email validation is a bare substring check, `"@" in email`
  (`reports.py:439`) — accepts clearly invalid addresses like `a@` or `@@@`.
- `_fmt_time()` (lines 69-80) attempts `dt.strftime("%-d %b %H:%M")` first —
  the `%-d` (no leading zero) format code is a glibc/Unix strftime extension
  not supported by Windows' C runtime, so on this Windows deployment that
  first attempt is expected to raise `ValueError` on every call and fall
  through to the `%d %b %H:%M` fallback in the `except` block. The fallback
  produces a correct timestamp either way, so this is a latent inefficiency
  (an exception thrown on every timestamp render) rather than a visible bug.
- `_available_sprints()` hardcodes `'2026'` into every `LIKE` pattern
  (`reports.py:39-50`) — once iterations roll into 2027, this dropdown will
  silently stop returning any sprints unless someone updates the pattern
  list.
- The admin queue has no pagination or filtering; `get_all_requests(limit=50)`
  (default in `db/report_requests.py:78`) means once there are more than 50
  historical requests, the oldest simply disappear from the panel with no
  indication that more exist.
- Nothing in this page limits how many pipeline runs can be started
  concurrently — clicking "Run" on several pending requests in a row starts
  that many background threads, bounded only by whatever `agents.pipeline.
  start_pipeline()` itself guards against (see `reports.md`).
