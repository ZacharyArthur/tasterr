## MODIFIED Requirements

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

## ADDED Requirements

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
