# Leave Management

- **Route / entry point**: `/leave-management` (`pages_dash/capacity/leave_management.py:18`, `dash.register_page`)
- **Backing file(s)**: `db/leaves.py` (`p_company_holidays`, `p_dev_leaves`)
- **Nav location**: CAPACITY → "Leave Management" (`app.py:117`, built flag `True`)

## What it does

A BA-facing form-plus-table page for recording two kinds of time off that
reduce team capacity:

- **Company holidays** — a date + name, office-wide (left column form/table,
  `_holiday_form()` / `_holiday_table()`).
- **Developer leaves** — pick a developer from a dropdown, a leave type
  (Planned / Sick), a duration (Full day = 9h / Half day = 4.5h), and either a
  single date or a date range (right column form/table, `_leave_form()` /
  `_leave_table()`). Range entry auto-skips weekends and any already-recorded
  company holiday (`leave_management.py:311-312`, via `_workdays_in_range()` +
  `_holiday_set()` from `db/leaves.py`).

Both tables support inline delete (✕ button, pattern-matched `ALL` ids) and
the leave table has a "filter by developer" dropdown. Both list dates
newest/soonest first with past entries dimmed (`opacity: 0.5`).

## Why it exists

Capacity math elsewhere in the app (Developer Capacity, Admin Hours, and any
other page that calls `db.leaves.get_leave_capacity()`) needs to know how many
hours a developer actually has available in a given month after holidays and
personal leave are subtracted. This page is the only UI that writes that data
— there's no other entry point for holidays or leave days.

## How it works

- **Reads/writes** `p_company_holidays` and `p_dev_leaves` exclusively through
  `db/leaves.py`'s public functions — confirmed imports at
  `leave_management.py:13-16`: `add_dev_leave`, `add_holiday`,
  `delete_dev_leave`, `delete_holiday`, `get_dev_leaves`, `get_holidays`,
  `init_leave_tables`, plus two "private" helpers (`_workdays_in_range`,
  `_holiday_set`) that the page reaches into directly for range-expansion on
  the client side before calling `add_dev_leave()`.
- `init_leave_tables()` is called once from `app.py`'s startup block
  (`app.py:557-561`, wrapped in try/except per the standard "optional init
  step" convention in master.md §6) — the page module itself never calls it.
- **Developer dropdown source**: `_DEV_OPTIONS` (`leave_management.py:32`) is
  built from `config.dev_capacity.DEVELOPERS` only — i.e. staff whose `team`
  is `"Development"` or `"Mobile"` (`config/dev_capacity.py:44`). QA, Design,
  and Management staff (including `Chhavi Bhardwaj` and `Geetika Khanna`, who
  are hardcoded into `admin_hours.py`'s roster — see that page's doc) cannot
  be selected here, so no one can log a leave day for them through this UI.
  See Known issues.
- **Write path**: both `_add_holiday` and `_add_leave` write straight to
  Postgres via `db/leaves.py` (no `sync.ado_write` involved — these are
  app-only `p_*` fields, correctly following the DB field-routing rule in
  master.md §6) and then call `bust_ui_cache()` (`leave_management.py:276`,
  `321`) so any page rendering leave-derived UI picks up the change on next
  render. `bust_loader_cache()` is not called and doesn't need to be — leave
  data never touches `work_items_main`.
  - `add_dev_leave()` upserts one row per expanded date with
    `ON CONFLICT (developer_name, leave_date) DO UPDATE` (`db/leaves.py:148-156`)
    — re-adding a leave for a date that already has one **silently overwrites**
    type/hours/created_by with no warning to the BA.
  - `add_holiday()` returns `0` (treated as "duplicate date") on **any**
    exception, not just the unique-constraint violation
    (`db/leaves.py:97-108`, bare `except Exception: return 0`) — a real DB
    connectivity problem would surface to the user as "That date already has
    a holiday entry," which is misleading.
- **Delete path**: `Input({"type": "lm-del-hol"/"lm-del-leave", "id": ALL}, "n_clicks")`
  pattern-matching, gated by `ctx.triggered_id` + a truthy click count
  (`leave_management.py:337-338`, `391-392`) to avoid firing on initial render.
- **Capacity consumers**: `db.leaves.get_leave_capacity(yms)` (used by
  `pages_dash/capacity/admin_hours.py` and — per `db.md` §2 — the Developer
  Capacity grid) sums `p_dev_leaves.hours` per `(developer, month)` and
  `p_company_holidays` count × 9h per month, keyed by calendar month
  (`TO_CHAR(..., 'YYYY-MM')`), not by any ADO sprint/iteration concept.

## Known issues / quirks

- **Leave can't be logged for everyone Admin Hours tracks leave for.**
  `admin_hours.py`'s `_PLAN_DEVS` (`admin_hours.py:40-43`) explicitly adds
  `Chhavi Bhardwaj` and `Geetika Khanna` (QA / Management) to its roster and
  pulls their leave hours via `get_leave_capacity()`, but this page's
  developer dropdown (`_DEV_OPTIONS`, built from `DEVELOPERS` only) never
  offers those two names — so their "LEAVE H" column on Admin Hours will
  always read 0/"—" regardless of actual time off taken. One of the two
  hardcoded staff-directory derivations (`DEVELOPERS` vs. the ad hoc
  `DEVELOPERS + [...]` list in `admin_hours.py`) needs to be the actual
  source of truth for "who can have leave logged," not two different subsets
  living in two files.
- **Silent overwrite on duplicate date+developer.** Re-submitting a leave for
  a developer/date pair that already exists overwrites type, hours, and
  `created_by` with no confirmation or diff shown (`db/leaves.py:151-156`).
- **`add_holiday()` swallows all exceptions**, not just the unique-constraint
  one it's meant to catch, and reports every failure as "date already has a
  holiday entry" (`db/leaves.py:97-108`) — masks real DB errors.
- **Inconsistent sort/grouping between the two tables**: the holiday table
  explicitly reorders to upcoming-then-past ascending
  (`leave_management.py:348-350`), while the leave table is a flat
  `ORDER BY leave_date DESC` from `get_dev_leaves()` (`db/leaves.py:182`) with
  no upcoming/past separation — past and future leave rows are interleaved by
  date rather than grouped.
- No pagination or date-range limit on either table — `get_holidays()` and
  `get_dev_leaves()` both return the full table every render; fine at current
  data volumes, worth revisiting if leave history accumulates for years.
