# app-settings Specification

## Purpose
Separate environment-only deployment settings and secrets from editable household
preferences, with validated defaults, explicit overrides and safe public responses.

## Requirements

### Requirement: Settings load from environment only

Application deployment settings SHALL be loaded via a pydantic-settings model.
Secrets and connection values (`TMDB_API_KEY`, `SEERR_INTERNAL_URL`,
`SEERR_EXTERNAL_URL`, `SEERR_API_KEY`, `PLEX_SERVER_ID`, `JELLYFIN_INTERNAL_URL`,
`JELLYFIN_API_KEY`, `JELLYFIN_ALLOW_EMPTY_PASSWORD`, `TASTERR_SECRET_KEY`,
`DATABASE_PATH`, bind
host/port) SHALL come from the environment only — never from the database, never
editable via any API. The separate DB-backed runtime preferences SHALL contain no
deployment-setting, secret, token, cookie, credential, or internal/external URL
field.

#### Scenario: Settings populate from env
- **WHEN** the app starts with configuration set in environment variables
- **THEN** the deployment settings model reflects those values without reading
  any other source

#### Scenario: Missing integration secrets do not crash boot
- **WHEN** the app starts with `TMDB_API_KEY` or Seerr values unset
- **THEN** the app boots and reports the integration as unconfigured

#### Scenario: Runtime settings cannot override deployment settings
- **WHEN** runtime preferences are read from or written to the database
- **THEN** no deployment setting or secret value can be represented or changed

#### Scenario: Plex server id is validated
- **WHEN** `PLEX_SERVER_ID` is set to an empty value or one containing characters
  other than letters, digits, and hyphens, or longer than 64 characters
- **THEN** settings validation fails at boot instead of disabling the gate silently

### Requirement: PublicConfig projection contains no secrets

The system SHALL define a `PublicConfig` model as the only settings shape ever
serialized toward ordinary authenticated clients. It SHALL be built as an
explicit allowlist from integration-configured booleans, the resolved
allowlisted appearance enums, and the resolved metadata language code. A
regression test MUST assert that no secret field (API keys, internal URLs, secret
key, tokens, cookies, credentials) appears in the `PublicConfig` schema or its
serialized output, including when both deployment and runtime settings are fully
populated.

#### Scenario: Secret fields are absent by schema
- **WHEN** the `PublicConfig` regression test inspects the model schema and a
  serialized instance built from fully-populated deployment and runtime settings
- **THEN** no secret field name or secret value is present

#### Scenario: Appearance is constrained public data
- **WHEN** `PublicConfig` is serialized for an authenticated client
- **THEN** its appearance contains only the resolved theme and named accent enums

#### Scenario: Metadata language is a validated code
- **WHEN** `PublicConfig` is serialized
- **THEN** it carries the resolved metadata language as an `ll-CC` code and
  nothing else about catalog administration

### Requirement: PublicConfig is served via a session-gated endpoint

`GET /api/v1/config` SHALL return the `PublicConfig` projection to authenticated
clients only, using the shared session dependency. It remains the only settings
shape serialized toward non-admin clients and SHALL include the current resolved
appearance without exposing region/service/rail administration or secret
material.

#### Scenario: Authenticated client fetches config
- **WHEN** a client with a valid session requests `GET /api/v1/config`
- **THEN** it receives the `PublicConfig` projection with current appearance and
  no secret material

#### Scenario: Unauthenticated config request
- **WHEN** a client without a valid session requests `GET /api/v1/config`
- **THEN** the response is 401

### Requirement: Global runtime preferences are typed and persisted atomically

The system SHALL resolve one global runtime-settings document containing a
two-letter upper-case region, a TMDB metadata language in `ll-CC` form (two
lower-case letters, a hyphen, two upper-case letters), up to eight unique positive
TMDB service ids, a set of disabled server-known rail types, and allowlisted
theme/accent appearance. The document SHALL be stored as non-secret JSON in the
`settings` table under one global key. An absent or invalid stored document SHALL
resolve to documented code-owned defaults (`US`, `en-US`, no selected services,
all rail types enabled, and the default dark appearance); an existing document
without a language SHALL resolve to `en-US` without migration. Saving SHALL
validate and replace the complete document atomically; invalid input SHALL leave
the previous value unchanged.

#### Scenario: Fresh database resolves defaults
- **WHEN** no global settings row exists
- **THEN** the application resolves the documented defaults without requiring a
  bootstrap write

#### Scenario: Valid document round-trips
- **WHEN** an admin saves a valid complete runtime-settings document
- **THEN** subsequent requests resolve exactly that document from the global row

#### Scenario: Invalid replacement is atomic
- **WHEN** an admin submits an invalid region, language, service id, rail type,
  theme, or accent
- **THEN** validation rejects the request and the previously stored document is
  unchanged

#### Scenario: Existing document gains the default language
- **WHEN** a stored document predates the language field
- **THEN** the language resolves to `en-US` and every other value is unchanged

#### Scenario: Invalid stored JSON fails to safe defaults
- **WHEN** the global row cannot be parsed as the typed runtime document
- **THEN** the application uses the documented defaults and does not expose the
  stored value in a response or log

### Requirement: Admin settings API is default-deny and mutation-hardened

`GET /api/v1/settings` SHALL return the resolved runtime document and the
server-owned rail-type ids/labels; `PUT /api/v1/settings` SHALL accept one complete
runtime document and return the saved result. Both endpoints SHALL require the
shared admin dependency and explicit secret-free request/response models. The PUT
SHALL require the same-origin CSRF dependency and a bounded admin-mutation rate
limit. A normal authenticated client SHALL never receive or mutate admin settings.

#### Scenario: Admin reads resolved settings
- **WHEN** a Seerr-derived admin requests `GET /api/v1/settings`
- **THEN** they receive the resolved non-secret document and known rail-type
  descriptors

#### Scenario: Admin replaces settings
- **WHEN** an admin sends a valid same-origin `PUT /api/v1/settings`
- **THEN** the document is saved atomically and the response returns the saved
  resolved value

#### Scenario: Non-admin is forbidden
- **WHEN** an authenticated non-admin calls either settings endpoint
- **THEN** the response is 403 and no settings data is returned or changed

#### Scenario: Cross-origin or rate-limited save is rejected
- **WHEN** a settings mutation is cross-origin or exceeds the admin-mutation
  bucket
- **THEN** it is rejected before any database write

### Requirement: Admin catalog choices and connection tests stay behind clients

`GET /api/v1/regions` SHALL return typed TMDB watch-provider regions and `GET
/api/v1/services?region=` SHALL return the de-duplicated, display-priority-ordered
union of movie and TV flatrate providers for a validated two-letter region.
`POST /api/v1/connection-test` SHALL accept only `tmdb`, `seerr`, `plex`, or
`jellyfin` and probe the already configured integration. All three SHALL require
the admin dependency; the POST SHALL also require same-origin and admin-mutation
rate limiting. Outbound work SHALL occur only in `clients/`, use typed upstream
models/timeouts, and return explicit responses with generic failures that
disclose no credentials, internal URL, upstream body, or upstream headers.

The `plex` and `jellyfin` tests SHALL use only the calling admin's own linked
account, because Tasterr holds no server-wide Plex credential and the Jellyfin API
key is used only for reads scoped to a linked user:

- `plex`: when Plex is not configured, fail with "Plex is not configured".
  When the admin has no usable Plex link, fail with "Link Plex on your Account
  page to test it" and make no upstream call. Otherwise read the admin's Plex
  account and run the existing bounded server discovery (pinned to
  `PLEX_SERVER_ID` when set) under a ten-second deadline: succeed when at least
  one server connection is verified, fail with "Plex.tv works, but no Plex server
  was reachable" when none is, and fail generically on a plex.tv refusal, outage,
  or deadline.
- `jellyfin`: when Jellyfin is unconfigured, fail with "Jellyfin is not
  configured". When the admin has a Jellyfin link, read that user with the API
  key: succeed when it is returned, and fail generically otherwise. When the admin
  has no Jellyfin link, read Jellyfin's unauthenticated public server info without
  the API key: when it answers, fail with "Jellyfin is reachable. Link your
  Jellyfin account to verify the API key", and fail generically otherwise.

These details are fixed strings and SHALL NOT include server names, ids,
connection coordinates, or account names.

#### Scenario: Admin lists region services
- **WHEN** an admin requests services for a valid region
- **THEN** the response contains each movie/TV provider once in TMDB display order

#### Scenario: Invalid region is rejected before outbound work
- **WHEN** a region query is not a two-letter code
- **THEN** input validation rejects it and no TMDB call occurs

#### Scenario: Configured connection succeeds
- **WHEN** an admin tests a configured reachable integration
- **THEN** the response identifies the target and reports success without any
  secret or connection coordinate

#### Scenario: Connection failure is generic and contained
- **WHEN** the selected integration is unconfigured, unreachable, or rejects the
  probe
- **THEN** the response reports a failed result with a fixed, secret-free detail
  and ordinary browsing remains available

#### Scenario: Plex test needs the admin's Plex link
- **WHEN** an admin without a Plex link tests Plex
- **THEN** the response asks them to link Plex and no Plex call is made

#### Scenario: Pinned Plex server unreachable
- **WHEN** an admin with a Plex link tests Plex while `PLEX_SERVER_ID` names a
  server with no reachable connection
- **THEN** the response reports that plex.tv works but no Plex server was
  reachable

#### Scenario: Jellyfin key verified through the admin's link
- **WHEN** an admin with a Jellyfin link tests Jellyfin and the key can read that
  user
- **THEN** the response reports success

#### Scenario: Jellyfin reachable without a link
- **WHEN** an admin without a Jellyfin link tests a reachable Jellyfin
- **THEN** the response is not ok, says Jellyfin is reachable, asks them to link
  Jellyfin to verify the key, and the API key was not sent

### Requirement: Forwarded-header trust is env-only and narrowly validated

The deployment settings SHALL expose `TASTERR_FORWARDED_ALLOW_IPS` as an env-only,
comma-separated allowlist of literal proxy-peer IP addresses or CIDR networks. It
SHALL default to loopback only. Empty entries, hostnames, URLs, malformed IP/CIDR
values, and wildcard trust (`*`) MUST fail settings validation rather than broaden
trust. The normalized allowlist SHALL be passed only to the production server and
MUST NOT be stored in the database, editable through an API, or included in
`PublicConfig`.

#### Scenario: Direct deployment gets a narrow default
- **WHEN** `TASTERR_FORWARDED_ALLOW_IPS` is unset
- **THEN** settings trust forwarding headers from loopback only

#### Scenario: Explicit proxy peers are accepted
- **WHEN** the env value contains valid literal addresses and narrow CIDR networks
- **THEN** settings expose their normalized values to the production server

#### Scenario: Unsafe trust input fails closed
- **WHEN** the env value contains `*`, a hostname, URL, empty item, or malformed
  address/network
- **THEN** application settings validation fails and no broader forwarding trust is
  applied

#### Scenario: Proxy trust never reaches clients or runtime preferences
- **WHEN** deployment and runtime settings are fully populated and their public/API
  projections are inspected
- **THEN** the trusted-proxy allowlist appears in neither `PublicConfig` nor any
  database-backed runtime-settings shape

### Requirement: V2 rail capabilities are independently admin-toggleable

The server-owned rail type registry SHALL add `continue-watching`,
`unexpected-picks`, and `household-blend` with the user-facing labels **Continue
Watching**, **Picks You Wouldn't Usually Watch**, and **Something for Everyone
Tonight**. Each type SHALL be absent from the default disabled set and therefore
enabled for existing/fresh settings until an admin disables it. Disablement SHALL
gate the corresponding provider/member/blend work before any Plex, Jellyfin,
profile, or catalog fetch. Existing stored settings SHALL remain valid without a
migration or bootstrap rewrite.

#### Scenario: Existing settings enable new types by default

- **WHEN** an existing runtime document predates the v2 enum members
- **THEN** all three v2 types are enabled because none is in its disabled set

#### Scenario: Admin can disable one V2 rail only

- **WHEN** an admin saves `continue-watching` in the disabled set
- **THEN** Continue Watching performs no Plex or Jellyfin work while unexpected
  picks, household blend, and all other enabled rail types remain available

#### Scenario: Settings API owns V2 descriptors

- **WHEN** an admin reads settings
- **THEN** the returned rail descriptors include the exact three v2 ids/labels and
  no secret/capability state

### Requirement: Discovery preferences with explicit environment overrides

The household runtime document SHALL include `hide_library_items` (false by default), `hide_watched_items` (true by default), and `excluded_service_ids` (empty by default, at most eight unique positive IDs). Existing documents SHALL gain those defaults without migration. Optional environment variables `TASTERR_HIDE_LIBRARY_ITEMS`, `TASTERR_HIDE_WATCHED_ITEMS`, and `TASTERR_EXCLUDED_SERVICE_IDS` SHALL override those preferences only when explicitly set; false and the empty JSON array SHALL be valid explicit overrides. Invalid environment values SHALL fail validation. Admin GET/PUT SHALL return effective values and allowlisted lock metadata; saving SHALL preserve stored preferences beneath locks. PublicConfig SHALL remain unchanged.

#### Scenario: Missing fields preserve default browsing
- **WHEN** an existing or fresh settings document has no exclusion fields
- **THEN** library hiding and service exclusions resolve disabled and watched hiding resolves enabled

#### Scenario: Explicit overrides include false and empty
- **WHEN** environment values explicitly disable library or watched hiding or provide `[]`
- **THEN** they override non-default stored preferences and appear locked to the admin

#### Scenario: Saving locked controls preserves stored preferences
- **WHEN** an admin saves other settings while overrides are set
- **THEN** persisted exclusion preferences retain their underlying values and responses show effective overridden values

#### Scenario: Invalid service selections are rejected
- **WHEN** API or environment input contains duplicate, nonpositive, or more than eight excluded IDs
- **THEN** validation rejects it
- **AND** excluded IDs must be actual integers; booleans, numeric strings and floating-point numbers are rejected

#### Scenario: Explicit null or empty environment values are rejected
- **WHEN** an exclusion override is explicitly supplied as JSON `null` or an empty string
- **THEN** startup validation rejects it rather than treating it as unset

### Requirement: Exclusion controls follow region and explain precedence

The admin screen SHALL provide labelled library hiding, labelled watched-title hiding ("Hide titles members have watched", explaining that each member's own watched titles are hidden from their discovery and that Not interested always hides), and a separate excluded-service selector using regional service options, visible environment locks, best-effort semantics, and an explanation that exclusions win over inclusion. Changing region SHALL clear editable exclusions while retaining environment-controlled IDs for evaluation in the new region.

#### Scenario: Watched hiding control reflects its lock
- **WHEN** `TASTERR_HIDE_WATCHED_ITEMS` is set and an admin opens Settings
- **THEN** the watched-title hiding control shows the effective value read-only with the environment explanation

#### Scenario: Region changes clear editable exclusions
- **WHEN** an admin changes region without a service-exclusion override
- **THEN** the draft clears excluded service IDs

#### Scenario: Region changes retain locked exclusions
- **WHEN** an admin changes region while service exclusions are environment-controlled
- **THEN** those IDs remain fixed and are evaluated in the new region

#### Scenario: Missing regional services remain removable
- **WHEN** a saved exclusion ID is missing from the regional options or those options fail to load
- **THEN** an editable ID-labelled control allows its removal, even at the eight-service limit, while environment-controlled exclusions remain locked

### Requirement: Admin metadata language choices

`GET /api/v1/languages` SHALL require the admin dependency and return TMDB's
primary translations as validated `ll-CC` codes, deduplicated and sorted, read
through `clients/` with the catalog's bounded stale-on-error caching. Codes that
fail validation SHALL be dropped. When TMDB is unconfigured or unavailable with
nothing cached, it SHALL return the generic catalog-unavailable response. The
Settings screen SHALL offer the language beside the region, labelled with the
browser's own language display names and the code, and SHALL always include the
currently saved language even if TMDB omits it. Saving a language is accepted
whenever the code is well-formed; it is not checked against TMDB at save time.

#### Scenario: Admin picks Spanish
- **WHEN** an admin selects `es-ES` and saves settings
- **THEN** the runtime document stores `es-ES` and subsequent display reads use it

#### Scenario: Malformed upstream codes are dropped
- **WHEN** TMDB's list contains an entry that is not `ll-CC`
- **THEN** that entry is omitted from the response

#### Scenario: Members cannot list languages
- **WHEN** a non-admin requests `/api/v1/languages`
- **THEN** the response is 403 and no TMDB call is made

### Requirement: Watch-history initial window is environment-configured

The optional environment variable `TASTERR_WATCH_HISTORY_DAYS` SHALL set the
initial watch-history window in days for a link's first Plex or Jellyfin
history sync: an integer from 1 to 3650, defaulting to 365 when unset. Valid
decimal strings from the environment (for example `730`) SHALL be accepted. A
value that is not an integer in that range, including explicit JSON `null`, an
empty string, a fractional number, or a boolean, SHALL fail boot validation. Changing it SHALL
affect only future first syncs; it SHALL NOT clear any watermark or trigger a
re-import. It SHALL NOT appear in `PublicConfig` or the runtime document.

#### Scenario: Default window is one year

- **WHEN** `TASTERR_WATCH_HISTORY_DAYS` is unset
- **THEN** first Plex and Jellyfin syncs read up to 365 days back

#### Scenario: Environment value is accepted

- **WHEN** `TASTERR_WATCH_HISTORY_DAYS=730` is set in the environment
- **THEN** boot succeeds and first syncs read up to 730 days back

#### Scenario: Out-of-range value fails boot

- **WHEN** `TASTERR_WATCH_HISTORY_DAYS` is `0`, `3651`, `1.5`, `null`, or empty
- **THEN** startup validation fails rather than using a default

#### Scenario: Change applies to future first syncs only

- **WHEN** an operator raises the value and restarts
- **THEN** existing links keep syncing from their watermark, and a link whose
  sync timestamps are cleared by reset reads the new window

### Requirement: Admins choose which sign-in methods are offered

The household runtime document SHALL include `disabled_sign_in_methods`, a
unique subset of `plex`, `jellyfin`, and `seerr`, empty by default, so existing
documents remain valid without migration and offer every configured method. The
optional environment variable `TASTERR_SIGN_IN_METHODS` SHALL, when set, be a
JSON array of one to three unique known method names that are the only offered
methods, overriding and locking the stored value. An empty array, JSON `null`,
an empty string, unknown names, or duplicates SHALL fail boot validation.

Admin `GET /api/v1/settings` SHALL return the effective offered methods, whether
they are locked, which methods are configured, and `sign_in_link_counts`: for
each distinct set of configured sign-in providers (`plex`, `jellyfin`, `seerr`;
link-only providers are ignored) that members have linked, the number of
members with exactly that set. It SHALL contain counts only, never member
identities. Admin `PUT /api/v1/settings` SHALL refuse with 409 and a fixed message
when, after the save, the saving admin would have no linked, configured provider
that is offered; the stored document SHALL then be unchanged. While locked, a
submitted value SHALL be ignored and the stored value preserved, as with other
locked preferences.

The Settings screen SHALL show one checkbox per method. A method that is not
configured SHALL be shown disabled and labelled as not configured. While locked,
all checkboxes SHALL be read-only with an explanation naming the environment
variable. Before saving, the screen SHALL show how many members would have no
offered method, computed from `sign_in_link_counts`. Unchecking every configured
method SHALL be prevented in the UI as well as by the save guard.

#### Scenario: Existing settings offer everything

- **WHEN** a stored document predates `disabled_sign_in_methods`
- **THEN** every configured method is offered

#### Scenario: Admin offers only Jellyfin

- **WHEN** an admin with a Jellyfin link unchecks Plex and Seerr and saves
- **THEN** the save succeeds and `/auth/methods` reports only Jellyfin

#### Scenario: Admin cannot lock themselves out

- **WHEN** an admin whose only links are Plex and Seerr saves with only Jellyfin
  offered
- **THEN** the response is 409, nothing is stored, and Plex and Seerr stay offered

#### Scenario: Stranded members are previewed

- **WHEN** an admin unchecks Plex and two members have only a Plex link
- **THEN** the screen states that two members would have no way to sign in before
  the admin saves

#### Scenario: Environment lock overrides and recovers

- **WHEN** `TASTERR_SIGN_IN_METHODS=["plex"]` is set and the stored document
  disables Plex
- **THEN** only Plex is offered, the checkboxes are read-only, and the stored
  value is preserved underneath

#### Scenario: Invalid environment value fails boot

- **WHEN** `TASTERR_SIGN_IN_METHODS` is `[]`, `null`, empty, or names an unknown
  method
- **THEN** startup validation fails rather than treating it as unset

### Requirement: Admin Seerr integration summary

`GET /api/v1/integrations` SHALL require the admin dependency, perform no
mutation, and return: whether Seerr is configured; Seerr's media server as one
of `plex`, `jellyfin`, `emby`, `none`, or `unknown`; the three Seerr login method
booleans as derived in `account-linking`, each reported as `true`, `false`, or
`null` for unknown; whether `PLEX_SERVER_ID` is set (a boolean, never the id);
and whether Jellyfin is configured. It SHALL return no URL, key, server id,
server name, or upstream body, and a Seerr outage SHALL yield `unknown`/`null`
values rather than an error.

The Settings screen's Connections section SHALL render this summary and SHALL
show a fixed warning for each mismatch that applies:

- Plex sign-in depends on Seerr (`PLEX_SERVER_ID` unset) but Seerr is known to
  refuse Plex login: Plex sign-in and Plex linking will fail; set
  `PLEX_SERVER_ID`.
- Jellyfin is configured and Seerr is known to refuse Jellyfin login: members who
  only use Jellyfin need a Seerr local account (or a Plex link, when Seerr accepts
  Plex) before they can request.
- Additionally, Seerr is known to refuse local login: such members cannot request
  at all unless they link Plex.

Unknown values SHALL produce no warning.

#### Scenario: Plex-backed Seerr with Jellyfin configured

- **WHEN** an admin opens Settings with Jellyfin configured and Seerr reporting a
  Plex media server and local login enabled
- **THEN** the summary shows media server Plex and the Jellyfin-only warning
  pointing to Seerr local accounts

#### Scenario: Plex sign-in would fail

- **WHEN** `PLEX_SERVER_ID` is unset and Seerr reports a Jellyfin media server
- **THEN** the summary warns that Plex sign-in and linking will fail and names
  `PLEX_SERVER_ID` as the fix

#### Scenario: Seerr outage yields unknown without warnings

- **WHEN** Seerr cannot be reached and no value is cached
- **THEN** the endpoint returns 200 with media server `unknown`, null login
  methods, and the screen shows no mismatch warning

#### Scenario: Members cannot read the summary

- **WHEN** a non-admin member requests `/api/v1/integrations`
- **THEN** the response is 403 and no Seerr call is made
