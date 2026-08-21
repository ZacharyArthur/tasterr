## Why

The M2/M5 browse feed can hide eight curated movie genres and presents release-date-based service rails as if TMDB reported when titles joined a service. The service query is also too narrow for several common providers, producing noticeably short rails before normal cross-rail de-duplication.

## What Changes

- Make every curated movie genre reachable by reserving only the genres actually shown on Home and returning the remaining curated genres through infinite scroll.
- Rename the generic release rail to `Recent Releases`, its admin toggle to `Recent releases`, and per-service rails to `Recent Releases on {service}` so their labels match the data TMDB provides.
- Expand the per-service recent-release window from 150 to 365 days while preserving the existing movie-only, flatrate, vote-floor, ordering, de-duplication, minimum-size, and four-service-cap behavior.
- Add regression coverage for complete curated-genre reachability, honest rail titles, and the service discovery query.

This advances the existing M2 media-browse and M5 settings-aware discovery capabilities.

## Non-goals

- Mixing TV shows into service rails.
- Fetching additional TMDB pages or guaranteeing a fixed number of cards per rail.
- Expanding the first-four service-rail cap.
- Removing flatrate filtering, the vote floor, selected-service filtering, cross-rail de-duplication, or the minimum rail size.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `media-browse`: Clarify release-based rail semantics and require all curated movie genres to remain reachable across Home and additional-rail pagination.

## Impact

- Backend rail registration and additional-rail composition under `backend/src/tasterr/rails/`, plus the recent-rail descriptor in runtime settings.
- Backend rail composer tests and their catalog fake.
- The `GET /api/v1/home` and `GET /api/v1/rails` response content changes only in rail titles, service candidates, and restored genre rails; the admin settings descriptor for `recent` is relabelled `Recent releases`; response schemas remain unchanged.
- No new dependencies, database changes, frontend changes, secrets, or new outbound-HTTP boundary are introduced.
