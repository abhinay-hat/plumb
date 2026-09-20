"""Assemble Vega-Lite specs in Python, and rank what shape the rows want.

Model-authored specs go through chart_guard first — Vega-Lite renders an
invalid spec as a blank chart rather than throwing, so unvalidated specs would
fail silently. When chart_spec is absent or rejected, this module builds from
the plan's chart fields or from the result-shape recommendation.
"""

from __future__ import annotations

import difflib
import json
import re

from backend.guard import match_column
from backend.models import ChartAdvice, Plan

MAX_ROWS = 50
MIN_ROWS = 2
# Past this many marks the value labels overlap each other and the chart is
# harder to read with them than without.
LABEL_MAX_POINTS = 24
_TEMPORAL = ("DATE", "TIMESTAMP", "TIME")
_QUANTITATIVE = (
    "INT",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "HUGEINT",
    "UBIGINT",
    "UINTEGER",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "DECIMAL",
    "NUMERIC",
)


def vega_type(dtype: str) -> str:
    """Map a DuckDB dtype onto a Vega-Lite field type."""
    upper = (dtype or "").upper()
    if upper.startswith(_TEMPORAL):
        return "temporal"
    if upper.startswith(_QUANTITATIVE):
        return "quantitative"
    return "nominal"


def _is_numeric_cell(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def enrich_dtypes(
    columns: list[str], rows: list[list], table_dtypes: dict[str, str]
) -> dict[str, str]:
    """Table dtypes miss aggregate aliases — infer those from the result rows."""
    merged = dict(table_dtypes)
    for i, col in enumerate(columns):
        key = match_column(col, list(merged))
        if key and vega_type(merged.get(key, "")) != "nominal":
            continue
        values = [row[i] for row in rows if i < len(row) and row[i] is not None]
        if not values:
            continue
        if all(_is_numeric_cell(v) for v in values):
            merged[col] = "BIGINT"
        elif key is None and all(isinstance(v, str) for v in values):
            merged[col] = "VARCHAR"
    return merged


# The words that mean "draw this". Matched with a little tolerance because
# "line chat" and "bar grpah" are the same request as "line chart", and being
# pedantic about a typo costs the user their chart.
_DRAW_WORDS = ("chart", "graph", "plot", "visualise", "visualize", "visualisation")
_KIND_WORDS = ("bar", "line", "pie", "scatter")


def _mentions(word: str, tokens: list[str]) -> bool:
    """Whether `word` appears, allowing one typo in anything long enough to risk one."""
    if word in tokens:
        return True
    return bool(difflib.get_close_matches(word, tokens, n=1, cutoff=0.8))


def visualization_kind(question: str) -> str | None:
    """Detect a chart-only follow-up such as 'show this as a bar chart'."""
    q = question.lower().strip()
    if not q:
        return None
    tokens = [t for t in re.split(r"[^a-z]+", q) if t]
    asked_to_draw = any(_mentions(word, tokens) for word in _DRAW_WORDS)
    named = next((kind for kind in _KIND_WORDS if _mentions(kind, tokens)), None)
    if asked_to_draw:
        # "as a bar" with no kind named still means draw something; the shape
        # of the result decides which, upstream of here.
        return named or "bar"
    # "scatter" and "as a pie" name a chart without the word chart in sight.
    return named


def infer_axes(columns: list[str], dtypes: dict[str, str]) -> tuple[str, str] | None:
    """Pick category/time on x and a measure on y from result columns."""
    if len(columns) < 2:
        return None
    temporal: list[str] = []
    nominal: list[str] = []
    quantitative: list[str] = []
    for col in columns:
        key = match_column(col, list(dtypes)) or col
        kind = vega_type(dtypes.get(key, ""))
        if kind == "temporal":
            temporal.append(col)
        elif kind == "quantitative":
            quantitative.append(col)
        else:
            nominal.append(col)
    if not quantitative:
        return None
    x = nominal[0] if nominal else temporal[0] if temporal else None
    y = quantitative[0]
    if not x or x == y:
        for col in columns:
            if col != y:
                x = col
                break
    if not x or x == y:
        return None
    return x, y


def _escape(field: str) -> str:
    """A column name inside a Vega expression. `Order Date` needs the brackets."""
    return "datum[" + json.dumps(field) + "]"


def number_format(values: list) -> str:
    """A d3 format string sized to the numbers actually present.

    `664.8717948717949` is the arithmetic, not the answer. How many decimals
    help is a property of the magnitudes in front of us: thousands need none,
    a column of small ratios needs two. Reading it off the data means the same
    code formats rupees and percentages without being told which it has.
    """
    numbers = [abs(v) for v in values if _is_numeric_cell(v)]
    if not numbers:
        return ""
    if all(float(v).is_integer() for v in numbers):
        return ","
    largest = max(numbers)
    if largest >= 1000:
        return ",.0f"
    if largest >= 10:
        return ",.1f"
    return ",.2f"


# A NULL category is a real group — "the rows with no department" — so it is
# labelled rather than dropped. Silently filtering it would change the total.
BLANK_LABEL = "(blank)"


def _label_layer(text: dict, compact: bool = False, **mark) -> dict:
    """A text mark carrying the value, so a chart can be read without a ruler."""
    size = 9 if compact else 11
    return {
        "mark": {"type": "text", "fontSize": size, **mark},
        "encoding": {"text": text},
    }


def compact_spec(spec: dict) -> dict:
    """Strip dashboard clutter — title lives on the panel header."""
    out = dict(spec)
    out.pop("title", None)
    encoding = out.get("encoding")
    if isinstance(encoding, dict):
        enc = dict(encoding)
        x_field = enc.get("x", {}).get("field") if isinstance(enc.get("x"), dict) else None
        color = enc.get("color")
        if (
            x_field
            and isinstance(color, dict)
            and color.get("field") == x_field
            and color.get("type") == "nominal"
        ):
            enc.pop("color", None)
        out["encoding"] = enc
    return out


def build_spec(
    plan: Plan,
    columns: list[str],
    rows: list[list],
    dtypes: dict[str, str],
    *,
    compact: bool = False,
) -> dict | None:
    """Vega-Lite spec without `data` — the caller injects the rows."""
    if plan.chart == "none" or not plan.chart_x or not plan.chart_y:
        return None
    if not (MIN_ROWS <= len(rows) <= MAX_ROWS):
        return None

    x = match_column(plan.chart_x, columns)
    if x is None:
        return None
    ys = [match_column(y, columns) for y in plan.chart_y]
    if not ys or any(y is None for y in ys):
        return None

    def field_type(column: str) -> str:
        key = match_column(column, list(dtypes)) or column
        return vega_type(dtypes.get(key, ""))

    y = ys[0]
    mark = {"bar": "bar", "line": "line", "pie": "arc", "scatter": "point"}[plan.chart]
    title = None if compact else f"{y} by {x}"
    fmt = number_format(_column_values(columns, rows, y))
    value_text = {"field": y, "type": "quantitative", "format": fmt}
    # A null x is a group with no name, not a missing row. Naming it keeps the
    # legend honest instead of printing "null" at the reader.
    blanks = [
        {
            "calculate": f"{_escape(x)} == null ? '{BLANK_LABEL}' : {_escape(x)}",
            "as": x,
        }
    ]

    if plan.chart == "pie":
        total = "__total"
        share = "__share"
        pie: dict = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "transform": blanks
            + [
                # Share of total is the only thing a pie says better than a
                # table, so it is what the slice is labelled with.
                {"joinaggregate": [{"op": "sum", "field": y, "as": total}], "groupby": []},
                {"calculate": f"{_escape(y)} / datum['{total}']", "as": share},
            ],
            "encoding": {
                "theta": {"field": y, "type": "quantitative", "stack": True},
                "color": {"field": x, "type": "nominal", "title": x},
                "tooltip": [
                    {"field": x, "type": "nominal"},
                    {"field": y, "type": "quantitative", "format": fmt},
                    {"field": share, "type": "quantitative", "format": ".1%", "title": "share"},
                ],
            },
            "layer": [
                {
                    "mark": {
                        "type": "arc",
                        "outerRadius": 88 if compact else 110,
                    }
                },
            ],
        }
        if title:
            pie["title"] = title
        if not compact:
            pie["layer"].append(
                _label_layer(
                    {"field": share, "type": "quantitative", "format": ".0%"},
                    radius=132,
                )
            )
        return pie

    x_encoding: dict = {"field": x, "type": field_type(x), "title": x}
    if plan.chart == "bar" and x_encoding["type"] == "nominal":
        x_encoding["sort"] = {"field": y, "op": "sum", "order": "descending"}

    spec: dict = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "transform": blanks if field_type(x) == "nominal" else [],
        "encoding": {
            "x": x_encoding,
            "y": {"field": y, "type": field_type(y), "title": y},
        },
        "layer": [{"mark": {"type": mark, "tooltip": True, "point": plan.chart == "line"}}],
    }
    if title:
        spec["title"] = title
    if len(ys) > 1:
        color_field = ys[1]
        if not (compact and color_field == x):
            spec["encoding"]["color"] = {"field": color_field, "type": field_type(color_field)}
    # One number per mark is readable; a scatter of forty points labelled forty
    # times is not, and the tooltip already answers "which point is this".
    if (
        not compact
        and plan.chart in ("bar", "line")
        and len(rows) <= LABEL_MAX_POINTS
    ):
        spec["layer"].append(_label_layer(value_text, dy=-8))
    return spec


# Column names that mean a candlestick — a shape plumb does not render.
_OHLC = ("open", "high", "low", "close")


def _classify(
    columns: list[str], dtypes: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Split result columns into temporal, quantitative, and nominal."""
    temporal: list[str] = []
    quantitative: list[str] = []
    nominal: list[str] = []
    for col in columns:
        key = match_column(col, list(dtypes)) or col
        kind = vega_type(dtypes.get(key, ""))
        (temporal if kind == "temporal" else quantitative if kind == "quantitative" else nominal).append(col)
    return temporal, quantitative, nominal


def _column_values(columns: list[str], rows: list[list], col: str) -> list:
    i = columns.index(col)
    return [row[i] for row in rows if i < len(row) and row[i] is not None]


def _has_null(columns: list[str], rows: list[list], col: str) -> bool:
    i = columns.index(col)
    return any(i >= len(row) or row[i] is None for row in rows)


def _unsupported_shape(columns: list[str]) -> str | None:
    """Name a chart the data asks for that plumb cannot draw."""
    lowered = {col.lower() for col in columns}
    if all(any(part == token or part.endswith("_" + token) for part in lowered) for token in _OHLC):
        return "candlestick"
    return None


def _is_sequence(values: list) -> bool:
    """Whether these x values are an evenly spaced run, whatever their dtype.

    `EXTRACT(year FROM hire_date)` comes back VARCHAR or BIGINT, never DATE, so
    a dtype check calls 2019…2026 eight unrelated categories. Even spacing is
    the property that actually makes an axis continuous, and it is measurable:
    sort the distinct values and see whether one step repeats. Departments
    never pass; years, months, and quarters always do.
    """
    numbers: list[float] = []
    for value in values:
        try:
            numbers.append(float(str(value).strip()))
        except (TypeError, ValueError):
            return False
    ordered = sorted(set(numbers))
    if len(ordered) < 3:
        return False
    steps = {round(b - a, 9) for a, b in zip(ordered, ordered[1:])}
    return len(steps) == 1


def _measure(columns: list[str], rows: list[list], dtypes: dict[str, str]) -> dict:
    """Everything the ranking is allowed to know, measured off the result rows."""
    temporal, quantitative, nominal = _classify(columns, dtypes)
    x = (temporal or nominal or quantitative[1:] or [None])[0]
    y = (quantitative or [None])[0]
    if y is not None and x == y:
        x = next((col for col in columns if col != y), None)
    x_values = _column_values(columns, rows, x) if x else []
    # A null x is drawn as its own `(blank)` bar, so it has to be counted as a
    # category too — otherwise the reason says five and the chart shows six.
    points = len(set(map(str, x_values))) + (
        1 if x and _has_null(columns, rows, x) else 0
    )
    measures = [v for v in (_column_values(columns, rows, y) if y else []) if _is_numeric_cell(v)]
    total = sum(abs(v) for v in measures)
    return {
        "rows": len(rows),
        "temporal": temporal,
        "quantitative": quantitative,
        "nominal": nominal,
        "x": x,
        "y": y,
        "points": points,
        # A continuous axis by measurement rather than by dtype.
        "continuous": bool(x) and (x in temporal or _is_sequence(x_values)),
        "measures": measures,
        "negatives": any(v < 0 for v in measures),
        # Share the smallest slice would take of a pie. A slice thinner than
        # one row's worth of the circle is a slice nobody can read.
        "min_share": (min(measures) / total) if measures and total else 0.0,
        "even_share": (1.0 / points) if points else 0.0,
    }


def _scores(m: dict) -> dict[str, float]:
    """Rank each chart kind against the measured result. Highest wins.

    No kind is gated behind a hand-picked threshold — each scores on the ratio
    the data itself produces, so the same code ranks two rows and two hundred
    without a magic number deciding where "too many" starts. The row cap is the
    one exception and it is not a taste call: `MAX_ROWS` is what the renderer
    can draw legibly, and `MIN_ROWS` is the point below which a chart has no
    second value to compare against.
    """
    if not (MIN_ROWS <= m["rows"] <= MAX_ROWS) or not m["y"] or not m["x"]:
        return {}

    spread = m["points"] / m["rows"] if m["rows"] else 0.0  # 1.0 = every row its own x
    crowding = m["points"] / MAX_ROWS  # how close the axis is to unreadable
    scores: dict[str, float] = {}

    if m["continuous"]:
        # A line needs somewhere to go. Two points are one interval — a segment,
        # which bars state without implying a slope — and the line's score rises
        # with every further interval the data actually contains.
        scores["line"] = (m["points"] - 2) / (m["points"] - 1) if m["points"] > 1 else 0.0
        scores["bar"] = 1.0 / m["points"] if m["points"] else 0.0
    elif m["x"] in m["nominal"] or m["x"] in m["quantitative"]:
        # Bars degrade gracefully as categories grow; pies do not.
        scores["bar"] = 1.0 - crowding
        if not m["negatives"] and len(m["quantitative"]) == 1 and m["min_share"] > 0:
            # A pie is honest only when the slices are parts of one whole and
            # the smallest is still a readable wedge relative to an even split.
            scores["pie"] = (m["min_share"] / m["even_share"]) * (1.0 - crowding)
    if len(m["quantitative"]) >= 2 and not m["nominal"] and not m["temporal"]:
        scores["scatter"] = spread
    return {kind: score for kind, score in scores.items() if score > 0}


def _reason(kind: str, m: dict, scores: dict[str, float]) -> str:
    """State the measurement that won, not a slogan about chart types."""
    if kind == "line":
        return (
            f"{m['y']} is measured at {m['points']} points of {m['x']}, so a line "
            f"shows the direction between them."
        )
    if kind == "bar":
        if m["continuous"]:
            return (
                f"Only {m['points']} points on {m['x']} — too few intervals for a "
                f"trend, so bars compare them without implying a slope."
            )
        note = (
            f" A pie also holds here: the smallest slice is "
            f"{m['min_share'] * 100:.0f}% against an even {m['even_share'] * 100:.0f}%."
            if scores.get("pie", 0) > 0
            else ""
        )
        return (
            f"{m['points']} categories of {m['x']} against {m['y']}. Length compares "
            f"more precisely than angle, so bars rank them." + note
        )
    if kind == "pie":
        return (
            f"{m['points']} slices of {m['y']}, smallest at {m['min_share'] * 100:.0f}% "
            f"of the total — each wedge stays readable, so share reads directly."
        )
    if kind == "scatter":
        return (
            f"{m['rows']} rows of {m['y']} against {m['x']} with no category to group "
            f"by — a scatter shows whether the two move together."
        )
    if m["rows"] < MIN_ROWS:
        return (
            "One row is a number, not a shape — the table states it more precisely."
            if m["rows"] == 1
            else "No rows came back, so there is nothing to plot."
        )
    if m["rows"] > MAX_ROWS:
        return (
            f"{m['rows']} rows is past the {MAX_ROWS} this renderer can draw legibly. "
            f"A top-N or a grouped total makes it plottable."
        )
    if not m["quantitative"]:
        return "No numeric column came back, so there is nothing to measure on an axis."
    if not m["x"]:
        return f"Only {m['y']} came back — nothing to plot it against."
    return "Nothing in this result shape reads better as a chart than as the table."


def recommend(
    columns: list[str], rows: list[list], dtypes: dict[str, str]
) -> ChartAdvice:
    """The chart this *result* wants, read off the rows rather than the question.

    `Plan.chart` is the model's opinion about a sentence. This is arithmetic on
    what came back: row count, distinct categories, dtype per axis, sign, and
    how evenly the measure is spread. When the two disagree the user is told
    both — a pie of forty slices is a rendering of a bad choice, not a bad
    question.
    """
    dtypes = enrich_dtypes(columns, rows, dtypes)
    m = _measure(columns, rows, dtypes)
    scores = _scores(m)
    unsupported = _unsupported_shape(columns)

    if not scores:
        return ChartAdvice(kind="none", reason=_reason("none", m, scores), unsupported=unsupported)

    ranked = sorted(scores, key=lambda kind: scores[kind], reverse=True)
    best = ranked[0]
    # An alternative worth naming is one that scored in the same class as the
    # winner. A pie whose smallest wedge is a hair is technically drawable and
    # offering it would be advice nobody should take.
    ranked = [kind for kind in ranked if scores[kind] * 2 >= scores[best]]
    x, y = m["x"], m["y"]
    if best == "scatter":
        x, y = m["quantitative"][0], m["quantitative"][1]
    return ChartAdvice(
        kind=best,  # type: ignore[arg-type]
        x=x,
        y=y,
        reason=_reason(best, m, {kind: scores[kind] for kind in ranked}),
        alternatives=ranked[1:],
        unsupported=unsupported,
    )


def build_from_advice(
    advice: ChartAdvice,
    columns: list[str],
    rows: list[list],
    dtypes: dict[str, str],
    *,
    compact: bool = False,
) -> dict | None:
    """Draw what the result shape asked for, when the question named nothing.

    The brief asks for a chart "where the question calls for one". A question
    calls for one when its *answer* has a shape — which is what `recommend`
    already measured. Leaving that measurement unrendered produced the worst
    of both: a card that said "better as a bar" above no chart at all.
    """
    if advice.kind == "none" or not advice.x or not advice.y:
        return None
    spec = build_spec(
        Plan(
            route="answer",
            sql="",
            chart=advice.kind,  # type: ignore[arg-type]
            chart_x=advice.x,
            chart_y=[advice.y],
        ),
        columns,
        rows,
        dtypes,
        compact=compact,
    )
    return compact_spec(spec) if spec is not None and compact else spec


def build_spec_for_question(
    question: str,
    plan: Plan,
    columns: list[str],
    rows: list[list],
    dtypes: dict[str, str],
) -> tuple[dict | None, str | None]:
    """Use the plan's chart fields, or infer them when the user only asked to chart."""
    dtypes = enrich_dtypes(columns, rows, dtypes)
    spec = build_spec(plan, columns, rows, dtypes)
    if spec is not None:
        return spec, plan.chart if plan.chart != "none" else None
    kind = visualization_kind(question)
    if not kind:
        return None, None
    axes = infer_axes(columns, dtypes)
    if axes is None:
        return None, None
    x, y = axes
    inferred = Plan(
        route="answer",
        sql=plan.sql or "",
        chart=kind,  # type: ignore[arg-type]
        chart_x=x,
        chart_y=[y],
    )
    spec = build_spec(inferred, columns, rows, dtypes)
    return spec, kind if spec is not None else None
