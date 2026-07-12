"""Pure scoring math: ordering properties, boosts, exclusions, MMR (no I/O)."""

from tasterr.recommend.features import FeatureRecord, l2_normalize
from tasterr.recommend.scorer import (
    Candidate,
    dot,
    engaged_titles,
    hidden_titles,
    quality_prior,
    rank,
    score,
)
from tasterr.recommend.signals import SignalKind, TitleKey

PROFILE = l2_normalize({"genre:drama": 1.0, "kw:heist": 0.6})


def _candidate(
    key: TitleKey,
    vector: dict[str, float],
    *,
    vote_average: float = 7.0,
    vote_count: int = 1000,
    available: bool = False,
) -> Candidate:
    record = FeatureRecord(
        vector=l2_normalize(vector), vote_average=vote_average, vote_count=vote_count
    )
    return Candidate(key=key, record=record, available=available)


def test_similar_title_outranks_dissimilar_popular_title() -> None:
    similar = _candidate(("movie", 1), {"genre:drama": 1.0, "kw:heist": 0.6}, vote_average=6.5)
    popular = _candidate(("movie", 2), {"genre:comedy": 1.0}, vote_average=9.0, vote_count=50000)

    assert score(PROFILE, similar) > score(PROFILE, popular)


def test_in_library_wins_an_otherwise_even_tie() -> None:
    on_server = _candidate(("movie", 1), {"genre:drama": 1.0}, available=True)
    elsewhere = _candidate(("movie", 2), {"genre:drama": 1.0}, available=False)

    assert score(PROFILE, on_server) > score(PROFILE, elsewhere)


def test_unknown_availability_scores_without_boost() -> None:
    candidate = _candidate(("movie", 1), {"genre:drama": 1.0}, available=False)

    assert score(PROFILE, candidate) > 0.0  # still ranked — no boost, no penalty


def test_quality_prior_shrinks_thin_vote_counts() -> None:
    assert quality_prior(9.2, 40) < quality_prior(8.4, 30000)
    assert quality_prior(8.0, 0) == 0.0


def test_mmr_demotes_a_near_duplicate() -> None:
    # A profile spanning two tastes; the clone duplicates the lead exactly,
    # the fresh pick matches the profile equally well via different dims.
    profile = l2_normalize({"genre:drama": 1.0, "kw:heist": 0.6, "kw:courtroom": 0.6})
    lead = _candidate(("movie", 1), {"genre:drama": 1.0, "kw:heist": 0.6})
    clone = _candidate(("movie", 2), {"genre:drama": 1.0, "kw:heist": 0.6})
    fresh = _candidate(("movie", 3), {"genre:drama": 1.0, "kw:courtroom": 0.6})

    picked = rank(profile, [lead, clone, fresh], limit=2)

    keys = [c.key for c in picked]
    assert keys[0] == ("movie", 1)
    assert keys[1] == ("movie", 3)  # the clone loses its slot to coverage


def test_rank_respects_the_limit() -> None:
    candidates = [_candidate(("movie", i), {"genre:drama": 1.0}) for i in range(10)]

    assert len(rank(PROFILE, candidates, limit=4)) == 4


def test_hidden_and_engaged_exclusion_sets() -> None:
    signals: list[tuple[TitleKey, SignalKind]] = [
        (("movie", 1), "not_interested"),
        (("movie", 2), "request"),
        (("movie", 3), "watchlist"),
        (("movie", 4), "seed_request_history"),
        (("movie", 5), "detail_open"),
    ]

    assert hidden_titles(signals) == {("movie", 1)}
    assert engaged_titles(signals) == {("movie", 2), ("movie", 3), ("movie", 4)}


def test_dot_ignores_disjoint_dimensions() -> None:
    assert dot({"a": 1.0}, {"b": 1.0}) == 0.0
    assert dot({"a": 0.5, "b": 0.5}, {"a": 0.5}) == 0.25
