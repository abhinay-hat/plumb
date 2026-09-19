"""Named providers and presets. Transport lives in llm.py; this is the roster.

Every preset is an OpenAI-compatible URL. None of them needs its own request
function — they are `custom` with the URL pre-filled. A preset whose key env
var is unset does not appear in the picker. A preset URL still goes through
`validate_endpoint`; if one would fail the guard, that is a bug in the preset.

The roster is **discovered, not declared**: `models_for` asks the provider's
own `/v1/models` and returns what the key can actually call today. A hand-kept
list is wrong the moment a provider retires a model — which is exactly how
`llama-3.3-70b-versatile` became a 404 in the picker. The `FALLBACK_MODELS`
tuples below are only what the picker shows when discovery cannot run: no key,
no network, or a provider that answers with something unparseable.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger("plumb.providers")

# Discovery is a picker convenience, not the answer path — a slow provider must
# never hold the UI. Short timeout, cached, and a failure just falls back.
DISCOVERY_TIMEOUT_SECONDS = 4.0
DISCOVERY_TTL_SECONDS = 300.0

PROVIDERS: tuple[dict[str, str], ...] = (
    {"id": "groq", "label": "Groq"},
    {"id": "openrouter", "label": "OpenRouter"},
    {"id": "ollama", "label": "Ollama"},
    {"id": "custom", "label": "Custom"},
)


def ollama_base() -> str:
    """Where Ollama listens. Not everyone runs it on this machine."""
    return os.environ.get("PLUMB_OLLAMA_URL", "http://localhost:11434").rstrip("/")


# Shown only when discovery cannot run. Groq withdrew llama-3.3-70b-versatile
# and llama-3.1-8b-instant from the free plan on 16 August 2026, so these are
# the ids most likely to still work offline — not a curated roster.
FALLBACK_MODELS: dict[str, tuple[dict[str, str], ...]] = {
    "groq": (
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},
    ),
    "openrouter": (
        {"id": "openrouter/free", "label": "Free router"},
    ),
    "ollama": (
        {"id": "qwen2.5-coder:7b-instruct", "label": "Qwen2.5 Coder 7B"},
    ),
}

# The provider ids the process pin accepts. `custom` is deliberately absent:
# a custom endpoint is per session so its key never becomes process state.
BUILTIN_PROVIDERS: tuple[str, ...] = ("groq", "openrouter", "ollama")

# Cerebras, Together, and SambaNova ended their free tiers in mid-2026.
# Presetting a dead free tier just produces a confusing 402.
PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "google",
        "label": "Google AI Studio",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GOOGLE_API_KEY",
        "models": (
            {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        ),
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "key_env": "MISTRAL_API_KEY",
        "models": (
            {"id": "mistral-small-latest", "label": "Mistral Small"},
        ),
    },
    {
        "id": "nvidia",
        "label": "NVIDIA NIM",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key_env": "NVIDIA_API_KEY",
        "models": (
            {"id": "meta/llama-3.1-8b-instruct", "label": "Llama 3.1 8B"},
            {"id": "google/gemma-2-9b-it", "label": "Gemma 2 9B"},
        ),
    },
    {
        "id": "cloudflare",
        "label": "Cloudflare Workers AI",
        "url": (
            "https://api.cloudflare.com/client/v4/accounts/{account_id}"
            "/ai/v1/chat/completions"
        ),
        "key_env": "CF_API_TOKEN",
        "account_env": "CF_ACCOUNT_ID",
        "models": (
            {"id": "@cf/meta/llama-3.1-8b-instruct", "label": "Llama 3.1 8B"},
        ),
    },
    {
        "id": "cohere",
        "label": "Cohere",
        "url": "https://api.cohere.ai/compatibility/v1/chat/completions",
        "key_env": "COHERE_API_KEY",
        "models": (
            {"id": "command-a-plus-05-2026", "label": "Command A Plus"},
        ),
    },
)


def _models_url(chat_url: str) -> str:
    """The `/models` sibling of an OpenAI-compatible `/chat/completions` URL."""
    return chat_url.replace("/chat/completions", "/models")


def _discovery_target(provider_id: str) -> tuple[str, str | None] | None:
    """(models URL, key env var) for a built-in provider, or None if it has none."""
    if provider_id == "groq":
        return "https://api.groq.com/openai/v1/models", "GROQ_API_KEY"
    if provider_id == "openrouter":
        # Public: OpenRouter lists its catalogue without a key, which is what
        # makes the free-tier picker useful before anyone has signed up.
        return "https://openrouter.ai/api/v1/models", None
    if provider_id == "ollama":
        return f"{ollama_base()}/v1/models", None
    preset = find_preset(provider_id)
    if preset is not None:
        return _models_url(preset_url(preset)), str(preset["key_env"])
    return None


def _label_for(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "").strip()
    return name or str(row["id"])


def _strings(*candidates: Any) -> list[str]:
    for value in candidates:
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    return []


def _is_free(row: dict[str, Any]) -> bool:
    pricing = row.get("pricing")
    if not isinstance(pricing, dict):
        return False
    try:
        return float(pricing.get("prompt", 1)) == 0.0
    except (TypeError, ValueError):
        return False


# Groq publishes speech, guard, and safety models beside chat planners.
# They pass modality/JSON heuristics but cannot run plumb's planner.
_GROQ_EXCLUDE_FRAGMENTS = (
    "whisper",
    "orpheus",
    "prompt-guard",
    "safeguard",
)


def _usable(provider_id: str, row: dict[str, Any]) -> bool:
    """Whether plumb can actually plan with this model.

    Every filter reads a field the provider itself publishes — nothing here is
    a curated opinion about a named model:

    * text out. Groq's roster includes whisper (audio in) and orpheus (audio
      out); both 404 or return audio on /chat/completions.
    * JSON. plumb sends `response_format`, and a model without it answers prose
      the planner cannot parse. Groq says so in `supported_features`,
      OpenRouter in `supported_parameters`. A provider that publishes neither
      is assumed capable rather than hidden — the request is what proves it.
    * price, on OpenRouter only. Its 447-model catalogue is mostly paid, and
      an unaffordable list is not a picker. Groq bills the free plan by rate
      limit rather than a zero price, so the same filter there empties it.
    """
    architecture = row.get("architecture")
    modalities = _strings(
        row.get("output_modalities"),
        architecture.get("output_modalities") if isinstance(architecture, dict) else None,
    )
    if modalities and "text" not in modalities:
        return False
    published = _strings(row.get("supported_parameters"), row.get("supported_features"))
    if published and not ({"response_format", "structured_outputs", "json_mode"} & set(published)):
        return False
    if provider_id == "openrouter" and not _is_free(row):
        return False
    return True


def _parse_models(provider_id: str, body: Any) -> list[dict[str, str]]:
    """OpenAI `{"data": [{"id": ...}]}`. Anything else yields nothing."""
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        if provider_id == "groq" and any(
            part in model_id.lower() for part in _GROQ_EXCLUDE_FRAGMENTS
        ):
            continue
        if not _usable(provider_id, row):
            continue
        seen.add(model_id)
        found.append({"id": model_id, "label": _label_for(row)})
    found.sort(key=lambda row: row["label"].lower())
    return found


_discovered: dict[str, tuple[float, tuple[dict[str, str], ...]]] = {}


def discovery_enabled() -> bool:
    return os.environ.get("PLUMB_LIVE_MODELS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def forget_discovered() -> None:
    """Drop the discovery cache. For tests and for a key changing mid-process."""
    _discovered.clear()


def models_for(
    provider_id: str,
    *,
    fallback: tuple[dict[str, str], ...] | None = None,
    now: float | None = None,
) -> list[dict[str, str]]:
    """What `provider_id` can actually run right now, falling back to a static list."""
    offline = list(FALLBACK_MODELS.get(provider_id, ()) if fallback is None else fallback)
    if not discovery_enabled():
        return offline
    stamp = time.monotonic() if now is None else now
    cached = _discovered.get(provider_id)
    if cached is not None and stamp - cached[0] < DISCOVERY_TTL_SECONDS:
        return list(cached[1])
    target = _discovery_target(provider_id)
    if target is None:
        return offline
    url, key_env = target
    headers = {}
    if key_env:
        key = os.environ.get(key_env, "").strip()
        if not key:
            return offline
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = httpx.get(url, headers=headers, timeout=DISCOVERY_TIMEOUT_SECONDS)
        response.raise_for_status()
        found = _parse_models(provider_id, response.json())
    except Exception as e:  # network, auth, HTML error page — all the same here
        log.info("model discovery failed for %s: %s", provider_id, e)
        found = []
    if not found:
        return offline
    _discovered[provider_id] = (stamp, tuple(found))
    return found


def find_preset(preset_id: str) -> dict[str, Any] | None:
    for item in PRESETS:
        if item["id"] == preset_id:
            return item
    return None


def preset_url(preset: dict[str, Any]) -> str:
    url = str(preset["url"])
    account_env = preset.get("account_env")
    if account_env:
        account = os.environ.get(account_env, "").strip()
        if not account:
            raise ValueError(
                f"{account_env} is not set; it is required for {preset['label']}"
            )
        url = url.replace("{account_id}", account)
    return url


def visible_presets() -> list[dict[str, Any]]:
    """Presets whose key (and account id, when needed) is present in the environment."""
    visible: list[dict[str, Any]] = []
    for item in PRESETS:
        if not os.environ.get(item["key_env"], "").strip():
            continue
        account_env = item.get("account_env")
        if account_env and not os.environ.get(account_env, "").strip():
            continue
        visible.append(item)
    return visible
