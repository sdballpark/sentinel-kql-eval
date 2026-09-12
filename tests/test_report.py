"""Aggregation behaviour for eval reports. No emulator required."""

from __future__ import annotations

from kql_eval.evaluation.report import EvalReport
from kql_eval.evaluation.scoring import Grade, ItemScore


def _score(item_id: str, category: str, grade: Grade) -> ItemScore:
    return ItemScore(
        item_id=item_id, category=category, grade=grade, expected_row_count=1
    )


def _report(*scores: ItemScore) -> EvalReport:
    return EvalReport(model="test-model", corpus_version="1.0.0", scores=list(scores))


def test_empty_report_does_not_divide_by_zero():
    report = _report()
    assert report.execution_rate == 0.0
    assert report.strict_accuracy == 0.0
    assert report.semantic_accuracy == 0.0


def test_strict_is_stricter_than_semantic():
    report = _report(
        _score("a", "aggregation", Grade.EXACT),
        _score("b", "aggregation", Grade.RENAMED_COLUMNS),
        _score("c", "aggregation", Grade.UNORDERED),
        _score("d", "aggregation", Grade.MISMATCH),
    )
    assert report.strict_accuracy == 0.25
    assert report.semantic_accuracy == 0.75


def test_errors_lower_execution_rate_but_mismatches_do_not():
    report = _report(
        _score("a", "aggregation", Grade.ERROR),
        _score("b", "aggregation", Grade.MISMATCH),
        _score("c", "aggregation", Grade.EXACT),
        _score("d", "aggregation", Grade.EXACT),
    )
    assert report.execution_rate == 0.75
    assert report.strict_accuracy == 0.5


def test_grade_counts_cover_every_grade():
    report = _report(_score("a", "aggregation", Grade.EXACT))
    counts = report.grade_counts()
    assert set(counts) == {g.value for g in Grade}
    assert counts["exact"] == 1
    assert counts["mismatch"] == 0


def test_breakdown_splits_by_category():
    report = _report(
        _score("a", "aggregation", Grade.EXACT),
        _score("b", "aggregation", Grade.MISMATCH),
        _score("c", "detection_logic", Grade.EXACT),
    )
    rows = {r.category: r for r in report.by_category()}
    assert rows["aggregation"].strict_accuracy == 0.5
    assert rows["detection_logic"].strict_accuracy == 1.0
    assert rows["detection_logic"].items == 1


def test_failures_lists_uncredited_items_only():
    report = _report(
        _score("a", "aggregation", Grade.EXACT),
        _score("b", "aggregation", Grade.UNORDERED),
        _score("c", "aggregation", Grade.MISMATCH),
        _score("d", "aggregation", Grade.ERROR),
    )
    assert [s.item_id for s in report.failures()] == ["c", "d"]


def test_render_produces_a_summary():
    report = _report(_score("a", "aggregation", Grade.EXACT))
    out = report.render()
    assert "test-model" in out
    assert "strict accuracy" in out
    assert "aggregation" in out


# --- error taxonomy ---------------------------------------------------------


def _error_score(item_id: str, error: str) -> ItemScore:
    from kql_eval.corpus.schema import CorpusItem
    from kql_eval.evaluation.scoring import score_item

    item = CorpusItem(
        id=item_id,
        question="q",
        category="aggregation",
        tables=["SecurityEvent"],
        reference_kql="SecurityEvent | count",
        expected_rows=[{"Count": 1}],
    )
    return score_item(item, None, error=error)


UNKNOWN_COLUMN = (
    "Semantic error: SEM0100: 'where' operator: Failed to resolve column or "
    "scalar expression named 'TargetAccount'"
)
SYNTAX = "Syntax error: SYN0002: Query operator expected"


def test_taxonomy_separates_unknown_column_from_syntax():
    report = _report(
        _error_score("a", UNKNOWN_COLUMN),
        _error_score("b", UNKNOWN_COLUMN),
        _error_score("c", SYNTAX),
    )
    taxonomy = report.error_taxonomy()
    assert taxonomy["unknown_column"] == 2
    assert taxonomy["syntax"] == 1


def test_taxonomy_is_empty_when_nothing_errored():
    assert _report(_score("a", "aggregation", Grade.EXACT)).error_taxonomy() == {}


def test_taxonomy_is_ordered_most_common_first():
    report = _report(
        _error_score("a", SYNTAX),
        _error_score("b", UNKNOWN_COLUMN),
        _error_score("c", UNKNOWN_COLUMN),
    )
    assert next(iter(report.error_taxonomy())) == "unknown_column"


def test_unresolved_names_are_collected_and_counted():
    report = _report(
        _error_score("a", UNKNOWN_COLUMN),
        _error_score("b", UNKNOWN_COLUMN),
        _error_score("c", SYNTAX),
    )
    assert report.top_unresolved_names() == [("TargetAccount", 2)]


def test_render_shows_taxonomy_when_errors_exist():
    out = _report(_error_score("a", UNKNOWN_COLUMN)).render()
    assert "failure cause" in out
    assert "unknown_column" in out
    assert "TargetAccount" in out


def test_render_omits_taxonomy_when_clean():
    out = _report(_score("a", "aggregation", Grade.EXACT)).render()
    assert "failure cause" not in out
