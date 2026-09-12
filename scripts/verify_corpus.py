"""Check every reference query against its committed expected rows.

This is the guarantee the corpus schema promises: run each reference_kql on the
fixtures and assert it reproduces expected_rows exactly. A failure here means
the ground truth is wrong, which would silently corrupt every score downstream.

Reference queries are held to EXACT and nothing weaker. A reference that grades
UNORDERED is returning the right rows in a different order, which means its
sort has ties and the committed row order is arbitrary -- fragile ground truth
that would fail intermittently, so it is reported as a failure here.
"""

from __future__ import annotations

import sys
from pathlib import Path

from kql_eval.corpus.loader import load_corpus
from kql_eval.evaluation.scoring import Grade, grade_rows
from kql_eval.execution.kusto import KustoEmulator

REPO_ROOT = Path(__file__).resolve().parent.parent

_DIAGNOSIS = {
    Grade.UNORDERED: "right rows, wrong order -- the sort has ties, so the "
    "committed order is arbitrary",
    Grade.EXTRA_COLUMNS: "returns more columns than committed",
    Grade.RENAMED_COLUMNS: "right values, different column names",
    Grade.MISMATCH: "different rows",
}


def main() -> int:
    corpus = load_corpus(REPO_ROOT / "data" / "corpus" / "corpus_v1.json")

    with KustoEmulator() as kusto:
        if not kusto.is_ready():
            print("emulator not reachable on http://localhost:8080", file=sys.stderr)
            return 2

        kusto.load_fixtures(corpus.fixtures)
        for table in corpus.fixtures:
            count = kusto.query(f"{table.name} | count")[0]["Count"]
            status = "ok" if count == len(table.rows) else f"MISMATCH want {len(table.rows)}"
            print(f"  ingested {table.name:<22} {count:>3} rows  {status}")
        print()

        failures = []
        for item in corpus.items:
            try:
                actual = kusto.query(item.reference_kql)
            except Exception as exc:  # noqa: BLE001 - report, never abort the run
                failures.append((item.id, "query error", str(exc)[:400], None))
                print(f"  ERROR  {item.id}")
                continue

            grade = grade_rows(item.expected_rows, actual)
            if grade is Grade.EXACT:
                print(f"  pass   {item.id:<48} {len(actual):>2} rows")
            else:
                failures.append((item.id, _DIAGNOSIS[grade], item.expected_rows, actual))
                print(f"  FAIL   {item.id:<48} {grade.value}")

    print()
    if not failures:
        print(f"all {len(corpus.items)} reference queries reproduce their expected rows")
        return 0

    print(f"{len(failures)} of {len(corpus.items)} items failed\n")
    for item_id, diagnosis, expected, actual in failures:
        print(f"--- {item_id}: {diagnosis}")
        if actual is None:
            print(f"    {expected}")
            continue
        print(f"    expected ({len(expected)} rows):")
        for row in expected[:6]:
            print(f"      {row}")
        print(f"    actual ({len(actual)} rows):")
        for row in actual[:6]:
            print(f"      {row}")
        print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
