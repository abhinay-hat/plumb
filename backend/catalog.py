"""Ingest spreadsheets into DuckDB and profile them into a schema card.

The DuckDB identifier for a column is derived deterministically from the
original header by `clean_names`, so no mapping needs to be carried around:
`ColumnInfo.name` keeps the original header and any consumer that needs the
queryable identifier re-derives it from the ordered column list.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import duckdb
import pandas as pd

from backend.models import ColumnInfo, TableInfo

_MAX_SCHEMA_CHARS = 10_000  # ~2500 tokens at 4 chars/token
_DATE_SHAPES = (
    ("iso", re.compile(r"^\s*\d{4}-\d{1,2}-\d{1,2}\s*$"), None),
    ("dmy", re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4}\s*$"), "%d/%m/%Y"),
)
_DATE_CONVERSION_THRESHOLD = 0.9
_FK_CONTAINMENT_THRESHOLD = 0.8

# Populated by `ingest`, read by `render_schema`. Keyed by table name; a repeat
# ingest of the same table simply overwrites its entry.
FOREIGN_KEYS: dict[str, list[str]] = {}


def clean_names(originals: list[str]) -> list[str]:
    """Map original headers to unique snake_case DuckDB identifiers."""
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, raw in enumerate(originals):
        base = re.sub(r"[^0-9a-z]+", "_", str(raw or "").strip().lower()).strip("_")
        if not base:
            base = f"column_{i + 1}"
        if base[0].isdigit():
            base = f"c_{base}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        out.append(base if count == 1 else f"{base}_{count}")
    return out


def identifiers(table: TableInfo) -> list[str]:
    """DuckDB identifiers for a table's columns, in column order."""
    return clean_names([c.name for c in table.columns])


def _table_name(stem: str, sheet: str | None = None) -> str:
    parts = [stem] if sheet is None else [stem, sheet]
    return clean_names(["_".join(parts)])[0]


def _read_headers(path: Path, delimiter: str) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh, delimiter=delimiter):
            return row
    return []


def _load_delimited(con: duckdb.DuckDBPyConnection, path: Path, table: str) -> None:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    names = clean_names(_read_headers(path, delimiter))
    args = (str(path), names, delimiter)
    try:
        con.execute(
            "CREATE OR REPLACE TABLE "
            + _quote(table)
            + " AS SELECT * FROM read_csv(?, header=true, names=?, delim=?, "
            "sample_size=-1, null_padding=true)",
            args,
        )
    except duckdb.Error:
        con.execute(
            "CREATE OR REPLACE TABLE "
            + _quote(table)
            + " AS SELECT * FROM read_csv(?, header=true, names=?, delim=?, "
            "all_varchar=true, null_padding=true, ignore_errors=true)",
            args,
        )


def _load_excel(con: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, list[str]]]:
    raw = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    loaded: list[tuple[str, list[str]]] = []
    for sheet, head_df in raw.items():
        originals = [
            "" if pd.isna(v) else str(v) for v in (head_df.iloc[0] if len(head_df) else [])
        ]
        names = clean_names(originals)
        frame = pd.read_excel(path, sheet_name=sheet, header=0, names=names)
        table = _table_name(path.stem, sheet)
        con.register("_plumb_stage", frame)
        con.execute(f"CREATE OR REPLACE TABLE {_quote(table)} AS SELECT * FROM _plumb_stage")
        con.unregister("_plumb_stage")
        loaded.append((table, originals))
    return loaded


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _convert_date_columns(con: duckdb.DuckDBPyConnection, table: str) -> None:
    """Retype VARCHAR columns that parse as dates for >90% of non-null values."""
    varchar_cols = [
        row[0]
        for row in con.execute(f"DESCRIBE {_quote(table)}").fetchall()
        if row[1].upper().startswith("VARCHAR")
    ]
    for col in varchar_cols:
        q = _quote(col)
        non_null = con.execute(
            f"SELECT count({q}) FROM {_quote(table)}"
        ).fetchone()[0]
        if not non_null:
            continue
        sample = con.execute(
            f"SELECT {q} FROM {_quote(table)} WHERE {q} IS NOT NULL LIMIT 20"
        ).fetchall()
        for _, shape, fmt in _DATE_SHAPES:
            if not any(shape.match(str(v[0])) for v in sample):
                continue
            expr = (
                f"TRY_CAST({q} AS DATE)"
                if fmt is None
                else f"TRY_CAST(try_strptime({q}, '{fmt}') AS DATE)"
            )
            ok = con.execute(
                f"SELECT count({expr}) FROM {_quote(table)}"
            ).fetchone()[0]
            if ok / non_null > _DATE_CONVERSION_THRESHOLD:
                con.execute(
                    f"ALTER TABLE {_quote(table)} ALTER {q} TYPE DATE USING {expr}"
                )
                break


def _profile(
    con: duckdb.DuckDBPyConnection, table: str, originals: list[str]
) -> TableInfo:
    described = con.execute(f"DESCRIBE {_quote(table)}").fetchall()
    row_count = con.execute(f"SELECT count(*) FROM {_quote(table)}").fetchone()[0]
    if not described:
        return TableInfo(name=table, row_count=row_count, columns=[])
    parts = []
    for name, _dtype, *_rest in described:
        q = _quote(name)
        parts.append(f"count(*) - count({q})")
        parts.append(f"count(DISTINCT {q})")
    stats = con.execute(f"SELECT {', '.join(parts)} FROM {_quote(table)}").fetchone()

    columns: list[ColumnInfo] = []
    for i, (name, dtype, *_rest) in enumerate(described):
        q = _quote(name)
        samples = con.execute(
            f"SELECT DISTINCT {q} FROM {_quote(table)} WHERE {q} IS NOT NULL LIMIT 3"
        ).fetchall()
        columns.append(
            ColumnInfo(
                name=originals[i] if i < len(originals) and originals[i] else name,
                dtype=str(dtype),
                null_count=int(stats[i * 2]),
                distinct_count=int(stats[i * 2 + 1]),
                samples=[str(s[0]) for s in samples],
            )
        )
    return TableInfo(name=table, row_count=row_count, columns=columns)


def _detect_foreign_keys(
    con: duckdb.DuckDBPyConnection, tables: list[TableInfo]
) -> dict[str, list[str]]:
    """Heuristic FK comments: name match or _id match with >80% containment."""
    unique_cols: list[tuple[str, str]] = []
    for t in tables:
        for ident, col in zip(identifiers(t), t.columns):
            if t.row_count and col.distinct_count == t.row_count and not col.null_count:
                unique_cols.append((t.name, ident))

    found: dict[str, list[str]] = {t.name: [] for t in tables}
    for t in tables:
        for ident, col in zip(identifiers(t), t.columns):
            if col.distinct_count == 0:
                continue
            for target_table, target_col in unique_cols:
                if target_table == t.name and target_col == ident:
                    continue
                name_match = target_col == ident or (
                    ident.endswith("_id") and target_col.endswith("_id")
                )
                if not name_match:
                    continue
                try:
                    hits = con.execute(
                        f"SELECT count(*) FROM {_quote(t.name)} s "
                        f"WHERE s.{_quote(ident)} IS NOT NULL AND EXISTS "
                        f"(SELECT 1 FROM {_quote(target_table)} d "
                        f"WHERE d.{_quote(target_col)} = s.{_quote(ident)})"
                    ).fetchone()[0]
                except duckdb.Error:
                    continue  # incomparable types are simply not a foreign key
                non_null = t.row_count - col.null_count
                if non_null and hits / non_null > _FK_CONTAINMENT_THRESHOLD:
                    found[t.name].append(
                        f"-- {t.name}.{ident} likely references "
                        f"{target_table}.{target_col}"
                    )
                    break
    return found


def ingest(
    file_path: str, session_id: str
) -> tuple[duckdb.DuckDBPyConnection, list[TableInfo]]:
    """Load a spreadsheet into a fresh in-memory DuckDB and profile every table."""
    path = Path(file_path)
    con = duckdb.connect(database=":memory:")
    con.execute(f"SET temp_directory='{Path.cwd() / '.plumb_tmp'}'")
    suffix = path.suffix.lower()

    if suffix in (".csv", ".tsv"):
        table = _table_name(path.stem)
        delimiter = "\t" if suffix == ".tsv" else ","
        originals = _read_headers(path, delimiter)
        _load_delimited(con, path, table)
        loaded = [(table, originals)]
    elif suffix == ".xlsx":
        loaded = _load_excel(con, path)
    else:
        raise ValueError(f"unsupported file type for plumb ingest: {suffix or path.name}")

    tables: list[TableInfo] = []
    for table, originals in loaded:
        _convert_date_columns(con, table)
        tables.append(_profile(con, table, originals))

    FOREIGN_KEYS.update(_detect_foreign_keys(con, tables))
    return con, tables


def ingest_many(
    file_paths: list[str], session_id: str
) -> tuple[duckdb.DuckDBPyConnection, list[TableInfo]]:
    """Ingest several files into one connection so joins across them work."""
    con = duckdb.connect(database=":memory:")
    tables: list[TableInfo] = []
    for file_path in file_paths:
        single_con, single_tables = ingest(file_path, session_id)
        for t in single_tables:
            frame = single_con.execute(f"SELECT * FROM {_quote(t.name)}").df()
            con.register("_plumb_stage", frame)
            con.execute(
                f"CREATE OR REPLACE TABLE {_quote(t.name)} AS SELECT * FROM _plumb_stage"
            )
            con.unregister("_plumb_stage")
            tables.append(t)
        single_con.close()
    FOREIGN_KEYS.update(_detect_foreign_keys(con, tables))
    return con, tables


def _ddl(table: TableInfo, with_samples: bool) -> str:
    lines = [f"CREATE TABLE {table.name} ("]
    idents = identifiers(table)
    last = len(table.columns) - 1
    for i, (ident, col) in enumerate(zip(idents, table.columns)):
        notes = [f"{col.distinct_count} distinct"]
        if col.null_count:
            notes.append(f"{col.null_count} null")
        if with_samples and col.samples:
            notes.append("e.g. " + ", ".join(col.samples))
        decl = f"  {ident} {col.dtype}" + ("" if i == last else ",")
        lines.append(decl.ljust(28) + "-- " + ", ".join(notes))
    lines.append(");")
    lines.append(f"-- {table.name}: {table.row_count} rows")
    return "\n".join(lines)


def render_schema(
    tables: list[TableInfo], foreign_keys: dict[str, list[str]] | None = None
) -> str:
    """Render CREATE TABLE DDL with profiling comments for the model prompt."""
    fks = FOREIGN_KEYS if foreign_keys is None else foreign_keys
    for with_samples, with_fks in ((True, True), (False, True), (False, False)):
        blocks = []
        for t in tables:
            block = _ddl(t, with_samples)
            if with_fks:
                block += "".join("\n" + line for line in fks.get(t.name, []))
            blocks.append(block)
        card = "\n\n".join(blocks)
        if len(card) <= _MAX_SCHEMA_CHARS:
            return card
    return card[:_MAX_SCHEMA_CHARS]


def schema_dict(tables: list[TableInfo]) -> dict[str, dict[str, str]]:
    """Schema in the shape `guard.validate` needs: table -> column -> dtype."""
    return {
        t.name: {
            ident: col.dtype for ident, col in zip(identifiers(t), t.columns)
        }
        for t in tables
    }
