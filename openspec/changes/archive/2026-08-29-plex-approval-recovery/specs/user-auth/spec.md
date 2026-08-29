## MODIFIED Requirements

### Requirement: SPA login experience

The login screen SHALL offer both paths: "Sign in with Plex" and a local
email/password form. Plex sign-in SHALL attempt to open a script-created popup
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
