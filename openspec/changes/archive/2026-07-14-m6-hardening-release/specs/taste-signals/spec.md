## MODIFIED Requirements

### Requirement: Signals endpoint is hardened
`POST /api/v1/signals` SHALL require a valid session using the shared
default-deny dependency and, as a mutation, SHALL enforce the same-origin (CSRF)
check and shared loose authenticated-mutation rate limit. It SHALL declare an
explicit, secret-free response model, return generic errors, and log no per-title
viewing behavior beyond outcome status. A rate-limited call SHALL return 429 before
recording/retracting a signal or refreshing a profile.

#### Scenario: Unauthenticated signal rejected
- **WHEN** a client without a valid session posts a signal
- **THEN** the response is `401` and nothing is stored

#### Scenario: Cross-origin signal rejected
- **WHEN** a signal request arrives with cross-site origin evidence
- **THEN** it is rejected `403` before anything is stored

#### Scenario: Rate-limited signal has no side effect
- **WHEN** an authenticated user has exhausted the shared mutation bucket and posts
  or retracts a signal
- **THEN** the response is `429`, no signal row changes, and no profile refresh runs
