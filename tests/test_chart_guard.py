"""chart_guard rejects bad Vega-Lite before it reaches the browser."""

from __future__ import annotations

import copy

import pytest

from backend import chart
from backend.chart_guard import ChartSpecError, validate_spec

COLUMNS = ["department", "headcount", "salary"]
ROWS = [
    ["Engineering", 12, 90000],
    ["Sales", 9, 75000],
    ["HR", 3, 65000],
]


def _histogram() -> dict:
    return {
        "mark": "bar",
        "encoding": {
            "x": {"field": "salary", "type": "quantitative", "bin": True},
            "y": {"aggregate": "count"},
        },
    }


def _boxplot() -> dict:
    return {
        "mark": "boxplot",
        "encoding": {
            "x": {"field": "department", "type": "nominal"},
            "y": {"field": "salary", "type": "quantitative"},
        },
    }


def test_hallucinated_field_is_rejected() -> None:
    spec = {
        "mark": "bar",
        "encoding": {
            "x": {"field": "not_a_column", "type": "nominal"},
            "y": {"field": "headcount", "type": "quantitative"},
        },
    }
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(spec, COLUMNS, ROWS)
    assert exc.value.code == "unknown_field"
    assert "not_a_column" in exc.value.message


def test_case_insensitive_field_is_rewritten() -> None:
    spec = {
        "mark": "bar",
        "encoding": {
            "x": {"field": "Department", "type": "nominal"},
            "y": {"field": "Headcount", "type": "quantitative"},
        },
    }
    out = validate_spec(spec, COLUMNS, ROWS)
    assert out["encoding"]["x"]["field"] == "department"
    assert out["encoding"]["y"]["field"] == "headcount"


def test_data_url_is_rejected() -> None:
    spec = {
        "data": {"url": "https://example.com/data.json"},
        "mark": "bar",
        "encoding": {
            "x": {"field": "department", "type": "nominal"},
            "y": {"field": "headcount", "type": "quantitative"},
        },
    }
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(spec, COLUMNS, ROWS)
    assert exc.value.code == "external_data"


def test_inline_data_is_stripped() -> None:
    spec = {
        "data": {"values": [{"department": "x", "headcount": 1}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "department", "type": "nominal"},
            "y": {"field": "headcount", "type": "quantitative"},
        },
    }
    out = validate_spec(spec, COLUMNS, ROWS)
    assert "data" not in out


def test_invented_mark_is_rejected() -> None:
    spec = {
        "mark": "candlestick",
        "encoding": {
            "x": {"field": "department", "type": "nominal"},
            "y": {"field": "headcount", "type": "quantitative"},
        },
    }
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(spec, COLUMNS, ROWS)
    assert exc.value.code == "invalid_mark"


def test_histogram_with_bin_passes() -> None:
    out = validate_spec(_histogram(), COLUMNS, ROWS)
    assert out["mark"] == "bar"
    assert out["encoding"]["x"]["bin"] is True


def test_boxplot_passes() -> None:
    out = validate_spec(_boxplot(), COLUMNS, ROWS)
    assert out["mark"] == "boxplot"


def test_layered_text_label_validates_every_layer() -> None:
    spec = {
        "encoding": {
            "x": {"field": "department", "type": "nominal"},
            "y": {"field": "headcount", "type": "quantitative"},
        },
        "layer": [
            {"mark": "bar"},
            {
                "mark": {"type": "text", "dy": -8},
                "encoding": {"text": {"field": "bogus_label", "type": "quantitative"}},
            },
        ],
    }
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(spec, COLUMNS, ROWS)
    assert "bogus_label" in exc.value.message

    good = copy.deepcopy(spec)
    good["layer"][1]["encoding"]["text"]["field"] = "headcount"
    out = validate_spec(good, COLUMNS, ROWS)
    assert out["layer"][1]["encoding"]["text"]["field"] == "headcount"


def test_eighty_rows_is_rejected() -> None:
    rows = [[f"d{i}", i, i * 1000] for i in range(80)]
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(_histogram(), COLUMNS, rows)
    assert exc.value.code == "row_count"
    assert "80 rows" in exc.value.message


def test_oversized_spec_is_rejected() -> None:
    spec = _histogram()
    spec["title"] = "x" * 9000
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(spec, COLUMNS, ROWS)
    assert exc.value.code == "spec_too_large"


def test_deeply_nested_spec_is_rejected() -> None:
    spec: dict = {"mark": "bar", "encoding": {"x": {"field": "department"}}}
    node: dict = spec
    for _ in range(8):
        node = node.setdefault("wrap", {})
    node["mark"] = "point"
    node["encoding"] = {"y": {"field": "headcount"}}
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(spec, COLUMNS, ROWS)
    assert exc.value.code == "spec_too_deep"


def test_panel_spec_is_validated_against_its_own_columns_only() -> None:
    """A field from another panel's result must not slip through."""
    panel_a_columns = ["department", "headcount"]
    panel_a_rows = [["Engineering", 12], ["Sales", 9], ["HR", 3]]
    panel_b_spec = {
        "mark": "bar",
        "encoding": {
            "x": {"field": "avg_salary", "type": "nominal"},
            "y": {"field": "headcount", "type": "quantitative"},
        },
    }
    with pytest.raises(ChartSpecError) as exc:
        validate_spec(panel_b_spec, panel_a_columns, panel_a_rows)
    assert "avg_salary" in exc.value.message


def test_validate_returns_a_copy() -> None:
    spec = _boxplot()
    original = copy.deepcopy(spec)
    out = validate_spec(spec, COLUMNS, ROWS)
    assert out is not spec
    assert spec == original
    assert out["$schema"].endswith("/v5.json")
