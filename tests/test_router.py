"""Routing across free tiers: a busy provider costs a retry, not the turn."""

from __future__ import annotations

import httpx
import pytest

from backend import llm, router


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    router.reset_health()
    monkeypatch.setenv("PLUMB_ROUTE", "1")
    monkeypatch.setenv("GROQ_API_KEY", "sk-groq")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    monkeypatch.delenv("PLUMB_OLLAMA_URL", raising=False)
    yield
    router.reset_health()


def _answer(text: str = '{"route": "refuse"}') -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": text}}]},
        request=httpx.Request("POST", "https://example.test"),
    )


def _limited(retry_after: str = "1") -> httpx.Response:
    return httpx.Response(
        429,
        headers={"retry-after": retry_after},
        text="rate limit reached",
        request=httpx.Request("POST", "https://example.test"),
    )


class _Sequence:
    """Answers each POST from a scripted list, recording which model was asked."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.models: list[str] = []

    def __call__(self, url, headers=None, json=None, timeout=None):  # noqa: ANN001
        self.models.append((json or {}).get("model", "?"))
        return self.responses.pop(0) if self.responses else _answer()


def test_a_rate_limited_provider_hands_off_instead_of_failing(monkeypatch) -> None:
    posts = _Sequence(_limited(), _answer('{"route": "answer"}'))
    monkeypatch.setattr(llm.httpx, "post", posts)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    assert llm.complete("s", "u") == '{"route": "answer"}'
    assert len(posts.models) == 2, "the second candidate should have been tried"
    assert posts.models[0] != posts.models[1]


def test_the_model_that_answered_is_the_one_reported(monkeypatch) -> None:
    posts = _Sequence(_limited(), _answer())
    monkeypatch.setattr(llm.httpx, "post", posts)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    llm.complete("s", "u")
    # The winner stays bound so the audit log and the answer card agree.
    assert llm.current_model() == posts.models[1]


def test_a_burned_provider_is_not_tried_first_next_time(monkeypatch) -> None:
    posts = _Sequence(_limited("30"), _answer())
    monkeypatch.setattr(llm.httpx, "post", posts)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    llm.complete("s", "u")
    burned = posts.models[0]

    ordered = router.rank(router.pool())
    assert ordered[0].model != burned, "a cooling candidate must not lead the pool"


def test_everything_limited_still_reports_a_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(llm.httpx, "post", _Sequence(*[_limited() for _ in range(12)]))
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    with pytest.raises(llm.RateLimitError) as caught:
        llm.complete("s", "u")
    assert "every configured model is rate-limited" in str(caught.value)


def test_routing_off_keeps_the_single_provider_behaviour(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_ROUTE", "0")
    posts = _Sequence(_limited(), _answer())
    monkeypatch.setattr(llm.httpx, "post", posts)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    llm.complete("s", "u")
    assert len(set(posts.models)) == 1, "no failover when routing is disabled"


def test_a_provider_without_a_key_is_never_in_the_pool(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert [c for c in router.pool() if c.provider in {"groq", "openrouter"}] == []


def test_measured_speed_outranks_an_untried_candidate() -> None:
    fast = router.Candidate(provider="groq", model="fast")
    unknown = router.Candidate(provider="openrouter", model="unknown")
    router.health_for(fast.name).record_success(400.0)

    assert router.rank([unknown, fast])[0].model == "fast"


def test_an_explicit_pick_is_tried_before_the_ranking() -> None:
    pinned = router.Candidate(provider="openrouter", model="chosen-by-hand")
    router.health_for(pinned.name).record_success(9000.0)  # slow, but chosen

    assert router.order(pinned)[0].model == "chosen-by-hand"
