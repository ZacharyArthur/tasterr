## MODIFIED Requirements

### Requirement: Continue Watching composes as a capability-gated rail

For a Plex-backed session with the rail type enabled, the home composer SHALL add
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

- **WHEN** an enabled Plex-backed user has enough canonically mapped in-progress
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
