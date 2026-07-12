"""Pure feature-vector math: title facts → sparse, label-bearing vectors.

Dimension keys are namespaced, self-describing strings (`genre:science
fiction`, `kw:time travel`, `cast:tom hanks`, ...) so the explain endpoint's
reasons fall straight out of the arithmetic — no label table to keep in sync.
Vectors are L2-normalized so cosine similarity is a plain dot product. No I/O
here; persistence lives in store.py.
"""

import math

from pydantic import BaseModel

from tasterr.catalog.facts import TitleFacts

# Per-class dimension weights: genres define taste most strongly; keywords are
# the texture; people and the rest are light touches so a shared actor alone
# never outweighs a genre match. Tuned by living with it (design.md Risks).
WEIGHT_GENRE = 1.0
WEIGHT_KEYWORD = 0.6
WEIGHT_CAST = 0.4
WEIGHT_CREATOR = 0.5
WEIGHT_LANGUAGE = 0.3
WEIGHT_DECADE = 0.3
WEIGHT_RUNTIME = 0.2
MAX_KEYWORD_DIMS = 12
# Defensive cap: catalog facts already carry top-billed-only cast, but the
# invariant belongs to the vector builder, not its callers.
MAX_CAST_DIMS = 5

_RUNTIME_BUCKETS = ((90, "short"), (120, "standard"), (150, "long"))


class FeatureRecord(BaseModel):
    """A title's engine-facing features: sparse vector + quality-prior inputs.
    This is the persisted `title_features.features` JSON shape."""

    vector: dict[str, float]
    vote_average: float = 0.0
    vote_count: int = 0


def build_record(facts: TitleFacts) -> FeatureRecord:
    dims: dict[str, float] = {}
    for name in facts.genres:
        dims[f"genre:{_norm(name)}"] = WEIGHT_GENRE
    for name in facts.keywords[:MAX_KEYWORD_DIMS]:
        dims[f"kw:{_norm(name)}"] = WEIGHT_KEYWORD
    for name in facts.cast[:MAX_CAST_DIMS]:
        dims[f"cast:{_norm(name)}"] = WEIGHT_CAST
    for name in facts.creators:
        dims[f"director:{_norm(name)}"] = WEIGHT_CREATOR
    if facts.original_language:
        dims[f"lang:{_norm(facts.original_language)}"] = WEIGHT_LANGUAGE
    if facts.year is not None:
        dims[f"decade:{facts.year // 10 * 10}"] = WEIGHT_DECADE
    bucket = runtime_bucket(facts.runtime)
    if bucket is not None:
        dims[f"runtime:{bucket}"] = WEIGHT_RUNTIME
    return FeatureRecord(
        vector=l2_normalize(dims),
        vote_average=facts.vote_average,
        vote_count=facts.vote_count,
    )


def runtime_bucket(runtime: int | None) -> str | None:
    if runtime is None or runtime <= 0:
        return None
    for ceiling, label in _RUNTIME_BUCKETS:
        if runtime <= ceiling:
            return label
    return "epic"


def l2_normalize(vector: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm == 0.0:
        return {}
    return {key: value / norm for key, value in vector.items()}


def _norm(label: str) -> str:
    return label.strip().lower()
