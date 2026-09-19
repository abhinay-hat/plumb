"""Ingest spreadsheets into DuckDB and profile them into a schema card.

The DuckDB identifier for a column is derived deterministically from the
original header by `clean_names`, so no mapping needs to be carried around:
`ColumnInfo.name` keeps the original header and any consumer that needs the
queryable identifier re-derives it from the ordered column list.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from backend.models import ColumnInfo, TableInfo

log = logging.getLogger("plumb.catalog")

_MAX_SCHEMA_CHARS = 10_000  # ~2500 tokens at 4 chars/token
_CHARS_PER_TOKEN = 4
_COMPACT_SAMPLE_COUNT = 2
_COMPACT_SAMPLE_DISTINCT_CAP = 50
_ENUM_DISTINCT_CAP = 8  # at or below this, name the values instead of counting
_NULL_NOTE_MIN_PCT = 1.0  # below this, a null note is noise
_PRUNE_MIN_TABLES = 3  # never send fewer than this
_PRUNE_MIN_SCORE = 3  # below this the question named nothing: send everything
_RARE_TOKEN_TABLES = 2  # a word on at most this many tables is a strong signal
_STOPWORDS = frozenset(
    {
        "what", "whats", "which", "many", "much", "show", "give", "list", "tell",
        "have", "has", "does", "each", "from", "with", "that", "this", "there",
        "their", "them", "they", "were", "when", "where", "about", "into",
        "over", "under", "than", "then", "some", "most", "least", "more",
        "less", "only", "just", "also", "been", "being", "will", "would",
        "could", "should", "please", "average", "total", "count", "number",
        "sum", "rate", "percent", "percentage", "breakdown", "group", "sort",
        "order", "across", "between", "during", "last", "year", "years",
        "month", "months", "our", "ours", "the", "and", "for", "are", "per",
    }
)
_COMPACT_SCHEMA_CHARS = 7_200  # ~1800 tokens, the per-call budget we planned for
# A sheet called "order" or "group" must keep its prefix: unquoted, the short
# form would not parse as a table reference in the SQL the model writes.
_RESERVED_TABLE_WORDS = frozenset(
    {
        "all", "and", "any", "as", "asc", "between", "by", "case", "cast", "check",
        "column", "constraint", "create", "cross", "current", "default", "delete",
        "desc", "distinct", "drop", "else", "end", "except", "exists", "false",
        "from", "full", "group", "having", "in", "inner", "insert", "intersect",
        "into", "is", "join", "left", "like", "limit", "not", "null", "offset",
        "on", "or", "order", "outer", "primary", "references", "right", "select",
        "set", "some", "table", "then", "to", "true", "union", "unique", "update",
        "using", "values", "when", "where", "window", "with",
    }
)
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


def _load_excel(
    con: duckdb.DuckDBPyConnection, path: Path
) -> list[tuple[str, list[str], str]]:
    raw = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    loaded: list[tuple[str, list[str], str]] = []
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
        loaded.append((table, originals, clean_names([str(sheet)])[0]))
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
        if _is_varchar(col.dtype) and 0 < distinct_count <= _ENUM_DISTINCT_CAP:
            # Small enough to name exhaustively. Knowing the literals is what
            # stops a query filtering on a value the column never holds.
            col.values = [
                str(v[0])
                for v in con.execute(
                    f"SELECT DISTINCT {q} FROM {_quote(table)} "
                    f"WHERE {q} IS NOT NULL ORDER BY 1"
                ).fetchall()
            ]
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


_NUMERIC_PREFIXES = (
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT",
    "USMALLINT", "UINTEGER", "UBIGINT", "DECIMAL", "NUMERIC", "REAL",
    "FLOAT", "DOUBLE",
)


def _is_numeric(dtype: str) -> bool:
    """Types avg() and sum() are meaningful on."""
    return dtype.upper().strip().startswith(_NUMERIC_PREFIXES)


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


def _entity_date_is_unique(
    con: duckdb.DuckDBPyConnection, table: str, grain: str, date_col: str
) -> bool:
    """True when each (entity, date) pair appears at most once.

    A history table has exactly one row per (entity, date). A composite fact
    table — engagement by department × location × quarter — repeats that pair.
    """
    tq, gq, dq = _quote(table), _quote(grain), _quote(date_col)
    row_count, distinct_pairs = con.execute(
        f"SELECT count(*), "
        f"(SELECT count(*) FROM (SELECT DISTINCT {gq}, {dq} FROM {tq})) "
        f"FROM {tq}"
    ).fetchone()
    return row_count == distinct_pairs


def _profile_grain(con: duckdb.DuckDBPyConnection, table: TableInfo) -> None:
    """Detect the entity a table repeats over, and whether it is a history table.

    Candidates are foreign keys plus `*_id` columns. The winner is the column
    with the highest row-count coverage (non-null rows, then distinct count),
    so a unique employee_id beats a repeating department FK. History requires
    rows_per_entity >= 1.15, a DATE/TIMESTAMP column, *and* uniqueness of
    (grain, date) — 1.0 is an entity table, a little above 1.0 is usually dirt,
    and a repeating (entity, date) pair is a composite fact table, not SCD-2.
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
    if (
        table.rows_per_entity >= _HISTORY_RPE_THRESHOLD
        and date_col
        and _entity_date_is_unique(con, table.name, ident, date_col)
    ):
        table.is_history_table = True
        table.history_date_column = date_col


def aggregate_coverage(sql: str, tables: list[TableInfo]) -> dict | None:
    """If SQL aggregates a *numeric* column with null_pct > 1, return covered/total.

    Numeric only, for the same reason the schema card no longer promises
    `avg() covers N rows` on a VARCHAR: a coverage disclosure attached to a
    text column describes an aggregate that cannot meaningfully be taken.
    """
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
                if not _is_numeric(col.dtype):
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
        # A CSV table is already just its stem, so there is no prefix to drop.
        loaded = [(table, originals, table)]
    elif suffix == ".xlsx":
        loaded = _load_excel(con, path)
    else:
        raise ValueError(f"unsupported file type for plumb ingest: {suffix or path.name}")

    tables: list[TableInfo] = []
    for table, originals, sheet in loaded:
        _convert_date_columns(con, table)
        info = _profile(con, table, originals)
        info.sheet_name = sheet
        tables.append(info)

    FOREIGN_KEYS.update(_detect_foreign_keys(con, tables))
    for t in tables:
        _profile_grain(con, t)
    assign_display_names(tables)
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
        _profile_grain(con, t)
    log_schema_cost(tables)
    return con, tables


def log_schema_cost(tables: list[TableInfo]) -> int:
    """Log what the schema card will cost on every planner call.

    The card is sent with each question, so its size is the standing per-turn
    token bill — invisible until it trips a per-minute ceiling.
    """
    card = render_schema(tables)
    tokens = len(card) // _CHARS_PER_TOKEN
    log.info(
        "schema card: %d tables, %d chars, ~%d tokens per planner call",
        len(tables),
        len(card),
        tokens,
    )
    return tokens


def assign_display_names(tables: list[TableInfo]) -> None:
    """Show `employees`, not `northwind_hr_analytics_employees`.

    Every sheet in one workbook carries the same file-stem prefix. It buys the
    model nothing, and it is paid for twice: once in the schema card, and again
    in every query the model writes. Dropping it is safe only while the short
    form stays unambiguous, so a name shared by two uploaded files — or one
    that would collide with another table's full name — keeps its prefix.
    """
    short_counts: dict[str, int] = {}
    for t in tables:
        candidate = (t.sheet_name or t.name).lower()
        short_counts[candidate] = short_counts.get(candidate, 0) + 1
    full_names = {t.name.lower() for t in tables}

    for t in tables:
        candidate = t.sheet_name or t.name
        lowered = candidate.lower()
        ambiguous = (
            short_counts.get(lowered, 0) > 1
            or (lowered != t.name.lower() and lowered in full_names)
            or lowered in _RESERVED_TABLE_WORDS
            or not candidate
        )
        t.display_name = t.name if ambiguous else candidate


def display_name(table: TableInfo) -> str:
    return table.display_name or table.name


def alias_map(tables: list[TableInfo]) -> dict[str, str]:
    """display name (lowercased) -> real DuckDB table name."""
    return {
        display_name(t).lower(): t.name
        for t in tables
        if display_name(t).lower() != t.name.lower()
    }


def _fk_references(tables: list[TableInfo]) -> dict[str, set[str]]:
    """Which tables each table *points at* through a detected foreign key.

    Direction matters. `compensation.employee_id` cannot be resolved without
    `employees`, so choosing compensation must pull employees in. The reverse
    is not true: `training` also points at employees, but a question about
    salaries does not need the training sheet. Following the edges both ways
    on a star schema selects the whole workbook and prunes nothing.
    """
    known = {t.name for t in tables}
    edges: dict[str, set[str]] = {t.name: set() for t in tables}
    for owner, lines in FOREIGN_KEYS.items():
        if owner not in known:
            continue
        for line in lines:
            match = _FK_LINE.match(line.strip())
            if match and match.group(3) in known and match.group(3) != owner:
                edges[owner].add(match.group(3))
    return edges


def _question_tokens(question: str) -> set[str]:
    words = re.findall(r"[a-z]{4,}", question.lower())
    return {w for w in words if w not in _STOPWORDS}


def _score_tables(question: str, tables: list[TableInfo]) -> dict[str, int]:
    """Score each table against the question, weighting rare matches higher.

    "department" is a column on five of eight sheets, so it barely narrows
    anything; "salary" appears on one, so it all but names the table. Scoring
    every match equally lets the common word drown out the decisive one.
    """
    tokens = _question_tokens(question)
    scores = {t.name: 0 for t in tables}

    matches: dict[str, set[str]] = {token: set() for token in tokens}
    for t in tables:
        haystack = " ".join(
            [*identifiers(t), *(c.name.lower() for c in t.columns)]
        ).replace("_", " ")
        for token in tokens:
            if token in haystack:
                matches[token].add(t.name)

    for token, owners in matches.items():
        weight = 3 if 0 < len(owners) <= _RARE_TOKEN_TABLES else 1
        for name in owners:
            scores[name] += weight

    for t in tables:
        name = display_name(t).lower()
        if any(part in tokens or f"{part}s" in tokens for part in name.split("_")):
            scores[t.name] += 3
        for col in t.columns:
            if any(v.lower() in question.lower() for v in col.values if len(v) > 3):
                scores[t.name] += 1
                break
    return scores


def select_tables(question: str, tables: list[TableInfo]) -> list[TableInfo]:
    """The tables a question plausibly needs, plus everything they join to.

    Sending eight tables to answer a three-table question is most of the
    prompt bill. The risk is the opposite error — dropping a table a join
    needs — so scoring is only ever allowed to narrow a clear signal: a vague
    question, a small workbook, or a thin result all fall back to everything,
    and `guard` catching an unknown table re-runs the turn on the full schema.
    """
    if len(tables) <= _PRUNE_MIN_TABLES + 1:
        return tables

    scores = _score_tables(question, tables)
    best = max(scores.values(), default=0)
    if best < _PRUNE_MIN_SCORE:
        # The question names nothing in the schema. A vague question must not
        # be answered against a subset we picked for it.
        return tables

    chosen = {name for name, score in scores.items() if score * 2 >= best}
    edges = _fk_references(tables)
    frontier = list(chosen)
    while frontier:  # a referenced table may itself reference another
        name = frontier.pop()
        for target in edges.get(name, set()):
            if target not in chosen:
                chosen.add(target)
                frontier.append(target)

    if len(chosen) < _PRUNE_MIN_TABLES or len(chosen) >= len(tables):
        return tables
    return [t for t in tables if t.name in chosen]


def restore_table_names(sql: str, aliases: dict[str, str]) -> str:
    """Put the real table names back before anything validates or executes.

    The model writes SQL against the display names it was shown; DuckDB only
    knows the real ones. Rewriting here — on the AST, not by string
    replacement — keeps `guard.validate` resolving against real identifiers,
    so the security boundary never sees a name it cannot check.
    """
    if not aliases:
        return sql
    try:
        tree = sqlglot.parse_one(sql, dialect="duckdb")
    except ParseError:
        return sql  # let the guard produce the parse error, with its own message
    if tree is None:
        return sql
    # A CTE may legitimately be named like a table; renaming its references
    # would point the query at a table the user never asked about.
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for node in tree.find_all(exp.Table):
        name = node.name.lower()
        if name in cte_names:
            continue
        real = aliases.get(name)
        if real:
            node.set("this", exp.to_identifier(real, quoted=False))
    return tree.sql(dialect="duckdb")


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
    name = display_name(table)
    repeating = (
        table.grain_column
        and table.grain_entities is not None
        and table.rows_per_entity is not None
        and table.rows_per_entity >= _HISTORY_RPE_THRESHOLD
    )
    if table.is_history_table and repeating:
        grain = table.grain_column
        date_col = table.history_date_column or "date"
        lines = [
            f"-- {name}: {table.row_count} rows, "
            f"{table.grain_entities} distinct {grain} "
            f"({table.rows_per_entity} rows per {grain}).",
            f"-- HISTORY TABLE: each row is a point in time, keyed by {date_col}.",
            f"-- For current values, take the latest {date_col} per {grain}.",
            "-- Do NOT average across rows — that weights employees by how many records they have.",
        ]
    elif repeating:
        grain = table.grain_column
        lines = [
            f"-- {name}: {table.row_count} rows, "
            f"{table.grain_entities} distinct {grain} "
            f"({table.rows_per_entity} rows per {grain}).",
            f"-- Multiple rows per {grain} — check which columns form the grain before aggregating.",
        ]
    else:
        lines = [f"-- {name}: {table.row_count} rows"]
    if table.row_count > _CASE_VARIANT_ROW_CAP:
        lines.append(
            f"-- case-variant check skipped: table has {table.row_count} rows"
        )
    return lines


def _enumerable_values(col: ColumnInfo, row_count: int) -> list[str]:
    """The full value set, when it is short enough to be worth naming."""
    if not col.values or col.distinct_count > _ENUM_DISTINCT_CAP:
        return []
    if col.case_variant_count is not None:
        return []  # the case-variant note already names the colliding values
    if row_count > 1 and col.distinct_count == row_count:
        # One value per row: a key, not a category. Listing it teaches the
        # model nothing about how to filter and costs a line per value.
        return []
    return col.values


def _null_notes(col: ColumnInfo, row_count: int) -> list[str]:
    """Null coverage, phrased so it is true for the column's type.

    `avg() covers 633 rows` on a VARCHAR is not merely wasted tokens — avg()
    on text is meaningless, so the note invites a query that cannot work. The
    coverage fact still matters for text; only the avg() framing is numeric.
    """
    if not row_count or not col.null_count:
        return []
    if col.null_pct <= _NULL_NOTE_MIN_PCT:
        return []  # under 1%: not decision-relevant, and it costs a line
    if _is_numeric(col.dtype):
        covered = row_count - col.null_count
        return [
            f"{col.null_count} of {row_count} null ({col.null_pct}%). "
            f"avg() covers {covered} rows."
        ]
    return [f"{round(col.null_pct)}% null"]


def _samples_for(col: ColumnInfo, compact: bool) -> list[str]:
    """Sample values are the cheapest thing in the card to cut, and the least
    load-bearing: they help the model recognise a value's shape, which a
    high-cardinality column cannot convey in a handful of examples anyway."""
    if not compact:
        return col.samples
    if col.distinct_count > _COMPACT_SAMPLE_DISTINCT_CAP:
        return []
    return col.samples[:_COMPACT_SAMPLE_COUNT]


def _ddl(
    table: TableInfo,
    with_samples: bool,
    with_case: bool = True,
    compact_samples: bool = False,
) -> str:
    lines = [f"CREATE TABLE {display_name(table)} ("]
    idents = identifiers(table)
    last = len(table.columns) - 1
    skip_case_table = table.row_count > _CASE_VARIANT_ROW_CAP
    for i, (ident, col) in enumerate(zip(idents, table.columns)):
        notes: list[str] = []
        enumerated = _enumerable_values(col, table.row_count)
        uninformative = compact_samples and (
            col.distinct_count > _COMPACT_SAMPLE_DISTINCT_CAP
            # "2 distinct, e.g. False, True" on a BOOLEAN is the type restated.
            or col.dtype.upper().startswith("BOOL")
        )
        if with_case and col.case_variant_count is not None:
            notes.append(_case_variant_note(ident, col))
        else:
            if enumerated:
                # Naming the values beats counting them: "2 distinct" is what
                # makes a model write status = 'active' against data holding
                # 'Active', get zero rows, and report it as an answer.
                notes.append(", ".join(f"'{v}'" for v in enumerated))
            elif not uninformative:
                # "640 distinct" on a 640-row id column says nothing the
                # column name did not already say. Dropped only in compact
                # mode; the case-variant warning below is never dropped.
                notes.append(f"{col.distinct_count} distinct")
            if (
                with_case
                and not skip_case_table
                and _is_varchar(col.dtype)
                and col.distinct_count > _CASE_VARIANT_DISTINCT_CAP
            ):
                notes.append("case-variant check skipped (>10000 distinct)")
        notes.extend(_null_notes(col, table.row_count))
        samples = [] if (enumerated or uninformative) else _samples_for(col, compact_samples)
        if with_samples and samples:
            notes.append("e.g. " + ", ".join(samples))
        decl = f"  {ident} {col.dtype}" + ("" if i == last else ",")
        decl = decl + " " if compact_samples else decl.ljust(28)
        lines.append((decl + ("-- " + ", ".join(notes) if notes else "")).rstrip())
    lines.append(");")
    lines.extend(_table_shape_comments(table))
    return "\n".join(lines)


_FK_LINE = re.compile(r"^-- (\S+)\.(\S+) likely references (\S+)\.(\S+)$")


def _render_fk(line: str, names: dict[str, str], compact: bool) -> str:
    """Rewrite an FK note into display names, and shorten it in compact mode.

    `-- a.b likely references c.d` → `-- FK b -> c.d`: the line already sits
    inside table `a`'s block, so repeating the owning table name costs tokens
    and tells the model nothing new.
    """
    match = _FK_LINE.match(line.strip())
    if not match:
        return line
    owner, col, target, target_col = match.groups()
    owner = names.get(owner, owner)
    target = names.get(target, target)
    if compact:
        return f"-- FK {col} -> {target}.{target_col}"
    return f"-- {owner}.{col} likely references {target}.{target_col}"


def render_schema(
    tables: list[TableInfo], foreign_keys: dict[str, list[str]] | None = None
) -> str:
    """Render CREATE TABLE DDL with profiling comments for the model prompt."""
    fks = FOREIGN_KEYS if foreign_keys is None else foreign_keys
    # A workbook with many tables pays for full sample lists on every planner
    # call, and at a per-minute token ceiling that cost is what makes a demo
    # look broken. Start compact above the threshold instead of only falling
    # back to it once the card has already blown past the char cap.
    # Compact rendering used to be reserved for wide workbooks. Once pruning
    # landed, table count stopped being a proxy for cost — a three-table card
    # was being rendered verbosely purely because it was short on tables — and
    # the compact form is strictly better anyway: it drops padding and uncounted
    # ids, never a warning.
    compact = True
    budget = _COMPACT_SCHEMA_CHARS
    names = {t.name: display_name(t) for t in tables}
    card = ""
    for with_samples, with_fks, with_case in (
        (True, True, True),
        (False, True, True),
        (False, False, True),
        (False, False, False),
    ):
        blocks = []
        for t in tables:
            block = _ddl(t, with_samples, with_case=with_case, compact_samples=compact)
            if with_fks:
                block += "".join(
                    "\n" + _render_fk(line, names, compact)
                    for line in fks.get(t.name, [])
                )
            blocks.append(block.rstrip())
        card = "\n\n".join(blocks)
        if len(card) <= budget:
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
