# jellyfin-personalization Specification

## Purpose
Optional Jellyfin integration: configuration, the client boundary, Jellyfin
sign-in, and bounded watch-history synchronization into taste signals.

## Requirements

### Requirement: Jellyfin is configured from the environment

Jellyfin features SHALL be enabled only when both `JELLYFIN_INTERNAL_URL` and
`JELLYFIN_API_KEY` are set.

#### Details

The URL SHALL be http or https with a host and SHALL
NOT carry embedded credentials (`user:pass@`), which would replace the required
`Authorization: MediaBrowser` header with basic auth; any other value SHALL be
treated as unset. The URL is server-side only. Neither value SHALL appear in `PublicConfig`, `/auth/methods`,
logs, or any response; only `/auth/methods` reports whether Jellyfin is
available.

#### Scenario: Partial configuration leaves Jellyfin off

- **WHEN** only one of the two Jellyfin settings is set
- **THEN** Jellyfin sign-in, linking, and sync are unavailable and boot succeeds

#### Scenario: URL with embedded credentials is rejected

- **WHEN** `JELLYFIN_INTERNAL_URL` contains `user:pass@`
- **THEN** Jellyfin is treated as unconfigured and boot succeeds

#### Scenario: Jellyfin secrets stay server-side

- **WHEN** `PublicConfig` and `/auth/methods` are serialized with Jellyfin fully configured
- **THEN** neither contains the Jellyfin URL or API key

### Requirement: Jellyfin calls stay behind the client boundary

All Jellyfin calls SHALL live in `clients/jellyfin.py`, use only the configured
base URL, carry explicit timeouts, never follow redirects, parse responses into
typed models (unknown fields dropped), and never forward browser headers upstream
or upstream headers/bodies downstream.

#### Details

The API key and any user access token SHALL
be sent only in the `Authorization` header (`MediaBrowser Token="…"`), never in a
URL. The API key SHALL be used only for reads scoped by an explicit Jellyfin user
id (user record, played items, series lookups, resumable items, next-up
episodes); it SHALL NOT be used for any mutation, and no API-key read SHALL omit
the user id.

#### Scenario: Unexpected Jellyfin payload

- **WHEN** Jellyfin returns an unexpected shape
- **THEN** the client raises a typed error and callers degrade generically

#### Scenario: Key never appears in URLs

- **WHEN** any Jellyfin call succeeds or fails
- **THEN** the API key appears only in the outbound `Authorization` header and is
  absent from URLs, logs, errors, and responses

#### Scenario: Resume reads are scoped to the linked user

- **WHEN** Continue Watching reads resumable or next-up items
- **THEN** every request carries the caller's linked Jellyfin user id and no other

### Requirement: Jellyfin sign-in

An empty password SHALL be refused with the same generic 401, before any Jellyfin
call, unless the operator sets `JELLYFIN_ALLOW_EMPTY_PASSWORD=true` (default
false), because Jellyfin sees every attempt as coming from Tasterr's own address
and would admit passwordless accounts to anyone who can reach Tasterr.

#### Details

`POST /api/v1/auth/jellyfin` with `{username, password}` SHALL forward the
credentials once to Jellyfin `AuthenticateByName`, and on success SHALL
immediately log out the returned access token, where a failed logout SHALL be logged
generically and SHALL NOT fail the sign-in, attempt the Seerr auto-link with
the same credentials, then resolve the Tasterr user through linked accounts with
the Jellyfin user id as the sign-in account and that Seerr result as input to
resolution step (2), and mint a session. Any enabled
account on the configured Jellyfin server SHALL be admitted. Credentials and the
returned access token SHALL NOT be stored or logged. Rejection SHALL return a
generic 401 identical for unknown user and wrong password; Jellyfin outage SHALL
return the generic upstream error. The endpoint SHALL enforce the same-origin
check and the tight login bucket, and SHALL return 503 when Jellyfin is not
configured.

#### Scenario: Valid Jellyfin credentials

- **WHEN** a user submits credentials Jellyfin accepts
- **THEN** a session is minted, the Jellyfin user is linked by id, and the
  Jellyfin access token has been logged out

#### Scenario: Empty password refused by default

- **WHEN** a sign-in or Jellyfin link arrives with an empty password and
  `JELLYFIN_ALLOW_EMPTY_PASSWORD` is unset
- **THEN** the response is the generic 401 and Jellyfin is not called

#### Scenario: Operator allows passwordless accounts

- **WHEN** `JELLYFIN_ALLOW_EMPTY_PASSWORD=true` and a passwordless Jellyfin
  account signs in
- **THEN** Jellyfin is asked as usual and the sign-in proceeds on success

#### Scenario: Invalid credentials stay generic

- **WHEN** Jellyfin rejects the credentials
- **THEN** the response is 401 with a generic message and nothing is created

#### Scenario: Jellyfin sign-in does not need Seerr or Plex

- **WHEN** only Jellyfin and the secret key are configured
- **THEN** Jellyfin sign-in succeeds and requests show as unavailable

### Requirement: Jellyfin appears on the login screen

When `/auth/methods` reports `jellyfin`, the login screen SHALL show "Continue with
Jellyfin" as a pill button with the Jellyfin mark, positioned after Plex and before
Seerr, expanding a username/password form in place. Session-transition rules of
the SPA login experience SHALL apply to Jellyfin sign-in.

#### Scenario: Jellyfin button expands its form

- **WHEN** the user activates "Continue with Jellyfin"
- **THEN** a username/password form expands below it

### Requirement: Jellyfin watch history synchronizes in bounded background work

A Jellyfin sign-in, a new Jellyfin link, and a Home read by any user with a
Jellyfin link SHALL evaluate one per-user single-flight trigger that schedules a
background sync only when the Jellyfin link's `sync_attempted_at` is absent or
older than six hours, waiting for that user's Seerr sync to settle.

#### Details

The task SHALL
commit the attempt timestamp before network work and SHALL NOT delay or fail
sign-in or Home. It SHALL read the linked user's played movies and played
episodes with the API key, newest play first, in pages of 100, at most 500 rows
per item type, under a 30-second network/mapping deadline. A first sync SHALL
read plays no older than the configured initial window
(`TASTERR_WATCH_HISTORY_DAYS`, default 365 days, see `app-settings`) before the
captured cutoff; a later sync SHALL
stop at plays older than 24 hours before `sync_synced_at`.

Movies SHALL map only from a valid positive TMDB provider id within the shared
bound. Episodes SHALL collapse to their series, whose TMDB provider id SHALL be
read in batched series lookups (at most 100 ids per call); an episode's own TMDB
id SHALL NOT be used. Items without a valid TMDB id SHALL be skipped. Each title
SHALL upsert one `watched_jellyfin` signal at its newest observed play time.
Played items without a play date SHALL be skipped.
`sync_synced_at` SHALL advance to the cutoff only after every read completes
within bounds (reaching a cap counts as complete; deadline expiry does not).
Network and mapping work SHALL finish before writes, with at most 100 facts per
write transaction. No raw Jellyfin item, item id, or play data SHALL be retained.

#### Scenario: First sync is bounded and non-blocking

- **WHEN** a user links Jellyfin
- **THEN** the response returns immediately while one background task imports
  at most the bounded window configured by `TASTERR_WATCH_HISTORY_DAYS`

#### Scenario: Play just outside the default window

- **WHEN** a member's newest Jellyfin play is 400 days old and
  `TASTERR_WATCH_HISTORY_DAYS` is 730
- **THEN** the first sync imports it

#### Scenario: Episodes count toward their series

- **WHEN** a user has played one episode of a series
- **THEN** one `watched_jellyfin` signal for the series is stored, from the
  series' TMDB id

#### Scenario: Unmapped items are skipped

- **WHEN** a played item has no valid TMDB provider id
- **THEN** it contributes no signal and the sync continues

#### Scenario: Items without a play date are skipped

- **WHEN** a played item has no `LastPlayedDate`
- **THEN** it contributes no signal and the sync continues

#### Scenario: Deadline keeps the watermark

- **WHEN** the 30-second deadline expires before reads complete
- **THEN** already mapped facts may be written but `sync_synced_at` does not advance

#### Scenario: Jellyfin outage does not affect Home

- **WHEN** Jellyfin is unreachable during a sync
- **THEN** Home returns normally and the sync retries after the six-hour throttle

### Requirement: Jellyfin contributes to Continue Watching

For a user with a usable Jellyfin link (Jellyfin configured, link not dormant)
and the `continue-watching` rail type enabled, Continue Watching SHALL include a
Jellyfin contribution read live with the API key, scoped to that link's Jellyfin
user id: up to 50 resumable movies and episodes, up to 50 next-up episodes, and
one page of up to 100 most recently played episodes ordered by descending
last-played time.

#### Details

The played-episode page SHALL be read concurrently with resume
and next-up, without pagination, solely to establish next-up activity timestamps;
it SHALL NOT contribute additional cards or imported signals. The Jellyfin source
load SHALL have a ten-second wall-clock deadline and SHALL run concurrently with
any Plex load.

Progress SHALL equal `floor(100 * position / runtime)` from the item's playback
position and runtime ticks when the position is non-negative and the runtime is
positive. A resumable item SHALL be included only when progress is 1 through 99.
Next-up episodes SHALL be included with null progress. An episode SHALL carry
`S{season} E{episode}` context when both numbers are valid non-negative integers,
and SHALL be omitted otherwise. Movies SHALL map only from their own valid TMDB
provider id. Episodes SHALL collapse to their series, whose TMDB id SHALL come
from the batched series lookup; an episode's own TMDB id SHALL NOT be used. Items
without a valid TMDB id SHALL be omitted. A resumable item SHALL be ordered by its
last-played time. A next-up episode SHALL use the newest last-played time of a
matching series' episode from the bounded played-episode page. If that page has no
matching dated episode, it SHALL use the series' own last-played time when present,
and otherwise keep its server-provided position after dated items. Activity
outside the 100-episode window SHALL NOT trigger additional history reads.

Plex and Jellyfin candidates SHALL merge per TMDB title: the newest activity
wins, then non-null progress on an equal timestamp, then Plex before Jellyfin,
then server order. At most 20 merged candidates SHALL enter TMDB resolution. The
result SHALL share the caller's single five-minute Continue Watching cache entry
with Plex. Successfully linking or refreshing either media account SHALL clear
that entry so the next Home load reads the current sources. Shared TMDB resolution
SHALL have a separate ten-second deadline after source collection; expiry SHALL
cancel resolution and cache an empty negative entry for five minutes, without
serving stale cards. A failed or timed-out Jellyfin load SHALL contribute nothing; when no
contributing source succeeds, the entry SHALL be an empty negative entry. No
Jellyfin item, item id, position, or progress SHALL be persisted or appear in a
browser response beyond the TMDB-backed summary, progress, and context.

#### Scenario: Jellyfin-only member sees resumable titles

- **WHEN** a member whose only media link is Jellyfin has a movie 40 % watched and
  a next-up episode S2 E3
- **THEN** Home shows Continue Watching with the movie at 40 % and the series card
  with `S2 E3` context and no progress bar

#### Scenario: Both servers merge into one rail

- **WHEN** a member with Plex and Jellyfin links is mid-way through the same movie
  on both, last played more recently on Jellyfin
- **THEN** Continue Watching shows that movie once, with the Jellyfin progress

#### Scenario: Unmapped Jellyfin items are omitted

- **WHEN** a resumable Jellyfin item has no valid TMDB provider id
- **THEN** it is omitted and the rest of the rail renders

#### Scenario: Jellyfin outage does not fail Home

- **WHEN** Jellyfin is unreachable while a Jellyfin-only member loads Home
- **THEN** Home returns without Continue Watching and no Jellyfin retry happens
  within five minutes

#### Scenario: Disabled rail does no Jellyfin work

- **WHEN** the admin disables Continue Watching
- **THEN** no Jellyfin resume or next-up read runs

#### Scenario: Dormant Jellyfin link is not read

- **WHEN** Jellyfin is no longer configured and a member with a Jellyfin link
  loads Home
- **THEN** no Jellyfin Continue Watching read runs

#### Scenario: Next-up uses episode activity when the series date is absent

- **WHEN** a next-up series has no own last-played date and a matching played
  episode is present in the bounded activity page
- **THEN** the card uses the newest matching episode date for merging and ordering

#### Scenario: Activity outside the bounded window keeps the fallback

- **WHEN** none of the 100 most recent played episodes supplies a date for a
  next-up series and the series has no own date
- **THEN** its card keeps server position after dated candidates without another
  activity page request

#### Scenario: Shared TMDB resolution times out

- **WHEN** source collection finishes but shared TMDB resolution exceeds its own
  ten-second deadline
- **THEN** resolution is cancelled, the rail is omitted, and the empty result is
  cached for five minutes without stale serving

#### Scenario: Linking a media account refreshes a cached rail

- **WHEN** a member with a positive or negative Continue Watching entry
  successfully links or refreshes Plex or Jellyfin
- **THEN** the entry is cleared and the next Home load reads the current sources

#### Scenario: Nothing is persisted

- **WHEN** Continue Watching is fetched with a Jellyfin contribution
- **THEN** no Jellyfin item, id, position, or progress is written to SQLite
