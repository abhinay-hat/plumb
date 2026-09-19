"""Schema-derived example questions."""

from pathlib import Path

from backend import catalog, suggestions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_employees_fixture_gets_department_and_salary_questions() -> None:
    _, tables = catalog.ingest(str(FIXTURES / "employees.csv"), "t")
    qs = suggestions.suggest_questions(tables)
    assert len(qs) == 3
    joined = " ".join(qs).lower()
    assert "department" in joined
    assert "salary" in joined
    assert "employee" in joined


def test_empty_schema_returns_no_data_questions() -> None:
    assert suggestions.suggest_questions([]) == []


def _hr_tables():
    from backend import catalog

    _, tables = catalog.ingest(str(FIXTURES / "northwind_hr_analytics.xlsx"), "s")
    return tables


def test_follow_ups_name_columns_the_answer_did_not_use() -> None:
    tables = _hr_tables()
    employees = next(t for t in tables if "employees" in t.name)
    columns = catalog.identifiers(employees)[:2]
    rows = [["a", 1], ["b", 2]]

    out = suggestions.follow_ups(columns, rows, tables)

    assert out, "a real schema should always yield at least one follow-up"
    known = {
        name.replace("_", " ")
        for table in tables
        for name in catalog.identifiers(table)
    }
    for line in out:
        assert line.endswith("?") or line.endswith(".")
    # Every follow-up that mentions a column mentions a column that exists.
    mentioned = [line for line in out if any(name in line for name in known)]
    assert mentioned, f"no follow-up named a real column: {out}"


def test_follow_ups_offer_the_chart_the_shape_supports() -> None:
    from backend.models import ChartAdvice

    tables = _hr_tables()
    advice = ChartAdvice(kind="bar", x="department", y="headcount", reason="x")
    out = suggestions.follow_ups(
        ["department", "headcount"],
        [["a", 1], ["b", 2]],
        tables,
        advice=advice,
        rendered=None,
    )
    assert out[0] == "Show this as a bar chart."


def test_a_rendered_chart_is_not_offered_again() -> None:
    from backend.models import ChartAdvice

    tables = _hr_tables()
    advice = ChartAdvice(kind="bar", x="department", y="headcount", reason="x")
    out = suggestions.follow_ups(
        ["department", "headcount"],
        [["a", 1], ["b", 2]],
        tables,
        advice=advice,
        rendered="bar",
    )
    assert all("Show this as a bar chart." != line for line in out)


def test_follow_ups_stay_empty_without_a_schema() -> None:
    assert suggestions.follow_ups(["a"], [[1]], []) == []
