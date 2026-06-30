# PRD — In-House Project Management Platform
### Release Analytics Dashboard — Operational Layer
**Status:** Discovery complete. Capacity Planning Layer added. Ready for Phase 1 technical design.
**Last updated:** 8 April 2026
**Author:** Mayank Joshi

---

## 1. Vision

Build an in-house project management platform, layered on top of the existing Release Analytics Dashboard, that tracks work from idea to delivery in a single tool — structured around how this team actually works rather than generic ADO conventions.

**The core problem being solved:**
Work on the same product area (e.g. "Mileage Setup") is scattered across years of disconnected Enhancements in ADO. There is no thread connecting them. You cannot trace the history or current state of a capability area without manually digging through hundreds of unlinked tickets. The team has no standardised process for task creation, no templates, and no way to connect planning to capacity to delivery in one place.

**The goal:**
One tool where a PM can create a Feature under the right Epic and Release, the right templated tasks auto-generate for Dev/Design/QA, the team executes against them, and the analytics dashboards reflect everything — all without context-switching to ADO.

---

## 2. Core Principles

- **Structured to our needs** — not a clone of VSTS/Jira. Workflows, states, and templates reflect how this team actually works.
- **Idea to delivery in one place** — from Epic creation to task closure to release analytics.
- **Efficiency over completeness** — quick-create apparatus, pre-templated tasks, sensible defaults. Minimal friction.
- **ADO stays in sync** — ADO is not abandoned. This platform syncs bidirectionally so external stakeholders and existing integrations still work.
- **Analytics are native** — the operational layer feeds directly into the existing dashboards. No separate reporting setup.

---

## 3. Hierarchy Model

Three independent concepts that connect through relationships:

```
EPIC (Product Area — permanent, cross-release)
│   e.g. "Mileage Management", "Expense Reports", "User Management"
│   Lives forever. Groups all Features ever built for a capability.
│
└──► FEATURE (Deliverable chunk — linked to one Epic + one Release)
         e.g. "Multi-currency Mileage" → belongs to Epic "Mileage" + Release "4.26"
         │
         ├──► TASK (Implementation work — templated)
         │        e.g. REQ | Design | DEV | TEST | REVIEW | etc.
         │
         └──► BUG (Found during this Feature's development)
                  Linked to this Feature. Tracked as a child.

RELEASE (Time-boxed delivery — independent of Epic)
│   e.g. "Release 4.26", "Release 4.27"
│   Groups all Features targeted for a specific delivery window.
│
└──► FEATURES targeted for this release (from any Epic)

BUG POOL (Standalone bugs — regression, sanity, not tied to a Feature)
    e.g. bugs found in general testing, production issues, sanity failures
```

### Relationships at a glance

| From | To | Relationship |
|---|---|---|
| Epic | Feature | 1 : many (one Epic, many Features over time) |
| Release | Feature | 1 : many (one Release, many Features from any Epic) |
| Feature | Epic | many : 1 |
| Feature | Release | many : 1 (or unscheduled/backlog) |
| Feature | Task | 1 : many |
| Feature | Bug | 1 : many (bugs found during this Feature) |
| Bug Pool | Bug | standalone (no Feature parent) |

---

## 4. Entity Definitions and Fields

---

### 4.1 Epic

**Definition:** A permanent product capability area. Not time-boxed. Groups all Features ever built for a product domain.

**Examples:** Mileage Management, Expense Reports, User Management, Notifications, Reporting, Admin Panel

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| Epic ID | Auto (EP-001) | Yes | System generated |
| Title | Text | Yes | Short capability name |
| Description | Rich text | No | What this capability covers |
| Owner | Person | Yes | PM or lead responsible |
| Status | Enum | Yes | Active / Archived |
| Created date | Date | Auto | |
| Tags | Multi-tag | No | |

**Status flow:**
```
Active ──► Archived
```
Simple. Epics don't close — they archive when a capability is deprecated.

---

### 4.2 Release

**Definition:** A time-boxed delivery window. Groups Features from any Epic that are targeted for a specific release. Independent of Epic.

**Examples:** Release 4.26, Release 4.27, Phase 4 — April, September P1 Release

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| Release ID | Auto (REL-001) | Yes | System generated |
| Title | Text | Yes | e.g. "Release 4.26" |
| Description | Rich text | No | Goals, scope summary |
| Target date | Date | Yes | Planned release date |
| Owner | Person | Yes | |
| Status | Enum | Yes | See below |
| Iterations | Multi-select | No | Which ADO iterations are in scope |
| Created date | Date | Auto | |

**Status flow:**
```
Planning ──► In Progress ──► Released ──► Archived
                │
                └──► On Hold
```

---

### 4.3 Feature (formerly Enhancement)

**Definition:** A specific, deliverable piece of work. Belongs to one Epic and is targeted at one Release (or sits in Backlog if unscheduled). This is the primary unit of work the team creates and executes against.

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| Feature ID | Auto (F-001) | Yes | System generated |
| Title | Text | Yes | |
| Description | Rich text | No | Problem statement, scope |
| Epic | Link | Yes | Must belong to an Epic |
| Planned Release | Link | No | Release it was originally scoped for |
| Actual Release | Link | No | Release it was actually delivered in (set on Done) |
| Spill-over | Auto flag | Auto | Set if Actual Release ≠ Planned Release |
| Iteration | Select | No | ADO iteration |
| Priority | 1–4 | Yes | Default 2 |
| State | Enum | Yes | See below |
| Assigned to | Person | No | Current owner |
| Main Developer | Person | No | Dev lead on this Feature |
| Main Designer | Person | No | Designer on this Feature |
| Original Estimate (h) | Number | No | Total planned hours |
| Area | Select | No | Module/area within product |
| Function | Select | No | Frontend / Backend / DB / Mobile / etc. |
| Tags | Multi-tag | No | |
| ADO ID | Number | Auto | Synced from ADO |
| Created date | Date | Auto | |
| Closed date | Date | Auto | Set when state = Done |

**Status flow:**
```
Backlog ──► In Planning ──► In Design ──► In Development ──► In QA ──► Done
               │                │               │                │
               └──► On Hold     └──► On Hold     └──► On Hold     └──► Rejected / Won't Do
```

**Notes on states:**
- **Backlog** — captured but not yet scheduled
- **In Planning** — Req Gathering task is active; scope being defined
- **In Design** — Design task is active
- **In Development** — Dev task is active
- **In QA** — Testing task is active
- **Done** — all tasks closed, QA passed
- **On Hold** — parked at any stage
- **Rejected / Won't Do** — descoped

---

### 4.4 Task

**Definition:** A unit of implementation work under a Feature. Always has a type (activity). Created from templates.

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| Task ID | Auto (T-001) | Yes | System generated |
| Title | Text | Yes | Auto-generated from template pattern |
| Activity / Type | Enum | Yes | See template library |
| Parent Feature | Link | Yes* | *Null for Overhead tasks |
| Assigned to | Person | No | |
| State | Enum | Yes | To Do / In Progress / Done / Blocked |
| Priority | 1–4 | No | Default 2 |
| Original Estimate (h) | Number | No | Pre-filled by template |
| Completed Work (h) | Number | No | Updated daily |
| Remaining Work (h) | Number | Auto | Estimate − Completed |
| Description | Rich text | No | Template scaffold pre-filled |
| DoD (Definition of Done) | Rich text | No | Template scaffold pre-filled |
| Tags | Multi-tag | No | Auto-set by template |
| ADO ID | Number | Auto | Synced |
| Created date | Date | Auto | |
| Closed date | Date | Auto | |

**Status flow:**
```
To Do ──► In Progress ──► Done
   │            │
   └──► Blocked ┘
```

---

### 4.5 Iteration Capacity Configuration

**Definition:** A per-person, per-iteration capacity record. Defines how many hours a person has available in a given iteration — accounting for leave, public holidays, and planned overhead. This is the baseline the planning layer uses to compute utilisation and fire alerts.

**This is not an ADO entity.** It lives only in the local DB. It is configured by the PM or team lead at the start of each iteration.

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| Config ID | Auto | Yes | System generated |
| Person | Person (FK) | Yes | Linked to team member |
| Iteration | Select | Yes | ADO iteration name |
| Available Days | Number | Yes | Working days in iteration (default from calendar) |
| Hours Per Day | Number | Yes | Default 8 — override per person if needed |
| Leave Days | Number | No | Days off within iteration (reduces Available Days) |
| Total Available Hours | Auto | Yes | (Available Days − Leave Days) × Hours Per Day |
| Notes | Text | No | e.g. "On leave wk 2", "50% on other project" |
| Created by | Person | Auto | |
| Created date | Date | Auto | |

**How it's used:**
- Capacity Planning board reads this to show each person's available hours vs committed hours (sum of their Tasks' `original_estimate` in that iteration)
- Utilisation % = committed / available × 100
- Alerts fire when utilisation crosses thresholds (amber = 90%, red = 110%)

---

### 4.6 Bug

**Definition:** A defect. Either linked to a Feature (found during active development/QA of that Feature) or standalone in the Bug Pool (found in regression, sanity, or production).

**Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| Bug ID | Auto (B-001) | Yes | System generated |
| Title | Text | Yes | |
| Type | Enum | Yes | Bug / Bug_UI / Bug_Text |
| Linked Feature | Link | No | Null = Bug Pool |
| Priority | 1–4 | Yes | |
| Severity | Enum | No | Critical / High / Medium / Low |
| State | Enum | Yes | See below |
| Assigned to | Person | No | |
| Main Developer | Person | No | Dev fixing it |
| Area | Select | No | |
| Function | Select | No | |
| Found in Iteration | Select | No | |
| Found in Release | Link | No | |
| Reproduction steps | Rich text | No | |
| ADO ID | Number | Auto | |
| Created date | Date | Auto | |
| Closed date | Date | Auto | |

**Status flow:**
```
New ──► Active ──► Resolved ──► Closed
  │                              │
  └──► Rejected                  └──► (re-open) Active
```

---

## 5. Task Template Library

Templates auto-fill title, activity tag, default fields, and description scaffold when a task is created. Grouped into two categories.

---

### 5.1 Feature-linked Templates
Used for work directly tied to a Feature. Title includes the Feature ID.

**Naming pattern:** `<ACTIVITY> | F-<FeatureID> | <Short description>`

---

#### TASK — Req Gathering
- **Use when:** Starting a new Feature — discussions, client calls, requirement clarifications
- **Title pattern:** `REQ | F-<ID> | Clarify requirements`
- **Auto-set fields:** Activity = Requirement/Analysis, Priority = 2, Target Date = Feature due date
- **Description scaffold:**
  - Problem statement
  - Open questions
  - Stakeholders involved
  - Meeting notes
  - **DoD:** Requirements documented and approved

---

#### TASK — Design Implementation
- **Use when:** Solution design, DB/schema changes, sequence diagrams, UX flows
- **Title pattern:** `DESIGN | F-<ID> | <Module>`
- **Auto-set fields:** Activity = Design, Function = relevant module, Tag = Design
- **Description scaffold:**
  - Current behaviour
  - Proposed design
  - Impacted components
  - Risks
  - **DoD:** Design reviewed and signed-off

---

#### TASK — Development
- **Use when:** Pure coding work for the Feature
- **Title pattern:** `DEV | F-<ID> | Implement <feature name>`
- **Auto-set fields:** Activity = Development, Function = module, Tag = Dev, Original Estimate pre-filled
- **Description scaffold:**
  - Scope of change
  - Files / modules affected
  - APIs / DB changes
  - Feature flags
  - Unit test plan
  - **DoD:** Code merged and unit tests added

---

#### TASK — Testing (Story)
- **Use when:** Manual / functional testing of the Feature
- **Title pattern:** `TEST | F-<ID> | Functional testing`
- **Auto-set fields:** Activity = Testing, Priority = 2, Tag = Testing
- **Description scaffold:**
  - Test scope
  - Environments
  - Test data
  - Entry / exit criteria
  - Bugs logged (links)
  - **DoD:** All scenarios passed / defects linked

---

#### TASK — Review / Playback
- **Use when:** Feature walk-through with PO/client; design or dev review sessions
- **Title pattern:** `REVIEW | F-<ID> | <Type of review>`
- **Auto-set fields:** Activity = Meeting/Review, Priority = 2
- **Description scaffold:**
  - Meeting objective
  - Attendees
  - Agenda
  - Notes
  - Action items
  - **DoD:** Feedback addressed / follow-up tasks created

---

#### TASK — Test Case Authoring
- **Use when:** Writing manual test cases or building the automation backlog for a Feature
- **Title pattern:** `TESTCASE | F-<ID> | <Module> | Author test cases`
- **Auto-set fields:** Activity = Testing/Documentation, Tag = TestCases
- **Description scaffold:**
  - Scope
  - Test design technique
  - Location of cases (link)
  - Coverage summary
  - **DoD:** Cases reviewed and approved

---

#### TASK — Automation / Sanity
- **Use when:** Building automation scripts or maintaining sanity suite for a Feature
- **Title pattern:** `AUTOMATION | F-<ID> | <Module>`
- **Auto-set fields:** Activity = Automation/Testing, Tag = Automation
- **Description scaffold:**
  - Scenarios to automate
  - Framework / repo path
  - Test data
  - CI job link
  - **DoD:** Scripts in repo and pipeline green

---

### 5.2 Overhead Templates
Not tied to a Feature. Used to track time spent on meetings, calls, and non-Feature analytical work.

**Naming pattern:** `<ACTIVITY> | <Context> | <Date or short description>`

---

#### TASK — Daily Standup
- **Use when:** Morning / evening status calls
- **Title pattern:** `CALL | Daily standup | <Date>`
- **Auto-set fields:** Activity = Meeting, Priority = 3, Estimate = 0.5–1 hr
- **Description scaffold:**
  - Participants
  - Yesterday / Today / Blockers summary
  - Action items

---

#### TASK — Ad-hoc / Unplanned Call
- **Use when:** Any unplanned call — prod issue, urgent requirement change, stakeholder escalation
- **Title pattern:** `CALL | Ad-hoc | <Short reason>`
- **Auto-set fields:** Activity = Meeting, Priority = 2, Tag = Unplanned
- **Description scaffold:**
  - Context
  - Duration
  - Decisions taken
  - Follow-up actions
  - **DoD:** Follow-up tasks created and linked

---

#### TASK — Analytics Work
- **Use when:** Dashboards, ad-hoc data pulls, investigations, reporting
- **Title pattern:** `ANALYTICS | <Area> | <Short goal>`
- **Auto-set fields:** Activity = Analytics/Reporting, Function = Analytics, Tag = Analytics
- **Description scaffold:**
  - Question to answer
  - Data sources
  - Approach
  - Key findings
  - Output (links / screenshots)
  - **DoD:** Results shared with stakeholders

---

## 6. Creation Apparatus (UX Flow)

The "+" button or command palette. Context-aware — knows where you are and pre-fills accordingly.

---

### 6.1 Creating a Feature

**Trigger:** "+" button on Epic page, Release page, or Backlog view.

**Quick-create form (minimal):**
1. Title
2. Epic (pre-filled if triggered from Epic page)
3. Release (pre-filled if triggered from Release page; else Backlog)
4. Priority (default 2)
5. Main Developer (optional)

**On create:**
- Feature is created with state = Backlog
- User is offered: "Add tasks now?" → shows template selector (checkbox list)
- Selected templates auto-create as child Tasks with pre-filled fields and description scaffolds
- Feature auto-syncs to ADO as Enhancement

---

### 6.2 Template Selector (after Feature creation)

```
Add tasks to this Feature?

[ ] Req Gathering          [ ] Design Implementation
[ ] Development            [ ] Testing
[ ] Review / Playback      [ ] Test Case Authoring
[ ] Automation / Sanity

[ Add selected tasks ]  [ Skip for now ]
```

- Ticking a template → task is created instantly with auto-filled title, fields, and description
- Can always add more tasks later from the Feature detail page

---

### 6.3 Creating an Overhead Task

**Trigger:** "+" → "Overhead Task" → template picker (Standup, Ad-hoc, Analytics)

No Feature link required. Assigned to the person creating it. Goes to their personal worklog.

---

### 6.4 Creating a Bug

**Trigger:** "+" → "Bug" → quick form.

**Quick-create form:**
1. Title
2. Type (Bug / Bug_UI / Bug_Text)
3. Priority
4. Linked Feature (optional — if blank, goes to Bug Pool)
5. Assigned to (optional)

---

### 6.5 Creating an Epic

**Trigger:** "+" → "Epic" → simple form (Title, Owner, Description).

Epics are created rarely — typically by PM when a new product capability area is identified.

---

### 6.6 Creating a Release

**Trigger:** "+" → "Release" → form (Title, Target date, Linked Iterations).

Done by PM at the start of a release cycle. Features are added to the Release from the Backlog view or directly during Feature creation.

---

## 7. Views and Navigation

---

### 7.1 Epic View
- List of all Epics (Active / Archived toggle)
- Click Epic → drills into all Features for that Epic, across all releases
- Shows total features, open features, in-progress, done — grouped by Release
- Lets you see the full history of a capability area

---

### 7.2 Release View
- List of all Releases
- Click Release → shows all Features in scope, their states, linked Epics
- Capacity summary: total estimated hours vs team capacity
- Progress bar: Features done / total

---

### 7.3 Backlog View
- All Features with Release = null (unscheduled)
- Sortable by Priority, Epic, Creation date
- Drag to assign to a Release (or use the Release field dropdown)

---

### 7.4 Feature Board (Kanban)
- Columns = Feature states: Backlog → In Planning → In Design → In Development → In QA → Done
- Cards show: Feature title, Epic tag, Assignee, Priority, task completion (e.g. 3/5 tasks done)
- Filterable by Release, Epic, Team, Assignee
- Drag card → state changes → syncs to ADO

---

### 7.5 Feature Detail Page
- Full field editor
- Task list (templated tasks shown with state badges)
- Linked Bugs list
- Activity log (state changes, comments)
- "Add Task" button → template picker
- "Log Bug" button → bug quick-create pre-linked to this Feature

---

### 7.6 Bug Pool View
- All standalone bugs (not linked to any Feature)
- Filterable by type, priority, state, area
- Bulk assign to iterations or features

---

### 7.7 My Work View (per person)
- All Tasks assigned to me across all Features
- Grouped by Feature
- Shows To Do / In Progress / Done
- Includes Overhead Tasks
- Hours logged today / this iteration

---

## 8. ADO Sync Strategy

| Direction | What syncs | When |
|---|---|---|
| ADO → Local | All work items (read) | Every 15 min (existing) |
| Local → ADO | Feature creates / edits | On save (immediate push) |
| Local → ADO | Task creates / edits | On save (immediate push) |
| Local → ADO | Bug creates / edits | On save (immediate push) |
| Local → ADO | State changes | On state transition |
| Local → ADO | Iteration reassignment (drag in planner) | On drop (immediate push) |
| Local → ADO | Assignee change (drag in planner) | On drop (immediate push) |
| Local → ADO | Estimate change | On save |
| None | Iteration Capacity Config | Local only — never synced |

**Source of truth:** This platform is source of truth. ADO is the sync target for external stakeholders and existing integrations.

**Fields that map to ADO:**

| Platform field | ADO field |
|---|---|
| Feature | Enhancement work item |
| Task | Task work item |
| Bug | Bug work item |
| Epic | Epic work item |
| Release | (ADO iteration grouping / tags) |
| State | State |
| Main Developer | Custom field (main_developer) |
| Activity/Type | Activity field |
| Iteration | iteration_path |
| Assigned to | assigned_to |
| Original Estimate | original_estimate |
| Completed Work | completed_work |

**Write-back implementation note:**
All Local → ADO writes go through `sync/ado_write.py`. Each field change is an individual PATCH to the ADO work items REST API (`/_apis/wit/workitems/{id}`). Writes are fire-and-forget with retry on failure (3 attempts, exponential backoff). Failures are logged and surfaced as a toast notification in the UI — they do not block the local save.

---

## 9. Analytics Integration

The operational layer feeds directly into existing dashboards with zero extra work because the data model is the same underlying DB.

| Dashboard | Benefit from new platform |
|---|---|
| Capacity | Feature + Task hours flow straight in; main_dev_team already correct |
| Items / Bugs | Features and bugs structured properly; Epic and Release filters now available |
| Teams | Per-person task load visible; overhead tasks included in time tracking |
| Summary | Release-level progress KPIs now possible |
| Release Outlook | Release entity gives a clean scope/timeline anchor |
| New: Epic Health | Across all releases — how is "Mileage Management" progressing historically? |

---

## 10. Phased Delivery Plan

---

### Phase 1 — Read + Edit (Foundation)
**Goal:** Make existing data editable. Prove the ADO write pipeline.

- Ticket detail side panel (click any item → full view)
- Edit fields: state, priority, assignee, main developer, iteration, estimate
- Save → write to ADO + update local DB
- Validate sync round-trip

**Delivers:** Team can manage work without opening ADO.

---

### Phase 2 — Feature Creation + Template Engine
**Goal:** New work starts here, not in ADO.

- Create Feature form with Epic + Release linking
- Template selector (checkbox-based task auto-generation)
- Pre-filled task titles, fields, and description scaffolds
- Bug quick-create with Feature linking
- All items sync to ADO on creation

**Delivers:** Standardised task creation with templates. Full traceability from Feature creation.

---

### Phase 3 — Epic and Release Management
**Goal:** The hierarchy model is live.

- Create / manage Epics (product areas)
- Create / manage Releases (delivery windows)
- Epic view: full Feature history across releases
- Release view: scope, progress, capacity summary
- Backlog view: unscheduled Features

**Delivers:** The "Mileage Management" history problem is solved. PM can see all work ever done on a capability.

---

### Phase 4 — Capacity Planning Layer + Board Views
**Goal:** Interactive capacity planning with ADO write-back. The dashboard becomes a control panel, not just a report.

---

#### 4A — Capacity Planner (Current)

The primary planning interface for 2026+ iterations. **Task-bound only** — estimates on non-Task items are excluded (new team practice as of 2026).

**Iteration Capacity Setup:**
- PM sets available hours per person per iteration at iteration start
- Form: select iteration → select person → set available days, leave days, hours/day
- System auto-computes total available hours
- Stored in local DB only (not synced to ADO)

**Planning Grid View:**
- Rows = team members, Columns = iterations (or single selected iteration)
- Each cell shows: Committed Hours / Available Hours + utilisation bar
- Colour coding: green (<90%), amber (90–110%), red (>110%)
- Click a cell → expands to show all Tasks assigned to that person in that iteration

**Item Assignment Panel (sidebar):**
- Shows all Tasks for the selected iteration not yet assigned (unassigned pool)
- Drag a Task from the pool onto a person in the grid → assigns it
- Drag a Task from one person to another → reassigns
- Drag a Task to a different iteration column → moves iteration
- All drags trigger immediate ADO write-back (assigned_to / iteration_path PATCH)
- Utilisation bars update live as items are moved

**Inline Alert System:**
- When a drag would push someone above 110% → red warning inline: "This will put [Person] at 118%. Confirm?"
- Amber warning at 90–110%: shown as passive indicator, no block
- Alerts also surface on page load for already-overcommitted people

**Estimate Editing:**
- Click any Task in the grid → inline edit of original_estimate
- Save → writes to local DB + ADO immediately

---

#### 4B — Capacity Audit Tab

Read-only historical view. All pre-2026 data lives here. **No planning actions available.**

**Content:**
- All existing capacity charts (utilisation, accuracy, throughput, per-person, per-team, forecast)
- Uses full mixed-methodology data (Tasks + Standalone non-Tasks, pre-2026 practice)
- Disclaimer banner at top: "Pre-2026 data uses mixed estimation practices — estimates may appear on both parent items and tasks. Figures are for reference only."
- Iteration filter defaults to pre-2026 iterations only

**Why separate:**
Pre-2026 data cannot be cleaned quickly — the team had no task-creation habit and estimates lived directly on bugs and enhancements. Separating it prevents the inflated numbers from polluting the current planner, while preserving the historical record for audit and trend analysis.

---

#### 4C — Board Views

- Feature Kanban board (drag-drop state changes → ADO write-back)
- My Work view (per-person task list, grouped by Feature, shows To Do / In Progress / Done)
- Bug Pool view (standalone bugs, bulk assign to iterations or features)
- Iteration planning: drag Backlog Features into a Release/Iteration

**Delivers:** Full day-to-day execution and sprint planning happens here. The capacity planner tells you who has room; the board views show you what's being worked on.

---

### Phase 5 — Intelligence Layer
**Goal:** The AI recommendation and analytics layer.

- Release scope recommendation: "Based on velocity and capacity, X features fit in this release"
- Risk flags: features in Dev with no QA task created, overdue tasks, unlinked bugs
- Epic Health dashboard: historical view of capability evolution
- Automated DoD checks: alert if a Feature moves to Done with open tasks

**Delivers:** The platform becomes proactive — it guides the team, not just records their work.

---

## 11. Decisions Log

All open questions resolved.

---

### D1 — Tasks: now in scope from Phase 2 *(revised 8 April 2026)*
**Original decision:** Tasks out of scope — too malleable in ADO at Phase 1.

**Revised decision:** Tasks are in scope from Phase 2 onwards. The Capacity Planning Layer (Phase 4) requires full Task write-back — iteration reassignment, assignee changes, and estimate edits must all sync to ADO. Additionally, the template engine (Phase 2) generates Tasks on Feature creation, which requires Task create in ADO.

**Phase 1 still excludes Task creation/editing** — the write-back infrastructure will be built and validated on Features and Bugs first. Task write-back is added as a Phase 2 dependency alongside the template engine.

---

### D2 — Role-Based Access Control (RBAC)
**Decision:** The platform needs an RBAC engine from day one. Item creation rights will be role-gated:

| Role | Can create | Can edit | Notes |
|---|---|---|---|
| Admin | Everything | Everything | Mayank for now |
| PM | Epics, Releases, Features | Epics, Releases, Features | |
| Developer | Features, Bugs | Own items | |
| QA | Bugs | Own items | |
| All | View | — | Read access by default |

**Implementation:** Role assigned per user at login. Checked before any create/edit action. Designed to be extended without code changes (roles stored in DB, not hardcoded).

---

### D3 — Spill-over tracking
**Decision:** A Feature carries both a **Planned Release** and an **Actual Release** field. If a Feature doesn't finish in its planned release and is moved, both fields are preserved. A `spill_over` flag is auto-set when `actual_release ≠ planned_release`.

**Why this matters:** Spill-overs are analysable — patterns in why Features slip (scope, capacity, dependencies) become visible in the analytics layer.

---

### D4 — Daily time logging with end-of-day reminders
**Decision:** This platform will eventually replace ADO for time logging entirely. The mechanism:
- Tasks/items a person marks as **Active** in the morning appear in an **end-of-day prompt** asking for hours logged
- Not forced — dismissable — but persistent if not actioned
- Completed work syncs to ADO
- Gradual rollout — ADO remains the fallback until team adopts this consistently

**Phase:** End-of-day prompt is a Phase 4 feature. Time logging fields are designed in from Phase 1 so the data model is ready.

---

### D5 — Bug re-opening: same ticket with audit trail
**Decision:** Reopen the same Bug ticket rather than creating a new one. Rationale: regression history is analytically valuable — knowing a bug regressed tells you something was missed in testing or the fix was incomplete.

**Constraint to watch:** Storage cost is negligible for a team of this size (thousands of bugs, not millions). API call cost for ADO sync is per-operation, not per-ticket-age, so reopening is no more expensive than creating new.

**Audit trail requirement:** Every state change on a Bug must be logged with timestamp + actor. This is a hard requirement for the reopen model to work.

---

### D6 — Authentication
**Decision:** Auth is in Phase 1. The platform will roll out to the whole team. For the POC, Mayank = Admin with full access. The auth system must be designed to support per-user roles from day one (see D2).

**Approach:** Session-based auth (username + password to start). OAuth/SSO (Microsoft, given the ADO/SharePoint environment) as a Phase 2 upgrade.

---

### D7 — Capacity Planning is a planning tool, not just a report
**Decision:** The Capacity Board is redesigned in Phase 4 as an interactive planning layer, not a dashboard. It has two tabs: Current (2026+, task-bound, interactive) and Audit (pre-2026, read-only, full chart set).

**Methodology boundary:** 2026 iterations use Tasks-only for estimation (new team practice). Pre-2026 data uses mixed methodology (estimates on parent items + tasks simultaneously). These two datasets must never be mixed in planning calculations. The data split is enforced at the query level, not by manual cleanup.

**ADO write-back is a hard dependency.** The planner cannot function without the ability to write `iteration_path` and `assigned_to` back to ADO. This must be validated in Phase 1 before Phase 4 is built.

**Capacity configuration lives locally.** Per-person, per-iteration available hours are not an ADO concept. They live in the local DB (`p_iteration_capacity` table) and are managed entirely within this platform.

---

## 12. Phase 1 — Revised Scope

Based on all decisions above, Phase 1 is:

**In scope:**
- Authentication (login / session management)
- RBAC engine (roles + permission checks)
- Create and edit: Epics, Releases, Features, Bugs
- Feature → Epic linking, Feature → Release linking (Planned + Actual)
- Bug → Feature linking (or standalone Bug Pool)
- ADO write-back for Epics, Features, Bugs (NOT Tasks)
- ADO write-back infrastructure validated: PATCH API, retry logic, error toasts — **this is the foundation Phase 4 depends on**
- Spill-over flag on Features

**Out of scope for Phase 1:**
- Task creation / editing (Phase 2 — after write-back is validated on Features/Bugs)
- Iteration Capacity Configuration table (Phase 4 — needs Task write-back first)
- Overhead task tracking
- Board / Kanban views (Phase 4)
- End-of-day reminders (Phase 4)
- Template engine (Phase 2)

---

## 13. Dependency Map

```
Phase 1: Auth + RBAC + Feature/Bug/Epic CRUD + ADO write-back foundation
    │
    ├──► Phase 2: Template Engine + Task create/edit + Task ADO write-back
    │       │
    │       └──► Phase 3: Epic + Release Management + Backlog view
    │               │
    │               └──► Phase 4A: Capacity Planner (needs Task write-back + Capacity Config table)
    │               │
    │               └──► Phase 4B: Audit Tab (no new dependencies — uses existing data)
    │               │
    │               └──► Phase 4C: Board Views + Kanban (needs Feature/Bug state write-back)
    │
    └──► Phase 5: Intelligence Layer (needs all operational data flowing correctly)
```

**Critical path to Capacity Planner:**
Phase 1 (write-back infra) → Phase 2 (Task write-back) → Phase 4A (Capacity Planner)

Phase 4B (Audit tab) can ship as soon as the Capacity Board UI is restructured — no write-back needed.

---

*PRD v0.3 — Capacity Planning Layer added. All decisions resolved. Ready for Phase 1 technical design.*
*Next step: DB schema design + ADO write API setup for Phase 1*
