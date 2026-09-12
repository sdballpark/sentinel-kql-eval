"""Corpus and fixture schemas.

An item pairs a plain-English security question with a reference KQL query and
the rows that query is expected to return. Expected rows are committed rather
than computed at run time so that a wrong reference query is a test failure
instead of a silently moving target.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ColumnType = Literal["string", "int", "long", "real", "bool", "datetime"]

Category = Literal[
    "filtering_and_time",
    "aggregation",
    "join_and_correlation",
    "detection_logic",
    "schema_navigation",
]


class FixtureTable(BaseModel):
    name: str
    columns: dict[str, ColumnType]
    rows: list[dict[str, Any]]

    @model_validator(mode="after")
    def rows_match_columns(self) -> FixtureTable:
        allowed = set(self.columns)
        for i, row in enumerate(self.rows):
            extra = set(row) - allowed
            if extra:
                raise ValueError(f"{self.name} row {i} has unknown columns: {sorted(extra)}")
            missing = allowed - set(row)
            if missing:
                raise ValueError(f"{self.name} row {i} missing columns: {sorted(missing)}")
        return self


class CorpusItem(BaseModel):
    id: str
    question: str
    category: Category
    tables: list[str] = Field(min_length=1)
    reference_kql: str
    expected_rows: list[dict[str, Any]]
    notes: str | None = None

    @model_validator(mode="after")
    def expected_rows_are_uniform(self) -> CorpusItem:
        if self.expected_rows:
            first = set(self.expected_rows[0])
            for i, row in enumerate(self.expected_rows[1:], start=1):
                if set(row) != first:
                    raise ValueError(f"{self.id} expected_rows[{i}] has a different shape")
        return self


class Corpus(BaseModel):
    version: str
    fixtures: list[FixtureTable]
    items: list[CorpusItem]

    @model_validator(mode="after")
    def ids_unique_and_tables_exist(self) -> Corpus:
        seen: set[str] = set()
        for item in self.items:
            if item.id in seen:
                raise ValueError(f"duplicate item id: {item.id}")
            seen.add(item.id)

        known = {t.name for t in self.fixtures}
        for item in self.items:
            unknown = set(item.tables) - known
            if unknown:
                raise ValueError(f"{item.id} references missing fixtures: {sorted(unknown)}")
        return self

    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.category] = counts.get(item.category, 0) + 1
        return counts
