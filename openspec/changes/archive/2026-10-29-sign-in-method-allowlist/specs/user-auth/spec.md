## MODIFIED Requirements

### Requirement: Sign-in methods are advertised without secrets

`GET /api/v1/auth/methods` SHALL be unauthenticated by explicit decision (the
login screen needs it before a session exists) and SHALL return only booleans for
each sign-in method: `plex` (configured when `PLEX_SERVER_ID` is set or Seerr is
configured), `jellyfin` (configured when the Jellyfin URL and API key are set),
and `seerr` (configured when Seerr is configured), each also requiring
`TASTERR_SECRET_KEY`. A method SHALL be reported true only when it is configured
**and** offered by the admin sign-in allowlist (see `app-settings`). A method is
**available for sign-in** exactly when this endpoint reports it true; every rule
that refers to an available sign-in method uses this definition. The endpoint
SHALL NOT return URLs, server ids, keys, the allowlist itself, or any other
configuration, and SHALL perform no upstream call.

#### Scenario: Methods reflect configuration

- **WHEN** only `PLEX_SERVER_ID` and the secret key are configured
- **THEN** the response is `plex: true, jellyfin: false, seerr: false`

#### Scenario: Methods carry no configuration detail

- **WHEN** every integration is configured and the response is inspected
- **THEN** it contains only method booleans and no URL, id, or secret

#### Scenario: Allowlist hides a configured method

- **WHEN** Plex, Jellyfin, and Seerr are configured and the admin offers only
  Jellyfin
- **THEN** the response is `plex: false, jellyfin: true, seerr: false`, and the
  login screen shows only "Continue with Jellyfin"

#### Scenario: Hidden method is refused

- **WHEN** Plex is configured but not offered and a client calls the Plex sign-in
  PIN endpoint directly
- **THEN** the response is the generic 503 "authentication unavailable" and no
  plex.tv call is made
