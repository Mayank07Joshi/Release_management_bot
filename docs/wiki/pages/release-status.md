# Release Status

- **Route / entry point**: `/release-status`
- **Backing file(s)**: `pages_dash/misc/release_status.py`
- **Nav location**: ENHANCEMENTS section, label "Release Status" — flagged
  placeholder in `app.py`'s `_NAV_TREE` (`built=False`, `app.py:108`). Also
  linked from the Overview page's "In release pipeline" KPI card
  (`pages_dash/trends/overview.py:244`, `href="/release-status"`), so it's
  reachable from two places in the live nav, not just the sidebar entry.

## What it does

A per-story release-readiness tracker. Pick a release (a pill list built from
the distinct `release_date` values on active Enhancement/User Story work
items) and see a wide table of every active story tagged with that release:
owner, developer, QA, size, story status, release date, then eleven pipeline
stage columns (Development Status, Testing on Demo, QA Sign Off, Sunil's Sign
Off, Final Demo 1, Deployment on Dev, Dev Env., Deployment on QA, Final Demo
2, QA Env., Live, Overall Status) plus a comment column. Each stage cell shows
a status (Done/WIP/Not started) and a date.

Clicking a row opens a right-hand side panel where you can: change the story
owner/developer (dropdowns), QA assignee and story size (toggle buttons), set
each stage's status (three colored radio-style buttons) and date, edit a free
-text comment, change the release date, push the ADO-owned fields back to
Azure DevOps with an explicit "Save to ADO" button, or delete the local
tracking row for that story.

## Why it exists

ADO's own `state` field doesn't model the multi-environment promotion path
(Dev → Demo → QA → Live) with the several sign-offs this team requires
(QA, "Sunil's" sign-off, two rounds of demo) before a story is actually
released. This page gives whoever runs releases a single readiness grid
across all of those gates per release, instead of chasing status in Slack/ADO
comments.

## How it works

- **Reads `work_items_main`** — filtered to `work_item_type IN ('Enhancement',
  'User Story')` and excluding a closed-like state list (`_load_stories`,
  `release_status.py:134-150`; `_get_releases`, lines 121-131). `release_date`
  here is the free-text ADO field on the work item — **not** the platform's
  `p_releases` entity described in `db.md` §2. Same English word, unrelated
  concept; worth not conflating the two.
- **Owns its own DDL.** `p_release_rows` (work_item_id PK, qa_person, comment,
  updated_at) and `p_release_stages` (work_item_id + stage_key composite PK,
  status, stage_date) are created inline by `_ensure_tables()`
  (`release_status.py:82-100`), called once at import time inside a bare
  `try/except: pass` (lines 102-105). Per `db.md` §2/§4, this is the one
  `p_*`-table pair defined inside `pages_dash/` rather than in `db/` —
  confirmed by reading the file; there is no DDL for either table anywhere
  else in the repo.
- Also reads `p_planning_gates` (`claude_screens`, `text_written`,
  `our_screens`, `html_screens`, `sn_signoff`) to render a derived "Story
  Status: Complete/Incomplete N/5 gates" badge (`_story_status_badge`, lines
  229-250) in the side panel — a different signal from the `story_status`
  column shown in the main table, which is a plain `work_items_main` field.
  Only 5 of the table's real 12 gates (`db.md` §4) are checked here; which
  five, and why those specifically, isn't explained in code.
- **Field routing**, per the convention in `master.md` §6: story owner,
  developer, and release date write straight to `work_items_main`
  (`_save_owner`, `_save_developer`, `_save_release_date`); QA and comment go
  to `p_release_rows`; stage status/date go to `p_release_stages`. Per-field
  saves are local-only until the explicit **"Save to ADO"** button
  (`_save_to_ado`, lines 1051-1077) re-reads `story_owner`, `main_developer`,
  `story_size`, `release_date` from `work_items_main` and calls
  `sync.ado_write.write_fields()` to push them to Azure DevOps.
- **Delete story row** (`_delete_row`, lines 1080-1097) removes the
  `p_release_stages`/`p_release_rows` rows for that work item only — it never
  touches `work_items_main`, so the ADO item itself is untouched; the story
  just drops out of this page's tracking data until someone re-adds stage
  info.
- ~14 callbacks total: release-pill select, table render (driven by selected
  release + panel visibility so the table can highlight the open row), row
  click → open panel (snapshots `story_owner`/`main_developer`/`release_date`
  into a `dcc.Store` for unsaved-change comparison), panel close, panel
  content render, and one save callback per editable field/stage-button
  group.

## Known issues / quirks

- `_ensure_tables()` swallows every exception at import time
  (`release_status.py:102-105`). If table creation ever fails (bad DB creds at
  startup, permissions issue), the page still registers successfully and the
  failure only surfaces later as a runtime query error against
  `p_release_rows`/`p_release_stages`, not at startup where it'd be easier to
  spot.
- "Release" is overloaded across the codebase: on this page it means the
  free-text `release_date` value on a work item; elsewhere (`db.md` §2) it
  means the `p_releases` platform entity. No code path connects the two.
- The 5 gates checked by `_story_status_badge()` (`claude_screens`,
  `text_written`, `our_screens`, `html_screens`, `sn_signoff`) are a hardcoded
  subset of the 12 real columns in `p_planning_gates`; the selection looks
  like "content readiness" gates but that grouping isn't documented anywhere,
  so it's easy to assume it reflects all sign-off state when it doesn't.
- `p_release_rows`/`p_release_stages` inserts (`_save_qa`, `_save_comment`,
  stage saves) have no foreign-key or existence check against
  `work_items_main` — a comment or stage record can persist for a
  `work_item_id` that no longer matches any current row (e.g. release_date
  changed, or the item was deleted/renumbered upstream by a full ADO resync),
  and nothing in this page would notice or clean it up.
