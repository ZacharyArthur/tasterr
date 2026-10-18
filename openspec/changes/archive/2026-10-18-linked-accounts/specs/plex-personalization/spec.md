# plex-personalization Specification (delta)

## MODIFIED Requirements

### Requirement: Plex watch history synchronizes in bounded background work

A successful Plex sign-in, a new Plex link, and a Home read by any user with a
Plex link SHALL evaluate the same per-user single-flight trigger: schedule only
when the Plex link's `sync_attempted_at` is absent or older than six hours. The
task SHALL use the token stored on the Plex link, whichever method the user signed
in with. Plex SHALL use single-flight state separate from the Seerr sync state and
SHALL only read the latter to wait for that user's Seerr sync to settle. After
task creation, the
task SHALL use its own DB session to commit the attempt timestamp before any
network work; failed task creation or failed timestamp commit SHALL clear the
single-flight claim without leaving an attempt timestamp. The task SHALL NOT delay
or fail login/Home and SHALL be bounded to four deterministic servers, pages of
100, 500 newest-first rows per server, 500 total metadata resolutions at
concurrency eight, and a 30-second network/mapping deadline.

Each sync SHALL capture a cutoff. A first sync SHALL request from no earlier than
365 days before that cutoff; a later sync SHALL start 24 hours before
the Plex link's `sync_synced_at`. For each PMS, the identity validated by `/api/v2/user`
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

- **WHEN** a user whose Plex link has no sync timestamps signs in
- **THEN** sign-in completes normally while one background task imports at most
  the bounded 365-day history window

#### Scenario: Sync does not depend on the sign-in method

- **WHEN** a user with a Plex link signed in with Seerr local credentials loads Home
- **THEN** the Plex history trigger is evaluated with the token stored on the
  Plex link

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

- **WHEN** a user's Seerr request-history sync and Plex sync are both eligible
- **THEN** the Plex task starts only after the Seerr task settles

#### Scenario: Reset cannot be undone by an in-flight sync

- **WHEN** reset races an active Plex history task
- **THEN** reset consumes cancellation without propagating `CancelledError`,
  returns 204 within the task's 30-second bound, clears signals and both sync
  timestamps, and permits no canceled batch to commit afterward

### Requirement: Continue Watching composes as a capability-gated rail

For a user with a Plex link and the rail type enabled, the home composer SHALL add
`continue-watching` titled **Continue Watching** ahead of the other personalized
providers. It SHALL read bounded items from
`MediaContainer.Hub[].Metadata` on each validated server, retain only
account-scoped in-progress movie items and eligible in-progress or next-up
episode items, order them by the first available item, show, or season
last-viewed timestamp and deterministic resource/input order, de-duplicate equal
per-server rating keys, and let at most the first `RAIL_SIZE = 20` enter Plex
metadata/GUID expansion. A next-up episode with none of those timestamps SHALL
remain eligible in its server-provided hub position rather than be dropped.
Those candidates SHALL then be canonically mapped/merged and no more than 20
SHALL enter browser-facing TMDB resolution. Each server hub SHALL return at most
50 items. The complete load SHALL have a ten-second wall-clock deadline. Final
secret-free results SHALL be cached per user for five minutes. A failed/timed-out
load SHALL replace the result with an empty negative entry for five minutes;
stale-on-error SHALL NOT be used. Plex capability gating SHALL happen before
cache access. Raw Plex payloads, server connections, and access tokens SHALL NOT
be cached. The provider SHALL use no request DB session and SHALL compose non-
exclusively; its declared response order SHALL remain first among personalized
providers.

Progress SHALL equal `floor(100 * view_offset / duration)` when the offset is
finite and non-negative and duration is finite and positive. Started items SHALL
be included only when the result is from 1 through 99; zero, complete, and
invalid progress SHALL omit the item rather than clamp it. Missing progress SHALL
omit a movie, but an episode with an absent view offset MAY be included as a
next-up item with null progress. A valid episode MAY carry locally generated
`S{season} E{episode}` context. A card with that context SHALL display it even
when progress is null, while omitting the progress bar. The provider SHALL use
the existing minimum-size, cross-rail de-duplication, and
independent-degradation behavior.

#### Scenario: Progress is calculated deterministically

- **WHEN** a resumable item has view offset 5 and duration 8
- **THEN** its progress is 62 percent

#### Scenario: Plex-backed user sees resumable titles

- **WHEN** an enabled user with a Plex link has enough canonically mapped in-progress
  movies, in-progress episodes, or next-up episodes
- **THEN** Home begins its personalized rails with one de-duplicated Continue
  Watching rail of TMDB-backed summaries

#### Scenario: Next-up episode uses show activity timestamp

- **WHEN** an episode has no view offset or item last-viewed timestamp but has a
  show or season last-viewed timestamp
- **THEN** it remains eligible with null progress and uses the first available
  show or season timestamp for ordering

#### Scenario: Next-up episode falls back to Plex hub position

- **WHEN** an episode has no view offset and no item, show, or season last-viewed
  timestamp
- **THEN** it remains eligible with null progress in the relative recency order
  supplied by its server's Continue Watching hub

#### Scenario: Progress-less movie remains excluded

- **WHEN** a movie has no valid in-progress percentage
- **THEN** it is omitted from Continue Watching

#### Scenario: Next-up card shows episode context without progress

- **WHEN** an eligible next-up episode has local season and episode context but
  null progress
- **THEN** its card displays the context without rendering a progress bar

#### Scenario: Continue Watching work is capped before TMDB

- **WHEN** four servers each expose more than 50 eligible hub items
- **THEN** at most 50 items per server are read, at most 20 newest eligible rows
  enter Plex metadata expansion, and at most 20 merged canonical items enter TMDB
  resolution

#### Scenario: Fetch concurrency does not change response priority

- **WHEN** Continue Watching and other non-exclusive providers compose together
- **THEN** their fetches may overlap while a successful Continue Watching rail
  still appears first among personalized results

#### Scenario: Duplicate episode sources merge to a show

- **WHEN** several servers or episodes resolve to the same TMDB series
- **THEN** one series card remains from the newest available activity timestamp,
  preferring non-null progress on an equal timestamp before server hub and
  deterministic resource order break any remaining tie

#### Scenario: Tokenless or disabled capability performs no work

- **WHEN** the user has no Plex link or the admin disabled Continue Watching
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

- **WHEN** two sessions for the same Tasterr user with a Plex link request Home during
  one cache lifetime
- **THEN** they use the same caller-scoped Continue Watching result without a
  second Plex load

#### Scenario: Continue Watching is isolated to the caller

- **WHEN** an owner-capable token's hub cannot be proven scoped or filtered to the
  validated account
- **THEN** Continue Watching is skipped for that token and no other user's
  progress can appear

## REMOVED Requirements

### Requirement: Plex media reads use only the caller's protected session material
**Reason**: Plex credentials move from the session to the user's Plex link.
**Migration**: Replaced by "Plex media reads use only the caller's linked-account
material"; members sign in once after migration `0007` to store the token on the link.

## ADDED Requirements

### Requirement: Plex media reads use only the caller's linked-account material

For an authenticated user with a Plex link, the system SHALL decrypt the token
stored on that link only inside the server-side request/task that needs it. It
SHALL validate the token against the Plex account endpoint, discover accessible
Plex Media Server resources through plex.tv, and use each resource's access token
only as an `X-Plex-Token` request header. A user without a Plex link, or whose
link token cannot be decrypted, SHALL have no live Plex media capability. No Plex
account token, resource access token, account id, server URL, machine id, rating
key, or raw Plex payload SHALL be returned to the browser or written to logs.

#### Scenario: Linked caller gains read capability

- **WHEN** an authenticated user with a valid Plex link loads Home
- **THEN** the backend can discover and read that user's accessible Plex servers
  without serializing any credential or connection metadata, whichever method
  they signed in with

#### Scenario: Unlinked user has no live Plex capability

- **WHEN** an authenticated user without a Plex link requests Home
- **THEN** no Plex account, resources, history, or Continue Watching call is made

#### Scenario: Credentials stay out of URLs and output

- **WHEN** any Plex read succeeds or fails
- **THEN** account/resource tokens appear only in outbound headers and are absent
  from URLs, cache keys, logs, errors, API bodies, and generated browser contracts
