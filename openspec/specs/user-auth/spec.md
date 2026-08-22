# user-auth Specification

## Purpose
TBD - created by archiving change m1-auth. Update Purpose after archive.
## Requirements
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

### Requirement: Local Seerr login
`POST /api/v1/auth/local` SHALL forward the submitted email and password verbatim
to Seerr `/api/v1/auth/local`. Credentials MUST never be stored and never logged.
On Seerr success the same user upsert and session minting as the Plex flow apply;
on Seerr rejection the response is a generic 401 that does not reveal whether the
account exists.

#### Scenario: Valid local credentials
- **WHEN** a user submits credentials Seerr accepts
- **THEN** a Tasterr session is minted and the response contains the user and
  session cookie

#### Scenario: Invalid credentials stay generic
- **WHEN** a user submits credentials Seerr rejects
- **THEN** the response is 401 with a generic message, identical for wrong
  password and unknown account

### Requirement: User records mirror Seerr identity
Users SHALL be upserted at login keyed by their Seerr user id, storing display
name, avatar URL, and auth type (`plex` | `local`). `is_admin` SHALL be derived
from the Seerr permissions bitmask (ADMIN bit 2) at every login — never cached
across logins — and `last_login_at` updated.

#### Scenario: First login creates the user
- **WHEN** a Seerr user logs in for the first time
- **THEN** a user row is created with their Seerr id, display name, and admin flag

#### Scenario: Later login refreshes identity
- **WHEN** a user whose Seerr display name or admin status changed logs in again
- **THEN** the existing row is updated in place — no duplicate user is created

### Requirement: Tasterr session lifecycle
Sessions SHALL use a 256-bit random token delivered as an HttpOnly, `SameSite=Lax`
cookie, marked `Secure` when the request is HTTPS (respecting proxy forwarding
headers). Only the token's SHA-256 hash is stored. Sessions expire 30 days after
last activity (sliding). Every login mints a fresh token; validation of an
expired or unknown token fails with 401 and expired rows are deleted.

#### Scenario: Token is stored hashed only
- **WHEN** a session is minted
- **THEN** the database row contains the SHA-256 hash, and the raw token appears
  only in the Set-Cookie header

#### Scenario: Expired session is rejected
- **WHEN** a request presents a session token past its expiry
- **THEN** the request fails 401 and the session row is removed

#### Scenario: Activity slides expiry
- **WHEN** an authenticated request arrives on a valid session
- **THEN** the session's expiry window slides forward from recent activity

#### Scenario: Login never reuses a token
- **WHEN** a user logs in while already holding a session cookie
- **THEN** a brand-new token is minted (no session fixation)

### Requirement: Upstream session material is protected at rest
The Seerr session cookie obtained at login SHALL be stored only on the server-side
session row and never sent to the browser. The Plex auth token (Plex logins only)
SHALL be stored encrypted (Fernet keyed from `TASTERR_SECRET_KEY`) for M3's silent
re-auth; local logins store no Plex token.

#### Scenario: No plaintext Plex token at rest
- **WHEN** a Plex login completes and the session row is inspected
- **THEN** the Plex token column holds only Fernet ciphertext

#### Scenario: Upstream credentials never reach the client
- **WHEN** any auth endpoint responds
- **THEN** the body and headers contain no Seerr cookie and no Plex token

### Requirement: Current user endpoint and logout
`GET /api/v1/auth/me` SHALL return the current user (id, display name, avatar,
admin flag) from local state without calling Seerr, or 401 without a valid
session. `POST /api/v1/auth/logout` SHALL require the same-origin check and shared
loose authenticated-mutation rate limit, then delete the session row and clear the
cookie — revocation is immediate. A rate-limited logout SHALL return 429 without
revoking the session or altering the cookie.

#### Scenario: Me with a valid session
- **WHEN** an authenticated client requests `/auth/me`
- **THEN** it receives the current user without any outbound Seerr call

#### Scenario: Logout revokes server-side
- **WHEN** a client logs out and then replays the old session cookie
- **THEN** the replayed request fails 401

#### Scenario: Logout is rate-limited before revocation
- **WHEN** an authenticated user has exhausted the shared mutation bucket and posts
  logout
- **THEN** the response is 429 and the existing session remains valid

### Requirement: Session and admin dependencies are default-deny
A shared session dependency SHALL gate authenticated routes (401 when absent or
invalid) and a shared admin dependency SHALL gate admin routes (403 for
authenticated non-admins). All future session/admin routes MUST use these
dependencies rather than re-implementing checks.

#### Scenario: Unauthenticated request to a gated route
- **WHEN** a request without a valid session hits a session-gated route
- **THEN** the response is 401

#### Scenario: Non-admin hits an admin route
- **WHEN** an authenticated non-admin calls a route with the admin dependency
- **THEN** the response is 403

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

### Requirement: Auth degrades when Seerr is unavailable or unconfigured
When Seerr settings or `TASTERR_SECRET_KEY` are unset, login endpoints SHALL
return 503 with a generic "authentication unavailable" error. When Seerr is
unreachable or errors, login fails with a generic upstream-unavailable error that
carries no upstream body or internal URL. The rest of the app (health, SPA
serving) keeps working.

#### Scenario: Auth not configured
- **WHEN** login is attempted while Seerr or the secret key is unconfigured
- **THEN** the response is 503 with a generic message and no configuration detail

#### Scenario: Seerr down during login
- **WHEN** Seerr times out or returns a server error during login
- **THEN** the client receives a generic error, and `/api/v1/health` still responds

### Requirement: Outbound auth calls are bounded and typed
All plex.tv and Seerr calls SHALL live in `clients/`, carry explicit timeouts,
parse responses into typed models (unknown fields dropped), and never forward
browser headers upstream or upstream headers/bodies downstream.

#### Scenario: Unexpected upstream response shape
- **WHEN** Seerr or plex.tv returns an unexpected payload
- **THEN** the client raises a typed error and the API responds with a generic
  error, never the raw upstream body

### Requirement: SPA login experience

The login screen SHALL offer both paths: "Sign in with Plex" and a local
email/password form. Plex sign-in SHALL open a script-created popup context
directly from the user's activation, sever that context's access to its opener
before navigating to the backend-provided Plex approval URL, and retain only an
in-memory handle for best-effort cleanup. The SPA SHALL poll until completion and,
when the browser still exposes the script-created context, close it and request
focus for Tasterr after success.
A blocked, manually closed, or browser-severed context SHALL NOT block polling or
successful login, and the user SHALL be able to reopen a new protected approval
context. On success the SPA SHALL switch to the authenticated state without a full
reload; a logout control SHALL end the session and return to the login screen.
Failures SHALL surface as generic, human-readable messages. On each confirmed
session transition — successful local login, successful Plex PIN completion,
successful logout, or `auth/me` resolving to a different user — the SPA SHALL
invalidate prior-session mutation callbacks, cancel in-flight TanStack Query
requests before removing cached query data, and publish the confirmed user or
signed-out state only after that boundary completes. Failed login or logout
attempts SHALL preserve the current confirmed auth state and query cache.

#### Scenario: Plex login from the SPA

- **WHEN** the user starts Plex login, approves on plex.tv, and the browser retains
  the script-created context handle
- **THEN** the SPA detects completion via polling, closes that context, requests
  focus for Tasterr, and shows the authenticated app

#### Scenario: Plex approval cannot control Tasterr

- **WHEN** Tasterr navigates its script-created context to the Plex approval URL
- **THEN** the child context has no `opener` reference to the Tasterr tab

#### Scenario: Approval context is unavailable

- **WHEN** a popup blocker, manual close, or browser opener policy makes the
  approval context unavailable
- **THEN** polling and successful login remain operable, and the reopen action can
  create and track a replacement context

#### Scenario: Local login from the SPA

- **WHEN** the user submits email and password accepted by Seerr
- **THEN** the SPA shows the authenticated app

#### Scenario: Logout from the SPA

- **WHEN** the user activates logout
- **THEN** the SPA returns to the login screen and the session is revoked

#### Scenario: Shared browser changes household user

- **WHEN** one household user logs out and another completes local or Plex login
- **THEN** no cached response from the prior user renders while the new user's
  responses are loading

#### Scenario: Prior-session query completes late

- **WHEN** an in-flight query from the prior session completes after a confirmed
  session transition
- **THEN** its response does not repopulate the active query cache

#### Scenario: Current-user refresh detects a different identity

- **WHEN** `auth/me` refetches after the browser session cookie changes from one
  household user to another
- **THEN** the prior user's query data is removed before the new identity renders

#### Scenario: Prior-session mutation completes late

- **WHEN** a mutation from the prior session completes after a confirmed session
  transition
- **THEN** its callback does not alter the active session's UI or cached queries

#### Scenario: Auth transition fails

- **WHEN** login or logout fails before a new session state is confirmed
- **THEN** the SPA preserves the current confirmed auth state and cached data

### Requirement: Live Seerr contract tests
A pytest-marked live suite (excluded from `just check` and CI) SHALL validate the
Seerr auth contract against a real instance: Plex token login, local login,
user/permissions shape, and the invalid-session 403 behavior — recording the
Seerr version tested.

#### Scenario: Live suite validates the contract
- **WHEN** the live-marked tests run with real Seerr coordinates configured
- **THEN** they verify the auth endpoints' behavior and record the Seerr version

#### Scenario: Default test runs skip live tests
- **WHEN** `just check` runs
- **THEN** no live-marked test executes and no network access is attempted

### Requirement: Forwarding headers affect auth only from trusted peers

The production server SHALL honor forwarded client IP and scheme only when the
request's direct peer matches the validated trusted-proxy allowlist. A trusted
proxy's forwarded client IP SHALL key the tight login bucket, and its forwarded
`https` scheme SHALL cause session cookies to be marked `Secure`. Forwarding headers
from any untrusted peer MUST be ignored so a direct client cannot evade rate limits
or influence cookie security.

#### Scenario: Trusted HTTPS proxy sets effective client and Secure cookie
- **WHEN** an allowlisted proxy forwards a login with a client IP and `https` scheme
- **THEN** the forwarded client IP keys the login bucket and the minted session
  cookie carries `Secure`

#### Scenario: Untrusted forwarding headers are ignored
- **WHEN** a non-allowlisted peer supplies forwarded client IP or scheme headers
- **THEN** auth uses the socket peer and direct request scheme instead
