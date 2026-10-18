# user-auth Specification (delta)

## MODIFIED Requirements

### Requirement: Plex PIN login flow
The system SHALL implement Plex PIN login. `POST /api/v1/auth/plex/pin` creates a
PIN at plex.tv (product `Tasterr`, a stable client identifier) and returns an
opaque poll handle plus the plex.tv approval URL. The handle is polled with a
same-origin-protected `POST /api/v1/auth/plex/pin/poll` carrying
`{pin_id: <handle>}` in the body; it reports pending until the PIN is claimed.
Once claimed, the backend SHALL validate the Plex token against the plex.tv
account endpoint, exchange it at Seerr `/api/v1/auth/plex`, resolve the Tasterr
user through linked accounts (see `account-linking`), mint a Tasterr session, set
the session cookie, and return the user. Seerr refusing the Plex account SHALL
fail sign-in with a generic 401 and SHALL create no user, link, or session. The
Plex auth token MUST never be returned to the browser, and no `GET` endpoint
SHALL mint a session — the poll is a POST guarded by the same-origin check so a
cross-site page cannot trigger a session-swapping completion by top-level
navigation.

#### Scenario: Poll while PIN is unclaimed
- **WHEN** the SPA posts the handle to `/auth/plex/pin/poll` before the user
  approves the PIN
- **THEN** the response is `{status: "pending"}` with no session cookie

#### Scenario: Poll after PIN is claimed
- **WHEN** the SPA posts the handle to `/auth/plex/pin/poll` after the user
  approves the PIN at plex.tv
- **THEN** the backend logs the user into Seerr, resolves their Tasterr user
  through linked accounts, mints a session, sets the session cookie, and
  responds `{status: "ok"}` with the user

#### Scenario: Seerr refuses the Plex account
- **WHEN** a claimed PIN's Plex account is rejected by Seerr
- **THEN** the response is a generic 401 and no user, linked account, or session
  is created

#### Scenario: Poll handle is opaque and single-use
- **WHEN** a login has completed for a handle, the handle has expired, or the
  handle never existed
- **THEN** polling it returns a generic 404 — handles are unguessable random
  values (≥128 bits), never the raw plex.tv PIN id

#### Scenario: Cross-site poll cannot swap a session
- **WHEN** a cross-site request (`Sec-Fetch-Site: cross-site` or a mismatched
  `Origin`) posts any handle to `/auth/plex/pin/poll`
- **THEN** the response is 403, issued before any plex.tv/Seerr call, handle
  consumption, session-cookie change, or session creation

#### Scenario: No GET endpoint mints a session
- **WHEN** a GET request is made to any Plex PIN completion path
- **THEN** no session is minted, no cookie is set, and no upstream auth call fires

### Requirement: Local Seerr login
`POST /api/v1/auth/local` SHALL forward the submitted email and password verbatim
to Seerr `/api/v1/auth/local`. Credentials MUST never be stored and never logged.
On Seerr success the user SHALL be resolved through linked accounts with the
Seerr account as the sign-in account, and a session minted as in the Plex flow;
on Seerr rejection the response is a generic 401 that does not reveal whether
the account exists.

#### Scenario: Valid local credentials
- **WHEN** a user submits credentials Seerr accepts
- **THEN** a Tasterr session is minted and the response contains the user and
  session cookie

#### Scenario: Invalid credentials stay generic
- **WHEN** a user submits credentials Seerr rejects
- **THEN** the response is 401 with a generic message, identical for wrong
  password and unknown account

### Requirement: Upstream session material is protected at rest

Upstream credentials SHALL be stored only on the owning user's linked-account
row, never on Tasterr session rows, and never sent to the browser. The Seerr
session cookie (Seerr link) and the Plex account token (Plex link) SHALL each be
stored encrypted with Fernet keyed from `TASTERR_SECRET_KEY`. The Seerr cookie
MAY be decrypted only to create the member's own Seerr requests. The Plex token
MAY be decrypted only for silent Seerr re-authentication, Seerr linking with the
`plex` method, admin and display identity checks, or the owning user's bounded Plex account/resource/PMS reads and
history task. Credentials SHALL survive logout and session expiry and SHALL be
deleted when their link is unlinked or the user is deleted. Plex resource access
tokens discovered for PMS communication SHALL be call-local and SHALL NOT be
persisted.

#### Scenario: No plaintext Plex token at rest

- **WHEN** a Plex sign-in completes and the linked-account rows are inspected
- **THEN** the Plex token and Seerr cookie columns hold only Fernet ciphertext,
  and the session row holds neither

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

### Requirement: Auth degrades when Seerr is unavailable or unconfigured
When Seerr settings or `TASTERR_SECRET_KEY` are unset, login endpoints SHALL
return 503 with a generic "authentication unavailable" error. When Seerr has an
outage (transport error, timeout, or HTTP 502, 503, or 504, as defined in
`account-linking`), login fails with a generic upstream-unavailable error that
carries no upstream body or internal URL; any other Seerr error is a refusal and
fails with the generic 401. The rest of the app (health, SPA
serving) keeps working.

#### Scenario: Auth not configured
- **WHEN** login is attempted while Seerr or the secret key is unconfigured
- **THEN** the response is 503 with a generic message and no configuration detail

#### Scenario: Seerr down during login
- **WHEN** Seerr times out, is unreachable, or returns 502, 503, or 504 during login
- **THEN** the client receives a generic error, and `/api/v1/health` still responds

## REMOVED Requirements

### Requirement: User records mirror Seerr identity
**Reason**: Superseded by `account-linking` — users are Tasterr-owned and Seerr is
one linked account among several.
**Migration**: Migration `0007` turns each `users.seerr_user_id` into a Seerr
linked account; admin and display identity are re-derived from links at sign-in.
