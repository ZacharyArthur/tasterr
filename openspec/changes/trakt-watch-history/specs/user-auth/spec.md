## MODIFIED Requirements

### Requirement: Upstream session material is protected at rest

Upstream credentials SHALL be stored only on the owning user's linked-account
row, never on Tasterr session rows, and never sent to the browser. The Seerr
session cookie (Seerr link) and the Plex account token (Plex link) SHALL each be
stored encrypted with Fernet keyed from `TASTERR_SECRET_KEY`. The Seerr cookie
MAY be decrypted only to create the member's own Seerr requests. The Plex token
MAY be decrypted only for silent Seerr re-authentication, Seerr linking with the
`plex` method, admin and display identity checks, or the owning user's bounded Plex account/resource/PMS reads and
history task. The Trakt token set (Trakt link) SHALL be stored encrypted the
same way and MAY be decrypted only for the owning user's Trakt history task,
token refresh, and best-effort revocation on unlink or account deletion.
Credentials SHALL survive logout and session expiry and SHALL be
deleted when their link is unlinked or the user is deleted. Plex resource access
tokens discovered for PMS communication SHALL be call-local and SHALL NOT be
persisted.

#### Scenario: No plaintext Plex token at rest

- **WHEN** a Plex sign-in completes and the linked-account rows are inspected
- **THEN** the Plex token and Seerr cookie columns hold only Fernet ciphertext,
  and the session row holds neither

#### Scenario: No plaintext Trakt token at rest

- **WHEN** a Trakt link completes and the linked-account row is inspected
- **THEN** its credential column holds only Fernet ciphertext and no session row
  holds a Trakt token

#### Scenario: Local session has no Plex token

- **WHEN** Seerr local sign-in completes for a user without a Plex link
- **THEN** no Plex token is stored on any row and the user has no live Plex media
  capability

#### Scenario: Credentials outlive the session but not the link

- **WHEN** a member logs out and later unlinks Plex
- **THEN** the Plex token remains after logout and is deleted by the unlink

#### Scenario: Resource access token is transient

- **WHEN** a Plex-backed request discovers a PMS resource access token
- **THEN** that token is used only in outbound headers for the current bounded
  operation and is absent from SQLite and process caches afterward

#### Scenario: Upstream credentials never reach the client

- **WHEN** any auth, account, home, household, recommendation, or Plex-degraded
  endpoint responds
- **THEN** the body and headers contain no Seerr cookie, Plex account/resource
  token, server connection, or raw upstream body

