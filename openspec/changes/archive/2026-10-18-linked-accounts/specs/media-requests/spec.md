# media-requests Specification (delta)

## MODIFIED Requirements

### Requirement: Request a title as the member

`POST /api/v1/request` SHALL proxy `POST {SEERR_INTERNAL_URL}/api/v1/request`
using the **per-user Seerr session cookie** stored encrypted on the member's Seerr
link, so the request is attributed to that member in Seerr and subject
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
failure to record the signal SHALL NOT fail the request response. Seerr 202 SHALL
be treated as a failed no-op request, with no success availability or request
taste signal. Any explicit TV season list SHALL require freshly verified
partial-request support: disabled support returns 422 before creation;
unreadable settings return generic failure without creating a request.
This includes full explicit lists and Specials-only lists. Bare TV requests
SHALL retain the regular whole-series "all" body without a settings read.
A season list containing 0 SHALL additionally require freshly verified
Specials support: disabled support returns 422 before creation; an unreadable
setting returns generic failure without creating a request.

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
- **THEN** the backend calls Seerr with the cookie from that member's Seerr link and Seerr
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

#### Scenario: No seasons available is a failure

- **WHEN** Seerr returns 202 because no seasons remain to request
- **THEN** the response reports failure without success availability or a request taste signal

#### Scenario: Specials support is checked at submission

- **WHEN** a TV request includes 0 and Seerr Specials support is disabled or unreadable
- **THEN** creation is blocked with 422 for disabled support or generic failure for an unreadable setting

#### Scenario: Movie seasons rejected with Seerr unconfigured

- **WHEN** a movie request includes seasons while Seerr is unconfigured
- **THEN** the response is 422 without any upstream call

### Requirement: Invalid-session re-auth ladder

A member without a Seerr link, or whose stored Seerr cookie is absent or cannot be
decrypted, SHALL receive `re_auth_required` without any Seerr call. Otherwise the
backend SHALL recover from Seerr's `403` invalid-session rejection with a bounded
re-auth ladder, re-authenticating **at most once** per request (because `403` is
also Seerr's genuine permission-denied response). For a member with a **Plex
link**, the backend SHALL silently re-authenticate by decrypting the link's Plex
token and logging into Seerr again. When the token cannot be decrypted or Seerr
refuses the login, the response SHALL be `re_auth_required` so the member can
reconnect Seerr. Only when Seerr returns the linked Seerr account SHALL the backend persist the fresh cookie on the Seerr link and retry the
request once with it; when Seerr returns a different account, the cookie SHALL be
discarded and the response SHALL be `re_auth_required` without retrying. A second
`403` SHALL be treated as a genuine denial and surfaced as a generic failure. For a
member **without a Plex link**, the backend SHALL surface `re_auth_required` for
the SPA to offer reconnecting Seerr, without retrying.

#### Scenario: Plex member silently re-authenticates and retries

- **WHEN** a member with a Plex link gets `403` for a lapsed Seerr session
- **THEN** the backend re-authenticates with the Plex link's token, updates the
  Seerr link's cookie, and retries the request once

#### Scenario: Re-auth as a different Seerr account never retries

- **WHEN** a member's Seerr link is a local Seerr account and their Plex token
  logs into a different Seerr account during re-auth
- **THEN** the fresh cookie is discarded, nothing is persisted or retried, and
  the response is `re_auth_required`

#### Scenario: Failed silent re-auth asks the member to reconnect

- **WHEN** the Plex token cannot be decrypted or Seerr refuses it during re-auth
- **THEN** the response is `re_auth_required` and nothing is retried

#### Scenario: Persistent denial after re-auth is generic

- **WHEN** the retried request is still `403`
- **THEN** the response is a generic failure with no upstream body, and no further
  re-auth is attempted

#### Scenario: Local member is asked to re-login

- **WHEN** a member without a Plex link gets `403`
- **THEN** the response is `re_auth_required` and no silent re-auth is attempted

#### Scenario: Member without a Seerr link is asked to connect

- **WHEN** a member without a Seerr link requests a title while Seerr is configured
- **THEN** the response is `re_auth_required` and no Seerr call is made

### Requirement: Request destinations for a title

GET /api/v1/{type}/{id}/destinations SHALL return a secret-free options envelope
containing current per-media standard/4K request capabilities, advanced capability, and
permitted destinations, plus can_request_4k_default indicating permission and a
configured default 4K server. TV discovery SHALL also return
can_request_partial, true only when Seerr public settings explicitly enable
partialRequestsEnabled, and can_request_specials, true only when both partial
requesting and enableSpecialEpisodes are explicitly enabled. A failed settings read SHALL disable season selection and Specials and preserve
otherwise successful capabilities and destinations. Movie and unconfigured
discovery SHALL return can_request_partial=false and can_request_specials=false. Without a default, only advanced members with a configured
4K destination SHALL have 4K capability. The validated type selects Radarr or Sonarr;
the bounded id preserves route consistency and does not choose dispatch. Discovery SHALL
require a session and use the global key for server-derived user permissions and
household service metadata. Destination metadata SHALL be exposed only to members with
advanced capability, and only for request variants they can request. The member's
permissions SHALL be read for the Seerr account on their Seerr link; a member
without a Seerr link SHALL get unavailable capabilities and an empty list with no
Seerr call. Each entry SHALL
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

#### Scenario: Specials capability follows public settings

- **WHEN** TV discovery succeeds and Seerr public settings enable partial requests and Specials
- **THEN** can_request_partial and can_request_specials are true and no other public settings are exposed

#### Scenario: Specials settings failure preserves ordinary requesting

- **WHEN** TV permissions and destinations succeed but public settings fail
- **THEN** can_request_partial and can_request_specials are false while ordinary capabilities and destinations remain available

#### Scenario: Member without a Seerr link

- **WHEN** a member without a Seerr link requests destinations for a title
- **THEN** capabilities are unavailable, the list is empty, and no Seerr call is made

## ADDED Requirements

### Requirement: Request control offers to connect Seerr

When a request returns `re_auth_required`, the request control SHALL open an
inline "Connect Seerr" dialog offering the same Seerr link methods as the account
page. A successful link SHALL retry the original request (same variant,
destination, and seasons) once. Cancel SHALL close the dialog without requesting.
The dialog SHALL follow the existing dialog focus and keyboard rules.

#### Scenario: Reconnect then retry

- **WHEN** a member reconnects Seerr from the dialog
- **THEN** the original request is retried once with the same selection

#### Scenario: Cancel requests nothing

- **WHEN** the member cancels the dialog
- **THEN** no link or request is made and the control returns to its prior state
