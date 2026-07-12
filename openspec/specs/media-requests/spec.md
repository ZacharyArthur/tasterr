# media-requests Specification

## Purpose
TBD - created by archiving change m3-seerr. Update Purpose after archive.
## Requirements
### Requirement: Request a title as the member

`POST /api/v1/request` SHALL proxy `POST {SEERR_INTERNAL_URL}/api/v1/request` using
the **per-user Seerr session cookie** stored on the member's Tasterr session row,
so the request is attributed to that member in Seerr and subject to their own quota
and approval rules. The request body SHALL be validated (`media_type` constrained
to `movie` or `tv`, a positive integer `tmdb_id`); a TV request SHALL request the
whole series at the default quality. The global Seerr API key SHALL NOT be used for
requests. On success the response SHALL carry the title's resulting library status
so the SPA can update its badge, and the backend SHALL record a `request` taste
signal for the member server-side — a failure to record the signal SHALL NOT fail
the request response.

#### Scenario: Request lands attributed to the member

- **WHEN** an authenticated member requests a title
- **THEN** the backend calls Seerr with that member's session cookie and Seerr
  records the request as that member's

#### Scenario: TV request covers the series

- **WHEN** a member requests a TV title
- **THEN** the request asks Seerr for the whole series at the default quality

#### Scenario: Successful request returns the new status

- **WHEN** Seerr accepts the request
- **THEN** the response includes the title's resulting library status

#### Scenario: Successful request records a taste signal

- **WHEN** Seerr accepts a member's request
- **THEN** a `request` signal for that title is recorded server-side for the member

#### Scenario: Signal failure never fails the request

- **WHEN** the taste-signal write errors after Seerr accepted the request
- **THEN** the request response still reports success

### Requirement: Invalid-session re-auth ladder

The backend SHALL recover from Seerr's `403` invalid-session rejection with a
bounded re-auth ladder, re-authenticating **at most once** per request (because
`403` is also Seerr's genuine permission-denied response). For a **Plex**
member (an encrypted Plex token is stored on the session), the backend SHALL
silently re-authenticate by decrypting the stored token, logging into Seerr again,
persisting the refreshed session cookie, and retrying the request once; a second
`403` SHALL be treated as a genuine denial and surfaced as a generic failure. For a
**local** member (no stored token), the backend SHALL surface a `re_auth_required`
signal for the SPA to prompt re-login, without retrying.

#### Scenario: Plex member silently re-authenticates and retries

- **WHEN** a Plex member's request gets `403` for a lapsed session
- **THEN** the backend re-authenticates with the stored Plex token, updates the
  stored session cookie, and retries the request once

#### Scenario: Persistent denial after re-auth is generic

- **WHEN** the retried request is still `403`
- **THEN** the response is a generic failure with no upstream body, and no further
  re-auth is attempted

#### Scenario: Local member is asked to re-login

- **WHEN** a local member's request gets `403`
- **THEN** the response is `re_auth_required` and no silent re-auth is attempted

### Requirement: Seerr redirect fallback is built server-side

Every `POST /api/v1/request` response SHALL include a Seerr **external** deep link
for the title when `SEERR_EXTERNAL_URL` is configured, assembled server-side from
the validated external URL and the integer title id — never echoed from request
input and never exposing the internal Seerr URL. When `SEERR_EXTERNAL_URL` is
unset, no link SHALL be included. This lets the SPA always offer a "Request in
Seerr" fallback without constructing a Seerr URL client-side.

#### Scenario: Response carries a server-built external link

- **WHEN** a request completes (successfully or not) and the external URL is set
- **THEN** the response includes a Seerr external deep link for that title built
  from validated configuration

#### Scenario: No external URL, no link, no leak

- **WHEN** `SEERR_EXTERNAL_URL` is unset
- **THEN** the response includes no Seerr link and never exposes the internal URL

### Requirement: Request endpoint is hardened and degrades

`POST /api/v1/request` SHALL require a valid session using the shared default-deny
dependency and, as a mutation, SHALL enforce the same-origin (CSRF) check.
It SHALL declare an explicit, secret-free response model and return generic errors
carrying no upstream body, status, or internal URL. When Seerr is unconfigured the
endpoint SHALL report requests unavailable rather than attempt a call; when Seerr
is unreachable it SHALL return a generic failure plus the redirect fallback.
Browsing SHALL remain unaffected by any of these outcomes.

#### Scenario: Unauthenticated request

- **WHEN** a client without a valid session calls `POST /api/v1/request`
- **THEN** the response is `401`

#### Scenario: Cross-origin request rejected

- **WHEN** a request arrives with cross-site origin evidence
- **THEN** it is rejected `403` before any Seerr call

#### Scenario: Requests unavailable while Seerr is unconfigured

- **WHEN** a member submits a request with Seerr unconfigured
- **THEN** the endpoint reports requests unavailable and makes no Seerr call

#### Scenario: Seerr down yields a generic failure with fallback

- **WHEN** Seerr is unreachable during a request
- **THEN** the response is a generic failure that discloses no upstream detail and
  carries the redirect fallback, and browsing still works

### Requirement: Live request-as-user contract test

A pytest-marked live suite (excluded from `just check` and CI) SHALL validate the
request-as-user contract against a real instance — creating a request with a user
session and confirming attribution, then cleaning up without treating Seerr's
delete `204` as authoritative while a request may still be mid-dispatch. It SHALL
also validate the re-auth **primitives** the ladder composes — an invalid session
returning `403`, and (given an operator-supplied stored Plex token) that token
minting a fresh session — while the ladder's orchestration (`403` → re-auth →
retry once) is covered by the mocked unit tests. The Seerr version tested SHALL be
recorded.

#### Scenario: Live suite validates attribution

- **WHEN** the live-marked tests run with real Seerr coordinates configured
- **THEN** they create a request attributed to the user and record the Seerr version

#### Scenario: Default test runs skip live tests

- **WHEN** `just check` runs
- **THEN** no live-marked request test executes and no network access is attempted

