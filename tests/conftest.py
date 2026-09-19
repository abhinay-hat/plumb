"""Test-wide invariants.

`make test` does not touch the network. Model discovery is the one piece of
the picker that would — `.env` carries a real GROQ_API_KEY, so a bare
`llm.catalog()` in a test would otherwise call Groq for its roster. Off by
default here; the discovery tests turn it back on around a faked transport.
"""

from __future__ import annotations

import pytest

from backend import providers


@pytest.fixture(autouse=True)
def _no_live_model_discovery(monkeypatch):
    monkeypatch.setenv("PLUMB_LIVE_MODELS", "0")
    providers.forget_discovered()
    yield
    providers.forget_discovered()
