# media-requests Specification (delta)

## ADDED Requirements

### Requirement: TV season selection dialog

For a TV title with more than one season entry (Specials included), activating
Request SHALL open a dialog listing every season and, when the title has them,
Specials, each with an on/off toggle, plus an "All seasons" toggle, an OK
action and a Cancel action. Regular seasons SHALL start on and Specials off.
OK with that default choice SHALL send the same request body as a request
without the dialog; any other choice SHALL send the chosen season numbers.
OK SHALL be blocked while no season is chosen. Cancel and Escape SHALL close
only the dialog without requesting, and reopening SHALL restore the default
choice. Movies and single-season titles SHALL keep the one-step request. The
title detail page's own season list SHALL continue to omit Specials.

#### Scenario: Dialog defaults

- **WHEN** a member activates Request on a TV title with several seasons and Specials
- **THEN** a dialog lists every season on and Specials off, and nothing is submitted yet

#### Scenario: Default choice keeps the whole-series request

- **WHEN** the member presses OK without changing any toggle
- **THEN** the request body is identical to a request made without the dialog

#### Scenario: Chosen seasons are requested

- **WHEN** the member changes the toggles and presses OK
- **THEN** the request carries exactly the chosen season numbers, Specials as 0

#### Scenario: Empty choice is blocked

- **WHEN** every toggle is off
- **THEN** OK is disabled and a hint asks for at least one season

#### Scenario: Cancel requests nothing

- **WHEN** the member presses Cancel or Escape
- **THEN** only the dialog closes and no request is sent

#### Scenario: Single-season title requests directly

- **WHEN** a member activates Request on a TV title with one season entry
- **THEN** the request is submitted without a dialog

## MODIFIED Requirements

### Requirement: Request a title as the member

`POST /api/v1/request` SHALL proxy `POST {SEERR_INTERNAL_URL}/api/v1/request`
using the **per-user Seerr session cookie** stored on the member's Tasterr
session row, so the request is attributed to that member in Seerr and subject
to their own quota and approval rules. The request body SHALL be validated
(`media_type` constrained to `movie` or `tv`, an integer `tmdb_id` between 1
and 2,147,483,647 inclusive); a TV request SHALL request the whole series at
the selected standard or 4K variant unless an optional `seasons` list is
given. `seasons`, when present, SHALL be a non-empty list of unique integers
between 0 and 1000 inclusive (0 is Specials), SHALL only be accepted for `tv`,
SHALL be forwarded to Seerr as its `seasons` array in place of `"all"`, and
SHALL be preserved on a re-auth retry; invalid `seasons` SHALL be rejected with
`422` before any Seerr call. The request body MAY additionally include optional
`server_id`, `profile_id`, and `root_folder` fields to select a non-default
destination; when any of these is present, the backend SHALL validate the
combination against that title's permitted destinations (as returned by the
destinations requirement below) and SHALL reject the request (`422`, before
any Seerr request creation) if it does not match a real server/profile/root-folder for
that title. For standard requests with all three destination fields omitted,
the forwarded body SHALL remain identical to the default-destination request. The global Seerr API key
SHALL NOT be used for requests. On success the response SHALL carry the
title's resulting library status so the SPA can update its badge, and the
backend SHALL record a `request` taste signal for the member server-side — a
failure to record the signal SHALL NOT fail the request response.

The body SHALL accept is_4k (default false); a 4K request SHALL forward is4k=true. The
backend SHALL check current Seerr media-specific request/4K permissions and reject
unauthorized requests with 403 before creation. Advanced overrides SHALL require ADMIN,
MANAGE_REQUESTS, or REQUEST_ADVANCED; MANAGE_REQUESTS alone SHALL NOT grant ordinary or
4K requesting. A bare 4K request SHALL require a configured default 4K server for its
media type; absent configuration SHALL reject with 422 before request creation. Advanced
members MAY explicitly choose a validated non-default 4K server. The selected server
SHALL match is_4k. Server/profile ids SHALL be between 0 and 2,147,483,647 and
root_folder SHALL be nonempty and at most 4096 characters. A requested, processing,
partial or available variant SHALL reject repeat submission with 409; the other missing
variant SHALL remain requestable. Failed permission/status/destination reads SHALL
return generic failure with the server-built fallback rather than 422. Seerr quota,
approval and administrator rules SHALL remain authoritative.

#### Scenario: Request lands attributed to the member

- **WHEN** an authenticated member requests a title
- **THEN** the backend calls Seerr with that member's session cookie and Seerr
  records the request as that member's

#### Scenario: TV request covers the series

- **WHEN** a member requests a TV title without a season list
- **THEN** the request asks Seerr for the whole series at the selected standard or 4K variant

#### Scenario: TV request for chosen seasons

- **WHEN** a member requests a TV title with a valid `seasons` list
- **THEN** the request asks Seerr for exactly those seasons, and the same list is kept on a re-auth retry

#### Scenario: Invalid season list rejected

- **WHEN** `seasons` is sent for a movie, or is empty, out of range, or contains duplicates
- **THEN** the response is `422` and no Seerr call is made

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
- **THEN** the response is `422` and no Seerr request is created

#### Scenario: Omitted override behaves as before

- **WHEN** a member requests a standard title with no destination override fields
- **THEN** the request forwarded to Seerr is identical to today's
  default-destination request

#### Scenario: Bare 4K requires a configured default

- **WHEN** no default 4K server exists for the media type
- **THEN** a bare 4K request is rejected with 422 before creation, while an authorized explicit valid 4K destination remains allowed

#### Scenario: Missing 4K variant can be requested

- **WHEN** standard media is available and a permitted member requests its missing 4K variant
- **THEN** the member-cookie request carries is4k=true without changing the standard variant

#### Scenario: Variant and capability validation

- **WHEN** a member lacks the selected variant permission or submits an unauthorized advanced override
- **THEN** the response is 403 and no request is created

#### Scenario: Mismatched or already requested variant

- **WHEN** an override points to the wrong server variant or the selected variant already exists
- **THEN** the response is respectively 422 or 409 and no request is created

#### Scenario: Override discovery failure returns fallback

- **WHEN** the selected destination cannot be verified because its upstream read fails
- **THEN** the response is a generic failed outcome with the configured external fallback
