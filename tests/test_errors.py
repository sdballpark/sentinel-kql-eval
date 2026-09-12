"""Error taxonomy. Message shapes were probed off the live emulator."""

from __future__ import annotations

import pytest

from kql_eval.evaluation.errors import (
    DESCRIPTIONS,
    ErrorKind,
    classify_error,
    unresolved_name,
)

UNKNOWN_COLUMN = (
    "HTTP 400: Semantic error: SEM0100: 'where' operator: Failed to resolve "
    "column or scalar expression named 'NoSuchColumn'"
)
UNKNOWN_TABLE = (
    "HTTP 400: Semantic error: SEM0100: 'count' operator: Failed to resolve "
    "table or column expression named 'NoSuchTable'"
)
JOIN_KEY = (
    "HTTP 400: Semantic error: SEM0100: 'join' operator: Failed to resolve "
    "scalar expression named 'NotAColumn'"
)
SYNTAX = "HTTP 400: Syntax error: SYN0002: Query operator expected"
UNKNOWN_FUNC = "HTTP 400: Semantic error: SEM0260: Unknown function: 'nosuchfunc'"
TYPE_MISMATCH = "HTTP 400: Semantic error: SEM0064: Cannot compare values of types"
JOIN_STRUCTURE = "HTTP 400: Semantic error: SEM0400: join: Invalid"
RESOLVE_139 = "HTTP 400: Semantic error: SEM0139: Failed to resolve something"


def test_no_error_classifies_as_none():
    assert classify_error(None) is None
    assert classify_error("") is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (UNKNOWN_COLUMN, ErrorKind.UNKNOWN_COLUMN),
        (JOIN_KEY, ErrorKind.UNKNOWN_COLUMN),
        (RESOLVE_139, ErrorKind.UNKNOWN_COLUMN),
        (UNKNOWN_TABLE, ErrorKind.UNKNOWN_TABLE),
        (SYNTAX, ErrorKind.SYNTAX),
        (UNKNOWN_FUNC, ErrorKind.UNKNOWN_FUNCTION),
        (TYPE_MISMATCH, ErrorKind.TYPE_MISMATCH),
        (JOIN_STRUCTURE, ErrorKind.JOIN_STRUCTURE),
    ],
)
def test_classification(error, expected):
    assert classify_error(error) is expected


def test_syntax_beats_semantic_when_both_words_appear():
    """A parse failure never reaches name resolution, so syntax must win."""
    mixed = "Syntax error: SYN0002: near 'Failed to resolve'"
    assert classify_error(mixed) is ErrorKind.SYNTAX


def test_unknown_column_is_distinct_from_syntax():
    """The whole point of the taxonomy: these are opposite findings."""
    assert classify_error(UNKNOWN_COLUMN) is not classify_error(SYNTAX)


def test_generation_timeout_is_separate_from_execution_failure():
    assert classify_error("generation failed: timed out") is ErrorKind.GENERATION_TIMEOUT
    assert classify_error("generation failed: connection refused") is ErrorKind.GENERATION_FAILED


def test_unrecognised_semantic_code_falls_back():
    assert classify_error("Semantic error: SEM9999: something new") is ErrorKind.SEMANTIC_OTHER


def test_completely_unknown_error_is_other():
    assert classify_error("the disk caught fire") is ErrorKind.OTHER


@pytest.mark.parametrize(
    ("error", "name"),
    [
        (UNKNOWN_COLUMN, "NoSuchColumn"),
        (UNKNOWN_TABLE, "NoSuchTable"),
        (JOIN_KEY, "NotAColumn"),
    ],
)
def test_unresolved_name_extraction(error, name):
    assert unresolved_name(error) == name


def test_unresolved_name_absent_when_engine_named_nothing():
    assert unresolved_name(SYNTAX) is None
    assert unresolved_name(None) is None


def test_every_kind_has_a_description():
    for kind in ErrorKind:
        assert DESCRIPTIONS.get(kind)
