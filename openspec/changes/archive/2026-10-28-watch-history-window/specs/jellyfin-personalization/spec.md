## MODIFIED Requirements

### Requirement: Jellyfin watch history synchronizes in bounded background work

A Jellyfin sign-in, a new Jellyfin link, and a Home read by any user with a
Jellyfin link SHALL evaluate one per-user single-flight trigger that schedules a
background sync only when the Jellyfin link's `sync_attempted_at` is absent or
older than six hours, waiting for that user's Seerr sync to settle. The task SHALL
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
