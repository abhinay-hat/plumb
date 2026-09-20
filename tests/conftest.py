"""Test-wide invariants.

`make test` does not touch the network, and it must not depend on which keys
happen to be in the developer's `.env`. Two things enforce that here.

Model discovery is off: a bare `llm.catalog()` would otherwise ask every
provider for its live roster. The discovery tests turn it back on around a
faked transport.

Every provider key is cleared: a key present on one machine and absent on
another silently changes the routing pool, so a test that passes locally fails
in CI — or worse, passes while sending real requests. A test that wants a
provider sets its key itself.
"""

from __future__ import annotations

import pytest

from backend import providers, router

_KEY_VARS = (
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "PLUMB_OLLAMA_URL",
    *(str(preset["key_env"]) for preset in providers.PRESETS),
    *(
        str(preset["account_env"])
        for preset in providers.PRESETS
        if preset.get("account_env")
    ),
)


@pytest.fixture(autouse=True)
def _hermetic_providers(monkeypatch):
    monkeypatch.setenv("PLUMB_LIVE_MODELS", "0")
    for name in _KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    providers.forget_discovered()
    router.reset_health()
    yield
    providers.forget_discovered()
    router.reset_health()
