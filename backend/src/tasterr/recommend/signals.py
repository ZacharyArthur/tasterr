"""Signal kinds and weights (SPEC §8) — shared vocabulary for the taste engine.

`request`, `seed_request_history`, and both watch kinds are server-recorded only;
the client may record (and, for the toggles, retract) the rest. Weights are written onto each
signal row at record time, so history keeps the weight it earned even if these
constants are retuned later.
"""

from collections.abc import Iterable
from typing import Literal, get_args

from tasterr.catalog.models import MAX_TMDB_ID as MAX_TMDB_ID

MediaType = Literal["movie", "tv"]
TitleKey = tuple[MediaType, int]

SignalKind = Literal[
    "request",
    "watchlist",
    "detail_open",
    "not_interested",
    "seed_request_history",
    "watched_plex",
    "watched_jellyfin",
]
# The only kinds POST /signals accepts — strong kinds are unrepresentable there.
ClientSignalKind = Literal["detail_open", "watchlist", "not_interested"]

SIGNAL_WEIGHTS: dict[SignalKind, float] = {
    "request": 3.0,
    "watchlist": 2.0,
    "seed_request_history": 2.0,
    "watched_plex": 2.5,
    "watched_jellyfin": 2.5,
    "detail_open": 0.3,
    "not_interested": -3.0,
}

# Kinds with on/off semantics: adding is idempotent, retracting deletes.
TOGGLE_KINDS: frozenset[SignalKind] = frozenset(("watchlist", "not_interested"))
# Kinds with at most one row per user+title. Imported rows are deduped so
# overlapping history imports cannot double a
# title's influence — idempotence instead of cross-request locking.
UNIQUE_PER_TITLE_KINDS: frozenset[SignalKind] = TOGGLE_KINDS | frozenset(
    ("seed_request_history", "watched_plex", "watched_jellyfin")
)
# Positive kinds strong enough to anchor "More like X" and pool candidates.
STRONG_POSITIVE_KINDS: frozenset[SignalKind] = frozenset(
    ("request", "watchlist", "seed_request_history", "watched_plex", "watched_jellyfin")
)

ALL_KINDS: frozenset[SignalKind] = frozenset(get_args(SignalKind))

TasteSource = Literal["seerr", "plex", "jellyfin", "browsing"]
SOURCE_KINDS: dict[TasteSource, frozenset[SignalKind]] = {
    "seerr": frozenset(("seed_request_history",)),
    "plex": frozenset(("watched_plex",)),
    "jellyfin": frozenset(("watched_jellyfin",)),
    "browsing": frozenset(("detail_open",)),
}


def excluded_kinds(sources: Iterable[TasteSource]) -> frozenset[SignalKind]:
    return frozenset(kind for source in sources for kind in SOURCE_KINDS[source])
