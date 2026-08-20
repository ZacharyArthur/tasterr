## Context

See `proposal.md` for motivation and `specs/media-browse/spec.md` for the changed
behavior contract. TMDB discovery exposes current watch-provider availability and
release-date filters, but not the date a title joined a provider. The current
composer also independently derives the four Home genre rails and the additional
genre catalogue, allowing those two selections to drift.

## Goals / Non-Goals

**Goals:**

- Derive the Home genre names and the additional-rail exclusion set through one
  deterministic rule.
- Describe the release-date data honestly and widen sparse service candidate
  pools without increasing outbound request count.
- Pin the corrected behavior with focused regression tests.

**Non-Goals:**

- Guarantee rail fullness or change cross-rail allocation.
- Add new provider data, endpoints, persistence, configuration, or dependencies.

## Decisions

### Derive the featured genre set from the genres actually used by Home

A shared pure helper will take the ordered curated genre names that exist in the
movie genre map and return at most `HOME_GENRE_COUNT`. Home will build its genre
providers from that result, and additional pagination will exclude exactly that
same result. This fixes the root cause without state shared across requests or
changes to pagination.

Keeping `set(GENRE_PICKS)` was rejected because it suppresses curated genres that
Home never consumed. Passing Home response state into the separate pagination
request was rejected because both endpoints can deterministically derive the
same answer from the cached genre map.

### Keep the existing service query shape and widen only its release window

The service provider will continue to request one movie page sorted by primary
release date, filtered to flatrate availability, the selected provider, the
existing vote floor, and the active region. Only the lower date bound changes
from 150 to 365 days. This grows small provider pools without additional TMDB
calls or a new composition policy.

Changing only the sort to popularity was rejected because it does not grow the
candidate pool and can trade overlap with the release rail for overlap with the
existing popularity rail. Removing flatrate or vote filters was rejected because
it changes selected-service semantics or result quality rather than fixing the
reported defect.

### Preserve stable rail ids while changing user-facing titles

The existing `recently-added` and `service-{provider_id}` ids remain unchanged;
only titles become `Recent Releases` and `Recent Releases on {service}`. No
frontend or generated API type change is required because titles are already
backend-provided strings. The `recent` admin rail-type descriptor becomes
`Recent releases` so the settings control uses the same honest terminology.

### Deferred and intentionally unchanged behavior

- **Deferred:** mixing TV results into service rails. It adds one discovery call
  per service and requires an explicit movie/TV merge and ordering policy. Revisit
  only if the 365-day movie pool remains inadequate in real household use.
- **Deferred:** fetching page two or guaranteeing a target rail length. It adds
  outbound work and post-de-duplication limiting complexity. Revisit only with
  evidence that widened pools still yield objectionably short rails.
- **Intentionally unchanged:** up to eight selected services continue to filter
  discovery and recommendations, while only the first four receive Home rails as
  the existing latency bound.
- **Intentionally unchanged:** movie-only service results, flatrate filtering,
  vote floors, selected-service filtering of discovery rails, composition order,
  cross-rail de-duplication, and the four-item minimum.

## Security considerations

No API endpoint, auth/session path, outbound HTTP client, frontend trust boundary,
database schema, logging path, or dependency changes. The fixed date window and
rail titles introduce no user-controlled input. Catalog discovery continues to
route through `CatalogService` and `clients/`, preserving the outbound-HTTP
boundary, typed normalization, timeouts, bounded retries, and secret handling.
Responses retain their existing explicit secret-free models. Therefore none of
the area-specific endpoint, auth, frontend, database, or dependency checklist
items in `docs/SECURITY.md` require a code change.

No new dependency is introduced; the existing standard library and project
modules cover the change.

## Risks / Trade-offs

- [A one-year window can include titles that do not feel brand-new] -> The
  release-based labels are explicit, newest-first ordering remains, and the wider
  bound is limited to service rails with demonstrated sparse pools.
- [Very small providers can still produce short or omitted rails] -> Preserve the
  existing minimum-size quality floor and defer extra requests until real usage
  justifies them.
- [Restored genres lengthen the additional-rail catalogue] -> Existing bounded
  cursor pagination already handles a larger provider list; regression coverage
  walks pagination to exhaustion.

## Migration Plan

Deploy the code and synchronized living spec together. There is no data or schema
migration. Rollback restores the prior labels, 150-day window, and genre
selection logic without touching persisted state.
