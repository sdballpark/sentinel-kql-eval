"""Run the baseline generators through the scorer and write results to runs/.

Usage:
    ./scripts/emulator.sh start
    uv run python scripts/run_baselines.py [name ...]

With no arguments every baseline runs. The local model is much slower than the
stubs, so naming a subset is useful while iterating.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from kql_eval.corpus.loader import load_corpus
from kql_eval.corpus.schema import Corpus
from kql_eval.evaluation.report import EvalReport
from kql_eval.evaluation.scoring import score_item
from kql_eval.execution.kusto import KustoEmulator
from kql_eval.generation.base import Generator
from kql_eval.generation.baselines import (
    BareTableGenerator,
    KeywordStubGenerator,
    OllamaGenerator,
    SchemaAwareOllamaGenerator,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def run_baseline(
    generator: Generator, corpus: Corpus, kusto: KustoEmulator
) -> EvalReport:
    """Generate, execute and score every item for one generator.

    Generation failures and execution failures are both recorded as ERROR
    rather than raised, so one unlucky item cannot void a whole run.
    """
    scores = []
    for n, item in enumerate(corpus.items, start=1):
        try:
            kql = generator.generate(item.question, item.tables)
        except Exception as exc:  # noqa: BLE001 - record, never abort the run
            scores.append(
                score_item(item, None, error=f"generation failed: {str(exc)[:400]}")
            )
            print(f"    [{n:>2}/{len(corpus.items)}] {item.id}: generation failed", flush=True)
            continue

        try:
            rows = kusto.query(kql)
        except Exception as exc:  # noqa: BLE001 - invalid KQL is a result, not a crash
            scores.append(
                score_item(item, None, error=str(exc)[:600], generated_kql=kql)
            )
            print(f"    [{n:>2}/{len(corpus.items)}] {item.id}: error", flush=True)
            continue

        score = score_item(item, rows, generated_kql=kql)
        scores.append(score)
        print(f"    [{n:>2}/{len(corpus.items)}] {item.id}: {score.grade.value}", flush=True)

    return EvalReport(
        model=generator.name, corpus_version=corpus.version, scores=scores
    )


def main(argv: list[str]) -> int:
    corpus = load_corpus(REPO_ROOT / "data" / "corpus" / "corpus_v1.json")

    available: dict[str, Generator] = {
        "bare-table": BareTableGenerator(),
        "keyword-stub": KeywordStubGenerator(),
        "ollama-blind": OllamaGenerator(),
        "ollama-schema": SchemaAwareOllamaGenerator(corpus.fixtures),
    }
    wanted = argv or list(available)
    unknown = set(wanted) - set(available)
    if unknown:
        print(f"unknown baseline(s): {sorted(unknown)}", file=sys.stderr)
        print(f"available: {list(available)}", file=sys.stderr)
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNS / f"baselines-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    with KustoEmulator() as kusto:
        if not kusto.is_ready():
            print(
                "emulator not reachable -- run ./scripts/emulator.sh start",
                file=sys.stderr,
            )
            return 2
        kusto.load_fixtures(corpus.fixtures)

        reports = []
        for key in wanted:
            generator = available[key]
            print(f"\n== {generator.name}", flush=True)
            report = run_baseline(generator, corpus, kusto)
            reports.append(report)
            path = out_dir / f"{slugify(generator.name)}.json"
            path.write_text(report.model_dump_json(indent=2))
            print(f"  -> {path.relative_to(REPO_ROOT)}", flush=True)

    print("\n" + "=" * 66)
    for report in reports:
        print()
        print(report.render())

    print("\n" + "=" * 66)
    print(f"\n  {"baseline":<38} {'exec':>7} {'strict':>8} {'semantic':>9}")
    for report in reports:
        print(
            f"  {report.model:<38} {report.execution_rate:>7.1%} "
            f"{report.strict_accuracy:>8.1%} {report.semantic_accuracy:>9.1%}"
        )

    summary = {
        "corpus_version": corpus.version,
        "items": len(corpus.items),
        "generated_at": stamp,
        "baselines": [
            {
                "model": r.model,
                "execution_rate": round(r.execution_rate, 4),
                "strict_accuracy": round(r.strict_accuracy, 4),
                "semantic_accuracy": round(r.semantic_accuracy, 4),
                "grades": r.grade_counts(),
                "error_taxonomy": r.error_taxonomy(),
                "unresolved_names": r.top_unresolved_names(),
            }
            for r in reports
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {(out_dir / 'summary.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
