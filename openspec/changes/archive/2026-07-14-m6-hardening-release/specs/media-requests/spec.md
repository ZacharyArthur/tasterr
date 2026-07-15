## MODIFIED Requirements

### Requirement: Request endpoint is hardened and degrades
`POST /api/v1/request` SHALL require a valid session using the shared default-deny
dependency and, as a mutation, SHALL enforce the same-origin (CSRF) check and shared
loose authenticated-mutation rate limit. It SHALL declare an explicit, secret-free
response model and return generic errors carrying no upstream body, status, or
internal URL. When Seerr is unconfigured the endpoint SHALL report requests
unavailable rather than attempt a call; when Seerr is unreachable it SHALL return a
generic failure plus the redirect fallback. Browsing SHALL remain unaffected by any
of these outcomes. A rate-limited call SHALL return 429 before any Seerr request,
session re-authentication, taste-signal write, or database change.

#### Scenario: Unauthenticated request
- **WHEN** a client without a valid session calls `POST /api/v1/request`
- **THEN** the response is `401`

#### Scenario: Cross-origin request rejected
- **WHEN** a request arrives with cross-site origin evidence
- **THEN** it is rejected `403` before any Seerr call

#### Scenario: Rate-limited request has no side effect
- **WHEN** an authenticated user has exhausted the shared mutation bucket and
  requests a title
- **THEN** the response is `429` and no Seerr request, re-authentication, taste
  signal, or database mutation occurs

#### Scenario: Requests unavailable while Seerr is unconfigured
- **WHEN** a member submits a request with Seerr unconfigured
- **THEN** the endpoint reports requests unavailable and makes no Seerr call

#### Scenario: Seerr down yields a generic failure with fallback
- **WHEN** Seerr is unreachable during a request
- **THEN** the response is a generic failure that discloses no upstream detail and
  carries the redirect fallback, and browsing still works
