"""JSON Schema for planner completions on models with strict Structured Outputs."""

from __future__ import annotations

# Groq gpt-oss strict mode requires every property and additionalProperties: false.
PLAN_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "route": {
            "type": "string",
            "enum": ["answer", "clarify", "refuse", "chat", "dashboard"],
        },
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
        # No enum on purpose. Under strict mode an enum here would forbid the
        # model from ever naming a histogram or a candlestick, and without
        # strict mode it named one anyway and broke the parse. The name is free;
        # what can be drawn is decided by chart.BUILDABLE and chart_guard.
        #
        # Null is allowed because a refusal has no chart, and the model says so
        # by writing null. Demanding a string made Groq reject its own correct
        # refusal with a 400 — the user saw "the model returned a response plumb
        # could not read" when the model had answered perfectly. Plan's
        # validator maps null to "none".
        "chart": {"type": ["string", "null"]},
        "chart_x": {"type": ["string", "null"]},
        "chart_y": {
            "anyOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "null"},
            ]
        },
        "chart_spec": {
            "anyOf": [
                {"type": "string"},
                {"type": "null"},
            ]
        },
        "panels": {
            "anyOf": [
                {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "sql": {"type": ["string", "null"]},
                            "chart_spec": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "null"},
                                ]
                            },
                        },
                        "required": ["title", "sql", "chart_spec"],
                        "additionalProperties": False,
                    },
                },
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
        "chart_spec",
        "panels",
    ],
    "additionalProperties": False,
}
