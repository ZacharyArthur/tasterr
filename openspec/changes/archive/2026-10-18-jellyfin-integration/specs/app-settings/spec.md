# app-settings Specification (delta)

## MODIFIED Requirements

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
