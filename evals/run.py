"""Run the fixture question set through pipeline.ask(). Do not tune prompts first."""

from __future__ import annotations

import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import catalog, guard  # noqa: E402
from backend.pipeline import Session, ask  # noqa: E402

QUESTIONS = Path(__file__).resolve().parent / "questions.yaml"
RESULTS = Path(__file__).resolve().parent / "results.md"
FIXTURES = ROOT / "fixtures"


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Decimal):
        return str(float(value))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def _flatten(columns: list[str] | None, rows: list[list] | None) -> str:
    parts: list[str] = list(columns or [])
    for row in rows or []:
        parts.extend(_cell_text(cell) for cell in row)
    return " | ".join(parts).lower()


def _present(needle: object, haystack: str) -> bool:
    text = _cell_text(needle).lower()
    if text in haystack:
        return True
    compact = text.replace(",", "")
    if compact and compact in haystack.replace(",", ""):
        return True
    try:
        as_int = str(int(float(compact)))
    except ValueError:
        return False
    return as_int in haystack.replace(",", "")


def check_answer(expected: dict | None, columns: list[str] | None, rows: list[list] | None) -> bool:
    if not expected:
        return True
    haystack = _flatten(columns, rows)
    contains = expected.get("contains", [])
    if not isinstance(contains, list):
        contains = [contains]
    return all(_present(item, haystack) for item in contains)


def build_session() -> Session:
    con, tables = catalog.ingest_many(
        [str(FIXTURES / "employees.csv"), str(FIXTURES / "departments.csv")],
        "eval",
    )
    guard.safe_connection(con)
    return Session(con=con, tables=tables)


def main() -> int:
    spec = yaml.safe_load(QUESTIONS.read_text())
    items = spec["questions"]
    session = build_session()
    rows_out: list[dict[str, str]] = []
    passed = 0

    print(f"{'#':<3} {'route':<8} {'got':<8} {'ans':<5} question")
    print("-" * 78)

    for i, item in enumerate(items, 1):
        if i > 1:
            time.sleep(8)
        question = str(item["question"])
        expected_route = str(item["expected_route"])
        response = ask(question, session)
        route_ok = response.route == expected_route
        answer_ok = True
        if expected_route == "answer":
            answer_ok = route_ok and check_answer(
                item.get("expected_answer"), response.columns, response.rows
            )
        ok = route_ok and answer_ok
        if ok:
            passed += 1
        mark = "PASS" if ok else "FAIL"
        ans = "-" if expected_route != "answer" else ("ok" if answer_ok else "miss")
        print(
            f"{i:<3} {expected_route:<8} {response.route:<8} {ans:<5} {question[:48]}"
        )
        rows_out.append(
            {
                "n": str(i),
                "mark": mark,
                "question": question,
                "expected": expected_route,
                "got": response.route,
                "answer": ans,
                "sql": response.sql or "",
                "narration": (response.narration or "")[:180],
                "refuse": response.refuse_reason or "",
                "clarify": response.clarify_question or "",
            }
        )

    total = len(items)
    rate = passed / total if total else 0.0
    print("-" * 78)
    print(f"{passed}/{total}  pass rate {rate:.0%}")

    lines = [
        "# Eval results",
        "",
        f"Date: {date.today().isoformat()}",
        f"Pass rate: **{passed}/{total} ({rate:.0%})**",
        "",
        "| # | Result | Expected | Got | Answer | Question |",
        "|---|--------|----------|-----|--------|----------|",
    ]
    for row in rows_out:
        q = row["question"].replace("|", "/")
        lines.append(
            f"| {row['n']} | {row['mark']} | {row['expected']} | {row['got']} "
            f"| {row['answer']} | {q} |"
        )
    lines.extend(["", "## Failures", ""])
    fails = [r for r in rows_out if r["mark"] == "FAIL"]
    if not fails:
        lines.append("None.")
    else:
        for row in fails:
            lines.append(f"### {row['n']}. {row['question']}")
            lines.append("")
            lines.append(f"- expected `{row['expected']}`, got `{row['got']}`")
            if row["sql"]:
                lines.append(f"- sql: `{row['sql']}`")
            if row["narration"]:
                lines.append(f"- narration: {row['narration']}")
            if row["clarify"]:
                lines.append(f"- clarify: {row['clarify']}")
            if row["refuse"]:
                lines.append(f"- refuse: {row['refuse']}")
            lines.append("")
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {RESULTS}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
