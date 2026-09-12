"""Three baselines, weakest first.

A benchmark number means nothing without a floor to compare it against. These
three establish one:

- BareTable answers every question with the table name alone. Anything a model
  scores above this is attributable to the model rather than to the corpus
  being easy.
- KeywordStub adds naive question-word matching and a single where clause. It
  is the "obvious script anyone would write in an afternoon" bar, and it is the
  one a language model actually has to beat to justify its cost.
- Ollama runs a local instruct model over the same thin context.

The keyword map below is deliberately small and general. It was written from
security-domain vocabulary, not by reading the corpus answers -- a stub tuned
per item would report a flattering floor and make the model look worse than it
is.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import httpx

from kql_eval.corpus.schema import FixtureTable
from kql_eval.generation.base import strip_code_fences

DEFAULT_OLLAMA_ENDPOINT = os.environ.get(
    "KQL_EVAL_OLLAMA_ENDPOINT", "http://127.0.0.1:11434"
)

_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Question vocabulary -> table. Checked in order, so the more specific phrases
# ("azure ad" meaning sign-ins) must precede the looser ones ("azure").
_TABLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("sign-in", "signin", "sign in", "azure ad", "entra"), "SigninLogs"),
    (("logon", "log on", "event id", "windows security", "security log"), "SecurityEvent"),
    (("command line", "powershell", "process"), "DeviceProcessEvents"),
    (("connect", "network", "remote ip", "beacon", "outbound", "talked to"), "DeviceNetworkEvents"),
    (("resource group", "control-plane", "control plane", "subscription", "caller", "azure"), "AzureActivity"),
)

# (table, vocabulary) -> a single where clause. No aggregation by design.
_FILTER_HINTS: dict[str, tuple[tuple[tuple[str, ...], str], ...]] = {
    "SecurityEvent": (
        (("failed", "failure", "brute", "spray"), "EventID == 4625"),
        (("special privilege", "privilege"), "EventID == 4672"),
        (("account was created", "new account", "created"), "EventID == 4720"),
        (("successful", "succeeded", "logged on"), "EventID == 4624"),
    ),
    "SigninLogs": (
        (("risky", "risk"), 'RiskLevelDuringSignIn == "high"'),
        (("outside", "country", "foreign", "abroad"), 'Location != "US"'),
        (("failed", "failure"), 'ResultType != "0"'),
        (("successful", "succeeded", "success"), 'ResultType == "0"'),
    ),
    "DeviceProcessEvents": (
        (("-enc", "encoded"), 'ProcessCommandLine contains "-enc"'),
        (("powershell",), 'FileName =~ "powershell.exe"'),
    ),
    "DeviceNetworkEvents": (
        (("failed", "blocked"), 'ActionType == "ConnectionFailed"'),
        (("beacon", "repeated", "successful"), 'ActionType == "ConnectionSuccess"'),
    ),
    "AzureActivity": (
        (("failed", "failure"), 'ActivityStatusValue == "Failed"'),
        (("succeeded", "successful"), 'ActivityStatusValue == "Succeeded"'),
    ),
}

_IP_COLUMN = {
    "SecurityEvent": "IpAddress",
    "SigninLogs": "IPAddress",
    "DeviceNetworkEvents": "RemoteIP",
    "AzureActivity": "CallerIpAddress",
}


class BareTableGenerator:
    """Emit the table name and nothing else.

    The floor. Every query it produces is valid KQL, so execution_rate is 100%
    by construction and any accuracy above zero would mean a question was
    answerable by dumping a whole table.
    """

    name = "bare-table"

    def generate(self, question: str, tables: Sequence[str]) -> str:
        return tables[0]


class KeywordStubGenerator:
    """Pick a table by question keywords and bolt on one where clause."""

    name = "keyword-stub"

    def generate(self, question: str, tables: Sequence[str]) -> str:
        lowered = question.lower()
        table = self._pick_table(lowered, tables)
        clauses = []

        found_ip = _IP.search(question)
        if found_ip and table in _IP_COLUMN:
            clauses.append(f'{_IP_COLUMN[table]} == "{found_ip.group(0)}"')
        else:
            for vocabulary, clause in _FILTER_HINTS.get(table, ()):
                if any(word in lowered for word in vocabulary):
                    clauses.append(clause)
                    break

        if not clauses:
            return table
        return f"{table}\n| where {clauses[0]}"

    @staticmethod
    def _pick_table(lowered: str, tables: Sequence[str]) -> str:
        for vocabulary, table in _TABLE_HINTS:
            if table in tables and any(word in lowered for word in vocabulary):
                return table
        return tables[0]


_BLIND_PROMPT = """You are writing a single KQL query for Microsoft Sentinel.

Tables in scope: {tables}

Question: {question}

Reply with only the KQL query. No explanation, no markdown fences."""

_SCHEMA_PROMPT = """You are writing a single KQL query for Microsoft Sentinel.

Schema of the tables in scope:

{schema}

Question: {question}

Use only the columns listed above. Reply with only the KQL query. No
explanation, no markdown fences."""


class OllamaGenerator:
    """A local instruct model given only the question and table names.

    Temperature and seed are pinned so a rerun of the benchmark reproduces its
    numbers; a sampled baseline would make every regression ambiguous.
    """

    def __init__(
        self,
        model: str = "qwen2.5:14b-instruct",
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        timeout: float = 300.0,
    ) -> None:
        self.model = model
        self.name = f"{model} (schema-blind)"
        self.endpoint = endpoint.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _build_prompt(self, question: str, tables: Sequence[str]) -> str:
        return _BLIND_PROMPT.format(tables=", ".join(tables), question=question)

    def generate(self, question: str, tables: Sequence[str]) -> str:
        response = self._client.post(
            f"{self.endpoint}/api/generate",
            json={
                "model": self.model,
                "prompt": self._build_prompt(question, tables),
                "stream": False,
                "options": {"temperature": 0, "seed": 0},
            },
        )
        response.raise_for_status()
        return strip_code_fences(response.json()["response"])


class SchemaAwareOllamaGenerator(OllamaGenerator):
    """The same model and settings, but shown each table's columns and types.

    Only the tables already in scope for the item are described, so the single
    variable against the schema-blind run is column knowledge -- not a wider
    choice of tables, which would confound the comparison.
    """

    def __init__(
        self,
        fixtures: Sequence[FixtureTable],
        model: str = "qwen2.5:14b-instruct",
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(model=model, endpoint=endpoint, timeout=timeout)
        self.name = f"{model} (schema-aware)"
        self._columns = {f.name: dict(f.columns) for f in fixtures}

    def render_schema(self, tables: Sequence[str]) -> str:
        blocks = []
        for table in tables:
            columns = self._columns.get(table)
            if not columns:
                blocks.append(f"{table}\n  (schema unavailable)")
                continue
            body = "\n".join(f"  {c}: {t}" for c, t in columns.items())
            blocks.append(f"{table}\n{body}")
        return "\n\n".join(blocks)

    def _build_prompt(self, question: str, tables: Sequence[str]) -> str:
        return _SCHEMA_PROMPT.format(
            schema=self.render_schema(tables), question=question
        )
