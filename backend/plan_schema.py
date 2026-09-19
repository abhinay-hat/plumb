"""JSON Schema for planner completions on models with strict Structured Outputs."""

from __future__ import annotations

# Groq gpt-oss strict mode requires every property and additionalProperties: false.
PLAN_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ["answer", "clarify", "refuse", "chat"]},
        "sql": {"type": ["string", "null"]},
        "clarify_question": {"type": ["string", "null"]},
        "clarify_options": {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ]
        },
        "clarify_term": {"type": ["string", "null"]},
        "refuse_reason": {"type": ["string", "null"]},
        "reply": {"type": ["string", "null"]},
        "chart": {
            "type": "string",
            "enum": ["bar", "line", "pie", "scatter", "none"],
        },
        "chart_x": {"type": ["string", "null"]},
        "chart_y": {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ]
        },
    },
    "required": [
        "route",
        "sql",
        "clarify_question",
        "clarify_options",
        "clarify_term",
        "refuse_reason",
        "reply",
        "chart",
        "chart_x",
        "chart_y",
    ],
    "additionalProperties": False,
}
