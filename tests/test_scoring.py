"""Unit tests for the grading tiers. No emulator required."""

from __future__ import annotations

import pytest

from kql_eval.corpus.schema import CorpusItem
from kql_eval.evaluation.scoring import (
    CREDITED,
    Grade,
    grade_rows,
    normalize_rows,
    normalize_value,
    score_item,
)

ROWS = [
    {"IpAddress": "203.0.113.45", "FailedLogons": 7},
    {"IpAddress": "198.51.100.22", "FailedLogons": 2},
]


def test_identical_rows_are_exact():
    assert grade_rows(ROWS, list(ROWS)) is Grade.EXACT


def test_empty_results_match_exactly():
    assert grade_rows([], []) is Grade.EXACT


def test_column_order_within_a_row_does_not_matter():
    flipped = [{"FailedLogons": r["FailedLogons"], "IpAddress": r["IpAddress"]} for r in ROWS]
    assert grade_rows(ROWS, flipped) is Grade.EXACT


def test_reordered_rows_are_unordered():
    assert grade_rows(ROWS, list(reversed(ROWS))) is Grade.UNORDERED


def test_extra_columns_are_credited_separately():
    padded = [{**r, "Computer": "WEB01"} for r in ROWS]
    assert grade_rows(ROWS, padded) is Grade.EXTRA_COLUMNS


def test_renamed_summarize_column_is_credited():
    # KQL names a bare `summarize count()` column `count_`.
    renamed = [{"IpAddress": r["IpAddress"], "count_": r["FailedLogons"]} for r in ROWS]
    assert grade_rows(ROWS, renamed) is Grade.RENAMED_COLUMNS


def test_wrong_values_are_a_mismatch():
    wrong = [{**ROWS[0], "FailedLogons": 99}, ROWS[1]]
    assert grade_rows(ROWS, wrong) is Grade.MISMATCH


def test_missing_row_is_a_mismatch():
    assert grade_rows(ROWS, ROWS[:1]) is Grade.MISMATCH


def test_missing_column_is_not_credited_as_extra_columns():
    trimmed = [{"IpAddress": r["IpAddress"]} for r in ROWS]
    assert grade_rows(ROWS, trimmed) is Grade.MISMATCH


def test_empty_expected_against_rows_is_a_mismatch():
    assert grade_rows([], ROWS) is Grade.MISMATCH


@pytest.mark.parametrize(
    "raw",
    ["2026-09-07T01:12:05.0000000Z", "2026-09-07T01:12:05.000Z", "2026-09-07T01:12:05Z"],
)
def test_kusto_fractional_seconds_normalize_to_committed_form(raw):
    assert normalize_value(raw) == "2026-09-07T01:12:05Z"


def test_non_datetime_strings_pass_through():
    assert normalize_value("WEB01") == "WEB01"
    assert normalize_value(7) == 7


def test_datetime_formatting_does_not_break_exact_match():
    expected = [{"TimeGenerated": "2026-09-07T01:12:05Z"}]
    from_engine = [{"TimeGenerated": "2026-09-07T01:12:05.0000000Z"}]
    assert grade_rows(expected, from_engine) is Grade.EXACT


def test_normalize_rows_leaves_structure_intact():
    assert normalize_rows(ROWS) == ROWS


def _item() -> CorpusItem:
    return CorpusItem(
        id="t-001",
        question="q",
        category="aggregation",
        tables=["SecurityEvent"],
        reference_kql="SecurityEvent | count",
        expected_rows=ROWS,
    )


def test_score_item_records_counts():
    score = score_item(_item(), list(ROWS))
    assert score.grade is Grade.EXACT
    assert score.expected_row_count == 2
    assert score.actual_row_count == 2
    assert score.credited


def test_failed_execution_is_error_not_mismatch():
    score = score_item(_item(), None, error="Syntax error near 'summarize'")
    assert score.grade is Grade.ERROR
    assert score.actual_row_count is None
    assert "Syntax error" in score.error
    assert not score.credited


def test_error_grade_is_not_credited():
    assert Grade.ERROR not in CREDITED
    assert Grade.MISMATCH not in CREDITED
