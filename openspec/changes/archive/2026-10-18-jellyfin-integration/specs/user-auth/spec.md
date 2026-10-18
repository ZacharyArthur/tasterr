# user-auth Specification (delta)

## MODIFIED Requirements

### Requirement: Sign-in methods are advertised without secrets

`GET /api/v1/auth/methods` SHALL be unauthenticated by explicit decision (the
login screen needs it before a session exists) and SHALL return only booleans for
each sign-in method: `plex` (true when `PLEX_SERVER_ID` is set or Seerr is
configured), `jellyfin` (true when the Jellyfin URL and API key are set), and
`seerr` (true when Seerr is configured), each also requiring
`TASTERR_SECRET_KEY`. It SHALL NOT return URLs, server ids, keys, or any other
configuration, and SHALL perform no upstream call.

#### Scenario: Methods reflect configuration

- **WHEN** only `PLEX_SERVER_ID` and the secret key are configured
- **THEN** the response is `plex: true, jellyfin: false, seerr: false`

#### Scenario: Methods carry no configuration detail

- **WHEN** every integration is configured and the response is inspected
- **THEN** it contains only method booleans and no URL, id, or secret

### Requirement: Login endpoints are hardened
Mutating auth endpoints SHALL enforce a same-origin check (`Sec-Fetch-Site` /
`Origin`). The login-start endpoints (`/auth/plex/pin`, `/auth/local`, `/auth/jellyfin`) SHALL be
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

### Requirement: Live Seerr contract tests
A pytest-marked live suite (excluded from `just check` and CI) SHALL validate the
Seerr auth contract against a real instance: Plex token login, local login,
Jellyfin login, the status returned when a media-server login is disabled,
user/permissions shape, and the invalid-session 403 behavior — recording the
Seerr version tested.

#### Scenario: Live suite validates the contract
- **WHEN** the live-marked tests run with real Seerr coordinates configured
- **THEN** they verify the auth endpoints' behavior and record the Seerr version

#### Scenario: Default test runs skip live tests
- **WHEN** `just check` runs
- **THEN** no live-marked test executes and no network access is attempted

### Requirement: SPA login experience

The login screen SHALL offer exactly the sign-in methods `GET /api/v1/auth/methods`
reports as available, as a full-width stack of rounded pill buttons in the style
of common single-sign-on buttons, each with its service's mark as inline SVG and a
"Continue with …" label: "Continue with Plex", "Continue with Jellyfin", and
"Continue with Seerr", in that order. A method
that needs credentials SHALL expand its email/password (or, for Jellyfin, username/password) form in place when
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
Jellyfin login, successful logout, or `auth/me` resolving to a different user — the SPA SHALL invalidate
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
