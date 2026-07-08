# media-availability Specification

## Purpose
TBD - created by archiving change m3-seerr. Update Purpose after archive.
## Requirements
### Requirement: Seerr availability reads are isolated behind the client boundary

The system SHALL perform all Seerr availability reads through the single Seerr
client module in `tasterr.clients`, resolving a title's library status by TMDB id
via `GET {SEERR_INTERNAL_URL}/api/v1/{type}/{tmdbId}` and parsing `mediaInfo`
(overall status, plus per-season status for TV). Reads SHALL authenticate with the
**global `SEERR_API_KEY`** server setting — never a per-user session — because
availability is not user-attributed. Each read SHALL carry a short timeout and
SHALL NOT be retried (no retry storm). A `404` SHALL resolve to a *known*
not-in-library result; any other upstream error or timeout SHALL surface a typed
error for the caller to degrade. Browser headers SHALL NOT be forwarded upstream
and Seerr response bodies SHALL NOT be returned downstream.

#### Scenario: Known title resolves to a library status

- **WHEN** the client reads availability for a title Seerr knows
- **THEN** it returns the parsed library status from `mediaInfo`, with per-season
  status for TV

#### Scenario: Unknown-to-Seerr title is a known not-in-library result

- **WHEN** Seerr responds `404` for the title
- **THEN** the client returns a *known* not-in-library result, not an error

#### Scenario: Upstream failure surfaces for degradation

- **WHEN** the availability read times out or returns a non-404 error
- **THEN** the client raises a typed error carrying no upstream body or URL, and
  the read is not retried

### Requirement: Availability is a typed, secret-free status

Normalization SHALL convert Seerr's `mediaInfo` into a typed domain model — a
status of available, partially available, processing, pending, or not-requested,
plus a `known` flag that is false only when Seerr is unreachable (Unknown). The
model SHALL contain no secret material and SHALL NOT import the application
settings module.

#### Scenario: Seerr status maps to a typed status

- **WHEN** Seerr reports a title as available (or partial/processing/pending)
- **THEN** normalization yields the corresponding typed status with `known` true

#### Scenario: Absent media info is not-requested

- **WHEN** a known title carries no `mediaInfo`
- **THEN** normalization yields a not-requested status with `known` true

#### Scenario: Unreachable Seerr is Unknown

- **WHEN** availability cannot be resolved because Seerr is unreachable
- **THEN** the status is Unknown with `known` false

### Requirement: Availability reads are cached and degrade to Unknown

The availability engine SHALL cache Seerr reads in-process with a short TTL over a
bounded store, collapsing concurrent misses for the same title to a single upstream
fetch (single-flight). When a read fails, the engine SHALL resolve that title to
**Unknown** — it SHALL NOT serve a stale availability value and SHALL NOT cache the
failure. Because reads use the global API key, availability SHALL keep resolving
even when an individual user's Seerr session has lapsed.

#### Scenario: Fresh value avoids an upstream call

- **WHEN** a title's availability is requested within its TTL after being cached
- **THEN** the cached status is returned and no Seerr request is made

#### Scenario: Concurrent misses collapse to one fetch

- **WHEN** multiple callers request the same uncached title concurrently
- **THEN** exactly one Seerr read runs and all callers receive its result

#### Scenario: Seerr error degrades to Unknown, never stale

- **WHEN** a Seerr read fails, even if a previous value was cached
- **THEN** the title resolves to Unknown rather than a stale status, and the
  failure is not cached

### Requirement: Batch availability hydration endpoint

`POST /api/v1/availability` SHALL take a bounded, validated list of `{type, id}`
titles and return a library status for each, so the SPA can hydrate badges after a
feed has rendered. The endpoint SHALL require a valid session using the shared
default-deny dependency and SHALL declare an explicit, secret-free response model.
A failure resolving any single title SHALL degrade that title to Unknown without
failing the batch. When Seerr is unconfigured, the endpoint SHALL return Unknown
for every title without making a Seerr call.

#### Scenario: Unauthenticated hydration request

- **WHEN** a client without a valid session calls `POST /api/v1/availability`
- **THEN** the response is `401`

#### Scenario: Batch returns a status per title

- **WHEN** an authenticated client submits a list of titles
- **THEN** it receives a library status for each requested title

#### Scenario: One unresolved title does not fail the batch

- **WHEN** availability for one title in the batch cannot be resolved
- **THEN** that title is Unknown and the rest still carry their statuses

#### Scenario: Seerr unconfigured yields Unknown without a call

- **WHEN** the batch runs while Seerr is unconfigured
- **THEN** every title is Unknown and no Seerr request is made

### Requirement: Live Seerr availability contract test

A pytest-marked live suite (excluded from `just check` and CI) SHALL validate the
Seerr availability read contract against a real instance — the `mediaInfo` status
shape for an available title and the `404` not-in-library path — recording the
Seerr version tested.

#### Scenario: Live suite validates the availability contract

- **WHEN** the live-marked tests run with real Seerr coordinates configured
- **THEN** they verify the availability read shape and record the Seerr version

#### Scenario: Default test runs skip live tests

- **WHEN** `just check` runs
- **THEN** no live-marked availability test executes and no network access is
  attempted

