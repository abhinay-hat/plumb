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


def test_upload_and_schema() -> None:
    with (FIXTURES / "employees.csv").open("rb") as fh:
        response = client.post("/api/upload", files={"file": ("employees.csv", fh, "text/csv")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"]
    tables = body["tables"]
    assert tables[0]["name"] == "employees"
    assert tables[0]["row_count"] == 60

    schema = client.get(f"/api/session/{body['session_id']}/schema")
    assert schema.status_code == 200
    assert schema.json()[0]["row_count"] == 60


def test_missing_session_is_structured() -> None:
    response = client.get("/api/session/nope/schema")
    assert response.status_code == 404
    assert response.json() == {"code": "session_not_found", "message": "no session nope"}
