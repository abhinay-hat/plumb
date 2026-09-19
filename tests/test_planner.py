"""Planner parsing and the invariants Python enforces on the model's JSON."""

from __future__ import annotations

import json

import pytest

from backend import llm, planner
from backend.models import Plan


def _stub_completion(monkeypatch: pytest.MonkeyPatch, payloads: list[dict]) -> list[str]:
    """Serve `payloads` in order as raw completions; record the prompts sent."""
    prompts: list[str] = []

    def fake_complete(_system: str, user: str, json_mode: bool = True) -> str:
        prompts.append(user)
        return json.dumps(payloads[min(len(prompts) - 1, len(payloads) - 1)])

    monkeypatch.setattr(planner.llm, "complete", fake_complete)
    return prompts


def test_clarify_without_a_term_is_repaired_not_passed_through(monkeypatch) -> None:
    _stub_completion(
        monkeypatch,
        [{"route": "clarify", "clarify_question": "Which one?", "clarify_options": ["a", "b"]}],
    )

    result = planner.plan("What's our headcount?", "schema", {}, [])

    assert result.route == "clarify"
    # A clarify with no term files the answer under a key nothing matches.
    assert result.clarify_term == "what's our headcount"


def test_an_empty_clarify_term_counts_as_missing(monkeypatch) -> None:
    _stub_completion(
        monkeypatch,
        [
            {
                "route": "clarify",
                "clarify_question": "Which one?",
                "clarify_options": ["a"],
                "clarify_term": "   ",
            }
        ],
    )

    result = planner.plan("Who are our top performers?", "schema", {}, [])
    assert result.clarify_term == "who are our top performers"


def test_a_named_clarify_term_survives(monkeypatch) -> None:
    _stub_completion(
        monkeypatch,
        [
            {
                "route": "clarify",
                "clarify_question": "Which one?",
                "clarify_options": ["a"],
                "clarify_term": "top performers",
            }
        ],
    )

    assert planner.plan("Who are our top performers?", "s", {}, []).clarify_term == (
        "top performers"
    )


def test_chat_without_a_reply_falls_back_to_refuse(monkeypatch) -> None:
    _stub_completion(monkeypatch, [{"route": "chat", "reply": "  "}])
    assert planner.plan("hi", "schema", {}, []).route == "refuse"


def test_chat_with_a_reply_is_returned(monkeypatch) -> None:
    _stub_completion(monkeypatch, [{"route": "chat", "reply": "Hi — ask me about salary."}])
    result = planner.plan("hi", "schema", {}, [])
    assert result.route == "chat"
    assert result.sql is None


def test_rate_limit_propagates_instead_of_becoming_a_refusal(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise llm.RateLimitError("429")

    monkeypatch.setattr(planner.llm, "complete", boom)

    with pytest.raises(llm.RateLimitError):
        planner.plan("what's our headcount?", "schema", {}, [])


def test_other_llm_errors_still_refuse(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise llm.LLMError("garbage")

    monkeypatch.setattr(planner.llm, "complete", boom)
    assert planner.plan("q", "schema", {}, []).route == "refuse"


def test_only_two_history_turns_are_sent(monkeypatch) -> None:
    prompts = _stub_completion(monkeypatch, [{"route": "refuse", "refuse_reason": "x"}])
    history = [
        {"question": "oldest", "route": "answer", "sql": "SELECT 1"},
        {"question": "middle", "route": "answer", "sql": "SELECT 2"},
        {"question": "newest", "route": "answer", "sql": "SELECT 3"},
    ]

    planner.plan("q", "schema", {}, history)

    assert "oldest" not in prompts[0]
    assert "middle" in prompts[0]
    assert "newest" in prompts[0]


def test_force_answer_tells_the_model_the_definition_is_final(monkeypatch) -> None:
    prompts = _stub_completion(monkeypatch, [{"route": "refuse", "refuse_reason": "x"}])

    planner.plan("q", "schema", {"headcount": "everyone"}, [], force_answer=True)
    assert planner._FORCE_ANSWER_NOTE in prompts[0]

    planner.plan("q", "schema", {"headcount": "everyone"}, [])
    assert planner._FORCE_ANSWER_NOTE not in prompts[1]


def test_system_prompt_states_the_settled_definition_rule() -> None:
    # The rule is the whole point of P1; a silent prompt edit that drops it
    # would reopen the loop with no test failing.
    assert "Do not clarify the same term twice" in planner.SYSTEM_PROMPT
    assert "clarify_term" in planner.SYSTEM_PROMPT
    assert "chat" in planner.SYSTEM_PROMPT


def test_plan_shape_still_validates_all_four_routes() -> None:
    for route in ("answer", "clarify", "refuse", "chat"):
        assert Plan(route=route).route == route
