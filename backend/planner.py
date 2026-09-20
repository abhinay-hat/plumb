"""Route a question to answer / clarify / refuse, and produce validated SQL."""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from backend import catalog, dashboard, guard, llm
from backend.models import ChartAdvice, Panel, Plan

log = logging.getLogger("plumb.planner")

SYSTEM_PROMPT = """DuckDB SQL analyst. Given a schema and a question, return JSON only, unused fields null:
{"route":"answer"|"clarify"|"refuse"|"chat"|"dashboard","sql":str|null,"clarify_question":str|null,"clarify_options":[str]|null,"clarify_term":str|null,"refuse_reason":str|null,"reply":str|null,"chart":"bar"|"line"|"pie"|"scatter"|"none","chart_x":str|null,"chart_y":[str]|null,"chart_spec":str|null,"panels":[{"title":str,"sql":str,"chart_spec":str|null}]|null}

answer — maps unambiguously onto the schema. One read-only DuckDB SELECT, only the tables and columns given. Alias every aggregate (count(*) AS headcount). Never SELECT * on a table with more than 8 columns — name them.

clarify — underspecified, or uses a business term the schema does not define. One short clarify_question plus 2-4 clarify_options, each a concrete definition naming real columns. Terms needing clarification include: top performers (which measure, what period), active (which column and value), recent (what window), attrition (leavers over average or over starting headcount), tenure (to today or to termination).
Set clarify_term: a short lowercase noun phrase naming the ambiguous term as it appears in the question — "headcount", "top performers", "recent". Not a sentence.
If a definition has already been settled for a term in this question, you MUST use that definition and route to answer. Do not clarify the same term twice. Treat settled definitions as the user's own words.

refuse — cannot be answered from these columns at all: causal questions ("why is attrition up"), predictions, or data not present. State plainly in refuse_reason what is missing. Do not guess.

chat — not about the data: greeting, thanks, what you are or can do, small talk. Put a short warm reply in reply, one or two sentences. If the user is orienting themselves, name two or three questions they could ask about the columns in this schema, using real table and column names. Never invent data; never answer a data question here.

chart — bar for category against measure, line for a time series, pie only for parts of a whole under 8 categories, scatter for two measures, none for a single value. chart_x and chart_y must be aliases the query returns. When the user only asks to change the visualization ("as a bar chart", "chart this"), reuse the same SQL as the previous answer and set chart, chart_x, and chart_y from the query aliases.

chart_spec — when the answer has a visual shape, emit a complete Vega-Lite v5 spec as a JSON string in chart_spec with no data key (rows are injected server-side). Use whatever mark and transforms fit: bin for a histogram, boxplot for a distribution, rect for a heatmap, layered rule + bar for a candlestick. Every field must be a column name from the result of the SQL just written. Include value labels where they fit — a layered text mark. Emit chart_spec null when the result is a single number or has no numeric column. A chart recommendation from the result shape may appear in the user message as a hint, not a constraint — you may disagree and pick a histogram.

dashboard — route here when the question asks for an overview rather than one number: it names no single metric, or asks to analyse, summarise, explore, or what is interesting here. A question naming one measure or one filter stays on answer. Emit between 2 and {max_panels} panels in panels, each with title, one aggregated SELECT, and optionally chart_spec as a JSON string (no data key). Panels must cut the data in different ways — a count by the largest category, a measure by a grouping column, a trend over a date column when one exists, a distribution, a cross-file join when the schema supports one. Pick what this schema actually supports; do not force a trend onto a sheet with no dates. Every panel SQL must be independently valid; panels may not reference each other. Aggregate — a panel returning hundreds of raw rows is not an insight. Set sql, chart, and chart_spec null on the top level.

Prefer clarify over a confident guess. A wrong confident answer is the worst outcome."""

_REPAIR_TEMPLATE = """The SQL you returned was rejected before execution.

SQL:
{sql}

Rejection: {error}

Return the same JSON shape again with corrected SQL that uses only the tables and columns in the schema. If the question cannot be answered from these columns, use the refuse route instead."""

# The repair turn re-sends the question, not the whole schema card — the model
# has just seen it and the rejection names what was wrong. The exception is a
# rejection that is *about* the schema: an unknown table or column cannot be
# fixed without the column list in front of you.
_SCHEMA_DEPENDENT_ERRORS = ("unknown_table", "unknown_column")

_CHART_REPAIR_TEMPLATE = """The chart_spec you returned was rejected before rendering.

Rejection: {error}

Columns returned by the SQL: {columns}

Chart recommendation from the result shape (a hint, not a constraint): {advice}

Return the same JSON shape again with a corrected chart_spec that references only those columns, or set chart_spec to null if the result cannot be charted. No data key — rows are injected server-side."""


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
    if schema_card:
        parts = [f"Schema:\n{schema_card}"]
    else:
        parts = [
            "No spreadsheet loaded yet. Route greetings and what-you-can-do "
            "questions to chat. Route data questions to refuse and say a "
            "sheet must be uploaded first."
        ]
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
    # gpt-oss harmony output sometimes prefixes safety or analysis lines.
    if "{" not in text:
        raise ValueError(f"no JSON object in model output: {raw[:200]}")
    if not text.lstrip().startswith("{"):
        text = text[text.find("{") :]
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
    if data.get("chart_spec") == {}:
        data["chart_spec"] = None
    if isinstance(data.get("chart_spec"), str):
        text = data["chart_spec"].strip()
        data["chart_spec"] = json.loads(text) if text else None
    raw_panels = data.get("panels")
    if isinstance(raw_panels, list):
        parsed: list[Panel] = []
        for item in raw_panels:
            if not isinstance(item, dict):
                parsed.append(item)
                continue
            panel = dict(item)
            spec = panel.get("chart_spec")
            if isinstance(spec, str):
                panel["chart_spec"] = json.loads(spec) if spec.strip() else None
            parsed.append(Panel.model_validate(panel))
        data["panels"] = parsed
    return Plan.model_validate(data)


def _refuse(reason: str, guard_code: str | None = None) -> Plan:
    return Plan(route="refuse", refuse_reason=reason, guard_code=guard_code)


def _unreadable_plan_reason() -> str:
    return (
        "The model returned a response plumb could not read. "
        "Try again, rephrase the question, or pick a different model."
    )


def _system_prompt(max_panels: int) -> str:
    return SYSTEM_PROMPT.replace("{max_panels}", str(max_panels))


def _prepare_dashboard(plan: Plan) -> Plan:
    if not plan.panels:
        return _refuse("The model chose dashboard but returned no panels.")
    capped = plan.panels[: dashboard.panel_limit()]
    deduped = dashboard.dedupe_panels(capped)
    if len(deduped) < 2:
        return _refuse(
            "The dashboard needs at least two distinct panels, but the model "
            "returned fewer or duplicated the same query."
        )
    plan.panels = deduped
    plan.sql = None
    plan.chart_spec = None
    return plan


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


def _format_advice_hint(advice: ChartAdvice | None) -> str:
    if advice is None or advice.kind == "none":
        return "none — the result may not chart well"
    parts = [f"{advice.kind}: {advice.reason}"]
    if advice.alternatives:
        parts.append(f"alternatives: {', '.join(advice.alternatives)}")
    if advice.unsupported:
        parts.append(f"unsupported shape noted: {advice.unsupported}")
    return " ".join(parts)


def repair_chart_spec(
    question: str,
    plan: Plan,
    schema_card: str,
    definitions: dict[str, str],
    history: list[dict],
    columns: list[str],
    error: str,
    advice: ChartAdvice | None = None,
    schema: dict[str, dict[str, str]] | None = None,
    aliases: dict[str, str] | None = None,
) -> Plan:
    """One repair attempt when chart_guard rejects the model's Vega-Lite."""
    user = _build_user_message(question, schema_card, definitions, history)
    if advice is not None:
        user += f"\n\nChart recommendation (hint, not a constraint): {_format_advice_hint(advice)}"
    user += "\n\n" + _CHART_REPAIR_TEMPLATE.format(
        error=error,
        columns=", ".join(columns) or "(none)",
        advice=_format_advice_hint(advice),
    )
    try:
        repaired = _parse_plan(
            llm.complete(_system_prompt(dashboard.panel_limit()), user, json_mode=True)
        )
    except (llm.RateLimitError, llm.ProviderUnavailableError):
        raise
    except (llm.LLMError, ValueError, json.JSONDecodeError, ValidationError) as e:
        log.warning("chart_spec repair unusable: %s", e)
        plan.chart_spec = None
        return plan

    if repaired.route != "answer" or not repaired.sql:
        plan.chart_spec = None
        return plan

    if schema is not None:
        try:
            repaired.sql = guard.validate(
                catalog.restore_table_names(repaired.sql, aliases or {}), schema
            )
        except guard.GuardError as e:
            log.warning("chart_spec repair changed SQL and guard rejected it: %s", e)
            plan.chart_spec = None
            return plan

    return repaired


def plan(
    question: str,
    schema_card: str,
    definitions: dict[str, str],
    history: list[dict],
    schema: dict[str, dict[str, str]] | None = None,
    force_answer: bool = False,
    aliases: dict[str, str] | None = None,
    chart_advice_hint: ChartAdvice | None = None,
    question_hints: list[str] | None = None,
) -> Plan:
    """Ask the model for a route. When `schema` is given, SQL is guard-checked
    here and one repair attempt is made before falling back to refuse.

    `RateLimitError` and `ProviderUnavailableError` are deliberately not
    caught: a busy or vanished model never told us anything about the data,
    so turning either into a refusal would be a lie.
    """
    user = _build_user_message(
        question, schema_card, definitions, history, force_answer=force_answer
    )
    if chart_advice_hint is not None:
        user += (
            "\n\nChart recommendation from a prior result (hint, not a constraint): "
            + _format_advice_hint(chart_advice_hint)
        )
    if question_hints:
        lines = "\n".join(f"- {hint}" for hint in question_hints)
        user += (
            "\n\nExample questions this schema supports (hint, not a constraint):\n"
            + lines
        )
    prompt = _system_prompt(dashboard.panel_limit())
    try:
        raw = llm.complete(prompt, user, json_mode=True)
        current = _parse_plan(raw)
    except (llm.RateLimitError, llm.ProviderUnavailableError):
        raise
    except (llm.LLMError, ValueError, json.JSONDecodeError, ValidationError) as e:
        log.warning("planner attempt 1 unusable: %s", e)
        try:
            raw = llm.complete(
                prompt,
                user + "\n\nReturn one JSON object only. No prose.",
                json_mode=True,
            )
            current = _parse_plan(raw)
        except (llm.RateLimitError, llm.ProviderUnavailableError):
            raise
        except (llm.LLMError, ValueError, json.JSONDecodeError, ValidationError) as retry:
            log.warning("planner attempt 2 unusable: %s", retry)
            return _refuse(_unreadable_plan_reason())

    if current.route == "dashboard":
        return _prepare_dashboard(current)
    if current.route == "answer" and not current.sql:
        return _refuse("The model chose to answer but returned no SQL.")
    if current.route == "chat" and not (current.reply or "").strip():
        return _refuse("The model chose to chat but returned no reply.")
    if current.route != "answer" or schema is None:
        return _repair_clarify_term(current, question)

    try:
        current.sql = guard.validate(
            catalog.restore_table_names(current.sql, aliases or {}), schema
        )
        return current
    except guard.GuardError as first:
        first_error = first.message
        first_code = first.code
        log.warning("guard rejected attempt 1 (%s): %s", first.code, current.sql)

    card = schema_card if first_code in _SCHEMA_DEPENDENT_ERRORS else ""
    repair = _build_user_message(question, card, definitions, []) + "\n\n" + _REPAIR_TEMPLATE.format(
        sql=current.sql, error=first_error
    )
    try:
        retry = _parse_plan(llm.complete(prompt, repair, json_mode=True))
    except (llm.RateLimitError, llm.ProviderUnavailableError):
        raise
    except (llm.LLMError, ValueError, json.JSONDecodeError, ValidationError) as e:
        log.warning("planner repair attempt unusable: %s", e)
        return _refuse(f"That query could not be run: {first_error}", first_code)

    if retry.route != "answer":
        return _repair_clarify_term(retry, question)
    if not retry.sql:
        return _refuse(f"That query could not be run: {first_error}", first_code)

    try:
        retry.sql = guard.validate(
            catalog.restore_table_names(retry.sql, aliases or {}), schema
        )
        return retry
    except guard.GuardError as second:
        log.warning("guard rejected repair attempt (%s): %s", second.code, retry.sql)
        return _refuse(f"That query could not be run: {second.message}", second.code)
