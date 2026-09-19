---
name: plumb
description: answers you can check
colors:
  paper: "#d5e2e6"
  chassis: "#eef4f5"
  channel: "#9eb3b8"
  ink: "#152028"
  muted: "#2c3a40"
  panel: "#e4eef0"
  line: "#9bb0b6"
  grid: "#b8cbd0"
  answer: "#1a5c68"
  clarify: "#b13224"
  ticket: "#f4f8f9"
  refuse: "#5a6a70"
typography:
  display:
    fontFamily: "Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.03em"
  body:
    fontFamily: "Schibsted Grotesk, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Red Hat Mono, ui-monospace, monospace"
    fontSize: "10px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "0.14em"
  data:
    fontFamily: "Red Hat Mono, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  none: "0px"
spacing:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ticket}"
    rounded: "{rounded.none}"
    padding: "8px 16px"
  button-primary-hover:
    backgroundColor: "{colors.answer}"
    textColor: "{colors.ticket}"
  button-primary-disabled:
    backgroundColor: "{colors.line}"
    textColor: "{colors.muted}"
  ticket:
    backgroundColor: "{colors.ticket}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "10px 12px"
  method-plate:
    backgroundColor: "{colors.clarify}"
    textColor: "{colors.ticket}"
    rounded: "{rounded.none}"
    padding: "8px 16px"
  composer-input:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "6px 0"
---

# Design System: plumb

## Overview

**Creative North Star: "The Chart Recorder"**

plumb is an Operate surface that looks like a lab chart-recorder printout sitting on a desk under fluorescent light. The user loads a spreadsheet on the metal chassis at left, then reads answers as stamped printouts on cyan grid paper. Three routes are instrument stamps — ANSWER, METHOD, OUT OF RANGE — not chat bubbles and not error toasts.

The world refuses cream-and-serif data-tool defaults, near-black neon AI chrome, and a 4px tinted left border as the whole identity of clarify. Color strategy is Restrained-to-Committed: neutrals carry the task; the clarify plate is the one region that owns a saturated field.

**Key Characteristics:**

- Cyan chart paper with a 24px measurement grid
- Square-cut plates, 1px hairline borders, no drop shadows
- Schibsted Grotesk for UI; Red Hat Mono for stamps, schema, SQL, and table cells
- Clarify is a recorder-red method plate with white tickets

## Colors

Chart-recorder paper and carbon ink, with a recorder-pen red reserved for METHOD.

### Primary

- **Recorder red** (`#b13224`): the METHOD plate only — the whole card, not an accent stripe. White tickets sit on it.
- **Pen blue** (`#1a5c68`): ANSWER stamp, RUN label, primary hover.

### Neutral

- **Chart paper** (`#d5e2e6`): main log surface; holds the 24px grid (`#b8cbd0`).
- **Chassis** (`#eef4f5`): sidebar and title block, cooler than the paper.
- **Cut channel** (`#9eb3b8`): 8px gap between chassis and paper (desktop).
- **Carbon ink** (`#152028`): headings, body, primary buttons.
- **Muted carbon** (`#2c3a40`): secondary copy; ≥4.5:1 on paper and chassis.
- **Ticket** (`#f4f8f9`): printout cards, option tickets, table ground.
- **Panel** (`#e4eef0`): alternating table rows, SQL annotation strip.
- **Line** (`#9bb0b6`): hairline borders.
- **Out of range** (`#5a6a70`): refuse stamp and reason; never red.

Selection highlight is `#c9dde1`. Focus ring and caret are recorder red. SQL lives as carbon on panel, not a dark terminal.

## Typography

One grotesque for the product, one mono for measurement.

- **Display / body:** Schibsted Grotesk. Empty-state heading 34px / 600 / -0.03em. Narration 16px. Option tickets 13px. Fixed rem scale, not fluid.
- **Stamps / schema / SQL / tables:** Red Hat Mono. Stamps are 10px, 500, 0.14em, uppercase. Table cells 12px tabular-nums. SQL 12px, wrap, carbon on panel.

Do not introduce a display serif. Do not costume the whole UI in mono.

## Layout

Desktop (~1280px): 272px chassis | 8px channel | fluid chart-bed. Composer pinned to the bottom as the RUN line. Log is a single column, max-width 48rem, on the grid.

`max-lg`: chassis stacks on top (max 30vh, scroll), then title block, log, composer. Composer is `shrink-0` so it never clips.

Spacing follows the 24px grid: 8 / 12 / 16 / 24. More space above a heading than below it.

## Elevation & Depth

Flat. Depth is cut faces and paper layers, not shadows. The channel is a physical gap. Cards are ticket stock on the grid, 1px line, 0 radius. The closed audit drawer translates in from the right; the scrim is ink at 25%.

## Shapes

Square-cut. Radius is 0 everywhere. No pills except nothing — even small controls are rectangular. Hairline 1px borders. The chart-bed grid is the measurement canvas, not decoration.

## Components

### Buttons

Square ink plates. Primary: ink fill, ticket text, 11px mono uppercase. Hover: pen blue. Disabled: line fill, muted text. METHOD tickets: ticket fill on the red plate, ink text, hover border ticket.

### Cards / printouts

- **Answer:** ticket stock, ANSWER stamp in pen blue, narration, grid table, optional chart, collapsed Show SQL as a pinned annotation.
- **Method:** full recorder-red field, white tickets, free-text on the red field with a ticket-colored caret.
- **Out of range:** panel fill, refuse stamp, muted reason. No red.
- **Recording:** ticket stock plus the one authored motion — a 2px red pen trace drawing left to right (`cubic-bezier(0.16, 1, 0.3, 1)`, 1.8s). Static under `prefers-reduced-motion`.

### Inputs

Composer: transparent field, bottom hairline, 15px grotesque, red caret. Placeholder "Ask this sheet". RUN is a channel label, Ask is the action.

### Schema

Packed hairline modules. Table name + row count as the control; columns list name, dtype, samples. No "Schema" kicker.

### Audit

Chassis drawer, 360px, chart-bed scroll, newest first.

## Do's and Don'ts

### Do:

- **Do** treat clarify as a feature: the red method plate is the memorable surface.
- **Do** keep SQL collapsed behind "Show SQL" and style it as an annotation, not a terminal.
- **Do** put schema on the chassis so the user can confirm the file before asking.
- **Do** use the 24px grid only on the chart-bed (the actual measuring surface).

### Don't:

- **Don't** use a colored `border-left` on cards; METHOD owns a field, not a stripe.
- **Don't** use cream + serif, or near-black + neon, as the page identity.
- **Don't** put kickers (eyebrow labels) above headings.
- **Don't** round corners past 0px or add drop shadows on printouts.
- **Don't** color refuse red.
