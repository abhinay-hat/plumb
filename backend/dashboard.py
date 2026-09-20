"""Execute dashboard panels and derive findings without extra LLM calls.

A dashboard is several small answers in one turn. Each panel is isolated — one
bad query must not abort the others — and every finding is computed in Python
so the turn stays at one planner call.
"""

from __future__ import annotations

import os

from backend import chart, narrate

MAX_PANELS = 6
_DEFAULT_PANELS = 4
_DEFAULT_TIMEOUT_MS = 20_000


def panel_limit() -> int:
    raw = int(os.environ.get("PLUMB_DASHBOARD_PANELS", str(_DEFAULT_PANELS)))
    return max(2, min(raw, MAX_PANELS))


def timeout_ms() -> int:
    return max(1000, int(os.environ.get("PLUMB_DASHBOARD_TIMEOUT_MS", str(_DEFAULT_TIMEOUT_MS))))


def summary_enabled() -> bool:
    return os.environ.get("PLUMB_DASHBOARD_SUMMARY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def uniquify_columns(columns: list[str]) -> list[str]:
    """DuckDB allows duplicate aliases; Vega and findings need distinct names."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for col in columns:
        key = col.strip().strip('"').lower()
        count = seen.get(key, 0) + 1
        seen[key] = count
        out.append(col if count == 1 else f"{col}_{count}")
    return out


def normalize_sql(sql: str) -> str:
    """Collapse whitespace for deduplication — not a security transform."""
    return " ".join(sql.lower().split())


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _format_value(value: object) -> str:
    if value is None:
        return "(blank)"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    if isinstance(value, (int, float)):
        return f"{value:,}"
    return str(value)


def _format_label(value: object) -> str:
    if value is None:
        return chart.BLANK_LABEL
    return str(value)


def derive_finding(columns: list[str], rows: list[list], dtypes: dict[str, str]) -> str:
    """One line from the rows — every number must survive narration verification."""
    if not rows:
        return "No rows returned."
    if len(rows) == 1 and len(columns) == 1:
        return f"{columns[0]} is {_format_value(rows[0][0])}."

    dtypes = chart.enrich_dtypes(columns, rows, dtypes)
    temporal, quantitative, nominal = chart._classify(columns, dtypes)  # noqa: SLF001

    if len(rows) == 1 and quantitative:
        measure = quantitative[0]
        mi = columns.index(measure)
        return f"{measure} is {_format_value(rows[0][mi])}."

    if nominal and quantitative:
        cat = nominal[0]
        measure = quantitative[0]
        ci, mi = columns.index(cat), columns.index(measure)
        ranked = [
            row
            for row in rows
            if mi < len(row) and _is_numeric(row[mi])
        ]
        if ranked:
            best = max(ranked, key=lambda row: float(row[mi]))
            return (
                f"Highest {measure} is {_format_value(best[mi])} "
                f"({_format_label(best[ci] if ci < len(best) else None)})."
            )

    if quantitative:
        measure = quantitative[0]
        mi = columns.index(measure)
        values = [
            float(row[mi])
            for row in rows
            if mi < len(row) and _is_numeric(row[mi])
        ]
        if values:
            if len(values) == 1:
                return f"{measure} is {_format_value(values[0])}."
            return (
                f"{measure} ranges from {_format_value(min(values))} "
                f"to {_format_value(max(values))}."
            )

    if len(columns) == 1:
        return f"{len(rows)} distinct {columns[0]} values."

    return f"{len(rows)} rows returned."


def verified_finding(columns: list[str], rows: list[list], dtypes: dict[str, str]) -> str:
    finding = derive_finding(columns, rows, dtypes)
    if narrate.verify_narration(finding, rows):
        return finding
    return f"{len(rows)} rows returned."


def dedupe_panels(panels: list) -> list:
    """Drop panels whose SQL normalises to the same string."""
    seen: set[str] = set()
    out: list = []
    for panel in panels:
        sql = getattr(panel, "sql", None) or ""
        key = normalize_sql(sql)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(panel)
    return out
