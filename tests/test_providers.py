"""The picker roster is discovered from the provider, not declared in the repo."""

from __future__ import annotations

import httpx
import pytest

from backend import llm, providers


class _Stub:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.calls = 0

    def __call__(self, url, headers=None, timeout=None):  # noqa: ANN001
        self.calls += 1
        self.url = url
        self.headers = dict(headers or {})
        return httpx.Response(
            self.status,
            json=self.payload,
            request=httpx.Request("GET", url),
        )


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("PLUMB_LIVE_MODELS", "1")
    providers.forget_discovered()
    yield
    providers.forget_discovered()


def test_roster_comes_from_the_provider(live, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    stub = _Stub({"data": [{"id": "z-model"}, {"id": "a-model", "name": "A Model"}]})
    monkeypatch.setattr(providers.httpx, "get", stub)

    found = providers.models_for("groq")

    assert [row["id"] for row in found] == ["a-model", "z-model"]
    assert found[0]["label"] == "A Model"
    assert stub.headers["Authorization"] == "Bearer sk-test"


def test_a_model_that_cannot_do_json_is_not_offered(live, monkeypatch) -> None:
    monkeypatch.setattr(
        providers.httpx,
        "get",
        _Stub(
            {
                "data": [
                    {
                        "id": "prose-only",
                        "pricing": {"prompt": "0"},
                        "supported_parameters": ["temperature"],
                    },
                    {
                        "id": "json-ok",
                        "pricing": {"prompt": "0"},
                        "supported_parameters": ["response_format"],
                    },
                ]
            }
        ),
    )
    assert [row["id"] for row in providers.models_for("openrouter")] == ["json-ok"]


def test_a_speech_model_is_not_offered_as_a_planner(live, monkeypatch) -> None:
    """Groq's roster carries whisper and orpheus; neither can plan SQL."""
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    monkeypatch.setattr(
        providers.httpx,
        "get",
        _Stub(
            {
                "data": [
                    {"id": "whisper-large-v3", "output_modalities": ["text"],
                     "supported_features": []},
                    {"id": "orpheus", "output_modalities": ["audio"],
                     "supported_features": ["json_mode"]},
                    {"id": "planner", "output_modalities": ["text"],
                     "supported_features": ["json_mode"]},
                ]
            }
        ),
    )
    assert [row["id"] for row in providers.models_for("groq")] == ["planner"]


def test_a_dead_provider_falls_back_instead_of_emptying_the_picker(
    live, monkeypatch
) -> None:
    def boom(*_args, **_kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(providers.httpx, "get", boom)
    assert providers.models_for("ollama") == list(providers.FALLBACK_MODELS["ollama"])


def test_discovery_is_cached_per_provider(live, monkeypatch) -> None:
    stub = _Stub({"data": [{"id": "one", "pricing": {"prompt": "0"}}]})
    monkeypatch.setattr(providers.httpx, "get", stub)

    providers.models_for("openrouter")
    providers.models_for("openrouter")

    assert stub.calls == 1


def test_an_unset_key_never_reaches_the_network(live, monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    stub = _Stub({"data": [{"id": "should-not-be-asked"}]})
    monkeypatch.setattr(providers.httpx, "get", stub)

    assert providers.models_for("groq") == list(providers.FALLBACK_MODELS["groq"])
    assert stub.calls == 0


def test_the_catalog_serves_the_discovered_roster(live, monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "openrouter")
    monkeypatch.setenv("PLUMB_MODEL", "one")
    monkeypatch.setattr(
        providers.httpx,
        "get",
        _Stub({"data": [{"id": "one", "pricing": {"prompt": "0"}}]}),
    )

    body = llm.catalog()
    roster = next(item for item in body["providers"] if item["id"] == "openrouter")

    assert [row["id"] for row in roster["models"]] == ["one"]
