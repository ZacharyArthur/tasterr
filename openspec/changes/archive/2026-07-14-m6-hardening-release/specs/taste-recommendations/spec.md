## MODIFIED Requirements

### Requirement: Taste profile is resettable per user

`POST /api/v1/recommendations/reset` SHALL require a valid session, the same-origin
(CSRF) check, and the shared loose authenticated-mutation rate limit, delete only the
calling user's signals and profile, and then re-seed from their Seerr request history.
When Seerr is unavailable the reset SHALL still clear the profile and leave the user
on the non-personalized experience. The response SHALL be secret-free and generic on
failure. A rate-limited reset SHALL return 429 before deleting or re-seeding anything.

#### Scenario: Reset wipes and re-seeds

- **WHEN** a user resets their taste profile
- **THEN** their signals and profile are deleted and re-seeded from their Seerr
  request history

#### Scenario: Reset touches only the caller

- **WHEN** one user resets their profile
- **THEN** other users' signals and profiles are untouched

#### Scenario: Reset with Seerr down still clears

- **WHEN** Seerr is unreachable during a reset
- **THEN** the user's signals and profile are cleared and the home degrades to
  non-personalized without an error

#### Scenario: Rate-limited reset preserves the current profile

- **WHEN** an authenticated user has exhausted the shared mutation bucket and posts
  a reset
- **THEN** the response is 429 and their signals, profile, and seed state are
  unchanged
