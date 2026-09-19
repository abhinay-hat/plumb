# plumb red-team e2e

Deterministic Playwright suite for the five HR landmines and the guard/input attacks.
The Groq planner is **stubbed**. A 429 is a harness failure, not a product finding.

## What this tests

| File | Hits | LLM |
|---|---|---|
| `tests/landmines.spec.ts` | Compensation history mean, case-split locations, the missing seven, nulls in `avg()`, contested terms | Stubbed. Replays payloads captured from a live Groq run on 2026-09-19 against `fixtures/northwind_hr_analytics.xlsx`. |
| `tests/guard.spec.ts` | System-prompt leak and `read_csv_auto` in the question box (stubbed refusals). Foreign `session_id` and upload type checks hit the **real** API. | Stub for `/api/ask`. None for HTTP. |
| `tests/inputs.spec.ts` | Zero-byte csv, latin-1, path-traversal filename, `select` as a column name | None |
| `tests/flow.spec.ts` | Reload, second tab, composer disabled, Ask disabled in flight | Stubbed |

The landmine tests are characterization tests of **defects**. They assert the product currently presents the naive number. They fail if a pipeline-level check starts refusing or clarifying those questions *and* the stub is updated. Updating `helpers/captured.ts` is how you record a new live run.

## Prerequisites

```bash
# from repo root — API :8000 and Vite :5173
set -a && [ -f .env ] && source .env && set +a
make dev
```

The landmine tests mock `/api/*` in the browser, so they do not call Groq even if `make dev` is using a live key. `inputs.spec.ts` and the HTTP half of `guard.spec.ts` **do** hit `http://127.0.0.1:8000`.

## Run

```bash
cd qa/e2e
npm install
npx playwright test
```

Config uses system Chrome (`channel: "chrome"`). Do **not** run `npx playwright install chromium` on a tight disk.

```bash
PLUMB_E2E_BASE=http://localhost:5173 PLUMB_API=http://127.0.0.1:8000 npx playwright test
```

## Optional: stub the real planner (Ollama shape)

`llm.py` talks to `http://localhost:11434/api/chat` when `PLUMB_PROVIDER=ollama`. The live app uses Groq, so port 11434 is usually free.

```bash
# terminal 1
python qa/e2e/stub_ollama.py          # :11434

# terminal 2
PLUMB_PROVIDER=ollama PLUMB_MODEL=stub \
  .venv/bin/python -m uvicorn backend.app:app --port 8010

# then point Vite or Playwright at :8010 after `make build`
```

`stub_ollama.py` returns the same plans as `helpers/captured.ts` by matching the question text. Use this when you want DuckDB and `guard.validate` in the loop, still without Groq.

## Ground truth for assertions

See `qa/RED-TEAM.md`. The numbers the stubs replay:

- naive mean salary **3050227.168** (wrong)
- Hyderabad **183** plus hyderabad **4** (wrong; folded is 187)
- department null group **7**, total employees **640**
- `avg(performance_rating)` **3.1935** over 1,248 of 1,300 rows
