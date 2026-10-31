## MODIFIED Requirements

### Requirement: Server-recorded kinds are not accepted from the client

The `request`, `seed_request_history`, `watched_plex`, `watched_jellyfin`, and
`watched_trakt` signal kinds SHALL be
recorded only by the backend itself — by the successful Seerr request flow, the
incremental Seerr request-history sync, and the account-scoped Plex, Jellyfin,
and Trakt history syncs
respectively.
`POST /api/v1/signals` SHALL reject these kinds by input validation, so a client
cannot fabricate strong signals it did not earn.

#### Scenario: Client cannot self-report a request signal

- **WHEN** a client posts a signal with kind `request`,
  `seed_request_history`, `watched_plex`, `watched_jellyfin`, or `watched_trakt`
- **THEN** the request is rejected by input validation and nothing is stored

## ADDED Requirements

### Requirement: Trakt watched signals are unique latest-watch facts

`watched_trakt` SHALL have the fixed stored weight +2.5 and at most one active
row per user, media type, and TMDB id. Re-importing the same or an older observed
watch SHALL be an idempotent no-op; observing a later watch SHALL update only that
row's creation time and SHALL invalidate the user's materialized profile in the
same transaction. The signal SHALL be a strong positive and SHALL be rebuildable
from the caller's Trakt history while their Trakt account is linked.

#### Scenario: First canonical watch creates one signal

- **WHEN** a Trakt sync first observes a watched title with a TMDB id for a user
- **THEN** one +2.5 `watched_trakt` row is stored at its last-watched time

#### Scenario: Same title on Plex and Trakt

- **WHEN** a user has watched a title on Plex and it is also in their Trakt
  history
- **THEN** one `watched_plex` and one `watched_trakt` row exist, each from its own
  source
