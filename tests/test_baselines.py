"""Baseline generator behaviour. No emulator or model server required."""

from __future__ import annotations

import pytest

from kql_eval.corpus.schema import FixtureTable
from kql_eval.generation.base import Generator, strip_code_fences
from kql_eval.generation.baselines import (
    BareTableGenerator,
    KeywordStubGenerator,
    OllamaGenerator,
    SchemaAwareOllamaGenerator,
)


def test_all_baselines_satisfy_the_shared_interface():
    for generator in (BareTableGenerator(), KeywordStubGenerator(), OllamaGenerator()):
        assert isinstance(generator, Generator)
        assert generator.name


def test_bare_table_emits_only_the_table():
    assert BareTableGenerator().generate("anything at all", ["SecurityEvent"]) == "SecurityEvent"


def test_bare_table_uses_the_first_declared_table():
    out = BareTableGenerator().generate("q", ["SigninLogs", "AzureActivity"])
    assert out == "SigninLogs"


@pytest.fixture
def stub():
    return KeywordStubGenerator()


def test_keyword_stub_picks_table_from_question_words(stub):
    out = stub.generate("Show failed sign-ins", ["SecurityEvent", "SigninLogs"])
    assert out.startswith("SigninLogs")


def test_keyword_stub_falls_back_to_first_table_when_nothing_matches(stub):
    out = stub.generate("zzzz qqqq", ["AzureActivity"])
    assert out == "AzureActivity"


def test_keyword_stub_adds_one_where_clause(stub):
    out = stub.generate("Show failed Windows logons", ["SecurityEvent"])
    assert "| where EventID == 4625" in out
    assert out.count("| where") == 1


def test_keyword_stub_never_aggregates(stub):
    questions = [
        "How many failed logons per IP address?",
        "Count sign-ins by user",
        "Which caller ran the most operations?",
    ]
    for q in questions:
        assert "summarize" not in stub.generate(q, ["SecurityEvent"])


def test_keyword_stub_extracts_a_literal_ip(stub):
    out = stub.generate("Did anything connect to 45.133.1.88?", ["DeviceNetworkEvents"])
    assert 'RemoteIP == "45.133.1.88"' in out


def test_keyword_stub_uses_the_right_ip_column_per_table(stub):
    out = stub.generate("sign-ins from 203.0.113.45", ["SigninLogs"])
    assert 'IPAddress == "203.0.113.45"' in out


def test_keyword_stub_only_chooses_among_declared_tables(stub):
    """A question mentioning sign-ins must not invent a table not in scope."""
    out = stub.generate("failed sign-in activity", ["AzureActivity"])
    assert out.startswith("AzureActivity")


@pytest.mark.parametrize(
    "raw",
    [
        "```kql\nSecurityEvent | count\n```",
        "```\nSecurityEvent | count\n```",
        "  ```KQL\nSecurityEvent | count\n```  ",
    ],
)
def test_fenced_output_is_unwrapped(raw):
    assert strip_code_fences(raw) == "SecurityEvent | count"


def test_unfenced_output_passes_through():
    assert strip_code_fences("SecurityEvent | count") == "SecurityEvent | count"


def test_multiline_query_survives_unwrapping():
    raw = "```kql\nSecurityEvent\n| where EventID == 4625\n| count\n```"
    assert strip_code_fences(raw) == "SecurityEvent\n| where EventID == 4625\n| count"


def test_ollama_generator_is_pinned_to_a_named_model():
    assert OllamaGenerator().model == "qwen2.5:14b-instruct"
    assert OllamaGenerator(model="other:8b").model == "other:8b"


# --- schema-aware variant ---------------------------------------------------

FIXTURES = [
    FixtureTable(
        name="SecurityEvent",
        columns={"TimeGenerated": "datetime", "EventID": "int", "IpAddress": "string"},
        rows=[],
    ),
    FixtureTable(
        name="SigninLogs",
        columns={"TimeGenerated": "datetime", "IPAddress": "string"},
        rows=[],
    ),
]


@pytest.fixture
def aware():
    return SchemaAwareOllamaGenerator(FIXTURES)


def test_schema_aware_has_a_distinct_name_from_blind(aware):
    """Names must differ or the two runs overwrite each other's artifacts."""
    assert aware.name != OllamaGenerator().name
    assert "schema-aware" in aware.name
    assert "schema-blind" in OllamaGenerator().name


def test_schema_aware_uses_the_same_underlying_model(aware):
    assert aware.model == OllamaGenerator().model


def test_rendered_schema_lists_columns_and_types(aware):
    rendered = aware.render_schema(["SecurityEvent"])
    assert "SecurityEvent" in rendered
    assert "EventID: int" in rendered
    assert "IpAddress: string" in rendered


def test_rendered_schema_covers_only_tables_in_scope(aware):
    """Widening the table choice would confound the comparison."""
    rendered = aware.render_schema(["SecurityEvent"])
    assert "SigninLogs" not in rendered
    assert "IPAddress" not in rendered


def test_schema_aware_prompt_contains_columns_and_blind_prompt_does_not(aware):
    question = "Which IPs failed to log on?"
    tables = ["SecurityEvent"]
    assert "EventID: int" in aware._build_prompt(question, tables)
    assert "EventID" not in OllamaGenerator()._build_prompt(question, tables)


def test_both_prompts_carry_the_question(aware):
    question = "Which IPs failed to log on?"
    for gen in (aware, OllamaGenerator()):
        assert question in gen._build_prompt(question, ["SecurityEvent"])


def test_unknown_table_degrades_rather_than_raising(aware):
    assert "schema unavailable" in aware.render_schema(["NotAFixture"])
