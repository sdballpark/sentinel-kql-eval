"""Scoring generated queries against the committed expected rows.

Strict equality is the honest headline number, but on its own it is misleading.
A model can answer a question correctly and still fail strict equality for
reasons an analyst would not care about: KQL names a bare `summarize count()`
column `count_`, so a query that is otherwise perfect disagrees on a column
name; a question that never asked for an ordering gets rows back in a different
order; a model that skips a final `project` returns the right answer plus extra
columns.

Grading in tiers keeps the strict number as the headline while making visible
how much of the remaining gap is cosmetic rather than substantive. That split
is usually the interesting finding, so it should not be hidden inside a single
pass/fail.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from kql_eval.corpus.schema import CorpusItem


class Grade(StrEnum):
    """How closely a result matched, from strictest to weakest.

    Tiers are tried in declaration order and the first that holds wins, so a
    grade always names the strongest statement that is true of the result.
    """

    EXACT = "exact"
    UNORDERED = "unordered"
    EXTRA_COLUMNS = "extra_columns"
    RENAMED_COLUMNS = "renamed_columns"
    MISMATCH = "mismatch"
    ERROR = "error"


#: Grades where the model retrieved the right data, whatever it called the
#: columns or what order it returned them in.
CREDITED = frozenset(
    {Grade.EXACT, Grade.UNORDERED, Grade.EXTRA_COLUMNS, Grade.RENAMED_COLUMNS}
)

def normalize_value(value: Any) -> Any:
    """Collapse engine datetime formatting before comparison.

    Kusto renders datetimes with seven fractional digits while the corpus
    commits whole seconds. Without this every datetime column compares unequal
    and the scores are meaningless.

    Only strings shaped like a UTC timestamp are touched, so a value that merely
    happens to be ISO-parseable -- a bare date sitting in a string column, say --
    is left exactly as the engine returned it.
    """
    if not isinstance(value, str) or "T" not in value or not value.endswith("Z"):
        return value
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: normalize_value(v) for k, v in row.items()} for row in rows]


def _row_key(row: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Canonical hashable form of a row, insensitive to column order."""
    return tuple(sorted(row.items(), key=lambda kv: kv[0]))


def _row_bag(rows: list[dict[str, Any]]) -> Counter[tuple[tuple[str, Any], ...]]:
    return Counter(_row_key(r) for r in rows)


def _values_key(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Canonical form of a row's values with column names discarded.

    Values are keyed by (type, repr) so rows holding mixed types stay sortable.
    This deliberately cannot tell apart two columns of the same type whose
    values were swapped, which is an acceptable false positive in the weakest
    tier but means RENAMED_COLUMNS is evidence of a near miss, not proof of one.
    """
    return tuple(sorted((type(v).__name__, str(v)) for v in row.values()))


def _values_bag(rows: list[dict[str, Any]]) -> Counter[tuple[tuple[str, str], ...]]:
    return Counter(_values_key(r) for r in rows)


def grade_rows(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]]
) -> Grade:
    """Return the strongest equivalence that holds between two result sets."""
    expected = normalize_rows(expected)
    actual = normalize_rows(actual)

    if actual == expected:
        return Grade.EXACT

    if _row_bag(actual) == _row_bag(expected):
        return Grade.UNORDERED

    # A model that omitted a final `project` still answered the question, so
    # long as every column that was asked for is present and correct.
    if expected and actual:
        wanted = set(expected[0])
        if wanted < set(actual[0]):
            trimmed = [{k: row[k] for k in wanted} for row in actual]
            if _row_bag(trimmed) == _row_bag(expected):
                return Grade.EXTRA_COLUMNS

    if _values_bag(actual) == _values_bag(expected):
        return Grade.RENAMED_COLUMNS

    return Grade.MISMATCH


class ItemScore(BaseModel):
    item_id: str
    category: str
    grade: Grade
    expected_row_count: int
    actual_row_count: int | None = None
    error: str | None = None

    @property
    def credited(self) -> bool:
        return self.grade in CREDITED


def score_item(
    item: CorpusItem,
    actual: list[dict[str, Any]] | None,
    error: str | None = None,
) -> ItemScore:
    """Score one generated query's result against its corpus item.

    Pass actual=None with an error when the query failed to execute; a query
    that does not run is a distinct failure from one that runs and is wrong,
    and collapsing the two hides whether a model produces invalid KQL.
    """
    if error is not None or actual is None:
        return ItemScore(
            item_id=item.id,
            category=item.category,
            grade=Grade.ERROR,
            expected_row_count=len(item.expected_rows),
            error=error or "no result returned",
        )

    return ItemScore(
        item_id=item.id,
        category=item.category,
        grade=grade_rows(item.expected_rows, actual),
        expected_row_count=len(item.expected_rows),
        actual_row_count=len(actual),
    )
