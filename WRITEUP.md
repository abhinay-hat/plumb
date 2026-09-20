# plumb — answers you can check

Upload one or more CSV/XLSX files, ask in English, get back the SQL that ran alongside the answer — or a question, or a refusal.

Live: **https://plumb.iamabhinay.com** · Local: `docker compose up --build`

## Approach: ambiguity is an outcome, not an error

Five routes — `answer`, `clarify`, `refuse`, `chat`, `dashboard`. "Top performers" and "attrition" are business words the spreadsheet does not define, and quietly guessing a filter is how these tools lie; clarify asks, and the chosen definition sticks for the session. "Why is attrition going up?" is causal, and the sheet holds status and dates, not causes — so it refuses. A broad question returns a dashboard: four panels, each with its own SQL, chart, and finding, from a **single** planner call, because free tiers allow 30 requests a minute and N panels cannot mean N calls.

## Key decision: the model proposes, Python decides

DuckDB's `access_mode=READ_ONLY` still allows `read_csv_auto('/etc/passwd')` and still writes files with `COPY ... TO`. A read-only connection is not a security boundary. plumb disables external access and walks the SQL AST: one statement, SELECT only, columns qualified against the loaded schema, rows capped.

The same rule covers charts. Vega-Lite renders an invalid spec as a **blank chart rather than throwing**, so a hallucinated field name fails silently. The model authors the full spec — histogram, box plot, whatever fits — and `chart_guard` validates every field against the actual result columns before it reaches the browser, with one repair attempt and a deterministic fallback. Chart type is not a hardcoded list.

## What red-teaming changed

I generated an 11,806-row HR workbook with planted defects that produce *plausible* wrong answers rather than crashes, and tested against ground truth computed independently.

It failed three. "What's the average salary?" returned the mean of 1,303 historical compensation rows — 2.04 per employee — counting one person's four raises four times. Hyderabad showed 183 people instead of 187, because four rows spell it `hyderabad`. An average was reported without mentioning that 52 of 1,300 values were null.

All three were one defect: the schema card said what the columns *were*, not what shape the data was *in*. The model reasoned correctly from what it was told, and it was not told enough. The profiler now measures grain, history shape, case collisions, and null coverage, and the narration states coverage — "across 1,248 of 1,300 values". `avg()` skipping nulls is correct SQL; not saying so is a disclosure failure, and disclosure is the product.

**The SQL is not the lie; the question the SQL answers is.**

## What real use taught me

Every bug found in use was a *seam* bug — two modules each correct alone, disagreeing where they meet. Display names were resolved per file, so two uploads both containing `employees` collapsed onto whichever loaded last. A join on `e.name` and `d.name` produced duplicate column keys, and the chart plotted one while the table beside it showed both.

220 passing single-module tests caught none of them. The answer was not more unit tests but invariants asserted across the whole pipeline: names are unique, every result column is addressable, what the advice claims and what the chart draws agree.

Separately: one provider is a single point of failure. Every configured free tier is now a candidate in a pool, a 429 marks it cooling using the provider's own `Retry-After`, and the turn moves on. The model roster is discovered from each provider's `/v1/models` — a hand-kept list is wrong the moment a model is retired, which is how `llama-3.3-70b-versatile` became a 404.

## Eval

30 questions, both fixtures, recorded 20 September 2026: **27/30 (90%)**, no prompt tuning against the set. The misses are routing disagreements, not wrong numbers — `What's our headcount?` was specified as clarify and answered as `count(*)`.

## What I'd build next

A governed metric layer so `active` outlives the tab. A hash-chained audit log for regulated deployments. Property-based tests over generated result shapes, which would have caught the duplicate-column bug before a user did. And a clarify axis for grain: "current salary, or salary history?" deserves to be its own question.
