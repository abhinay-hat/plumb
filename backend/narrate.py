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


def verify_narration(text: str, rows: list[list]) -> bool:
    """True when every number in `text` is present in `rows` or is the row count."""
    allowed = _numbers_in_rows(rows)
    for token in _NUMBER.findall(text or ""):
        value = _normalise(token)
        if value is None:
            continue
        if value not in allowed:
            return False
    return True


def narrate(question: str, sql: str, columns: list[str], rows: list[list]) -> str:
    """One or two sentences describing the query and its headline finding."""
    shown = rows[:_MAX_ROWS_IN_PROMPT]
    body = "\n".join(" | ".join("" if c is None else str(c) for c in row) for row in shown)
    truncated = "" if len(rows) <= _MAX_ROWS_IN_PROMPT else (
        f"\n(showing {_MAX_ROWS_IN_PROMPT} of {len(rows)} rows)"
    )
    user = (
        f"Question: {question}\n\n"
        f"SQL that ran:\n{sql}\n\n"
        f"Columns: {', '.join(columns)}\n"
        f"Rows ({len(rows)} total):\n{body}{truncated}"
    )
    try:
        return llm.complete(SYSTEM_PROMPT, user, json_mode=False).strip()
    except llm.LLMError as e:
        log.warning("narration unavailable: %s", e)
        return f"{len(rows)} rows returned."
