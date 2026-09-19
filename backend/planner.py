"""Route a question to answer / clarify / refuse, and produce validated SQL."""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from backend import guard, llm
from backend.models import Plan

log = logging.getLogger("plumb.planner")

SYSTEM_PROMPT = """You are a DuckDB SQL analyst. You are given a database schema and a question. Return JSON only, matching the given shape.

Choose one of four routes.

answer — the question maps unambiguously onto the schema. Write one read-only DuckDB SELECT using only the tables and columns given. Alias every aggregate (count(*) AS headcount). Never SELECT * on a table with more than 8 columns — name them. Use DuckDB syntax and functions.

clarify — the question is underspecified, or it uses a business term the schema does not define. Give one short clarify_question and 2-4 clarify_options, each phrased as a concrete definition naming real columns. Terms that require clarification include: top performers (by which measure, over what period), active (which column and value), recent (what window), attrition (leavers over average headcount, or over starting headcount), tenure (to today, or to termination).

When you clarify you MUST also set clarify_term: a short lowercase noun phrase naming the ambiguous term as it appears in the question — "headcount", "top performers", "average salary", "recent". Not a sentence, not a question.

If a definition has already been settled for a term in this question, you MUST use that definition and route to answer. Do not clarify the same term twice. The settled definitions are given to you; treat them as the user's own words.

refuse — the question cannot be answered from these columns at all: causal questions ("why is attrition up"), predictions, or data that is not present. State plainly in refuse_reason what is missing. Do not guess.

chat — the input is not a question about the data: a greeting, thanks, a question about what you are or what you can do, or small talk. Put a short, warm, useful reply in reply — one or two sentences. When the user seems to be orienting themselves, name two or three questions they could actually ask about the columns in this schema, using real table and column names. Never invent data in a chat reply, and never answer a data question through this route.

Chart: bar for a category against a measure, line for a time series, pie only for parts of a whole with fewer than 8 categories, scatter for two measures, none for a single value. chart_x and chart_y must be aliases the query actually returns.

Prefer clarify over a confident guess. A wrong confident answer is the worst outcome.

Return exactly this JSON shape, with unused fields set to null:
{
  "route": "answer" | "clarify" | "refuse" | "chat",
  "sql": string or null,
  "clarify_question": string or null,
  "clarify_options": [string] or null,
  "clarify_term": string or null,
  "refuse_reason": string or null,
  "reply": string or null,
  "chart": "bar" | "line" | "pie" | "scatter" | "none",
  "chart_x": string or null,
  "chart_y": [string] or null
}"""

_REPAIR_TEMPLATE = """The SQL you returned was rejected before execution.

SQL:
{sql}

Rejection: {error}

Return the same JSON shape again with corrected SQL that uses only the tables and columns in the schema. If the question cannot be answered from these columns, use the refuse route instead."""


_FORCE_ANSWER_NOTE = """You already asked about this term and the user has settled it. The definition above is final. Route to answer and write the SQL that applies it. Do not clarify again; if the definition still cannot be applied to these columns, refuse and say why."""

# Two turns, not three. History is pure prompt weight, and at a 8k-tokens-per-
# minute ceiling the third turn cost more than it ever resolved.
_HISTORY_TURNS = 2


def _build_user_message(
    question: str,
    schema_card: str,
    definitions: dict[str, str],
    history: list[dict],
    force_answer: bool = False,
) -> str:
    parts = [f"Schema:\n{schema_card}"]
    if definitions:
        settled = "\n".join(f"- {term}: {meaning}" for term, meaning in definitions.items())
        parts.append(f"Settled definitions (apply these, do not ask again):\n{settled}")
    if history:
        turns = []
        for turn in history[-_HISTORY_TURNS:]:
            turns.append(
                f"Q: {turn.get('question', '')}\n"
                f"route: {turn.get('route', '')}"
                + (f"\nsql: {turn['sql']}" if turn.get("sql") else "")
            )
        parts.append("Recent turns:\n" + "\n\n".join(turns))
    parts.append(f"Question: {question}")
    if force_answer:
        parts.append(_FORCE_ANSWER_NOTE)
    return "\n\n".join(parts)


def _parse_plan(raw: str) -> Plan:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {raw[:200]}")
    data = json.loads(text[start : end + 1])
    if isinstance(data.get("clarify_options"), str):
        data["clarify_options"] = [data["clarify_options"]]
    if isinstance(data.get("chart_y"), str):
        data["chart_y"] = [data["chart_y"]]
    if not data.get("chart"):
        data["chart"] = "none"
    if isinstance(data.get("clarify_term"), str) and not data["clarify_term"].strip():
        data["clarify_term"] = None
    return Plan.model_validate(data)


def _refuse(reason: str) -> Plan:
    return Plan(route="refuse", refuse_reason=reason)


def _repair_clarify_term(plan: Plan, question: str) -> Plan:
    """A clarify with no named term is unusable — the answer gets filed under a
    key nothing will ever match, and the next turn clarifies all over again.
    The prompt demands the field; when the model skips it anyway, fall back to
    the question itself, which is at least a key that matches on re-ask."""
    if plan.route != "clarify" or plan.clarify_term:
        return plan
    fallback = question.strip().rstrip("?").strip().lower()
    log.warning("clarify plan had no clarify_term; falling back to %r", fallback)
    plan.clarify_term = fallback or "definition"
    return plan


def plan(
    question: str,
    schema_card: str,
    definitions: dict[str, str],
    history: list[dict],
    schema: dict[str, dict[str, str]] | None = None,
    force_answer: bool = False,
) -> Plan:
    """Ask the model for a route. When `schema` is given, SQL is guard-checked
    here and one repair attempt is made before falling back to refuse.

    `RateLimitError` is deliberately not caught: a busy provider never told us
    anything about the data, so turning it into a refusal would be a lie.
    """
    user = _build_user_message(
        question, schema_card, definitions, history, force_answer=force_answer
    )
    try:
        raw = llm.complete(SYSTEM_PROMPT, user, json_mode=True)
        current = _parse_plan(raw)
    except llm.RateLimitError:
        raise
    except (llm.LLMError, ValueError, json.JSONDecodeError, ValidationError) as e:
        log.warning("planner attempt 1 unusable: %s", e)
        return _refuse(f"The model did not return a usable plan: {e}")

    if current.route == "answer" and not current.sql:
        return _refuse("The model chose to answer but returned no SQL.")
    if current.route == "chat" and not (current.reply or "").strip():
        return _refuse("The model chose to chat but returned no reply.")
    if current.route != "answer" or schema is None:
        return _repair_clarify_term(current, question)

    try:
        current.sql = guard.validate(current.sql, schema)
        return current
    except guard.GuardError as first:
        first_error = first.message
        log.warning("guard rejected attempt 1 (%s): %s", first.code, current.sql)

    repair = user + "\n\n" + _REPAIR_TEMPLATE.format(sql=current.sql, error=first_error)
    try:
        retry = _parse_plan(llm.complete(SYSTEM_PROMPT, repair, json_mode=True))
    except llm.RateLimitError:
        raise
    except (llm.LLMError, ValueError, json.JSONDecodeError, ValidationError) as e:
        log.warning("planner repair attempt unusable: %s", e)
        return _refuse(f"That query could not be run: {first_error}")

    if retry.route != "answer":
        return _repair_clarify_term(retry, question)
    if not retry.sql:
        return _refuse(f"That query could not be run: {first_error}")

    try:
        retry.sql = guard.validate(retry.sql, schema)
        return retry
    except guard.GuardError as second:
        log.warning("guard rejected repair attempt (%s): %s", second.code, retry.sql)
        return _refuse(f"That query could not be run: {second.message}")
