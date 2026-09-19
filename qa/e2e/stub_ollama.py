#!/usr/bin/env python3
"""Ollama-shaped LLM stub for qa/e2e. Binds :11434. No Groq tokens."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

PLANS: list[tuple[str, dict]] = [
    (
        "average salary",
        {
            "route": "answer",
            "sql": "SELECT AVG(base_salary_inr) AS avg_salary FROM northwind_hr_analytics_compensation",
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": None,
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
    (
        "each location",
        {
            "route": "answer",
            "sql": "SELECT location, COUNT(*) AS headcount FROM northwind_hr_analytics_employees GROUP BY location ORDER BY headcount DESC",
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": None,
            "chart": "bar",
            "chart_x": "location",
            "chart_y": ["headcount"],
        },
    ),
    (
        "each department",
        {
            "route": "answer",
            "sql": "SELECT department, COUNT(*) AS headcount FROM northwind_hr_analytics_employees GROUP BY department ORDER BY headcount DESC",
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": None,
            "chart": "bar",
            "chart_x": "department",
            "chart_y": ["headcount"],
        },
    ),
    (
        "how many employees are there",
        {
            "route": "answer",
            "sql": "SELECT COUNT(*) AS headcount FROM northwind_hr_analytics_employees",
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": None,
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
    (
        "average performance rating",
        {
            "route": "answer",
            "sql": "SELECT AVG(performance_rating) AS avg_rating FROM northwind_hr_analytics_performance_reviews",
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": None,
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
    (
        "headcount",
        {
            "route": "answer",
            "sql": "SELECT COUNT(*) AS headcount FROM northwind_hr_analytics_employees",
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": None,
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
    (
        "attrition",
        {
            "route": "clarify",
            "sql": None,
            "clarify_question": "Which attrition formula?",
            "clarify_options": [
                "Terminated / all employees",
                "Terminated / active+terminated in period",
                "Voluntary exits / average headcount",
            ],
            "refuse_reason": None,
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
    (
        "top performers",
        {
            "route": "clarify",
            "sql": None,
            "clarify_question": "Top performers by which measure?",
            "clarify_options": [
                "Highest latest performance_rating",
                "Highest engagement_score",
                "rating_label = 'Outstanding'",
            ],
            "refuse_reason": None,
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
    (
        "system prompt",
        {
            "route": "refuse",
            "sql": None,
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": "That is not a question about the spreadsheet.",
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
    (
        "read_csv_auto",
        {
            "route": "answer",
            "sql": "SELECT * FROM read_csv_auto('/etc/passwd')",
            "clarify_question": None,
            "clarify_options": None,
            "refuse_reason": None,
            "chart": "none",
            "chart_x": None,
            "chart_y": None,
        },
    ),
]

DEFAULT = {
    "route": "refuse",
    "sql": None,
    "clarify_question": None,
    "clarify_options": None,
    "refuse_reason": "stub has no plan for this question",
    "chart": "none",
    "chart_x": None,
    "chart_y": None,
}

NARRATE = "1 rows returned."


def plan_for(user: str) -> dict:
    lower = user.lower()
    # last "Question:" wins
    q = lower
    if "question:" in lower:
        q = lower.rsplit("question:", 1)[-1]
    for needle, plan in PLANS:
        if needle in q:
            return plan
    return DEFAULT


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = json.loads(self.rfile.read(length) or b"{}")
        messages = raw.get("messages") or []
        user = ""
        system = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content") or ""
            if m.get("role") == "user":
                user = m.get("content") or ""
        if "describe the result of a SQL query" in system.lower() or "you describe" in system.lower():
            content = NARRATE
        else:
            content = json.dumps(plan_for(user))
        body = json.dumps({"message": {"role": "assistant", "content": content}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 11434), Handler).serve_forever()
