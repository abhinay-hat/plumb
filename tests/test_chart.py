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


def test_visualization_kind_detects_bar_follow_up() -> None:
    assert chart.visualization_kind("can you give me in bar chart") == "bar"
    assert chart.visualization_kind("show as a line chart") == "line"
    assert chart.visualization_kind("Can you give me the platform wise pie chart?") == "pie"
    assert chart.visualization_kind("How many employees?") is None


def test_infer_axes_picks_category_and_measure() -> None:
    axes = chart.infer_axes(["stp_name", "sheet1_count"], {"stp_name": "VARCHAR", "sheet1_count": "BIGINT"})
    assert axes == ("stp_name", "sheet1_count")


def test_enrich_dtypes_infers_aggregate_aliases_from_rows() -> None:
    table = {"department": "VARCHAR"}
    enriched = chart.enrich_dtypes(
        ["department", "headcount"],
        [["Engineering", 12], ["Sales", 9]],
        table,
    )
    assert enriched["headcount"] == "BIGINT"
    assert chart.infer_axes(["department", "headcount"], enriched) == (
        "department",
        "headcount",
    )


def test_build_spec_for_question_infers_bar_when_plan_has_none() -> None:
    plan = Plan(route="answer", sql="SELECT 1", chart="none")
    columns = ["stp_name", "sheet1_count"]
    rows = [["A", 10], ["B", 5]]
    dtypes = {"stp_name": "VARCHAR", "sheet1_count": "BIGINT"}
    spec, kind = chart.build_spec_for_question(
        "can you give me in bar chart", plan, columns, rows, dtypes
    )
    assert kind == "bar"
    assert spec is not None
    assert spec["mark"]["type"] == "bar"


def test_build_spec_for_question_infers_bar_without_alias_in_table_schema() -> None:
    plan = Plan(route="answer", sql="SELECT 1", chart="none")
    columns = ["department", "headcount"]
    rows = [["Engineering", 12], ["Sales", 9]]
    table_dtypes = {"department": "VARCHAR"}
    spec, kind = chart.build_spec_for_question(
        "can you give me in bar chart", plan, columns, rows, table_dtypes
    )
    assert kind == "bar"
    assert spec is not None
    assert spec["encoding"]["y"]["type"] == "quantitative"


def test_second_measure_becomes_colour() -> None:
    columns = ["department", "headcount", "location"]
    rows = [["Engineering", 12, "Pune"], ["Sales", 9, "Remote"]]
    dtypes = {**DTYPES, "location": "VARCHAR"}
    plan = bar_plan(chart_y=["headcount", "location"])
    spec = chart.build_spec(plan, columns, rows, dtypes)
    assert spec["encoding"]["color"]["field"] == "location"
