"""Ingestion must survive messy real-world spreadsheets."""

from pathlib import Path

import pandas as pd
import pytest

from backend import catalog

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_clean_names_blank_duplicate_and_punctuation() -> None:
    assert catalog.clean_names(["", "  ", "Order Date"]) == [
        "column_1",
        "column_2",
        "order_date",
    ]
    assert catalog.clean_names(["amt", "amt", "amt"]) == ["amt", "amt_2", "amt_3"]
    assert catalog.clean_names(["2024 total (₹)"]) == ["c_2024_total"]


def test_blank_headers(tmp_path: Path) -> None:
    path = write(tmp_path, "blank.csv", "id,,value\n1,x,10\n2,y,20\n")
    con, tables = catalog.ingest(path, "s")
    table = tables[0]
    assert table.row_count == 2
    assert catalog.identifiers(table)[1] == "column_2"
    assert con.execute("SELECT count(*) FROM blank").fetchone()[0] == 2


def test_duplicate_headers(tmp_path: Path) -> None:
    path = write(tmp_path, "dup.csv", "amt,amt,amt\n1,2,3\n4,5,6\n")
    _, tables = catalog.ingest(path, "s")
    assert catalog.identifiers(tables[0]) == ["amt", "amt_2", "amt_3"]
    assert [c.name for c in tables[0].columns] == ["amt", "amt", "amt"]


def test_headers_with_spaces_keep_original_name(tmp_path: Path) -> None:
    path = write(tmp_path, "spaced.csv", "Order Date,Net Amount!\n2024-01-01,5\n")
    _, tables = catalog.ingest(path, "s")
    assert [c.name for c in tables[0].columns] == ["Order Date", "Net Amount!"]
    assert catalog.identifiers(tables[0]) == ["order_date", "net_amount"]


def test_mixed_type_column_falls_back_to_varchar(tmp_path: Path) -> None:
    path = write(tmp_path, "mixed.csv", "k,v\n1,10\n2,abc\n3,2024-01-01\n4,\n")
    _, tables = catalog.ingest(path, "s")
    v = tables[0].columns[1]
    assert v.dtype.upper().startswith("VARCHAR")
    assert v.null_count == 1


def test_date_column_is_converted(tmp_path: Path) -> None:
    rows = "\n".join(f"{i},2024-01-{i:02d}" for i in range(1, 21))
    path = write(tmp_path, "dates.csv", f"id,d\n{rows}\n")
    _, tables = catalog.ingest(path, "s")
    assert tables[0].columns[1].dtype == "DATE"


def test_date_column_not_converted_below_threshold(tmp_path: Path) -> None:
    rows = "\n".join(f"{i},2024-01-{i:02d}" for i in range(1, 11))
    rows += "\n11,not a date\n12,also not\n"
    path = write(tmp_path, "halfdates.csv", f"id,d\n{rows}")
    _, tables = catalog.ingest(path, "s")
    assert tables[0].columns[1].dtype.upper().startswith("VARCHAR")


def test_dmy_dates_are_converted(tmp_path: Path) -> None:
    rows = "\n".join(f"{i},{i:02d}/03/2024" for i in range(1, 21))
    path = write(tmp_path, "dmy.csv", f"id,d\n{rows}\n")
    _, tables = catalog.ingest(path, "s")
    assert tables[0].columns[1].dtype == "DATE"


def test_tsv(tmp_path: Path) -> None:
    path = write(tmp_path, "t.tsv", "a\tb\n1\t2\n3\t4\n")
    _, tables = catalog.ingest(path, "s")
    assert tables[0].row_count == 2
    assert catalog.identifiers(tables[0]) == ["a", "b"]


def test_two_sheet_xlsx(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"id": [1, 2], "": ["x", "y"]}).to_excel(
            writer, sheet_name="Sales", index=False
        )
        pd.DataFrame({"region": ["N", "S"]}).to_excel(
            writer, sheet_name="Regions", index=False
        )
    con, tables = catalog.ingest(str(path), "s")
    names = sorted(t.name for t in tables)
    assert names == ["book_regions", "book_sales"]
    assert con.execute("SELECT count(*) FROM book_sales").fetchone()[0] == 2


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    path = write(tmp_path, "notes.txt", "hello")
    with pytest.raises(ValueError):
        catalog.ingest(path, "s")


def test_fixture_profile_and_schema_card() -> None:
    _, tables = catalog.ingest_many(
        [str(FIXTURES / "employees.csv"), str(FIXTURES / "departments.csv")], "s"
    )
    employees = next(t for t in tables if t.name == "employees")
    assert employees.row_count == 60
    by_name = {c.name: c for c in employees.columns}
    assert by_name["department"].null_count == 4
    assert by_name["performance_rating"].null_count == 2
    assert by_name["hire_date"].dtype == "DATE"
    assert all(len(c.samples) <= 3 for c in employees.columns)

    card = catalog.render_schema(tables)
    assert "CREATE TABLE employees (" in card
    assert "-- employees: 60 rows" in card
    assert "references departments.department" in card
    assert len(card) <= 10_000

    schema = catalog.schema_dict(tables)
    assert schema["employees"]["salary"].startswith("BIGINT")
    assert set(schema) == {"employees", "departments"}


def test_schema_card_drops_samples_when_too_long() -> None:
    _, tables = catalog.ingest_many([str(FIXTURES / "employees.csv")], "s")
    wide = catalog.render_schema(tables)
    assert "e.g." in wide
    original = catalog._MAX_SCHEMA_CHARS
    try:
        catalog._MAX_SCHEMA_CHARS = 420
        trimmed = catalog.render_schema(tables)
    finally:
        catalog._MAX_SCHEMA_CHARS = original
    assert "e.g." not in trimmed
    assert len(trimmed) < len(wide)
