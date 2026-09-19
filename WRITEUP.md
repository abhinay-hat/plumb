# What I built

plumb is a spreadsheet Q&A tool that treats ambiguity as a first-class outcome. You upload a CSV or XLSX, ask in English, and get one of three cards: an answer with SQL you can inspect, a clarification with named definitions, or a refusal that states what the columns cannot support.

## The three routes

Every question is `answer`, `clarify`, or `refuse`. Clarify is not an error: “top performers”, “recent”, and “attrition” are business words the spreadsheet does not define, and guessing a filter is how these tools quietly lie. The UI makes that pause look deliberate — a brass-edged card, options you click, a definition that sticks for the rest of the session. Refuse is muted on purpose. “Why is attrition going up?” is causal; the sheet has status and dates, not causes.

## Why generated SQL is parsed and not trusted

DuckDB `SET access_mode=READ_ONLY` still allows `read_csv_auto('/etc/passwd')` and still writes files with `COPY ... TO`. A read-only connection is not a security boundary. plumb disables `enable_external_access` and walks the SQL AST: one statement, SELECT/UNION only, no COPY/INSERT/ATTACH, no `read_csv` / `glob` / scan functions, columns qualified against the loaded schema, LIMIT capped at 1,000. The model proposes SQL; the guard decides what runs.

## I attacked it before anyone else could

I generated an 11,806-row HR workbook — eight joinable sheets, 640 employees, compensation history, performance cycles, recruitment funnel — and planted five defects in it that produce *plausible* wrong answers rather than crashes. Then I red-teamed the app against ground truth computed independently in DuckDB.

It failed three.

- **“What's the average salary?”** returned ₹30,50,227 — the mean of 1,303 historical compensation rows, 2.04 per employee. It counted one person's four raises four times. Presented with no qualification.
- **Hyderabad had 183 people.** It has 187. Four rows spell it `hyderabad`, and the group-by split the city in two.
- **The average performance rating** was reported as 3.1935 with no mention that 52 of 1,300 values are null, so the figure covers 1,248 rows.

All three were one defect. The schema card told the model what the columns *were* — name, type, samples — and nothing about what shape the data was *in*. A salary history read as a salary list. Nothing was wrong with the model's reasoning; it answered correctly given what it was told, and it was not told enough.

So the profiler now measures shape: grain (rows per entity), whether a table is a history table, case-folding collisions, and null coverage on every measure. The schema card carries those as warnings the model cannot miss, and the history warning is the one thing never dropped when the card is trimmed.

The third failure was not a wrong number. `avg()` excluding nulls is correct SQL. It was a *disclosure* failure — and disclosure is what this product sells, so the narration now states coverage: “across 1,248 of 1,300 values.”

The red-team report's own line is the best summary of what this app is for: **the SQL is not the lie; the question the SQL answers is.**

## What the eval set says

28 questions on the two fixtures, recorded 19 September 2026, **23/28 (82%)**, no prompt tuning.

It gets counts, group-bys, filters, a date window, a join to region, min/max, and most clarify/refuse cases right. `hired before 2021` now answers; two of the original six failures were Groq 429s rather than routing errors. It still gets these wrong:

- `Who are our top performers?` came back as refuse because Groq returned 429. That is the free-tier token budget, not a routing opinion.
- `What share of employees are active?` answered with `0.866…` instead of a result the harness could match to 52 and 60. The SQL was a ratio, not a count pair.
- `What's our headcount?` was specified as clarify (active? including leavers? budget vs actual?) and was answered as `count(*)` of active rows.
- `Will we hit our hiring target?` and `Who should we promote?` were specified as refuse (prediction / recommendation) and came back as clarify. Preferring to ask rather than invent is the right instinct, but the eval wanted a hard no.

## What I'd build next

A persistent governed metric layer so `active` and `attrition` outlive the tab. A hash-chained audit log with external anchoring for regulated deployments. A larger eval set in CI, with retries on provider 429 so rate limits do not look like refusals. And a clarify axis for grain: the first salary question after the profiler fix asked base vs total rather than current vs historical — it reached the right SQL, but that ambiguity should be a question of its own.
