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
