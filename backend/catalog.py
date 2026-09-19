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
_CASE_VARIANT_DISTINCT_CAP = 10_000
_CASE_VARIANT_ROW_CAP = 500_000
_HISTORY_RPE_THRESHOLD = 1.15
_HISTORY_DATE_HINTS = ("effective", "valid", "start", "as_of", "date")
_FK_IDENT = re.compile(r"^-- \S+\.(\S+) likely references ")
_AGG_COL = re.compile(
    r"\b(?:avg|sum|min|max|count)\s*\(\s*(?:distinct\s+)?"
    r"(?:(?P<qident>\"[^\"]+\"(?:\.\"[^\"]+\")*)|(?P<ident>[\w.*]+))\s*\)",
    re.IGNORECASE,
)

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

    skip_case = row_count > _CASE_VARIANT_ROW_CAP
    columns: list[ColumnInfo] = []
    for i, (name, dtype, *_rest) in enumerate(described):
        q = _quote(name)
        samples = con.execute(
            f"SELECT DISTINCT {q} FROM {_quote(table)} WHERE {q} IS NOT NULL LIMIT 3"
        ).fetchall()
        null_count = int(stats[i * 2])
        distinct_count = int(stats[i * 2 + 1])
        col = ColumnInfo(
            name=originals[i] if i < len(originals) and originals[i] else name,
            dtype=str(dtype),
            null_count=null_count,
            distinct_count=distinct_count,
            samples=[str(s[0]) for s in samples],
            null_pct=round(100.0 * null_count / row_count, 1) if row_count else 0.0,
        )
        if (
            not skip_case
            and _is_varchar(col.dtype)
            and 0 < distinct_count <= _CASE_VARIANT_DISTINCT_CAP
        ):
            _attach_case_variants(con, table, col, name)
        columns.append(col)
    return TableInfo(name=table, row_count=row_count, columns=columns)


def _is_varchar(dtype: str) -> bool:
    return dtype.upper().startswith("VARCHAR")


def _is_temporal(dtype: str) -> bool:
    upper = dtype.upper()
    return upper == "DATE" or upper.startswith("TIMESTAMP") or upper.startswith("DATETIME")


def _attach_case_variants(
    con: duckdb.DuckDBPyConnection, table: str, col: ColumnInfo, ident: str
) -> None:
    """Fold VARCHAR values; record collisions like Hyderabad vs hyderabad."""
    q, tq = _quote(ident), _quote(table)
    folded = con.execute(
        f"SELECT count(DISTINCT lower(trim(CAST({q} AS VARCHAR)))) "
        f"FROM {tq} WHERE {q} IS NOT NULL"
    ).fetchone()[0]
    if int(folded) == col.distinct_count:
        return
    col.case_variant_count = int(folded)
    groups = con.execute(
        f"WITH variants AS ("
        f"  SELECT CAST({q} AS VARCHAR) AS raw, "
        f"         lower(trim(CAST({q} AS VARCHAR))) AS folded, "
        f"         count(*) AS n "
        f"  FROM {tq} WHERE {q} IS NOT NULL "
        f"  GROUP BY 1, 2"
        f") "
        f"SELECT list(raw || ' (' || CAST(n AS VARCHAR) || ')' "
        f"            ORDER BY n DESC, raw) "
        f"FROM variants GROUP BY folded HAVING count(*) > 1 "
        f"ORDER BY sum(n) DESC LIMIT 3"
    ).fetchall()
    col.case_variant_examples = [" / ".join(row[0]) for row in groups if row[0]]


def _fk_column_idents(table_name: str) -> set[str]:
    found: set[str] = set()
    for line in FOREIGN_KEYS.get(table_name, []):
        match = _FK_IDENT.match(line)
        if match:
            found.add(match.group(1))
    return found


def _pick_history_date(table: TableInfo) -> str | None:
    dated = [
        ident
        for ident, col in zip(identifiers(table), table.columns)
        if _is_temporal(col.dtype)
    ]
    if not dated:
        return None
    for hint in _HISTORY_DATE_HINTS:
        for ident in dated:
            if hint in ident.lower():
                return ident
    return dated[0]


def _profile_grain(table: TableInfo) -> None:
    """Detect the entity a table repeats over, and whether it is a history table.

    Candidates are foreign keys plus `*_id` columns. The winner is the column
    with the highest row-count coverage (non-null rows, then distinct count),
    so a unique employee_id beats a repeating department FK. History requires
    rows_per_entity >= 1.15 *and* a DATE/TIMESTAMP column — 1.0 is an entity
    table, and a little above 1.0 is usually dirt rather than SCD-2.
    """
    table.grain_column = None
    table.grain_entities = None
    table.rows_per_entity = None
    table.is_history_table = False
    table.history_date_column = None
    if not table.row_count or not table.columns:
        return
    fk_idents = _fk_column_idents(table.name)
    candidates: list[tuple[int, int, str, float]] = []
    for ident, col in zip(identifiers(table), table.columns):
        if col.distinct_count <= 0:
            continue
        if ident not in fk_idents and not ident.endswith("_id"):
            continue
        coverage = table.row_count - col.null_count
        rpe = table.row_count / col.distinct_count
        candidates.append((coverage, col.distinct_count, ident, rpe))
    if not candidates:
        return
    _coverage, entities, ident, rpe = max(candidates, key=lambda c: (c[0], c[1]))
    table.grain_column = ident
    table.grain_entities = entities
    table.rows_per_entity = round(rpe, 2)
    date_col = _pick_history_date(table)
    if table.rows_per_entity >= _HISTORY_RPE_THRESHOLD and date_col:
        table.is_history_table = True
        table.history_date_column = date_col


def aggregate_coverage(sql: str, tables: list[TableInfo]) -> dict | None:
    """If SQL aggregates a column with null_pct > 1, return covered/total."""
    if not sql:
        return None
    best: dict | None = None
    best_pct = 1.0
    for match in _AGG_COL.finditer(sql):
        raw = match.group("qident") or match.group("ident") or ""
        token = raw.replace('"', "").split(".")[-1].strip()
        if not token or token == "*":
            continue
        token_l = token.lower()
        for t in tables:
            for ident, col in zip(identifiers(t), t.columns):
                if ident.lower() != token_l or col.null_pct <= 1:
                    continue
                if best is None or col.null_pct > best_pct:
                    best_pct = col.null_pct
                    best = {
                        "column": ident,
                        "covered": t.row_count - col.null_count,
                        "total": t.row_count,
                    }
    return best


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
    for t in tables:
        _profile_grain(t)
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
    for t in tables:
        _profile_grain(t)
    return con, tables


def _case_variant_note(ident: str, col: ColumnInfo) -> str:
    group = col.case_variant_examples[0] if col.case_variant_examples else ""
    pretty: list[str] = []
    for part in (p.strip() for p in group.split(" / ") if p.strip()):
        match = re.match(r"^(.*) \((\d+)\)$", part)
        if match:
            pretty.append(f"'{match.group(1)}'({match.group(2)})")
        else:
            pretty.append(part)
    if len(pretty) == 2:
        shown = f"{pretty[0]} and {pretty[1]}"
    elif pretty:
        shown = ", ".join(pretty)
    else:
        shown = "values"
    return (
        f"{col.distinct_count} raw distinct, {col.case_variant_count} case-insensitive. "
        f"{shown} are the same value. Group on lower({ident})."
    )


def _table_shape_comments(table: TableInfo) -> list[str]:
    """Warnings that sit immediately after CREATE TABLE, before anything trimable."""
    if table.is_history_table and table.grain_column and table.grain_entities is not None:
        grain = table.grain_column
        date_col = table.history_date_column or "date"
        lines = [
            f"-- {table.name}: {table.row_count} rows, "
            f"{table.grain_entities} distinct {grain} "
            f"({table.rows_per_entity} rows per {grain}).",
            f"-- HISTORY TABLE: each row is a point in time, keyed by {date_col}.",
            f"-- For current values, take the latest {date_col} per {grain}.",
            "-- Do NOT average across rows — that weights employees by how many records they have.",
        ]
    else:
        lines = [f"-- {table.name}: {table.row_count} rows"]
    if table.row_count > _CASE_VARIANT_ROW_CAP:
        lines.append(
            f"-- case-variant check skipped: table has {table.row_count} rows"
        )
    return lines


def _ddl(table: TableInfo, with_samples: bool, with_case: bool = True) -> str:
    lines = [f"CREATE TABLE {table.name} ("]
    idents = identifiers(table)
    last = len(table.columns) - 1
    skip_case_table = table.row_count > _CASE_VARIANT_ROW_CAP
    for i, (ident, col) in enumerate(zip(idents, table.columns)):
        notes: list[str] = []
        if with_case and col.case_variant_count is not None:
            notes.append(_case_variant_note(ident, col))
        else:
            notes.append(f"{col.distinct_count} distinct")
            if (
                with_case
                and not skip_case_table
                and _is_varchar(col.dtype)
                and col.distinct_count > _CASE_VARIANT_DISTINCT_CAP
            ):
                notes.append("case-variant check skipped (>10000 distinct)")
        if col.null_pct > 1 and table.row_count:
            covered = table.row_count - col.null_count
            notes.append(
                f"{col.null_count} of {table.row_count} null ({col.null_pct}%). "
                f"avg() covers {covered} rows."
            )
        elif col.null_count:
            notes.append(f"{col.null_count} null")
        if with_samples and col.samples:
            notes.append("e.g. " + ", ".join(col.samples))
        decl = f"  {ident} {col.dtype}" + ("" if i == last else ",")
        lines.append(decl.ljust(28) + "-- " + ", ".join(notes))
    lines.append(");")
    lines.extend(_table_shape_comments(table))
    return "\n".join(lines)


def render_schema(
    tables: list[TableInfo], foreign_keys: dict[str, list[str]] | None = None
) -> str:
    """Render CREATE TABLE DDL with profiling comments for the model prompt."""
    fks = FOREIGN_KEYS if foreign_keys is None else foreign_keys
    card = ""
    for with_samples, with_fks, with_case in (
        (True, True, True),
        (False, True, True),
        (False, False, True),
        (False, False, False),
    ):
        blocks = []
        for t in tables:
            block = _ddl(t, with_samples, with_case=with_case)
            if with_fks:
                block += "".join("\n" + line for line in fks.get(t.name, []))
            blocks.append(block)
        card = "\n\n".join(blocks)
        if len(card) <= _MAX_SCHEMA_CHARS:
            return card
    # History-table warnings prevent a wrong number. A sliced card that drops
    # them is worse than one that overruns the token cap by a few hundred chars.
    if any(t.is_history_table for t in tables):
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
