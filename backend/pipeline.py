"""The seam every front end sits on. No web concerns live here."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import duckdb

from backend import catalog, chart, guard, narrate
from backend.models import AskResponse, TableInfo
from backend.planner import plan as make_plan

log = logging.getLogger("plumb.pipeline")


@dataclass
class Session:
    """One loaded spreadsheet plus everything the conversation has settled."""

    con: duckdb.DuckDBPyConnection
    tables: list[TableInfo]
    definitions: dict[str, str] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def settle(self, term: str, definition: str) -> None:
        """Record a chosen clarify option so later turns stop asking."""
        self.definitions[term.strip().lower()] = definition

    def schema_card(self) -> str:
        return catalog.render_schema(self.tables)

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


def ask(question: str, session: Session) -> AskResponse:
    """Answer a question about the loaded spreadsheet, or ask one back."""
    started = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    applied = _applied_definitions(question, session.definitions)
    plan = make_plan(
        question,
        session.schema_card(),
        session.definitions,
        session.history,
        schema=session.schema(),
    )

    if plan.route in ("clarify", "refuse"):
        session.history.append(
            {"question": question, "route": plan.route, "sql": None}
        )
        return AskResponse(
            route=plan.route,
            clarify_question=plan.clarify_question,
            clarify_options=plan.clarify_options,
            refuse_reason=plan.refuse_reason,
            definitions_applied=applied,
            elapsed_ms=elapsed(),
        )

    sql = guard.validate(plan.sql, session.schema())
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
    )
