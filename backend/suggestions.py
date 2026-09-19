"""Example questions derived from the loaded schema — never hardcoded copy."""

from __future__ import annotations

import re

from backend import catalog
from backend.models import ChartAdvice, ColumnInfo, TableInfo

_GROUP_HINTS = (
    "department",
    "dept",
    "team",
    "location",
    "city",
    "region",
    "country",
    "category",
    "status",
    "type",
    "segment",
    "channel",
    "brand",
    "vendor",
    "supplier",
    "product",
    "sku",
)
_METRIC_HINTS = (
    "salary",
    "revenue",
    "amount",
    "price",
    "cost",
    "rating",
    "score",
    "quantity",
    "qty",
    "total",
    "profit",
    "margin",
    "tenure",
    "days",
)
_DATE_HINTS = ("date", "time", "month", "year", "hire", "created", "ordered", "termination")
_ENTITY_WORDS = (
    "employee",
    "customer",
    "order",
    "product",
    "review",
    "sale",
    "transaction",
    "invoice",
    "record",
    "row",
    "item",
    "account",
    "user",
    "member",
    "candidate",
    "requisition",
)


def _tokens(name: str) -> set[str]:
    return {part for part in re.split(r"[_\s\-]+", name.lower()) if part}


def _score_name(name: str, hints: tuple[str, ...]) -> int:
    parts = _tokens(name)
    return sum(2 if hint in parts else 1 if any(hint in part for part in parts) else 0 for hint in hints)


def _entity_label(table: TableInfo) -> str:
    name = (catalog.display_name(table) or table.name).replace("_", " ").strip()
    lower = name.lower()
    for word in _ENTITY_WORDS:
        if word in lower:
            return word + ("s" if not word.endswith("s") else "")
    words = lower.split()
    if words:
        last = words[-1]
        if last.endswith("s") and len(last) > 3:
            return last
        return last + "s"
    return "rows"


def _is_numeric(col: ColumnInfo) -> bool:
    upper = col.dtype.upper()
    return any(token in upper for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "HUGEINT"))


def _is_date(col: ColumnInfo) -> bool:
    upper = col.dtype.upper()
    return "DATE" in upper or "TIME" in upper or _score_name(col.name, _DATE_HINTS) > 0


def _is_groupable(col: ColumnInfo, row_count: int) -> bool:
    if _is_numeric(col) or _is_date(col):
        return False
    if col.distinct_count <= 1:
        return False
    if row_count and col.distinct_count > max(24, row_count // 2):
        return False
    return True


def _pick_group_column(columns: list[ColumnInfo], row_count: int) -> ColumnInfo | None:
    candidates = [col for col in columns if _is_groupable(col, row_count)]
    if not candidates:
        return None
    return max(candidates, key=lambda col: _score_name(col.name, _GROUP_HINTS))


def _pick_metric_column(columns: list[ColumnInfo]) -> ColumnInfo | None:
    numeric = [col for col in columns if _is_numeric(col)]
    if not numeric:
        return None
    return max(numeric, key=lambda col: _score_name(col.name, _METRIC_HINTS))


def _pick_date_column(columns: list[ColumnInfo]) -> ColumnInfo | None:
    dated = [col for col in columns if _is_date(col)]
    if not dated:
        return None
    return max(dated, key=lambda col: _score_name(col.name, _DATE_HINTS))


def _human(col: ColumnInfo) -> str:
    return col.name.replace("_", " ")


def _entity_rank(table: TableInfo) -> int:
    name = (catalog.display_name(table) or table.name).lower()
    core = ("employee", "customer", "order", "product", "account", "member")
    for word in core:
        if word in name:
            return 3
    for word in _ENTITY_WORDS:
        if word in name:
            return 2
    return 0


def _table_score(table: TableInfo) -> tuple[int, int, int]:
    """Prefer entity sheets over event logs, even when logs have more rows."""
    name = (catalog.display_name(table) or table.name).lower()
    score = 0
    if table.is_history_table:
        score -= 40
    for word in _ENTITY_WORDS:
        if word in name:
            score += 25
    if _pick_group_column(table.columns, table.row_count):
        score += 8
    if _pick_metric_column(table.columns):
        score += 8
    for noise in ("leave", "attendance", "log", "audit", "event", "history", "survey"):
        if noise in name:
            score -= 15
    return (score, _entity_rank(table), table.row_count)


def _pick_primary_table(tables: list[TableInfo]) -> TableInfo:
    return max(tables, key=_table_score)


def _is_measure(col: ColumnInfo, table: TableInfo) -> bool:
    """A number worth averaging, as opposed to a number that identifies a row.

    An id is numeric and would average cleanly into nonsense. Both tests come
    from the data rather than the spelling of the name: a primary key takes a
    near-distinct value per row, and a foreign key is whatever `catalog`
    already matched against another sheet. That catches `employee_id`,
    `manager_id`, and `emp_no` alike, without a list of suffixes to maintain.
    """
    if not _is_numeric(col) or _is_date(col):
        return False
    if table.row_count and col.distinct_count / table.row_count > 0.9:
        return False
    return col.name not in catalog.foreign_key_columns(table)


def _columns_in(tables: list[TableInfo]) -> dict[str, tuple[TableInfo, ColumnInfo]]:
    found: dict[str, tuple[TableInfo, ColumnInfo]] = {}
    for table in tables:
        for name, col in zip(catalog.identifiers(table), table.columns):
            found.setdefault(name.lower(), (table, col))
            found.setdefault(col.name.lower(), (table, col))
    return found


def follow_ups(
    columns: list[str],
    rows: list[list],
    tables: list[TableInfo],
    advice: ChartAdvice | None = None,
    rendered: str | None = None,
    limit: int = 3,
) -> list[str]:
    """Next questions, built from the columns this answer actually returned.

    Every line names a real column of the source sheet — the same rule as
    `suggest_questions`, applied to a result instead of a schema. Nothing here
    is a canned prompt: with no matching column, the list comes back short
    rather than padded.
    """
    if not columns or not tables:
        return []

    known = _columns_in(tables)
    answered = {col.lower() for col in columns}
    resolved = [known[col.lower()] for col in columns if col.lower() in known]
    source = resolved[0][0] if resolved else _pick_primary_table(tables)
    label = _entity_label(source)

    used_metric = next(
        (col for _, col in resolved if _is_measure(col, source)), None
    )
    used_group = next((col for _, col in resolved if _is_groupable(col, source.row_count)), None)

    out: list[str] = []

    # A chart the shape supports but this turn did not draw is the cheapest
    # next question there is — the SQL is already right.
    if advice is not None and advice.kind != "none" and advice.kind != rendered:
        out.append(f"Show this as a {advice.kind} chart.")
    if advice is not None and advice.unsupported:
        out.append(
            f"This looks like {advice.unsupported} data — ask for it as a "
            f"{advice.kind if advice.kind != 'none' else 'line'} chart instead."
        )

    # Another way to cut the same measure: a grouping column the answer did not use.
    if used_metric:
        other_group = next(
            (
                col
                for _, col in _columns_in([source]).values()
                if _is_groupable(col, source.row_count) and col.name.lower() not in answered
            ),
            None,
        )
        if other_group:
            out.append(
                f"What's the average {_human(used_metric)} by {_human(other_group)}?"
            )
        date_col = _pick_date_column(source.columns)
        if date_col and date_col.name.lower() not in answered:
            out.append(f"How has {_human(used_metric)} changed over {_human(date_col)}?")

    # The same grouping against a measure the answer did not report.
    if used_group:
        other_metric = next(
            (
                col
                for col in source.columns
                if _is_measure(col, source) and col.name.lower() not in answered
            ),
            None,
        )
        if other_metric:
            out.append(f"Show {_human(other_metric)} by {_human(used_group)}.")

    # A second sheet the answer never touched.
    unused = [t for t in tables if t.name not in {table.name for table, _ in resolved}]
    if unused and used_metric is None:
        other = max(unused, key=_table_score)
        metric = _pick_metric_column(other.columns)
        if metric:
            out.append(
                f"What's the average {_human(metric)} in {catalog.display_name(other)}?"
            )
    elif not out and used_metric:
        out.append(f"Who are the top {label} by {_human(used_metric)}?")

    seen: set[str] = set()
    deduped: list[str] = []
    for question in out:
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(question)
        if len(deduped) >= limit:
            break
    return deduped


def suggest_questions(tables: list[TableInfo], limit: int = 3) -> list[str]:
    """Up to `limit` English questions that name real columns from the schema."""
    if not tables:
        return []

    primary = _pick_primary_table(tables)
    label = _entity_label(primary)
    group = _pick_group_column(primary.columns, primary.row_count)
    metric = _pick_metric_column(primary.columns)
    date_col = _pick_date_column(primary.columns)

    out: list[str] = []

    if group:
        out.append(f"How many {label} in each {_human(group)}?")

    if metric and group:
        out.append(f"What's the average {_human(metric)} by {_human(group)}?")
    elif metric:
        out.append(f"What's the average {_human(metric)}?")

    if metric:
        out.append(f"Who are the top {label} by {_human(metric)}?")
    elif date_col:
        out.append(f"How many {label} by {_human(date_col)}?")
    elif group:
        out.append(f"Show {label} grouped by {_human(group)}.")

    if len(tables) > 1 and len(out) < limit:
        other = next((table for table in tables if table.name != primary.name), None)
        if other and metric:
            out.append(
                f"What's the average {_human(metric)} in {catalog.display_name(other)}?"
            )

    seen: set[str] = set()
    deduped: list[str] = []
    for question in out:
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(question)
        if len(deduped) >= limit:
            break
    return deduped
