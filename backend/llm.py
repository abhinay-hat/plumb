"""Plain-HTTP LLM access. Built-in providers plus any OpenAI-compatible endpoint."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx
from dotenv import load_dotenv

from backend import router
from backend.endpoint_guard import EndpointError, ValidatedEndpoint, inspect_endpoint
from backend.plan_schema import PLAN_JSON_SCHEMA
from backend.providers import (
    BUILTIN_PROVIDERS,
    PROVIDERS,
    find_preset,
    models_for,
    ollama_base,
    preset_url,
    visible_presets,
)

# Docker Compose reads .env on its own, but `make dev`, `make demo`, and
# `make eval` run the interpreter directly — without this they saw neither
# GROQ_API_KEY nor the PLUMB_MODEL pin and fell back to a default model that
# 404s. Load it here because this module is the only reader of those vars.
# override=False so an exported shell value still wins over the file.
load_dotenv(override=False)

log = logging.getLogger("plumb.llm")

TIMEOUT_SECONDS = 30.0
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq withdrew llama-3.3-70b-versatile from the free plan on 16 August 2026.
GROQ_MODEL = "openai/gpt-oss-20b"
OLLAMA_URL = f"{ollama_base()}/api/chat"
OLLAMA_MODEL = "qwen2.5-coder:7b-instruct"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/free"
# OpenRouter attributes calls with these, and some upstreams reject a request
# that carries neither.
OPENROUTER_HEADERS = {
    "HTTP-Referer": os.environ.get("PLUMB_PUBLIC_URL", "http://localhost:5173"),
    "X-Title": "plumb",
}

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


class ProviderUnavailableError(LLMError):
    """The model itself is gone, not the request wrong.

    A `:free` model on OpenRouter disappears when its upstream pulls it, and
    answers 404 or 502 thereafter. That is a "pick another model" problem, and
    telling the user their data cannot answer the question would be a lie in
    exactly the way a rate limit is.
    """


class ProviderAuthError(LLMError):
    """The key is refused or the account cannot pay. Retrying changes nothing.

    Separate from a rate limit, which clears on its own. A 401/402/403 clears
    when somebody edits a billing page, so the router parks this candidate for
    a long time instead of spending a call on it every turn.
    """


class RateLimitError(LLMError):
    """The provider was busy. The prompt was fine; nothing was answered.

    Separate from LLMError so the layers above can tell "the model was busy"
    apart from "the model said something unusable" — the second is a refusal,
    the first is not.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class BoundEndpoint:
    """The provider a single turn (or session) will call.

    Custom keys live here, not in os.environ, so two tabs can point at
    different gateways and a key typed into a browser never becomes
    process-wide state.
    """

    provider: str
    model: str
    url: str | None = None
    key: str | None = None
    host: str | None = None
    ip: str | None = None
    preset_id: str | None = None


_bound: ContextVar[BoundEndpoint | None] = ContextVar("plumb_llm_bound", default=None)


def bind(endpoint: BoundEndpoint | None) -> Token:
    return _bound.set(endpoint)


def reset(token: Token) -> None:
    _bound.reset(token)


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


def current_provider() -> str:
    bound = _bound.get()
    if bound is not None:
        return bound.provider
    return os.environ.get("PLUMB_PROVIDER", "groq").strip().lower() or "groq"


def current_model() -> str:
    bound = _bound.get()
    if bound is not None and bound.model:
        return bound.model
    provider = current_provider()
    if provider == "auto":
        # Before the first call there is no answer yet; after one, the winning
        # candidate is bound and the branch above already returned its name.
        return os.environ.get("PLUMB_MODEL", "auto")
    if provider == "ollama":
        return os.environ.get("PLUMB_MODEL", OLLAMA_MODEL)
    if provider == "openrouter":
        return os.environ.get("PLUMB_MODEL", OPENROUTER_MODEL)
    if provider == "custom":
        return os.environ.get("PLUMB_CUSTOM_MODEL", os.environ.get("PLUMB_MODEL", "")).strip()
    return os.environ.get("PLUMB_MODEL", GROQ_MODEL)


def current_host() -> str | None:
    bound = _bound.get()
    if bound is not None:
        return bound.host
    if current_provider() == "custom":
        return env_pin().host
    return None


def configure(provider: str, model: str) -> None:
    """Pin the process to a built-in provider + model the next complete() will use.

    Custom endpoints are per session — they must not land in os.environ.
    """
    chosen = provider.strip().lower()
    if chosen not in BUILTIN_PROVIDERS:
        raise ValueError(
            f"unknown provider {provider!r}; use "
            + ", ".join(repr(name) for name in BUILTIN_PROVIDERS)
        )
    name = model.strip()
    if not name:
        raise ValueError("model is required")
    os.environ["PLUMB_PROVIDER"] = chosen
    os.environ["PLUMB_MODEL"] = name


def env_pin() -> BoundEndpoint:
    """The process-wide pin from the environment. Used when no session override exists."""
    provider = os.environ.get("PLUMB_PROVIDER", "groq").strip().lower() or "groq"
    if provider == "auto":
        return BoundEndpoint("auto", os.environ.get("PLUMB_MODEL", "auto"))
    if provider == "custom":
        url = os.environ.get("PLUMB_CUSTOM_URL", "").strip()
        model = os.environ.get("PLUMB_CUSTOM_MODEL", os.environ.get("PLUMB_MODEL", "")).strip()
        key = os.environ.get("PLUMB_CUSTOM_KEY") or None
        host = None
        ip = None
        if url:
            try:
                inspected = inspect_endpoint(url)
                url, host, ip = inspected.url, inspected.host, inspected.ip
            except EndpointError:
                parsed = urlparse(url)
                host = parsed.hostname
        return BoundEndpoint("custom", model, url=url or None, key=key, host=host, ip=ip)
    if provider == "ollama":
        model = os.environ.get("PLUMB_MODEL", OLLAMA_MODEL)
    elif provider == "openrouter":
        model = os.environ.get("PLUMB_MODEL", OPENROUTER_MODEL)
    else:
        model = os.environ.get("PLUMB_MODEL", GROQ_MODEL)
    return BoundEndpoint(provider, model)


def session_endpoint(session: object) -> BoundEndpoint:
    provider = getattr(session, "provider", "") or ""
    if not provider:
        return env_pin()
    return BoundEndpoint(
        provider=provider,
        model=getattr(session, "model", "") or "",
        url=getattr(session, "endpoint_url", None),
        key=getattr(session, "endpoint_key", None),
        host=getattr(session, "endpoint_host", None),
        ip=getattr(session, "endpoint_ip", None),
        preset_id=getattr(session, "preset_id", None),
    )


def catalog(session: object | None = None) -> dict[str, object]:
    """What the nav select should render, plus the pin currently in effect."""
    pin = session_endpoint(session) if session is not None else env_pin()
    selected = pin.preset_id or pin.provider
    providers: list[dict[str, object]] = []
    for item in PROVIDERS:
        if item["id"] == "auto":
            providers.append(
                {
                    "id": "auto",
                    "label": item["label"],
                    "models": [{"id": "auto", "label": "Best available"}],
                    "kind": "auto",
                }
            )
            continue
        if item["id"] == "custom":
            models: list[dict[str, str]] = []
            if pin.provider == "custom" and pin.model and not pin.preset_id:
                models = [{"id": pin.model, "label": pin.model}]
            providers.append(
                {"id": "custom", "label": "Custom", "models": models, "kind": "custom"}
            )
            continue
        models = models_for(item["id"])
        ids = {row["id"] for row in models}
        if item["id"] == pin.provider and pin.model and pin.model not in ids:
            models.insert(0, {"id": pin.model, "label": pin.model})
        providers.append({"id": item["id"], "label": item["label"], "models": models})
    presets: list[dict[str, object]] = []
    for item in visible_presets():
        models = models_for(item["id"], fallback=tuple(item["models"]))
        providers.append(
            {"id": item["id"], "label": item["label"], "models": models, "kind": "preset"}
        )
        presets.append(
            {
                "id": item["id"],
                "label": item["label"],
                "url": preset_url(item),
                "models": models,
            }
        )
    return {
        "provider": selected,
        "model": pin.model,
        "host": pin.host,
        "providers": providers,
        "presets": presets,
    }


def _is_gpt_oss(model: str) -> bool:
    return "gpt-oss" in model.lower()


def _system_for_model(model: str, system: str) -> str:
    """gpt-oss expects a reasoning level in the system message."""
    if _is_gpt_oss(model):
        return f"Reasoning: low\n\n{system}"
    return system


def _response_format(model: str, provider: str, json_mode: bool) -> dict | None:
    if not json_mode:
        return None
    if provider in ("groq", "openrouter") and _is_gpt_oss(model):
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "plan",
                "strict": True,
                "schema": PLAN_JSON_SCHEMA,
            },
        }
    return {"type": "json_object"}


def _openai_payload(
    model: str, system: str, user: str, json_mode: bool, provider: str
) -> dict:
    payload: dict = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _system_for_model(model, system)},
            {"role": "user", "content": user},
        ],
    }
    fmt = _response_format(model, provider, json_mode)
    if fmt is not None:
        payload["response_format"] = fmt
    return payload


def _groq_request(system: str, user: str, json_mode: bool) -> tuple[str, dict, dict]:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError(
            "GROQ_API_KEY is not set. Export it, or set PLUMB_PROVIDER=ollama "
            "to use a local model."
        )
    return GROQ_URL, {"Authorization": f"Bearer {key}"}, _openai_payload(
        current_model(), system, user, json_mode, "groq"
    )


def _openrouter_request(system: str, user: str, json_mode: bool) -> tuple[str, dict, dict]:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError(
            "OPENROUTER_API_KEY is not set. Export it, or set PLUMB_PROVIDER to "
            "groq or ollama."
        )
    headers = {"Authorization": f"Bearer {key}", **OPENROUTER_HEADERS}
    return OPENROUTER_URL, headers, _openai_payload(
        current_model(), system, user, json_mode, "openrouter"
    )


def _ollama_request(system: str, user: str, json_mode: bool) -> tuple[str, dict, dict]:
    payload: dict = {
        "model": current_model(),
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


def _custom_request(
    system: str, user: str, json_mode: bool
) -> tuple[str, dict, dict, str, str]:
    """Return url, headers, payload, pinned ip, host."""
    bound = _bound.get() or env_pin()
    url = (bound.url or "").strip()
    if not url:
        raise LLMError(
            "PLUMB_CUSTOM_URL is not set. Paste an OpenAI-compatible chat "
            "completions URL, or pick Groq, OpenRouter, or Ollama."
        )
    model = bound.model or current_model()
    if not model:
        raise LLMError("a model name is required for a custom endpoint")
    inspected_url = url
    ip = bound.ip
    host = bound.host
    if not ip or not host:
        inspected = inspect_endpoint(url)
        inspected_url, ip, host = inspected.url, inspected.ip, inspected.host
    headers: dict[str, str] = {}
    if bound.key:
        headers["Authorization"] = f"Bearer {bound.key}"
    payload = _openai_payload(model, system, user, json_mode, "custom")
    return inspected_url, headers, payload, ip, host


def _pinned_post(
    url: str,
    headers: dict,
    payload: dict,
    *,
    ip: str,
    host: str,
) -> httpx.Response:
    parsed = urlparse(url)
    ip_literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_literal}:{parsed.port}" if parsed.port else ip_literal
    pinned = urlunparse(parsed._replace(netloc=netloc))
    host_header = f"{host}:{parsed.port}" if parsed.port else host
    # Through a Client, not httpx.post: the module-level helper takes no
    # `extensions`, so this raised TypeError before a single byte was sent —
    # every preset and every custom endpoint, and no test caught it because
    # they all monkeypatch httpx.post and never see the real signature.
    # sni_hostname is what makes TLS validate against the name while the
    # connection goes to the address already resolved and checked.
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        return client.post(
            pinned,
            headers={**headers, "Host": host_header},
            json=payload,
            extensions={"sni_hostname": host},
        )


def _scrub(message: str, key: str | None) -> str:
    if key:
        message = message.replace(key, "***")
    return message


def _extract(provider: str, body: dict) -> str:
    if provider == "ollama":
        content = body.get("message", {}).get("content")
    else:
        choices = body.get("choices") or []
        if not choices:
            raise LLMError(f"{provider} returned no choices: {body}")
        message = choices[0].get("message") or {}
        parsed = message.get("parsed")
        if isinstance(parsed, dict):
            return json.dumps(parsed)
        content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError(f"provider returned an empty completion: {body}")
    return content


def _complete_once(
    system: str, user: str, json_mode: bool = True, wait_on_limit: bool = True
) -> str:
    """Send one prompt to the currently bound provider and return the raw text.

    `wait_on_limit=False` turns a 429 into an immediate raise. Waiting out a
    rate limit only makes sense when this provider is the only one there is;
    with a pool behind it, sleeping here would spend the user's patience on a
    queue while an idle provider sits unused.
    """
    provider = current_provider()
    pinned_ip: str | None = None
    pinned_host: str | None = None
    key: str | None = None
    if provider == "groq":
        url, headers, payload = _groq_request(system, user, json_mode)
    elif provider == "openrouter":
        url, headers, payload = _openrouter_request(system, user, json_mode)
    elif provider == "ollama":
        url, headers, payload = _ollama_request(system, user, json_mode)
    elif provider == "custom":
        bound = _bound.get() or env_pin()
        key = bound.key
        url, headers, payload, pinned_ip, pinned_host = _custom_request(
            system, user, json_mode
        )
    else:
        raise LLMError(
            f"unknown PLUMB_PROVIDER {provider!r}; use 'groq', 'openrouter', "
            "'ollama', or 'custom'"
        )

    display = pinned_host or url
    last: Exception | None = None
    transient = 0  # timeouts and 5xx, two attempts as before
    throttled = 0  # 429s, waited out on the provider's own schedule
    slept = 0.0
    while transient < 2:
        try:
            if pinned_ip and pinned_host:
                response = _pinned_post(
                    url, headers, payload, ip=pinned_ip, host=pinned_host
                )
            else:
                response = httpx.post(
                    url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS
                )
        except httpx.TimeoutException as e:
            last = e
            transient += 1
            continue
        except httpx.RequestError as e:
            raise LLMError(
                _scrub(f"could not reach {provider} at {display}: {e}", key)
            ) from e
        if response.status_code == 429:
            throttled += 1
            wait = _retry_wait(response)
            pause = (2.0 if wait is None else wait) + _RETRY_PAD_SECONDS
            if (
                not wait_on_limit
                or throttled >= RATE_LIMIT_ATTEMPTS
                or slept + pause > RATE_LIMIT_BUDGET_SECONDS
            ):
                raise RateLimitError(
                    _scrub(
                        f"{provider} is rate-limited after {throttled} attempt(s) "
                        f"and {slept:.1f}s of waiting: {response.text}",
                        key,
                    ),
                    retry_after=wait,
                )
            log.warning(
                "%s rate-limited (attempt %d), waiting %.2fs", provider, throttled, pause
            )
            time.sleep(pause)
            slept += pause
            continue
        # A :free model on OpenRouter answers 404 or 502 once its upstream
        # pulls it. That is "pick another model", not a data refusal, and
        # retrying a vanished model just spends the wait.
        if provider == "openrouter" and response.status_code in (404, 502):
            raise ProviderUnavailableError(
                f"{payload.get('model', current_model())} is unavailable on "
                "OpenRouter. Pick another model."
            )
        if response.status_code >= 500:
            last = LLMError(
                _scrub(
                    f"{provider} returned {response.status_code}: {response.text}",
                    key,
                )
            )
            transient += 1
            continue
        if response.status_code in (401, 402, 403):
            raise ProviderAuthError(
                _scrub(
                    f"{provider} returned {response.status_code}: {response.text}",
                    key,
                )
            )
        if response.status_code >= 400:
            raise LLMError(
                _scrub(
                    f"{provider} returned {response.status_code}: {response.text}",
                    key,
                )
            )
        try:
            body = response.json()
        except ValueError as e:
            raise LLMError(
                f"{provider} did not return JSON; this endpoint is not OpenAI-compatible"
            ) from e
        return _extract(provider, body)

    raise LLMError(
        _scrub(f"{provider} failed after 2 attempts: {last}", key)
    ) from last


def _pinned_candidate() -> router.Candidate | None:
    """The bound endpoint as a routing candidate, so an explicit pick goes first."""
    bound = _bound.get() or env_pin()
    if not bound.model or bound.provider == "auto":
        return None
    return router.Candidate(
        provider=bound.provider,
        model=bound.model,
        url=bound.url,
        key=bound.key,
        preset_id=bound.preset_id,
    )


def complete(system: str, user: str, json_mode: bool = True) -> str:
    """Answer this prompt using whichever free model can, right now.

    With routing off this is one call to one provider, exactly as before. With
    it on, a rate limit or a withdrawn model is not the end of the turn: the
    provider is marked as cooling and the next candidate is tried. Only when
    every candidate has refused does the error reach the user — and then it is
    the truthful one, because by then it really is unanswerable.
    """
    if not router.routing_enabled():
        return _complete_once(system, user, json_mode)

    candidates = router.order(_pinned_candidate())
    if not candidates:
        raise LLMError(
            "no provider is configured; set GROQ_API_KEY, OPENROUTER_API_KEY, "
            "run Ollama, or configure a preset"
        )

    last: Exception | None = None
    for candidate in candidates:
        health = router.health_for(candidate.name)
        token = bind(
            BoundEndpoint(
                candidate.provider,
                candidate.model,
                url=candidate.url,
                key=candidate.key,
                preset_id=candidate.preset_id,
            )
        )
        started = time.perf_counter()
        answered = False
        try:
            answer = _complete_once(system, user, json_mode, wait_on_limit=False)
            answered = True
        except RateLimitError as e:
            last = e
            health.record_failure(e.retry_after)
            log.warning("%s is rate-limited, trying the next model", candidate.name)
            continue
        except ProviderAuthError as e:
            last = e
            health.record_failure(router.AUTH_COOLDOWN_SECONDS)
            log.warning(
                "%s refused the key or the account cannot pay; parking it", candidate.name
            )
            continue
        except ProviderUnavailableError as e:
            last = e
            health.record_failure(None)
            log.warning("%s is unavailable, trying the next model", candidate.name)
            continue
        except LLMError as e:
            last = e
            health.record_failure(None)
            log.warning("%s failed (%s), trying the next model", candidate.name, e)
            continue
        finally:
            # The winner stays bound on purpose: the caller reads
            # current_model() to report which model actually answered.
            if not answered:
                reset(token)
        health.record_success((time.perf_counter() - started) * 1000)
        return answer

    names = ", ".join(c.name for c in candidates)
    if isinstance(last, RateLimitError):
        raise RateLimitError(
            f"every configured model is rate-limited right now ({names})",
            retry_after=last.retry_after,
        ) from last
    raise LLMError(f"no configured model could answer ({names}): {last}") from last


def probe(url: str, key: str | None, model: str) -> ValidatedEndpoint:
    """Send one trivial completion and raise if the endpoint cannot answer.

    A user must never discover a bad URL halfway through their first question.
    """
    name = model.strip()
    if not name:
        raise LLMError("a model name is required for a custom endpoint")
    inspected = inspect_endpoint(url)
    payload = _openai_payload(name, "", "reply with ok", json_mode=False, provider="custom")
    headers: dict[str, str] = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = _pinned_post(
            inspected.url, headers, payload, ip=inspected.ip, host=inspected.host
        )
    except httpx.TimeoutException as e:
        raise LLMError(f"{inspected.host} did not respond in time") from e
    except httpx.RequestError as e:
        raise LLMError(
            _scrub(f"could not reach {inspected.host}: {e}", key)
        ) from e
    if response.status_code in (401, 403):
        raise LLMError("wrong API key")
    if response.status_code == 404:
        raise LLMError(f"model {name!r} was not found on {inspected.host}")
    if response.status_code == 429:
        raise RateLimitError(
            f"{inspected.host} is rate-limited",
            retry_after=_retry_wait(response),
        )
    if response.status_code >= 400:
        raise LLMError(
            _scrub(
                f"{inspected.host} returned {response.status_code}: {response.text}",
                key,
            )
        )
    try:
        body = response.json()
    except ValueError as e:
        raise LLMError(
            f"{inspected.host} did not return JSON; this endpoint is not OpenAI-compatible"
        ) from e
    try:
        _extract("custom", body)
    except LLMError as e:
        raise LLMError(
            f"{inspected.host} is not OpenAI-compatible: {e}"
        ) from e
    return inspected


def apply_session_provider(
    session: object,
    provider: str,
    model: str,
    *,
    url: str | None = None,
    key: str | None = None,
) -> BoundEndpoint:
    """Validate, probe custom endpoints, then write onto the session.

    On failure the session is left as it was, so a switch never strands a
    conversation without a working model.
    """
    chosen = provider.strip().lower()
    name = model.strip()
    if not name:
        raise ValueError("model is required")

    previous = BoundEndpoint(
        provider=getattr(session, "provider", "") or "",
        model=getattr(session, "model", "") or "",
        url=getattr(session, "endpoint_url", None),
        key=getattr(session, "endpoint_key", None),
        host=getattr(session, "endpoint_host", None),
        ip=getattr(session, "endpoint_ip", None),
        preset_id=getattr(session, "preset_id", None),
    )

    def restore() -> None:
        _write_session(session, previous)

    try:
        if chosen in BUILTIN_PROVIDERS:
            pin = BoundEndpoint(chosen, name)
            _write_session(session, pin)
            return pin

        preset = find_preset(chosen)
        if preset is not None:
            if not os.environ.get(preset["key_env"], "").strip():
                raise ValueError(
                    f"{preset['label']} is not configured; set {preset['key_env']}"
                )
            inspected = inspect_endpoint(preset_url(preset))
            preset_key = os.environ.get(preset["key_env"]) or None
            probe(inspected.url, preset_key, name)
            pin = BoundEndpoint(
                "custom",
                name,
                url=inspected.url,
                key=preset_key,
                host=inspected.host,
                ip=inspected.ip,
                preset_id=preset["id"],
            )
            _write_session(session, pin)
            return pin

        if chosen != "custom":
            raise ValueError(
                f"unknown provider {provider!r}; use 'groq', 'openrouter', "
                "'ollama', 'custom', or a configured preset"
            )

        target = (url or "").strip() or previous.url or ""
        if not target:
            raise ValueError("url is required for a custom endpoint")
        secret = previous.key if key is None else (key or None)
        inspected = inspect_endpoint(target)
        probe(inspected.url, secret, name)
        pin = BoundEndpoint(
            "custom",
            name,
            url=inspected.url,
            key=secret,
            host=inspected.host,
            ip=inspected.ip,
        )
        _write_session(session, pin)
        return pin
    except Exception:
        restore()
        raise


def _write_session(session: object, pin: BoundEndpoint) -> None:
    session.provider = pin.provider
    session.model = pin.model
    session.endpoint_url = pin.url
    session.endpoint_key = pin.key
    session.endpoint_host = pin.host
    session.endpoint_ip = pin.ip
    session.preset_id = pin.preset_id
