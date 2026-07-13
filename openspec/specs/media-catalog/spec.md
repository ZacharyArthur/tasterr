# media-catalog Specification

## Purpose
TBD - created by archiving change m2-browse. Update Purpose after archive.
## Requirements
### Requirement: TMDB access is isolated behind the client boundary

The system SHALL perform all TMDB access through a single client module in
`tasterr.clients`, including catalog reads, region/provider enumeration, and the
configured connection probe. Every request SHALL carry an explicit timeout and a
bounded retry with backoff that honors `Retry-After` on `429`/`5xx`. The global
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

#### Scenario: Service filters are serialized server-side
- **WHEN** catalog discovery has selected provider ids
- **THEN** the client sends bounded integer provider ids with flatrate semantics
  and never accepts an outbound base URL from the request

### Requirement: Catalog normalization produces typed, secret-free domain models

Normalization SHALL convert TMDB JSON into typed domain models — media summary,
media detail, hero slide, rail, person, video, season summary, watch-provider
info, region option, and service option — resolving movie/TV titles and release
years and passing image/logo paths through unchanged. Person results returned by
multi-search SHALL be dropped. Movie/TV provider lists SHALL be unioned by
provider id and ordered by the best TMDB display priority. Domain models SHALL
contain no secret material and SHALL NOT import the application deployment
settings module.

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
  active-region watch-provider info

#### Scenario: Movie and TV providers are de-duplicated
- **WHEN** the same service appears in both TMDB provider lists for a region
- **THEN** normalization emits it once using the better display priority

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

The catalog SHALL resolve the global admin-configured region for certifications,
watch-provider selection, title facts, provider enumeration, and discover's
`watch_region`. When no valid runtime row exists it SHALL use the documented
default region. A non-empty selected-service list SHALL additionally constrain
discover calls with OR semantics to titles available flatrate on any selected
service; an empty list SHALL omit the provider filter and browse all titles in
the active region.

#### Scenario: Region-dependent read uses the configured region
- **WHEN** an admin-configured region is present
- **THEN** certification, watch-provider, facts, and discover reads use that
  region consistently for the request

#### Scenario: Region-dependent read uses the default region
- **WHEN** no valid configured region exists
- **THEN** region-dependent reads use the documented default region

#### Scenario: Selected services filter discovery
- **WHEN** one or more service ids are selected
- **THEN** discovery requests require flatrate availability on any selected
  service in the active region

#### Scenario: Empty selection does not hide the catalog
- **WHEN** no services are selected
- **THEN** discovery omits the provider filter and returns region-wide catalog
  results

### Requirement: Unconfigured TMDB degrades without crashing

When `TMDB_API_KEY` is unset, catalog operations SHALL fail at their boundary with
a typed not-configured signal, and the application SHALL continue serving
`/api/v1/health` and the SPA.

#### Scenario: Catalog call while TMDB is unconfigured
- **WHEN** a catalog operation runs with no configured TMDB key
- **THEN** it raises a typed not-configured signal and `/api/v1/health` still
  responds `200`

### Requirement: Title facts feed the recommendation engine

The catalog SHALL expose an internal **title facts** surface per title — genres,
keywords, top-billed cast, director/creator, original language, release year,
runtime, vote statistics, active watch region, and that region's flatrate
provider ids — for the recommendation engine's feature builder. The TMDB detail
fetch SHALL include keywords and watch providers via the detail append, so facts
derive from the same cached detail payload as normalized detail and repeated
facts reads within the cache TTL make no additional TMDB call. Title facts are
internal domain data: they SHALL NOT appear in any API response model and SHALL
NOT import application deployment settings.

#### Scenario: Facts include keywords
- **WHEN** title facts are built for a title whose TMDB detail carries keywords
- **THEN** the facts include those keywords alongside genres, cast, creator,
  language, year, runtime, and vote statistics

#### Scenario: Facts include active-region services
- **WHEN** title facts are built for a title with flatrate providers in the active
  region
- **THEN** the facts include that region and the provider ids from the same detail
  payload

#### Scenario: Facts reuse the cached detail fetch
- **WHEN** title facts are requested for a title whose detail payload is cached
  and fresh
- **THEN** no additional TMDB request is made

#### Scenario: Facts stay out of API responses
- **WHEN** any `/api/v1` response model is serialized
- **THEN** it contains no title-facts payload

### Requirement: Region and provider metadata use bounded stale-on-error caching

TMDB region and provider-list reads SHALL use the existing bounded in-process
cache with long endpoint-specific TTL/stale windows and single-flight behavior.
Cache keys SHALL include media type and region where applicable. A stale value
SHALL be served when refresh fails; a cold failure SHALL surface through the
generic catalog error boundary rather than returning partial upstream JSON.

#### Scenario: Region provider cache is reused
- **WHEN** an admin repeats a provider-list request within its TTL
- **THEN** the cached typed value is returned without another TMDB call

#### Scenario: Stale provider list survives refresh failure
- **WHEN** provider metadata is stale-but-servable and TMDB refresh fails
- **THEN** the last good list is returned
