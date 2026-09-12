"""Aggregating item scores into a reportable result.

Three headline numbers, deliberately kept separate:

- execution_rate: did the generated KQL run at all
- strict_accuracy: did it return exactly the committed rows, in order
- semantic_accuracy: did it return the right data, ignoring cosmetics

A single accuracy figure would conflate "produced invalid KQL", "misunderstood
the question", and "named a column differently", which are three different
problems with three different fixes.
"""

from __future__ import annotations

from pydantic import BaseModel

from kql_eval.evaluation.scoring import CREDITED, Grade, ItemScore


class CategoryBreakdown(BaseModel):
    category: str
    items: int
    executed: int
    exact: int
    credited: int

    @property
    def strict_accuracy(self) -> float:
        return self.exact / self.items if self.items else 0.0

    @property
    def semantic_accuracy(self) -> float:
        return self.credited / self.items if self.items else 0.0


class EvalReport(BaseModel):
    model: str
    corpus_version: str
    scores: list[ItemScore]

    @property
    def total(self) -> int:
        return len(self.scores)

    @property
    def execution_rate(self) -> float:
        if not self.scores:
            return 0.0
        ran = sum(1 for s in self.scores if s.grade is not Grade.ERROR)
        return ran / self.total

    @property
    def strict_accuracy(self) -> float:
        if not self.scores:
            return 0.0
        return sum(1 for s in self.scores if s.grade is Grade.EXACT) / self.total

    @property
    def semantic_accuracy(self) -> float:
        if not self.scores:
            return 0.0
        return sum(1 for s in self.scores if s.grade in CREDITED) / self.total

    def grade_counts(self) -> dict[str, int]:
        counts = {g.value: 0 for g in Grade}
        for score in self.scores:
            counts[score.grade.value] += 1
        return counts

    def by_category(self) -> list[CategoryBreakdown]:
        categories: dict[str, list[ItemScore]] = {}
        for score in self.scores:
            categories.setdefault(score.category, []).append(score)

        return [
            CategoryBreakdown(
                category=name,
                items=len(group),
                executed=sum(1 for s in group if s.grade is not Grade.ERROR),
                exact=sum(1 for s in group if s.grade is Grade.EXACT),
                credited=sum(1 for s in group if s.grade in CREDITED),
            )
            for name, group in sorted(categories.items())
        ]

    def failures(self) -> list[ItemScore]:
        return [s for s in self.scores if s.grade not in CREDITED]

    def render(self) -> str:
        """Human-readable summary for the terminal."""
        lines = [
            f"model:  {self.model}",
            f"corpus: {self.corpus_version}  ({self.total} items)",
            "",
            f"  execution rate     {self.execution_rate:6.1%}",
            f"  strict accuracy    {self.strict_accuracy:6.1%}",
            f"  semantic accuracy  {self.semantic_accuracy:6.1%}",
            "",
            "  grades: "
            + ", ".join(f"{k}={v}" for k, v in self.grade_counts().items() if v),
            "",
            f"  {'category':<22} {'n':>3} {'strict':>8} {'semantic':>9}",
        ]
        for row in self.by_category():
            lines.append(
                f"  {row.category:<22} {row.items:>3} "
                f"{row.strict_accuracy:>8.1%} {row.semantic_accuracy:>9.1%}"
            )
        return "\n".join(lines)
