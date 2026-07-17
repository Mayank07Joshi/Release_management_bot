# Issue Planning

- **Route / entry point**: `/issue-planning`
- **Backing file(s)**: `pages_dash/bugs/issue_planning.py` (layout + all callbacks,
  ~1,369 lines); `db/issue_planning.py` (persistence for `issue_caps` and
  `issue_dev_config`); reads `config/dev_capacity.py` for `DEV_NAMES`,
  `DESIGNER_NAMES`, `STORY_OWNER_NAMES`; writes through
  `sync/ado_write.py::write_fields()` / `FIELD_MAP`.
- **Nav location**: BUGS & ISSUES → "Issue Planning" (`app.py` `_NAV_TREE`,
  lines 110–113), built flag `True`.

## What it does

A single-screen triage board for all currently-open Bug-type work items. It
shows:

- A KPI row (All / P1 / P2 / P3 / Other / Unassigned / Past Due counts, each
  clickable) — `_build_kpi_row()` (`pages_dash/bugs/issue_planning.py:199-220`).
- A "developer load" panel — one row per developer showing a progress bar of
  current assigned-issue count vs. a combined cap, ordered by each developer's
  configured priority order — `_build_dev_load()` (`:225-302`).
- A "caps" panel — four buttons per priority (`P1`/`P2`/`P3`/`Other`), each
  settable to 2/4/6/8, that define how many issues a developer is allowed to
  carry — `_build_caps_section()` (`:304-362`).
- A big issue table with a sticky ID/title/priority/source/developer/iteration
  column block, plus one column per upcoming release month (a "release month
  matrix," not an iteration/sprint matrix — the page has an explicit banner
  saying so, `:642-644`) — `_build_table()` (`:389-557`).
- A right-hand side panel (opened by clicking a row) for editing one issue's
  Priority, Source, Story Size, Developer, Main Designer, User Story Owner,
  Iteration, and Release Month, with a pending-changes buffer and an explicit
  "Save Changes" / "Clear" pair — `_render_issue_panel()` (`:773-970`).
- A second side panel (opened by clicking a developer's name in the load
  panel) for reordering developers and toggling which priorities each one is
  allowed to receive — `_build_dev_panel_rows()` (`:559-586`).
- "AUTO-ASSIGN" — bulk-assigns every currently-unassigned issue to a developer
  using the priority order + per-priority permissions + combined cap
  (`_auto_assign`, `:1267-1333`).
- "CLEAR ALL" — bulk-unassigns every currently-assigned issue
  (`_clear_all`, `:1336-1369`).
- Clicking the "PAST DUE" KPI card downloads an `.xlsx` of overdue issues
  instead of filtering the table (`_past_due_download`, `:701-736`).

## Why it exists

Bugs arrive continuously and unevenly across developers and priorities. This
page is the lever PMs/QA leads use to balance bug intake: cap how many bugs of
each priority any one developer should be carrying at once (`issue_caps`),
decide which developers are even eligible for P1s/P2s/etc. and in what pecking
order they get filled first (`issue_dev_config`), then either assign issues
by hand or let "AUTO-ASSIGN" apply those rules in bulk. It's the bug-side
counterpart to Developer Capacity / Team Pulse, but scoped to the always-open
bug backlog rather than sprint-planned Enhancement work.

## How it works

**Data sources**

- `work_items_main`, filtered to `work_item_type IN ('Bug','Bug_UI','Bug_Text')`
  and a fixed list of open states (`New`, `Request Estimate`, `Estimated`,
  `Clarification`, `Active`, `Dev InProgress`, `Dev Review`, `Dev Complete`,
  `reopened`) — `_load_issues()` (`:113-152`). Columns read include `priority`
  (mapped to `P1`/`P2`/`P3`/`Other` labels via `_pri_label()`, `:84-90`),
  `assigned_to` (cleaned of the `<email>` suffix via `_clean_dev()`, `:81-82`),
  `type` (aliased as `source_type` → "Customer"/"Internal" Source badge),
  `iteration_path`, `release_date` (free-text ADO field, parsed to a
  `YYYY-MM` bucket by `_parse_release_ym()`, `:95-111`), `story_size`,
  `story_owner`, `main_designer`.
- `issue_caps` / `issue_dev_config` (`db/issue_planning.py`) — loaded via
  `load_caps()` / `load_dev_config()`, seeded with a default cap of 4 per
  priority and one row per `config.dev_capacity.DEV_NAMES` entry, ordered by
  insertion order (`init_issue_planning_tables()`, `db/issue_planning.py:23-53`).
  Table init is called from `app.py` at startup inside a `try/except`
  (`app.py:581-585`), consistent with the "optional init steps shouldn't abort
  startup" convention in master.md §6.
- Distinct `iteration_path` and `release_date` values (for the two dropdowns in
  the edit panel) are queried live from `work_items_main` on every panel open —
  `_get_iterations()` (`:154-161`) and the inline query at `:867-873`.

**Write path** — edits go through a local pending-changes buffer
(`ip-pending` store), then on "Save Changes" `_commit_ip_changes()`
(`:1130-1218`) does two things per changed field: writes the local row via
`_update_issue_local()` (`:163-184`, a `col_map`-driven `UPDATE work_items_main`)
*and* fire-and-forgets `sync.ado_write.write_fields()` for the same field —
except **Source**, see Known issues below. "AUTO-ASSIGN" and "CLEAR ALL" both
call `_update_issue_local()` + `write_fields()` per affected issue as well
(`:1319-1325`, `:1355-1360`). None of `issue_caps`/`issue_dev_config` ever
touch ADO — they're pure `p_*`-style app-only config, correctly kept out of
`work_items_main` per the field-routing rule in master.md §6.

**Major callback groups**

- **Caps**: `_cap_click` (`:659-676`) — click a cap button, `save_cap()`,
  re-render the caps section.
- **KPI filter / export**: `_kpi_filter` (`:679-698`) toggles the table's active
  filter; `_past_due_download` (`:701-736`) is a second callback on the *same*
  KPI-card `Input`, gated to fire only when the triggered key is `past_due`
  (the filter callback explicitly `PreventUpdate`s for that key so the two
  don't fight).
- **Issue side panel open/close**: `_toggle_issue_panel` (`:739-770`) opens on
  row click, snapshots the issue's current `iteration`/`release_date` into an
  `ip-initial` store (used by the dropdown callbacks below to distinguish a
  real user edit from the dropdown's own initial-value render).
  `_render_issue_panel` (`:773-970`) renders the panel body from
  `ip-panel-id` + `ip-pending` merged over the stored issue.
- **Pending-state setters** (one per field): `_select_ip_pri`, `_select_ip_src`,
  `_select_ip_dev`, `_select_ip_size`, `_select_ip_owner`, `_select_ip_designer`
  (`:975-1074`, all button-toggle pattern) and `_select_ip_iter` /
  `_select_ip_month` (`:1077-1116`, dropdown pattern, guarded against firing on
  the dropdown's own initial render via the `ip-initial` snapshot).
  `_clear_ip_pending` (`:1119-1127`) resets the buffer.
- **Commit**: `_commit_ip_changes` (`:1130-1218`) — the only callback that
  actually writes to `work_items_main` / ADO for row-level edits.
- **Developer panel**: `_toggle_dev_panel` (`:1221-1236`) open/close;
  `_dev_perm_change` (`:1239-1264`) handles both the up/down reorder buttons
  (`move_dev()`) and the per-priority permission toggles (`save_dev_field()`).
- **Bulk actions**: `_auto_assign` (`:1267-1333`), `_clear_all` (`:1336-1369`) —
  both post to the shared `notif-store` (defined outside this file, in the app
  shell) to surface a toast.

**Auto-assign algorithm** (`:1280-1333`): sort developers by
`priority_order`; sort unassigned issues by priority (P1 first) then Source
(Customer before Internal); for each issue, walk developers in priority order
and assign to the first one that (a) is under its combined cap and (b) has
`can_p1`/`can_p2`/`can_p3`/`can_other` set for that issue's priority.

## Known issues / quirks

- **Caps are configured per priority but enforced only as a single combined
  total.** `issue_caps` stores four independent values (P1/P2/P3/Other cap),
  and the caps panel and `db/issue_planning.py`'s own docstring ("global cap
  *per priority*... applies to every dev") imply each priority is capped
  separately. But both `_build_dev_load()` (`:226,236-237`) and
  `_auto_assign`'s `_can_take()` (`:1289-1295`) only ever check a developer's
  **total** open-issue count against `sum(caps.values())`. A developer could
  end up carrying, e.g., 16 P1s and zero of anything else and still register
  as "under cap" — the per-priority caps have no independent enforcement
  anywhere in this file.
- **Source edits are silently local-only and will be reverted by the next
  sync.** The edit panel's "Source" toggle (Customer/Internal) sets
  `pending["source"]`, which `_commit_ip_changes` (`:1158-1159`) writes to
  `work_items_main.type` via `_update_issue_local()` — but never adds a
  corresponding key to `ado_fields`, so `write_fields()` is never called for
  it. `type` is read from ADO's `Custom.Type` field during sync
  (`sync/ado_sync.py:222`), but `sync/ado_write.py`'s `FIELD_MAP` has no entry
  for `type`/`source` at all. Per the field-routing rule (master.md §6) and
  the delete-then-insert upsert on `work_items_main` (db.md §7), any Source
  edit made here is lost the moment the next full ADO resync reinserts that
  row from ADO's actual `Custom.Type` value — every other field edited in this
  panel (Priority, Developer, Story Size, Main Designer, Story Owner,
  Iteration, Release Month) round-trips to ADO; Source does not.
- **Cap values are UI-limited to `{2, 4, 6, 8}`** (`_CAP_OPTIONS`, `:28`) even
  though the underlying `issue_caps.cap_value` column is a plain `INTEGER` —
  there's no way to set an odd cap or anything above 8 without a direct SQL
  update.
- **`_ALL_MONTH_OPTIONS` is a hardcoded literal list running only through
  "Jun 2027"** (`:41-45`). Once that date passes, the release-month matrix
  silently stops offering later months as dropdown options (though the table
  columns themselves are also filtered to `>= cur_ym`, so the visible symptom
  would be first noticed in the edit panel's Release Month dropdown, not the
  table).
- **"Other" priority is a lossy catch-all in both directions.** `_pri_label()`
  (`:84-90`) maps any priority that isn't 1/2/3 (including `NULL`) to the
  label `"Other"`; if a user then re-saves that issue without changing
  Priority, `_pri_int()` (`:92-93`) converts `"Other"` back to the literal
  integer `4` and writes it to both `work_items_main.priority` and ADO's
  `Microsoft.VSTS.Common.Priority` — so an originally-`NULL`/unset priority
  can become a hardcoded `4` just by touching the panel and saving unrelated
  fields.
- **`STORY_OWNER_NAMES` is a hardcoded 4-name list** in
  `config/dev_capacity.py` with a comment noting it "must match ADO picklist
  values exactly" — any picklist change in ADO requires a matching manual
  edit here or the dropdown silently offers stale options.
- **The PAST DUE KPI card behaves differently from every other KPI card** — it
  triggers a file download (`_past_due_download`) instead of filtering the
  table, via a second callback listening on the same
  `{"type": "ip-kpi", "key": ALL}` input pattern, with the filter callback
  explicitly special-cased to no-op for `key == "past_due"` (`:694-695`). Easy
  to miss when adding a new KPI card, since the "click to filter" behavior is
  the default for every other key.
- **All write-back calls (`write_fields`, plural per-issue loops in
  `_auto_assign`/`_clear_all`) are wrapped in bare `try/except: pass`**
  (`:1192-1196`, `:1319-1325`, `:1355-1360`) — an ADO write failure is
  silently swallowed with no user-facing error, only a success toast claiming
  the write happened (e.g. `"Auto-assigned N issue(s) to ADO"` is shown even
  if every individual `write_fields` call failed, since `write_fields` itself
  is fire-and-forget and failures only surface via
  `get_pending_failures()`, which this page never calls).
