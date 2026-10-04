# media-requests Specification (delta)

## ADDED Requirements

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

## MODIFIED Requirements

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
