"""Pure profile math: decay, weights, rebuildability (no I/O)."""

from datetime import datetime, timedelta

import pytest

from tasterr.recommend.profile import HALF_LIFE_DAYS, SignalInput, compute_profile, decay_factor
from tasterr.recommend.signals import TitleKey

NOW = datetime(2026, 7, 9, 12, 0, 0)
DRAMA: TitleKey = ("movie", 1)
COMEDY: TitleKey = ("movie", 2)
VECTORS: dict[TitleKey, dict[str, float]] = {
    DRAMA: {"genre:drama": 1.0},
    COMEDY: {"genre:comedy": 1.0},
}


def test_strong_signal_shifts_the_profile_toward_the_title() -> None:
    signals = [
        SignalInput(DRAMA, 3.0, NOW),
        SignalInput(COMEDY, 0.3, NOW),
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert profile["genre:drama"] > profile["genre:comedy"] > 0.0


def test_one_half_life_old_signal_contributes_half() -> None:
    old = NOW - timedelta(days=HALF_LIFE_DAYS)
    signals = [
        SignalInput(DRAMA, 2.0, NOW),
        SignalInput(COMEDY, 2.0, old),
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert profile["genre:comedy"] / profile["genre:drama"] == pytest.approx(0.5)


def test_not_interested_contributes_negatively() -> None:
    signals = [
        SignalInput(DRAMA, 2.0, NOW),
        SignalInput(COMEDY, -3.0, NOW),
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert profile["genre:comedy"] < 0.0 < profile["genre:drama"]


def test_recompute_is_deterministic() -> None:
    signals = [
        SignalInput(DRAMA, 3.0, NOW - timedelta(days=10)),
        SignalInput(COMEDY, 2.0, NOW - timedelta(days=200)),
        SignalInput(COMEDY, -3.0, NOW - timedelta(days=1)),
    ]

    assert compute_profile(signals, VECTORS, NOW) == compute_profile(signals, VECTORS, NOW)


def test_signals_without_vectors_are_skipped() -> None:
    signals = [
        SignalInput(DRAMA, 3.0, NOW),
        SignalInput(("tv", 999), 3.0, NOW),  # no vector built for this title
    ]

    profile = compute_profile(signals, VECTORS, NOW)

    assert set(profile) == {"genre:drama"}


def test_no_usable_signals_yield_an_empty_profile() -> None:
    assert compute_profile([], VECTORS, NOW) == {}


def test_decay_clamps_future_timestamps() -> None:
    assert decay_factor(-5.0) == 1.0
