---
title: plumb
emoji: 🔧
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
short_description: Ask a spreadsheet a question. See the SQL it ran.
---

# plumb

Answers you can check.

Ask a spreadsheet a question in English. plumb shows the SQL it ran, or it asks what a term means, or it says the columns cannot support the question. It does not guess.

## Run

```bash
export GROQ_API_KEY=gsk_...
docker compose up --build
```

Then open http://localhost:8000, drop `fixtures/employees.csv`, and ask.

Locally, without Docker:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make setup
make build
make dev
```

`make setup` points git at `.githooks/` — once per clone.

`make dev` starts the API on :8000 and Vite on :5173.

## Eval

Honest run, **20 September 2026**, against `evals/questions.yaml` (30 questions, both fixtures, `openai/gpt-oss-20b` on Groq):

**27/30 (90%)**

Includes two dashboard routing cases; one dashboard question hit a provider error. The remaining misses are routing disagreements — see `evals/results.md`. Prompts were not tuned against this set before recording that number.

```bash
make eval
```

Groq withdrew `llama-3.3-70b-versatile` from the free plan on 16 August 2026 — the 404 was the model gone, not a broken key. The picker offers `openai/gpt-oss-20b` (8,000 TPM). A paid Groq key can still pin the 70B via `PLUMB_MODEL`.

## Red team

The app was adversarially tested against `fixtures/northwind_hr_analytics.xlsx` (11,806 rows, eight sheets) with planted defects that produce plausible wrong numbers rather than crashes. It failed three — a salary history averaged as a salary list, a case-split city, and an average that hid its nulls — all from one hole in the schema card. All three are closed. The report is `qa/RED-TEAM.md`.

## Tests

```bash
make test
```

No LLM required. The suite covers the deterministic modules — guard, catalog, chart, narration verification, session store, HTTP surface. Anything that routes or narrates needs a live provider, which is why the routing number lives in `make eval` and not here.

## Architecture

1. A spreadsheet is profiled into DuckDB and a schema card. The card carries grain, history-table warnings, case-folding collisions, and null coverage — not just names and types.
2. `planner.plan` returns one of five routes: answer, clarify, refuse, chat, or dashboard. Broad overview questions (`analyse this data`, `what is interesting here`) can return a dashboard — several panels, each with its own SQL, chart, and one-line finding, from a single planner call.
3. Generated SQL is parsed and rewritten; a read-only DuckDB connection is not trusted on its own.
4. Answers are narrated, then every number in the narration is checked against the rows. Years, ISO dates, and disclosed coverage figures are context, not invented claims.
5. Charts are model-authored Vega-Lite validated by `chart_guard`, with a Python fallback. Dashboard panels use compact specs sized for a grid cell.
6. FastAPI and the React UI wrap that seam. They do not decide the route.

## Switch to Ollama

```bash
export PLUMB_PROVIDER=ollama
export PLUMB_MODEL=qwen2.5-coder:7b-instruct   # optional; this is the default
```

Ollama must be listening on `http://localhost:11434`. No Groq key is required.

## Bring your own endpoint

Any OpenAI-compatible server works: vLLM, LM Studio, LiteLLM, an internal gateway.

```bash
export PLUMB_PROVIDER=custom
export PLUMB_CUSTOM_URL=http://localhost:11434/v1/chat/completions
export PLUMB_CUSTOM_MODEL=qwen2.5-coder:7b-instruct
# PLUMB_CUSTOM_KEY=          # optional
# PLUMB_ALLOW_PRIVATE_ENDPOINTS=1   # required for 10/8, 172.16/12, 192.168/16
```

The URL is untrusted input. plumb checks the scheme, resolves the host, pins that address, refuses redirects, and only allows ports 443, 80, 8000, 8080, 11434, and 1234 — the same discipline as the SQL guard. A key typed in the UI is held on the session, never in process-wide env, and never written to the audit log.

## Limitations

- Sessions live in memory and are dropped after two hours idle. Refresh the page and the spreadsheet is gone.
- Only `SELECT`. No writes, no multiple statements, no files outside the upload.
- Business definitions (`active`, `top performer`) last for one session. There is no metric layer.
- Routing is the model's. `headcount` is sometimes answered as `count(*)` instead of being clarified; some prediction questions come back as clarify instead of refuse.
- Spreadsheet typing is heuristic. Mixed columns become VARCHAR; dates convert only when >90% of values parse.
- No authentication. Anyone who can reach the process can query the loaded sheet.
- Groq's free token budget will turn a question into `refuse` if the planner call is rate-limited.
