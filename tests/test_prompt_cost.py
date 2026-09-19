"""Part A: what the schema card may cost, and what it may never stop saying.

The three warnings asserted at the bottom exist because each one prevented a
Critical defect. An optimiser will take them if nothing is watching.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend import catalog, guard

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HR = FIXTURES / "northwind_hr_analytics.xlsx"


@pytest.fixture(scope="module")
def hr():
    _con, tables = catalog.ingest_many([str(HR)], "cost")
    return tables


@pytest.fixture(scope="module")
def csvs():
    _con, tables = catalog.ingest_many(
        [str(FIXTURES / "employees.csv"), str(FIXTURES / "departments.csv")], "cost"
    )
    return tables


# --- A1: table names -------------------------------------------------------


def test_the_file_stem_is_dropped_when_the_short_name_is_unique(hr) -> None:
    shown = {catalog.display_name(t) for t in hr}
    assert "employees" in shown
    assert "compensation" in shown
    assert not any(name.startswith("northwind") for name in shown)
    # The real identifiers are untouched — those are what DuckDB knows.
    assert all(t.name.startswith("northwind_hr_analytics_") for t in hr)


def test_display_names_are_reversed_before_the_guard_sees_the_sql(hr) -> None:
    aliases = catalog.alias_map(hr)
    restored = catalog.restore_table_names(
        "SELECT count(*) AS n FROM employees", aliases
    )
    assert "northwind_hr_analytics_employees" in restored
    # And it survives the guard, which only knows real names.
    assert guard.validate(restored, catalog.schema_dict(hr))


def test_a_cte_named_like_a_table_is_left_alone(hr) -> None:
    aliases = catalog.alias_map(hr)
    sql = "WITH employees AS (SELECT 1 AS x) SELECT x FROM employees"
    assert catalog.restore_table_names(sql, sql and aliases) == sql


def test_a_colliding_sheet_name_keeps_both_prefixes(tmp_path) -> None:
    """Two files with the same sheet name must stay distinguishable."""
    first = tmp_path / "q1.csv"
    second = tmp_path / "q2.csv"
    shutil.copy(FIXTURES / "employees.csv", first)
    shutil.copy(FIXTURES / "employees.csv", second)
    _con, tables = catalog.ingest_many([str(first), str(second)], "collide")

    shown = [catalog.display_name(t) for t in tables]
    assert len(set(shown)) == len(tables), shown


# --- A2: coverage notes ----------------------------------------------------


def test_no_avg_coverage_promise_on_a_text_column(hr) -> None:
    card = catalog.render_schema(hr)
    for line in card.splitlines():
        if "avg() covers" in line:
            assert "VARCHAR" not in line, line


def test_a_text_column_still_discloses_its_nulls(hr) -> None:
    card = catalog.render_schema(hr)
    exit_reason = next(
        line for line in card.splitlines() if line.strip().startswith("exit_reason")
    )
    assert "null" in exit_reason
    assert "avg()" not in exit_reason


def test_numeric_columns_keep_the_avg_coverage_note(hr) -> None:
    assert "avg() covers" in catalog.render_schema(hr)


def test_aggregate_coverage_ignores_text_columns(hr) -> None:
    employees = next(t for t in hr if catalog.display_name(t) == "employees")
    text = catalog.aggregate_coverage(
        f"SELECT count(exit_reason) FROM {employees.name}", hr
    )
    numeric = catalog.aggregate_coverage(
        f"SELECT avg(manager_id) FROM {employees.name}", hr
    )
    assert text is None
    assert numeric is not None


# --- A3: values over counts ------------------------------------------------


def test_a_small_value_set_is_listed_not_counted(hr) -> None:
    card = catalog.render_schema(hr)
    status = next(line for line in card.splitlines() if line.strip().startswith("status "))
    assert "'Active'" in status and "'Terminated'" in status
    assert "2 distinct" not in status


def test_a_mid_cardinality_column_shows_a_count(hr) -> None:
    card = catalog.render_schema(hr)
    sub_team = next(line for line in card.splitlines() if line.strip().startswith("sub_team"))
    assert "28 distinct" in sub_team
    assert "'" not in sub_team.split("--")[1]


def test_a_high_cardinality_column_says_nothing(hr) -> None:
    card = catalog.render_schema(hr)
    email = next(line for line in card.splitlines() if line.strip().startswith("work_email"))
    assert "--" not in email


# --- A4 / A5: size and pruning --------------------------------------------


def test_sub_one_percent_nulls_are_not_mentioned(hr) -> None:
    for t in hr:
        for ident, col in zip(catalog.identifiers(t), t.columns):
            if 0 < col.null_pct <= 1:
                line = next(
                    (
                        ln
                        for ln in catalog.render_schema([t]).splitlines()
                        if ln.strip().startswith(f"{ident} ")
                    ),
                    "",
                )
                assert "null" not in line, line


def test_no_trailing_whitespace_and_no_double_blank_lines(hr) -> None:
    card = catalog.render_schema(hr)
    assert not any(line != line.rstrip() for line in card.splitlines())
    assert "\n\n\n" not in card


def test_a_salary_by_department_question_sends_three_tables(hr) -> None:
    sent = catalog.select_tables("What is the average salary by department?", hr)
    assert {catalog.display_name(t) for t in sent} == {
        "employees",
        "departments",
        "compensation",
    }


def test_a_vague_question_sends_everything(hr) -> None:
    for vague in ("how's the team doing?", "hi", "what can you do?"):
        assert len(catalog.select_tables(vague, hr)) == len(hr)


def test_pruning_never_goes_below_three_tables(hr) -> None:
    for question in (
        "What is the average salary by department?",
        "How many employees in each location?",
        "Show me training completion by job level",
        "how many people took parental leave",
    ):
        assert len(catalog.select_tables(question, hr)) >= 3


def test_a_small_workbook_is_never_pruned(csvs) -> None:
    assert len(catalog.select_tables("how many employees", csvs)) == len(csvs)


def test_a_chosen_table_pulls_in_what_it_references(hr) -> None:
    """compensation.employee_id is unusable without employees."""
    sent = {
        catalog.display_name(t)
        for t in catalog.select_tables("average base_salary_inr by pay_grade", hr)
    }
    assert "compensation" in sent
    assert "employees" in sent


# --- the three warnings that are not negotiable ---------------------------


def test_the_history_table_warning_survives_every_trim(hr) -> None:
    card = catalog.render_schema(hr)
    assert "HISTORY TABLE" in card
    assert "Do NOT average across rows" in card


def test_the_case_fold_note_survives_every_trim(hr) -> None:
    card = catalog.render_schema(hr)
    assert "Group on lower(location)" in card
    assert "'Hyderabad'" in card and "'hyderabad'" in card


def test_null_coverage_survives_every_trim(hr) -> None:
    card = catalog.render_schema(hr)
    assert "avg() covers" in card
    assert "82% null" in card


def test_the_pruned_card_keeps_the_warnings_too(hr) -> None:
    sent = catalog.select_tables("What is the average salary by department?", hr)
    card = catalog.render_schema(sent)
    assert "HISTORY TABLE" in card
    assert "Group on lower(location)" in card
    assert "avg() covers" in card
