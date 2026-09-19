"""Pydantic contracts shared by every module in the pipeline."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    null_count: int
    distinct_count: int
    samples: list[str]
    values: list[str] = []  # the complete value set, for low-cardinality text
    null_pct: float = 0.0  # null_count / row_count, 0–100
    case_variant_count: int | None = None  # distinct(lower(col)) when it differs
    case_variant_examples: list[str] = []  # e.g. ["Hyderabad (183) / hyderabad (4)"]


class TableInfo(BaseModel):
    name: str  # the real DuckDB identifier — the only thing that ever executes
    row_count: int
    columns: list[ColumnInfo]
    sheet_name: str | None = None  # the sheet/file part, without the file stem
    display_name: str = ""  # what the model is shown; "" means use `name`
    grain_column: str | None = None  # the FK this table repeats over
    grain_entities: int | None = None  # distinct values of that column
    rows_per_entity: float | None = None
    is_history_table: bool = False
    history_date_column: str | None = None  # the effective-date column, when found


class Plan(BaseModel):
    route: Literal["answer", "clarify", "refuse", "chat"]
    sql: str | None = None
    clarify_question: str | None = None
    clarify_options: list[str] | None = None
    clarify_term: str | None = None  # which term this clarification is about
    refuse_reason: str | None = None
    reply: str | None = None  # route == "chat"
    chart: Literal["bar", "line", "pie", "scatter", "none"] = "none"
    chart_x: str | None = None
    chart_y: list[str] | None = None
    guard_code: str | None = None  # why the planner gave up, when it did


class ChartAdvice(BaseModel):
    """What the *result shape* says the chart should be, and why.

    Separate from `Plan.chart`, which is what the model asked for. The model
    reads a question; this reads the rows that came back — cardinality, dtype,
    sign, row count — so the advice survives a model that picks a pie for
    forty categories.
    """

    kind: Literal["bar", "line", "pie", "scatter", "none"]
    x: str | None = None
    y: str | None = None
    reason: str = ""
    alternatives: list[str] = []
    # A shape plumb cannot draw (candlestick, heatmap). Named rather than
    # silently ignored, so "no chart" never reads as "no chart was possible".
    unsupported: str | None = None
    rendered: str | None = None  # the chart actually drawn, when it differs


class AskResponse(BaseModel):
    route: Literal["answer", "clarify", "refuse", "chat", "error"]
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list] | None = None
    narration: str | None = None
    chart: dict | None = None
    clarify_question: str | None = None
    clarify_options: list[str] | None = None
    clarify_term: str | None = None
    refuse_reason: str | None = None
    reply: str | None = None  # route == "chat"
    error_code: str | None = None  # route == "error", e.g. provider_rate_limited
    error_message: str | None = None
    tables_sent: list[str] | None = None  # which tables the planner was shown
    chart_advice: ChartAdvice | None = None
    follow_ups: list[str] = []  # next questions, derived from this result
    definitions_applied: dict[str, str] = {}
    elapsed_ms: int
    provider: str = ""
    model: str = ""
    endpoint_host: str | None = None
