# CHANGEME

## Setup

```bash
uv sync
uv run python scripts/check_models.py
```

Model weights are not in this repo. See `configs/models.yaml` for what to pull;
they land in `$HF_HOME` (shared across projects).

## Layout

- `src/` application code
- `configs/models.yaml` model registry — repo, revision, license, purpose
- `scripts/check_models.py` reports cached vs missing models
- `evals/` benchmark results
- `data/` source data (gitignored)
