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
    null_pct: float = 0.0  # null_count / row_count, 0–100
    case_variant_count: int | None = None  # distinct(lower(col)) when it differs
    case_variant_examples: list[str] = []  # e.g. ["Hyderabad (183) / hyderabad (4)"]


class TableInfo(BaseModel):
    name: str
    row_count: int
    columns: list[ColumnInfo]
    grain_column: str | None = None  # the FK this table repeats over
    grain_entities: int | None = None  # distinct values of that column
    rows_per_entity: float | None = None
    is_history_table: bool = False
    history_date_column: str | None = None  # the effective-date column, when found


class Plan(BaseModel):
    route: Literal["answer", "clarify", "refuse"]
    sql: str | None = None
    clarify_question: str | None = None
    clarify_options: list[str] | None = None
    refuse_reason: str | None = None
    chart: Literal["bar", "line", "pie", "scatter", "none"] = "none"
    chart_x: str | None = None
    chart_y: list[str] | None = None


class AskResponse(BaseModel):
    route: Literal["answer", "clarify", "refuse"]
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list] | None = None
    narration: str | None = None
    chart: dict | None = None
    clarify_question: str | None = None
    clarify_options: list[str] | None = None
    refuse_reason: str | None = None
    definitions_applied: dict[str, str] = {}
    elapsed_ms: int
