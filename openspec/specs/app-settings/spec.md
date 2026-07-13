# app-settings Specification

## Purpose
TBD - created by archiving change m0-scaffold. Update Purpose after archive.
## Requirements
### Requirement: Settings load from environment only

Application deployment settings SHALL be loaded via a pydantic-settings model.
Secrets and connection values (`TMDB_API_KEY`, `SEERR_INTERNAL_URL`,
`SEERR_EXTERNAL_URL`, `SEERR_API_KEY`, `TASTERR_SECRET_KEY`, `DATABASE_PATH`, bind
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

### Requirement: PublicConfig projection contains no secrets

The system SHALL define a `PublicConfig` model as the only settings shape ever
serialized toward ordinary authenticated clients. It SHALL be built as an
explicit allowlist from integration-configured booleans and the resolved
allowlisted appearance enums. A regression test MUST assert that no secret field
(API keys, internal URLs, secret key, tokens, cookies, credentials) appears in
the `PublicConfig` schema or its serialized output, including when both deployment
and runtime settings are fully populated.

#### Scenario: Secret fields are absent by schema
- **WHEN** the `PublicConfig` regression test inspects the model schema and a
  serialized instance built from fully-populated deployment and runtime settings
- **THEN** no secret field name or secret value is present

#### Scenario: Appearance is constrained public data
- **WHEN** `PublicConfig` is serialized for an authenticated client
- **THEN** its appearance contains only the resolved theme and named accent enums

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
two-letter upper-case region, up to eight unique positive TMDB service ids, a set
of disabled server-known rail types, and allowlisted theme/accent appearance.
The document SHALL be stored as non-secret JSON in the `settings` table under one
global key. An absent or invalid stored document SHALL resolve to documented
code-owned defaults (`US`, no selected services, all rail types enabled, and the
default dark appearance). Saving SHALL validate and replace the complete document
atomically; invalid input SHALL leave the previous value unchanged.

#### Scenario: Fresh database resolves defaults
- **WHEN** no global settings row exists
- **THEN** the application resolves the documented defaults without requiring a
  bootstrap write

#### Scenario: Valid document round-trips
- **WHEN** an admin saves a valid complete runtime-settings document
- **THEN** subsequent requests resolve exactly that document from the global row

#### Scenario: Invalid replacement is atomic
- **WHEN** an admin submits an invalid region, service id, rail type, theme, or
  accent
- **THEN** validation rejects the request and the previously stored document is
  unchanged

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
`POST /api/v1/connection-test` SHALL accept only `tmdb` or `seerr` and probe the
already configured integration. All three SHALL require the admin dependency;
the POST SHALL also require same-origin and admin-mutation rate limiting. Outbound
work SHALL occur only in `clients/`, use typed upstream models/timeouts, and return
explicit responses with generic failures that disclose no credentials, internal
URL, upstream body, or upstream headers.

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
- **THEN** the response reports a generic failed result and ordinary browsing
  remains available

