"""Pure profile math: decay, weights, rebuildability (no I/O)."""

from datetime import datetime, timedelta

import pytest

from tasterr.recommend.profile import (
    HALF_LIFE_DAYS,
    SignalInput,
    blend_profiles,
    compute_profile,
    decay_factor,
)
from tasterr.recommend.signals import SIGNAL_WEIGHTS, TitleKey

NOW = datetime(2026, 7, 9, 12, 0, 0)
DRAMA: TitleKey = ("movie", 1)
COMEDY: TitleKey = ("movie", 2)
VECTORS: dict[TitleKey, dict[str, float]] = {
    DRAMA: {"genre:drama": 1.0},
    COMEDY: {"genre:comedy": 1.0},
}


def test_strong_signal_shifts_the_profile_toward_the_title() -> None:
    signals = [
        SignalInput(DRAMA, 3.0, NOW, "request"),
        SignalInput(COMEDY, 0.3, NOW, "detail_open"),
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert profile["genre:drama"] > profile["genre:comedy"] > 0.0


def test_plex_watch_is_a_strong_profile_signal() -> None:
    profile = compute_profile(
        [
            SignalInput(DRAMA, SIGNAL_WEIGHTS["watched_plex"], NOW, "watched_plex"),
            SignalInput(COMEDY, SIGNAL_WEIGHTS["detail_open"], NOW, "detail_open"),
        ],
        VECTORS,
        NOW,
    )

    assert profile["genre:drama"] > profile["genre:comedy"] > 0


def test_one_half_life_old_signal_contributes_half() -> None:
    old = NOW - timedelta(days=HALF_LIFE_DAYS)
    signals = [
        SignalInput(DRAMA, 2.0, NOW, "watchlist"),
        SignalInput(COMEDY, 2.0, old, "watchlist"),
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert profile["genre:comedy"] / profile["genre:drama"] == pytest.approx(0.5)


def test_not_interested_contributes_negatively() -> None:
    signals = [
        SignalInput(DRAMA, 2.0, NOW, "watchlist"),
        SignalInput(COMEDY, -3.0, NOW, "not_interested"),
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert profile["genre:comedy"] < 0.0 < profile["genre:drama"]


def test_recompute_is_deterministic() -> None:
    signals = [
        SignalInput(DRAMA, 3.0, NOW - timedelta(days=10), "request"),
        SignalInput(COMEDY, 2.0, NOW - timedelta(days=200), "watchlist"),
        SignalInput(COMEDY, -3.0, NOW - timedelta(days=1), "not_interested"),
    ]

    assert compute_profile(signals, VECTORS, NOW) == compute_profile(signals, VECTORS, NOW)


def test_signals_without_vectors_are_skipped() -> None:
    signals = [
        SignalInput(DRAMA, 3.0, NOW, "request"),
        SignalInput(("tv", 999), 3.0, NOW, "request"),  # no vector built for this title
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert set(profile) == {"genre:drama"}


def test_no_usable_signals_yield_an_empty_profile() -> None:
    assert compute_profile([], VECTORS, NOW) == {}


def test_decay_clamps_future_timestamps() -> None:
    assert decay_factor(-5.0) == 1.0


def test_blend_is_the_normalized_mean_of_normalized_profiles() -> None:
    result = blend_profiles([{"genre:drama": 2.0}, {"genre:comedy": 5.0}])

    assert result["genre:drama"] == pytest.approx(2**-0.5)
    assert result["genre:comedy"] == pytest.approx(2**-0.5)


def test_blend_rejects_an_empty_selected_profile() -> None:
    assert blend_profiles([{"genre:drama": 1.0}, {}]) == {}


def test_watches_collapse_to_newest_without_collapsing_deliberate_signals() -> None:
    from tasterr.recommend.signals import SignalKind

    kinds: list[SignalKind] = ["watched_plex", "watched_jellyfin", "watched_trakt"]
    watches = [
        SignalInput(DRAMA, 2.5, NOW - timedelta(days=90 - i * 45), kind)
        for i, kind in enumerate(kinds)
    ]
    other = SignalInput(COMEDY, 2, NOW, "watchlist")
    expected = compute_profile([watches[-1], other], VECTORS, NOW)
    assert compute_profile([watches[0], watches[-1], other], VECTORS, NOW) == expected
    assert compute_profile([*watches, other], VECTORS, NOW) == expected
    assert compute_profile([watches[0], other], VECTORS, NOW) != expected
    deliberate = SignalInput(DRAMA, 3, NOW, "request")
    assert compute_profile([*watches, deliberate, other], VECTORS, NOW) == compute_profile(
        [watches[-1], deliberate, other], VECTORS, NOW
    )
    assert compute_profile([watches[-1], deliberate, other], VECTORS, NOW) != expected
