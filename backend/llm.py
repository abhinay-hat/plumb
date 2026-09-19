"""Plain-HTTP LLM access. One function, two providers, no framework."""

from __future__ import annotations

import os

import httpx

TIMEOUT_SECONDS = 30.0
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5-coder:7b-instruct"


class LLMError(RuntimeError):
    """The provider could not be reached or returned something unusable."""


def _groq_request(system: str, user: str, json_mode: bool) -> tuple[str, dict, dict]:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError(
            "GROQ_API_KEY is not set. Export it, or set PLUMB_PROVIDER=ollama "
            "to use a local model."
        )
    payload: dict = {
        "model": os.environ.get("PLUMB_MODEL", GROQ_MODEL),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return GROQ_URL, {"Authorization": f"Bearer {key}"}, payload


def _ollama_request(system: str, user: str, json_mode: bool) -> tuple[str, dict, dict]:
    payload: dict = {
        "model": os.environ.get("PLUMB_MODEL", OLLAMA_MODEL),
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        payload["format"] = "json"
    return OLLAMA_URL, {}, payload


def _extract(provider: str, body: dict) -> str:
    if provider == "groq":
        choices = body.get("choices") or []
        if not choices:
            raise LLMError(f"groq returned no choices: {body}")
        content = choices[0].get("message", {}).get("content")
    else:
        content = body.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError(f"provider returned an empty completion: {body}")
    return content


def complete(system: str, user: str, json_mode: bool = True) -> str:
    """Send one prompt to the configured provider and return the raw text."""
    provider = os.environ.get("PLUMB_PROVIDER", "groq").strip().lower()
    if provider == "groq":
        url, headers, payload = _groq_request(system, user, json_mode)
    elif provider == "ollama":
        url, headers, payload = _ollama_request(system, user, json_mode)
    else:
        raise LLMError(f"unknown PLUMB_PROVIDER {provider!r}; use 'groq' or 'ollama'")

    last: Exception | None = None
    for attempt in range(2):
        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS
            )
        except httpx.TimeoutException as e:
            last = e
            continue
        except httpx.RequestError as e:
            raise LLMError(f"could not reach {provider} at {url}: {e}") from e
        if response.status_code >= 500:
            last = LLMError(f"{provider} returned {response.status_code}: {response.text}")
            continue
        if response.status_code >= 400:
            raise LLMError(f"{provider} returned {response.status_code}: {response.text}")
        return _extract(provider, response.json())

    raise LLMError(f"{provider} failed after 2 attempts: {last}") from last
