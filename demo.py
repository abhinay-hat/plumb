"""Run five questions through the pipeline against the bundled fixtures."""

from __future__ import annotations

import logging
from pathlib import Path

from backend import catalog, guard
from backend.pipeline import Session, ask

FIXTURES = Path(__file__).resolve().parent / "fixtures"
QUESTIONS = [
    "How many employees in each department?",
    "Who are our top performers?",
    "What's the average salary by location?",
    "Why is attrition going up?",
    "How many people joined in 2025?",
]


def build_session() -> Session:
    """Load both fixtures into one guarded connection."""
    con, tables = catalog.ingest_many(
        [str(FIXTURES / "employees.csv"), str(FIXTURES / "departments.csv")], "demo"
    )
    guard.safe_connection(con)
    return Session(con=con, tables=tables)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    session = build_session()
    print(session.schema_card())

    for i, question in enumerate(QUESTIONS, 1):
        response = ask(question, session)
        print("\n" + "=" * 72)
        print(f"{i}. {question}")
        print(f"   route: {response.route}  ({response.elapsed_ms} ms)")
        if response.sql:
            print(f"   sql: {response.sql}")
        if response.narration:
            print(f"   narration: {response.narration}")
        if response.rows is not None:
            print(f"   rows: {len(response.rows)} x {len(response.columns)}")
            for row in response.rows[:5]:
                print(f"     {row}")
        if response.clarify_question:
            print(f"   clarify: {response.clarify_question}")
            for option in response.clarify_options or []:
                print(f"     - {option}")
        if response.refuse_reason:
            print(f"   refuse: {response.refuse_reason}")
        if response.chart:
            print(f"   chart: {response.chart['mark']['type']} — {response.chart['title']}")

    print("\n" + "=" * 72)
    print("routes:", ", ".join(ask_route for ask_route in (t["route"] for t in session.history)))


if __name__ == "__main__":
    main()
