# user-auth Specification (delta)

## MODIFIED Requirements

### Requirement: Plex PIN login flow
The system SHALL implement Plex PIN login. `POST /api/v1/auth/plex/pin` creates a
PIN at plex.tv (product `Tasterr`, a stable client identifier) and returns an
opaque poll handle plus the plex.tv approval URL. The handle is polled with a
same-origin-protected `POST /api/v1/auth/plex/pin/poll` carrying
`{pin_id: <handle>}` in the body; it reports pending until the PIN is claimed.
Plex sign-in SHALL be available when `PLEX_SERVER_ID` is set or Seerr is
configured. Once claimed, the backend SHALL validate the Plex token against the
plex.tv account endpoint and admit the account: when `PLEX_SERVER_ID` is set, only
if the account's plex.tv resources include that server (owner, shared, and Plex
Home users alike), checked on every sign-in; otherwise only if Seerr
`/api/v1/auth/plex` accepts the token. When Seerr is configured the backend SHALL
also attempt the Seerr exchange for auto-linking; with `PLEX_SERVER_ID` set, a
Seerr refusal SHALL NOT block sign-in, and a Seerr outage SHALL block only a
sign-in that would create a new user (see `account-linking`). An admitted account SHALL be
resolved to a Tasterr user through linked accounts (see `account-linking`), and
the backend SHALL mint a Tasterr session, set the session cookie, and return the
user. A refused account SHALL get a generic 401 with no user, link, or session
created; a server-access check that cannot complete SHALL fail closed with a
generic upstream error. The
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
- **THEN** the backend admits the account, resolves their Tasterr user
  through linked accounts, mints a session, sets the session cookie, and
  responds `{status: "ok"}` with the user

#### Scenario: Seerr refuses the Plex account
- **WHEN** `PLEX_SERVER_ID` is unset and Seerr rejects a claimed PIN's Plex account
- **THEN** the response is a generic 401 and no user, linked account, or session
  is created

#### Scenario: Account without server access is refused
- **WHEN** `PLEX_SERVER_ID` is set and a claimed PIN's account cannot see that
  server
- **THEN** the response is a generic 401 and no user, linked account, or session
  is created, even if Seerr would accept the account

#### Scenario: Existing link does not bypass the server gate
- **WHEN** a Plex account already linked to a user loses access to the
  configured server and signs in
- **THEN** sign-in is refused with a generic 401

#### Scenario: Seerr outage does not block a server-gated sign-in
- **WHEN** `PLEX_SERVER_ID` is set, the account can see that server, and Seerr
  refuses the token, or is down while the Plex account is already linked
- **THEN** sign-in succeeds without a Seerr auto-link

#### Scenario: Seerr outage blocks a first sign-in
- **WHEN** `PLEX_SERVER_ID` is set, Seerr is configured but down, and the Plex
  account is linked to no user
- **THEN** sign-in fails with the generic upstream error and no user is created

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

### Requirement: SPA login experience

The login screen SHALL offer exactly the sign-in methods `GET /api/v1/auth/methods`
reports as available, as a full-width stack of rounded pill buttons in the style
of common single-sign-on buttons, each with its service's mark as inline SVG and a
"Continue with …" label: "Continue with Plex" and "Continue with Seerr". A method
that needs credentials SHALL expand its email/password form in place when
activated. Plex sign-in SHALL attempt to open a script-created popup
context directly from the user's activation, sever that context's access to its
opener before navigating to the backend-provided Plex approval URL, and retain
only an in-memory handle for best-effort cleanup. The SPA SHALL poll until
completion and, when the browser still exposes the script-created context, close
it and request focus for Tasterr after success.
While a Plex PIN is pending, the SPA SHALL expose the backend-provided approval
URL through a link that opens a new context without opener or referrer access and
through a copy action. A blocked, manually closed, or browser-severed popup
context SHALL NOT block polling, successful login, or either recovery action.
Each completed copy attempt SHALL provide visible and assistive success or failure
feedback, a fallback copy attempt SHALL restore the user's prior focus, and
feedback from an ended approval flow SHALL NOT reappear.
On success the SPA SHALL switch to the authenticated state without a full reload;
a logout control SHALL end the session and return to the login screen. Failures
SHALL surface as generic, human-readable messages. On each confirmed session
transition — successful local login, successful Plex PIN completion, successful
logout, or `auth/me` resolving to a different user — the SPA SHALL invalidate
prior-session mutation callbacks, cancel in-flight TanStack Query requests before
removing cached query data, and publish the confirmed user or signed-out state
only after that boundary completes. Failed login or logout attempts SHALL preserve
the current confirmed auth state and query cache.

#### Scenario: Plex login from the SPA

- **WHEN** the user starts Plex login, approves on plex.tv, and the browser retains
  the script-created context handle
- **THEN** the SPA detects completion via polling, closes that context, requests
  focus for Tasterr, and shows the authenticated app

#### Scenario: Plex approval cannot control Tasterr

- **WHEN** Tasterr opens the backend-provided Plex approval URL in either the
  script-created popup or the durable recovery link
- **THEN** the approval context has no `opener` reference to the Tasterr tab

#### Scenario: Approval context is unavailable

- **WHEN** a popup blocker, manual close, or browser opener policy makes the
  script-created approval context unavailable
- **THEN** polling and successful login remain operable, and the protected
  approval link and copy action remain available for the pending PIN

#### Scenario: Approval URL copy succeeds repeatedly

- **WHEN** the user copies the pending approval URL one or more times
- **THEN** each successful attempt is announced visibly and to assistive
  technology, and any fallback copy operation restores prior focus

#### Scenario: Approval URL copy fails

- **WHEN** the browser rejects both supported copy mechanisms
- **THEN** the SPA announces a generic failure and leaves the protected approval
  link available

#### Scenario: Approval flow ends during copy

- **WHEN** a copy operation completes after its pending PIN has expired or ended
- **THEN** feedback from that obsolete approval flow does not reappear

#### Scenario: Only configured methods are offered

- **WHEN** the login screen loads on a deployment with `PLEX_SERVER_ID` set and
  Seerr unconfigured
- **THEN** only "Continue with Plex" is shown

#### Scenario: Credential form expands in place

- **WHEN** the user activates "Continue with Seerr"
- **THEN** its email/password form expands below the button without leaving the
  screen

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

### Requirement: Tasterr session lifecycle
Sessions SHALL use a 256-bit random token delivered as an HttpOnly, `SameSite=Lax`
cookie, marked `Secure` when the request is HTTPS (respecting proxy forwarding
headers). Only the token's SHA-256 hash is stored. Sessions expire 30 days after
last activity (sliding) and SHALL never outlive 90 days from creation, whatever
the activity, so every member signs in again at least every 90 days and the
sign-in gate and admin derivation re-run. Every login mints a fresh token; validation of an
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

#### Scenario: Absolute lifetime forces a fresh sign-in
- **WHEN** a session has been active continuously for 90 days since creation
- **THEN** the next request fails 401, the row is deleted, and the member must
  sign in again, re-running the server-access check and admin derivation

## ADDED Requirements

### Requirement: Sign-in methods are advertised without secrets

`GET /api/v1/auth/methods` SHALL be unauthenticated by explicit decision (the
login screen needs it before a session exists) and SHALL return only booleans for
each sign-in method: `plex` (true when `PLEX_SERVER_ID` is set or Seerr is
configured) and `seerr` (true when Seerr is configured), each also requiring
`TASTERR_SECRET_KEY`. It SHALL NOT return URLs, server ids, keys, or any other
configuration, and SHALL perform no upstream call.

#### Scenario: Methods reflect configuration

- **WHEN** only `PLEX_SERVER_ID` and the secret key are configured
- **THEN** the response is `plex: true, seerr: false`

#### Scenario: Methods carry no configuration detail

- **WHEN** every integration is configured and the response is inspected
- **THEN** it contains only method booleans and no URL, id, or secret

### Requirement: Auth degrades when no sign-in method is available

When `TASTERR_SECRET_KEY` is unset or no sign-in method is available, sign-in
endpoints SHALL return 503 with a generic "authentication unavailable" error, and
an endpoint for an unavailable method SHALL do the same. When an upstream needed
for a sign-in has an outage (transport error, timeout, or HTTP 502, 503, or 504,
as defined in `account-linking`), that sign-in SHALL fail with a generic
upstream-unavailable error that carries no upstream body or internal URL. Seerr
SHALL NOT be required for Plex sign-in when `PLEX_SERVER_ID` is set. The rest of
the app (health, SPA serving) keeps working.

#### Scenario: Auth not configured
- **WHEN** sign-in is attempted with no secret key or no available method
- **THEN** the response is 503 with a generic message and no configuration detail

#### Scenario: Plex sign-in works without Seerr
- **WHEN** `PLEX_SERVER_ID` and the secret key are set and Seerr is unconfigured
- **THEN** Plex sign-in is available and Seerr local sign-in returns 503

#### Scenario: Upstream down during sign-in
- **WHEN** plex.tv or Seerr has an outage during a sign-in that needs it
- **THEN** the client receives a generic error, and `/api/v1/health` still responds

## REMOVED Requirements

### Requirement: Auth degrades when Seerr is unavailable or unconfigured
**Reason**: Seerr is no longer required for sign-in.
**Migration**: Replaced by "Auth degrades when no sign-in method is available";
behavior is unchanged for deployments that configure only Seerr.
