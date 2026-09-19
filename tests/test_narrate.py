"""Every number shown must be traceable to a returned row."""

import datetime

from backend import narrate

ROWS = [["Engineering", 12, 1450000.0], ["Sales", 9, 980000.5], ["HR", 3, 700000.0]]
COLUMNS = ["department", "headcount", "avg_salary"]


def test_numbers_present_in_rows_pass() -> None:
    text = "Counted rows in employees grouped by department. Engineering leads with 12."
    assert narrate.verify_narration(text, ROWS)


def test_row_count_is_allowed() -> None:
    assert narrate.verify_narration("3 rows returned.", ROWS)


def test_invented_total_fails() -> None:
    text = "Grouped by department. Across all teams there are 24 people."
    assert not narrate.verify_narration(text, ROWS)


def test_invented_percentage_fails() -> None:
    assert not narrate.verify_narration("Engineering is 50% of headcount.", ROWS)


def test_thousands_separators_are_normalised() -> None:
    assert narrate.verify_narration("The average is 1,450,000.", ROWS)


def test_decimals_are_rounded_to_two_places() -> None:
    assert narrate.verify_narration("Sales averages 980000.50.", ROWS)
    assert not narrate.verify_narration("Sales averages 980000.51.", ROWS)


def test_numbers_inside_string_cells_count() -> None:
    rows = [["2025-03-14", "north"]]
    assert narrate.verify_narration("The earliest date is 2025-03-14.", rows)


def test_dates_as_objects_count() -> None:
    rows = [[datetime.date(2025, 3, 14), 4]]
    assert narrate.verify_narration("Hiring peaked on 2025-03-14 with 4 joins.", rows)


def test_text_without_numbers_passes() -> None:
    assert narrate.verify_narration("Grouped employees by department.", ROWS)


def test_empty_rows_only_allow_zero() -> None:
    assert narrate.verify_narration("0 rows returned.", [])
    assert not narrate.verify_narration("7 rows returned.", [])


def test_narrate_falls_back_when_provider_is_unreachable(monkeypatch) -> None:
    monkeypatch.setenv("PLUMB_PROVIDER", "ollama")
    monkeypatch.setattr(narrate.llm, "OLLAMA_URL", "http://127.0.0.1:1/api/chat")
    text = narrate.narrate("how many?", "SELECT 1", COLUMNS, ROWS)
    assert text == "3 rows returned."
    assert narrate.verify_narration(text, ROWS)


def test_year_in_question_is_allowed() -> None:
    text = "Counted employees hired in 2025. 197 people joined."
    assert narrate.verify_narration(
        text, [[197]], question="How many people joined in 2025?"
    )


def test_invented_number_still_fails_even_with_a_year_in_the_question() -> None:
    text = "Counted 2025 hires. There were 999 people."
    assert not narrate.verify_narration(
        text, [[197]], question="How many people joined in 2025?"
    )


def test_coverage_omission_is_filled_in(monkeypatch) -> None:
    coverage = {"column": "performance_rating", "covered": 1248, "total": 1300}
    monkeypatch.setattr(
        narrate.llm,
        "complete",
        lambda *args, **kwargs: "The average performance rating is 3.19.",
    )
    text = narrate.narrate(
        "What's the average performance rating?",
        "SELECT AVG(performance_rating) FROM reviews",
        ["avg"],
        [[3.19]],
        coverage=coverage,
    )
    assert "1,248" in text or "1248" in text
    assert "1,300" in text or "1300" in text
    assert narrate.verify_narration(text, [[3.19]], coverage=coverage)


def test_iso_date_literal_is_not_parsed_as_negative_one() -> None:
    text = "Counted employees hired before 2021-01-01. 143 rows matched."
    assert narrate.verify_narration(text, [[143]])
    assert not narrate.verify_narration(
        "Counted employees hired before 2021-01-01. 999 rows matched.",
        [[143]],
        question="How many employees were hired before 2021?",
    )
