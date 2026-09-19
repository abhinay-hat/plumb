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


def test_gpt_oss_uses_strict_json_schema_on_groq(monkeypatch) -> None:
    seen: dict = {}

    def fake_post(_url, headers=None, json=None, timeout=None):
        seen.update(json or {})
        return _ok()

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setenv("PLUMB_PROVIDER", "groq")
    monkeypatch.setenv("PLUMB_MODEL", "openai/gpt-oss-20b")
    llm.complete("system", "user")
    fmt = seen["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert seen["messages"][0]["content"].startswith("Reasoning: low")


def test_extract_prefers_structured_parsed_field() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "content": "User Safety: safe",
                    "parsed": {"route": "refuse", "refuse_reason": "nope"},
                }
            }
        ]
    }
    assert llm._extract("groq", body) == '{"route": "refuse", "refuse_reason": "nope"}'


def test_configure_overrides_the_env_pin(monkeypatch) -> None:
    seen: dict = {}

    def fake_post(_url, headers=None, json=None, timeout=None):
        seen.update(json or {})
        return _ok()

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.configure("groq", "openai/gpt-oss-20b")
    assert llm.complete("s", "u") == '{"route": "refuse"}'
    assert seen["model"] == "openai/gpt-oss-20b"


def test_catalog_surfaces_an_unlisted_pin(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "groq")
    monkeypatch.setenv("PLUMB_MODEL", "custom-pin")
    body = llm.catalog()
    groq = next(item for item in body["providers"] if item["id"] == "groq")
    assert groq["models"][0]["id"] == "custom-pin"


def test_other_4xx_is_still_immediate(monkeypatch, _slept) -> None:
    recorder = _Recorder([_response(400, body="bad request")])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.LLMError) as caught:
        llm.complete("s", "u")
    assert not isinstance(caught.value, llm.RateLimitError)
    assert recorder.calls == 1
    assert _slept == []


def test_openrouter_is_reached(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("PLUMB_MODEL", "qwen/qwen3.8-27b:free")
    seen: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["json"] = json
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"route": "refuse"}'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.complete("s", "u") == '{"route": "refuse"}'
    assert seen["url"] == llm.OPENROUTER_URL
    assert seen["headers"]["Authorization"] == "Bearer or-key"
    assert seen["json"]["model"] == "qwen/qwen3.8-27b:free"


def test_configure_accepts_openrouter(monkeypatch) -> None:
    llm.configure("openrouter", "google/gemma-4-31b-it:free")
    assert llm.current_provider() == "openrouter"
    assert llm.current_model() == "google/gemma-4-31b-it:free"


def test_openrouter_404_is_unavailable_not_a_refusal(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    recorder = _Recorder([_response(404, body="No endpoints found")])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.ProviderUnavailableError) as caught:
        llm.complete("s", "u")
    assert not isinstance(caught.value, llm.RateLimitError)
    assert "Pick another model" in str(caught.value)
    assert recorder.calls == 1


def test_openrouter_502_is_unavailable_not_retried(monkeypatch, _slept) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    recorder = _Recorder([_response(502, body="Bad Gateway")])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.ProviderUnavailableError):
        llm.complete("s", "u")
    assert recorder.calls == 1
    assert _slept == []


def test_extract_names_the_actual_provider() -> None:
    with pytest.raises(llm.LLMError) as caught:
        llm._extract("openrouter", {"choices": []})
    assert "openrouter returned no choices" in str(caught.value)
    with pytest.raises(llm.LLMError) as caught:
        llm._extract("groq", {"choices": []})
    assert "groq returned no choices" in str(caught.value)
    with pytest.raises(llm.LLMError) as caught:
        llm._extract("custom", {"choices": []})
    assert "custom returned no choices" in str(caught.value)


def _ok_openai() -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"choices": [{"message": {"content": "ok"}}]},
        request=httpx.Request("POST", "http://127.0.0.1:11434/v1/chat/completions"),
    )


def test_custom_endpoint_is_reached(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "custom")
    monkeypatch.setenv("PLUMB_CUSTOM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("PLUMB_CUSTOM_MODEL", "llama3.2")
    monkeypatch.setenv("PLUMB_CUSTOM_KEY", "sk-secret")
    seen: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        seen["url"] = url
        seen["headers"] = headers
        seen["json"] = json
        seen["kwargs"] = kwargs
        return _ok_openai()

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.complete("s", "u") == "ok"
    assert "127.0.0.1" in seen["url"]
    assert seen["headers"]["Authorization"] == "Bearer sk-secret"
    assert seen["headers"]["Host"] == "127.0.0.1:11434"
    assert seen["json"]["model"] == "llama3.2"
    assert seen["kwargs"].get("follow_redirects") is False


def test_custom_429_is_a_rate_limit(monkeypatch, _slept) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "custom")
    monkeypatch.setenv("PLUMB_CUSTOM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("PLUMB_CUSTOM_MODEL", "llama3.2")
    recorder = _Recorder([_response(429, headers={"retry-after": "1"})])
    monkeypatch.setattr(llm.httpx, "post", recorder)

    with pytest.raises(llm.RateLimitError):
        llm.complete("s", "u")
    assert recorder.calls == llm.RATE_LIMIT_ATTEMPTS
    assert not isinstance(llm.RateLimitError("x"), llm.ProviderUnavailableError)


def test_custom_key_is_scrubbed_from_errors(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "custom")
    monkeypatch.setenv("PLUMB_CUSTOM_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("PLUMB_CUSTOM_MODEL", "llama3.2")
    monkeypatch.setenv("PLUMB_CUSTOM_KEY", "sk-never-leak")

    def fake_post(*_a, **_k):
        raise httpx.ConnectError("failed to reach http://127.0.0.1 with sk-never-leak")

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    with pytest.raises(llm.LLMError) as caught:
        llm.complete("s", "u")
    assert "sk-never-leak" not in str(caught.value)


def test_custom_key_never_appears_in_catalog(monkeypatch) -> None:
    from backend.pipeline import Session

    session = Session(
        con=None,  # type: ignore[arg-type]
        tables=[],
        provider="custom",
        model="llama3.2",
        endpoint_url="http://127.0.0.1:11434/v1/chat/completions",
        endpoint_key="sk-never-leak",
        endpoint_host="127.0.0.1",
        endpoint_ip="127.0.0.1",
    )
    dumped = str(llm.catalog(session))
    assert "sk-never-leak" not in dumped
    assert llm.catalog(session)["host"] == "127.0.0.1"


def test_two_sessions_hold_different_custom_endpoints(monkeypatch) -> None:
    from backend.endpoint_guard import inspect_endpoint
    from backend.pipeline import Session

    monkeypatch.setattr(llm, "probe", lambda url, key, model: inspect_endpoint(url))

    a = Session(con=None, tables=[])  # type: ignore[arg-type]
    b = Session(con=None, tables=[])  # type: ignore[arg-type]
    llm.apply_session_provider(
        a, "custom", "one", url="http://127.0.0.1:11434/v1/chat/completions", key="key-a"
    )
    llm.apply_session_provider(
        b, "custom", "two", url="http://127.0.0.1:1234/v1/chat/completions", key="key-b"
    )
    assert a.endpoint_key == "key-a"
    assert b.endpoint_key == "key-b"
    assert a.model == "one"
    assert b.model == "two"
    assert a.endpoint_url != b.endpoint_url
    assert "key-a" not in str(llm.catalog(a))
    assert "key-b" not in str(llm.catalog(b))
