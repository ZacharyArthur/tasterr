"""Pure explain math: profile ⊙ title vector overlap → readable reasons.

The label-bearing dimension keys make this arithmetic, not prose generation:
the top positively-contributing dims *are* the reasons. No profile or no
positive overlap → an honest not-personalized result, never fabricated.
"""

from dataclasses import dataclass

MAX_REASONS = 5

_RUNTIME_LABELS = {
    "short": "shorter titles",
    "standard": "feature-length titles",
    "long": "longer titles",
    "epic": "epics",
}


@dataclass
class Explanation:
    personalized: bool
    reasons: list[str]


def explain(profile: dict[str, float], vector: dict[str, float]) -> Explanation:
    contributions = sorted(
        (
            (profile[dim] * value, dim)
            for dim, value in vector.items()
            if profile.get(dim, 0.0) * value > 0.0
        ),
        reverse=True,
    )
    if not contributions:
        return Explanation(personalized=False, reasons=[])
    return Explanation(
        personalized=True,
        reasons=[_label(dim) for _, dim in contributions[:MAX_REASONS]],
    )


def _label(dim: str) -> str:
    prefix, _, value = dim.partition(":")
    if prefix == "genre" or prefix == "cast" or prefix == "director":
        return value.title()
    if prefix == "kw":
        return value
    if prefix == "lang":
        return f"{value.upper()}-language titles"
    if prefix == "decade":
        return f"titles from the {value}s"
    if prefix == "runtime":
        return _RUNTIME_LABELS.get(value, value)
    return value
