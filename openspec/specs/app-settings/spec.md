# app-settings Specification

## Purpose
TBD - created by archiving change m0-scaffold. Update Purpose after archive.
## Requirements
### Requirement: Settings load from environment only
Application settings SHALL be loaded via a pydantic-settings model. Secrets and
connection values (`TMDB_API_KEY`, `SEERR_INTERNAL_URL`, `SEERR_EXTERNAL_URL`,
`SEERR_API_KEY`, `TASTERR_SECRET_KEY`, `DATABASE_PATH`, bind host/port) SHALL come
from the environment only — never from the database, never editable via any API.

#### Scenario: Settings populate from env
- **WHEN** the app starts with configuration set in environment variables
- **THEN** the settings model reflects those values without reading any other source

#### Scenario: Missing integration secrets do not crash boot
- **WHEN** the app starts with `TMDB_API_KEY` or Seerr values unset
- **THEN** the app boots and reports the integration as unconfigured

### Requirement: PublicConfig projection contains no secrets
The system SHALL define a `PublicConfig` model as the only settings shape ever
serialized toward the client. A regression test MUST assert that no secret field
(API keys, internal URLs, secret key, tokens) appears in the `PublicConfig` schema
or its serialized output.

#### Scenario: Secret fields are absent by schema
- **WHEN** the `PublicConfig` regression test inspects the model schema and a
  serialized instance built from fully-populated settings
- **THEN** no secret field name or secret value is present

