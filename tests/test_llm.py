"""Rate limits are a provider state, not a data verdict — llm must say which."""

from __future__ import annotations

import httpx
import pytest

from backend import llm


class _Recorder:
    """Stands in for httpx.post and replays a scripted list of responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls = 0

    def __call__(self, *_args, **_kwargs) -> httpx.Response:
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _response(status: int, *, body: str = "", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        text=body,
        headers=headers or {},
        request=httpx.Request("POST", llm.GROQ_URL),
    )


def _ok() -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"choices": [{"message": {"content": '{"route": "refuse"}'}}]},
        request=httpx.Request("POST", llm.GROQ_URL),
    )


@pytest.fixture(autouse=True)
def _groq_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")


@pytest.fixture
def _slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waits: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    return waits


def test_retry_after_header_is_obeyed(monkeypatch, _slept) -> None:
    recorder = _Recorder([_response(429, headers={"retry-after": "3"}), _ok()])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    assert llm.complete("s", "u") == '{"route": "refuse"}'
    assert recorder.calls == 2
    assert _slept == [3.0 + llm._RETRY_PAD_SECONDS]


def test_wait_is_parsed_out_of_the_body_when_no_header(monkeypatch, _slept) -> None:
    body = "Rate limit reached ... Please try again in 7.605s. Visit ..."
    recorder = _Recorder([_response(429, body=body), _ok()])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    llm.complete("s", "u")
    assert _slept == [7.605 + llm._RETRY_PAD_SECONDS]


def test_a_minutes_and_seconds_wait_is_read_whole(monkeypatch, _slept) -> None:
    # A daily-quota 429 reads "try again in 10m31.152s". Taking only the
    # seconds would turn a ten-minute wait into a thirty-second one and then
    # retry straight into the same wall.
    body = "on tokens per day (TPD) ... Please try again in 10m31.152s."
    recorder = _Recorder([_response(429, body=body)])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.RateLimitError):
        llm.complete("s", "u")
    assert recorder.calls == 1  # 631s is past the budget: tell the user now
    assert _slept == []


def test_gives_up_after_three_attempts_with_a_distinct_error(monkeypatch, _slept) -> None:
    recorder = _Recorder([_response(429, headers={"retry-after": "1"})])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.RateLimitError):
        llm.complete("s", "u")
    assert recorder.calls == llm.RATE_LIMIT_ATTEMPTS


def test_total_wait_is_capped(monkeypatch, _slept) -> None:
    recorder = _Recorder([_response(429, headers={"retry-after": "120"})])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.RateLimitError):
        llm.complete("s", "u")
    assert sum(_slept) <= llm.RATE_LIMIT_BUDGET_SECONDS
    assert recorder.calls == 1


def test_rate_limit_error_is_not_a_plain_llm_error_by_accident() -> None:
    # It stays an LLMError so existing `except LLMError` sites keep working,
    # but callers that care can single it out.
    assert issubclass(llm.RateLimitError, llm.LLMError)
    assert not isinstance(llm.LLMError("x"), llm.RateLimitError)


def test_other_4xx_is_still_immediate(monkeypatch, _slept) -> None:
    recorder = _Recorder([_response(400, body="bad request")])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.LLMError) as caught:
        llm.complete("s", "u")
    assert not isinstance(caught.value, llm.RateLimitError)
    assert recorder.calls == 1
    assert _slept == []
