## MODIFIED Requirements

### Requirement: Upstream session material is protected at rest

The Seerr session cookie obtained at login SHALL be stored only on the server-side
session row and never sent to the browser. The Plex auth token (Plex logins only)
SHALL be stored encrypted with Fernet keyed from `TASTERR_SECRET_KEY` and MAY be
decrypted only for silent Seerr re-authentication or the authenticated caller's
bounded Plex account/resource/PMS reads and history task. Local logins SHALL store
no Plex token. Plex resource access tokens discovered for PMS communication SHALL
be call-local and SHALL NOT be persisted.

#### Scenario: No plaintext Plex token at rest

- **WHEN** a Plex login completes and the session row is inspected
- **THEN** the Plex token column holds only Fernet ciphertext

#### Scenario: Local session has no Plex token

- **WHEN** local Seerr login completes
- **THEN** its session has no Plex token and no live Plex media capability

#### Scenario: Resource access token is transient

- **WHEN** a Plex-backed request discovers a PMS resource access token
- **THEN** that token is used only in outbound headers for the current bounded
  operation and is absent from SQLite and process caches afterward

#### Scenario: Upstream credentials never reach the client

- **WHEN** any auth, home, household, recommendation, or Plex-degraded endpoint
  responds
- **THEN** the body and headers contain no Seerr cookie, Plex account/resource
  token, server connection, or raw upstream body
