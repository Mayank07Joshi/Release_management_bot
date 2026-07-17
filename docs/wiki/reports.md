# Reports & Recommendations Layer

- **Backing dirs**: `reports/`, `agents/`, `db/report_requests.py`, `scripts/`
- **Wiki context**: see [`master.md`](master.md) for the system overview and
  [`db.md`](db.md) for table families. This file covers everything under the
  "Reports" umbrella in the nav map.

"Reports" is not one feature — it's three unrelated things that happen to
live under `reports/`/`scripts/`/`agents/`:

1. **Contextual recommendations** (`reports/recommendations.py` +
   `reports/rec_display.py`) — small threshold-based rule engine meant to
   surface inline insight pills on dashboard pages. **As of this writing it
   is fully implemented but not wired into any page** — see §2.
2. **Static report generators** — `reports/iteration_report.py` (a live,
   data-driven sprint HTML report served through the app) and
   `scripts/generate_ppt.py` / `generate_word_doc.py` / `generate_management_ppt.py`
   (hand-run, mostly hardcoded pitch decks — see §5).
3. **The LLM-driven custom-report pipeline** — `agents/pipeline.py` +
   `db/report_requests.py`, wired into the `/reports` page
   (`pages_dash/misc/reports.py`) and served via `auth/routes.py`'s
   `/download-generated` route — see §4.

A fourth, separate pair of modules — `reports/summarizer.py` and
`reports/formatter.py` — looks like it belongs with the recommendation
engine (both produce "what should I pay attention to" text) but is a
distinct, second implementation with its own schema. It's covered in §2
alongside the recommendation engine since that's the closest conceptual
neighbor, but the two do not share code or data structures.

---

## 1. Overview — verifying against the code, not the plan

There is a completed-looking project note in the team's own history
("Recommendation Engine Plan" — logic + display + wiring across 5 boards,
status marked COMPLETE 2026-04-08). Reading the actual code tells a more
specific story:

- **Phase 1 (logic) and Phase 2 (display) are real and match the plan
  closely** — `reports/recommendations.py` has the five
  `get_recommendations_*` functions the plan specified, with thresholds
  matching almost exactly, and `reports/rec_display.py` has the pill-strip
  renderer the plan called for.
- **Phase 3 (wiring the strip into `capacity.py`, `bugs.py`,
  `release_outlook.py`, `iteration_board.py`, `summary.py`) does not exist
  in the current tree.** A repo-wide search for `rec_display`,
  `rec_strip`, `rec_strip_for_page`, and every `get_recommendations_*` name
  turns up matches only inside `reports/recommendations.py` and
  `reports/rec_display.py` themselves — no file under `pages_dash/` imports
  either module. The page names in the old plan (`capacity.py`, `bugs.py`,
  `release_outlook.py`, `iteration_board.py`) also don't correspond to any
  file that exists today (the real files are `capacity_planner.py`,
  `bugs_unestimated.py`, etc.), which is a second, independent sign the
  wiring step was never carried out against this codebase.
- Corroborating this from the other direction: `scripts/generate_management_ppt.py`
  (a leadership-deck generator — see §5) has a slide, written after the
  "COMPLETE" plan note, that still lists **"🤖 Recommendation Engine —
  WAITING APPROVAL"** as a *roadmap* item
  (`scripts/generate_management_ppt.py:605-613`), not something already
  shipped.

Treat the recommendation engine as **logic-complete, UI-orphaned**: the
functions work if you call them directly against a DataFrame, but no
dashboard page currently renders their output.

---

## 2. Recommendation engine — logic, display, and the parallel summarizer/formatter system

### 2.1 `reports/recommendations.py` — the rule engine

Five pure functions, each taking the loader's DataFrame (and, for capacity,
an `hours_day` kwarg) and returning a list of recommendation dicts:

```python
{"type": "critical"|"warning"|"positive", "title": str, "message": str,
 "metric": str, "value": any}
```

| Function | Line | Board | What it checks |
|---|---|---|---|
| `get_recommendations_capacity` | `recommendations.py:62` | Capacity | Team utilisation vs. 60/90/110/130% bands, estimation accuracy (±50% of actual vs. estimate), per-person overload (≥130% individual utilisation) |
| `get_recommendations_bugs` | `recommendations.py:177` | Bugs | Open P1 count, P1 aging (≥3 days), unassigned P1/P2, 30-day bug creation trend vs. prior 30 days, single-area hotspot (≥30% of open bugs), reopen rate (≥20%) |
| `get_recommendations_qa` | `recommendations.py:296` | QA | SLA breach rate (10%/25% thresholds, per-priority SLA_DAYS map), tester load imbalance (>1.5× team average), defect escape rate to `"4 - PROD"` stage |
| `get_recommendations_release` | `recommendations.py:382` | Release | Per-release completion % and open-P1 count, grouped by `release_date`; releases ≥80% complete with 0 P1 → "on track", <50% or any P1 open → "at risk" |
| `get_recommendations_iteration` | `recommendations.py:445` | Iteration/Sprint board | Not-started % mid-iteration, closed %, 60+ day stale open items |
| `get_recommendations_all` | `recommendations.py:525` | Aggregate/Summary | Calls bugs+QA+release+capacity and tags each rec with a `"board"` field for a combined feed |

All five share one thresholds dict (`T`, `recommendations.py:23-50`) and one
closed-state set (`CLOSED_STATES`, `recommendations.py:19`) that mirrors
(but is a separate literal copy of) the one in `summarizer.py:27`. Sort
order is always critical → warning → positive (`_sort()`, `recommendations.py:53-55`).

### 2.2 `reports/rec_display.py` — the renderer

Turns a rec list into a horizontal wrap of rounded "pill" `html.Div`s —
red/amber/green by type, icon + short title visible, full `message` text
only on hover via the native `title=` tooltip attribute (`rec_pill()`,
`rec_display.py:58-81`). `rec_strip()` (`rec_display.py:84-96`) renders the
whole labeled strip, or an empty `html.Div()` if the list is empty — so a
page can call it unconditionally without an `if recs:` guard. `rec_strip_for_page()`
(`rec_display.py:99-109`) is a convenience wrapper that calls one of the
`get_recommendations_*` functions and swallows any exception into an empty
div — this is the one function a page would import to wire the engine in
with a single line, and it is currently unused.

### 2.3 `reports/summarizer.py` + `reports/formatter.py` — a second, separate system

These two files implement a **different** recommendation-adjacent feature:
per-board "summary" dicts with an embedded RAG scorecard and inline
suggestion text, explicitly aimed (per `formatter.py`'s docstring) at "the
report modal." `summarizer.py` has its own `TARGETS` dict
(`summarizer.py:12-25`) and its own copy of `CLOSED_STATES`/`BUG_TYPES`
(`summarizer.py:27-28`) — independent of `recommendations.py`'s `T` and
`CLOSED_STATES`, so the two systems can and do use different thresholds for
conceptually the same checks (e.g. SLA breach warning is 10% in both, but
open-P1 critical is a fixed `<5` target in `summarizer.TARGETS` vs. an aging/count-based
check in `recommendations.py`).

- `summarize_bugs` / `summarize_qa` / `summarize_releases` / `summarize_capacity`
  / `summarize_executive` (`summarizer.py:45,144,210,269,364`) compute the
  dicts.
- `format_bugs` / `format_qa` / `format_releases` / `format_capacity` /
  `format_executive` (`formatter.py:106,235,299,361,484`) turn each dict
  into a full Dash `html.Div` — KPI badges, detail rows, and a
  hardcoded-per-metric "Recommendations" section built from `if` checks
  directly inside the formatter (e.g. `formatter.py:189-222`), not from
  `reports/recommendations.py`. `format_report()` (`formatter.py:545-551`)
  dispatches on `summary["board"]` via the `_FORMATTERS` map
  (`formatter.py:536-542`).

**This system is also not wired into any Dash callback.** A repo-wide
search for every `format_*`/`summarize_*` name turns up no caller outside
`reports/summarizer.py`/`reports/formatter.py` themselves, with one
exception: `scripts/generate_management_ppt.py:100-105` imports
`summarize_bugs`, `summarize_qa`, `summarize_releases`, `summarize_capacity`
directly (not through `formatter.py`) to pull live numbers into a slide
deck — see §5. The "report modal" and the "📄 Board Reports — one-click
summary for any board" feature pitched on
`scripts/generate_management_ppt.py:515-522` (slide 8, "What The Platform
Tracks") do not appear to exist as a live page/callback in the current
codebase.

---

## 3. Iteration report — `reports/iteration_report.py`

`generate_iteration_report(ym_str)` (`iteration_report.py:402`) is the one
genuinely live, wired report generator in this layer. Given a `"YYYY-MM"`
string it:

- Loads `work_items_main` for that iteration month (`_load()`,
  `iteration_report.py:43-191`), filtering on
  `iteration_path LIKE '%Iteration {year} {month:02d}-%'`.
- Buckets state into planning / dev-active / dev-done / QA-active /
  fully-done sets (`_PLANNING`, `_DEV_ACTIVE`, `_DEV_DONE`, `_QA_ACTIVE`,
  `_FULLY_DONE`, `iteration_report.py:24-34`) — a state taxonomy specific to
  this report, separate from `recommendations.py`'s/`summarizer.py`'s
  `CLOSED_STATES`.
- Computes scope creep (items created after sprint day 3), per-developer
  capacity across Task/Bug/Enhancement hours (pulling `DEVELOPERS` from
  `config/dev_capacity.py`, `iteration_report.py:563`), estimation
  compliance, carry-forward, and reopened items.
- Generates rule-based findings (`_findings()`, `iteration_report.py:287-397`)
  — hardcoded thresholds (e.g. enhancement delivery <40%/<70%, scope
  creep >20%/>40%, bug:enhancement ratio >1.5×) each producing a
  HIGH/MEDIUM/LOW-tagged card with a `rec` recommendation string. This is a
  **third**, independent threshold/finding system alongside
  `recommendations.py` and `summarizer.py`/`formatter.py` — none of the
  three share a thresholds dict or a findings schema.
- Returns one big self-contained HTML string (inline `<style>`, Google
  Fonts link, light theme — deliberately different from the app's dark
  `midnight` Plotly theme, since this is meant to be exported/printed) built
  entirely with f-string HTML helpers (`_kpi`, `_table`, `_section`,
  `_badge`, `_progress_bar`, `_ado_link`, `iteration_report.py:214-282`).

**Serving path**: `auth/routes.py`'s `/download-report` route
(`auth/routes.py:154-171`) takes a `?sprint=YYYY-MM` query param, calls
`generate_iteration_report(ym_str)`, and returns the HTML as a
`Content-Disposition: attachment` download. It's triggered from the
Reports page's "Sprint Iteration Reports" section
(`pages_dash/misc/reports.py:299-331`) — a sprint-month dropdown populated
by `_available_sprints()` (`pages_dash/misc/reports.py:29-64`, itself a raw
SQL `CASE` mapping `iteration_path` substrings to `2026-MM`) plus a download
link whose `href` is set by `_update_link()`
(`pages_dash/misc/reports.py:412-424`) to `/download-report?sprint=...`.
Every hit regenerates the report from live data — there's no caching layer
on top of `generate_iteration_report()`.

---

## 4. LLM report-request pipeline — `agents/pipeline.py` + `db/report_requests.py`

A four-stage, two-checkpoint pipeline that runs entirely on local Ollama
models, background-threaded so it doesn't block the Dash process.

### 4.1 Stages

| Stage | Function | Model | What it does |
|---|---|---|---|
| 1. Intake | `_agent_intake` (`pipeline.py:115-141`) | `llama3.2:3b` | Parses the user's free-text query into a structured spec (`analysis_type`, `time_range`, `focus_areas`, `summary`) via `_ollama()` + `_extract_json()`. Falls back to a generic spec if JSON parsing fails. |
| 2. Planner | `_agent_planner` (`pipeline.py:146-177`) | `deepseek-r1:7b` | Given the spec and a hardcoded schema description (`DB_SCHEMA`, `pipeline.py:35-60`), writes up to 6 SQL `SELECT` queries plus a report outline. |
| — Checkpoint 1 — | `_wait_approval` (`pipeline.py:98-110`) | — | Polls `report_requests` every 3s (up to a 7200s/2h timeout) until an admin flips status to `cp1_approved`, or the request is cancelled/failed. |
| 3. Researcher | `_agent_researcher` (`pipeline.py:182-207`) | none (no LLM call) | Runs each planned query through `_safe_select()` (`pipeline.py:86-95`) and assembles a Markdown-ish findings string (`## label` sections with row counts / previews). |
| — Checkpoint 2 — | `_wait_approval` again | — | Same poll, waiting for `cp2_approved`. |
| 4. Builder | `_agent_builder` (`pipeline.py:212-253`) | `deepseek-r1:7b` | Given query, spec, outline, and the findings text (truncated to 8000 chars), generates a complete self-contained HTML report. Falls back to a templated wrapper around the raw model output if it doesn't return recognizable `<!DOCTYPE html>`/`<html` markup. |

`INTAKE_MODEL = "llama3.2:3b"` and `WORK_MODEL = "deepseek-r1:7b"` are set
at `pipeline.py:26-27`. `_ollama()` (`pipeline.py:65-73`) calls
`ollama.chat(model=..., options={"temperature": 0.1})` and strips any
`<think>...</think>` block the model emits (deepseek-r1 is a
reasoning model that emits these) before returning the content.

`_run_pipeline()` (`pipeline.py:258-329`) is the orchestrator that chains
all four stages plus both checkpoints inside one try/except, writing the
finished HTML to `reports/generated/report_{id}_{timestamp}.html`
(`REPORTS_DIR`, `pipeline.py:29-30`) and setting the DB row's
`report_path` to that relative path. Any exception anywhere in the chain
sets status to `failed` and appends the exception text to the log
(`pipeline.py:319-325`).

`start_pipeline(request_id)` (`pipeline.py:331-341`) spawns one daemon
thread per request, guarded by an in-process `_active: dict[int, bool]` +
`threading.Lock` (`pipeline.py:32-33`) so the same request can't be started
twice concurrently. `is_running()` (`pipeline.py:344-345`) just checks that
dict.

### 4.2 `db/report_requests.py` — status states

```
pending → running → cp1 → cp1_approved → researching → cp2 → cp2_approved
        → building → done
                    ↘ failed / cancelled  (from any state)
```

All ten states are named constants (`STATUS_PENDING` … `STATUS_CANCELLED`,
`report_requests.py:9-19`) with a display label + color map
(`_LABELS`/`status_label()`, `report_requests.py:21-36`). The table itself
(`init_table()`, `report_requests.py:39-57`) is one flat row per request:
`email`, `query_text`, `status`, `intake_spec`, `query_plan`,
`data_findings`, `report_path`, `agent_log`, `admin_notes`, timestamps —
`intake_spec`/`query_plan`/`data_findings` are all stored as raw JSON/text
blobs, not normalized. `append_log()` (`report_requests.py:102-108`) does
an atomic `agent_log = agent_log || newline` update, which is what feeds
the live-updating agent log shown in the queue UI. `init_table()` is called
once at app startup from `app.py:569-573` (wrapped in the same
try/except-and-warn pattern as every other `init_*_tables()` call — see
`db.md` §2).

### 4.3 UI wiring — `pages_dash/misc/reports.py`

The `/reports` page (orphan route, not in the sidebar nav — see
`master.md` §5) has three sections: sprint report download (§3 above),
a "Request Custom Analysis" textarea + email field that calls
`add_request()` on submit (`_submit_request()`,
`pages_dash/misc/reports.py:427-449`), and an admin queue
(`_refresh_queue()`, `pages_dash/misc/reports.py:452-467`, polling every 8s
via `dcc.Interval`) that renders each request with status-appropriate
action buttons:

- **Pending** → "▶ Run" button calls `agents.pipeline.start_pipeline(req_id)`
  and sets status to `running` (`_handle_run()`,
  `pages_dash/misc/reports.py:470-488`).
- **cp1** → "✓ Approve Plan" flips to `cp1_approved`; the detail panel
  (`_render_cp1_detail()`, `pages_dash/misc/reports.py:83-125`) shows the
  parsed spec and each planned SQL query for review before approval.
- **cp2** → "✓ Approve Build" flips to `cp2_approved`; the detail panel
  (`_render_cp2_detail()`, `pages_dash/misc/reports.py:128-152`) previews
  the gathered data.
- **done** (with a `report_path`) → "↓ Download" link to
  `/download-generated?id={id}`.
- Any non-terminal state → "✕ Cancel" sets `STATUS_CANCELLED`.

`_handle_approve()` (`pages_dash/misc/reports.py:491-512`) is only ever a
DB status write — the actual state transition is picked up by the
already-running background thread's `_wait_approval()` poll, **not** by
this callback re-invoking anything. This matters for the known issue in §6
about restarts.

**Serving path**: `auth/routes.py`'s `/download-generated` route
(`auth/routes.py:173-192`) takes `?id=<request_id>`, looks up
`report_path` via `db.report_requests.get_request()`, resolves it relative
to the repo root, and streams the saved HTML file back (404 if the DB row
or the file is missing).

---

## 5. Static generators — `scripts/generate_*.py`

All three are plain top-level scripts (no `if __name__ == "__main__":`
guard — every statement, including the final `.save()`, runs at import
time) meant to be run by hand from a shell, per each file's own docstring
(`"Run: .venv/Scripts/python generate_ppt.py"` etc.). None of them are
imported anywhere else in the repo (confirmed by a repo-wide search) — no
Dash callback, no route, no scheduler job triggers any of the three. They
belong to the "one-off/maintenance scripts" category `master.md` §4
describes for `scripts/` generally.

| Script | Produces | Data source | Audience |
|---|---|---|---|
| `scripts/generate_ppt.py` | `Release_Analytics_Presentation.pptx` (hardcoded path, `generate_ppt.py:427`) — 10 slides: title, 3-phase "journey" (v1→v2→v3), a live-demo mockup slide, and 7 "before/after" area slides (Release Status, Reporting, Capacity, Bugs, Data Accuracy, Hour Counting, AI Integration) | **None** — every number, bullet, and metric (`AREAS` list, `generate_ppt.py:244-350`) is hand-authored prose/stats, not pulled from the DB | Internal pitch deck for the platform itself, presumably for whoever needs to explain "what we built" |
| `scripts/generate_word_doc.py` | `Phase3_CustomerAnalytics_Vision.docx` (hardcoded path, `generate_word_doc.py:441`) — an 8-section business proposal ("Phase 3 Analytics Vision — Customer Intelligence") | **None** — entirely hand-written prose/tables describing a *proposed, not-yet-built* customer-intelligence feature (churn detection, company health scorecards) | A management pitch document for a future feature, unrelated to any code that exists in this repo today |
| `scripts/generate_management_ppt.py` | `Management_Presentation_v2.pptx` (hardcoded path, `generate_management_ppt.py:681`) — 11-slide "Year-End Report & Platform Overview" leadership deck | **Live**, via `data.loader.load_data()` + `reports.summarizer.summarize_bugs/qa/releases/capacity` (`generate_management_ppt.py:96-105`), with a hardcoded fallback dict of stale numbers (`generate_management_ppt.py:112-127`) if that import/load fails | Leadership/year-end review — mixes real current KPIs with a roadmap pitch for two features not yet built (Recommendation Engine, a Slack/Teams "Release Bot"), both marked "WAITING APPROVAL" on slide 10 (`generate_management_ppt.py:604-625`) |

`generate_management_ppt.py` is the only one of the three that talks to the
running system's data layer at all, and it does so via `sys.path.insert(0, ...)`
(`generate_management_ppt.py:19-20`) to make `data`/`reports` importable
when run as a bare script from `scripts/` rather than as part of the
package — the same reason `db/init_platform.py` needs to be run the same
way (see `db.md` §5).

---

## 6. Known issues / quirks

- **The recommendation engine (`recommendations.py` + `rec_display.py`) is
  built but not wired into any page.** See §1 — a repo-wide search for
  every public name in both modules turns up zero callers outside the
  modules themselves. The team's own project note marks this "COMPLETE,"
  but the wiring phase it describes never happened against this codebase
  (the page files it names don't exist under those names), and a later
  slide deck (`scripts/generate_management_ppt.py:605-613`) still pitches
  the recommendation engine as future work. Anyone resuming this feature
  should not assume Phase 3 exists — check `pages_dash/` directly.
- **A second, independent recommendation/summary system
  (`summarizer.py` + `formatter.py`) is also unwired**, and duplicates
  effort with the first: it has its own thresholds dict, its own
  `CLOSED_STATES` literal, and its own inline suggestion-generation logic
  inside the formatter functions. The only real caller of any function in
  either file is `scripts/generate_management_ppt.py`, which imports the
  `summarize_*` functions directly and never touches `formatter.py` at
  all — so `formatter.py` in its entirety currently has no caller anywhere
  in the repo.
- **Three independent threshold/finding systems exist for conceptually
  the same "is this metric healthy" questions**: `recommendations.py`'s
  `T` dict, `summarizer.py`'s `TARGETS` dict, and
  `iteration_report.py`'s inline thresholds in `_findings()`. They
  disagree on some values (e.g. what counts as a healthy defect escape
  rate or SLA breach rate) because none of them import from a shared
  source of truth.
- **Hard, undocumented dependency on a local Ollama server.**
  `agents/pipeline.py` (models `llama3.2:3b`, `deepseek-r1:7b`) and
  `sync/task_classifier.py` (`llama3.2:3b`, for standalone-task
  classification — see `db.md` §2) both call the `ollama` Python client
  (pinned `ollama==0.6.1` in `requirements.txt`) against a local Ollama
  server. Nothing in this repo documents installing Ollama, starting the
  server, or pulling either model — no setup script, no README section, no
  startup health check. If the server isn't running or a model isn't
  pulled, `_ollama()` raises inside a bare `except Exception` at each
  call site (`pipeline.py:139-141,175-177,251-253`), which just logs to
  the request's `agent_log` and flips status to `failed` — there's no
  environment-level check that would tell an operator *why* every request
  is failing.
- **The pipeline does not survive an app restart mid-run.** In-flight
  state lives only in `agents.pipeline._active` (an in-process dict) and
  the daemon thread doing the work (`pipeline.py:32-33,331-341`). If the
  process restarts while a request is at `cp1`/`cp2` (awaiting approval)
  or actively `running`/`researching`/`building`, the thread is gone.
  Nothing on startup scans `report_requests` for stuck rows and resumes or
  fails them — `app.py`'s startup block only calls
  `report_requests.init_table()` (`app.py:569-573`), never anything from
  `agents/pipeline.py`. An admin can still click "Approve" in the UI
  (`pages_dash/misc/reports.py:491-512`), which happily updates the status
  column, but nothing is listening for that change anymore — the request
  is stuck permanently with no error surfaced anywhere.
- **The Researcher's SQL guard is a single `startswith("SELECT")` check.**
  `_safe_select()` (`pipeline.py:86-95`) executes whatever SQL the Planner
  LLM produced directly against the shared `engine`, with no statement
  allowlist beyond that one prefix check, no dedicated read-only DB role,
  and no server-side row cap (the 200-row cap is a client-side
  `fetchmany`). The Planner's prompt (`pipeline.py:146-165`) does instruct
  the model to only write `SELECT`s, but that's a prompt-level convention,
  not an enforced constraint — the only enforcement is the prefix check on
  whatever text comes back.
- **`generate_management_ppt.py` can silently present stale numbers as
  current.** If the live data pull fails, it falls back to a hardcoded
  dict of numbers from "our last analysis" (`generate_management_ppt.py:112-127`)
  and proceeds to build the exact same deck, still labeled "Data as of
  {AS_OF}" — the only indication anything went wrong is a `print()` to
  whatever console ran the script, not anything visible in the output
  file itself.
- **All three `scripts/generate_*.py` files hardcode their output path**
  to `c:\Python\Release\...` (`generate_ppt.py:427`,
  `generate_word_doc.py:441`, `generate_management_ppt.py:681`) — re-running
  any of them silently overwrites the previous file, and none of them
  accept a CLI argument to save elsewhere.
- **`generate_ppt.py` and `generate_management_ppt.py` duplicate the same
  slide-building primitives** (`box()`, `txt()`, `accent_bar()`/`section_tag()`/`divider()`,
  and the same `C_BG`/`C_CARD`/`C_PURPLE`/`C_GREEN`/`C_RED`/... palette)
  from scratch in each file, with no shared helper module between them.
- **Naming collision, not a bug but worth knowing**: `reports/formatter.py`
  and `components/bot/formatter.py` are two entirely unrelated modules
  with the same filename — the latter belongs to the separate "AI
  Assistant" chatbot feature (`components/bot/router.py`'s
  `bot_answer()`) and has nothing to do with the reports layer described
  in this file.
