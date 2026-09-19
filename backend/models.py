"""Pydantic contracts shared by every module in the pipeline."""

from pydantic import BaseModel
from typing import Literal


class ColumnInfo(BaseModel):
    name: str
    dtype: str
    null_count: int
    distinct_count: int
    samples: list[str]


class TableInfo(BaseModel):
    name: str
    row_count: int
    columns: list[ColumnInfo]


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
