# media-catalog Specification

## Purpose
TBD - created by archiving change m2-browse. Update Purpose after archive.
## Requirements
### Requirement: TMDB access is isolated behind the client boundary

The system SHALL perform all TMDB access through a single client module in
`tasterr.clients`. Every request SHALL carry an explicit timeout and a bounded
retry with backoff that honors `Retry-After` on `429`/`5xx`. The global
`TMDB_API_KEY` SHALL be attached to requests server-side only and never returned
to a client. Browser headers SHALL NOT be forwarded upstream, and upstream
responses SHALL be parsed into typed models with unknown fields dropped.

#### Scenario: Successful fetch returns typed data
- **WHEN** the client requests a configured TMDB endpoint that responds `200`
- **THEN** the response is parsed into a typed model and unknown fields are ignored

#### Scenario: Transient upstream failure is retried then surfaced generically
- **WHEN** TMDB returns `429` or `5xx` repeatedly beyond the bounded retry budget
- **THEN** the client raises a typed upstream-unavailable error carrying no
  upstream body or URL

### Requirement: Catalog normalization produces typed, secret-free domain models

Normalization SHALL convert TMDB JSON into typed domain models — media summary,
media detail, hero slide, rail, person, video, season summary, and watch-provider
info — resolving movie/TV titles and release years and passing image paths
through unchanged. Person results returned by multi-search SHALL be dropped.
Domain models SHALL contain no secret material and SHALL NOT import the
application settings module.

#### Scenario: Media result normalized to a summary
- **WHEN** a TMDB movie or TV result is normalized
- **THEN** it yields a summary with a resolved title, parsed year, and pass-through
  poster/backdrop paths, and its media type is set

#### Scenario: Person result is dropped
- **WHEN** a multi-search result of type `person` is normalized
- **THEN** it is omitted from the resulting summaries

#### Scenario: Detail normalized with derived fields
- **WHEN** a TMDB detail payload is normalized
- **THEN** it yields a detail model with a selected trailer and logo, ranked cast
  and key crew, certification for the active region, season summaries for TV, and
  region watch-provider info

### Requirement: In-process cache serves fresh, stale-on-error, and single-flight

The catalog SHALL cache TMDB reads in-process with per-endpoint-class TTLs over a
bounded store. Within a key's TTL it SHALL serve the cached value without calling
TMDB. When a refresh fails and a previously cached value exists within its stale
window, it SHALL serve that stale value instead of failing. Concurrent misses for
the same key SHALL result in a single upstream fetch.

#### Scenario: Fresh value avoids an upstream call
- **WHEN** a key is requested within its TTL after being cached
- **THEN** the cached value is returned and no TMDB request is made

#### Scenario: Stale value served on upstream error
- **WHEN** a key's TTL has expired, a refresh fails, and a value exists within the
  stale window
- **THEN** the last-good value is served rather than raising an error

#### Scenario: Concurrent misses collapse to one fetch
- **WHEN** multiple callers request the same uncached key concurrently
- **THEN** exactly one upstream fetch runs and all callers receive its result

#### Scenario: Cold miss with a failing upstream surfaces the error
- **WHEN** a key has no cached value and the upstream fetch fails
- **THEN** a typed upstream-unavailable error is raised

### Requirement: A default region drives region-dependent reads

Absent an admin-configured region, the catalog SHALL use a single documented
default region for its region-dependent TMDB reads — certifications and
watch-provider selection — and thread it into discover's `watch_region`, which
only filters results once service selection lands (M5).

#### Scenario: Region-dependent read uses the default region
- **WHEN** a certification, watch-provider, or discover query is composed with no configured region
- **THEN** it is issued against the documented default region

### Requirement: Unconfigured TMDB degrades without crashing

When `TMDB_API_KEY` is unset, catalog operations SHALL fail at their boundary with
a typed not-configured signal, and the application SHALL continue serving
`/api/v1/health` and the SPA.

#### Scenario: Catalog call while TMDB is unconfigured
- **WHEN** a catalog operation runs with no configured TMDB key
- **THEN** it raises a typed not-configured signal and `/api/v1/health` still
  responds `200`

