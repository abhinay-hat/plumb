"""The seam every front end sits on. No web concerns live here."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import duckdb

from backend import catalog, chart, chart_guard, dashboard, guard, llm, narrate, suggestions
from backend.models import AskResponse, ChartAdvice, Panel, Plan, TableInfo
from backend.planner import plan as make_plan
from backend.planner import repair_chart_spec

log = logging.getLogger("plumb.pipeline")


@dataclass
class Session:
    """One loaded spreadsheet plus everything the conversation has settled."""

    con: duckdb.DuckDBPyConnection
    tables: list[TableInfo]
    definitions: dict[str, str] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    clarify_counts: dict[str, int] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    endpoint_url: str | None = None
    endpoint_key: str | None = None
    endpoint_host: str | None = None
    endpoint_ip: str | None = None
    preset_id: str | None = None

    def settle(self, term: str, definition: str) -> None:
        """Record a chosen clarify option so later turns stop asking."""
        self.definitions[term.strip().lower()] = definition

    def schema_card(self, tables: list[TableInfo] | None = None) -> str:
        return catalog.render_schema(self.tables if tables is None else tables)

    def aliases(self) -> dict[str, str]:
        """Display table name -> real DuckDB name, for the SQL coming back."""
        return catalog.alias_map(self.tables)

    def schema(self) -> dict[str, dict[str, str]]:
        return catalog.schema_dict(self.tables)

    def dtypes(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for columns in self.schema().values():
            merged.update(columns)
        return merged


def _applied_definitions(question: str, definitions: dict[str, str]) -> dict[str, str]:
    lowered = question.lower()
    return {term: meaning for term, meaning in definitions.items() if term in lowered}


def _retry_phrase(retry_after: float | None) -> str:
    """"try again in a moment" is a lie when the quota resets in ten minutes."""
    if retry_after is None or retry_after < 60:
        return "in a moment"
    minutes = round(retry_after / 60)
    return f"in about {minutes} minute{'' if minutes == 1 else 's'}"


def _normalise(question: str) -> str:
    return " ".join(question.lower().split()).rstrip("?").strip()


def _term_is_settled(plan: Plan, applied: dict[str, str], definitions: dict[str, str]) -> bool:
    if applied:
        return True
    term = (plan.clarify_term or "").strip().lower()
    return bool(term) and term in definitions


def _inject_chart_data(spec: dict, columns: list[str], rows: list[list]) -> dict:
    out = dict(spec)
    out["data"] = {"values": [dict(zip(columns, row)) for row in rows]}
    return out


def _wants_chart(question: str, plan: Plan) -> bool:
    return chart.visualization_kind(question) is not None or plan.chart not in (
        None,
        "none",
    )


def _resolve_chart_spec(
    question: str,
    plan: Plan,
    session: Session,
    schema_card: str,
    applied: dict[str, str],
    columns: list[str],
    rows: list[list],
    advice: ChartAdvice,
    sent: list[TableInfo],
) -> tuple[dict | None, str | None]:
    """Validate plan.chart_spec, with one repair attempt, or drop it."""
    if plan.chart_spec is None:
        return None, None

    current = plan
    for attempt in range(2):
        try:
            validated = chart_guard.validate_spec(current.chart_spec, columns, rows)
            return validated, chart_guard.primary_mark(validated)
        except chart_guard.ChartSpecError as e:
            log.warning(
                "chart_spec rejected attempt %d (%s): %s",
                attempt + 1,
                e.code,
                e.message,
            )
            if attempt == 0:
                current = repair_chart_spec(
                    question,
                    current,
                    schema_card,
                    session.definitions,
                    session.history,
                    columns,
                    e.message,
                    advice,
                    schema=catalog.schema_dict(sent),
                    aliases=session.aliases(),
                )
                if current.chart_spec is None:
                    return None, None
            else:
                return None, None
    return None, None


def _panel_chart(
    raw: Panel,
    columns: list[str],
    rows: list[list],
    dtypes: dict[str, str],
) -> tuple[dict | None, ChartAdvice]:
    advice = chart.recommend(columns, rows, dtypes)
    spec: dict | None = None
    if raw.chart_spec is not None:
        try:
            spec = chart.compact_spec(
                chart_guard.validate_spec(raw.chart_spec, columns, rows)
            )
            advice.rendered = chart_guard.primary_mark(spec)
        except chart_guard.ChartSpecError as e:
            log.warning("dashboard panel chart_spec rejected (%s): %s", e.code, e.message)
    if spec is None:
        spec = chart.build_from_advice(advice, columns, rows, dtypes, compact=True)
        advice.rendered = advice.kind if spec is not None else None
    if spec is not None:
        spec = _inject_chart_data(spec, columns, rows)
    return spec, advice


def _dashboard_summary(question: str, panels: list[Panel]) -> str | None:
    lines = []
    for panel in panels:
        if panel.error_code or not panel.finding:
            continue
        lines.append(f"- {panel.title}: {panel.finding}")
    if not lines:
        return None
    user = (
        f"Question: {question}\n\n"
        "Panel findings:\n"
        + "\n".join(lines)
        + "\n\nWrite one short paragraph tying these together. Use only the "
        "numbers already stated above."
    )
    try:
        return llm.complete(
            "You summarise dashboard panels in one paragraph. "
            "Use only numbers from the findings given.",
            user,
            json_mode=False,
        ).strip()
    except llm.LLMError as e:
        log.warning("dashboard summary unavailable: %s", e)
        return None


def _dashboard(
    question: str,
    plan: Plan,
    session: Session,
    applied: dict[str, str],
    sent: list[TableInfo],
    sent_names: list[str],
    elapsed: Callable[[], int],
) -> AskResponse:
    deadline = time.perf_counter() + dashboard.timeout_ms() / 1000.0
    schema = catalog.schema_dict(sent)
    aliases = session.aliases()
    dtypes = session.dtypes()
    raw_panels = dashboard.dedupe_panels(
        (plan.panels or [])[: dashboard.panel_limit()]
    )
    completed: list[Panel] = []

    for index, raw in enumerate(raw_panels):
        if time.perf_counter() >= deadline:
            for skipped in raw_panels[index:]:
                completed.append(
                    Panel(title=skipped.title, error_code="timeout")
                )
            break

        panel = Panel(title=raw.title, chart_spec=raw.chart_spec)
        if not raw.sql:
            panel.error_code = "missing_sql"
            completed.append(panel)
            continue

        try:
            sql = guard.validate(
                catalog.restore_table_names(raw.sql, aliases), schema
            )
        except guard.GuardError as e:
            panel.error_code = e.code
            completed.append(panel)
            continue

        try:
            cursor = session.con.execute(sql)
            columns = dashboard.uniquify_columns([d[0] for d in cursor.description])
            rows = [list(r) for r in cursor.fetchall()]
        except duckdb.Error as e:
            log.warning("dashboard panel execution failed: %s", e)
            panel.sql = sql
            panel.error_code = "execution_error"
            completed.append(panel)
            continue

        panel.sql = sql
        panel.columns = columns
        panel.rows = rows
        try:
            panel.chart, panel.chart_advice = _panel_chart(raw, columns, rows, dtypes)
            panel.finding = dashboard.verified_finding(columns, rows, dtypes)
        except Exception as e:
            # Isolation has to cover the unexpected, not only GuardError and
            # duckdb.Error. A dashboard has N chances to hit an odd result
            # shape, and one of them raising must not discard the panels that
            # already succeeded — that would make this route strictly worse
            # than the single answer it replaced.
            log.warning("dashboard panel %r could not be drawn: %s", panel.title, e)
            panel.chart = None
            panel.chart_advice = None
            panel.finding = ""
            panel.error_code = "render_failed"
        completed.append(panel)

    # A panel that could not be drawn still has its rows, and a table is a
    # perfectly good panel. Only a panel with no data at all has failed.
    ok = [p for p in completed if p.rows is not None]
    if not ok:
        return AskResponse(
            route="refuse",
            refuse_reason=(
                "Every dashboard panel failed — nothing could be validated or "
                "executed against this schema."
            ),
            definitions_applied=applied,
            elapsed_ms=elapsed(),
            tables_sent=sent_names,
        )

    summary = None
    if dashboard.summary_enabled():
        try:
            summary = _dashboard_summary(question, completed)
        except Exception as e:
            # One more LLM call, so one more rate limit. The panels are already
            # computed; losing the turn over the paragraph that ties them
            # together would be the worst possible trade.
            log.warning("dashboard summary failed, panels stand: %s", e)

    lead = ok[0]
    session.history.append({"question": question, "route": "dashboard", "sql": None})
    return AskResponse(
        route="dashboard",
        panels=completed,
        summary=summary,
        follow_ups=suggestions.follow_ups(
            lead.columns or [],
            lead.rows or [],
            session.tables,
            asked=[turn["question"] for turn in session.history] + [question],
        ),
        definitions_applied=applied,
        elapsed_ms=elapsed(),
        tables_sent=sent_names,
    )


def _break_clarify_loop(
    question: str,
    plan: Plan,
    session: Session,
    schema_card: str,
    applied: dict[str, str],
) -> Plan:
    """A user must never see the same clarify card twice.

    The prompt tells the model not to re-ask a settled term, but a prompt rule
    is not a guarantee — same principle as the guard: the model proposes,
    Python decides. Once a question has clarified and its definition is
    settled, a second clarify is overridden with one forced re-plan, and a
    refusal if even that comes back asking.
    """
    key = _normalise(question)
    if session.clarify_counts.get(key, 0) < 1:
        return plan
    if not _term_is_settled(plan, applied, session.definitions):
        return plan

    log.warning("clarify loop on %r; forcing a re-plan against settled definitions", key)
    forced = make_plan(
        question,
        schema_card,
        session.definitions,
        session.history,
        schema=session.schema(),
        force_answer=True,
        aliases=session.aliases(),
    )
    if forced.route != "clarify":
        return forced

    term = plan.clarify_term or next(iter(applied), "that term")
    return Plan(
        route="refuse",
        refuse_reason=(
            f'You already settled what "{term}" means, but that definition could '
            "not be applied to these columns. Rephrase the question naming the "
            "column you want, or upload a sheet that carries it."
        ),
    )


def ask(question: str, session: Session) -> AskResponse:
    """Answer a question about the loaded spreadsheet, or ask one back."""
    token = llm.bind(llm.session_endpoint(session))
    try:
        response = _ask(question, session)
        response.provider = llm.current_provider()
        response.model = llm.current_model()
        response.endpoint_host = llm.current_host()
        return response
    finally:
        llm.reset(token)


def _ask(question: str, session: Session) -> AskResponse:
    started = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    applied = _applied_definitions(question, session.definitions)
    sent = catalog.select_tables(question, session.tables)
    schema_card = session.schema_card(sent)
    sent_names = [catalog.display_name(t) for t in sent]
    if len(sent) < len(session.tables):
        log.info(
            "planner sees %d of %d tables: %s",
            len(sent),
            len(session.tables),
            ", ".join(sent_names),
        )
    try:
        plan = make_plan(
            question,
            schema_card,
            session.definitions,
            session.history,
            schema=catalog.schema_dict(sent),
            aliases=session.aliases(),
            question_hints=suggestions.suggest_questions(sent, limit=5),
        )
        if plan.guard_code == "unknown_table" and len(sent) < len(session.tables):
            # Over-pruning is the one way this feature produces a wrong answer,
            # so it is made self-correcting: the model reached for a table we
            # decided not to show it, which is our mistake, not the user's.
            log.warning("pruned schema was too narrow; re-planning on all tables")
            sent = session.tables
            sent_names = [catalog.display_name(t) for t in sent]
            schema_card = session.schema_card(sent)
            plan = make_plan(
                question,
                schema_card,
                session.definitions,
                session.history,
                schema=session.schema(),
                aliases=session.aliases(),
                question_hints=suggestions.suggest_questions(sent, limit=5),
            )
        if plan.route == "clarify":
            plan = _break_clarify_loop(question, plan, session, schema_card, applied)
    except llm.ProviderUnavailableError as e:
        log.warning("provider model unavailable, not refusing: %s", e)
        return AskResponse(
            route="error",
            error_code="provider_unavailable",
            error_message=(
                "That model is unavailable right now, so this question was never "
                "answered. Nothing is wrong with your data — pick another model."
            ),
            definitions_applied=applied,
            elapsed_ms=elapsed(),
            tables_sent=sent_names,
        )
    except llm.RateLimitError as e:
        # The provider never looked at the data. Calling this a refusal would
        # tell the user their spreadsheet cannot answer the question, which is
        # a different — and false — claim.
        log.warning("provider rate-limited, not refusing: %s", e)
        return AskResponse(
            route="error",
            error_code="provider_rate_limited",
            error_message=(
                "The model provider is rate-limited right now, so this question "
                "was never answered. Nothing is wrong with your data — "
                f"try again {_retry_phrase(e.retry_after)}."
            ),
            definitions_applied=applied,
            elapsed_ms=elapsed(),
            tables_sent=sent_names,
        )

    if plan.route == "chat":
        session.history.append({"question": question, "route": "chat", "sql": None})
        return AskResponse(
            route="chat",
            reply=plan.reply,
            definitions_applied=applied,
            elapsed_ms=elapsed(),
            tables_sent=sent_names,
        )

    if plan.route in ("clarify", "refuse"):
        session.history.append(
            {"question": question, "route": plan.route, "sql": None}
        )
        if plan.route == "clarify":
            key = _normalise(question)
            session.clarify_counts[key] = session.clarify_counts.get(key, 0) + 1
        return AskResponse(
            route=plan.route,
            clarify_question=plan.clarify_question,
            clarify_options=plan.clarify_options,
            clarify_term=plan.clarify_term,
            refuse_reason=plan.refuse_reason,
            definitions_applied=applied,
            elapsed_ms=elapsed(),
            tables_sent=sent_names,
        )

    if plan.route == "dashboard":
        return _dashboard(
            question, plan, session, applied, sent, sent_names, elapsed
        )

    sql = guard.validate(
        catalog.restore_table_names(plan.sql, session.aliases()), session.schema()
    )
    try:
        cursor = session.con.execute(sql)
        columns = [d[0] for d in cursor.description]
        rows = [list(r) for r in cursor.fetchall()]
    except duckdb.Error as e:
        log.warning("execution failed for validated SQL: %s", e)
        session.history.append(
            {"question": question, "route": "refuse", "sql": sql}
        )
        return AskResponse(
            route="refuse",
            sql=sql,
            refuse_reason=f"The query passed validation but DuckDB could not run it: {e}",
            definitions_applied=applied,
            elapsed_ms=elapsed(),
            tables_sent=sent_names,
        )

    coverage = catalog.aggregate_coverage(sql, session.tables)
    narration = narrate.narrate(question, sql, columns, rows, coverage=coverage)
    if not narrate.verify_narration(
        narration, rows, question=question, coverage=coverage
    ):
        log.warning("narration cited an unsupported number, discarding: %s", narration)
        narration = narrate._with_coverage(f"{len(rows)} rows returned.", coverage)

    dtypes = session.dtypes()
    advice = chart.recommend(columns, rows, dtypes)

    spec, chart_kind = _resolve_chart_spec(
        question, plan, session, schema_card, applied, columns, rows, advice, sent
    )
    if spec is None:
        spec, chart_kind = chart.build_spec_for_question(
            question, plan, columns, rows, dtypes
        )
    if spec is None and _wants_chart(question, plan):
        spec = chart.build_from_advice(advice, columns, rows, dtypes)
        if spec is not None:
            chart_kind = advice.kind
    elif spec is None and chart.visualization_kind(question):
        log.info(
            "chart requested but no spec could be built: columns=%s rows=%d plan.chart=%s",
            columns,
            len(rows),
            plan.chart,
        )

    if spec is not None:
        spec = _inject_chart_data(spec, columns, rows)
    advice.rendered = chart_kind

    session.history.append({"question": question, "route": "answer", "sql": sql})
    return AskResponse(
        route="answer",
        sql=sql,
        columns=columns,
        rows=rows,
        narration=narration,
        chart=spec,
        chart_advice=advice,
        follow_ups=suggestions.follow_ups(
            columns,
            rows,
            session.tables,
            advice=advice,
            rendered=chart_kind,
            # Including this turn: a "next" that repeats the question just
            # answered is the one suggestion guaranteed to be useless.
            asked=[turn["question"] for turn in session.history] + [question],
        ),
        definitions_applied=applied,
        elapsed_ms=elapsed(),
        tables_sent=sent_names,
    )
