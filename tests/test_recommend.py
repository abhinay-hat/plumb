"""The chart recommendation is read off the result rows, not the question."""

from __future__ import annotations

from backend import chart


def test_a_date_axis_with_intervals_wants_a_line() -> None:
    rows = [["2026-01-01", 10], ["2026-02-01", 14], ["2026-03-01", 9]]
    advice = chart.recommend(["month", "revenue"], rows, {"month": "DATE", "revenue": "BIGINT"})
    assert advice.kind == "line"
    assert advice.x == "month" and advice.y == "revenue"
    assert "3 points" in advice.reason


def test_two_dates_are_a_segment_not_a_trend() -> None:
    rows = [["2026-01-01", 10], ["2026-02-01", 14]]
    advice = chart.recommend(["month", "revenue"], rows, {"month": "DATE", "revenue": "BIGINT"})
    assert advice.kind == "bar"
    assert "too few intervals" in advice.reason


def test_even_slices_offer_a_pie_as_well_as_bars() -> None:
    rows = [["north", 25], ["south", 25], ["east", 25], ["west", 25]]
    advice = chart.recommend(["region", "sales"], rows, {"region": "VARCHAR", "sales": "BIGINT"})
    assert advice.kind in {"bar", "pie"}
    assert "pie" in advice.alternatives or advice.kind == "pie"


def test_a_sliver_slice_keeps_the_pie_out_of_the_recommendation() -> None:
    rows = [["a", 1000], ["b", 900], ["c", 800], ["d", 1]]
    advice = chart.recommend(["team", "spend"], rows, {"team": "VARCHAR", "spend": "BIGINT"})
    assert advice.kind == "bar"
    assert advice.alternatives == [] or "pie" not in advice.alternatives[:1]


def test_a_negative_measure_is_never_a_pie() -> None:
    rows = [["a", 5], ["b", -5], ["c", 5]]
    advice = chart.recommend(["team", "delta"], rows, {"team": "VARCHAR", "delta": "BIGINT"})
    assert "pie" not in advice.alternatives and advice.kind != "pie"


def test_two_measures_and_no_category_is_a_scatter() -> None:
    rows = [[1, 2], [3, 5], [6, 9], [8, 12]]
    advice = chart.recommend(["tenure", "salary"], rows, {"tenure": "BIGINT", "salary": "BIGINT"})
    assert advice.kind == "scatter"
    assert advice.x == "tenure" and advice.y == "salary"


def test_one_row_is_a_number_not_a_chart() -> None:
    advice = chart.recommend(["total"], [[42]], {"total": "BIGINT"})
    assert advice.kind == "none"
    assert "table" in advice.reason


def test_too_many_rows_says_how_to_make_it_plottable() -> None:
    rows = [[f"r{i}", i] for i in range(chart.MAX_ROWS + 5)]
    advice = chart.recommend(["name", "score"], rows, {"name": "VARCHAR", "score": "BIGINT"})
    assert advice.kind == "none"
    assert "top-N" in advice.reason


def test_text_only_results_have_nothing_to_measure() -> None:
    rows = [["a", "x"], ["b", "y"]]
    advice = chart.recommend(["code", "label"], rows, {"code": "VARCHAR", "label": "VARCHAR"})
    assert advice.kind == "none"
    assert "numeric" in advice.reason


def test_ohlc_columns_name_the_chart_plumb_cannot_draw() -> None:
    rows = [
        ["2026-01-01", 1.0, 2.0, 0.5, 1.5],
        ["2026-01-02", 1.5, 2.5, 1.0, 2.0],
        ["2026-01-03", 2.0, 3.0, 1.5, 2.5],
    ]
    advice = chart.recommend(
        ["day", "open", "high", "low", "close"],
        rows,
        {
            "day": "DATE",
            "open": "DOUBLE",
            "high": "DOUBLE",
            "low": "DOUBLE",
            "close": "DOUBLE",
        },
    )
    assert advice.unsupported == "candlestick"
    assert advice.kind == "line"


def test_a_year_column_reads_as_an_axis_not_as_categories() -> None:
    """EXTRACT(year ...) is never a DATE dtype, but it is still continuous."""
    rows = [["2022", 10], ["2023", 14], ["2024", 9], ["2025", 12]]
    advice = chart.recommend(
        ["hire_year", "headcount"], rows, {"hire_year": "VARCHAR", "headcount": "BIGINT"}
    )
    assert advice.kind == "line"


def test_uneven_numeric_categories_stay_categories() -> None:
    rows = [["101", 10], ["250", 14], ["999", 9]]
    advice = chart.recommend(
        ["store_code", "sales"], rows, {"store_code": "VARCHAR", "sales": "BIGINT"}
    )
    assert advice.kind in {"bar", "pie"}


def test_a_blank_category_is_counted_like_any_other() -> None:
    """It gets drawn as a `(blank)` bar, so the reason must count it too."""
    rows = [["Sales", 11], ["HR", 12], [None, 4]]
    advice = chart.recommend(
        ["department", "headcount"], rows, {"department": "VARCHAR", "headcount": "BIGINT"}
    )
    assert "3 categories" in advice.reason
