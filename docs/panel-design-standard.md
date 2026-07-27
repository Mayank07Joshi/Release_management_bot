# Panel Design Standard

Reference implementation: `pages_dash/misc/release_status.py` — the Edit Release Row panel.
All side panels in this app must follow this spec.

---

## Color Palette

```python
_BG_PAGE = "rgb(10,13,21)"       # page background — darkest layer
_BG_CARD = "rgb(18,22,31)"       # panel background
_BG_HEAD = "rgb(23,28,40)"       # input / textarea / date field backgrounds
_BD      = "rgb(38,44,58)"       # primary border (panel edges, section dividers)
_BD_CELL = "rgb(30,36,51)"       # secondary border (stage rows, table cells)
_FG      = "rgb(234,236,242)"    # primary text
_MT      = "rgb(139,146,164)"    # secondary text (subtitles, placeholders)
_DIM     = "rgb(91,98,118)"      # dimmed text (section labels, field labels)
_INDIGO  = "rgb(110,118,241)"    # primary accent — supertitle, save button, selected state
_GREEN   = "rgb(70,194,142)"     # done / success
_AMBER   = "rgb(224,162,60)"     # WIP / warning
_RED     = "rgb(239,110,99)"     # not started / danger
_CYAN    = "rgb(63,182,201)"     # QA / info
_MONO    = "'JetBrains Mono','SF Mono',monospace"
```

**Rule:** use these exact RGB values, never CSS variables or hex equivalents.
This keeps panels visually consistent regardless of page-level theme overrides.

---

## Panel Container

```python
{
    "position": "fixed", "top": "0", "right": "0",
    "height": "100vh", "width": "760px",          # standard width
    "background": _BG_CARD,
    "borderLeft": f"1px solid {_BD}",
    "overflowY": "auto",
    "zIndex": "41",
    "boxShadow": "rgba(0,0,0,0.467) -8px 0px 24px",
}
```

- Width: **760 px**. Use 620 px only for secondary/nested panels.
- The panel itself scrolls (`overflowY: auto`). No inner scroll containers unless needed.
- Backdrop: semi-transparent `rgba(0,0,0,0.50)` div behind the panel at `zIndex: 40`.

---

## Header Anatomy

```
┌─────────────────────────────────────────────┬───┐
│  SUPERTITLE (9.5px, indigo, uppercase)       │ ✕ │
│  Story Title — bold, 14px, _FG              │   │
│  #id · Name  — 11px, _MT, monospace         │   │
│  [badge] [badge]                             │   │
└─────────────────────────────────────────────┴───┘
```

**Supertitle** — names the panel context, not the story:
```python
{"fontSize": "9.5px", "fontWeight": "700", "color": _INDIGO,
 "textTransform": "uppercase", "letterSpacing": "0.6px"}
```

**Title** — the item name, full text (no truncation):
```python
{"fontSize": "14px", "fontWeight": "700", "color": _FG,
 "marginTop": "4px", "lineHeight": "1.4"}
```

**Subtitle** — ID and key person, monospace:
```python
{"fontSize": "11px", "color": _MT, "marginTop": "3px", "fontFamily": _MONO}
```

**Close button** — top-right, no background:
```python
{"background": "none", "border": "none", "color": _DIM,
 "fontSize": "20px", "cursor": "pointer", "padding": "0 0 0 12px", "lineHeight": "1"}
```

**Header wrapper:**
```python
{"display": "flex", "alignItems": "flex-start",
 "padding": "18px 20px 14px", "borderBottom": f"1px solid {_BD}"}
```

---

## Body Wrapper

```python
{"padding": "18px 20px 28px"}
```

All field sections live inside this wrapper. No additional container nesting.

---

## Field Labels

Used above every input, dropdown, or control group:

```python
def _lbl(t):
    return html.Div(t, style={
        "fontSize": "9.5px", "fontWeight": "700", "color": _DIM,
        "textTransform": "uppercase", "letterSpacing": "0.5px",
        "marginBottom": "5px",
    })
```

---

## Section Headers

Used to separate logical groups within the body (e.g. "Stages", "ADO Settings"):

```python
def _sec(label):
    return html.Div(label, style={
        "fontSize": "9.5px", "fontWeight": "700", "color": _DIM,
        "textTransform": "uppercase", "letterSpacing": "0.6px",
        "marginBottom": "8px", "marginTop": "14px",
    })
```

Both `_lbl` and `_sec` use the same `_DIM` color and uppercase treatment — the difference
is `_sec` has `marginTop: 14px` to create visual breathing room between groups.

---

## Text Inputs

```python
_inp_style = {
    "width": "100%", "padding": "8px 10px",
    "background": _BG_HEAD, "border": f"1px solid {_BD}",
    "borderRadius": "7px", "color": _FG,
    "fontSize": "12.5px", "boxSizing": "border-box",
}
```

Date inputs use a narrower fixed width and monospace font:
```python
{
    "width": "122px", "padding": "5px 6px",
    "background": _BG_HEAD, "border": f"1px solid {_BD}",
    "color": _FG, "borderRadius": "6px",
    "fontSize": "11px", "fontFamily": _MONO,
}
```

All date inputs are `type="text"` with `placeholder="YYYY-MM-DD"`.
`dcc.Input(type="date")` is not supported in Dash 4.

---

## Dropdowns

```python
dcc.Dropdown(style={"fontSize": "12.5px"})
```

Background, border, and text colors are inherited from the Dash component theme.
Do not override container styles — only set `fontSize`.

---

## Toggle / Pill Buttons

Used for mutually exclusive options (Story Size, QA assignee, etc.):

```python
def _tog(label, btn_id, active, color=_INDIGO):
    r = _rgb(color)   # extract "R,G,B" from "rgb(R,G,B)"
    return html.Button(label, id=btn_id, n_clicks=0, style={
        "padding": "6px 12px", "borderRadius": "7px", "cursor": "pointer",
        "fontSize": "12px", "fontWeight": "600",
        "background": f"rgba({r},0.133)" if active else "transparent",
        "border":     f"1px solid rgba({r},0.5)" if active else f"1px solid {_BD}",
        "color":       color if active else _MT,
    })
```

- Active state: tinted background + matching border at 50% opacity.
- Inactive: transparent background, `_BD` border, `_MT` text.

---

## Status Circle Buttons

Used in stage/gate rows to set Done / WIP / Not Started / N/A:

```python
def _sbtn(val, color):
    active = current_status == val
    r = _rgb(color)
    icon = "—" if val == "n_a" else "✓"
    return html.Button(icon if active else "", style={
        "width": "22px", "height": "22px", "borderRadius": "50%",
        "cursor": "pointer", "padding": "0",
        "background": color if active else "transparent",
        "border": f"2px solid {color}" if active else f"2px solid rgba({r},0.4)",
        "display": "flex", "alignItems": "center", "justifyContent": "center",
        "color": _BG_PAGE,   # icon color — dark so it reads on colored bg
        "fontSize": "11px", "fontWeight": "800", "lineHeight": "1",
    })
```

Status colors:
| Status | Color |
|---|---|
| Done | `rgb(70,194,142)` — green |
| WIP | `rgb(224,162,60)` — amber |
| Not Started | `rgb(239,110,99)` — red |
| N/A | `rgb(148,163,184)` — grey |

Clicking the active status again deselects it (toggle off = not started).

---

## Stage / Gate Rows

The core repeating unit — label + status circles + date input:

```python
html.Div([
    html.Span(label, style={
        "flex": "1", "fontSize": "12px", "color": _FG, "lineHeight": "1.3",
    }),
    html.Div([_sbtn("done", _GREEN), _sbtn("wip", _AMBER),
              _sbtn("not_started", _RED), _sbtn("n_a", _NA_COLOR)],
             style={"display": "flex", "gap": "5px"}),
    dcc.Input(type="text", placeholder="YYYY-MM-DD", debounce=True,
              style={"width": "122px", "padding": "5px 6px",
                     "background": _BG_HEAD, "border": f"1px solid {_BD}",
                     "color": _FG, "borderRadius": "6px",
                     "fontSize": "11px", "fontFamily": _MONO}),
], style={
    "display": "flex", "alignItems": "center", "gap": "7px",
    "padding": "6px 8px", "borderRadius": "7px",
    "border": f"1px solid {_BD_CELL}",    # lighter than main _BD
    "marginBottom": "4px",
})
```

Section header above rows:
```python
html.Div([
    html.Span("Stages · set status & date", style={
        "fontSize": "10px", "fontWeight": "700", "color": _DIM,
        "textTransform": "uppercase", "letterSpacing": "0.5px",
    }),
    # legend: small circles + labels for Done / WIP / Not Started
], style={"display": "flex", "justifyContent": "space-between",
          "alignItems": "center", "marginBottom": "9px"})
```

---

## Save to ADO Button

Full-width primary action, indigo tint:

```python
html.Button("Save to ADO", style={
    "width": "100%", "padding": "9px", "borderRadius": "8px",
    "background": "rgba(110,118,241,0.133)",
    "border": "1px solid rgba(110,118,241,0.5)",
    "color": _INDIGO, "cursor": "pointer",
    "fontSize": "12px", "fontWeight": "700",
    "marginBottom": "4px",
})
```

All ADO writes are **batched** — collected in state and sent on this button click.
Never write to ADO on individual field change events.

---

## Danger Button

```python
html.Button("Delete …", style={
    "width": "100%", "padding": "9px", "borderRadius": "8px",
    "background": "transparent", "border": f"1px solid {_RED}",
    "color": _RED, "cursor": "pointer",
    "fontSize": "12px", "fontWeight": "600",
})
```

---

## Secondary Button

Ghost style, for lower-priority actions (Save comment, Cancel, etc.):

```python
html.Button("Save comment", style={
    "marginTop": "7px", "padding": "5px 13px", "borderRadius": "7px",
    "background": "transparent", "border": f"1px solid {_BD}",
    "color": _DIM, "cursor": "pointer", "fontSize": "11px",
})
```

---

## Divider

Used between major sections inside the body:

```python
html.Div(style={"borderTop": f"1px solid {_BD_CELL}", "margin": "13px 0 10px"})
```

Note: uses `_BD_CELL` (lighter), not `_BD`, so it doesn't compete with the panel border.

---

## Badge / Chip

Inline tags for priority, release, type, etc.:

```python
# Priority P1
{"background": "rgba(239,68,68,0.15)", "color": "rgb(239,68,68)",
 "border": "1px solid rgba(239,68,68,0.35)",
 "borderRadius": "4px", "padding": "1px 6px",
 "fontSize": "10px", "fontWeight": "600", "whiteSpace": "nowrap"}

# Release / cyan
{"background": "rgba(6,182,212,0.10)", "color": "rgb(6,182,212)",
 "border": "1px solid rgba(6,182,212,0.25)",
 "borderRadius": "4px", "padding": "1px 6px",
 "fontSize": "10px", "fontWeight": "600", "whiteSpace": "nowrap"}
```

Pattern: `rgba(R,G,B, 0.10–0.15)` fill, `rgba(R,G,B, 0.25–0.35)` border, full-opacity text.

---

## Two-Column Field Row

Standard layout for pairing two fields side by side:

```python
html.Div([
    html.Div([_lbl("Field A"), control_a], style={"flex": "1", "minWidth": "0"}),
    html.Div([_lbl("Field B"), control_b], style={"flex": "1", "minWidth": "0"}),
], style={"display": "flex", "gap": "10px", "marginBottom": "14px"})
```

`minWidth: 0` prevents flex children from overflowing.
`gap: 10px`, `marginBottom: 14px` is the standard field row spacing.

---

## Spacing Rhythm

| Context | Value |
|---|---|
| Header padding | `18px 20px 14px` |
| Body padding | `18px 20px 28px` |
| Between field rows | `marginBottom: 14px` |
| Between stage rows | `marginBottom: 4px` |
| Section divider margin | `13px 0 10px` |
| Gap between two-col fields | `10px` |
| Gap between toggle pills | `6px` |
| Gap between status circles | `5px` |
| Gap inside stage row | `7px` |

---

## Layout Order (standard panel)

```
[Header: supertitle + title + subtitle + badges + close ✕]
─────────────────────────────────────────────────── (_BD)
[Body]
  Field group A (e.g. Owner + Developer — 2 col)
  Field group B (e.g. QA / full width)
  Field group C (e.g. Size — toggles)
  Field group D (e.g. Status + Release — 2 col)

  [Save to ADO button]

  ─── divider (_BD_CELL)

  SECTION HEADER + legend
  [Row 1: label | circles | date]
  [Row 2: label | circles | date]
  …

  ─── divider (_BD_CELL)

  [Comment textarea]
  [Secondary button]
  [Danger button]
```

Fields that write to the local DB may save on-change (debounced).
Fields that write to ADO must be batched behind the **Save to ADO** button.
