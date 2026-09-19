"""The guard is the security boundary; every case here is exercised for real."""

from pathlib import Path

import duckdb
import pytest

from backend import catalog
from backend.guard import GuardError, match_column, safe_connection, validate

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

SCHEMA = {
    "employees": {
        "employee_id": "BIGINT",
        "name": "VARCHAR",
        "department": "VARCHAR",
        "location": "VARCHAR",
        "status": "VARCHAR",
        "hire_date": "DATE",
        "termination_date": "DATE",
        "salary": "BIGINT",
        "manager_id": "BIGINT",
        "performance_rating": "BIGINT",
    },
    "departments": {
        "department": "VARCHAR",
        "cost_center": "VARCHAR",
        "head_count_budget": "BIGINT",
        "region": "VARCHAR",
    },
}

REJECTED = [
    "DROP TABLE employees",
    "SELECT 1; DROP TABLE employees",
    "UPDATE employees SET salary=0",
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "COPY (SELECT 1) TO '/tmp/x.csv'",
    "SELECT nonexistent FROM employees",
    "SELECT e.bad FROM employees e",
    "SELECT * FROM unknown_table",
    "WITH x AS (SELECT * FROM read_parquet('/x')) SELECT * FROM x",
    "SELECT avg(nonexistent) FROM employees",
    "ATTACH '/tmp/e.db'",
    "PRAGMA database_list",
]

ACCEPTED = [
    "SELECT department, count(*) AS headcount FROM employees GROUP BY department",
    "SELECT employee_id, salary FROM employees WHERE status = 'active'",
    "SELECT d.region, avg(e.salary) AS avg_salary FROM employees e "
    "JOIN departments d ON e.department = d.department GROUP BY d.region",
]


@pytest.mark.parametrize("sql", REJECTED)
def test_rejected(sql: str) -> None:
    with pytest.raises(GuardError):
        validate(sql, SCHEMA)


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepted_gets_a_limit(sql: str) -> None:
    out = validate(sql, SCHEMA)
    assert "LIMIT" in out.upper()


def test_accepted_sql_actually_runs() -> None:
    con, tables = catalog.ingest_many(
        [str(FIXTURES / "employees.csv"), str(FIXTURES / "departments.csv")], "s"
    )
    safe_connection(con)
    schema = catalog.schema_dict(tables)
    for sql in ACCEPTED:
        con.execute(validate(sql, schema)).fetchall()


def test_hidden_write_inside_cte_is_rejected() -> None:
    with pytest.raises(GuardError):
        validate(
            "WITH x AS (SELECT * FROM employees) "
            "SELECT * FROM (SELECT glob('/etc/*') AS g)",
            SCHEMA,
        )


def test_existing_limit_is_lowered_not_raised() -> None:
    out = validate("SELECT employee_id FROM employees LIMIT 99999", SCHEMA, max_rows=10)
    assert out.upper().rstrip().endswith("LIMIT 10")
    out = validate("SELECT employee_id FROM employees LIMIT 5", SCHEMA, max_rows=10)
    assert out.upper().rstrip().endswith("LIMIT 5")


def test_guard_error_carries_code_and_message() -> None:
    with pytest.raises(GuardError) as excinfo:
        validate("SELECT nonexistent FROM employees", SCHEMA)
    assert excinfo.value.code == "unknown_column"
    assert excinfo.value.message


def test_match_column_is_case_insensitive() -> None:
    columns = ["order date", "Net Amount", "salary"]
    assert match_column("Order Date", columns) == "order date"
    assert match_column('"SALARY"', columns) == "salary"
    assert match_column("missing", columns) is None


def test_external_access_disabled_blocks_read_csv_auto() -> None:
    con = duckdb.connect(database=":memory:")
    safe_connection(con)
    with pytest.raises(duckdb.Error):
        con.execute("SELECT * FROM read_csv_auto('/etc/passwd')").fetchall()


def test_external_access_disabled_blocks_copy_to_file(tmp_path: Path) -> None:
    con = duckdb.connect(database=":memory:")
    safe_connection(con)
    target = tmp_path / "leak.csv"
    with pytest.raises(duckdb.Error):
        con.execute(f"COPY (SELECT 1) TO '{target}'")
    assert not target.exists()
