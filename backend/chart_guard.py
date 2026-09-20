"""Validate model-authored Vega-Lite before it reaches the browser.

Vega-Lite renders invalid specs as blank charts rather than throwing, so every
field reference must be checked against the real result columns — the same
pattern as guard.py uses for SQL.
"""

from __future__ import annotations

import copy
import json

from backend import chart
from backend.guard import match_column

VEGA_LITE_V5_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
MAX_SPEC_BYTES = 8192
MAX_DEPTH = 6

VALID_MARKS = frozenset(
    {
        "arc",
        "area",
        "bar",
        "boxplot",
        "circle",
        "errorband",
        "errorbar",
        "image",
        "line",
        "point",
        "rect",
        "rule",
        "square",
        "text",
        "tick",
        "trail",
    }
)

_ALLOWED_TRANSFORMS = frozenset(
    {
        "bin",
        "aggregate",
        "calculate",
        "filter",
        "joinaggregate",
        "window",
        "fold",
        "stack",
        "timeUnit",
        "loess",
        "regression",
    }
)

_RECURSE_KEYS = frozenset(
    {
        "encoding",
        "layer",
        "facet",
        "spec",
        "transform",
        "repeat",
        "concat",
        "hconcat",
        "vconcat",
        "row",
        "column",
    }
)


class ChartSpecError(Exception):
    """A model-authored chart spec was rejected before rendering."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def primary_mark(spec: dict) -> str | None:
    """The mark type actually drawn — for audit and chart_advice.rendered."""
    mark = spec.get("mark")
    if mark is not None:
        return mark.get("type") if isinstance(mark, dict) else str(mark)
    for layer in spec.get("layer") or []:
        if not isinstance(layer, dict):
            continue
        layer_mark = layer.get("mark")
        if layer_mark is not None:
            return (
                layer_mark.get("type")
                if isinstance(layer_mark, dict)
                else str(layer_mark)
            )
    return None


def _depth(node: object, current: int = 0) -> int:
    if current > MAX_DEPTH:
        return current
    if isinstance(node, dict):
        if not node:
            return current + 1
        return max(_depth(value, current + 1) for value in node.values())
    if isinstance(node, list):
        if not node:
            return current + 1
        return max(_depth(item, current + 1) for item in node)
    return current + 1


def _mark_type(mark: object) -> str | None:
    if mark is None:
        return None
    if isinstance(mark, str):
        return mark
    if isinstance(mark, dict):
        raw = mark.get("type")
        return str(raw) if raw is not None else None
    return None


def _validate_mark(mark: object, *, where: str) -> None:
    kind = _mark_type(mark)
    if kind is None:
        raise ChartSpecError("missing_mark", f"chart spec {where} has no mark type")
    if kind not in VALID_MARKS:
        raise ChartSpecError(
            "invalid_mark",
            f"mark type {kind!r} is not a Vega-Lite mark",
        )


def _rewrite_field(name: str, columns: list[str]) -> str:
    canonical = match_column(name, columns)
    if canonical is None:
        raise ChartSpecError(
            "unknown_field",
            f"field {name!r} is not a column in the query result",
        )
    return canonical


def _walk_fields(node: object, columns: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "field" and isinstance(value, str):
                node[key] = _rewrite_field(value, columns)
            elif key in _RECURSE_KEYS or key not in ("mark", "data", "$schema"):
                _walk_fields(value, columns)
    elif isinstance(node, list):
        for item in node:
            _walk_fields(item, columns)


def _validate_transforms(node: object) -> None:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key == "transform":
                transforms = value if isinstance(value, list) else [value]
                for step in transforms:
                    if not isinstance(step, dict):
                        raise ChartSpecError(
                            "invalid_transform",
                            "each transform step must be an object",
                        )
                    keys = set(step) - {"as"}
                    unknown = keys - _ALLOWED_TRANSFORMS
                    if unknown:
                        raise ChartSpecError(
                            "forbidden_transform",
                            f"transform {next(iter(unknown))!r} is not allowed",
                        )
            elif key in _RECURSE_KEYS:
                _validate_transforms(value)
    elif isinstance(node, list):
        for item in node:
            _validate_transforms(item)


def _validate_marks(node: object, *, path: str = "root") -> None:
    if isinstance(node, dict):
        if "mark" in node:
            _validate_mark(node["mark"], where=f"at {path}")
        for key in _RECURSE_KEYS:
            if key not in node:
                continue
            child = node[key]
            if key in ("layer", "concat", "hconcat", "vconcat") and isinstance(child, list):
                for i, item in enumerate(child):
                    _validate_marks(item, path=f"{path}.{key}[{i}]")
            elif key in ("repeat", "facet") and isinstance(child, dict):
                _validate_marks(child, path=f"{path}.{key}")
                nested = child.get("spec")
                if nested is not None:
                    _validate_marks(nested, path=f"{path}.{key}.spec")
            elif isinstance(child, (dict, list)):
                _validate_marks(child, path=f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _validate_marks(item, path=f"{path}[{i}]")


def _reject_dollar_keys(node: object) -> None:
    if isinstance(node, dict):
        for key in node:
            if key.startswith("$") and key != "$schema":
                raise ChartSpecError(
                    "forbidden_key",
                    f"key {key!r} is not allowed in a chart spec",
                )
            _reject_dollar_keys(node[key])
    elif isinstance(node, list):
        for item in node:
            _reject_dollar_keys(item)


def _handle_data(spec: dict) -> None:
    data = spec.get("data")
    if data is None:
        return
    if not isinstance(data, dict):
        raise ChartSpecError("invalid_data", "data must be an object when present")
    if "url" in data:
        raise ChartSpecError(
            "external_data",
            "chart spec must not load data from a URL — rows are injected server-side",
        )
    spec.pop("data", None)


def validate_spec(spec: dict, columns: list[str], rows: list[list]) -> dict:
    """Return a spec safe to render, or raise ChartSpecError."""
    if not isinstance(spec, dict):
        raise ChartSpecError("invalid_spec", "chart_spec must be a JSON object")

    if not (chart.MIN_ROWS <= len(rows) <= chart.MAX_ROWS):
        raise ChartSpecError(
            "row_count",
            f"{len(rows)} rows — charts need between {chart.MIN_ROWS} and "
            f"{chart.MAX_ROWS} rows",
        )

    encoded = json.dumps(spec, separators=(",", ":"))
    if len(encoded) > MAX_SPEC_BYTES:
        raise ChartSpecError(
            "spec_too_large",
            f"chart spec is {len(encoded)} bytes; the limit is {MAX_SPEC_BYTES}",
        )
    if _depth(spec) > MAX_DEPTH:
        raise ChartSpecError(
            "spec_too_deep",
            f"chart spec nests deeper than {MAX_DEPTH} levels",
        )

    out = copy.deepcopy(spec)
    _reject_dollar_keys(out)
    _handle_data(out)
    _validate_transforms(out)
    _validate_marks(out)
    _walk_fields(out, columns)
    if primary_mark(out) is None:
        raise ChartSpecError("missing_mark", "chart spec has no mark")
    out["$schema"] = VEGA_LITE_V5_SCHEMA
    return out
