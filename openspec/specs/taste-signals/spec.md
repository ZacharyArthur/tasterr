# taste-signals Specification

## Purpose
TBD - created by archiving change m4-taste. Update Purpose after archive.
## Requirements
### Requirement: In-app interaction signals are recorded per user

`POST /api/v1/signals` SHALL record an interaction signal for the authenticated
user with a validated body: `media_type` constrained to `movie` or `tv`, a
positive integer `tmdb_id`, and `kind` constrained to the client-recordable
kinds — `detail_open`, `watchlist`, `not_interested`. Each stored signal SHALL
carry its kind's fixed weight and a creation timestamp. Signals SHALL be scoped
to the authenticated user only: a signal is attributed to the session user, and
no endpoint SHALL expose one user's signals to another.

#### Scenario: Detail open recorded

- **WHEN** an authenticated user posts a `detail_open` signal for a title
- **THEN** a signal row is stored for that user with the detail-open weight and
  a timestamp

#### Scenario: Unknown kind rejected

- **WHEN** the posted `kind` is not one of the client-recordable kinds
- **THEN** the request is rejected by input validation before anything is stored

#### Scenario: Signals attributed to the session user

- **WHEN** a signal is posted on a valid session
- **THEN** it is stored against that session's user and no other

### Requirement: Server-recorded kinds are not accepted from the client

The `request` and `seed_request_history` signal kinds SHALL be recorded only by
the backend itself — by the request flow on a successful Seerr request and by
the cold-start seed import respectively. `POST /api/v1/signals` SHALL reject
these kinds by input validation, so a client cannot fabricate strong signals it
did not earn.

#### Scenario: Client cannot self-report a request signal

- **WHEN** a client posts a signal with kind `request` or `seed_request_history`
- **THEN** the request is rejected by input validation and nothing is stored

### Requirement: Toggle signals are retractable

The `watchlist` and `not_interested` kinds SHALL be retractable: a retraction
removes the user's stored signals of that kind for that title, so
remove-from-watchlist and un-hide leave no residual effect on the profile.
Retraction SHALL be rejected for non-toggle kinds.

#### Scenario: Watchlist retracted

- **WHEN** a user retracts a `watchlist` signal for a title they had listed
- **THEN** that user's watchlist signals for the title are removed

#### Scenario: Hide undone

- **WHEN** a user retracts a `not_interested` signal for a hidden title
- **THEN** the title is no longer treated as hidden for that user

#### Scenario: Non-toggle retraction rejected

- **WHEN** a retraction is posted for `detail_open`
- **THEN** the request is rejected by input validation

### Requirement: Detail-open signals are deduplicated per day

At most one `detail_open` signal per user, title, and calendar day SHALL be
stored, so repeatedly reopening a detail view does not inflate the title's
influence on the profile.

#### Scenario: Same-day reopen records nothing

- **WHEN** a user posts a second `detail_open` for the same title on the same day
- **THEN** no additional signal is stored and the response still succeeds

### Requirement: Signals endpoint is hardened

`POST /api/v1/signals` SHALL require a valid session using the shared
default-deny dependency and, as a mutation, SHALL enforce the same-origin (CSRF)
check. It SHALL declare an explicit, secret-free response model, return generic
errors, and log no per-title viewing behavior beyond outcome status.

#### Scenario: Unauthenticated signal rejected

- **WHEN** a client without a valid session posts a signal
- **THEN** the response is `401` and nothing is stored

#### Scenario: Cross-origin signal rejected

- **WHEN** a signal request arrives with cross-site origin evidence
- **THEN** it is rejected `403` before anything is stored
