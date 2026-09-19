"""The seam every front end sits on. No web concerns live here."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import duckdb

from backend import catalog, chart, guard, llm, narrate
from backend.models import AskResponse, Plan, TableInfo
from backend.planner import plan as make_plan

log = logging.getLogger("plumb.pipeline")


@dataclass
class Session:
    """One loaded spreadsheet plus everything the conversation has settled."""

    con: duckdb.DuckDBPyConnection
    tables: list[TableInfo]
    definitions: dict[str, str] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    clarify_counts: dict[str, int] = field(default_factory=dict)

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
            )
        if plan.route == "clarify":
            plan = _break_clarify_loop(question, plan, session, schema_card, applied)
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

    spec = chart.build_spec(plan, columns, rows, session.dtypes())
    if spec is not None:
        spec["data"] = {"values": [dict(zip(columns, row)) for row in rows]}

    session.history.append({"question": question, "route": "answer", "sql": sql})
    return AskResponse(
        route="answer",
        sql=sql,
        columns=columns,
        rows=rows,
        narration=narration,
        chart=spec,
        definitions_applied=applied,
        elapsed_ms=elapsed(),
        tables_sent=sent_names,
    )
