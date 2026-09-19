"""Chart specs are assembled in Python, and refuse to guess."""

from backend import chart
from backend.models import Plan

COLUMNS = ["department", "headcount"]
ROWS = [["Engineering", 12], ["Sales", 9], ["HR", 3]]
DTYPES = {"department": "VARCHAR", "headcount": "BIGINT", "hire_month": "DATE"}


def bar_plan(**kwargs) -> Plan:
    base = dict(
        route="answer",
        sql="SELECT 1",
        chart="bar",
        chart_x="department",
        chart_y=["headcount"],
    )
    base.update(kwargs)
    return Plan(**base)


def test_vega_type_mapping() -> None:
    assert chart.vega_type("DATE") == "temporal"
    assert chart.vega_type("TIMESTAMP WITH TIME ZONE") == "temporal"
    assert chart.vega_type("BIGINT") == "quantitative"
    assert chart.vega_type("DECIMAL(18,3)") == "quantitative"
    assert chart.vega_type("VARCHAR") == "nominal"
    assert chart.vega_type("") == "nominal"


def test_bar_spec_has_no_data_and_sorts_descending() -> None:
    spec = chart.build_spec(bar_plan(), COLUMNS, ROWS, DTYPES)
    assert spec is not None
    assert "data" not in spec
    assert spec["mark"]["type"] == "bar"
    assert spec["encoding"]["x"]["sort"]["order"] == "descending"
    assert spec["encoding"]["y"]["field"] == "headcount"
    assert spec["title"]


def test_line_spec_uses_temporal_x() -> None:
    plan = bar_plan(chart="line", chart_x="hire_month", chart_y=["headcount"])
    columns = ["hire_month", "headcount"]
    rows = [["2025-01-01", 4], ["2025-02-01", 6]]
    spec = chart.build_spec(plan, columns, rows, DTYPES)
    assert spec["encoding"]["x"]["type"] == "temporal"
    assert "sort" not in spec["encoding"]["x"]


def test_pie_spec_uses_theta_and_color() -> None:
    spec = chart.build_spec(bar_plan(chart="pie"), COLUMNS, ROWS, DTYPES)
    assert spec["mark"]["type"] == "arc"
    assert spec["encoding"]["theta"]["field"] == "headcount"
    assert spec["encoding"]["color"]["field"] == "department"


def test_case_insensitive_column_match() -> None:
    plan = bar_plan(chart_x="Department", chart_y=["Headcount"])
    spec = chart.build_spec(plan, COLUMNS, ROWS, DTYPES)
    assert spec["encoding"]["x"]["field"] == "department"
    assert spec["encoding"]["y"]["field"] == "headcount"


def test_none_chart_returns_none() -> None:
    assert chart.build_spec(bar_plan(chart="none"), COLUMNS, ROWS, DTYPES) is None


def test_unknown_column_returns_none() -> None:
    assert chart.build_spec(bar_plan(chart_x="not_a_column"), COLUMNS, ROWS, DTYPES) is None
    assert chart.build_spec(bar_plan(chart_y=["nope"]), COLUMNS, ROWS, DTYPES) is None


def test_missing_axes_return_none() -> None:
    assert chart.build_spec(bar_plan(chart_x=None), COLUMNS, ROWS, DTYPES) is None
    assert chart.build_spec(bar_plan(chart_y=None), COLUMNS, ROWS, DTYPES) is None


def test_row_count_bounds() -> None:
    assert chart.build_spec(bar_plan(), COLUMNS, ROWS[:1], DTYPES) is None
    too_many = [[f"d{i}", i] for i in range(chart.MAX_ROWS + 1)]
    assert chart.build_spec(bar_plan(), COLUMNS, too_many, DTYPES) is None


def test_second_measure_becomes_colour() -> None:
    columns = ["department", "headcount", "location"]
    rows = [["Engineering", 12, "Pune"], ["Sales", 9, "Remote"]]
    dtypes = {**DTYPES, "location": "VARCHAR"}
    plan = bar_plan(chart_y=["headcount", "location"])
    spec = chart.build_spec(plan, columns, rows, dtypes)
    assert spec["encoding"]["color"]["field"] == "location"
