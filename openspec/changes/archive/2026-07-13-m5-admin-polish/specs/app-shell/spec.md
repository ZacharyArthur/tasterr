## MODIFIED Requirements

### Requirement: SPA shell is auth-gated

The SPA SHALL resolve auth state from `GET /api/v1/auth/me` on load.
Unauthenticated visitors see the login screen; authenticated users see the routed
application shell — a navigation bar (current user, logout control, search entry
point, and an admin-only Settings entry) hosting the browse routes — rendered
through the OpenAPI-generated typed client via TanStack Query. The `/settings`
route SHALL render only after the admin settings request succeeds; hiding its link
SHALL NOT replace the backend admin gate.

#### Scenario: Unauthenticated visitor
- **WHEN** the SPA loads and `/api/v1/auth/me` returns 401
- **THEN** the login screen is shown and no authenticated content renders

#### Scenario: Authenticated user sees the routed shell
- **WHEN** the SPA loads with a valid session
- **THEN** it shows the navigation bar with the current user's display name and a
  logout control, and renders the application route matching the current URL

#### Scenario: Admin sees Settings entry
- **WHEN** the authenticated user's local identity has `is_admin=true`
- **THEN** the shell offers a Settings navigation entry that opens `/settings`

#### Scenario: Non-admin cannot open Settings
- **WHEN** a non-admin directly navigates to `/settings`
- **THEN** no settings form/data renders and the backend settings request remains
  forbidden with 403

## ADDED Requirements

### Requirement: Household appearance is constrained and applied shell-wide

The authenticated shell SHALL load the resolved appearance from `PublicConfig`
and map its allowlisted theme/accent enums to semantic CSS tokens. The selected
appearance SHALL cover shell, routes, overlays, status/error states, and form
controls with readable contrast. The SPA SHALL NOT interpolate an arbitrary API
value as CSS or persist a client-owned appearance override.

#### Scenario: Saved appearance applies without reload
- **WHEN** an admin successfully saves a different theme or accent
- **THEN** the returned/resolved appearance is applied across the authenticated
  shell without a page reload

#### Scenario: New session receives household appearance
- **WHEN** another authenticated household user opens Tasterr
- **THEN** their shell uses the same resolved global appearance

#### Scenario: Appearance remains an allowlist
- **WHEN** the shell maps a `PublicConfig` appearance
- **THEN** only known theme/accent attributes and semantic tokens are applied

### Requirement: Shell menus and feedback are keyboard and assistive-tech usable

The navbar user menu SHALL expose correct expanded/menu semantics, dismiss on
Escape and outside pointer activation, and return focus to its trigger when
dismissed. All interactive shell controls SHALL have a visible focus indicator
and an accessible name. Save, connection-test, reset, logout, and route-level
failure outcomes SHALL be expressed as visible text and announced through an
appropriate status or alert region rather than color alone.

#### Scenario: Escape dismisses user menu
- **WHEN** keyboard focus is in an open navbar user menu and Escape is pressed
- **THEN** the menu closes and focus returns to its trigger

#### Scenario: Outside activation dismisses user menu
- **WHEN** the user activates a target outside the open menu
- **THEN** the menu closes without activating a hidden menu item

#### Scenario: Async outcome is announced
- **WHEN** a shell mutation succeeds or fails
- **THEN** visible status/error text is exposed to assistive technology
