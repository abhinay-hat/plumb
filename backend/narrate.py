"""Describe what the executed query did, then check every number it cites."""

from __future__ import annotations

import logging
import re

from backend import llm

log = logging.getLogger("plumb.narrate")

SYSTEM_PROMPT = """You describe the result of a SQL query that has already run.

Write one or two sentences. First say in plain words what the query did, naming the filters — for example: "Counted rows in employees where status = 'active', grouped by department." Then state the headline finding.

Use only numbers that appear in the rows you are given. Never compute a new figure: no totals, no percentages, no differences, no averages that are not already a column. No preamble, no bullet points, no markdown."""

_NUMBER = re.compile(r"-?[\d,]+\.?\d*")
_MAX_ROWS_IN_PROMPT = 30


def _normalise(token: str) -> float | None:
    cleaned = token.replace(",", "").rstrip(".")
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _is_year(token: str) -> bool:
    cleaned = token.replace(",", "").rstrip(".")
    if not cleaned.isdigit() or len(cleaned) != 4:
        return False
    year = int(cleaned)
    return 1900 <= year <= 2100


def _numbers_in_rows(rows: list[list]) -> set[float]:
    found: set[float] = {float(len(rows))}
    for row in rows:
        for cell in row:
            if isinstance(cell, bool) or cell is None:
                continue
            if isinstance(cell, (int, float)):
                found.add(round(float(cell), 2))
            for token in _NUMBER.findall(str(cell)):
                value = _normalise(token)
                if value is not None:
                    found.add(value)
    return found


def _numbers_in_text(text: str | None) -> set[float]:
    found: set[float] = set()
    for token in _NUMBER.findall(text or ""):
        value = _normalise(token)
        if value is not None:
            found.add(value)
    return found


def _coverage_allowed(coverage: dict | None) -> set[float]:
    if not coverage:
        return set()
    allowed: set[float] = set()
    for key in ("covered", "total"):
        value = _normalise(str(coverage[key]))
        if value is not None:
            allowed.add(value)
    return allowed


def _mentions_coverage(text: str, coverage: dict) -> bool:
    found = _numbers_in_text(text)
    needed = _coverage_allowed(coverage)
    return bool(needed) and needed <= found


def _coverage_clause(coverage: dict) -> str:
    return (
        f"across {coverage['covered']:,} of {coverage['total']:,} "
        f"{coverage['column']} values."
    )


def _with_coverage(text: str, coverage: dict | None) -> str:
    if not coverage or _mentions_coverage(text, coverage):
        return text
    body = (text or "").rstrip()
    clause = _coverage_clause(coverage)
    if body:
        if not body.endswith("."):
            body += "."
        return f"{body} The aggregate covers {coverage['covered']:,} of {coverage['total']:,} {coverage['column']} values."
    return clause[0].upper() + clause[1:]


def verify_narration(
    text: str,
    rows: list[list],
    question: str | None = None,
    coverage: dict | None = None,
) -> bool:
    """True when every number in `text` is present in `rows` or is the row count.

    Years in 1900–2100, numbers that already appeared in the question, and
    coverage figures (covered / total) are also allowed — they are context, not
    invented claims.
    """
    allowed = _numbers_in_rows(rows)
    allowed |= _numbers_in_text(question)
    allowed |= _coverage_allowed(coverage)
    # ISO dates are not numbers; leaving them in lets `-01` parse as −1.
    scanned = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text or "")
    for token in _NUMBER.findall(scanned):
        value = _normalise(token)
        if value is None:
            continue
        if value in allowed or _is_year(token):
            continue
        return False
    return True


def _system_prompt(coverage: dict | None) -> str:
    if not coverage:
        return SYSTEM_PROMPT
    covered = f"{coverage['covered']:,}"
    total = f"{coverage['total']:,}"
    extra = (
        f"\n\nThe query aggregated {coverage['column']}, which has nulls. You MUST "
        f"state coverage in the sentence using these exact figures: {covered} of "
        f"{total}. Example: \"across {covered} of {total} reviews.\" Those two "
        "coverage figures are allowed numbers even though they are not result cells."
    )
    return SYSTEM_PROMPT + extra


def narrate(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list],
    coverage: dict | None = None,
) -> str:
    """One or two sentences describing the query and its headline finding."""
    shown = rows[:_MAX_ROWS_IN_PROMPT]
    body = "\n".join(" | ".join("" if c is None else str(c) for c in row) for row in shown)
    truncated = "" if len(rows) <= _MAX_ROWS_IN_PROMPT else (
        f"\n(showing {_MAX_ROWS_IN_PROMPT} of {len(rows)} rows)"
    )
    coverage_line = ""
    if coverage:
        coverage_line = (
            f"\nCoverage (must appear in the sentence): "
            f"{coverage['covered']:,} of {coverage['total']:,} "
            f"{coverage['column']} values.\n"
        )
    user = (
        f"Question: {question}\n\n"
        f"SQL that ran:\n{sql}\n\n"
        f"Columns: {', '.join(columns)}\n"
        f"Rows ({len(rows)} total):\n{body}{truncated}"
        f"{coverage_line}"
    )
    try:
        text = llm.complete(_system_prompt(coverage), user, json_mode=False).strip()
    except llm.LLMError as e:
        log.warning("narration unavailable: %s", e)
        text = f"{len(rows)} rows returned."
    return _with_coverage(text, coverage)
