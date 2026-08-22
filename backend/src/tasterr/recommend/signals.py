"""Signal kinds and weights (SPEC §8) — shared vocabulary for the taste engine.

`request` and `seed_request_history` are server-recorded only; the client may
record (and, for the toggles, retract) the rest. Weights are written onto each
signal row at record time, so history keeps the weight it earned even if these
constants are retuned later.
"""

from typing import Literal, get_args

MediaType = Literal["movie", "tv"]
TitleKey = tuple[MediaType, int]
MAX_TMDB_ID = 2_147_483_647

SignalKind = Literal[
    "request", "watchlist", "detail_open", "not_interested", "seed_request_history"
]
# The only kinds POST /signals accepts — strong kinds are unrepresentable there.
ClientSignalKind = Literal["detail_open", "watchlist", "not_interested"]

SIGNAL_WEIGHTS: dict[SignalKind, float] = {
    "request": 3.0,
    "watchlist": 2.0,
    "seed_request_history": 2.0,
    "detail_open": 0.3,
    "not_interested": -3.0,
}

# Kinds with on/off semantics: adding is idempotent, retracting deletes.
TOGGLE_KINDS: frozenset[SignalKind] = frozenset(("watchlist", "not_interested"))
# Kinds with at most one row per user+title. Seed rows are deduped so an
# overlapping login-seed and reset (or a double reset) cannot double a
# title's influence — idempotence instead of cross-request locking.
UNIQUE_PER_TITLE_KINDS: frozenset[SignalKind] = TOGGLE_KINDS | frozenset(("seed_request_history",))
# Positive kinds strong enough to anchor "More like X" and pool candidates.
STRONG_POSITIVE_KINDS: frozenset[SignalKind] = frozenset(
    ("request", "watchlist", "seed_request_history")
)

ALL_KINDS: frozenset[SignalKind] = frozenset(get_args(SignalKind))
