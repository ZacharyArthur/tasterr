## Why

Selected-service rails can look broken when a recent movie-only query yields only a few titles, and Continue Watching omits Plex next-up episodes that the server already returns. Both gaps discard useful rail content already available from existing upstream contracts.

## What Changes

- Build each selected-service rail from recent flatrate movies and TV series, alternating media types and filling from either side up to 20 items.
- Degrade a failed movie or TV service query independently and omit service rails that remain visibly under-filled.
- Retain unwatched next-up episodes from Plex Continue Watching, order them by the best available episode/show timestamp, and preserve Plex hub order when no timestamp exists.
- Show next-up episode context on cards even when no progress bar applies.
- Keep progress-less movies excluded and keep existing progress validation for started items.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `media-browse`: Selected-service rails change from recent movies only to balanced recent movie/TV results with a service-specific fullness floor.
- `plex-personalization`: Continue Watching eligibility and ordering expand to include next-up episodes without progress.

## Impact

- Advances the existing M2 Browse service-rail capability and the v2 Plex Continue Watching capability.
- Changes rail composition in `backend/src/tasterr/rails/registry.py`, Plex normalization and typed PMS item fields, and context rendering in `frontend/src/components/MediaCard.tsx`.
- Adds one TMDB discover call per configured service rail; existing discover caching and the four-service cap remain unchanged.
- No API model, database, migration, or dependency changes.

## Non-goals

- Widening the 365-day service-release window or treating TMDB release dates as service-arrival dates.
- Adding Plex endpoints or persisting raw Plex data.
- Changing general rail de-duplication, global rail ordering, or the four-service limit.
