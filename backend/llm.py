"""Plain-HTTP LLM access. One function, two providers, no framework."""

from __future__ import annotations

import logging
import os
import re
import time

import httpx
from dotenv import load_dotenv

# Docker Compose reads .env on its own, but `make dev`, `make demo`, and
# `make eval` run the interpreter directly — without this they saw neither
# GROQ_API_KEY nor the PLUMB_MODEL pin and fell back to a default model that
# 404s. Load it here because this module is the only reader of those vars.
# override=False so an exported shell value still wins over the file.
load_dotenv(override=False)

log = logging.getLogger("plumb.llm")

TIMEOUT_SECONDS = 30.0
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5-coder:7b-instruct"

# A 429 is not a bad prompt, it is a busy queue. Groq states the exact wait in
# the error body ("Please try again in 7.605s") and usually also in a
# retry-after header, so waiting the stated time is far better than backing off
# blind. Three attempts, and never more than half a minute of total sleeping —
# past that a human would rather be told than kept waiting.
RATE_LIMIT_ATTEMPTS = 3
RATE_LIMIT_BUDGET_SECONDS = 30.0
_RETRY_PAD_SECONDS = 0.25
# Groq writes short waits as "7.605s" and long ones as "10m31.152s". Reading
# only the seconds group turns a ten-minute wait into a thirty-second one.
_WAIT_PATTERN = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")


class LLMError(RuntimeError):
    """The provider could not be reached or returned something unusable."""


class RateLimitError(LLMError):
    """The provider was busy. The prompt was fine; nothing was answered.

    Separate from LLMError so the layers above can tell "the model was busy"
    apart from "the model said something unusable" — the second is a refusal,
    the first is not.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _retry_wait(response: httpx.Response) -> float | None:
    """Seconds the provider asked us to wait, or None if it did not say."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = _WAIT_PATTERN.search(response.text)
    if match:
        try:
            minutes = float(match.group(1) or 0)
            return minutes * 60 + float(match.group(2))
        except ValueError:
            pass
    return None


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
    transient = 0  # timeouts and 5xx, two attempts as before
    throttled = 0  # 429s, waited out on the provider's own schedule
    slept = 0.0
    while transient < 2:
        try:
            response = httpx.post(
                url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS
            )
        except httpx.TimeoutException as e:
            last = e
            transient += 1
            continue
        except httpx.RequestError as e:
            raise LLMError(f"could not reach {provider} at {url}: {e}") from e
        if response.status_code == 429:
            throttled += 1
            wait = _retry_wait(response)
            pause = (2.0 if wait is None else wait) + _RETRY_PAD_SECONDS
            if throttled >= RATE_LIMIT_ATTEMPTS or slept + pause > RATE_LIMIT_BUDGET_SECONDS:
                raise RateLimitError(
                    f"{provider} is rate-limited after {throttled} attempt(s) "
                    f"and {slept:.1f}s of waiting: {response.text}",
                    retry_after=wait,
                )
            log.warning(
                "%s rate-limited (attempt %d), waiting %.2fs", provider, throttled, pause
            )
            time.sleep(pause)
            slept += pause
            continue
        if response.status_code >= 500:
            last = LLMError(f"{provider} returned {response.status_code}: {response.text}")
            transient += 1
            continue
        if response.status_code >= 400:
            raise LLMError(f"{provider} returned {response.status_code}: {response.text}")
        return _extract(provider, response.json())

    raise LLMError(f"{provider} failed after 2 attempts: {last}") from last
