"""Assemble the Vega-Lite spec in Python.

The model only picks a chart type and column names. A model-authored spec is
never used: Vega-Lite renders an invalid spec as a blank chart rather than
throwing, so a bad spec would fail silently.
"""

from __future__ import annotations

from backend.guard import match_column
from backend.models import Plan

MAX_ROWS = 50
MIN_ROWS = 2
_TEMPORAL = ("DATE", "TIMESTAMP", "TIME")
_QUANTITATIVE = (
    "INT",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "HUGEINT",
    "UBIGINT",
    "UINTEGER",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "DECIMAL",
    "NUMERIC",
)


def vega_type(dtype: str) -> str:
    """Map a DuckDB dtype onto a Vega-Lite field type."""
    upper = (dtype or "").upper()
    if upper.startswith(_TEMPORAL):
        return "temporal"
    if upper.startswith(_QUANTITATIVE):
        return "quantitative"
    return "nominal"


def build_spec(
    plan: Plan, columns: list[str], rows: list[list], dtypes: dict[str, str]
) -> dict | None:
    """Vega-Lite spec without `data` — the caller injects the rows."""
    if plan.chart == "none" or not plan.chart_x or not plan.chart_y:
        return None
    if not (MIN_ROWS <= len(rows) <= MAX_ROWS):
        return None

    x = match_column(plan.chart_x, columns)
    if x is None:
        return None
    ys = [match_column(y, columns) for y in plan.chart_y]
    if not ys or any(y is None for y in ys):
        return None

    def field_type(column: str) -> str:
        key = match_column(column, list(dtypes)) or column
        return vega_type(dtypes.get(key, ""))

    y = ys[0]
    mark = {"bar": "bar", "line": "line", "pie": "arc", "scatter": "point"}[plan.chart]
    title = f"{y} by {x}"

    if plan.chart == "pie":
        return {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "mark": {"type": "arc"},
            "encoding": {
                "theta": {"field": y, "type": "quantitative"},
                "color": {"field": x, "type": "nominal"},
                "tooltip": [
                    {"field": x, "type": field_type(x)},
                    {"field": y, "type": "quantitative"},
                ],
            },
        }

    x_encoding: dict = {"field": x, "type": field_type(x), "title": x}
    if plan.chart == "bar" and x_encoding["type"] == "nominal":
        x_encoding["sort"] = {"field": y, "op": "sum", "order": "descending"}

    spec: dict = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": title,
        "mark": {"type": mark, "tooltip": True},
        "encoding": {
            "x": x_encoding,
            "y": {"field": y, "type": field_type(y), "title": y},
        },
    }
    if len(ys) > 1:
        spec["encoding"]["color"] = {"field": ys[1], "type": field_type(ys[1])}
    return spec
