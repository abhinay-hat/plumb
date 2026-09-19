"""Routing decisions Python makes, with the model stubbed out.

The planner itself needs a live provider, so everything here replaces
`pipeline.make_plan` with a scripted stub. What is under test is the part that
must hold even when the model misbehaves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import catalog, guard, llm, pipeline
from backend.models import Plan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def session() -> pipeline.Session:
    con, tables = catalog.ingest_many([str(FIXTURES / "employees.csv")], "test")
    guard.safe_connection(con)
    return pipeline.Session(con=con, tables=tables)


def _stub(monkeypatch: pytest.MonkeyPatch, plans: list[Plan]) -> list[dict]:
    """Serve `plans` in order, repeating the last, and record each call."""
    calls: list[dict] = []

    def fake_plan(question, schema_card, definitions, history, schema=None, force_answer=False):
        calls.append(
            {
                "question": question,
                "definitions": dict(definitions),
                "force_answer": force_answer,
            }
        )
        return plans[min(len(calls) - 1, len(plans) - 1)]

    monkeypatch.setattr(pipeline, "make_plan", fake_plan)
    return calls


def _clarify(term: str = "headcount") -> Plan:
    return Plan(
        route="clarify",
        clarify_question="Which headcount do you mean?",
        clarify_options=["Everyone on file", "Only status = Active"],
        clarify_term=term,
    )


def test_rate_limit_is_an_error_not_a_refusal(session, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise llm.RateLimitError("groq returned 429")

    monkeypatch.setattr(pipeline, "make_plan", boom)

    response = pipeline.ask("what's our headcount?", session)
    assert response.route == "error"
    assert response.error_code == "provider_rate_limited"
    assert "rate-limited" in (response.error_message or "")
    # The lie we are avoiding: telling the user their data cannot answer this.
    assert response.refuse_reason is None


def test_a_long_quota_wait_is_stated_not_softened(session, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise llm.RateLimitError("daily quota", retry_after=631.0)

    monkeypatch.setattr(pipeline, "make_plan", boom)

    message = pipeline.ask("q", session).error_message or ""
    assert "about 11 minutes" in message
    assert "in a moment" not in message


def test_clarify_carries_the_term_the_planner_named(session, monkeypatch) -> None:
    _stub(monkeypatch, [_clarify("headcount")])
    response = pipeline.ask("how's the team doing?", session)
    assert response.route == "clarify"
    assert response.clarify_term == "headcount"


def test_settled_definition_answers_on_the_second_ask(session, monkeypatch) -> None:
    answer = Plan(route="answer", sql="SELECT count(*) AS headcount FROM employees")
    calls = _stub(monkeypatch, [_clarify(), answer])

    first = pipeline.ask("what's our headcount?", session)
    assert first.route == "clarify"

    session.settle(first.clarify_term or "", "Everyone on file")
    second = pipeline.ask("what's our headcount?", session)

    assert second.route == "answer"
    assert second.rows
    # The settled definition reached the planner, and came back as applied.
    assert calls[1]["definitions"] == {"headcount": "Everyone on file"}
    assert second.definitions_applied == {"headcount": "Everyone on file"}


def test_a_stubborn_planner_never_clarifies_twice(session, monkeypatch) -> None:
    calls = _stub(monkeypatch, [_clarify(), _clarify(), _clarify()])

    first = pipeline.ask("what's our headcount?", session)
    assert first.route == "clarify"
    session.settle("headcount", "Everyone on file")

    second = pipeline.ask("what's our headcount?", session)
    assert second.route in ("answer", "refuse")
    assert second.route != "clarify"
    # The override made a forced re-plan before giving up.
    assert calls[-1]["force_answer"] is True


def test_the_loop_breaker_prefers_an_answer_from_the_forced_replan(
    session, monkeypatch
) -> None:
    answer = Plan(route="answer", sql="SELECT count(*) AS headcount FROM employees")
    _stub(monkeypatch, [_clarify(), _clarify(), answer])

    pipeline.ask("what's our headcount?", session)
    session.settle("headcount", "Everyone on file")
    second = pipeline.ask("what's our headcount?", session)

    assert second.route == "answer"


def test_an_unsettled_term_may_still_clarify_again(session, monkeypatch) -> None:
    """The breaker fires on settled terms only — otherwise a user who ignores
    the card and re-asks would be refused for no reason."""
    _stub(monkeypatch, [_clarify(), _clarify()])

    assert pipeline.ask("what's our headcount?", session).route == "clarify"
    assert pipeline.ask("what's our headcount?", session).route == "clarify"


def test_greeting_routes_to_chat_with_no_sql(session, monkeypatch) -> None:
    _stub(monkeypatch, [Plan(route="chat", reply="Hi — you've got 1 table loaded.")])

    response = pipeline.ask("hi", session)
    assert response.route == "chat"
    assert response.reply
    assert response.sql is None
    assert response.chart is None
    assert response.rows is None


def test_a_data_question_is_not_answered_through_chat(session, monkeypatch) -> None:
    """chat carries no SQL, so an answer routed through it would be a number
    with nothing behind it. The route is chosen by the planner; what the
    pipeline guarantees is that chat never gains a query surface."""
    _stub(monkeypatch, [Plan(route="chat", reply="There are 60 employees.")])

    response = pipeline.ask("how many employees?", session)
    assert response.sql is None
    assert response.columns is None
