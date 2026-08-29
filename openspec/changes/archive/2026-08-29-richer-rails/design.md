## Context

See `proposal.md` for motivation. Service rails currently perform one cached TMDB movie discovery, while Plex already returns next-up episode rows that normalization discards when progress or the episode-level timestamp is absent. Both changes fit the current provider and typed-client boundaries.

## Goals / Non-Goals

**Goals:**

- Preserve current rail composition and degradation contracts while using the movie, TV, and Plex hub data already available.
- Keep ordering deterministic, bounded, and directly unit-testable.
- Keep next-up episode context visible when progress is absent.
- Avoid new endpoints, models exposed to the browser, dependencies, or durable data.

**Non-Goals:**

- Infer when a title arrived on a streaming service; TMDB release/first-air dates remain the only recency signal.
- Change cross-rail de-duplication or Plex account/server validation.

## Decisions

### Fetch and interleave two service media types

Each service provider will gather two `CatalogService.discover` calls with the same service, region-derived flatrate behavior, 365-day window, and vote floor. Movies use `primary_release_date.desc`; TV uses `first_air_date.desc`. A local wrapper catches `UpstreamError` per call so one failed leg still returns the other.

A pure helper will alternate movie and TV results, then append the remaining side, capped by a local `SERVICE_RAIL_SIZE = 20`. This is smaller and easier to verify than teaching the composer about service-specific result groups. Sequential fetching was rejected because the calls are independent and would add latency.

### Require service rails to be at least half full

The service provider will set `min_items` to half of `SERVICE_RAIL_SIZE` (10). The global minimum of four remains correct for other providers, but a four-card service rail beside 20-card rails looks failed. Requiring 10 gives the service rail a simple, capacity-relative floor without changing composer behavior.

### Admit only genuinely absent-progress next-up episodes

Movies continue to require progress from 1 through 99. Episodes may carry null progress only when the upstream `viewOffset` field is absent; an explicitly supplied invalid, zero, or complete value remains ineligible. Pydantic's field-set metadata distinguishes an absent alias from a value that validation normalized to null.

The typed PMS item gains `grandparentLastViewedAt` and `parentLastViewedAt`. All three optional ordering timestamps normalize malformed values to absent so one bad advisory field cannot discard a server's hub. Ordering uses `lastViewedAt`, then grandparent, then parent. When all are absent, an internal negative rank derived from the row's zero-based hub position sorts the row after timestamped items while preserving hub recency and deterministic server order. The rank is neither persisted nor returned. When duplicate show candidates have the same timestamp, an in-progress episode wins over a next-up episode before stable server order breaks any remaining tie.

The existing `MediaSummary` already carries nullable progress and episode context. `MediaCard` will render context independently while continuing to omit the progress bar for null progress, so no response-model change is needed.

## Security considerations

- No endpoint, authentication, session, database, or browser response contract changes.
- The existing typed Plex client still calls only validated PMS connections with the existing timeout, redirect policy, token header, account scoping, and 50-row bound. The optional ordering timestamp aliases retain only positive integers and otherwise normalize to absent; unknown upstream fields remain ignored.
- TMDB discovery still routes only through `clients/`, uses validated settings, bounded timeouts, typed normalization, existing caching, and no browser headers. The extra call targets no new host.
- Raw Plex payloads, viewing data, tokens, server URLs, and the internal fallback rank are not logged, cached as raw data, persisted, or returned.
- Live verification remains opt-in and emits only generic exercised/skipped results. No dependency is added, so lockfiles and supply-chain review are unchanged.

## Risks / Trade-offs

- [Two TMDB calls per service double cold-cache discover work] → Keep the four-service cap and existing 45-minute discover cache; execute movie and TV legs concurrently.
- [A catalog-heavy service may still look thin] → Omit fewer-than-10 results; widening the 365-day window remains a separate product decision.
- [Plex timestamp fields vary by server/version] → Prefer three known fields and retain hub position as the final deterministic fallback; verify the real payload contract with the redacted live suite.
- [Position ranks cannot compare exact recency across servers] → Sort all timestamped rows first, then interleave equal hub positions by stable server order; no stronger cross-server signal exists.

## Migration Plan

No migration is required. Deploy the code and spec together; rollback restores the prior movie-only service query and progress-required Continue Watching filter without data cleanup.
