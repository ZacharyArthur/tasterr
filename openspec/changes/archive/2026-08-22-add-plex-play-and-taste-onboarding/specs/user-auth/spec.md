## MODIFIED Requirements

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
Failures SHALL surface as generic, human-readable messages.

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
