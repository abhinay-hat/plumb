"""Pydantic contracts shared by every module in the pipeline."""

from __future__ import annotations

from pydantic import BaseModel, field_validator
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
    source_file: str = ""  # the uploaded filename this table came out of
    display_name: str = ""  # what the model is shown; "" means use `name`
    grain_column: str | None = None  # the FK this table repeats over
    grain_entities: int | None = None  # distinct values of that column
    rows_per_entity: float | None = None
    is_history_table: bool = False
    history_date_column: str | None = None  # the effective-date column, when found


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


class Panel(BaseModel):
    """One cut of the data inside a dashboard answer."""

    title: str
    sql: str | None = None
    chart_spec: dict | None = None
    columns: list[str] | None = None
    rows: list[list] | None = None
    chart: dict | None = None
    finding: str = ""
    chart_advice: ChartAdvice | None = None
    error_code: str | None = None


class Plan(BaseModel):
    route: Literal["answer", "clarify", "refuse", "chat", "dashboard"]
    sql: str | None = None
    clarify_question: str | None = None
    clarify_options: list[str] | None = None
    clarify_term: str | None = None  # which term this clarification is about
    refuse_reason: str | None = None
    reply: str | None = None  # route == "chat"
    # Deliberately not a Literal. "Give me a candlestick" made the model answer
    # chart: "candlestick", which failed a five-item enum, failed the whole
    # Plan, and surfaced as "the model returned a response plumb could not
    # read" — the SQL was fine and the user lost it anyway. A chart name plumb
    # cannot hand-build is not a malformed plan: it is a chart that belongs in
    # chart_spec, where chart_guard validates it against Vega's own marks.
    # `chart.BUILDABLE` is what build_spec assembles; anything else falls
    # through to the spec, and its name is the model's word for what was asked.
    chart: str = "none"
    chart_x: str | None = None
    chart_y: list[str] | None = None
    chart_spec: dict | None = None  # model-authored Vega-Lite, validated before use
    panels: list[Panel] | None = None  # route == "dashboard"
    guard_code: str | None = None  # why the planner gave up, when it did

    @field_validator("chart", mode="before")
    @classmethod
    def _normalise_chart(cls, value: object) -> object:
        if value is None:
            return "none"
        if isinstance(value, str):
            return value.strip().lower() or "none"
        return value


class AskResponse(BaseModel):
    route: Literal["answer", "clarify", "refuse", "chat", "error", "dashboard"]
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
    panels: list[Panel] | None = None
    summary: str | None = None  # optional one-paragraph tie-together, off by default
    follow_ups: list[str] = []  # next questions, derived from this result
    definitions_applied: dict[str, str] = {}
    elapsed_ms: int
    provider: str = ""
    model: str = ""
    endpoint_host: str | None = None
