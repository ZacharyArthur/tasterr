"""Pure explain math: overlap → readable reasons (no I/O)."""

from tasterr.recommend.explain import MAX_REASONS, explain

PROFILE = {
    "genre:science fiction": 0.8,
    "kw:time travel": 0.5,
    "decade:2010": 0.3,
    "genre:romance": -0.4,
    "cast:tom hanks": 0.1,
    "lang:en": 0.05,
    "runtime:epic": 0.02,
}


def test_top_overlaps_become_reasons_in_contribution_order() -> None:
    vector = {
        "genre:science fiction": 0.7,
        "kw:time travel": 0.6,
        "decade:2010": 0.3,
    }

    result = explain(PROFILE, vector)

    assert result.personalized is True
    assert result.reasons == ["Science Fiction", "time travel", "titles from the 2010s"]


def test_negative_overlap_is_never_a_reason() -> None:
    vector = {"genre:romance": 0.9, "genre:science fiction": 0.2}

    result = explain(PROFILE, vector)

    assert result.reasons == ["Science Fiction"]


def test_reasons_are_capped() -> None:
    vector = {dim: 0.4 for dim in PROFILE if not dim.startswith("genre:romance")}

    result = explain(PROFILE, vector)

    assert len(result.reasons) == MAX_REASONS


def test_empty_profile_is_not_personalized() -> None:
    result = explain({}, {"genre:drama": 1.0})

    assert result.personalized is False
    assert result.reasons == []


def test_no_overlap_is_not_personalized() -> None:
    result = explain(PROFILE, {"genre:western": 1.0})

    assert result.personalized is False
    assert result.reasons == []


def test_label_variants_render_readably() -> None:
    profile = {"lang:en": 0.5, "runtime:epic": 0.4, "director:denis villeneuve": 0.3}
    vector = dict.fromkeys(profile, 0.5)

    result = explain(profile, vector)

    assert set(result.reasons) == {"EN-language titles", "epics", "Denis Villeneuve"}
