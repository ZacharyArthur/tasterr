## MODIFIED Requirements

### Requirement: Plex PIN login flow
The system SHALL implement Plex PIN login. `POST /api/v1/auth/plex/pin` creates a
PIN at plex.tv (product `Tasterr`, a stable client identifier) and returns an
opaque poll handle plus the plex.tv approval URL. The handle is polled with a
same-origin-protected `POST /api/v1/auth/plex/pin/poll` carrying
`{pin_id: <handle>}` in the body; it reports pending until the PIN is claimed.
Once claimed, the backend SHALL exchange the Plex auth token at Seerr
`/api/v1/auth/plex`, upsert the user, mint a Tasterr session, set the session
cookie, and return the user. The Plex auth token MUST never be returned to the
browser, and no `GET` endpoint SHALL mint a session — the poll is a POST guarded
by the same-origin check so a cross-site page cannot trigger a session-swapping
completion by top-level navigation.

#### Scenario: Poll while PIN is unclaimed
- **WHEN** the SPA posts the handle to `/auth/plex/pin/poll` before the user
  approves the PIN
- **THEN** the response is `{status: "pending"}` with no session cookie

#### Scenario: Poll after PIN is claimed
- **WHEN** the SPA posts the handle to `/auth/plex/pin/poll` after the user
  approves the PIN at plex.tv
- **THEN** the backend logs the user into Seerr, mints a session, sets the
  session cookie, and responds `{status: "ok"}` with the user

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

### Requirement: Login endpoints are hardened
Mutating auth endpoints SHALL enforce a same-origin check (`Sec-Fetch-Site` /
`Origin`). The login-start endpoints (`/auth/plex/pin`, `/auth/local`) SHALL be
tightly rate-limited in-process. The Plex PIN poll (`POST /auth/plex/pin/poll`)
SHALL enforce the same-origin check and SHALL be exempt from the tight login
rate limit — it polls every ~2s by design behind an unguessable, expiring,
single-use handle, and the same-origin check defeats the login-CSRF vector.
Auth failures are generic; credentials, tokens, and cookies MUST never appear in
logs.

#### Scenario: Cross-origin login attempt
- **WHEN** a POST to an auth endpoint arrives with cross-site origin evidence
- **THEN** it is rejected 403 before any Seerr call

#### Scenario: Login rate limit
- **WHEN** login attempts exceed the configured tight limit
- **THEN** further attempts receive 429 until the window relaxes
