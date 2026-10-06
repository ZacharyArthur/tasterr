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

#### Scenario: No seasons available is a failure

- **WHEN** Seerr returns 202 because no seasons remain to request
- **THEN** the response reports failure without success availability or a request taste signal

#### Scenario: Specials support is checked at submission

- **WHEN** a TV request includes 0 and Seerr Specials support is disabled or unreadable
- **THEN** creation is blocked with 422 for disabled support or generic failure for an unreadable setting

#### Scenario: Movie seasons rejected with Seerr unconfigured

- **WHEN** a movie request includes seasons while Seerr is unconfigured
- **THEN** the response is 422 without any upstream call

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

#### Scenario: Specials capability follows public settings

- **WHEN** TV discovery succeeds and Seerr public settings enable partial requests and Specials
- **THEN** can_request_partial and can_request_specials are true and no other public settings are exposed

#### Scenario: Specials settings failure preserves ordinary requesting

- **WHEN** TV permissions and destinations succeed but public settings fail
- **THEN** can_request_partial and can_request_specials are false while ordinary capabilities and destinations remain available

### Requirement: TV season selection dialog

For a TV title with verified partial-request support and more than one
selectable season entry, activating
Request SHALL open a dialog listing selectable seasons, each with an on/off
toggle, plus an "All seasons" toggle, an OK action and a Cancel action.
Selectable seasons SHALL have episode_count > 0; Specials SHALL additionally
require can_request_specials=true. Regular selectable seasons SHALL start on
and enabled Specials off, matching Seerr 3.5.0's whole-series selection.
OK with that default choice SHALL send the same request body as a request
without the dialog; any other choice SHALL send the chosen season numbers.
OK SHALL be blocked while no season is chosen. Cancel and Escape SHALL close
only the dialog without requesting, and reopening SHALL restore the default
choice. Movies and titles with at most one selectable season SHALL keep the
one-step request; when Specials is the sole selectable season, that request
SHALL explicitly select season 0 instead of the whole series only while
partial requesting is enabled. Disabled or unverified partial-request support
SHALL skip the picker and preserve regular whole-series requests; Specials
requesting in this mode remains in Seerr. The dialog SHALL retain the Standard/4K variant chosen when it opened.
Confirmation SHALL recheck current partial-request support and request eligibility, including refreshed variant,
default destination and advanced selection capabilities, before submission.
The title detail page's own season list SHALL continue to
omit Specials. Nested dialogs SHALL give the innermost dialog Escape and Tab
regardless of mount or callback-update order; removing a lower trap SHALL NOT
move focus outside a remaining dialog.

#### Scenario: Dialog defaults

- **WHEN** a member activates Request on a TV title with several positive-episode seasons while partial requests and Specials are enabled
- **THEN** a dialog lists regular selectable seasons on and enabled Specials off, and nothing is submitted yet

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

- **WHEN** a member activates Request on a TV title with at most one selectable season entry
- **THEN** the request is submitted without a dialog

#### Scenario: Empty seasons are excluded consistently

- **WHEN** a title includes zero-episode seasons
- **THEN** they are absent from the picker, All seasons and default-equivalence calculation, while positive-episode future seasons remain selectable

#### Scenario: Disabled Specials are hidden

- **WHEN** Specials support is disabled or discovery cannot verify it
- **THEN** Specials are absent from the picker and no explicit season selection includes 0

#### Scenario: Nested traps keep focus and key ownership

- **WHEN** nested dialogs mount together, the outer Escape callback changes, or a lower trap closes
- **THEN** only the innermost handles Escape and Tab and focus stays in the remaining dialog

#### Scenario: Specials-only title requests directly

- **WHEN** partial requests and Specials are enabled and Specials is the sole selectable season
- **THEN** the one-step request sends seasons [0] rather than the whole-series body

#### Scenario: Refreshed capabilities block season confirmation

- **WHEN** variant, default or advanced destination eligibility disappears while the picker is open
- **THEN** confirming seasons sends no request and cannot bypass the refreshed submission guards

#### Scenario: Partial requests disabled or unverified

- **WHEN** partial-request support is disabled or cannot be verified
- **THEN** the picker is skipped, a bare regular whole-series request remains possible, and explicit season lists cannot be created

#### Scenario: Partial policy changes during selection

- **WHEN** partial-request support disappears while the picker is open
- **THEN** confirmation sends no request, including for the former default selection

#### Scenario: Picker retains its request variant

- **WHEN** the original Standard or 4K variant loses permission while the picker is open
- **THEN** confirmation is blocked and does not silently submit the other variant
