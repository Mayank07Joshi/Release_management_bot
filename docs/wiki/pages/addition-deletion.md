# Addition & Deletion

- **Route / entry point**: `/addition-deletion`
- **Backing file(s)**: `pages_dash/trends/addition_deletion.py` (thin route
  wrapper); shared logic in `pages_dash/trends/focus.py` — see
  [`summary.md`](summary.md) for the full data/callback breakdown, not
  duplicated here per the `master.md` §6 shared-tab-content convention
- **Nav location**: TRENDS section, label "Addition & Deletion", built ✅
  (`app.py:100-102`)

## What it does

Renders the same `focus_tab_content()` view documented in
[`summary.md`](summary.md), but pinned open directly on the **Addition &
Deletion** view (the monthly added/closed/net/running-total chart with
platform/horizon/source/issue-type chip filters and the month-click P1
drill-down panel) with the tab strip and Summary-tab STATE filter hidden —
there's only one view to show, so there's nothing to switch between.

## Why it exists

A dedicated, single-purpose URL for the trend chart on its own — useful for
linking directly to the addition/deletion view (e.g. from a report or a
bookmark) without landing on the two-tab Summary page and having to click
into the second tab every time.

## How it works

`addition_deletion.py` (the entire file, 9 lines) is a thin wrapper:

```python
def layout(**_):
    return focus_tab_content(default_tab="sprint", tabs_visible=False)
```

Two arguments differ from the Summary page's call (`focus_tab_content()`
with no args):

- **`default_tab="sprint"`** — despite the name (a holdover from before the
  "sprint" tab was repointed at Addition & Deletion content; see
  [`summary.md`](summary.md) Known issues), this selects the Addition &
  Deletion render path (`focus.py::_render_sprint_adl`), not the Data Load
  Summary path.
- **`tabs_visible=False`** — hides the tab strip, the STATE dropdown, and the
  page title/subtitle row (all conditioned on `tabs_visible` inside
  `focus_tab_content()`, e.g. `focus.py:194-199, 262, 292`), and swaps the
  breadcrumb text to `"TRENDS · ADDITION & DELETION"` (`focus.py:172-176`)
  instead of `"VSTS DATA · FOCUS AREA & SPRINT ACTIVITY"`. The tab-strip
  button elements are still rendered, just hidden (`focus.py:196-198`),
  because the tab-switch callback (`_select_tab`) and the content-render
  callback both still wire up against those component IDs regardless of which
  page embeds them.

See [`summary.md`](summary.md) for the full query/callback/known-issues
detail — everything there (the shared `work_items_main` queries, the chip
filter callbacks, the month drill-down panel, the dead `_render_sprint`
function) applies equally to this route since it's the same code path.

## Known issues / quirks

- All of the shared-logic quirks in [`summary.md`](summary.md) apply here
  too (dead `_render_sprint`, "sprint"-named tab actually showing Addition &
  Deletion content, P1-only drill-down panel, repeated `work_items_main`
  reads).
- **Nothing on this page indicates it's showing filtered/reduced content** —
  a user landing here has no way to tell (short of already knowing) that this
  is one tab of a two-tab page that also exists at `/summary`; there's no
  cross-link from here back to the full Summary view.
- `layout(**_)` accepts and discards all keyword arguments (Dash passes path/
  query-string params this way) but never inspects them — no query-string
  driven behavior (e.g. deep-linking to a specific month or filter) exists on
  this route today.
