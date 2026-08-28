# plex-personalization Specification

## Purpose
TBD - created by archiving change v2-plex-aware-personalization. Update Purpose after archive.
## Requirements
### Requirement: Plex media reads use only the caller's protected session material

For a Plex-backed authenticated session, the system SHALL decrypt that session's
stored Plex account token only inside the server-side request/task that needs it.
It SHALL validate the token against the Plex account endpoint, discover accessible
Plex Media Server resources through plex.tv, and use each resource's access token
only as an `X-Plex-Token` request header. A local-login session or a session without
a valid Plex token SHALL have no live Plex media capability. No Plex account token,
resource access token, account id, server URL, machine id, rating key, or raw Plex
payload SHALL be returned to the browser or written to logs.

#### Scenario: Plex-backed caller gains read capability

- **WHEN** an authenticated Plex-backed caller has a valid encrypted token
- **THEN** the backend can discover and read that caller's accessible Plex servers
  without serializing any credential or connection metadata

#### Scenario: Local login has no live Plex capability

- **WHEN** an authenticated local-login session requests Home
- **THEN** no Plex account, resources, history, or Continue Watching call is made

#### Scenario: Credentials stay out of URLs and output

- **WHEN** any Plex read succeeds or fails
- **THEN** account/resource tokens appear only in outbound headers and are absent
  from URLs, cache keys, logs, errors, API bodies, and generated browser contracts

### Requirement: Advertised Plex server connections are verified before use

Resource discovery SHALL request HTTPS and relay connection data, retain at most
four Plex Media Server resources in deterministic owned-first, machine-identifier
order. The selected resources and at most six connections per resource SHALL be
probed concurrently, while the accepted result SHALL remain the first verified
connection in local-HTTPS, remote-direct, relay, then URI order. Before an
authenticated PMS read, the backend SHALL reject connections with an unapproved
scheme, host, port, credentials, query, or fragment;
require standard TLS certificate and hostname verification; and verify through
unauthenticated `/identity` that the connection's machine identifier matches the
resource. Redirects SHALL NOT be followed. Resource access tokens SHALL remain
call-local and SHALL NOT be persisted or stored in the general cache.
Resource pagination SHALL be implemented only when the live gate proves the
endpoint paginates; otherwise one bounded response SHALL be used.

#### Scenario: Local verified HTTPS connection wins

- **WHEN** one resource advertises valid local HTTPS, remote direct, and relay
  connections
- **THEN** the verified local HTTPS connection is used first

#### Scenario: Hostile advertised URL is skipped

- **WHEN** an advertised connection contains plain HTTP, credentials, an
  unapproved hostname/port, a query/fragment, or a mismatched machine identity
- **THEN** no authenticated request or credential is sent to that connection

#### Scenario: TLS verification cannot be bypassed

- **WHEN** an advertised HTTPS connection has an invalid or hostname-mismatched
  certificate
- **THEN** the connection is skipped even when its `/identity` body could claim the
  expected machine identifier

#### Scenario: One inaccessible server does not hide valid siblings

- **WHEN** one bounded resource has no usable connection and another does
- **THEN** reads continue with the usable resource without exceeding the server
  or connection-attempt bounds

#### Scenario: Multi-homed server has a fixed attempt ceiling

- **WHEN** one resource advertises more than six otherwise eligible connections
- **THEN** no more than its first six deterministically ordered connections receive
  an identity probe

#### Scenario: Stalled preferred connections do not serialize fallback

- **WHEN** earlier preferred connections stall while a later one verifies
- **THEN** their bounded probes overlap and the first verified connection by
  deterministic preference is selected without summing the individual timeouts

#### Scenario: More than four servers select deterministically

- **WHEN** resource discovery returns more than four accessible PMS devices
- **THEN** the same first four owned-first, machine-id-sorted resources are used
  for the same response on every run

#### Scenario: Failed account validation stops sibling discovery

- **WHEN** account validation fails while resource discovery is still running
- **THEN** discovery is cancelled and awaited before the media read fails or
  degrades

### Requirement: Plex media maps only through canonical TMDB GUIDs

The system SHALL map Plex movies only from validated `tmdb://<id>` GUIDs and
SHALL collapse an episode to its containing show's validated TMDB GUID. TMDB ids
SHALL satisfy the shared positive database-safe bound. Duplicates across servers
SHALL merge by `(media_type, tmdb_id)`, keeping the newest relevant watch/progress
context by the spike-confirmed last-viewed timestamp and then deterministic
resource order. Episode context SHALL be generated as `S{season} E{episode}` only
from validated positive integer fields. Unsupported media, malformed/missing
GUIDs, unresolved episodes, and invalid episode coordinates SHALL be skipped;
title/year fuzzy matching and upstream display-context passthrough SHALL NOT be
used.

#### Scenario: Movie maps canonically

- **WHEN** Plex movie metadata carries one valid TMDB GUID
- **THEN** it maps to that TMDB movie id

#### Scenario: Episode collapses to its show

- **WHEN** a Plex episode identifies a containing show with a valid TMDB GUID
- **THEN** it maps to that TMDB TV id rather than creating an episode signal/card

#### Scenario: Episode context uses validated coordinates

- **WHEN** an episode carries positive integer season and episode indexes
- **THEN** context is generated locally from those integers and no Plex display
  string is forwarded

#### Scenario: Unmatched media is omitted

- **WHEN** Plex metadata has no usable canonical TMDB GUID
- **THEN** the item is skipped without a title/year search or failed feed

#### Scenario: Metadata identity must match the request

- **WHEN** a metadata endpoint returns an item whose rating key differs from the
  requested key
- **THEN** that response is rejected and cannot contribute a canonical title

### Requirement: Plex watch history synchronizes in bounded background work

A successful Plex login and a Plex-backed Home read SHALL evaluate the same
per-user single-flight trigger: schedule only when
`plex_history_attempted_at` is absent or older than six hours. Plex SHALL use
single-flight state separate from the Seerr seed state and SHALL only read the
latter to wait for that user's cold-start seed to settle. After task creation, the
task SHALL use its own DB session to commit the attempt timestamp before any
network work; failed task creation or failed timestamp commit SHALL clear the
single-flight claim without leaving an attempt timestamp. The task SHALL NOT delay
or fail login/Home and SHALL be bounded to four deterministic servers, pages of
100, 500 newest-first rows per server, 500 total metadata resolutions at
concurrency eight, and a 30-second network/mapping deadline.

Each sync SHALL capture a cutoff. A first sync SHALL request from no earlier than
365 days before that cutoff; a later sync SHALL start 24 hours before
`plex_history_synced_at`. For each PMS, the identity validated by `/api/v2/user`
SHALL resolve to exactly one positive server-local `/accounts` row: first by exact
numeric `id` or `key`, or, when no numeric match exists, by one case-insensitive
exact `Account.name` match to the validated username. Unrelated malformed or
non-user rows SHALL be ignored; ambiguous, conflicting, missing, or malformed
candidate resolution SHALL fail that server. If and only if `/accounts` returns
403 for a self-only non-admin token, the validated positive cloud id SHALL be used
as the filter; redirects, 401, transport, 5xx, and malformed responses SHALL fail
closed. History SHALL be explicitly filtered to the resolved account id even for
an owner/admin token.
Every returned row's `accountID` SHALL equal that resolved id; a page with a
missing, malformed, or mismatched `accountID` fails that server and none of its
rows are imported. Account rows and resolved ids SHALL remain call-local and
SHALL NOT be persisted or logged.

Successful canonical watches SHALL upsert the caller's server-recorded
`watched_plex` title signals using the newest observed watch time. The watermark
SHALL advance to the captured cutoff only after every selected server completes
its bounded read; reaching a row/metadata cap counts as bounded completion and
older overflow is intentionally omitted. Deadline expiry SHALL fail each server
that has not completed its bounded read and SHALL NOT permit the success watermark
to advance. Partial success MAY persist idempotent
signal upserts but SHALL retain the prior success watermark for retry. All network
and mapping work SHALL finish before signal writes begin, and each write
transaction SHALL contain at most 100 facts. No raw history row or Plex identifier
SHALL be retained.

#### Scenario: First sync is bounded and non-blocking

- **WHEN** a Plex-backed user logs in without sync timestamps
- **THEN** login completes normally while one background task imports at most the
  bounded 365-day history window

#### Scenario: Failed scheduling leaves no six-hour dark window

- **WHEN** task creation or its pre-network attempt-timestamp commit fails
- **THEN** the Plex single-flight claim is cleared, no network read runs, and the
  user remains immediately eligible for a later trigger

#### Scenario: Owner history is account-filtered

- **WHEN** the caller's Plex token can administratively see several users
- **THEN** the caller's validated username resolves one PMS-local account row and
  every history page explicitly filters to that row's id

#### Scenario: Ambiguous PMS account identity fails closed

- **WHEN** a server's account list cannot uniquely map the validated cloud id or
  username to one local account
- **THEN** that server contributes no history and no account metadata is retained

#### Scenario: Non-admin account listing is forbidden

- **WHEN** a validated non-admin server token receives 403 from `/accounts`
- **THEN** its positive cloud account id is used as the self-only history filter
  and every returned row must exactly match it

#### Scenario: Other account endpoint failures stay closed

- **WHEN** `/accounts` redirects, rejects with a status other than 403, times out,
  returns a server error, or has a malformed shape
- **THEN** that server contributes no history

#### Scenario: Returned history identity is verified

- **WHEN** a filtered history page contains a row with a missing or different
  account id
- **THEN** that server read fails, none of its rows are imported, and the success
  watermark does not advance

#### Scenario: Repeated history is idempotent

- **WHEN** the 24-hour overlap returns a previously imported title
- **THEN** there remains one watched signal for that user/title and its timestamp
  moves only if the observed watch is newer

#### Scenario: Partial server failure retries safely

- **WHEN** one server imports and a sibling server fails
- **THEN** imported canonical signals may persist, the watermark does not advance,
  and no new attempt occurs for six hours before idempotent retry

#### Scenario: Deadline cannot advance past unread history

- **WHEN** the 30-second deadline expires after some selected servers finish but
  before another finishes its bounded read
- **THEN** the unfinished server is failed and the success watermark remains
  unchanged

#### Scenario: Oversized backlog follows the documented bound

- **WHEN** a stale sync window contains more than 500 newest-first rows on a server
- **THEN** only the bounded newest rows are considered, cap overflow is recorded as
  a generic count, and full selected-server completion may advance success to the
  captured cutoff

#### Scenario: Cold-start seed wins the scheduling race

- **WHEN** a new Plex-backed user's Seerr cold-start seed and Plex sync are both
  eligible
- **THEN** the Plex task starts only after the seed task settles, so Plex signals
  cannot suppress Seerr request-history seeding

#### Scenario: Reset cannot be undone by an in-flight sync

- **WHEN** reset races an active Plex history task
- **THEN** reset consumes cancellation without propagating `CancelledError`,
  returns 200 within the task's 30-second bound, clears signals and both sync
  timestamps, and permits no canceled batch to commit afterward

### Requirement: Continue Watching composes as a capability-gated rail

For a Plex-backed session with the rail type enabled, the home composer SHALL add
`continue-watching` titled **Continue Watching** ahead of the other personalized
providers. It SHALL read bounded items from
`MediaContainer.Hub[].Metadata` on each validated server, retain only
account-scoped resumable movie/episode items, order them by newest validated
last-viewed timestamp and deterministic resource/input order, de-duplicate equal
per-server rating keys, and let at most the first `RAIL_SIZE = 20` enter Plex
metadata/GUID expansion. Those candidates SHALL
then be canonically mapped/merged and no more than 20 SHALL enter browser-facing
TMDB resolution. Each server hub SHALL return at most 50 items. The complete load
SHALL have a ten-second wall-clock deadline. Final
secret-free results SHALL be cached per user for five minutes. A failed/timed-out
load SHALL replace the result with an empty negative entry for five minutes;
stale-on-error SHALL NOT be used. Plex capability gating SHALL happen before cache
access. Raw Plex payloads, server connections, and access tokens SHALL NOT be
cached. The provider SHALL use no request DB session and SHALL compose non-
exclusively; its declared response order SHALL remain first among personalized
providers.

Progress SHALL equal `floor(100 * view_offset / duration)` when the offset is
finite and non-negative and duration is finite and positive. Only results from 1
through 99 SHALL be included; zero, complete, missing, and invalid progress SHALL
omit the item rather than clamp it. A valid episode MAY carry locally generated
`S{season} E{episode}` context. The provider SHALL use the existing minimum-size,
cross-rail de-duplication, and independent-degradation behavior.

#### Scenario: Progress is calculated deterministically

- **WHEN** a resumable item has view offset 5 and duration 8
- **THEN** its progress is 62 percent

#### Scenario: Plex-backed user sees resumable titles

- **WHEN** an enabled Plex-backed user has enough canonically mapped in-progress
  movies or episodes
- **THEN** Home begins its personalized rails with one de-duplicated Continue
  Watching rail of TMDB-backed summaries

#### Scenario: Continue Watching work is capped before TMDB

- **WHEN** four servers each expose more than 50 resumable hub items
- **THEN** at most 50 items per server are read, at most 20 newest eligible rows
  enter Plex metadata expansion, and at most 20 merged canonical items enter TMDB
  resolution

#### Scenario: Fetch concurrency does not change response priority

- **WHEN** Continue Watching and other non-exclusive providers compose together
- **THEN** their fetches may overlap while a successful Continue Watching rail
  still appears first among personalized results

#### Scenario: Duplicate episode sources merge to a show

- **WHEN** several servers or episodes resolve to the same TMDB series
- **THEN** one series card remains from the newest last-viewed timestamp, with
  deterministic resource order breaking a tie

#### Scenario: Tokenless or disabled capability performs no work

- **WHEN** the session lacks a Plex token or the admin disabled Continue Watching
- **THEN** no Plex read runs and no empty rail placeholder is returned

#### Scenario: Plex failure does not fail Home

- **WHEN** plex.tv or every accessible PMS is unavailable and no cached result is
  usable
- **THEN** Continue Watching is omitted while the remaining Home feed returns

#### Scenario: Hanging Continue Watching is negatively cached

- **WHEN** the aggregate Plex load exceeds ten seconds
- **THEN** Home omits the rail, returns normally, and another request within five
  minutes performs no Plex retry

#### Scenario: Recovered Continue Watching replaces a negative entry

- **WHEN** Plex recovers after a five-minute negative cache entry expires
- **THEN** the next eligible load may populate and cache the caller's rail

#### Scenario: Failed refresh does not serve stale progress

- **WHEN** a successful five-minute entry expires and its refresh fails
- **THEN** the expired value is not served and an empty negative entry replaces it

#### Scenario: Plex sessions share one user cache entry

- **WHEN** two Plex-backed sessions for the same Tasterr user request Home during
  one cache lifetime
- **THEN** they use the same caller-scoped Continue Watching result without a
  second Plex load

#### Scenario: Continue Watching is isolated to the caller

- **WHEN** an owner-capable token's hub cannot be proven scoped or filtered to the
  validated account
- **THEN** Continue Watching is skipped for that token and no other user's
  progress can appear

### Requirement: Live Plex contracts are opt-in and redacted

An opt-in live pytest suite, excluded from `just check` and CI, SHALL validate the
current PIN token's account identity, PMS-local `/accounts` resolution or the
explicit-403 self-only fallback,
resources/access-token shape, connection identity with standard TLS validation,
resource paging behavior, explicitly account-filtered paged history with per-row
identity verification, account-scoped
Continue Watching, its merge timestamp, and canonical movie/show GUID mapping
against a real Plex deployment. Evidence SHALL record only Plex/PMS versions and
generic exercised/skipped/pass/fail cases. It
SHALL NOT retain tokens, connection/server/account/household identifiers, rating
keys, titles, timestamps, URLs, or raw bodies.

#### Scenario: Operator runs the live Plex contract

- **WHEN** the live suite receives operator-supplied Plex credentials
- **THEN** it validates only the documented read contract and emits redacted
  version/result evidence

#### Scenario: Default gate is network-free

- **WHEN** `just check` runs
- **THEN** no live Plex contract executes and no Plex network access is attempted
