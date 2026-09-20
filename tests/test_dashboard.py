"""Dashboard route — several analyses from one broad question."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend import catalog, dashboard, guard, narrate, pipeline
from backend.models import Panel, Plan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def session() -> pipeline.Session:
    con, tables = catalog.ingest_many([str(FIXTURES / "employees.csv")], "test")
    guard.safe_connection(con)
    return pipeline.Session(con=con, tables=tables)


def _stub(monkeypatch: pytest.MonkeyPatch, plans: list[Plan]) -> list[dict]:
    calls: list[dict] = []

    def fake_plan(*args, **kwargs):
        calls.append({"kwargs": kwargs})
        return plans[min(len(calls) - 1, len(plans) - 1)]

    monkeypatch.setattr(pipeline, "make_plan", fake_plan)
    return calls


def _sql_panel(title: str, sql: str) -> Panel:
    return Panel(title=title, sql=sql)


def _four_panel_plan() -> Plan:
    return Plan(
        route="dashboard",
        panels=[
            _sql_panel(
                "Headcount by department",
                'SELECT "department", COUNT(*) AS "headcount" '
                'FROM employees GROUP BY "department" ORDER BY "headcount" DESC',
            ),
            _sql_panel(
                "Average salary by location",
                'SELECT "location", ROUND(AVG("salary")) AS "avg_salary" '
                'FROM employees GROUP BY "location"',
            ),
            _sql_panel(
                "Active vs terminated",
                'SELECT "status", COUNT(*) AS "n" FROM employees GROUP BY "status"',
            ),
            _sql_panel(
                "Hires by year",
                'SELECT EXTRACT(YEAR FROM "hire_date") AS "hire_year", COUNT(*) AS "n" '
                'FROM employees GROUP BY 1 ORDER BY 1',
            ),
        ],
    )


def test_four_panel_plan_returns_four_populated_panels(session, monkeypatch) -> None:
    _stub(monkeypatch, [_four_panel_plan()])
    response = pipeline.ask("Give me an overview of this data", session)
    assert response.route == "dashboard"
    assert response.panels is not None
    assert len(response.panels) == 4
    for panel in response.panels:
        assert panel.error_code is None
        assert panel.rows
        assert panel.columns
        assert panel.finding
        assert panel.sql


def test_guard_failure_drops_one_panel(session, monkeypatch) -> None:
    plan = Plan(
        route="dashboard",
        panels=[
            _sql_panel("Good", "SELECT COUNT(*) AS n FROM employees"),
            _sql_panel("Bad", "SELECT 1 FROM not_a_real_table"),
            _sql_panel("Also good", 'SELECT "status", COUNT(*) AS n FROM employees GROUP BY 1'),
        ],
    )
    _stub(monkeypatch, [plan])
    response = pipeline.ask("analyse this data", session)
    assert response.route == "dashboard"
    assert response.panels is not None
    codes = [p.error_code for p in response.panels]
    assert any(code in ("unknown_table", "unknown_column") for code in codes if code)
    assert codes.count(None) >= 2


def test_execution_error_drops_panel(session, monkeypatch) -> None:
    plan = Plan(
        route="dashboard",
        panels=[
            _sql_panel("Good", "SELECT COUNT(*) AS n FROM employees"),
            _sql_panel(
                "Bad cast",
                'SELECT CAST("department" AS INTEGER) AS n FROM employees',
            ),
        ],
    )
    _stub(monkeypatch, [plan])
    response = pipeline.ask("explore the sheet", session)
    assert response.route == "dashboard"
    assert any(p.error_code == "execution_error" for p in response.panels or [])
    assert any(p.error_code is None for p in response.panels or [])


def test_all_panels_failing_returns_refuse(session, monkeypatch) -> None:
    plan = Plan(
        route="dashboard",
        panels=[
            _sql_panel("A", "SELECT 1 FROM missing_one"),
            _sql_panel("B", "SELECT 1 FROM missing_two"),
        ],
    )
    _stub(monkeypatch, [plan])
    response = pipeline.ask("summarise everything", session)
    assert response.route == "refuse"
    assert response.panels is None
    assert "Every dashboard panel failed" in (response.refuse_reason or "")


def test_duplicate_sql_is_deduplicated(session, monkeypatch) -> None:
    sql = "SELECT COUNT(*) AS n FROM employees"
    plan = Plan(
        route="dashboard",
        panels=[
            _sql_panel("One", sql),
            _sql_panel("Two", sql),
            _sql_panel("Three", 'SELECT "department", COUNT(*) AS n FROM employees GROUP BY 1'),
        ],
    )
    _stub(monkeypatch, [plan])
    response = pipeline.ask("overview", session)
    assert response.route == "dashboard"
    sqls = [p.sql for p in response.panels or [] if p.sql]
    assert len(sqls) == len(set(dashboard.normalize_sql(s) for s in sqls))


def test_finding_cites_only_panel_numbers(session, monkeypatch) -> None:
    _stub(monkeypatch, [_four_panel_plan()])
    response = pipeline.ask("insights please", session)
    for panel in response.panels or []:
        if panel.rows and panel.finding:
            assert narrate.verify_narration(panel.finding, panel.rows)


def test_panel_cap_is_enforced(session, monkeypatch) -> None:
    panels = [
        _sql_panel(f"Panel {i}", f"SELECT {i} AS n FROM employees")
        for i in range(8)
    ]
    monkeypatch.setenv("PLUMB_DASHBOARD_PANELS", "4")
    _stub(monkeypatch, [Plan(route="dashboard", panels=panels)])
    response = pipeline.ask("explore", session)
    assert response.route == "dashboard"
    assert len(response.panels or []) <= 4


def test_audit_records_every_panel_sql(monkeypatch, tmp_path) -> None:
    from backend import audit
    from backend.app import _log_turn
    from backend.models import AskResponse

    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    response = AskResponse(
        route="dashboard",
        panels=[
            Panel(title="A", sql="SELECT 1", rows=[[1]], columns=["n"], finding="n is 1."),
            Panel(title="B", sql="SELECT 2", error_code="unknown_table"),
        ],
        elapsed_ms=12,
    )
    _log_turn("sess-1", "overview?", response)
    entry = audit.read("sess-1")[0]
    assert entry["panel_count"] == 2
    assert entry["panel_sql"] == ["SELECT 1", "SELECT 2"]


def test_timeout_returns_completed_panels(session, monkeypatch) -> None:
    plan = _four_panel_plan()
    clock = iter([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0])

    monkeypatch.setattr(time, "perf_counter", lambda: next(clock, 1.0))
    monkeypatch.setattr(dashboard, "timeout_ms", lambda: 500)
    _stub(monkeypatch, [plan])
    response = pipeline.ask("overview", session)
    assert response.route == "dashboard"
    assert any(p.error_code == "timeout" for p in response.panels or [])
    assert any(p.error_code is None for p in response.panels or [])


def test_dashboard_uses_one_planner_call(session, monkeypatch) -> None:
    calls = _stub(monkeypatch, [_four_panel_plan()])
    pipeline.ask("analyse this spreadsheet", session)
    assert len(calls) == 1


def test_average_salary_stays_on_answer_route(session, monkeypatch) -> None:
    _stub(
        monkeypatch,
        [
            Plan(
                route="answer",
                sql='SELECT ROUND(AVG("salary")) AS "avg_salary" FROM employees',
            )
        ],
    )
    response = pipeline.ask("what is the average salary?", session)
    assert response.route == "answer"
    assert response.panels is None


def test_an_unexpected_render_error_costs_one_panel_not_the_turn(
    session, monkeypatch
) -> None:
    """Isolation has to cover the unexpected, not only the errors we predicted.

    Guard and DuckDB failures were already handled. An odd result shape raising
    out of chart building took the whole dashboard with it — including the
    panels that had already succeeded.
    """
    _stub(monkeypatch, [_four_panel_plan()])
    calls = {"n": 0}

    def explode(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyError("a column nobody expected")
        return None, None

    monkeypatch.setattr(pipeline, "_panel_chart", explode)

    response = pipeline.ask("give me an overview", session)

    assert response.route == "dashboard"
    assert response.panels is not None and len(response.panels) == 4
    broken = [p for p in response.panels if p.error_code == "render_failed"]
    assert len(broken) == 1
    # The rows survived: a panel that cannot be drawn is still a table.
    assert broken[0].rows
    assert all(p.rows for p in response.panels)


def test_a_failed_summary_does_not_discard_the_panels(session, monkeypatch) -> None:
    _stub(monkeypatch, [_four_panel_plan()])
    monkeypatch.setattr(dashboard, "summary_enabled", lambda: True)

    def boom(*_args, **_kwargs):
        raise RuntimeError("provider rate-limited")

    monkeypatch.setattr(pipeline, "_dashboard_summary", boom)

    response = pipeline.ask("give me an overview", session)

    assert response.route == "dashboard"
    assert response.summary is None
    assert response.panels is not None and len(response.panels) == 4
