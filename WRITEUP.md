# What I built

plumb is a spreadsheet Q&A tool that treats ambiguity as a first-class outcome. You upload a CSV or XLSX, ask in English, and get one of three cards: an answer with SQL you can inspect, a clarification with named definitions, or a refusal that states what the columns cannot support. The engine — catalog, guard, planner, narrate, chart, pipeline — already existed. This phase is the session store, JSONL audit log, FastAPI wrapper, React UI, eval harness, and the ship path.

## The three routes

Every question is `answer`, `clarify`, or `refuse`. Clarify is not an error: “top performers”, “recent”, and “attrition” are business words the spreadsheet does not define, and guessing a filter is how these tools quietly lie. The UI makes that pause look deliberate — a brass-edged card, options you click, a definition that sticks for the rest of the session. Refuse is muted on purpose. “Why is attrition going up?” is causal; the sheet has status and dates, not causes.

## Why generated SQL is parsed and not trusted

DuckDB `SET access_mode=READ_ONLY` still allows `read_csv_auto('/etc/passwd')` and still writes files with `COPY ... TO`. A read-only connection is not a security boundary. plumb disables `enable_external_access` and walks the SQL AST: one statement, SELECT/UNION only, no COPY/INSERT/ATTACH, no `read_csv` / `glob` / scan functions, columns qualified against the loaded schema, LIMIT capped at 1,000. The model proposes SQL; the guard decides what runs.

## What the eval set says

28 questions on the two fixtures, recorded 19 September 2026, **22/28 (79%)**, no prompt tuning.

It gets counts, group-bys, filters, a date window, a join to region, min/max, and most clarify/refuse cases right. It gets these wrong:

- Two questions (`hired before 2021`, `top performers`) came back as refuse because Groq returned 429. That is the free-tier token budget, not a routing opinion.
- `What share of employees are active?` answered with `0.866…` instead of a result the harness could match to 52 and 60. The SQL was a ratio, not a count pair.
- `What's our headcount?` was specified as clarify (active? including leavers? budget vs actual?) and was answered as `count(*)` of active rows.
- `Will we hit our hiring target?` and `Who should we promote?` were specified as refuse (prediction / recommendation) and came back as clarify. Preferring to ask rather than invent is the right instinct, but the eval wanted a hard no.

## What I'd build next

A persistent governed metric layer so `active` and `attrition` outlive the tab. A hash-chained audit log with external anchoring for regulated deployments. A larger eval set in CI, with retries on provider 429 so rate limits do not look like refusals.
