"""Canonical Jellyfin provider ids shared by history and resume mapping."""

from tasterr.catalog.models import MAX_TMDB_ID
from tasterr.clients.jellyfin import JellyfinItem


def tmdb_id(item: JellyfinItem) -> int | None:
    raw = item.provider_ids.get("Tmdb", "")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 10:
        return None
    value = int(raw)
    return value if 0 < value <= MAX_TMDB_ID else None
