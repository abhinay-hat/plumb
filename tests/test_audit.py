"""Audit writes real JSONL and reads it back."""

from backend import audit


def test_append_and_read_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    entry = {
        "ts": "2026-09-19T00:00:00+00:00",
        "session_id": "abc",
        "question": "how many?",
        "route": "answer",
        "sql": "SELECT 1",
        "row_count": 1,
        "elapsed_ms": 12,
        "model": "llama-3.3-70b-versatile",
        "provider": "groq",
        "guard_errors": [],
        "definitions_applied": {},
        "narration_verified": True,
    }
    audit.append("abc", entry)
    audit.append("abc", {**entry, "question": "again"})
    rows = audit.read("abc")
    assert len(rows) == 2
    assert rows[0]["question"] == "how many?"
    assert rows[1]["question"] == "again"
    assert (tmp_path / "abc.jsonl").read_text().count("\n") == 2


def test_read_missing_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    assert audit.read("nope") == []
