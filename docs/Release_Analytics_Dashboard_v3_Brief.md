# Release Analytics Dashboard — Complete Build Documentation
### Version 3 PPT Brief | As of 30 March 2026

---

## What Is This?

A fully custom internal web dashboard built in **Python (Plotly Dash)**, running locally at `127.0.0.1:8050`. It connects live to **Azure DevOps (ADO)** via a background sync process, stores data in a local SQLite database, and renders interactive analytics across 8 pages. No third-party BI tool — entirely custom-built.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Python — Plotly Dash 4.0 |
| UI Components | Dash Bootstrap Components (DARKLY theme) |
| Charts | Plotly (custom "midnight" dark template) |
| Fonts | Inter (Google Fonts) |
| Data Source | Azure DevOps REST API |
| Local Storage | SQLite (via APScheduler background sync every 15 min) |
| Styling | Custom CSS (dark theme, assets/style.css) |

---

## Application Architecture

```
app.py                       Entry point, global layout, top nav, APScheduler
├── pages_dash/
│   ├── home.py              Landing page
│   ├── summary.py           Cross-team rollup
│   ├── capacity.py          Planning > Capacity
│   ├── release_outlook.py   Planning > Release Outlook
│   ├── iteration_board.py   Planning > Iteration Board
│   ├── bugs.py              Items (all work item types)
│   ├── teams.py             Team-specific analytics
│   ├── qa_health.py         QA quality metrics
│   └── assistant.py         AI assistant
├── data/
│   └── loader.py            load_data(), apply_filters(), filter_activity_since()
├── config/
│   └── team_mapping.py      Employee to Team mapping
├── sync/
│   └── ado_sync.py          ADO pull + SQLite upsert (runs every 15 min)
└── assets/
    └── style.css            All global and component styles
```

**Multi-page routing:** Dash `use_pages=True` with `pages_folder="pages_dash"`. Each page is a self-contained module with its own `layout()` and `@callback`.

**Data flow:** ADO → SQLite (every 15 min via background thread) → `load_data()` → page callbacks → Plotly figures.

---

## Dataset (as of 30 March 2026)

- **5,774 total work items** in current dataset
- **Work item types:** Task (2,183), Bug (1,984), Enhancement (1,064), Bug_UI (336), Bug_Text (174), User Story (33)
- **Hierarchy types:** Standalone (2,766), Leaf (747), Root (99), Middle (31)
- **26 columns** including: `work_item_id`, `title`, `assigned_to`, `state`, `work_item_type`, `priority`, `severity`, `original_estimate`, `completed_work`, `remaining_work`, `function`, `iteration_path`, `main_developer`, `main_designer`, `created_date`, `closed_date`, `area`, `tags`, `hierarchy_type`, `team`, `main_dev_team`

---

## Team Structure

| Team | Members |
|---|---|
| Development | Rajesh K, Arpit Bhardwaj, Archana Pandey, Nitesh Bagdi, Dhananjai Kalra, Pranjal Jindal, Shivi Prajapati |
| QA | Chhavi Bhardwaj, Satyarth Singh, Nancy Rana, Nitin Singh, Vineeta Arora, Mayank Joshi, Kunal Joshi, Shubham Negi |
| Mobile | Dolly Munjal, Sagar Khurana, Jyoti Dahiya |
| Design/Video | Kaushik Awasthi, Furquan Nayyar, Akarsh Bahl, Gagandeep Kaur, Neeraj Kumar |
| Management | Arjan Bolwerk |
| User Story | Geetika Khanna |

Two derived columns exist in the dataset:

- **`team`** — derived from `assigned_to` field. Used by bugs/QA/items pages. Represents who currently holds the ticket.
- **`main_dev_team`** — derived from `main_developer` field. Used by capacity page. Represents who is actually building the work.

---

## Pages and Features

---

### 1. Home (/)
Landing page. High-level project health snapshot, recent activity, quick KPIs.

---

### 2. Summary (/summary)
Cross-team rollup. Shows aggregate metrics across all teams and item types for the selected release/iteration scope.

---

### 3. Planning > Capacity (/capacity)

Most technically complex page in the app.

**Filters:** Team, Developer, Iteration, Hours/Person/Day (slider), Lookback weeks (slider)

**At a Glance KPIs:**
- Assigned Hours, Completed Hours, Remaining Hours
- Utilisation %, Accuracy % (Completed / Assigned)
- People count, Work Days in scope, Total Capacity

**Charts:**
- Team: Original vs Completed vs Remaining (grouped bar)
- Team Utilisation % (horizontal bar — red/amber/green thresholds)
- Per-Person Utilisation % (horizontal bar)
- Work by Iteration (stacked bar)
- Estimation Accuracy by Team (horizontal bar)
- Estimation Accuracy by Person (horizontal bar)

---

#### Fix 1 — Use main_developer not assigned_to for Capacity

**The problem:**
In ADO, bugs and enhancements are often `assigned_to` a QA person (who is testing them), but the `main_developer` field holds the person who is actually building the work. Using `assigned_to` for team filtering was causing:

- 1,229 Dev-built items being counted under the QA team
- Filtering by "Development" team was missing a huge chunk of Dev work
- 57% of all items (3,295 out of 5,774) had a mismatch between assigned_to team and main_developer team

**The fix:**
A new `main_dev_team` column was added to `loader.py`, derived from `main_developer` via TEAM_MAPPING. The capacity page was changed to:

- Show teams dropdown populated from `main_dev_team` values
- Filter data by `main_dev_team` when a team is selected (instead of `team`)
- Group all team-level charts (multibar, utilisation %, estimation accuracy) by `main_dev_team`

The existing `team` column (from `assigned_to`) is unchanged so other pages (bugs, QA health) continue to work correctly.

---

#### Fix 2 — Parent/Child Double-Counting in Hours

**Background:**
A recent practice (about 1 iteration old) started having developers attach Tasks as children to Enhancements/User Stories and log actual hours on the Tasks rather than the parent. This meant the dataset had both the parent Enhancement (with an `original_estimate`) and its child Tasks (also with estimates) — double-counting total hours.

- **Old pattern (historical):** Standalone Enhancements/Bugs had hours logged directly on them. No child tasks.
- **New pattern (recent):** Parent Enhancement is a container (`original_estimate` set, `completed_work = 0`). Child Tasks are Leaf items with the actual hours.

**The solution:**
Since the dataset includes both parent and child items as separate rows, child Tasks are already counted as Leaf items. We just need to exclude parent containers to avoid double counting.

**Rule applied:** Exclude `hierarchy_type IN (Root, Middle)` where `completed_work = 0`.

- If a Root/Middle item has `completed_work > 0` → someone logged time directly on it → old-style item → include it
- If a Root/Middle item has `completed_work = 0` → it is a new-style container → its Leaf children are already in the dataset → exclude it

No parent_id join is needed — child Tasks are already present as separate rows in the filtered data. This is self-correcting — no cutoff date required, handles both old and new data patterns simultaneously.

---

### 4. Planning > Release Outlook (/release-outlook)
Timeline and scope view for releases. Shows what is planned, in progress, and completed per release.

---

### 5. Planning > Iteration Board (/iteration)
Kanban/board style view per iteration. Work item state distribution and velocity tracking.

---

### 6. Items (/items) — formerly "Bugs"

**Completely restructured from a bug-only page to a type-aware analytics page.**

**The problem before:**
All charts, labels, KPIs, and measures were hardcoded for bugs — "Source donut," "MTTC (Mean Time to Close)," "Customer vs Internal trend," "Bug Movement Matrices," etc. — even when viewing Enhancements, Tasks, or Stories.

**Architecture change:**
Moved from 15 static callback outputs to 7 outputs + 1 dynamic children div (`items-specific-content`). The 6 common charts adapt their labels to the selected type. The type-specific section is built by a dedicated function and injected as children.

**Filters:** Type (Bug, Enhancement, User Story, Task, etc. + All), Release, Iteration, Team, Employee, State

**Always-visible sections (labels adapt to type):**
- At a Glance KPIs
- Priority Breakdown (bar chart)
- Age and Ownership (age histogram + owner breakdown)
- Trends Over Time (flow chart + backlog chart)

**Type-specific sections injected dynamically:**

| Selected Type | Section Shown |
|---|---|
| Bug / Bug_UI / Bug_Text | Source donut, MTTC by priority, Hotspots (area + function), Customer vs Internal trend, Bug Movement Matrices (collapsible) |
| Enhancement / Story / Feature / Task | State distribution bar, Cycle time histogram, Area breakdown, Iteration distribution |
| All (combined view) | Item type mix donut, State distribution, Area breakdown |

**KPI rows are type-aware:**

| Type | Row 1 | Row 2 |
|---|---|---|
| Bug | Total Bugs, Open, P1 Open, P2 Open | Closed, Closure%, Rejected, Avg MTTC |
| All | Total Items, Open, Closed, Closure% | Bug count, Enhancement count, Task count, Avg Days to Close |
| Enhancement/Story/Task | Total, Open, In Progress, Closed | Closure%, Avg Days to Close, Oldest Open, Avg Open Age |

---

### 7. Teams (/teams)
Team-specific analytics page. Select a team and see its velocity, item breakdown, quality metrics, and member-level stats.

---

### 8. QA Health (/qa_health)
QA-specific metrics — test coverage, bug escape rate, defect density, rejection rates.

---

### 9. Assistant (/assistant)
AI chat assistant integrated into the dashboard — answers questions about the release data.

---

## Navigation — Top Nav

A persistent top navigation bar with:
- **Left:** RA logo + "Release Analytics / ADO Dashboard" brand
- **Centre:** Home | Summary | Planning (dropdown) | Items | Teams | Assistant
- **Right:** Avatar (RM initials)

**Planning dropdown** uses a `<details>/<summary>` HTML pattern (no JavaScript required). Contains: Capacity, Release Outlook, Iteration Board.

**Active state logic:**
- Regular tabs use Dash `active="exact"` on NavLink
- Planning dropdown has a separate callback: highlights the Planning toggle when the current URL is `/capacity`, `/release-outlook`, or `/iteration`

**Bug fixed (this session):**
The dropdown menu was being clipped by `overflow-x: auto` on `.topnav-tabs`. Fixed in CSS. The Planning toggle was also always showing as active regardless of the current page — fixed by changing the active-state CSS to only apply via the className callback.

---

## Data Layer (data/loader.py)

**`load_data()`** reads from SQLite and applies standard column cleaning:
- Strips email suffixes from `assigned_to`, `main_developer`, `main_designer`
- Derives `hierarchy_type`: Standalone (no parent, no children), Root (has children, no parent), Middle (has both), Leaf (has parent, no children)
- Derives `team` from `assigned_to` via TEAM_MAPPING
- Derives `main_dev_team` from `main_developer` via TEAM_MAPPING (added this session)
- Computes boolean flags: `is_active`, `is_closed`, `is_recent`

**`apply_filters(df, team, employee, iterations, release, states)`** — standard filter function used by most pages. For capacity, team filtering bypasses this in favour of `main_dev_team` filtering directly in the callback.

**`filter_activity_since(df, date)`** — keeps only items with any activity (created, closed, or changed) on or after the given date. Used to limit historical noise.

---

## Background Sync (sync/ado_sync.py)

- Runs on app startup in a daemon thread
- Then runs every 15 minutes via APScheduler
- Pulls work items from ADO REST API
- Upserts into local SQLite database
- Only runs in the Werkzeug reloader child process to avoid double execution

---

## Summary of Key Numbers

| Metric | Value |
|---|---|
| Total work items in DB | 5,774 |
| Bugs (all variants) | ~2,494 (Bug + Bug_UI + Bug_Text) |
| Enhancements | 1,064 |
| Tasks | 2,183 |
| User Stories | 33 |
| Teams tracked | 6 |
| People tracked | 26 |
| Dashboard pages | 8 |
| Sync frequency | Every 15 minutes |
| Data start | 2025-01-01 |

---

## What Is Planned Next (Not Yet Built)

**Planner feature:**
- Gantt chart views for iterations and releases
- Capacity-wise division of work across team members
- AI recommendation engine for release planning
- ADO/VSTS write-back — bidirectional ticket editing from within the dashboard

---

*Document generated 30 March 2026*
