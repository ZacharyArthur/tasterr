# media-requests Specification

## Purpose
TBD - created by archiving change m3-seerr. Update Purpose after archive.

## Requirements

### Requirement: Request a title as the member

`POST /api/v1/request` SHALL proxy `POST {SEERR_INTERNAL_URL}/api/v1/request`
using the **per-user Seerr session cookie** stored on the member's Tasterr
session row, so the request is attributed to that member in Seerr and subject
to their own quota and approval rules. The request body SHALL be validated
(`media_type` constrained to `movie` or `tv`, an integer `tmdb_id` between 1
and 2,147,483,647 inclusive); a TV request SHALL request the whole series at
the default quality. The request body MAY additionally include optional
`server_id`, `profile_id`, and `root_folder` fields to select a non-default
destination; when any of these is present, the backend SHALL validate the
combination against that title's real destinations (as returned by the
destinations requirement above) and SHALL reject the request (`422`, before
any Seerr call) if it does not match a real server/profile/root-folder for
that title. When all three are omitted, request behavior is byte-for-byte
unchanged from the default-destination request. The global Seerr API key
SHALL NOT be used for requests. On success the response SHALL carry the
title's resulting library status so the SPA can update its badge, and the
backend SHALL record a `request` taste signal for the member server-side — a
failure to record the signal SHALL NOT fail the request response.

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

#### Scenario: Out-of-range title id rejected before request

- **WHEN** a member submits a `tmdb_id` outside the supported range
- **THEN** input validation rejects it before any Seerr or taste side effect

#### Scenario: Valid destination override is honored

- **WHEN** a member requests a title with a `server_id`/`profile_id`/
  `root_folder` combination that matches one of that title's real destinations
- **THEN** the request forwarded to Seerr specifies that server, profile, and
  root folder

#### Scenario: Invalid destination override is rejected

- **WHEN** a member requests a title with an override combination that does
  not match any of that title's real destinations
- **THEN** the response is `422` and no Seerr call is made

#### Scenario: Omitted override behaves as before

- **WHEN** a member requests a title with no override fields
- **THEN** the request forwarded to Seerr is identical to today's
  default-destination request

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

### Requirement: Request destinations for a title

`GET /api/v1/{type}/{id}/destinations` SHALL return the available request
destinations for that title's media type — every configured Seerr server for
`radarr` (movies) or `sonarr` (TV), each with its available quality profiles
and root folders, and each server's own default profile/root folder flagged.
`{type}` SHALL be validated the same as the request endpoint's `media_type`;
`{id}` SHALL be validated the same as the request endpoint's `tmdb_id` and is
used only to select `radarr` vs. `sonarr` dispatch. The endpoint SHALL require
a valid session (default-deny) and SHALL use the **global** Seerr API key, not
a per-user session cookie, because this is household configuration metadata,
not a per-user action. The response SHALL be an explicit, secret-free model —
no raw upstream JSON passthrough. When Seerr is unconfigured or unreachable,
the endpoint SHALL return an empty destinations list rather than an error.

#### Scenario: Single configured destination

- **WHEN** a title's media type has exactly one configured Seerr server
- **THEN** the response lists that one server with its profiles and root
  folders, its default profile/root folder flagged

#### Scenario: Multiple configured destinations

- **WHEN** a title's media type has more than one configured Seerr server
- **THEN** the response lists every server, each with its own profiles, root
  folders, and flagged default

#### Scenario: Seerr unconfigured yields an empty list

- **WHEN** Seerr is unconfigured
- **THEN** the response is an empty destinations list and no upstream call is
  attempted

#### Scenario: Seerr unreachable yields an empty list

- **WHEN** Seerr is unreachable
- **THEN** the response is an empty destinations list, discloses no upstream
  error body, status, or internal URL

#### Scenario: Unauthenticated destinations request

- **WHEN** a client without a valid session calls the destinations endpoint
- **THEN** the response is `401`
