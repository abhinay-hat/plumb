"""Pick which free model answers this turn, and move on when one is busy.

Every free tier is rate-limited, and the limits are low enough to hit inside a
single demo: Groq allows 30 requests a minute, OpenRouter's `:free` models 20 a
minute and 50 a day, Gemini Flash 15 a minute. One provider is therefore not a
configuration — it is a single point of failure, and the failure surfaces to the
user as "this question was never answered".

So plumb treats every configured provider as one candidate in a pool. A 429 is
not an error to report, it is a signal to try the next candidate and a note that
this one is cooling down. The user sees an answer and which model produced it.

The ordering is learned, not declared. Nothing here ranks by model name. The
signals are what the provider itself publishes (`context_length`, whether it
advertises JSON output) and what plumb has measured (how fast this candidate has
answered, whether it recently failed, when its cooldown expires). A candidate
that is fast and reliable today outranks one that was fast last month.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from backend.providers import (
    BUILTIN_PROVIDERS,
    models_for,
    ollama_base,
    preset_url,
    strict_json,
    visible_presets,
)

log = logging.getLogger("plumb.router")

# How many models to take from any one provider. The pool exists to survive a
# provider going quiet; three models behind the same rate limit does not help.
MODELS_PER_PROVIDER = 2
# A candidate with no measurement yet is neither trusted nor punished — it sorts
# as though it answered in this long, so a proven-fast candidate goes first and
# an unknown one still gets tried before anything that has actually failed.
UNMEASURED_MS = 20_000.0
# What a provider gets for a 429 that arrives without a Retry-After header.
DEFAULT_COOLDOWN_SECONDS = 60.0
# A refused key or an unpaid account does not heal on its own, so retrying it
# every minute only spends a call per turn to learn the same thing.
AUTH_COOLDOWN_SECONDS = 3600.0


@dataclass(frozen=True)
class Candidate:
    """One (provider, model) pair the router may send this turn to."""

    provider: str  # what llm.complete dispatches on: groq/openrouter/ollama/custom
    model: str
    url: str | None = None
    key: str | None = None
    preset_id: str | None = None
    context: int = 0
    json_native: bool = False

    @property
    def strict(self) -> bool:
        """Whether the reply can be constrained to the Plan schema outright."""
        return strict_json(self.preset_id or self.provider, self.model)

    @property
    def name(self) -> str:
        return f"{self.preset_id or self.provider}:{self.model}"


@dataclass
class Health:
    """What plumb has observed about one candidate, this process."""

    ewma_ms: float | None = None
    failures: int = 0
    successes: int = 0
    cooling_until: float = 0.0

    def record_success(self, elapsed_ms: float) -> None:
        # Exponential moving average: recent turns matter more than the first
        # one, which is often slow because the provider was cold.
        self.ewma_ms = (
            elapsed_ms if self.ewma_ms is None else (self.ewma_ms * 0.7 + elapsed_ms * 0.3)
        )
        self.successes += 1
        self.failures = 0
        self.cooling_until = 0.0

    def record_failure(self, cooldown: float | None) -> None:
        self.failures += 1
        wait = DEFAULT_COOLDOWN_SECONDS if cooldown is None else cooldown
        self.cooling_until = time.monotonic() + wait

    def cooling(self, now: float) -> bool:
        return now < self.cooling_until


_health: dict[str, Health] = {}


def health_for(name: str) -> Health:
    return _health.setdefault(name, Health())


def reset_health() -> None:
    """Forget every measurement. For tests, and for a key that just changed."""
    _health.clear()


def routing_enabled() -> bool:
    """Routing is on unless a caller pinned one provider and meant it.

    `PLUMB_PROVIDER=auto` asks for the pool outright. Any other pin still gets
    failover — being pinned to Groq should not mean a Groq rate limit ends the
    turn when a Gemini key is sitting right there — unless PLUMB_ROUTE says no.
    """
    setting = os.environ.get("PLUMB_ROUTE", "").strip().lower()
    if setting in {"0", "false", "no", "off"}:
        return False
    if setting in {"1", "true", "yes", "on"}:
        return True
    return os.environ.get("PLUMB_PROVIDER", "").strip().lower() == "auto"


def _entries(provider_id: str, fallback=None) -> list[dict[str, str]]:
    """The best few models from one provider, not the first few alphabetically.

    `models_for` returns the roster sorted by label so the picker reads
    sensibly. Taking the head of that list to build the pool meant
    `openai/gpt-oss-20b` — the one Groq model whose reply can be constrained to
    the Plan schema — lost its slot to `allam-2-7b`, and every turn ran on a
    model that answers prose often enough to break the parse.
    """
    rows = models_for(provider_id, fallback=fallback)
    rows.sort(
        key=lambda row: (
            not strict_json(provider_id, row["id"]),
            row.get("json_native") != "1",
            -int(row.get("context") or 0),
        )
    )
    return rows[:MODELS_PER_PROVIDER]


def _as_candidate(provider: str, row: dict[str, str], **extra) -> Candidate:
    return Candidate(
        provider=provider,
        model=row["id"],
        context=int(row.get("context") or 0),
        json_native=row.get("json_native") == "1",
        **extra,
    )


def pool() -> list[Candidate]:
    """Every (provider, model) this process is actually able to call right now.

    A provider with no key contributes nothing — it would only produce a 401 on
    the way to the answer.
    """
    found: list[Candidate] = []

    if os.environ.get("GROQ_API_KEY", "").strip():
        found += [_as_candidate("groq", row) for row in _entries("groq")]
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        found += [_as_candidate("openrouter", row) for row in _entries("openrouter")]
    # Ollama needs no key; discovery already answers empty when it is not running.
    if os.environ.get("PLUMB_OLLAMA_URL") or _entries("ollama"):
        found += [_as_candidate("ollama", row) for row in _entries("ollama")]

    for preset in visible_presets():
        key = os.environ.get(preset["key_env"]) or None
        try:
            url = preset_url(preset)
        except ValueError as e:  # a preset missing its account id
            log.info("preset %s is not usable: %s", preset["id"], e)
            continue
        rows = _entries(preset["id"], fallback=tuple(preset["models"]))
        found += [
            _as_candidate("custom", row, url=url, key=key, preset_id=preset["id"])
            for row in rows
        ]
    return found


def rank(candidates: list[Candidate], now: float | None = None) -> list[Candidate]:
    """Best first. Cooling candidates go last rather than being dropped.

    Dropping them would mean a pool that has entirely rate-limited itself has no
    candidates at all, which turns a wait into a hard failure.
    """
    stamp = time.monotonic() if now is None else now

    def key(c: Candidate) -> tuple:
        health = health_for(c.name)
        return (
            health.cooling(stamp),  # False sorts first
            health.failures,
            # A schema we can enforce beats a bigger context window: an
            # unparseable reply is not a slower answer, it is no answer.
            -int(c.strict),
            -int(c.json_native),  # advertised JSON beats hoping
            health.ewma_ms if health.ewma_ms is not None else UNMEASURED_MS,
            -c.context,
        )

    return sorted(candidates, key=key)


def order(pinned: Candidate | None = None) -> list[Candidate]:
    """The pinned candidate first when there is one, then the ranked rest."""
    ranked = rank(pool())
    if pinned is None:
        return ranked
    rest = [c for c in ranked if c.name != pinned.name]
    return [pinned, *rest]
