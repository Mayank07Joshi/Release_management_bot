# Release Confidence Score — Claude Code Brief
## Feature to build inside an existing planning tool

---

## Context

This is a new page/module to be added to an existing planning tool that is already being built. The page is called **Release Confidence Score (RCS)**. It does two things:

1. Scores every user story/ticket on a formulaic, weighted model to produce a confidence grade (like a credit rating — AAA down to NR)
2. Checks a defined set of verifiable artifacts against VSTS/Azure DevOps (ADO) to determine if mandatory deliverables actually exist on the story

The tool already connects to VSTS/ADO. All story data, field values, linked items, and work item relationships should be pulled from there.

---

## What the Page Should Do

- Accept a **Story ID** (VSTS work item ID) as input
- Pull all relevant data from VSTS for that story
- Run the **Hard Gate checks** first — if any fail, cap score at 30 and show blocked state
- Run all **5 scoring dimensions** and compute the weighted RCS
- Show the **grade** (AAA / AA / A / BBB / BB / NR) with colour coding
- Show a **dimension breakdown** — score per dimension, what passed/failed within each
- Show the **Verifiable Artifact check results** — which artifacts are present and which are missing
- Show the **Honor System items** as a separate section — displayed as a checklist for the user to self-report
- Show the **release decision** based on grade (who needs to sign off)
- Allow a **Release-level view** — input multiple story IDs, compute weighted aggregate RCS for the full release

---

## Grade Scale

| Grade | Score Range | Colour     | Release Decision |
|-------|-------------|------------|-----------------|
| AAA   | 90–100      | Green      | Auto-approved, no action needed |
| AA    | 80–89       | Green      | Auto-approved, minor notes logged |
| A     | 70–79       | Amber      | Release Manager sign-off required |
| BBB   | 60–69       | Amber      | Explicit Release Manager sign-off before deployment |
| BB    | 50–59       | Red        | Three-way sign-off: Dev Lead + QA Lead + Release Manager |
| NR    | Below 50    | Dark Red   | BLOCKED — story cannot deploy, issues must be resolved |

**Hard Gate override:** If any hard gate triggers, score is capped at 30 and grade is forced to NR regardless of formula result.

---

## Hard Gates — Check These First

If ANY of the following are true, the story is immediately NR (score = 30, blocked). Display which gate triggered.

| # | Gate | How to Check |
|---|------|-------------|
| 1 | CI pipeline failing on current build | Check CI status linked to the story's PR or branch in ADO |
| 2 | SonarQube blocker or critical issues on new code | Call SonarQube API for the story's branch — check issue severity |
| 3 | SonarQube security hotspots unreviewed on new code | SonarQube API — hotspot review status on new code |
| 4 | No code review / peer review completed | Check linked Pull Request in ADO — PR must have at least 1 approval |
| 5 | Zero acceptance tests — no test cases linked to story | ADO native: check `Tested By` relationships on the work item — count must be > 0 |

---

## Scoring Model — 5 Dimensions

### Formula
```
RCS = (D1 × 0.25) + (D2 × 0.25) + (D3 × 0.25) + (D4 × 0.15) + (D5 × 0.10)
```

Each dimension scores 0–100. Final RCS is 0–100.

---

### Dimension 1: Story Definition Quality (Weight: 25%)

| Indicator | Max Points | Scoring Logic | Where to Get Data |
|-----------|-----------|---------------|-------------------|
| Pre-Dev QA Review gate completed | 20 | Yes = 20, No = 0 | Custom VSTS field: `Pre-Dev QA Review Completed` (Yes/No) |
| Acceptance criteria approved and testable | 20 | Yes = 20, No = 0 | Custom VSTS field: `Acceptance Criteria Approved` checkbox in Story Completion Checklist |
| Story size | 20 | XS = 20, S = 16, M = 12, L = 6 | Custom VSTS field: `Size` (dropdown: XS/S/M/L) |
| All dependencies identified and resolved at sprint start | 20 | Yes = 20, Partial = 10, No = 0 | Check linked blocked/blocking work items — if any linked items are still active/open = Partial or No |
| Definition of Ready checklist items 1–5 complete | 20 | % complete × 20 | Custom VSTS field: `Story Completion Checklist` — read first 5 items |

D1 Score = sum of above points (max 100)

---

### Dimension 2: Code Quality via SonarQube (Weight: 25%)

Pull all data from SonarQube API using the story's branch or PR identifier.

| Indicator | Max Points | Scoring Logic | SonarQube Metric |
|-----------|-----------|---------------|-----------------|
| Reliability rating on new code | 30 | A=30, B=22, C=15, D=8, E=0 | `new_reliability_rating` |
| Security rating on new code | 30 | A=30, B=22, C=15, D=8, E=0 | `new_security_rating` |
| Test coverage on new code | 25 | ≥80%=25, 70–79%=18, 60–69%=12, 50–59%=6, <50%=0 | `new_coverage` |
| Technical debt ratio (SQALE) on new code | 15 | ≤5%=15, 6–10%=10, 11–20%=5, >20%=0 | `new_sqale_debt_ratio` |

D2 Score = sum of above points (max 100)

Note: If SonarQube data is unavailable for the story's branch, display a warning and score D2 as 0 with a flag explaining why.

---

### Dimension 3: Testing Rigour (Weight: 25%)

| Indicator | Max Points | Scoring Logic | Where to Get Data |
|-----------|-----------|---------------|-------------------|
| QA cycle count (times story returned from QA to Dev) | 35 | 0 returns=35, 1=20, 2=10, 3+=0 | Count state transitions: `In QA` → `In Dev` from work item history in ADO |
| Test cases documented and linked before QA started | 25 | Yes=25, No=0 | Check `Tested By` link timestamp vs timestamp when story moved to `In QA` — linked test cases must exist before QA state |
| QA sign-off formally obtained | 20 | Yes=20, No=0 | Custom VSTS field: `QA Sign-off Obtained` (Yes/No checkbox in Story Completion Checklist) |
| No open defects linked to story at time of scoring | 20 | 0 open=20, 1 open=10, 2+ open=0 | Count linked Bug work items where State != Closed/Resolved |

D3 Score = sum of above points (max 100)

---

### Dimension 4: Release Process Health (Weight: 15%)

| Indicator | Max Points | Scoring Logic | Where to Get Data |
|-----------|-----------|---------------|-------------------|
| CI pipeline green on current build | 40 | Green=40, Red=0 (also triggers Hard Gate if Red) | ADO pipeline run status linked to story's PR/branch |
| Code review (peer review) completed and approved | 35 | Approved=35, No review=0 (also triggers Hard Gate if missing) | Linked Pull Request in ADO — PR approval status |
| Story Completion Checklist completion rate | 25 | % of 16 items complete × 25 | Custom VSTS field: `Story Completion Checklist` — count checked items / 16 |

D4 Score = sum of above points (max 100)

---

### Dimension 5: Risk Profile (Weight: 10%)

Start at 100. Deduct for each risk factor present. Minimum score is 0.

| Risk Factor | Deduction | How to Detect |
|-------------|-----------|---------------|
| DB schema changes | −25 | Custom VSTS field: `DB Schema Changes` (Yes/No) |
| Security-sensitive code touched (auth, payments, PII, encryption) | −25 | Custom VSTS field: `Security Sensitive` (Yes/No) |
| API contract changes (new endpoints, modified request/response) | −20 | Custom VSTS field: `API Changes` (Yes/No) |
| New external integration or third-party dependency | −20 | Custom VSTS field: `External Integration` (Yes/No) |
| Story sized L (>24 dev hours) | −10 | From `Size` field — if L, apply deduction |

D5 Score = (100 − total deductions, minimum 0)

---

## Verifiable Artifact Checks

These are separate from the RCS score. They are a checklist of artifacts that MUST exist on the story. Display them as a distinct section on the page — green tick if present, red cross if missing.

Each missing artifact should display: what it is, why it matters, and who is responsible for providing it.

| # | Artifact | VSTS Field / Mechanism | Required At Stage |
|---|----------|----------------------|-------------------|
| 1 | Figma / Design Link | Custom URL field: `Design Link` — check not empty, must contain `figma.com` | Before `In Dev` |
| 2 | Final Design Sign-off By | Custom text field: `Design Sign-off By` — check not empty | Before `Estimation` |
| 3 | Final Design Sign-off Date | Custom date field: `Design Sign-off Date` — check not empty | Before `Estimation` |
| 4 | Estimation Sheet Link | Custom URL field: `Estimation Sheet Link` — check not empty | Before `In Dev` |
| 5 | Child tasks exist | Native ADO relationship — count child work items linked to story. Must be > 0 | Before `In Dev` |
| 6 | API Documentation Link | Custom URL field: `API Doc Link` — only required if `API Changes = Yes`. Check not empty when applicable | Before `Ready for QA` |
| 7 | Technical Documentation Link | Custom URL field: `Technical Doc Link` — check not empty | Before `Ready for QA` |
| 8 | Test Cases linked (Azure Test Plans) | Native ADO `Tested By` relationship — count must be > 0 | Before `In QA` |
| 9 | No open P1 bugs | Native ADO — linked Bug work items where State != Closed AND Priority = 1. Count must be 0 | Before `Ready for Release` |
| 10 | Business Sign-off Status | Custom dropdown field: `Business Sign-off Status` — must equal `Approved` | Before `Ready for Release` |
| 11 | Business Sign-off By | Custom text field: `Business Sign-off By` — check not empty | Before `Ready for Release` |
| 12 | Release Notes | Custom text field: `Release Notes` — check not empty, must have content (not just whitespace) | Before Deployment |

**Display logic:**
- If the artifact is not applicable (e.g., API Doc Link when API Changes = No) — show as "N/A" in grey, not a red cross
- If the artifact is missing and the story is past the stage where it should exist — show as a red cross with the responsible person's role
- If the artifact exists — green tick with the value or a truncated preview of the URL

---

## Honor System Items

These cannot be verified from VSTS. Display them as a self-report checklist — the user (story owner or QA) ticks them manually. They do NOT affect the RCS score. They are displayed separately with a clear label: "Self-reported — not verified by system."

Show these in a collapsible section so they don't clutter the main score view.

**Honor System Checklist Items:**
- Internal design discussion held
- Competitive research conducted by design team
- Playback session conducted with QA and Dev team
- Developer self-verification completed before QA handover
- Progress demo conducted with stakeholders
- Stakeholder feedback captured and documented
- Peer review of test cases by second QA
- KT (Knowledge Transfer) session scheduled and completed
- Internal dev syncs held during development phase

---

## Release-Level Score

On the same page or a sub-tab, allow the user to input multiple story IDs for a full release.

**Aggregate scoring:**
- Compute individual RCS for each story
- Apply size-based weighting for the aggregate:
  - XS stories: weight = 0.5
  - S stories: weight = 1.0
  - M stories: weight = 1.5
  - L stories: weight = 2.0
- Release RCS = weighted average of all individual story scores

**Display:**
- Summary card showing Release RCS grade with colour
- Table of all stories with their individual grade, size, and score
- Count of stories per grade tier
- Any stories that are NR or have triggered Hard Gates — highlighted prominently at the top
- Release decision based on aggregate grade (same decision authority table as individual stories)

---

## VSTS Custom Fields Required

The following custom fields need to exist in VSTS for the tool to read. If they don't exist, the tool should display a warning on that specific check rather than crashing.

| Field Name | Field Type | Used In |
|------------|-----------|---------|
| `Pre-Dev QA Review Completed` | Yes/No (boolean) | D1 |
| `Story Completion Checklist` | Multi-line text or structured field | D1, D4 |
| `Size` | Dropdown: XS, S, M, L | D1, D5, Release aggregate |
| `QA Sign-off Obtained` | Yes/No (boolean) | D3 |
| `DB Schema Changes` | Yes/No (boolean) | D5 |
| `Security Sensitive` | Yes/No (boolean) | D5 |
| `API Changes` | Yes/No (boolean) | D5, Artifact #6 |
| `External Integration` | Yes/No (boolean) | D5 |
| `Design Link` | URL | Artifact #1 |
| `Design Sign-off By` | Text | Artifact #2 |
| `Design Sign-off Date` | Date | Artifact #3 |
| `Estimation Sheet Link` | URL | Artifact #4 |
| `API Doc Link` | URL | Artifact #6 |
| `Technical Doc Link` | URL | Artifact #7 |
| `Business Sign-off Status` | Dropdown: Pending, Approved | Artifact #10 |
| `Business Sign-off By` | Text | Artifact #11 |
| `Release Notes` | Multi-line text | Artifact #12 |

---

## SonarQube Integration

- The tool needs to connect to SonarQube via its REST API
- The connection requires: SonarQube base URL + API token
- To identify the correct project/branch for a story: the story's linked PR or branch name is used to find the SonarQube component key
- Metrics to fetch: `new_reliability_rating`, `new_security_rating`, `new_coverage`, `new_sqale_debt_ratio`, `new_security_hotspots_reviewed`
- If SonarQube is unreachable or the project is not found: display D2 as unavailable with a clear warning — do not block the rest of the score from computing

---

## UI Notes

- The page should feel like a dashboard, not a form
- Primary element: large score display (number + grade label + colour) at the top
- Below that: dimension breakdown — 5 cards, one per dimension, each showing the dimension score and the key indicators within it with pass/fail/partial states
- Below that: Verifiable Artifact section — two columns, ticks and crosses, clean and scannable
- Below that: Honor System section — collapsible, clearly labelled as self-reported
- Below that (or on a sub-tab): Release-level view
- Hard Gate failures should be shown as a prominent banner at the very top before the score — red, impossible to miss, listing which gates failed
- Colour scheme for grades: AAA/AA = green, A/BBB = amber, BB = orange-red, NR = dark red / blocked state
- The score should update in real time as the user inputs a story ID and data loads from VSTS and SonarQube

---

## Data Flow Summary

```
User inputs Story ID
        ↓
Fetch work item from ADO API (fields, relationships, history, linked items)
        ↓
Fetch SonarQube data for story's branch/PR
        ↓
Run Hard Gate checks → if any fail → cap score at 30 → show NR + which gates failed
        ↓
Compute D1 from ADO fields
Compute D2 from SonarQube metrics
Compute D3 from ADO history + linked bugs + test case links
Compute D4 from ADO PR status + pipeline status + checklist field
Compute D5 from ADO custom risk fields
        ↓
Apply weights → compute final RCS → assign grade
        ↓
Run Verifiable Artifact checks → show pass/fail/N-A per artifact
        ↓
Display full results
```

---

## Notes for Claude Code

- All ADO API calls should use the Azure DevOps REST API v7.0
- Story Completion Checklist field may be a structured multi-line text — parse it to count checked items (assume markdown checkbox format: `- [x] item` for checked, `- [ ] item` for unchecked)
- QA cycle count: read the work item's state history (`/workItems/{id}/updates` endpoint) and count transitions where `newValue = "In Dev"` AND `oldValue = "In QA"`
- Child task count: use `/workItems/{id}/relations` and count items with `rel = "System.LinkTypes.Hierarchy-Forward"`
- Linked bugs: use `/workItems/{id}/relations` and filter for work item type = Bug, then fetch each bug's State and Priority fields
- Test case links: use `/workItems/{id}/relations` and filter for `rel = "Microsoft.VSTS.Common.TestedBy-Reverse"` — count these
- PR status: use `/git/repositories/{repoId}/pullRequests` filtered by the story's linked PR ID — check `reviewers` for any with `vote = 10` (approved)
- Handle missing fields gracefully — if a custom field doesn't exist on a work item, treat it as unanswered/empty and score accordingly, with a visible warning on that specific indicator
