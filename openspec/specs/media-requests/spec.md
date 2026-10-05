# media-requests Specification

## Purpose
Let household members request missing Standard or 4K media with their Seerr
identity, permissions, defaults, quotas, and approval rules preserved.

## Requirements

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

#### Scenario: Destination contract verifies stored fields

- **WHEN** the opt-in operator-configured destination contract runs
- **THEN** it calls the production client, prefers a non-default permitted combination, verifies stored attribution/is4k/server/profile/root-folder, records Seerr version and attempts cleanup even after ambiguous submission failure

### Requirement: Request destinations for a title

GET /api/v1/{type}/{id}/destinations SHALL return a secret-free options envelope
containing current per-media standard/4K request capabilities, advanced capability, and
permitted destinations, plus can_request_4k_default indicating permission and a
configured default 4K server. Without a default, only advanced members with a configured
4K destination SHALL have 4K capability. The validated type selects Radarr or Sonarr;
the bounded id preserves route consistency and does not choose dispatch. Discovery SHALL
require a session and use the global key for server-derived user permissions and
household service metadata. Destination metadata SHALL be exposed only to members with
advanced capability, and only for request variants they can request. Each entry SHALL
include is_4k, the server id/name, defaults and available profiles/folders. Unconfigured
or failed discovery SHALL yield unavailable capabilities and an empty list; successful
details from other servers SHALL survive an individual detail failure.

#### Scenario: Permission-scoped standard and 4K destinations

- **WHEN** an advanced member can request both variants
- **THEN** discovery lists both variants with explicit is_4k and their distinct defaults

#### Scenario: Nonadvanced member retains default requesting

- **WHEN** a member has variant permission without advanced capability
- **THEN** capabilities permit the variant but no server/profile/folder metadata is disclosed

#### Scenario: Single configured destination

- **WHEN** an advanced member can request the single configured variant destination
- **THEN** the options envelope lists that server with its defaults/profiles/folders

#### Scenario: Multiple configured destinations

- **WHEN** an advanced member can request multiple configured destinations
- **THEN** the envelope lists all permitted destinations with explicit variant flags

#### Scenario: Seerr unconfigured yields an empty list

- **WHEN** Seerr is unconfigured
- **THEN** options are unavailable with an empty destinations list and no upstream call

#### Scenario: Seerr unreachable yields an empty list

- **WHEN** Seerr permission/server discovery fails
- **THEN** options are unavailable with an empty destinations list and no upstream detail

#### Scenario: Unauthenticated destinations request

- **WHEN** the caller has no valid session
- **THEN** discovery returns 401

### Requirement: Explicit and resilient request controls

Controls SHALL offer permitted missing Standard/4K variants explicitly, selecting
Standard first when requestable and otherwise the eligible missing variant. Initial
destination SHALL be Use Seerr defaults; no unchanged confirmation SHALL send
destination overrides. Advanced members SHALL be able to explicitly choose a variant-
matching server/profile/folder and cancel back to defaults. Controls SHALL await initial
discovery, block bare 4K confirmation without default capability while allowing explicit
advanced selection, reconcile selections against refreshed options, disable pending
actions, and visibly show mutation errors with retry. Unavailable discovery SHALL allow
a bare standard attempt only where standard availability is known missing; it SHALL NOT
authorize a 4K or advanced request. Shared media-type discovery SHALL not run when
unconfigured or no known variant is missing.

#### Scenario: Slow discovery cannot bypass selection

- **WHEN** discovery is pending
- **THEN** request submission waits until the initial lookup settles

#### Scenario: Defaults preserve anime routing

- **WHEN** a member confirms using Seerr defaults
- **THEN** no server/profile/root-folder overrides are submitted

#### Scenario: Stale selection requires reselection

- **WHEN** a chosen server/profile/folder disappears during refetch
- **THEN** confirmation cannot silently submit that stale destination or substitute another

#### Scenario: Errors and cancellation are visible

- **WHEN** submission is rejected or the member cancels advanced selection
- **THEN** the UI shows a retryable error or returns to Seerr defaults respectively

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
