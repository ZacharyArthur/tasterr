# taste-signals Specification (delta)

## MODIFIED Requirements

### Requirement: Server-recorded kinds are not accepted from the client

The `request`, `seed_request_history`, `watched_plex`, and `watched_jellyfin`
signal kinds SHALL be
recorded only by the backend itself — by the successful Seerr request flow, the
incremental Seerr request-history sync, and the account-scoped Plex and Jellyfin
history syncs
respectively.
`POST /api/v1/signals` SHALL reject these kinds by input validation, so a client
cannot fabricate strong signals it did not earn.

#### Scenario: Client cannot self-report a request signal

- **WHEN** a client posts a signal with kind `request`,
  `seed_request_history`, `watched_plex`, or `watched_jellyfin`
- **THEN** the request is rejected by input validation and nothing is stored

## ADDED Requirements

### Requirement: Jellyfin watched signals are unique latest-watch facts

`watched_jellyfin` SHALL have the fixed stored weight +2.5 and at most one active
row per user, media type, and TMDB id. Re-importing the same or an older observed
play SHALL be an idempotent no-op; observing a later play SHALL update only that
row's creation time and SHALL invalidate the user's materialized profile in the
same transaction. The signal SHALL be a strong positive and SHALL be rebuildable
from the caller's Jellyfin history while their Jellyfin account is linked.

#### Scenario: First canonical play creates one signal

- **WHEN** history sync first observes a played title with a TMDB id for a user
- **THEN** one +2.5 `watched_jellyfin` row is stored at the observed play time

#### Scenario: Same title on Plex and Jellyfin

- **WHEN** a user has watched a title on both Plex and Jellyfin
- **THEN** one `watched_plex` and one `watched_jellyfin` row exist, each from its
  own source
