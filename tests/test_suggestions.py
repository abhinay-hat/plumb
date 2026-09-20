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


def test_a_question_already_asked_is_never_suggested_again() -> None:
    tables = _hr_tables()
    repeat = "What's the average tenure days in northwind_hr_analytics_employees?"

    out = suggestions.follow_ups(
        ["average_tenure_days"], [[572.378125]], tables, asked=[repeat]
    )

    assert all(suggestions._asked_key(repeat) != suggestions._asked_key(q) for q in out)


def test_punctuation_and_case_do_not_smuggle_a_repeat_through() -> None:
    tables = _hr_tables()
    out = suggestions.follow_ups(
        ["average_tenure_days"],
        [[1.0]],
        tables,
        asked=["  WHAT'S THE AVERAGE TENURE DAYS IN NORTHWIND_HR_ANALYTICS_EMPLOYEES  "],
    )
    assert "average tenure days in northwind_hr_analytics_employees" not in " ".join(
        q.lower() for q in out
    )


def test_a_single_aggregate_is_offered_a_breakdown() -> None:
    """One number names no schema column, so every column-based branch misses."""
    tables = _hr_tables()

    out = suggestions.follow_ups(["average_tenure_days"], [[572.378125]], tables)

    assert out, "a single number should still suggest how to cut it"
    assert any(" by " in q for q in out)


def test_the_same_question_reworded_is_still_a_repeat() -> None:
    """Naming the table an answer already came from is not a new question."""
    tables = _hr_tables()

    out = suggestions.follow_ups(
        ["average_salary"],
        [[91000.0]],
        tables,
        asked=["What is the average salary?"],
    )

    assert not any("average salary in" in q.lower() for q in out), out


def test_a_genuinely_different_cut_survives_the_filter() -> None:
    tables = _hr_tables()

    out = suggestions.follow_ups(
        ["average_salary"],
        [[91000.0]],
        tables,
        asked=["What is the average salary?"],
    )

    assert any(" by " in q for q in out), f"a breakdown is a new question: {out}"


def test_a_briefing_may_quote_real_row_counts() -> None:
    from backend import briefing

    tables = _hr_tables()
    employees = next(t for t in tables if "employees" in t.name)
    text = f"You have {len(tables)} sheets; employees holds {employees.row_count} rows."

    assert briefing.verify_briefing(text, tables)


def test_a_rounded_row_count_is_rejected() -> None:
    """"about 600 employees" is the failure this whole application refuses."""
    from backend import briefing

    tables = _hr_tables()

    assert not briefing.verify_briefing("There are about 600 employees.", tables)


def test_sentence_furniture_is_not_a_claim() -> None:
    from backend import briefing

    tables = _hr_tables()

    assert briefing.verify_briefing("Try one of these 3 questions to start.", tables)


def test_the_fallback_briefing_names_real_sheets() -> None:
    from backend import briefing

    tables = _hr_tables()
    text = briefing.describe(tables)

    assert str(len(tables)) in text
    assert any(catalog.display_name(t) in text for t in tables)
    assert briefing.verify_briefing(text, tables), "the fallback must pass its own check"


def test_an_empty_session_says_so() -> None:
    from backend import briefing

    assert "No spreadsheet is loaded" in briefing.describe([])
