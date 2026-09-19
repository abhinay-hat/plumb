"""Session store holds live DuckDB connections and evicts idle ones."""

from pathlib import Path

from backend import catalog
from backend.pipeline import Session
from backend.session import IDLE_SECONDS, SessionStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _loaded() -> Session:
    con, tables = catalog.ingest(str(FIXTURES / "employees.csv"), "s")
    return Session(con=con, tables=tables)


def test_create_and_get_roundtrip() -> None:
    store = SessionStore()
    session = _loaded()
    session_id = store.create(session)
    found = store.get(session_id)
    assert found is session
    assert found.tables[0].name == "employees"
    assert found.con.execute("SELECT count(*) FROM employees").fetchone()[0] == 60


def test_unknown_session_is_none() -> None:
    assert SessionStore().get("missing") is None


def test_idle_session_is_evicted() -> None:
    store = SessionStore()
    session_id = store.create(_loaded())
    store._sessions[session_id].last_used -= IDLE_SECONDS + 1
    assert store.get(session_id) is None
