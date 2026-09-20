"""What is loaded, said in a sentence — and the check that keeps it honest.

A greeting is the first thing most people type, and "How can I help you with
your data today?" answers it with nothing. The useful reply names the sheets,
their sizes, and what could be asked of them.

That turns a chat reply into a claim about the data, so it gets the same
treatment as a narration: every number in it must be a number the schema
actually contains. A model that rounds 640 to "about 600 employees" is doing
the thing this whole application exists to refuse.
"""

from __future__ import annotations

import re

from backend import catalog
from backend.models import TableInfo

_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def schema_numbers(tables: list[TableInfo]) -> set[float]:
    """Every figure a truthful briefing could quote about this schema."""
    allowed: set[float] = {float(len(tables))}
    for table in tables:
        allowed.add(float(table.row_count))
        allowed.add(float(len(table.columns)))
        if table.grain_entities is not None:
            allowed.add(float(table.grain_entities))
    return allowed


def verify_briefing(text: str, tables: list[TableInfo]) -> bool:
    """True when every number in `text` is one the schema can support.

    Small integers are allowed through: "two or three questions" and "the first
    five rows" are sentence furniture, not claims about the data. Anything
    larger has to match a real row count, column count, or table count.
    """
    allowed = schema_numbers(tables)
    for token in _NUMBER.findall(text or ""):
        try:
            value = float(token.replace(",", ""))
        except ValueError:
            continue
        if value <= 10 or value in allowed:
            continue
        return False
    return True


def describe(tables: list[TableInfo]) -> str:
    """A briefing assembled in Python, for when the model's cannot be trusted.

    Deliberately plain. It is the fallback, and a fallback that reads like a
    flourish invites nobody to notice the model's version was discarded.
    """
    if not tables:
        return (
            "No spreadsheet is loaded yet. Drop a CSV, TSV, or XLSX on the left "
            "and I will tell you what is in it."
        )

    ranked = sorted(tables, key=lambda t: t.row_count, reverse=True)
    lead = ", ".join(
        f"{catalog.display_name(t)} ({t.row_count:,} rows, {len(t.columns)} columns)"
        for t in ranked[:3]
    )
    count = (
        "one sheet"
        if len(tables) == 1
        else f"{len(tables)} sheets"
    )
    rest = "" if len(ranked) <= 3 else f", and {len(ranked) - 3} more"
    return f"You have {count} loaded: {lead}{rest}."
