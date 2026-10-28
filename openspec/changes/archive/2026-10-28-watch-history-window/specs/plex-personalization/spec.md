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
the configured initial window (`TASTERR_WATCH_HISTORY_DAYS`, default 365 days, see
`app-settings`) before that cutoff; a later sync SHALL start 24 hours before
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
  the bounded history window configured by `TASTERR_WATCH_HISTORY_DAYS`

#### Scenario: Longer configured window reaches older plays

- **WHEN** `TASTERR_WATCH_HISTORY_DAYS` is 730 and a Plex link's first sync runs
- **THEN** history is requested from 730 days before the cutoff, within the same
  row and metadata caps

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

