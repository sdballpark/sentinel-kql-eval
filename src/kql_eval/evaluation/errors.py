"""Classifying why a generated query failed.

A single error count answers the wrong question. "20 of 22 failed" reads as a
model that cannot write KQL, when the schema-blind baseline was in fact
producing well-formed queries against column names it had no way to know. Those
are opposite findings with opposite fixes -- one calls for a better model, the
other for putting the schema in the prompt -- so the harness has to tell them
apart.

Codes and message shapes below were read off the emulator by probing it with
deliberately broken queries, not taken from documentation.
"""

from __future__ import annotations

import re
from enum import StrEnum


class ErrorKind(StrEnum):
    """Why an item produced no scorable result."""

    #: Referenced a column that does not exist. The query was well-formed.
    UNKNOWN_COLUMN = "unknown_column"
    #: Referenced a table that does not exist. Kusto cannot always tell this
    #: apart from a column reference in leading position, and says so.
    UNKNOWN_TABLE = "unknown_table"
    UNKNOWN_FUNCTION = "unknown_function"
    #: Malformed KQL -- the parser never got as far as resolving names.
    SYNTAX = "syntax"
    TYPE_MISMATCH = "type_mismatch"
    JOIN_STRUCTURE = "join_structure"
    SEMANTIC_OTHER = "semantic_other"
    #: The generator itself failed, so no query was ever produced.
    GENERATION_TIMEOUT = "generation_timeout"
    GENERATION_FAILED = "generation_failed"
    OTHER = "other"


#: Human-readable gloss, used when rendering a taxonomy.
DESCRIPTIONS = {
    ErrorKind.UNKNOWN_COLUMN: "valid KQL, column does not exist",
    ErrorKind.UNKNOWN_TABLE: "valid KQL, table does not exist",
    ErrorKind.UNKNOWN_FUNCTION: "called a function KQL does not have",
    ErrorKind.SYNTAX: "malformed KQL, failed to parse",
    ErrorKind.TYPE_MISMATCH: "compared or combined incompatible types",
    ErrorKind.JOIN_STRUCTURE: "join built incorrectly",
    ErrorKind.SEMANTIC_OTHER: "other semantic error",
    ErrorKind.GENERATION_TIMEOUT: "model did not answer in time",
    ErrorKind.GENERATION_FAILED: "generator raised before producing a query",
    ErrorKind.OTHER: "unclassified",
}

_UNRESOLVED_NAME = re.compile(r"Failed to resolve [^']*named '([^']+)'")


def classify_error(error: str | None) -> ErrorKind | None:
    """Bucket an error string by root cause.

    Returns None when there is no error at all, so a caller can distinguish
    "succeeded" from "failed for an unclassifiable reason".
    """
    if not error:
        return None

    if error.startswith("generation failed"):
        return (
            ErrorKind.GENERATION_TIMEOUT
            if "timed out" in error or "timeout" in error.lower()
            else ErrorKind.GENERATION_FAILED
        )

    # Parse failures never reach name resolution, so they are checked first.
    if "Syntax error" in error or re.search(r"\bSYN\d{4}\b", error):
        return ErrorKind.SYNTAX

    if "Unknown function" in error or "SEM0260" in error:
        return ErrorKind.UNKNOWN_FUNCTION

    if "Failed to resolve" in error:
        # Kusto reports a leading unknown identifier as "table or column",
        # because in that position it genuinely cannot tell which was meant.
        if "table or column expression" in error:
            return ErrorKind.UNKNOWN_TABLE
        return ErrorKind.UNKNOWN_COLUMN

    if "SEM0064" in error or "Cannot compare" in error:
        return ErrorKind.TYPE_MISMATCH

    if "SEM0400" in error or "join: Invalid" in error:
        return ErrorKind.JOIN_STRUCTURE

    if re.search(r"\bSEM\d{4}\b", error):
        return ErrorKind.SEMANTIC_OTHER

    return ErrorKind.OTHER


def unresolved_name(error: str | None) -> str | None:
    """Extract the identifier Kusto could not resolve, when it named one.

    Aggregated across a run this is the single most useful diagnostic: it says
    exactly which columns a model invented.
    """
    if not error:
        return None
    match = _UNRESOLVED_NAME.search(error)
    return match.group(1) if match else None
