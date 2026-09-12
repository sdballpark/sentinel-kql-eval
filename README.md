# sentinel-kql-eval

Measuring natural-language to KQL generation for security questions, against a
real Kusto engine with committed ground truth.

## The finding

A 14B instruct model was run twice over the same 22 questions. Same model, same
temperature 0 and pinned seed, same tables in scope. One variable changed:
whether the prompt listed each table's columns and types.

| | schema-blind | schema-aware |
|---|---:|---:|
| execution rate | 9.1% | 68.2% |
| strict accuracy | 0.0% | 9.1% |
| semantic accuracy | 4.5% | 40.9% |

Execution rate is the share of generated queries the engine accepted. Strict
accuracy is an exact row-for-row match against committed expected rows.
Semantic accuracy credits results that retrieved the right data but differed
cosmetically, such as naming a column `count_` or returning rows in a different
order.

## Why this is one cause and not diffuse improvement

Classifying every execution failure by root cause shows the gain concentrated
in a single bucket.

| failure cause | schema-blind | schema-aware |
|---|---:|---:|
| `unknown_column` | 14 | 1 |
| `syntax` | 4 | 3 |
| `semantic_other` | 0 | 3 |
| `join_structure` | 1 | 0 |
| `generation_timeout` | 1 | 0 |

Syntax errors barely moved, from 4 to 3. The model could already write
well-formed KQL. What it could not do was name columns that exist in these
fixtures. Unknown-column failures fell from 14 to 1.

The three new `semantic_other` failures are a different error class that only
becomes reachable once names resolve: a misused `extract()`, arithmetic between
two strings, and a `summarize` with no aggregate function. The schema-aware run
got far enough to make semantic mistakes instead of naming mistakes.

## The model knows the product, not the tenant

Column names the schema-blind run invented, as reported by the engine:

```
TargetAccount        countryOrRegion      DestinationIp
OperationName        userPrincipalName    DeviceNetworkID
AccountName          ComputerName         risk_level_aggregated
```

Most of these are real Microsoft Sentinel columns. `OperationName` is a genuine
`AzureActivity` field. `countryOrRegion` is a genuine sign-in location field.
They are simply not the columns these fixtures carry, and in one case the
fixture uses the newer spelling: `OperationNameValue` rather than
`OperationName`.

The model has learned the product schema from training data. It has not seen
these fixtures. That points the fix at retrieval, which means putting the actual
table schemas in front of the model, rather than at a larger model. Nothing in
these results suggests the 14B model was too small to write the queries.

## The casing trap

One `unknown_column` failure survived into the schema-aware run. The model
wrote a join between `SecurityEvent` and `SigninLogs` keyed on `IpAddress`.
That column exists in `SecurityEvent`. In `SigninLogs` it is spelled
`IPAddress`.

This inconsistency is real in Sentinel and was put into the fixtures on
purpose. It is the kind of detail a schema listing does not fix by itself,
because both spellings appear in the prompt and the model has to notice they
differ.

## Full results

Two non-model baselines establish a floor.

| baseline | execution rate | strict | semantic |
|---|---:|---:|---:|
| `bare-table` | 100.0% | 0.0% | 0.0% |
| `keyword-stub` | 100.0% | 0.0% | 18.2% |
| `qwen2.5:14b-instruct (schema-blind)` | 9.1% | 0.0% | 4.5% |
| `qwen2.5:14b-instruct (schema-aware)` | 68.2% | 9.1% | 40.9% |

`bare-table` emits the table name and nothing else. `keyword-stub` matches
question words to a table and one `where` clause, with no aggregation. Both
were written with knowledge of the fixture columns, which the schema-blind model
was denied. The comparison between the stubs and the schema-blind run is
therefore not like for like, and the schema-blind number should not be read as a
statement about the model's KQL ability.

Grade distribution for the schema-aware run: 2 exact, 3 extra columns, 4
renamed columns, 6 mismatch, 7 error.

## Limitations

These numbers are a starting point, not a benchmark result to cite.

- The corpus is 22 items. Per-category cells hold three to five items each, so
  per-category percentages move in large steps and are directional only.
- `join_and_correlation` scored 0% strict and 0% semantic even schema-aware.
  Joins are the hardest category here and the schema fix did not touch them.
- The corpus was authored by an LLM and is being used to evaluate an LLM. Shared
  blind spots between author and subject are plausible and not controlled for.
- The fixtures are synthetic. They were written to contain realistic security
  telemetry and deliberate schema friction, but they are not production Sentinel
  data and their distribution is not representative.
- Execution uses the Kusto emulator, which runs the real query engine but is a
  point-in-time container build. It may drift from a live workspace.
- Only one model at one size was tested. There is no evidence here about how
  the schema-blind gap behaves across model families or scales.

## A bug that reported the opposite finding

The first error taxonomy printed `semantic_other=14` and `unknown_column=0`.
That is the reverse of the actual result.

The cause was truncation. Errors were being stored at 300 characters. Kusto
wraps its diagnostic in a nested `@message` field behind roughly 300 characters
of JSON boilerplate, so `Failed to resolve` begins at character 305. Every
resolution failure was being classified from a string with the evidence cut off,
and fell through to the generic semantic bucket.

It was caught by checking the classifications against the raw error text rather
than trusting the labels, after the taxonomy disagreed with a hand count done
earlier.

The fix extracts the engine's nested `@message` at the point the error is
raised, rather than raising the truncation limit. Errors now arrive at roughly
160 characters with the diagnostic intact, and classification no longer depends
on a byte count. Raising the limit would have worked until a longer error
appeared.

## A deliberate constraint in det-003

The question for `det-003` names the `-enc` flag specifically rather than asking
for encoded PowerShell in general.

PowerShell accepts `-EncodedCommand` and any unambiguous shorter prefix. A model
writing the broader and arguably better detection, something like
`has_any("-enc", "-encodedcommand", "-ec", "-e")`, would also match the
`-ExecutionPolicy Bypass` row on a `contains` path. Against these fixtures it
would return three rows where the reference returns two, and be graded wrong for
writing the more thorough rule.

Scoping the question to the literal flag keeps the item about string matching
instead of about guessing how wide to cast. The trade-off is recorded in the
item's `notes` field so the narrowness is not later mistaken for an oversight.

## Ground truth

Expected rows are committed to the corpus rather than computed at run time, so a
wrong reference query is a test failure instead of a silently moving target.

`scripts/verify_corpus.py` runs all 22 reference queries against the emulator
and requires an exact match. It holds references to `exact` and nothing weaker:
a reference that grades `unordered` is returning the right rows in a different
order, which means its sort has ties and the committed order is arbitrary. All
22 currently verify.

The corpus is 5 fixture tables and 82 rows: `SecurityEvent` (18),
`SigninLogs` (18), `DeviceProcessEvents` (16), `DeviceNetworkEvents` (16),
`AzureActivity` (14). Items are spread across `filtering_and_time` (5),
`aggregation` (5), `detection_logic` (5), `join_and_correlation` (4) and
`schema_navigation` (3).

## Running it

Requires Docker and, for the model baselines, Ollama with
`qwen2.5:14b-instruct` pulled.

```bash
uv sync

# Start the Kusto emulator. Binds to 127.0.0.1 because the emulator
# supports neither HTTPS nor Entra authentication.
./scripts/emulator.sh start

# Verify the corpus ground truth.
uv run python scripts/verify_corpus.py

# Run baselines. Naming a subset is useful because the model runs are slow.
uv run python scripts/run_baselines.py bare-table keyword-stub
uv run python scripts/run_baselines.py ollama-blind ollama-schema

uv run pytest
./scripts/emulator.sh stop
```

Results land in `runs/<timestamp>/`, one JSON per baseline plus a `summary.json`.
Every score carries the query that produced it, so a run can be audited without
regenerating it.

Python is always invoked through `uv run`. Bare `python` does not exist on
Ubuntu 24.04 without `python-is-python3`, and the system `python3` does not have
this project's dependencies.

## Layout

- `data/corpus/corpus_v1.json` committed corpus: fixtures, questions, reference
  queries, expected rows
- `src/kql_eval/corpus/` schema and loader
- `src/kql_eval/execution/` Kusto emulator client
- `src/kql_eval/evaluation/` grading tiers, error taxonomy, report aggregation
- `src/kql_eval/generation/` generator interface and baselines
- `scripts/` emulator control, corpus verification, baseline runner
- `runs/` committed run artifacts
