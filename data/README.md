# data/

Most of this directory is gitignored working space. Two subdirectories are
committed on purpose, per the negation rules in `.gitignore`:

- `data/corpus/` — the evaluation corpus. This is ground truth, not source
  data: each item pairs a question with a reference query and the rows that
  query returns against the fixtures. It is committed so that a wrong reference
  query shows up as a test failure rather than a silently moving target.
- `data/fixtures/` — fixture tables, if any are kept outside a corpus file.

Everything else under `data/` is ignored. Put source data, scratch extracts and
anything regenerable here and it will stay out of the repo.

Verify the corpus against a live engine with:

```bash
./scripts/emulator.sh start
uv run python scripts/verify_corpus.py
```
