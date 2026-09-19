"""The security boundary. Nothing reaches DuckDB until `validate` returns.

A DuckDB read-only connection is not a security boundary: it still permits
`read_csv_auto('/etc/passwd')` and still writes files with `COPY ... TO`. The
AST checks below, plus `enable_external_access=false`, are what actually stop
filesystem access.
"""

from __future__ import annotations

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Copy,
    exp.Command,
    exp.Attach,
    exp.Use,
    exp.Pragma,
    exp.Set,
)

FORBIDDEN_FUNCTIONS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "read_text",
    "glob",
    "sniff_csv",
    "parquet_scan",
    "csv_scan",
    "install",
    "load",
    "delta_scan",
    "iceberg_scan",
    "postgres_scan",
    "sqlite_scan",
    "mysql_scan",
}


class GuardError(Exception):
    """A generated statement was rejected before execution."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def safe_connection(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Lock a connection out of the filesystem. Call right after data load."""
    con.execute("SET enable_external_access=false;")
    return con


def match_column(name: str, columns: list[str]) -> str | None:
    """Case-insensitive column lookup.

    DuckDB normalises identifiers case-insensitively and `qualify` rewrites
    `"Order Date"` to `"order date"`, so every lookup of a result column must
    go through here or charts break silently.
    """
    if name is None:
        return None
    target = name.strip().strip('"').lower()
    for col in columns:
        if col.strip().strip('"').lower() == target:
            return col
    return None


def _function_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this or "").lower()
    name = getattr(node, "sql_name", None)
    if callable(name):
        return str(name()).lower()
    return type(node).__name__.lower()


def _check_denylist(expr: exp.Expression) -> None:
    for node in expr.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardError(
                "forbidden_statement",
                f"{type(node).__name__.upper()} is not allowed; plumb only runs SELECT",
            )
        if isinstance(node, (exp.Func, exp.Anonymous)):
            if _function_name(node) in FORBIDDEN_FUNCTIONS:
                raise GuardError(
                    "forbidden_function",
                    f"the function {_function_name(node)}() reads outside the loaded "
                    "spreadsheet and is not allowed",
                )


def _apply_limit(expr: exp.Expression, max_rows: int) -> exp.Expression:
    limit = expr.args.get("limit")
    if limit is None:
        return expr.limit(max_rows)
    try:
        current = int(limit.expression.name)
    except (AttributeError, ValueError):
        return expr.limit(max_rows)
    if current > max_rows:
        return expr.limit(max_rows)
    return expr


def validate(sql: str, schema: dict[str, dict[str, str]], max_rows: int = 1000) -> str:
    """Return rewritten safe SQL, or raise GuardError."""
    try:
        statements = sqlglot.parse(sql, dialect="duckdb")
    except ParseError as e:
        raise GuardError("parse_error", str(e)) from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise GuardError(
            "multiple_statements",
            f"expected exactly one statement, parsed {len(statements)}",
        )
    expr = statements[0]

    if not isinstance(expr, (exp.Select, exp.Union, exp.Subquery)):
        raise GuardError(
            "not_read_only",
            f"{type(expr).__name__.upper()} is not a SELECT; plumb only runs SELECT",
        )

    _check_denylist(expr)

    try:
        qualified = qualify(
            expr, dialect="duckdb", schema=schema, validate_qualify_columns=True
        )
    except OptimizeError as e:
        message = str(e)
        code = "unknown_table" if "not found" in message.lower() else "unknown_column"
        raise GuardError(code, message) from e

    cte_names = {cte.alias_or_name for cte in qualified.find_all(exp.CTE)}
    for table in qualified.find_all(exp.Table):
        if table.name and table.name not in schema and table.name not in cte_names:
            raise GuardError(
                "unknown_table",
                f"table {table.name} is not one of the loaded tables: "
                f"{', '.join(sorted(schema))}",
            )

    _check_denylist(qualified)
    qualified = _apply_limit(qualified, max_rows)
    return qualified.sql(dialect="duckdb")
