## MODIFIED Requirements

### Requirement: In-app interaction signals are recorded per user

`POST /api/v1/signals` SHALL record an interaction signal for the authenticated
user with a validated body: `media_type` constrained to `movie` or `tv`, an
integer `tmdb_id` between 1 and 2,147,483,647 inclusive, and `kind` constrained
to the client-recordable kinds — `detail_open`, `watchlist`, `not_interested`.
Each stored signal SHALL carry its kind's fixed weight and a creation timestamp.
Signals SHALL be scoped to the authenticated user only: a signal is attributed
to the session user, and no endpoint SHALL expose one user's signals to another.

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

#### Scenario: Out-of-range title id rejected

- **WHEN** the posted `tmdb_id` is outside the supported range
- **THEN** input validation rejects it before any signal or profile side effect
