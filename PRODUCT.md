# Product

<!-- impeccable:product-schema 1 -->

> Inferred from the original plumb build brief (19 Sep 2026). Labeled because the init interview was not run; the user asked to proceed and design the UI.

## Platform

web

## Users

Analysts and operators who have a spreadsheet (CSV, TSV, XLSX) and a question in English. They sit at a laptop, usually around 1280px, and need an answer they can verify before they trust it.

## Product Purpose

plumb answers natural-language questions about a loaded spreadsheet, shows the SQL it ran, and asks for a definition instead of guessing. Success is a correct, checkable route: answer, clarify, or refuse.

## Positioning

Three explicit routes. Clarify is a feature, not an error. Generated SQL is parsed and guarded; a DuckDB read-only connection is not trusted. Tagline: *answers you can check.*

## Operating Context

Upload a sheet, inspect the inferred schema, ask in the composer, read a card. Audit log is a slide-over. Sessions are in-memory, two hours idle.

## Capabilities and Constraints

- Routes: answer (narration, table, optional chart, Show SQL), clarify (options + free text), refuse (reason, no red).
- Stack for this phase: FastAPI, Vite, React, TypeScript, Tailwind, react-vega. No component library, no router, no state library.
- Must look correct at 1280px with no horizontal overflow. Left schema ~280px, main conversation.
- Do not invent commercial claims, customers, or metrics the engine does not produce.

## Brand Commitments

- Name: plumb
- Tagline: answers you can check
- Voice: specific, shipped, no hype words
- Clarify card is the memorable surface: a recorder-red method plate with white option tickets, not an error. (The original brief's left accent was replaced in the Sep 2026 visual world.)

## Evidence on Hand

- Fixtures: `fixtures/employees.csv`, `fixtures/departments.csv`,
  `fixtures/northwind_hr_analytics.xlsx` (8 sheets, 11,806 rows)
- Eval: 23/28 (82%) on 19 Sep 2026 (`evals/results.md`)
- Red team: three Criticals found and closed, 19 Sep 2026 (`qa/RED-TEAM.md`)
- No logo, photography, or customer quotes. Do not fabricate them.

## Product Principles

- Show the work (SQL) next to the claim.
- Prefer a named definition over a confident guess.
- Refuse honestly when the columns cannot support the question.
- The schema panel is how the user confirms the file was understood.

## Accessibility & Inclusion

Keyboard operable, visible focus, 4.5:1 body contrast, `prefers-reduced-motion` respected. No product-specific WCAG mandate was recorded.
