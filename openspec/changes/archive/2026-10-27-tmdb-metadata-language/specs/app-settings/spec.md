## MODIFIED Requirements

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

## ADDED Requirements

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
