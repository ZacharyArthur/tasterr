"""Pure scoring: similarity + quality prior + availability boost, then MMR.

`score = 1.0·cosine(profile, title) + 0.15·quality + 0.10·availability` — the
similarity term dominates by design (SPEC §8). Vectors are L2-normalized, so
cosine is a plain dot product. The greedy MMR re-rank trades a little score
for coverage so the top of a rail is not one franchise. All constants live
here and are pinned by ordering-property tests.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from tasterr.recommend.features import FeatureRecord
from tasterr.recommend.signals import STRONG_POSITIVE_KINDS, TitleKey

ALPHA_SIMILARITY = 1.0
BETA_QUALITY = 0.15
GAMMA_AVAILABILITY = 0.10
MMR_LAMBDA = 0.3
# Votes at which a rating earns half its face value — keeps a 9.2 with 40
# votes from outranking an 8.4 with 30k.
QUALITY_SHRINK_VOTES = 200.0


@dataclass
class Candidate:
    key: TitleKey
    record: FeatureRecord
    available: bool = False  # in-library per media-availability; Unknown → False (no boost)


def dot(a: dict[str, float], b: dict[str, float]) -> float:
    if len(b) < len(a):
        a, b = b, a
    return sum(value * b[dim] for dim, value in a.items() if dim in b)


def quality_prior(vote_average: float, vote_count: int) -> float:
    if vote_count <= 0:
        return 0.0
    shrink = vote_count / (vote_count + QUALITY_SHRINK_VOTES)
    return (vote_average / 10.0) * shrink


def score(profile: dict[str, float], candidate: Candidate) -> float:
    return (
        ALPHA_SIMILARITY * dot(profile, candidate.record.vector)
        + BETA_QUALITY * quality_prior(candidate.record.vote_average, candidate.record.vote_count)
        + GAMMA_AVAILABILITY * (1.0 if candidate.available else 0.0)
    )


def rank(profile: dict[str, float], candidates: list[Candidate], limit: int) -> list[Candidate]:
    """Greedy MMR: repeatedly pick the candidate maximizing
    `base score - λ·max_similarity(already picked)`.

    Precondition: callers bound `candidates` (the service's CANDIDATE_CAP);
    the greedy loop is O(n²·k) and does no truncation of its own."""
    base = {id(candidate): score(profile, candidate) for candidate in candidates}
    return _diverse_rank(candidates, base, limit)


def rank_exploration(
    profile: dict[str, float], candidates: list[Candidate], limit: int
) -> list[Candidate]:
    """Rank the lowest non-negative similarity quarter by quality and availability."""
    unique = {candidate.key: candidate for candidate in candidates}
    by_similarity = sorted(
        (
            (similarity, candidate)
            for candidate in unique.values()
            if (similarity := dot(profile, candidate.record.vector)) >= 0.0
        ),
        key=lambda pair: (pair[0], pair[1].key[0], pair[1].key[1]),
    )
    fringe = [candidate for _, candidate in by_similarity[: (len(by_similarity) + 3) // 4]]
    base = {
        id(candidate): BETA_QUALITY
        * quality_prior(candidate.record.vote_average, candidate.record.vote_count)
        + GAMMA_AVAILABILITY * (1.0 if candidate.available else 0.0)
        for candidate in fringe
    }
    return _diverse_rank(fringe, base, limit)


def _diverse_rank(
    candidates: list[Candidate], base: dict[int, float], limit: int
) -> list[Candidate]:
    remaining = sorted(candidates, key=lambda c: base[id(c)], reverse=True)
    picked: list[Candidate] = []
    while remaining and len(picked) < limit:

        def adjusted(candidate: Candidate) -> float:
            penalty = max(
                (dot(candidate.record.vector, chosen.record.vector) for chosen in picked),
                default=0.0,
            )
            return base[id(candidate)] - MMR_LAMBDA * penalty

        best = max(remaining, key=adjusted)
        picked.append(best)
        remaining.remove(best)
    return picked


def hidden_titles(signals: Iterable[tuple[TitleKey, str]]) -> set[TitleKey]:
    """Titles hard-excluded from every personalized rail."""
    return {key for key, kind in signals if kind == "not_interested"}


def engaged_titles(signals: Iterable[tuple[TitleKey, str]]) -> set[TitleKey]:
    """Titles the user already acted on strongly — excluded from
    recommended-for-you (they know about those; My List and Seerr show them)."""
    return {key for key, kind in signals if kind in STRONG_POSITIVE_KINDS}
