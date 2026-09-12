"""The committed corpus must stay valid and balanced. No emulator required."""

from __future__ import annotations

from pathlib import Path

import pytest

from kql_eval.corpus.loader import load_corpus
from kql_eval.corpus.schema import Category

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "data" / "corpus" / "corpus_v1.json"


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(CORPUS_PATH)


def test_corpus_validates(corpus):
    assert corpus.version
    assert corpus.items
    assert corpus.fixtures


def test_every_category_is_represented(corpus):
    counts = corpus.category_counts()
    for category in Category.__args__:
        assert counts.get(category, 0) > 0, f"{category} has no items"


def test_item_ids_are_unique(corpus):
    ids = [i.id for i in corpus.items]
    assert len(ids) == len(set(ids))


def test_every_item_references_known_fixtures(corpus):
    known = {t.name for t in corpus.fixtures}
    for item in corpus.items:
        assert set(item.tables) <= known, item.id


def test_no_item_expects_an_empty_result(corpus):
    """An item expecting zero rows is passed by any query returning nothing."""
    empty = [i.id for i in corpus.items if not i.expected_rows]
    assert not empty, f"items with no expected rows: {empty}"


def test_expected_rows_are_uniform_within_an_item(corpus):
    for item in corpus.items:
        shapes = {frozenset(r) for r in item.expected_rows}
        assert len(shapes) == 1, item.id


def test_fixtures_have_enough_rows_to_be_interesting(corpus):
    for table in corpus.fixtures:
        assert len(table.rows) >= 12, f"{table.name} has only {len(table.rows)} rows"


def test_reference_queries_mention_their_declared_tables(corpus):
    """Catches an item whose tables list drifted from the query it describes."""
    for item in corpus.items:
        for table in item.tables:
            assert table in item.reference_kql, f"{item.id} does not query {table}"
