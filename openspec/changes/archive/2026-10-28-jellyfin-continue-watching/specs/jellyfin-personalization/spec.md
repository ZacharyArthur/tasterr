## MODIFIED Requirements

### Requirement: Jellyfin calls stay behind the client boundary

All Jellyfin calls SHALL live in `clients/jellyfin.py`, use only the configured
base URL, carry explicit timeouts, never follow redirects, parse responses into
typed models (unknown fields dropped), and never forward browser headers upstream
or upstream headers/bodies downstream. The API key and any user access token SHALL
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

## ADDED Requirements

### Requirement: Jellyfin contributes to Continue Watching

For a user with a usable Jellyfin link (Jellyfin configured, link not dormant)
and the `continue-watching` rail type enabled, Continue Watching SHALL include a
Jellyfin contribution read live with the API key, scoped to that link's Jellyfin
user id: up to 50 resumable movies and episodes, up to 50 next-up episodes, and
one page of up to 100 most recently played episodes ordered by descending
last-played time. The played-episode page SHALL be read concurrently with resume
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
