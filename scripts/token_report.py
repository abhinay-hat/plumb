"""What one planner call costs, broken down by what is paying for it.

Run with --save-baseline once before optimising; afterwards every run prints
`before -> after` against that saved file. The absolute numbers are estimates
(tiktoken when installed, else 4 chars per token); the comparison is the point.

    python scripts/token_report.py --save-baseline
    python scripts/token_report.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import catalog, planner  # noqa: E402

BASELINE = ROOT / "qa" / "_work" / "token-baseline.json"
DEFAULT_FIXTURE = ROOT / "fixtures" / "northwind_hr_analytics.xlsx"

# A representative turn: a question that needs a join, plus two settled
# definitions and two history turns, so the measured total is what a real
# mid-conversation call costs rather than a best case.
SAMPLE_QUESTION = "What is the average salary by department?"
SAMPLE_DEFINITIONS = {
    "headcount": "Every row in employees, including leavers",
    "average salary": "The latest compensation record per employee",
}
SAMPLE_HISTORY = [
    {"question": "How many employees in each department?", "route": "answer",
     "sql": "SELECT department, count(*) AS headcount FROM employees GROUP BY department"},
    {"question": "What's our attrition rate?", "route": "clarify", "sql": None},
]

try:  # optional; the comparison works either way
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")

    def tokens(text: str) -> int:
        return len(_ENCODING.encode(text))

    TOKENISER = "tiktoken cl100k_base"
except Exception:  # pragma: no cover - depends on the environment
    def tokens(text: str) -> int:
        return len(text) // 4

    TOKENISER = "len // 4"


def _table_name_cost(card: str, table_names: list[str]) -> int:
    """Tokens spent purely on repeating table names inside the card."""
    return sum(tokens(name) * card.count(name) for name in table_names)


def _comment_cost(card: str) -> int:
    """Tokens in the `-- ...` trailing comments on column lines."""
    comments = re.findall(r"--.*$", card, flags=re.MULTILINE)
    return sum(tokens(c) for c in comments)


def measure(fixture: Path) -> dict:
    _con, tables = catalog.ingest_many([str(fixture)], "tokenreport")
    # What a real call costs: the planner is shown the tables this question
    # needs, not the whole workbook.
    sent = catalog.select_tables(SAMPLE_QUESTION, tables)
    card = catalog.render_schema(sent)
    names = sorted({catalog.display_name(t) for t in sent}, key=len, reverse=True)

    user = planner._build_user_message(
        SAMPLE_QUESTION, card, SAMPLE_DEFINITIONS, SAMPLE_HISTORY
    )
    history_only = planner._build_user_message(
        SAMPLE_QUESTION, card, SAMPLE_DEFINITIONS, []
    )

    schema = tokens(card)
    system = tokens(planner.SYSTEM_PROMPT)
    history = tokens(user) - tokens(history_only)
    return {
        "fixture": fixture.name,
        "tables": len(sent),
        "tables_total": len(tables),
        "card_chars": len(card),
        "card_lines": card.count("\n") + 1,
        "schema card": schema,
        "  table names": _table_name_cost(card, names),
        "  column comments": _comment_cost(card),
        "system prompt": system,
        "history": history,
        "question + defs": tokens(user) - schema - history,
        "total input": system + tokens(user),
    }


ROWS = (
    "schema card",
    "  table names",
    "  column comments",
    "system prompt",
    "history",
    "question + defs",
    "total input",
)


def render(now: dict, before: dict | None) -> str:
    lines = [
        f"fixture: {now['fixture']}  ({now['tables']} of "
        f"{now.get('tables_total', now['tables'])} tables sent, "
        f"{now['card_chars']} chars, {now['card_lines']} lines)",
        f"question: {SAMPLE_QUESTION}",
        f"tokeniser: {TOKENISER}",
        "",
    ]
    for key in ROWS:
        if key == "total input":
            lines.append("                  " + "-" * 15)
        was = (before or {}).get(key)
        arrow = f"{was:>6,} -> " if was is not None else " " * 10
        lines.append(f"{key:<18}{arrow}{now[key]:>6,}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--budget", type=int, default=1300)
    args = parser.parse_args()

    now = measure(args.fixture)
    before = None
    if BASELINE.exists() and not args.save_baseline:
        before = json.loads(BASELINE.read_text())
        if before.get("fixture") != now["fixture"]:
            before = None

    print(render(now, before))

    if args.save_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(now, indent=2))
        print(f"\nbaseline written to {BASELINE.relative_to(ROOT)}")
        return 0

    over = now["total input"] - args.budget
    print(
        f"\nbudget {args.budget:,}: "
        + (f"OVER by {over:,}" if over > 0 else f"under by {-over:,}")
    )
    return 1 if over > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
