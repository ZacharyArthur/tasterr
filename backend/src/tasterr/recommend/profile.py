"""Pure profile math: signals + title vectors → a decayed, normalized profile.

The profile is the L2-normalized sum over signals of
`signal weight * decay(age) * title vector`, with an exponential half-life of
~90 days evaluated against a passed-in "now" (no clock reads here). It is a
pure function of the signals, so the materialized `profiles` row is only ever
a cache.
"""

import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import NamedTuple

from tasterr.recommend.features import l2_normalize
from tasterr.recommend.signals import TitleKey

HALF_LIFE_DAYS = 90.0
_SECONDS_PER_DAY = 86400.0
_LN2 = math.log(2.0)


class SignalInput(NamedTuple):
    """The slice of a signal row the math needs (kept ORM-free)."""

    key: TitleKey
    weight: float
    created_at: datetime


def decay_factor(age_days: float) -> float:
    """Exponential decay: 1.0 now, 0.5 at one half-life. Future timestamps
    (clock skew) clamp to no decay rather than amplifying."""
    return math.exp(-_LN2 * max(age_days, 0.0) / HALF_LIFE_DAYS)


def compute_profile(
    signals: Iterable[SignalInput],
    vectors: Mapping[TitleKey, dict[str, float]],
    now: datetime,
) -> dict[str, float]:
    """Signals whose title has no vector are skipped (their titles failed to
    build); they contribute again once the vector exists."""
    profile: dict[str, float] = {}
    for signal in signals:
        vector = vectors.get(signal.key)
        if not vector:
            continue
        age_days = (now - signal.created_at).total_seconds() / _SECONDS_PER_DAY
        factor = signal.weight * decay_factor(age_days)
        for dim, value in vector.items():
            profile[dim] = profile.get(dim, 0.0) + factor * value
    return l2_normalize(profile)


def blend_profiles(profiles: Iterable[dict[str, float]]) -> dict[str, float]:
    normalized = [l2_normalize(profile) for profile in profiles]
    if not normalized or any(not profile for profile in normalized):
        return {}
    mean: dict[str, float] = {}
    for profile in normalized:
        for dimension, value in profile.items():
            mean[dimension] = mean.get(dimension, 0.0) + value / len(normalized)
    return l2_normalize(mean)
