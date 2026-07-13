"""Pure feature-vector math (no I/O)."""

import math

import pytest

from tasterr.catalog.facts import TitleFacts
from tasterr.recommend.features import (
    MAX_KEYWORD_DIMS,
    WEIGHT_GENRE,
    WEIGHT_KEYWORD,
    build_record,
    l2_normalize,
    runtime_bucket,
)


def _facts(**overrides: object) -> TitleFacts:
    base: dict[str, object] = {
        "tmdb_id": 42,
        "media_type": "movie",
        "title": "Deep",
        "genres": ["Science Fiction"],
        "keywords": ["Time Travel"],
        "cast": ["Tom Hanks"],
        "creators": ["The Director"],
        "original_language": "EN",
        "year": 2014,
        "runtime": 100,
        "vote_average": 8.4,
        "vote_count": 33000,
        "watch_region": "US",
        "flatrate_provider_ids": [8, 337],
    }
    return TitleFacts.model_validate({**base, **overrides})


def test_vector_carries_every_dimension_class_with_normalized_labels() -> None:
    record = build_record(_facts())

    assert set(record.vector) == {
        "genre:science fiction",
        "kw:time travel",
        "cast:tom hanks",
        "director:the director",
        "lang:en",
        "decade:2010",
        "runtime:standard",
    }
    assert record.vote_average == 8.4
    assert record.vote_count == 33000
    assert record.watch_region == "US"
    assert record.flatrate_provider_ids == [8, 337]


def test_class_weight_ratios_survive_normalization() -> None:
    vector = build_record(_facts()).vector

    ratio = vector["genre:science fiction"] / vector["kw:time travel"]
    assert ratio == pytest.approx(WEIGHT_GENRE / WEIGHT_KEYWORD)


def test_vector_is_l2_normalized() -> None:
    vector = build_record(_facts()).vector

    assert math.sqrt(sum(v * v for v in vector.values())) == pytest.approx(1.0)


def test_keywords_are_capped() -> None:
    many = [f"keyword {i}" for i in range(MAX_KEYWORD_DIMS + 5)]
    vector = build_record(_facts(keywords=many)).vector

    assert sum(1 for key in vector if key.startswith("kw:")) == MAX_KEYWORD_DIMS


def test_empty_facts_build_an_empty_vector() -> None:
    facts = _facts(
        genres=[],
        keywords=[],
        cast=[],
        creators=[],
        original_language="",
        year=None,
        runtime=None,
    )
    record = build_record(facts)

    assert record.vector == {}


@pytest.mark.parametrize(
    ("runtime", "bucket"),
    [(None, None), (0, None), (85, "short"), (100, "standard"), (140, "long"), (200, "epic")],
)
def test_runtime_buckets(runtime: int | None, bucket: str | None) -> None:
    assert runtime_bucket(runtime) == bucket


def test_l2_normalize_of_empty_vector_is_empty() -> None:
    assert l2_normalize({}) == {}
