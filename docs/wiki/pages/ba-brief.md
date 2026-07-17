# BA Team Brief

- **Route / entry point**: `/ba-brief`
- **Backing file(s)**: `pages_dash/misc/ba_brief.py`
- **Nav location**: REFERENCE section, label "BA Team Brief" — flagged
  placeholder in `app.py`'s `_NAV_TREE` (`built=False`, `app.py:122`).

## What it does

Renders a static "BA Team Brief" screen: a section label, an H1-style title
with an amber "PLACEHOLDER" pill next to it, a one-line subtitle ("Business
analysis reference, team contacts, and process documentation."), and a single
card reading "Not designed yet — placeholder in the structure so the workflow
is complete. To be built." That's the entire page — no data is fetched, no
interactive elements are rendered, and there are no callbacks anywhere in the
file.

## Why it exists

Reserves the nav slot and route for a future business-analyst reference page
(team contacts, process docs — per the subtitle text already written into the
layout) so the REFERENCE section of the sidebar has a complete, navigable
structure ahead of the content existing — the same "amber dot" placeholder
convention used elsewhere in the nav (`master.md` §5, §7).

## How it works

`layout(**_)` (`ba_brief.py:12-51`) is a pure function returning a static
`html.Div` tree. There is no `engine` import, no `p_*` table, no `config`
import, no `dash.callback` — nothing dynamic to describe. This is the one
page of the four covered in this batch where the nav's "placeholder" flag and
the file's actual content agree: unlike `release_status.py` (also flagged
placeholder in the nav but backing a ~1,100-line, fully working page — see
`release-status.md`), this file really is unbuilt, matching the literal text
it renders ("Not designed yet").

## Known issues / quirks

None observed — there's no logic in the file for a quirk to hide in. Worth
noting for whoever builds this next: there is currently nothing here to
migrate away from (no data access, no state, no styling beyond the standard
`var(--*)` CSS variables already used elsewhere), so the eventual real
implementation can start from a blank slate rather than needing to unwind any
existing behavior.
