## MODIFIED Requirements

### Requirement: Server-recorded kinds are not accepted from the client

The `request`, `seed_request_history`, and `watched_plex` signal kinds SHALL be
recorded only by the backend itself — by the successful Seerr request flow, the
cold-start Seerr import, and the account-scoped Plex history sync respectively.
`POST /api/v1/signals` SHALL reject these kinds by input validation, so a client
cannot fabricate strong signals it did not earn.

#### Scenario: Client cannot self-report a request signal

- **WHEN** a client posts a signal with kind `request`,
  `seed_request_history`, or `watched_plex`
- **THEN** the request is rejected by input validation and nothing is stored

## ADDED Requirements

### Requirement: Plex watched signals are unique latest-watch facts

`watched_plex` SHALL have the fixed stored weight +2.5 and at most one active row
per user, media type, and TMDB id. Re-importing the same or an older observed
watch SHALL be an idempotent no-op; observing a later watch SHALL update only that
row's creation time and SHALL invalidate the user's materialized profile in the
same transaction. The signal SHALL be a strong positive and SHALL be entirely
rebuildable from the caller's Plex history while a usable Plex-backed session is
available.

#### Scenario: First canonical watch creates one signal

- **WHEN** history sync first observes a canonical watched title for a user
- **THEN** one +2.5 `watched_plex` row is stored at the observed watch time

#### Scenario: Older duplicate changes nothing

- **WHEN** a later sync returns the same title with an equal or older watch time
- **THEN** the existing row, timestamp, and profile materialization remain unchanged

#### Scenario: Rewatch advances the fact

- **WHEN** a later sync observes the same title with a newer watch time
- **THEN** the one row advances to that time and the user's profile is invalidated
