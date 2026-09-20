# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What plumb is

Ask a spreadsheet a question in English. plumb answers with the SQL it ran, asks what an
ambiguous business term means, or says the columns cannot support the question. It never
guesses. `README.md` states the user-facing contract, `DESIGN.md` the engineering
rationale, `PRODUCT.md` the product framing.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make setup         # git config core.hooksPath .githooks — once per clone
make build          # frontend/dist — the API serves this as the SPA at :8000
make dev            # uvicorn :8000 + vite :5173 concurrently
make test           # pytest -q
make demo           # five questions through pipeline.ask against fixtures/ (needs an LLM)
make eval           # evals/run.py — writes evals/results.md (needs an LLM)

.venv/bin/pytest tests/test_guard.py::test_name -q     # single test
npm --prefix frontend run lint                          # oxlint
npm --prefix frontend run build                         # tsc -b && vite build
```

`PYTHON ?= .venv/bin/python` in the Makefile — every target uses the venv interpreter, not
whatever is on PATH. Vite proxies `/api` to `127.0.0.1:8000`, so use `:5173` during dev
and `:8000` for the built SPA.

## LLM providers

`backend/llm.py` is the only network call. `PLUMB_PROVIDER` is `groq` (default, needs
`GROQ_API_KEY`), `openrouter` (`OPENROUTER_API_KEY`), `ollama` (`http://localhost:11434`,
no key), or `custom` (any OpenAI-compatible `/v1/chat/completions` URL). `PLUMB_MODEL`
overrides the per-provider default. Groq withdrew `llama-3.3-70b-versatile` from the
free plan on 16 August 2026; Docker Compose and `.env` pin `openai/gpt-oss-20b`.

The picker roster is **discovered, not declared**. `providers.models_for` asks each
provider's own `/v1/models` (5-minute cache, 4s timeout) and filters on fields the
payload publishes — text output, a JSON capability, and on OpenRouter a zero price.
`FALLBACK_MODELS` is what shows when discovery cannot run; it is not a curated list, so
do not "update" it when a provider changes its line-up. `PLUMB_LIVE_MODELS=0` disables
discovery, which `tests/conftest.py` sets for the whole suite so `make test` stays off
the network.

`backend/router.py` decides *which* free model answers. `PLUMB_PROVIDER=auto` (or any
pin, since failover stays on unless `PLUMB_ROUTE=0`) pools every provider whose key is
present. A 429 marks that candidate as cooling — using the provider's own `Retry-After`
— and the turn moves to the next one instead of failing; `_complete_once(...,
wait_on_limit=False)` is what stops it sleeping on a queue while an idle provider waits.
Ranking is learned: cooldown, consecutive failures, advertised JSON support,
EWMA latency, context length. No model is ranked by name. The winner stays bound so
`current_model()` reports who actually answered.

A user-supplied custom URL is untrusted input. `backend/endpoint_guard.py` validates
it the same way `guard.py` validates SQL: scheme, resolved address, pinned IP, no
redirects, port allowlist. Custom keys live on the session, not in `os.environ`.

`make test` does **not** hit an LLM — tests cover the deterministic modules (guard,
catalog, chart, narration verification, session store, HTTP surface). Anything touching
`planner.plan` or `narrate.narrate` needs a live provider, which is why the routing
quality number lives in `make eval`, not in pytest.

## Architecture

The engine is `backend/pipeline.py`. Everything else is either upstream of it (catalog),
called by it (planner, guard, narrate, chart), or a wrapper around it (`app.py`, `demo.py`,
`evals/run.py`). **FastAPI and React never decide a route** — if you find routing logic
creeping into `app.py` or the frontend, it belongs in the pipeline.

`pipeline.ask(question, session)` in order:

1. `planner.plan` → a `Plan` with `route ∈ {answer, clarify, refuse}`. The system prompt
   in `planner.py` *is* the routing policy — edit it there, nowhere else. The planner
   guard-checks its own SQL and makes exactly **one repair attempt** (feeding the
   `GuardError` message back to the model) before falling back to `refuse`.
2. clarify/refuse short-circuit; answer continues.
3. `guard.validate` runs again in the pipeline and returns *rewritten* SQL.
4. `narrate.narrate`, then `narrate.verify_narration` — any number in the narration not
   present in the result cells (or equal to the row count) makes the whole narration get
   discarded and replaced with `"N rows returned."`.
5. `chart.build_spec` assembles the Vega-Lite spec **in Python** from the plan's chart type
   and column names. A model-authored spec is never used: Vega-Lite renders an invalid spec
   as a blank chart instead of throwing, so errors would be silent.
6. `chart.recommend` reads the *result rows* — row count, distinct categories, dtype per
   axis, sign, share spread — and ranks every chart kind by a score computed from those
   measurements. No kind sits behind a hand-picked threshold; `MIN_ROWS`/`MAX_ROWS` are the
   renderer's limits, not taste. The winner, its reason, and same-class alternatives ship as
   `AskResponse.chart_advice`, alongside `rendered` (what was actually drawn) — so "you got
   a pie, a bar reads better here" is sayable. `unsupported` names a shape plumb cannot
   draw (candlestick) rather than silently omitting a chart.
7. `suggestions.follow_ups` builds next questions from the columns this answer returned,
   same rule as `suggest_questions`: every line names a real column, and the list comes back
   short rather than padded. `_is_measure` keeps ids out of "average X" by cardinality ratio
   and `catalog.foreign_key_columns`, never by name suffix.

### guard.py is the security boundary

A DuckDB read-only connection is not one — it still allows `read_csv_auto('/etc/passwd')`
and `COPY ... TO`. Three layers do the real work: `safe_connection` sets
`enable_external_access=false` right after load; `FORBIDDEN_NODES` / `FORBIDDEN_FUNCTIONS`
are walked over the sqlglot AST before *and* after qualification; `qualify(...,
validate_qualify_columns=True)` rejects unknown tables and columns. `validate` also caps
rows (default 1000). Nothing reaches DuckDB except `validate`'s return value.

`guard.match_column` exists because `qualify` lowercases identifiers (`"Order Date"` →
`"order date"`) and DuckDB compares them case-insensitively. Every lookup of a result
column must go through it or charts break silently.

### catalog.py

`ingest_many(paths, prefix)` → `(connection, list[TableInfo])`. Column identifiers are
derived deterministically from original headers by `clean_names`, so no header→identifier
map is carried anywhere — re-derive with `catalog.identifiers(table)`. `ColumnInfo.name`
keeps the *original* header. Typing is heuristic: mixed columns become VARCHAR, dates
convert only above a 0.9 parse rate; foreign keys are inferred by 0.8 value containment.
`render_schema` caps the schema card at ~10k chars to bound planner prompt size.

### State

`pipeline.Session` holds the DuckDB connection, tables, settled `definitions` (a chosen
clarify option, so later turns stop asking), and `history` (last 3 turns fed back to the
planner). `backend/session.py` keys these by uuid in memory with a per-session lock and a
2-hour idle eviction — there is no persistence, and a page refresh loses the spreadsheet.
`backend/audit.py` appends one JSONL line per turn to `audit/<session_id>.jsonl`; that is
the only durable record.

### Frontend

`frontend/src/App.tsx` is the state machine; each route gets its own card component
(`AnswerCard`, `ClarifyCard`, `RefuseCard`). `types.ts` mirrors `backend/models.py` —
changing `AskResponse` means changing both. Picking a clarify option calls
`/api/session/{id}/settle`, which writes into `session.definitions`.

## Conventions

- Module docstrings carry the *why* (see `guard.py`, `chart.py`, `catalog.py`). Keep that
  habit; the non-obvious reasoning is what makes the code readable.
- `from __future__ import annotations` at the top of every backend module.
- Errors are typed and carry a code: `GuardError(code, message)`, `AppError(code, message,
  status)`, `LLMError`, `ApiRequestError` on the frontend. HTTP errors always serialize as
  `{"code", "message"}`.
- `evals/questions.yaml` is a held-out set — `evals/run.py` says "do not tune prompts
  first". If you change the planner prompt, re-run `make eval` and record the honest number
  in `evals/results.md` and `README.md`.
- **No agent attribution in commits.** `.githooks/commit-msg` strips `Co-authored-by:` and
  `Claude-Session:` trailers. GitHub writes those into a contributor-index row that a
  history rewrite does *not* retract — the repo had to be deleted and recreated twice to
  clear `cursoragent` from the sidebar. `core.hooksPath` is local config, so a fresh clone
  needs `make setup` once before the hook does anything.

## Not committed

`.env` holds a live `GROQ_API_KEY` and is in `.gitignore`. Don't move secrets into tracked
files or example configs.
