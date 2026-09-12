#!/usr/bin/env python3
"""Report cache status for every model in configs/models.yaml."""
import sys
from pathlib import Path

import yaml
from huggingface_hub import HfApi, scan_cache_dir
from huggingface_hub.errors import CacheNotFound, HFValidationError, RepositoryNotFoundError

CFG = Path(__file__).resolve().parents[1] / "configs" / "models.yaml"


def main() -> int:
    cfg = yaml.safe_load(CFG.read_text())
    api = HfApi()
    try:
        cached = {r.repo_id for r in scan_cache_dir().repos}
    except CacheNotFound:
        cached = set()
    rc = 0
    for role, m in cfg.get("models", {}).items():
        repo, rev = m["repo_id"], m.get("revision", "main")
        mark = "OK  " if repo in cached else "MISS"
        if repo not in cached:
            rc = 1
        sha = ""
        try:
            sha = api.repo_info(repo, revision=rev).sha[:12]
        except (RepositoryNotFoundError, HFValidationError, OSError) as e:
            sha = f"<{type(e).__name__}>"
        print(f"{mark} {role:24} {repo:44} {rev:8} -> {sha}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
