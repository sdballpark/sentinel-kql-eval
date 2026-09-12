"""Executing KQL against a local Kusto emulator.

The emulator runs the real Kusto query engine, so query semantics match Azure
Data Explorer and Sentinel rather than an approximation of them. That matters
because the corpus commits expected rows to disk as ground truth: if the engine
only approximated KQL, a disagreement between expected and actual could not be
attributed to the query under test.
"""

from __future__ import annotations

import os
from typing import Any, Self

import httpx

from kql_eval.corpus.schema import FixtureTable

# Loopback by default: the emulator supports neither HTTPS nor Entra auth, so
# it must never be reachable off the host. Override only for a remote cluster
# that does authenticate.
DEFAULT_ENDPOINT = os.environ.get("KQL_EVAL_KUSTO_ENDPOINT", "http://127.0.0.1:8080")
DEFAULT_DATABASE = "NetDefaultDB"

# Corpus ColumnType -> KQL scalar type. One-to-one, but stated explicitly so a
# schema change surfaces here instead of producing a confusing ingestion error.
_KQL_TYPES = {
    "string": "string",
    "int": "int",
    "long": "long",
    "real": "real",
    "bool": "bool",
    "datetime": "datetime",
}

_STRING_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _kql_literal(value: Any, column_type: str) -> str:
    """Render a Python value as a KQL scalar literal."""
    if value is None:
        return "dynamic(null)"
    if column_type == "datetime":
        return f"datetime({value})"
    if column_type == "bool":
        return "true" if value else "false"
    if column_type in ("int", "long", "real"):
        return str(value)
    escaped = "".join(_STRING_ESCAPES.get(ch, ch) for ch in str(value))
    return f'"{escaped}"'


def _datatable_expression(table: FixtureTable) -> str:
    """Build a datatable() literal holding the whole fixture.

    Inlining the rows avoids mounting a data volume into the container, which
    keeps ingestion a pure function of the corpus file.
    """
    schema = ", ".join(f"{name}:{_KQL_TYPES[t]}" for name, t in table.columns.items())
    cells = [
        ", ".join(_kql_literal(row[name], t) for name, t in table.columns.items())
        for row in table.rows
    ]
    body = ",\n  ".join(cells)
    return f"datatable({schema}) [\n  {body}\n]"


class KustoEmulator:
    """Thin client over the emulator's HTTP query and management endpoints."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        database: str = DEFAULT_DATABASE,
        timeout: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.database = database
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, route: str, csl: str) -> dict[str, Any]:
        response = self._client.post(
            f"{self.endpoint}{route}",
            json={"db": self.database, "csl": csl},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise KustoError(f"HTTP {response.status_code}: {response.text[:800]}")
        return response.json()

    def is_ready(self) -> bool:
        try:
            self.query("print ready = 1")
        except Exception:  # noqa: BLE001 - any failure at all means not ready
            return False
        return True

    def query(self, csl: str) -> list[dict[str, Any]]:
        """Run a query and return its primary result as a list of row dicts."""
        return _primary_table(self._post("/v1/rest/query", csl))

    def management(self, csl: str) -> list[dict[str, Any]]:
        return _primary_table(self._post("/v1/rest/mgmt", csl))

    def load_fixtures(self, fixtures: list[FixtureTable]) -> None:
        """Replace each fixture table with the corpus rows.

        Dropping first makes ingestion idempotent, so a re-run cannot silently
        double rows and skew every count in the corpus.
        """
        for table in fixtures:
            self.management(f".drop table {table.name} ifexists")
            self.management(f".set {table.name} <| {_datatable_expression(table)}")


class KustoError(RuntimeError):
    """A query or management command the emulator rejected."""


def _primary_table(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the primary result out of a v1 REST response.

    A v1 response carries the result table plus trailing metadata tables
    (QueryStatus and friends), so the primary result is the first one.
    """
    tables = payload.get("Tables")
    if not tables:
        raise KustoError(f"no tables in response: {str(payload)[:500]}")
    table = tables[0]
    names = [c["ColumnName"] for c in table["Columns"]]
    return [dict(zip(names, row)) for row in table["Rows"]]


