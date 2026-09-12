"""Loading the committed corpus off disk."""

from __future__ import annotations

import json
from pathlib import Path

from kql_eval.corpus.schema import Corpus

DEFAULT_CORPUS = Path("data/corpus/corpus_v1.json")


def load_corpus(path: Path | str = DEFAULT_CORPUS) -> Corpus:
    """Read and validate a corpus file.

    Validation is not optional here: an invalid corpus means the ground truth
    everything is scored against is untrustworthy, so fail at load time.
    """
    return Corpus.model_validate(json.loads(Path(path).read_text()))
