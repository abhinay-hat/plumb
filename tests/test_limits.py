"""Upload size and request rate — the limits that protect the host, not the data."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from backend import ratelimit
from backend.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ratelimit.limiter.reset()
    monkeypatch.delenv("PLUMB_RATE_LIMIT_PER_MIN", raising=False)
    monkeypatch.delenv("PLUMB_TRUSTED_PROXY", raising=False)
    yield
    ratelimit.limiter.reset()


def _csv(mb: float) -> io.BytesIO:
    """A syntactically valid CSV of roughly `mb` megabytes."""
    header = b"a,b\n"
    row = b"1,xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
    return io.BytesIO(header + row * int(mb * 1024 * 1024 / len(row)))


def test_an_oversized_upload_is_refused_not_stored(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_MAX_UPLOAD_MB", "1")

    response = client.post(
        "/api/upload", files={"file": ("big.csv", _csv(3), "text/csv")}
    )

    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"


def test_the_budget_is_shared_across_a_multi_file_upload(monkeypatch) -> None:
    """Ten files each just under the cap must not be ten times the cap."""
    monkeypatch.setenv("PLUMB_MAX_UPLOAD_MB", "2")

    response = client.post(
        "/api/upload",
        files=[
            ("files", ("a.csv", _csv(1.5), "text/csv")),
            ("files", ("b.csv", _csv(1.5), "text/csv")),
        ],
    )

    assert response.status_code == 413


def test_too_many_files_is_refused_before_any_are_read(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_MAX_FILES", "2")

    response = client.post(
        "/api/upload",
        files=[("files", (f"f{i}.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")) for i in range(3)],
    )

    assert response.status_code == 400
    assert response.json()["code"] == "too_many_files"


def test_a_normal_upload_still_works(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_MAX_UPLOAD_MB", "32")

    response = client.post(
        "/api/upload", files={"file": ("small.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")}
    )

    assert response.status_code == 200
    assert response.json()["session_id"]


def test_the_rate_limit_is_off_by_default() -> None:
    for _ in range(5):
        assert ratelimit.limiter.check("ask:1.2.3.4") is None


def test_past_the_allowance_a_client_is_told_how_long_to_wait(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_RATE_LIMIT_PER_MIN", "2")

    assert ratelimit.limiter.check("ask:1.2.3.4", now=0.0) is None
    assert ratelimit.limiter.check("ask:1.2.3.4", now=1.0) is None
    wait = ratelimit.limiter.check("ask:1.2.3.4", now=2.0)

    assert wait is not None and 0 < wait <= ratelimit.WINDOW_SECONDS


def test_the_window_frees_up(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_RATE_LIMIT_PER_MIN", "1")

    assert ratelimit.limiter.check("ask:1.2.3.4", now=0.0) is None
    assert ratelimit.limiter.check("ask:1.2.3.4", now=1.0) is not None
    assert ratelimit.limiter.check("ask:1.2.3.4", now=61.0) is None


def test_clients_are_counted_apart(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_RATE_LIMIT_PER_MIN", "1")

    assert ratelimit.limiter.check("ask:1.2.3.4", now=0.0) is None
    assert ratelimit.limiter.check("ask:5.6.7.8", now=0.0) is None


def test_endpoints_are_counted_apart(monkeypatch) -> None:
    """Uploading should not spend the allowance for asking."""
    monkeypatch.setenv("PLUMB_RATE_LIMIT_PER_MIN", "1")

    assert ratelimit.limiter.check("upload:1.2.3.4", now=0.0) is None
    assert ratelimit.limiter.check("ask:1.2.3.4", now=0.0) is None


def test_a_forwarded_header_is_ignored_unless_the_proxy_is_trusted(monkeypatch) -> None:
    """Otherwise a caller mints a fresh identity per request and the limit is theatre."""
    monkeypatch.setenv("PLUMB_RATE_LIMIT_PER_MIN", "1")

    first = client.post(
        "/api/ask",
        json={"session_id": "nope", "question": "hi"},
        headers={"X-Forwarded-For": "9.9.9.1"},
    )
    second = client.post(
        "/api/ask",
        json={"session_id": "nope", "question": "hi"},
        headers={"X-Forwarded-For": "9.9.9.2"},
    )

    # Same socket, different spoofed header: the second must still be limited.
    assert first.status_code == 404  # session_not_found — it got past the limiter
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"


def test_a_trusted_proxy_header_is_believed(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_RATE_LIMIT_PER_MIN", "1")
    monkeypatch.setenv("PLUMB_TRUSTED_PROXY", "1")

    first = client.post(
        "/api/ask",
        json={"session_id": "nope", "question": "hi"},
        headers={"X-Forwarded-For": "9.9.9.1"},
    )
    second = client.post(
        "/api/ask",
        json={"session_id": "nope", "question": "hi"},
        headers={"X-Forwarded-For": "9.9.9.2"},
    )

    assert first.status_code == 404
    assert second.status_code == 404  # a different client, its own allowance
