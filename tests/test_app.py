"""HTTP surface: health, upload, schema. Ask is covered by the live verify."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_session_before_upload() -> None:
    response = client.post("/api/session")
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    assert session_id

    schema = client.get(f"/api/session/{session_id}/schema")
    assert schema.status_code == 200
    assert schema.json() == []


def test_upload_and_schema() -> None:
    with (FIXTURES / "employees.csv").open("rb") as fh:
        response = client.post("/api/upload", files={"file": ("employees.csv", fh, "text/csv")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"]
    tables = body["tables"]
    assert tables[0]["name"] == "employees"
    assert tables[0]["row_count"] == 60
    assert body["suggestions"]
    assert any("department" in q.lower() for q in body["suggestions"])

    listed = client.get(f"/api/session/{body['session_id']}/suggestions")
    assert listed.status_code == 200
    assert listed.json()["suggestions"] == body["suggestions"]

    schema = client.get(f"/api/session/{body['session_id']}/schema")
    assert schema.status_code == 200
    assert schema.json()[0]["row_count"] == 60


def test_missing_session_is_structured() -> None:
    response = client.get("/api/session/nope/schema")
    assert response.status_code == 404
    assert response.json() == {"code": "session_not_found", "message": "no session nope"}


def test_models_lists_the_providers() -> None:
    response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["providers"]]
    assert ids[:4] == ["groq", "openrouter", "ollama", "custom"]
    assert body["provider"] in ids
    groq = next(item for item in body["providers"] if item["id"] == "groq")
    groq_ids = {row["id"] for row in groq["models"]}
    assert "openai/gpt-oss-20b" in groq_ids
    assert "llama-3.3-70b-versatile" not in groq_ids
    openrouter = next(item for item in body["providers"] if item["id"] == "openrouter")
    openrouter_ids = {row["id"] for row in openrouter["models"]}
    assert "openrouter/free" in openrouter_ids


def test_models_pin_and_reject(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "groq")
    monkeypatch.setenv("PLUMB_MODEL", "llama-3.3-70b-versatile")

    ok = client.post(
        "/api/models",
        json={"provider": "ollama", "model": "qwen2.5-coder:7b-instruct"},
    )
    assert ok.status_code == 200
    assert ok.json()["provider"] == "ollama"
    assert ok.json()["model"] == "qwen2.5-coder:7b-instruct"

    bad = client.post("/api/models", json={"provider": "openai", "model": "gpt-4o"})
    assert bad.status_code == 400
    assert bad.json()["code"] == "invalid_model"

    routed = client.post(
        "/api/models",
        json={"provider": "openrouter", "model": "qwen/qwen3.8-27b:free"},
    )
    assert routed.status_code == 200
    assert routed.json()["provider"] == "openrouter"
    assert routed.json()["model"] == "qwen/qwen3.8-27b:free"


def _upload() -> str:
    with (FIXTURES / "employees.csv").open("rb") as fh:
        response = client.post("/api/upload", files={"file": ("employees.csv", fh, "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_custom_endpoint_is_per_session(monkeypatch) -> None:
    from backend.endpoint_guard import inspect_endpoint

    monkeypatch.setattr("backend.llm.probe", lambda url, key, model: inspect_endpoint(url))
    a = _upload()
    b = _upload()
    one = client.post(
        f"/api/session/{a}/provider",
        json={
            "provider": "custom",
            "model": "one",
            "url": "http://127.0.0.1:11434/v1/chat/completions",
            "key": "sk-session-a",
        },
    )
    two = client.post(
        f"/api/session/{b}/provider",
        json={
            "provider": "custom",
            "model": "two",
            "url": "http://127.0.0.1:1234/v1/chat/completions",
            "key": "sk-session-b",
        },
    )
    assert one.status_code == 200, one.text
    assert two.status_code == 200, two.text
    assert one.json()["host"] == "127.0.0.1"
    assert two.json()["model"] == "two"
    dumped = one.text + two.text
    assert "sk-session-a" not in dumped
    assert "sk-session-b" not in dumped

    listed = client.get(f"/api/models?session_id={a}")
    assert listed.status_code == 200
    assert "sk-session-a" not in listed.text
    assert listed.json()["host"] == "127.0.0.1"


def test_ssrf_urls_are_refused_and_not_requested(monkeypatch) -> None:
    sid = _upload()
    calls: list[str] = []

    def explode(url, *args, **kwargs):
        calls.append(str(url))
        raise AssertionError(f"must not request {url}")

    monkeypatch.setattr("backend.llm.httpx.post", explode)
    blocked = [
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "file:///etc/passwd",
        "gopher://internal:70/",
        "https://user:pass@example.com/v1",
        "http://10.0.0.5/v1/chat/completions",
        "https://example.com:22/v1",
    ]
    for url in blocked:
        response = client.post(
            f"/api/session/{sid}/provider",
            json={"provider": "custom", "model": "x", "url": url, "key": "sk-never-leak"},
        )
        assert response.status_code == 400, (url, response.text)
        assert "sk-never-leak" not in response.text
    assert calls == []


def test_custom_key_is_absent_from_audit(monkeypatch, tmp_path) -> None:
    from backend import audit
    from backend.app import _log_turn
    from backend.endpoint_guard import inspect_endpoint
    from backend.models import AskResponse

    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr("backend.llm.probe", lambda url, key, model: inspect_endpoint(url))
    sid = _upload()
    ok = client.post(
        f"/api/session/{sid}/provider",
        json={
            "provider": "custom",
            "model": "llama3.2",
            "url": "http://127.0.0.1:11434/v1/chat/completions",
            "key": "sk-never-leak",
        },
    )
    assert ok.status_code == 200
    _log_turn(
        sid,
        "how many?",
        AskResponse(
            route="refuse",
            refuse_reason="no",
            elapsed_ms=1,
            provider="custom",
            model="llama3.2",
            endpoint_host="127.0.0.1",
        ),
    )
    text = (tmp_path / f"{sid}.jsonl").read_text()
    assert "sk-never-leak" not in text
    assert "127.0.0.1" in text
    assert "http://127.0.0.1:11434" not in text
    listed = client.get(f"/api/session/{sid}/audit")
    assert "sk-never-leak" not in listed.text
