"""The contract every query generator implements.

Baselines and real model generators sit behind the same interface so the
harness cannot accidentally give one of them more context than another. What a
generator receives is deliberately thin -- the question and the names of the
tables in scope -- because handing it column lists would turn the benchmark
into a schema-lookup test rather than a question-understanding one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Generator(Protocol):
    """Turns a plain-English security question into a KQL query."""

    name: str

    def generate(self, question: str, tables: Sequence[str]) -> str:
        """Return a KQL query answering question over the named tables."""
        ...


_FENCE = re.compile(r"^\s*```(?:[A-Za-z]*)\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Unwrap a fenced code block if the model produced one.

    Instruction-tuned models fence code even when told not to, and a stray
    fence is a syntax error the moment the query reaches the engine. Stripping
    it measures the query the model meant to write rather than its obedience
    about formatting.
    """
    match = _FENCE.match(text.strip())
    return (match.group(1) if match else text).strip()
